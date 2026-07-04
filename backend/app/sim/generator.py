"""Deterministic per-persona transaction stream generator.

Given a :class:`~app.sim.personas.Persona` and a seed, this module produces a
day-by-day stream of realistic Indian retail-banking transactions: salary /
pension / pocket-money credits, rent, utilities, UPI P2M/P2P, card spends with
real MCC codes, EMIs, weekend spikes, and month-end thinning for low-income
archetypes.

Two entry points:

- :func:`generate_history` -- batch-generate ``months`` of history for seed
  data / backtests.
- :func:`generate_live` -- an infinite generator yielding the same stream in
  chronological order starting at a :class:`SimClock` reference; the caller
  (``runner.py``) is responsible for real-time pacing (sleeping between
  yields under time compression) and for calling life-event ``apply()``
  scripts against the shared :class:`GeneratorState` between ``next()`` calls.

Both accept an optional external ``state``: :func:`new_state` builds one from
a persona, and life-event scripts in ``events.py`` mutate it in place. This
lets a caller do::

    state = generator.new_state(persona, seed)
    before = generator.generate_history(persona, months=3, seed=seed, state=state)
    events.job_change.apply(persona, state, start_ts=...)
    after = generator.generate_history(persona, months=3, seed=seed, state=state)

and observe the mutation's effect on the continued stream.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.sim.personas import Archetype, Persona, derived_seed

_TXN_NAMESPACE: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_DNS, "sarathi.sim.txn")

# Historical generation needs a fixed, non-"today" anchor so that
# `generate_history(persona, months, seed)` is byte-identical no matter what
# day it is actually run on.
DEFAULT_HISTORY_START: Final[date] = date(2024, 1, 1)

DISCRETIONARY_BUFFER_PAISE: Final[int] = 300_00  # ~INR 300
MANDATORY_BUFFER_PAISE: Final[int] = 0


class Direction(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class Channel(StrEnum):
    UPI = "upi"
    NEFT = "neft"
    IMPS = "imps"
    CARD = "card"
    ATM = "atm"


class Txn(BaseModel):
    """A single ledger event, ready to be wrapped in a stream envelope."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    customer_id: str
    ts: datetime
    amount_paise: int = Field(gt=0)
    direction: Direction
    channel: Channel
    merchant: str | None
    mcc: str | None
    category: str
    balance_after_paise: int = Field(ge=0)
    description: str


