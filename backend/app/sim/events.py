"""Life-event scripts.

Each script mutates a persona's *subsequent* transaction stream by editing
its shared :class:`~app.sim.generator.GeneratorState` in place -- job changes
raise income, weddings add spend spikes, churn risk decays UPI activity to
near-zero, etc. Every script also emits a :class:`GroundTruthEvent`, the
label future detection agents will be graded against.

Usage::

    state = generator.new_state(persona, seed)
    generator.generate_history(persona, months=3, seed=seed, state=state)
    gt = job_change.apply(persona, state, start_ts=some_datetime)
    generator.generate_history(persona, months=3, seed=seed, state=state)

``apply()`` also updates the descriptive fields on ``persona`` itself (new
employer, no-longer-a-renter, etc.) so that anything reading the persona
record directly (e.g. the console UI) stays in sync with the mutated stream.
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel

from app.sim.generator import (
    BABY_STORE_MERCHANTS,
    EMI,
    WEDDING_MERCHANTS,
    Channel,
    GeneratorState,
    ScheduledAmount,
)
from app.sim.personas import (
    GIG_PLATFORMS,
    RETIREE_FORMER_EMPLOYERS,
    SMALL_BIZ_TYPES,
    TECH_EMPLOYERS,
    Archetype,
    Persona,
    derived_seed,
)


class LifeEventType(StrEnum):
    JOB_CHANGE = "job_change"
    NEW_CHILD = "new_child"
    HOME_PURCHASE_INTENT = "home_purchase_intent"
    BONUS_WINDFALL = "bonus_windfall"
    WEDDING = "wedding"
    CHURN_RISK = "churn_risk"


class GroundTruthEvent(BaseModel):
    """Judging label: what really happened to this persona's stream, and when."""

    customer_id: str
    type: LifeEventType
    start_ts: datetime
    params: dict[str, Any]


class LifeEventScript(Protocol):
    def apply(
        self, persona: Persona, state: GeneratorState, start_ts: datetime
    ) -> GroundTruthEvent: ...


def _rng_for(
    state: GeneratorState, persona: Persona, tag: str, start_ts: datetime
) -> random.Random:
    return random.Random(derived_seed(state.seed, persona.id, tag, start_ts.isoformat()))


def _funding_pair_times(rng: random.Random) -> tuple[time, time]:
    """(credit_time, debit_time) for a same-day funding-credit + big-debit
    pair, with the debit strictly and closely after the credit.

    Both land in the early hours -- before any organic discretionary spend
    for the day is generated -- so nothing can wedge between the credit
    landing and the debit consuming it. Relying on each side's normal,
    wide category time window (independently random) left enough of a gap
    for an unrelated same-day debit to drain the "reserved" funding first,
    silently failing the paired big-ticket debit's overdraft guard check.
    """
    credit_minute = rng.randint(0, 30)
    return time(hour=5, minute=credit_minute), time(hour=5, minute=credit_minute + 1)


class _JobChange:
    """New job: salary jumps 30-60%, one skipped pay cycle for the gap."""

    def apply(
        self, persona: Persona, state: GeneratorState, start_ts: datetime
    ) -> GroundTruthEvent:
        rng = _rng_for(state, persona, "job_change", start_ts)
        growth_factor = round(rng.uniform(1.3, 1.6), 3)
        previous_income = state.monthly_income_paise
        previous_employer = state.income_source_name
        new_income = int(previous_income * growth_factor)

        if persona.archetype == Archetype.YOUNG_SALARIED_TECHIE:
            pool = [e for e in TECH_EMPLOYERS if e != previous_employer] or TECH_EMPLOYERS
            new_employer = rng.choice(pool)
        elif persona.archetype == Archetype.GIG_WORKER:
            pool = [e for e in GIG_PLATFORMS if e != previous_employer] or GIG_PLATFORMS
            new_employer = rng.choice(pool)
        elif persona.archetype == Archetype.RETIREE:
            pool = [
                e for e in RETIREE_FORMER_EMPLOYERS if e != previous_employer
            ] or RETIREE_FORMER_EMPLOYERS
            new_employer = rng.choice(pool)
        elif persona.archetype == Archetype.SMALL_BUSINESS_OWNER:
            new_employer = f"{persona.name.split()[-1]} {rng.choice(SMALL_BIZ_TYPES)}"
        else:
            new_employer = f"New Employer ({rng.randint(1, 999)})"

        state.monthly_income_paise = new_income
        state.income_label = "Salary"
        state.income_source_name = new_employer
        state.salary_skip_cycles = max(state.salary_skip_cycles, 1)

        persona.employer = new_employer
        persona.monthly_income_paise = new_income

        return GroundTruthEvent(
            customer_id=persona.id,
            type=LifeEventType.JOB_CHANGE,
            start_ts=start_ts,
            params={
                "previous_income_paise": previous_income,
                "new_income_paise": new_income,
                "previous_employer": previous_employer,
                "new_employer": new_employer,
                "growth_factor": growth_factor,
            },
        )


