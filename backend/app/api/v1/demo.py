"""Demo-activity endpoint: fill the authed customer's account with realistic history.

A brand-new sign-up has an empty ledger, so nothing in the product has anything
to react to. This endpoint attaches a deterministic synthetic persona to the
CALLER's own customer record, backfills months of transactions through the same
generator the seeded cohort uses, and replays a recent burst (plus one windfall
credit) through the real ``txn.events`` pipeline so the worker and agents
produce nudges/life-events/proposals for this user. Synthetic data source,
real logic everywhere - per project rules.
"""

from __future__ import annotations

import random
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import orjson
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.logging import get_logger
from app.core.ratelimit import rate_limit
from app.core.redis import TXN_EVENTS, get_redis
from app.core.security import get_current_user
from app.llm.base import ChatMessage
from app.llm.router import LLMRouter, get_router
from app.models.banking import Account, Transaction
from app.models.customer import Customer
from app.models.enums import AccountStatus, AccountType, DigitalMaturity, NotificationKind
from app.models.identity import User
from app.seed import _SEGMENT_BY_ARCHETYPE, _history_start
from app.services import products
from app.services.notifications import notify
from app.sim import generator, personas
from app.sim.generator import Channel, Direction, Txn, to_envelope

from .customers import _customer_for_user_or_404

logger = get_logger(__name__)

router = APIRouter(prefix="/me", tags=["customers"])

_MONTHS = 6
_BURST_TXNS = 15
# Lowest-activity personas (retiree, homemaker) still exceed this over 6 months;
# anything above it means history was already loaded (or the user is a real,
# active customer who does not need demo data).
_ALREADY_LOADED_THRESHOLD = 20


class DemoActivityResponse(BaseModel):
    transactions: int
    months: int
    holdings: int
    events_published: int
    balance_paise: int


def _maturity_enum(score: float) -> DigitalMaturity:
    if score >= 0.66:
        return DigitalMaturity.HIGH
    if score >= 0.33:
        return DigitalMaturity.MEDIUM
    return DigitalMaturity.LOW


# Retail-spend categories whose merchant labels are safe to reskin with LLM
# flavour. Income, rent, EMIs, utilities, and P2P keep their structural labels.
_FLAVOUR_CATEGORIES = frozenset(
    {"groceries", "food_delivery", "transport", "chai_canteen", "card_spend", "pharmacy"}
)

_FLAVOR_SYSTEM = """You add realistic local flavour to a synthetic Indian retail-bank \
customer. Given the persona skeleton JSON, respond with ONLY JSON: {"employer_name": "<a \
realistic employer or business name fitting the occupation and city, or an empty string>", \
"merchant_flavor": ["5 to 8 real-sounding merchant or brand names this person, in their city \
and lifestyle, would actually pay - local kirana, restaurants, transport, pharmacies, \
utilities"], "spending_note": "<one short sentence on their spending style>"}. Keep names \
realistic for the city and income. No commentary."""


async def _persona_flavor(
    router: LLMRouter, persona: personas.Persona, customer_id: str
) -> dict[str, Any] | None:
    """One fast-tier LLM call adding local flavour to a persona skeleton.

    Returns a validated ``{employer_name, merchant_flavor, spending_note}`` dict,
    or ``None`` on any failure (the demo then keeps generator defaults). Never
    raises - the demo path must not break on an LLM hiccup.
    """
    skeleton = {
        "archetype": persona.archetype.value,
        "age": persona.age,
        "city": persona.city,
        "occupation": persona.occupation,
        "monthly_income_rupees": persona.monthly_income_paise // 100,
        "employer": persona.employer,
        "digital_maturity": persona.digital_maturity,
    }
    try:
        resp = await router.chat(
            tier="fast",
            messages=[ChatMessage(role="user", content=orjson.dumps(skeleton).decode())],
            system=_FLAVOR_SYSTEM,
            json_mode=True,
            temperature=0.7,
            purpose="demo:persona_flavor",
        )
        data = orjson.loads(resp.text)
    except Exception:
        logger.warning("demo_persona_flavor_failed", customer_id=customer_id)
        return None
    if not isinstance(data, dict):
        return None
    raw_merchants = data.get("merchant_flavor")
    merchants = (
        [str(m).strip() for m in raw_merchants if str(m).strip()]
        if isinstance(raw_merchants, list)
        else []
    )
    return {
        "employer_name": str(data.get("employer_name", "") or "").strip(),
        "merchant_flavor": merchants[:8],
        "spending_note": str(data.get("spending_note", "") or "").strip(),
    }