def to_envelope(txn: Txn) -> dict[str, Any]:
    """Wrap a :class:`Txn` in the ``txn.events`` Redis Stream envelope.

    Contract (golden keys, stable across the whole pipeline)::

        {"event_id": ..., "customer_id": ..., "type": "transaction",
         "ts": <iso8601>, "payload": {...all Txn fields, JSON-safe...}}
    """
    payload = txn.model_dump(mode="json")
    return {
        "event_id": txn.event_id,
        "customer_id": txn.customer_id,
        "type": "transaction",
        "ts": payload["ts"],
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Merchant / category reference data
# ---------------------------------------------------------------------------

MCC_GROCERY: Final[str] = "5411"
MCC_RESTAURANT: Final[str] = "5812"
MCC_TAXI: Final[str] = "4121"
MCC_PHARMACY: Final[str] = "5912"
MCC_INSURANCE: Final[str] = "6300"
MCC_ATM: Final[str] = "6011"

GROCERY_MERCHANTS: Final[list[str]] = [
    "Local Kirana Store",
    "BigBasket",
    "DMart",
    "Reliance Fresh",
    "More Supermarket",
]
FOOD_DELIVERY_MERCHANTS: Final[list[str]] = ["Swiggy", "Zomato"]
TRANSPORT_MERCHANTS: Final[list[str]] = ["Uber", "Ola", "Rapido", "Namma Metro", "Delhi Metro"]
CHAI_CANTEEN_MERCHANTS: Final[list[str]] = [
    "Chai Point",
    "Office Canteen",
    "Street Chai Stall",
    "College Canteen",
]
PHARMACY_MERCHANTS: Final[list[str]] = ["Apollo Pharmacy", "MedPlus", "Netmeds"]
INSURANCE_MERCHANTS: Final[list[str]] = ["LIC Premium", "ICICI Lombard", "HDFC Ergo"]
ELECTRICITY_BOARDS: Final[list[str]] = [
    "State Electricity Board",
    "BESCOM",
    "TSSPDCL",
    "Adani Electricity",
]
TELECOM_PROVIDERS: Final[list[str]] = ["Jio", "Airtel", "Vi"]
BROADBAND_PROVIDERS: Final[list[str]] = ["ACT Fibernet", "Airtel Xstream", "JioFiber"]
BABY_STORE_MERCHANTS: Final[list[str]] = ["FirstCry", "Mothercare", "BabyChakra"]
WEDDING_MERCHANTS: Final[dict[str, list[str]]] = {
    "wedding_catering": ["Royal Caterers", "Shubh Catering Services"],
    "jewellery": ["Tanishq", "Kalyan Jewellers", "Malabar Gold"],
    "venue_booking": ["Grand Palace Banquets", "Sunshine Convention Centre"],
}

_LOW_INCOME_ARCHETYPES: Final[set[Archetype]] = {
    Archetype.STUDENT,
    Archetype.GIG_WORKER,
    Archetype.HOMEMAKER,
}

_BASE_DAILY_PROB: Final[dict[str, float]] = {
    "groceries": 0.18,
    "food_delivery": 0.22,
    "transport": 0.35,
    "chai_canteen": 0.30,
    "p2p": 0.12,
    "atm": 0.03,
    "pharmacy": 0.02,
}
_BASE_AMOUNT_RANGE_PAISE: Final[dict[str, tuple[int, int]]] = {
    "groceries": (150_00, 800_00),
    "food_delivery": (120_00, 450_00),
    "transport": (25_00, 250_00),
    "chai_canteen": (10_00, 80_00),
    "p2p": (100_00, 3_000_00),
    "atm": (500_00, 5_000_00),
    "pharmacy": (100_00, 900_00),
}
_ARCHETYPE_SPEND_MULT: Final[dict[Archetype, float]] = {
    Archetype.YOUNG_SALARIED_TECHIE: 1.3,
    Archetype.GIG_WORKER: 0.8,
    Archetype.SMALL_BUSINESS_OWNER: 1.0,
    Archetype.STUDENT: 0.5,
    Archetype.HOMEMAKER: 0.9,
    Archetype.RETIREE: 0.6,
}

_ATM_NOTE_DENOMINATIONS: Final[list[int]] = [500_00, 1_000_00, 2_000_00, 5_000_00]

# Time-of-day windows (hour_start, hour_end), keyed by the *actual* ledger
# `category` string each transaction is emitted with -- this must stay in
# sync with every literal passed as `category=` below. A category missing
# here silently falls back to the (8, 20) default in `_time_for`, which is
# fine for minor ones but would be wrong for e.g. salary (must be a.m.).
_TIME_WINDOWS: Final[dict[str, tuple[int, int]]] = {
    "salary": (6, 9),
    "pension": (6, 9),
    "pocket_money": (7, 11),
    "household_allowance": (7, 11),
    "business_inflow": (9, 20),
    "gig_payout": (7, 22),
    "fd_interest": (9, 17),
    "gst_payment": (9, 18),
    "rent": (9, 18),
    "electricity": (9, 20),
    "mobile_recharge": (9, 21),
    "broadband": (9, 20),
    "emi": (6, 10),
    "home_loan_emi": (6, 10),
    "insurance": (9, 18),
    "groceries": (10, 21),
    "food_delivery": (12, 22),
    "transport": (7, 22),
    "chai_canteen": (8, 19),
    "pharmacy": (9, 21),
    "p2p_transfer": (8, 23),
    "card_spend": (10, 21),
    "cash_withdrawal": (9, 21),
    "baby_essentials": (10, 20),
    "school_fees": (9, 17),
    "builder_payment": (10, 18),
    "bonus": (9, 17),
    "wedding_catering": (10, 20),
    "jewellery": (10, 20),
    "venue_booking": (10, 20),
    "balance_drain": (0, 23),
    # Funding credits paired with a same-day big-ticket debit (home purchase,
    # wedding): pinned to an earlier, non-overlapping window than every debit
    # category above so `finalize()`'s ts-ordered pass always applies the
    # credit first and the debit's overdraft-guard check succeeds.
    "home_purchase_funding": (5, 6),
    "wedding_funding": (5, 6),
}


# ---------------------------------------------------------------------------
# Generator state (mutated in place by app.sim.events life scripts)
# ---------------------------------------------------------------------------


@dataclass
class EMI:
    label: str
    amount_paise: int
    day_of_month: int
    category: str = "emi"
    start_after: date | None = None


@dataclass
class ScheduledAmount:
    on_date: date
    amount_paise: int
    description: str
    category: str
    channel: Channel
    merchant: str | None = None
    # Explicit clock time override. Life-event scripts that pair a same-day
    # funding credit with a big-ticket debit (home purchase, wedding) set
    # this so the pair lands at deterministically adjacent instants --
    # relying on each side's independently-drawn category time window would
    # leave a wide gap an unrelated same-day debit could land in, draining
    # the "reserved" funding before the paired debit is applied and causing
    # it to be silently skipped by the overdraft guard.
    time_of_day: time | None = None


@dataclass
class GeneratorState:
    """Mutable, per-persona generation state.

    This is the seam life-event scripts (``app.sim.events``) mutate: bumping
    ``monthly_income_paise`` after a job change, adding ``scheduled_debits``
    for a wedding, decaying ``upi_activity_factor`` for churn risk, etc.
    """

    persona_id: str
    seed: int
    balance_paise: int
    seq: int = 0
    monthly_income_paise: int = 0
    income_label: str = "Salary"
    income_source_name: str = ""
    is_renter: bool = False
    monthly_rent_paise: int = 0
    landlord_name: str = ""
    emis: list[EMI] = field(default_factory=list)
    scheduled_credits: list[ScheduledAmount] = field(default_factory=list)
    scheduled_debits: list[ScheduledAmount] = field(default_factory=list)
    # category -> (multiplier, expires_on)
    category_multipliers: dict[str, tuple[float, date]] = field(default_factory=dict)
    upi_activity_factor: float = 1.0
    salary_skip_cycles: int = 0
    churn_decay_start: date | None = None
    churn_drain_vpa: str | None = None
    churn_drain_date: date | None = None
    churn_drain_fraction: float = 0.0
    last_generated_date: date | None = None


def _income_profile(persona: Persona) -> tuple[str, str]:
    """Return (income_label, income_source_name) for a fresh persona."""
    if persona.archetype == Archetype.YOUNG_SALARIED_TECHIE:
        return "Salary", persona.employer or "Employer"
    if persona.archetype == Archetype.GIG_WORKER:
        return "Payout", persona.employer or "Gig Platform"
    if persona.archetype == Archetype.SMALL_BUSINESS_OWNER:
        return "Business Inflow", persona.employer or "Business"
    if persona.archetype == Archetype.STUDENT:
        return "Pocket Money", "Parent"
    if persona.archetype == Archetype.HOMEMAKER:
        return "Household Allowance", "Spouse"
    return "Pension", persona.employer or "Pension Account"


def _initial_balance_paise(persona: Persona) -> int:
    rng = random.Random(derived_seed(persona.id, "initial_balance"))
    if persona.archetype in (Archetype.STUDENT, Archetype.HOMEMAKER):
        multiplier = rng.uniform(0.3, 0.8)
    elif persona.archetype == Archetype.GIG_WORKER:
        multiplier = rng.uniform(0.4, 1.0)
    else:
        multiplier = rng.uniform(0.6, 2.0)
    return max(500_00, int(persona.monthly_income_paise * multiplier))


def new_state(persona: Persona, seed: int, start_date: date | None = None) -> GeneratorState:
    """Build a fresh :class:`GeneratorState` seeded from ``persona``."""
    label, source = _income_profile(persona)
    rng = random.Random(derived_seed(seed, persona.id, "landlord"))
    landlord = f"{rng.choice(['Sharma', 'Reddy', 'Nair', 'Iyer', 'Khan', 'Patel'])} Properties"
    emis: list[EMI] = []
    if persona.emi_paise > 0:
        emis.append(EMI(label="Personal Loan EMI", amount_paise=persona.emi_paise, day_of_month=7))
    return GeneratorState(
        persona_id=persona.id,
        seed=seed,
        balance_paise=_initial_balance_paise(persona),
        monthly_income_paise=persona.monthly_income_paise,
        income_label=label,
        income_source_name=source,
        is_renter=persona.is_renter,
        monthly_rent_paise=persona.monthly_rent_paise,
        landlord_name=landlord,
        emis=emis,
        last_generated_date=(start_date - timedelta(days=1)) if start_date else None,
    )


@dataclass(frozen=True)
class SimClock:
    """Reference point for live (real-time-compressed) generation."""

    sim_start: datetime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _monthly_offset_date(
    seed: int, persona_id: str, year: int, month: int, tag: str, offset_range: tuple[int, int]
) -> date:
    """Deterministic day near the 1st of (year, month), offset by `tag`.

    Clamped to stay within (year, month) -- never rolls into the previous
    month. The day-loop only ever evaluates this anchor while iterating days
    tagged with this exact (year, month), so an anchor that rolled backward
    (e.g. "1st - 2 days" landing on Jan 30 for a February anchor) would
    silently never be reached and the monthly event would be skipped for
    that month entirely.
    """
    rng = random.Random(derived_seed(seed, persona_id, year, month, tag))
    offset = rng.randint(*offset_range)
    day_num = max(1, 1 + offset)
    return date(year, month, day_num)


def _monthly_day(
    seed: int, persona_id: str, year: int, month: int, tag: str, low: int, high: int
) -> int:
    """Deterministic day-of-month in [low, high] for a recurring monthly event."""
    rng = random.Random(derived_seed(seed, persona_id, year, month, tag))
    import calendar

    days_in_month = calendar.monthrange(year, month)[1]
    return rng.randint(low, min(high, days_in_month))


def _time_for(category: str, rng: random.Random) -> time:
    start_h, end_h = _TIME_WINDOWS.get(category, (8, 20))
    hour = rng.randint(start_h, max(start_h, end_h - 1))
    minute = rng.randint(0, 59)
    return time(hour=hour, minute=minute)


def _try_debit(state: GeneratorState, amount_paise: int, buffer_paise: int) -> bool:
    if state.balance_paise - amount_paise < buffer_paise:
        return False
    state.balance_paise -= amount_paise
    return True


def _credit(state: GeneratorState, amount_paise: int) -> None:
    state.balance_paise += amount_paise


def _category_multiplier(state: GeneratorState, category: str, day: date) -> float:
    entry = state.category_multipliers.get(category)
    if entry is None:
        return 1.0
    multiplier, expires_on = entry
    return multiplier if day <= expires_on else 1.0


def _upi_factor(state: GeneratorState, day: date) -> float:
    if state.churn_decay_start is None:
        return state.upi_activity_factor
    days_elapsed = (day - state.churn_decay_start).days
    if days_elapsed < 0:
        return state.upi_activity_factor
    return max(0.05, state.upi_activity_factor * (1.0 - days_elapsed / 45.0))


@dataclass
class _Proposal:
    """A candidate transaction for the day, not yet applied to the balance.

    Amount can be fixed (``amount_paise``) or computed lazily at finalize
    time as a fraction of whatever the running balance is at that point in
    chronological order (``amount_fraction_of_balance`` -- used by the
    churn-risk balance drain, whose size depends on the balance *at the
    moment of transfer*, not the balance at the start of the day).
    """

    direction: Direction
    channel: Channel
    category: str
    merchant: str | None
    mcc: str | None
    description: str
    ts: datetime
    buffer_paise: int
    amount_paise: int | None = None
    amount_fraction_of_balance: float | None = None


class _DayEmitter:
    """Collects proposed transactions for a single day, then applies them
    to the shared balance in chronological (``ts``) order.

    Proposals are generated in a fixed code order (income, rent, utilities,
    discretionary, ...) which does *not* match real time-of-day order (e.g.
    a salary credit posted at 07:00 must be applied before a grocery UPI
    debit at 11:00, even though grocery spend is decided later in code).
    Applying balance mutations at proposal time -- keyed to emission order
    instead of ``ts`` order -- would make ``balance_after_paise`` internally
    inconsistent once the day's transactions are sorted for output. Instead,
    every generation function only *proposes*; :meth:`finalize` sorts by
    ``ts`` and only then debits/credits the running balance, so the
    overdraft guard and every ``balance_after_paise`` reflect true
    chronological order.
    """

    def __init__(self, persona: Persona, state: GeneratorState, day: date, seed: int) -> None:
        self.persona = persona
        self.state = state
        self.day = day
        self.seed = seed
        self.proposals: list[_Proposal] = []

    def propose(
        self,
        *,
        direction: Direction,
        channel: Channel,
        category: str,
        merchant: str | None,
        mcc: str | None,
        description: str,
        rng: random.Random,
        amount_paise: int | None = None,
        amount_fraction_of_balance: float | None = None,
        buffer_paise: int = 0,
        forced_time: time | None = None,
    ) -> None:
        if amount_paise is None and amount_fraction_of_balance is None:
            return
        if amount_paise is not None and amount_paise <= 0:
            return
        ts = datetime.combine(
            self.day, forced_time if forced_time is not None else _time_for(category, rng)
        )
        self.proposals.append(
            _Proposal(
                direction=direction,
                channel=channel,
                category=category,
                merchant=merchant,
                mcc=mcc,
                description=description,
                ts=ts,
                buffer_paise=buffer_paise,
                amount_paise=amount_paise,
                amount_fraction_of_balance=amount_fraction_of_balance,
            )
        )

    def finalize(self) -> list[Txn]:
        state = self.state
        txns: list[Txn] = []
        for p in sorted(self.proposals, key=lambda x: x.ts):
            amount = p.amount_paise
            if amount is None and p.amount_fraction_of_balance is not None:
                amount = int(state.balance_paise * p.amount_fraction_of_balance)
            if amount is None or amount <= 0:
                continue
            if p.direction is Direction.DEBIT:
                if not _try_debit(state, amount, p.buffer_paise):
                    continue
            else:
                _credit(state, amount)
            state.seq += 1
            event_id = str(uuid.uuid5(_TXN_NAMESPACE, f"{self.persona.id}:{self.seed}:{state.seq}"))
            txns.append(
                Txn(
                    event_id=event_id,
                    customer_id=self.persona.id,
                    ts=p.ts,
                    amount_paise=amount,
                    direction=p.direction,
                    channel=p.channel,
                    merchant=p.merchant,
                    mcc=p.mcc,
                    category=p.category,
                    balance_after_paise=state.balance_paise,
                    description=p.description,
                )
            )
        return txns


def _generate_scheduled(emitter: _DayEmitter, rng: random.Random) -> None:
    state = emitter.state
    day = emitter.day
    due_credits = [s for s in state.scheduled_credits if s.on_date <= day]
    for s in due_credits:
        state.scheduled_credits.remove(s)
        emitter.propose(
            direction=Direction.CREDIT,
            channel=s.channel,
            amount_paise=s.amount_paise,
            category=s.category,
            merchant=s.merchant,
            mcc=None,
            description=s.description,
            rng=rng,
            forced_time=s.time_of_day,
        )
    due_debits = [s for s in state.scheduled_debits if s.on_date <= day]
    for s in due_debits:
        state.scheduled_debits.remove(s)
        emitter.propose(
            direction=Direction.DEBIT,
            channel=s.channel,
            amount_paise=s.amount_paise,
            category=s.category,
            merchant=s.merchant,
            mcc=None,
            description=s.description,
            rng=rng,
            buffer_paise=0,
            forced_time=s.time_of_day,
        )
    if state.churn_drain_date == day and state.churn_drain_vpa:
        # Fraction-of-balance, resolved at finalize() time in chronological
        # order -- the drain should take a cut of whatever balance actually
        # exists at the moment of transfer, not the balance at day-start.
        emitter.propose(
            direction=Direction.DEBIT,
            channel=Channel.UPI,
            amount_fraction_of_balance=state.churn_drain_fraction,
            category="balance_drain",
            merchant=state.churn_drain_vpa,
            mcc=None,
            description=f"UPI transfer to {state.churn_drain_vpa}",
            rng=rng,
        )
        state.churn_drain_date = None


def _generate_income(emitter: _DayEmitter, rng: random.Random) -> None:
    persona, state, day = emitter.persona, emitter.state, emitter.day
    if persona.archetype == Archetype.GIG_WORKER:
        # Irregular daily credits rather than a single monthly salary.
        if rng.random() < 0.85 * _upi_factor(state, day):
            amount = int(state.monthly_income_paise / 26 * rng.uniform(0.5, 1.6))
            emitter.propose(
                direction=Direction.CREDIT,
                channel=Channel.UPI,
                amount_paise=max(amount, 100_00),
                category="gig_payout",
                merchant=state.income_source_name,
                mcc=None,
                description=f"{state.income_source_name} payout",
                rng=rng,
            )
        return
    if persona.archetype == Archetype.SMALL_BUSINESS_OWNER:
        # Lumpy business inflows through the week instead of one salary date.
        if rng.random() < 0.35:
            amount = int(state.monthly_income_paise / 12 * rng.uniform(0.4, 2.2))
            emitter.propose(
                direction=Direction.CREDIT,
                channel=rng.choice([Channel.UPI, Channel.IMPS]),
                amount_paise=max(amount, 200_00),
                category="business_inflow",
                merchant="Customer Receipts",
                mcc=None,
                description="Business sale receipts",
                rng=rng,
            )
        # Monthly GST payment around the 18th-20th.
        gst_day = _monthly_day(emitter.seed, persona.id, day.year, day.month, "gst", 18, 20)
        if day.day == gst_day:
            gst_amount = int(state.monthly_income_paise * rng.uniform(0.05, 0.15))
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.NEFT,
                amount_paise=gst_amount,
                category="gst_payment",
                merchant="GSTN",
                mcc=None,
                description="GST payment",
                rng=rng,
                buffer_paise=MANDATORY_BUFFER_PAISE,
            )
        return

    # Salaried / pension / pocket-money / allowance: single monthly credit.
    offset_range = (-2, 2)
    pay_date = _monthly_offset_date(
        emitter.seed, persona.id, day.year, day.month, "income", offset_range
    )
    if day != pay_date:
        return
    if state.salary_skip_cycles > 0:
        state.salary_skip_cycles -= 1
        return
    variance = (
        rng.uniform(0.97, 1.03)
        if persona.archetype != Archetype.HOMEMAKER
        else rng.uniform(0.9, 1.1)
    )
    amount = int(state.monthly_income_paise * variance)
    emitter.propose(
        direction=Direction.CREDIT,
        channel=Channel.NEFT,
        amount_paise=amount,
        category="salary"
        if state.income_label == "Salary"
        else state.income_label.lower().replace(" ", "_"),
        merchant=state.income_source_name,
        mcc=None,
        description=f"{state.income_label} credit from {state.income_source_name}",
        rng=rng,
    )
    # Retirees additionally get quarterly FD interest.
    if persona.archetype == Archetype.RETIREE and day.month in (3, 6, 9, 12):
        fd_amount = int(state.monthly_income_paise * rng.uniform(0.1, 0.3))
        emitter.propose(
            direction=Direction.CREDIT,
            channel=Channel.NEFT,
            amount_paise=fd_amount,
            category="fd_interest",
            merchant="Fixed Deposit",
            mcc=None,
            description="FD interest credit",
            rng=rng,
        )