class _NewChild:
    """New baby: pharmacy/baby-store spend ramps for ~6mo, school fees later."""

    def apply(
        self, persona: Persona, state: GeneratorState, start_ts: datetime
    ) -> GroundTruthEvent:
        rng = _rng_for(state, persona, "new_child", start_ts)
        ramp_days = 180
        expires_on = start_ts.date() + timedelta(days=ramp_days)
        state.category_multipliers["pharmacy"] = (3.5, expires_on)

        num_purchases = rng.randint(2, 4)
        for _ in range(num_purchases):
            purchase_date = start_ts.date() + timedelta(days=rng.randint(0, 60))
            state.scheduled_debits.append(
                ScheduledAmount(
                    on_date=purchase_date,
                    amount_paise=rng.randint(3_000, 8_000) * 100,
                    description="Baby essentials purchase",
                    category="baby_essentials",
                    channel=Channel.UPI,
                    merchant=rng.choice(BABY_STORE_MERCHANTS),
                )
            )

        school_fee_date = start_ts.date() + timedelta(days=365 * 5)
        state.scheduled_debits.append(
            ScheduledAmount(
                on_date=school_fee_date,
                amount_paise=rng.randint(15_000, 40_000) * 100,
                description="School admission fees",
                category="school_fees",
                channel=Channel.NEFT,
                merchant="School",
            )
        )

        persona.dependents += 1
        family = dict(persona.family)
        children = list(family.get("children", []))
        children.append({"relation": "child", "age": 0})
        family["children"] = children
        family["dependents"] = persona.dependents
        persona.family = family

        return GroundTruthEvent(
            customer_id=persona.id,
            type=LifeEventType.NEW_CHILD,
            start_ts=start_ts,
            params={"ramp_days": ramp_days, "school_fee_date": school_fee_date.isoformat()},
        )


class _HomePurchaseIntent:
    """Buying a home: rent stops, builder debits, a home-loan EMI appears."""

    def apply(
        self, persona: Persona, state: GeneratorState, start_ts: datetime
    ) -> GroundTruthEvent:
        rng = _rng_for(state, persona, "home_purchase_intent", start_ts)
        previous_rent = state.monthly_rent_paise
        state.is_renter = False
        state.monthly_rent_paise = 0
        persona.is_renter = False
        persona.monthly_rent_paise = 0

        down_payment_total = state.monthly_income_paise * rng.randint(15, 25)
        first_chunk = int(down_payment_total * rng.uniform(0.4, 0.6))
        second_chunk = down_payment_total - first_chunk
        # A down payment this size (multiples of monthly income) is funded
        # from outside this account -- a loan disbursement / own-funds
        # transfer from elsewhere -- not paid out of the existing balance.
        # Pair each builder debit with a same-day funding credit so the
        # (visible, ground-truth-labelled) builder payment actually posts
        # instead of being silently dropped by the overdraft guard.
        for offset_days, chunk, label in (
            (7, first_chunk, "booking amount"),
            (37, second_chunk, "installment"),
        ):
            on_date = start_ts.date() + timedelta(days=offset_days)
            credit_time, debit_time = _funding_pair_times(rng)
            state.scheduled_credits.append(
                ScheduledAmount(
                    on_date=on_date,
                    amount_paise=chunk,
                    description="Home purchase funds transfer-in",
                    category="home_purchase_funding",
                    channel=Channel.NEFT,
                    merchant="Own Funds Transfer",
                    time_of_day=credit_time,
                )
            )
            state.scheduled_debits.append(
                ScheduledAmount(
                    on_date=on_date,
                    amount_paise=chunk,
                    description=f"Builder payment - {label}",
                    category="builder_payment",
                    channel=Channel.NEFT,
                    merchant="Builder Pvt Ltd",
                    time_of_day=debit_time,
                )
            )

        emi_amount = int(state.monthly_income_paise * rng.uniform(0.25, 0.4))
        emi_start = start_ts.date().replace(day=1) + timedelta(days=32)
        emi_start = emi_start.replace(day=5)
        state.emis.append(
            EMI(
                label="Home Loan EMI",
                amount_paise=emi_amount,
                day_of_month=5,
                category="home_loan_emi",
                start_after=emi_start,
            )
        )
        if "home_loan" not in persona.products_held:
            persona.products_held = [*persona.products_held, "home_loan"]

        return GroundTruthEvent(
            customer_id=persona.id,
            type=LifeEventType.HOME_PURCHASE_INTENT,
            start_ts=start_ts,
            params={
                "previous_monthly_rent_paise": previous_rent,
                "down_payment_total_paise": down_payment_total,
                "home_loan_emi_paise": emi_amount,
            },
        )