def _apply_flavor(txns: list[Txn], merchants: list[str], salt: int) -> list[Txn]:
    """Reskin a fraction of generic retail merchant names with flavour names.

    Deterministic given ``salt`` (persisted with the persona), so the same load
    reproduces and a fresh salt reshuffles. Only retail-spend debits are touched.
    """
    if not merchants:
        return txns
    rng = random.Random(salt)
    out: list[Txn] = []
    for txn in txns:
        if (
            txn.direction is Direction.DEBIT
            and txn.category in _FLAVOUR_CATEGORIES
            and rng.random() < 0.5
        ):
            merchant = merchants[rng.randrange(len(merchants))]
            out.append(txn.model_copy(update={"merchant": merchant}))
        else:
            out.append(txn)
    return out


def _clear_demo_pollution(customer: Customer) -> bool:
    """NULL identity columns an older demo version wrote onto the real profile.

    Only clears values that still equal what the stored demo persona would
    produce, and only when a demo persona is attached - a real customer (empty
    persona) or a hand-edited profile is never touched. Returns whether anything
    changed. Going forward the demo never writes these columns at all.
    """
    persona = customer.persona or {}
    archetype = persona.get("archetype")
    if not archetype:
        return False
    changed = False
    if customer.city is not None and customer.city == persona.get("city"):
        customer.city = None
        changed = True
    if customer.occupation is not None and customer.occupation == persona.get("occupation"):
        customer.occupation = None
        changed = True
    try:
        segment = _SEGMENT_BY_ARCHETYPE.get(personas.Archetype(archetype))
    except ValueError:
        segment = None
    if customer.segment is not None and customer.segment == segment:
        customer.segment = None
        changed = True
    monthly = persona.get("monthly_income_paise")
    if (
        isinstance(monthly, int)
        and customer.annual_income_paise is not None
        and customer.annual_income_paise == monthly * 12
    ):
        customer.annual_income_paise = None
        changed = True
    return changed