def _generate_rent(emitter: _DayEmitter, rng: random.Random) -> None:
    state, day = emitter.state, emitter.day
    if not state.is_renter or state.monthly_rent_paise <= 0:
        return
    rent_date = _monthly_offset_date(
        emitter.seed, emitter.persona.id, day.year, day.month, "rent", (1, 4)
    )
    if day != rent_date:
        return
    emitter.propose(
        direction=Direction.DEBIT,
        channel=Channel.IMPS,
        amount_paise=state.monthly_rent_paise,
        category="rent",
        merchant=state.landlord_name,
        mcc=None,
        description=f"Rent to {state.landlord_name}",
        rng=rng,
        buffer_paise=MANDATORY_BUFFER_PAISE,
    )


def _generate_utilities(emitter: _DayEmitter, rng: random.Random) -> None:
    persona, day = emitter.persona, emitter.day
    seed, pid = emitter.seed, persona.id

    elec_day = _monthly_day(seed, pid, day.year, day.month, "electricity", 5, 25)
    if day.day == elec_day:
        rng2 = random.Random(derived_seed(seed, pid, "electricity", day.isoformat()))
        emitter.propose(
            direction=Direction.DEBIT,
            channel=Channel.UPI if persona.upi_active else Channel.NEFT,
            amount_paise=int(
                rng2.randint(300, 3500) * 100 * _ARCHETYPE_SPEND_MULT.get(persona.archetype, 1.0)
            ),
            category="electricity",
            merchant=rng2.choice(ELECTRICITY_BOARDS),
            mcc=None,
            description="Electricity bill payment",
            rng=rng2,
            buffer_paise=MANDATORY_BUFFER_PAISE,
        )

    if persona.upi_active:
        mobile_day = _monthly_day(seed, pid, day.year, day.month, "mobile", 25, 28)
        if day.day == mobile_day:
            rng3 = random.Random(derived_seed(seed, pid, "mobile", day.isoformat()))
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=rng3.randint(149, 999) * 100,
                category="mobile_recharge",
                merchant=rng3.choice(TELECOM_PROVIDERS),
                mcc=None,
                description="Mobile recharge",
                rng=rng3,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )

    if persona.archetype in (
        Archetype.YOUNG_SALARIED_TECHIE,
        Archetype.SMALL_BUSINESS_OWNER,
        Archetype.HOMEMAKER,
    ):
        bb_day = _monthly_day(seed, pid, day.year, day.month, "broadband", 1, 10)
        if day.day == bb_day:
            rng4 = random.Random(derived_seed(seed, pid, "broadband", day.isoformat()))
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=rng4.randint(599, 1999) * 100,
                category="broadband",
                merchant=rng4.choice(BROADBAND_PROVIDERS),
                mcc=None,
                description="Broadband bill payment",
                rng=rng4,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )


def _generate_emis(emitter: _DayEmitter, rng: random.Random) -> None:
    state, day = emitter.state, emitter.day
    for emi in state.emis:
        if emi.start_after is not None and day < emi.start_after:
            continue
        if day.day != emi.day_of_month:
            continue
        emitter.propose(
            direction=Direction.DEBIT,
            channel=Channel.NEFT,
            amount_paise=emi.amount_paise,
            category=emi.category,
            merchant="Loan Auto-Debit",
            mcc=None,
            description=emi.label,
            rng=rng,
            buffer_paise=MANDATORY_BUFFER_PAISE,
        )


def _generate_insurance(emitter: _DayEmitter, rng: random.Random) -> None:
    persona, day = emitter.persona, emitter.day
    has_insurance = any(
        p in persona.products_held for p in ("term_insurance", "personal_accident_cover")
    )
    if not has_insurance:
        return
    prem_day = _monthly_day(emitter.seed, persona.id, day.year, day.month, "insurance", 1, 10)
    if day.day != prem_day or day.month % 3 != 0:  # quarterly premium
        return
    rng2 = random.Random(derived_seed(emitter.seed, persona.id, "insurance", day.isoformat()))
    emitter.propose(
        direction=Direction.DEBIT,
        channel=Channel.CARD,
        amount_paise=rng2.randint(800, 6000) * 100,
        category="insurance",
        merchant=rng2.choice(INSURANCE_MERCHANTS),
        mcc=MCC_INSURANCE,
        description="Insurance premium",
        rng=rng2,
        buffer_paise=MANDATORY_BUFFER_PAISE,
    )