class _BonusWindfall:
    """One-off bonus credit, 3-5x monthly income."""

    def apply(
        self, persona: Persona, state: GeneratorState, start_ts: datetime
    ) -> GroundTruthEvent:
        rng = _rng_for(state, persona, "bonus_windfall", start_ts)
        multiplier = round(rng.uniform(3.0, 5.0), 2)
        amount = int(state.monthly_income_paise * multiplier)
        state.scheduled_credits.append(
            ScheduledAmount(
                on_date=start_ts.date(),
                amount_paise=amount,
                description=f"Annual bonus credit from {state.income_source_name}",
                category="bonus",
                channel=Channel.NEFT,
                merchant=state.income_source_name,
            )
        )
        return GroundTruthEvent(
            customer_id=persona.id,
            type=LifeEventType.BONUS_WINDFALL,
            start_ts=start_ts,
            params={"multiplier": multiplier, "amount_paise": amount},
        )


class _Wedding:
    """Wedding season: catering/jewellery/venue spikes over ~45 days."""

    def apply(
        self, persona: Persona, state: GeneratorState, start_ts: datetime
    ) -> GroundTruthEvent:
        rng = _rng_for(state, persona, "wedding", start_ts)
        income_scale = max(
            0.3, min(4.0, state.monthly_income_paise / 8_000_000)
        )  # baseline ~INR 80k/mo
        total_spend = 0
        for category, merchants in WEDDING_MERCHANTS.items():
            base_low, base_high = {
                "wedding_catering": (80_000, 300_000),
                "jewellery": (50_000, 500_000),
                "venue_booking": (100_000, 600_000),
            }[category]
            amount = int(rng.randint(base_low, base_high) * 100 * income_scale)
            total_spend += amount
            on_date = start_ts.date() + timedelta(days=rng.randint(0, 45))
            credit_time, debit_time = _funding_pair_times(rng)
            # Real weddings are funded from savings drawn down over months,
            # family contributions, and gifts, not solely the day-to-day
            # transaction balance -- pair each big-ticket debit with a
            # same-day funding credit so it reliably posts (and shows up for
            # ground-truth detection) instead of being dropped for
            # insufficient balance.
            state.scheduled_credits.append(
                ScheduledAmount(
                    on_date=on_date,
                    amount_paise=amount,
                    description="Wedding fund transfer-in (family contribution)",
                    category="wedding_funding",
                    channel=Channel.NEFT,
                    merchant="Family Contribution",
                    time_of_day=credit_time,
                )
            )
            state.scheduled_debits.append(
                ScheduledAmount(
                    on_date=on_date,
                    amount_paise=amount,
                    description=f"Wedding expense - {category.replace('_', ' ')}",
                    category=category,
                    channel=Channel.NEFT,
                    merchant=rng.choice(merchants),
                    time_of_day=debit_time,
                )
            )
        return GroundTruthEvent(
            customer_id=persona.id,
            type=LifeEventType.WEDDING,
            start_ts=start_ts,
            params={"total_estimated_spend_paise": total_spend},
        )


class _ChurnRisk:
    """Disengagement: UPI activity decays to near-zero, balance drains out."""

    def apply(
        self, persona: Persona, state: GeneratorState, start_ts: datetime
    ) -> GroundTruthEvent:
        rng = _rng_for(state, persona, "churn_risk", start_ts)
        handle = persona.name.split()[0].lower()
        competitor_vpa = f"{handle}{rng.randint(100, 999)}@competitorbank"
        state.churn_decay_start = start_ts.date()
        state.churn_drain_vpa = competitor_vpa
        state.churn_drain_date = start_ts.date() + timedelta(days=rng.randint(5, 15))
        state.churn_drain_fraction = round(rng.uniform(0.6, 0.85), 2)

        return GroundTruthEvent(
            customer_id=persona.id,
            type=LifeEventType.CHURN_RISK,
            start_ts=start_ts,
            params={
                "decay_start": state.churn_decay_start.isoformat(),
                "drain_date": state.churn_drain_date.isoformat(),
                "drain_fraction": state.churn_drain_fraction,
                "competitor_vpa": competitor_vpa,
            },
        )


job_change = _JobChange()
new_child = _NewChild()
home_purchase_intent = _HomePurchaseIntent()
bonus_windfall = _BonusWindfall()
wedding = _Wedding()
churn_risk = _ChurnRisk()

REGISTRY: dict[LifeEventType, LifeEventScript] = {
    LifeEventType.JOB_CHANGE: job_change,
    LifeEventType.NEW_CHILD: new_child,
    LifeEventType.HOME_PURCHASE_INTENT: home_purchase_intent,
    LifeEventType.BONUS_WINDFALL: bonus_windfall,
    LifeEventType.WEDDING: wedding,
    LifeEventType.CHURN_RISK: churn_risk,
}