@router.post(
    "/demo-activity",
    response_model=DemoActivityResponse,
    # Heavy: months of synthetic history + a fast-tier LLM flavour call + a burst of
    # real events. 2/hour per user is ample for a genuine reload, absurd for abuse.
    dependencies=[
        Depends(rate_limit("demo_activity", limit=10, window_seconds=3600, key="by_user"))
    ],
)
async def load_demo_activity(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DemoActivityResponse:
    customer = await _customer_for_user_or_404(db, user)

    # Legacy cleanup: an earlier demo version wrote identity fields onto the real
    # profile. Remove that pollution (values that still equal the demo persona)
    # and never re-write them below. Commit now so it survives an early 409.
    if _clear_demo_pollution(customer):
        await db.commit()

    existing = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(Account.customer_id == customer.id)
    )
    if int(existing or 0) > _ALREADY_LOADED_THRESHOLD:
        raise HTTPException(status_code=409, detail="Demo activity is already loaded")

    # Fresh random salt mixed with the customer id: a re-load after a reset yields
    # different synthetic data, yet THIS load is reproducible (salt persisted in
    # the persona JSON). Synthetic data source only - all downstream logic is real.
    salt = secrets.randbelow(2**31)
    persona_seed = personas.derived_seed(str(customer.id), salt)
    persona = personas.make_cohort(1, seed=persona_seed)[0].model_copy(
        update={"id": str(customer.id), "name": customer.full_name}
    )

    account = (
        await db.execute(
            select(Account).where(Account.customer_id == customer.id).limit(1)
        )
    ).scalar_one_or_none()
    if account is None:
        account = Account(
            customer_id=customer.id,
            type=AccountType.SAVINGS,
            balance_paise=0,
            status=AccountStatus.ACTIVE,
            label="Primary Savings",
        )
        db.add(account)
        await db.flush()

    history_start = _history_start(_MONTHS)
    state = generator.new_state(persona, persona_seed, start_date=history_start)
    txns = generator.generate_history(
        persona, _MONTHS, persona_seed, state=state, start_date=history_start
    )

    # LLM persona flavour (one fast-tier call): realistic employer + local merchant
    # names threaded into the generated retail spends. Falls back to generator
    # defaults on any failure (logged, never breaks the demo).
    flavor = await _persona_flavor(get_router(), persona, str(customer.id))
    merchant_flavor = flavor.get("merchant_flavor", []) if flavor else []
    if merchant_flavor:
        txns = _apply_flavor(txns, merchant_flavor, salt)

    if txns:
        rows = [
            {
                "id": uuid.uuid4(),
                "account_id": account.id,
                "event_id": t.event_id,
                "ts": t.ts,
                "amount_paise": t.amount_paise,
                "direction": t.direction.value,
                "channel": t.channel.value,
                "merchant": t.merchant,
                "mcc": t.mcc,
                "category": t.category,
                "balance_after_paise": t.balance_after_paise,
                "description": t.description,
            }
            for t in txns
        ]
        await db.execute(sa.insert(Transaction), rows)
    account.balance_paise = state.balance_paise

    # Attach the persona JSON (agents need it) + digital maturity ONLY. The real
    # identity columns (city/occupation/segment/annual_income_paise) are left
    # untouched so demo activity never overwrites a customer's own profile.
    persona_json = persona.model_dump(mode="json")
    persona_json["demo_loaded"] = True
    persona_json["demo_salt"] = salt
    if flavor is not None:
        persona_json["demo_flavor"] = flavor
    customer.persona = persona_json
    customer.digital_maturity = _maturity_enum(persona.digital_maturity)

    holdings_created = 0
    for code in persona.products_held:
        await products.activate_holding(db, customer_id=customer.id, product_code=code)
        holdings_created += 1
    await db.flush()

    # Replay a recent burst plus one fresh windfall credit through the REAL
    # event pipeline; the worker's idempotent insert makes re-published rows
    # harmless while its prefilter rules and agents run for this customer.
    events_published = 0
    windfall_amount = max(persona.monthly_income_paise, 50_000_00) * 4
    windfall_source = (
        (flavor.get("employer_name") if flavor else "") or persona.employer or "Employer"
    )
    windfall = Txn(
        event_id=str(uuid.uuid4()),
        customer_id=str(customer.id),
        ts=datetime.now(UTC) - timedelta(minutes=1),
        amount_paise=windfall_amount,
        direction=Direction.CREDIT,
        channel=Channel.NEFT,
        merchant=windfall_source,
        mcc=None,
        category="salary",
        balance_after_paise=account.balance_paise + windfall_amount,
        description="Annual performance bonus",
    )
    try:
        redis = get_redis()
        burst: list[dict[str, Any]] = [to_envelope(t) for t in txns[-_BURST_TXNS:]]
        burst.append(to_envelope(windfall))
        for envelope in burst:
            await redis.xadd(TXN_EVENTS, {"data": orjson.dumps(envelope)})
        events_published = len(burst)
    except Exception:
        logger.warning("demo_activity_publish_failed", customer_id=str(customer.id))

    await notify(
        db,
        customer.id,
        NotificationKind.SYSTEM,
        "Your demo activity is ready",
        "We set up months of sample transactions and insights. Explore your dashboard, "
        "then check back for nudges as Sarathi reads your activity.",
        link="/app/home",
    )

    logger.info(
        "demo_activity_loaded",
        customer_id=str(customer.id),
        transactions=len(txns),
        events_published=events_published,
    )
    return DemoActivityResponse(
        transactions=len(txns),
        months=_MONTHS,
        holdings=holdings_created,
        events_published=events_published,
        balance_paise=account.balance_paise,
    )