def _spend_probability(persona: Persona, state: GeneratorState, day: date, category: str) -> float:
    base = _BASE_DAILY_PROB[category]
    mult = _ARCHETYPE_SPEND_MULT.get(persona.archetype, 1.0)
    weekend_boost = (
        1.6
        if day.weekday() >= 4 and category in ("food_delivery", "chai_canteen", "transport")
        else 1.0
    )
    is_month_end = day.day >= 25
    thinning = 0.4 if (is_month_end and persona.archetype in _LOW_INCOME_ARCHETYPES) else 1.0
    upi_factor = _upi_factor(state, day) if category != "atm" else 1.0
    maturity_factor = (
        0.5 + persona.digital_maturity if category != "atm" else 1.5 - persona.digital_maturity
    )
    return base * mult * weekend_boost * thinning * upi_factor * maturity_factor


def _generate_discretionary(emitter: _DayEmitter, rng: random.Random) -> None:
    """UPI/card/cash discretionary spend.

    Only the UPI-channel categories (groceries-via-UPI, food delivery,
    transport, chai/canteen, pharmacy, P2P) require ``upi_active`` -- a
    non-UPI customer still buys groceries and withdraws cash, they just do
    it in a way the bank's ledger can't see the retail detail of (which is
    itself a realistic "thin digital footprint" signal for the low-digital-
    maturity archetypes). Card spend and ATM withdrawals must stay reachable
    regardless of UPI adoption, or those personas would show zero spend at
    all -- clearly wrong for a small-business owner or retiree with a
    pension credit and no visible cost of living.
    """
    persona, state, day = emitter.persona, emitter.state, emitter.day

    def _amount(category: str) -> int:
        lo, hi = _BASE_AMOUNT_RANGE_PAISE[category]
        base = rng.randint(lo, hi)
        return int(base * _category_multiplier(state, category, day))

    if persona.upi_active:
        if rng.random() < _spend_probability(persona, state, day, "groceries"):
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=_amount("groceries"),
                category="groceries",
                merchant=rng.choice(GROCERY_MERCHANTS),
                mcc=MCC_GROCERY,
                description="UPI payment - groceries",
                rng=rng,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )
        if rng.random() < _spend_probability(persona, state, day, "food_delivery"):
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=_amount("food_delivery"),
                category="food_delivery",
                merchant=rng.choice(FOOD_DELIVERY_MERCHANTS),
                mcc=MCC_RESTAURANT,
                description="UPI payment - food delivery",
                rng=rng,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )
        if rng.random() < _spend_probability(persona, state, day, "transport"):
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=_amount("transport"),
                category="transport",
                merchant=rng.choice(TRANSPORT_MERCHANTS),
                mcc=MCC_TAXI,
                description="UPI payment - transport",
                rng=rng,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )
        if rng.random() < _spend_probability(persona, state, day, "chai_canteen"):
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=_amount("chai_canteen"),
                category="chai_canteen",
                merchant=rng.choice(CHAI_CANTEEN_MERCHANTS),
                mcc=None,
                description="UPI payment - chai/canteen",
                rng=rng,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )
        if rng.random() < _spend_probability(persona, state, day, "pharmacy"):
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=_amount("pharmacy"),
                category="pharmacy",
                merchant=rng.choice(PHARMACY_MERCHANTS),
                mcc=MCC_PHARMACY,
                description="UPI payment - pharmacy",
                rng=rng,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )
        if rng.random() < _spend_probability(persona, state, day, "p2p"):
            emitter.propose(
                direction=Direction.DEBIT,
                channel=Channel.UPI,
                amount_paise=_amount("p2p"),
                category="p2p_transfer",
                merchant="Friend/Family VPA",
                mcc=None,
                description="UPI P2P transfer",
                rng=rng,
                buffer_paise=DISCRETIONARY_BUFFER_PAISE,
            )

    has_card = (
        "credit_card" in persona.products_held
        or persona.archetype == Archetype.SMALL_BUSINESS_OWNER
    )
    if has_card and rng.random() < 0.1 * _ARCHETYPE_SPEND_MULT.get(persona.archetype, 1.0):
        emitter.propose(
            direction=Direction.DEBIT,
            channel=Channel.CARD,
            amount_paise=_amount("groceries"),
            category="card_spend",
            merchant=rng.choice(GROCERY_MERCHANTS + FOOD_DELIVERY_MERCHANTS),
            mcc=rng.choice([MCC_GROCERY, MCC_RESTAURANT]),
            description="Card spend",
            rng=rng,
            buffer_paise=DISCRETIONARY_BUFFER_PAISE,
        )

    # Non-UPI customers draw cash more often -- it is their main way of
    # funding day-to-day spend that the UPI branch above never generated.
    atm_prob = _spend_probability(persona, state, day, "atm")
    if not persona.upi_active:
        atm_prob *= 2.5
    if rng.random() < atm_prob:
        emitter.propose(
            direction=Direction.DEBIT,
            channel=Channel.ATM,
            amount_paise=rng.choice(_ATM_NOTE_DENOMINATIONS),
            category="cash_withdrawal",
            merchant="ATM",
            mcc=MCC_ATM,
            description="ATM cash withdrawal",
            rng=rng,
            buffer_paise=DISCRETIONARY_BUFFER_PAISE,
        )


def _generate_day(persona: Persona, state: GeneratorState, day: date, seed: int) -> list[Txn]:
    emitter = _DayEmitter(persona, state, day, seed)
    day_rng = random.Random(derived_seed(seed, persona.id, day.isoformat()))
    _generate_scheduled(emitter, day_rng)
    _generate_income(emitter, day_rng)
    _generate_rent(emitter, day_rng)
    _generate_utilities(emitter, day_rng)
    _generate_emis(emitter, day_rng)
    _generate_insurance(emitter, day_rng)
    _generate_discretionary(emitter, day_rng)
    txns = emitter.finalize()
    state.last_generated_date = day
    return txns


def generate_history(
    persona: Persona,
    months: int,
    seed: int,
    *,
    state: GeneratorState | None = None,
    start_date: date | None = None,
) -> list[Txn]:
    """Deterministically generate ``months`` of daily transactions.

    If ``state`` is omitted a fresh one is created via :func:`new_state`. If
    provided, generation continues from ``state.last_generated_date + 1`` (or
    ``start_date`` if given), letting callers chain segments around life
    events applied to the same state object.
    """
    if state is None:
        state = new_state(persona, seed, start_date=start_date)
    if start_date is None:
        start_date = (
            state.last_generated_date + timedelta(days=1)
            if state.last_generated_date
            else DEFAULT_HISTORY_START
        )
    end_date = start_date + timedelta(days=months * 30)
    txns: list[Txn] = []
    day = start_date
    while day < end_date:
        txns.extend(_generate_day(persona, state, day, seed))
        day += timedelta(days=1)
    txns.sort(key=lambda t: t.ts)
    return txns


def generate_live(
    persona: Persona,
    sim_clock: SimClock,
    seed: int,
    *,
    state: GeneratorState | None = None,
) -> Iterator[Txn]:
    """Infinite generator of ``persona``'s future transactions, chronological.

    Starts at ``sim_clock.sim_start`` and generates one simulated day at a
    time (lazily, so this never precomputes an unbounded future). The caller
    owns real-time pacing: pull `next()`, sleep until the compressed real
    time matching ``txn.ts`` elapses, publish, repeat. Because ``state`` is
    accepted by reference, a caller running concurrently can mutate it (via
    ``app.sim.events`` life-event scripts) between `next()` calls and see the
    effect on subsequently generated days.
    """
    if state is None:
        state = new_state(persona, seed, start_date=sim_clock.sim_start.date())
    day_offset = 0
    while True:
        day = sim_clock.sim_start.date() + timedelta(days=day_offset)
        yield from _generate_day(persona, state, day, seed)
        day_offset += 1
