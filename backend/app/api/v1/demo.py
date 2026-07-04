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
from app.core.redis import TXN_EVENTS, get_redis
from app.core.security import get_current_user
from app.models.banking import Account, Transaction
from app.models.enums import AccountStatus, AccountType, DigitalMaturity
from app.models.identity import User
from app.seed import _SEGMENT_BY_ARCHETYPE, _history_start
from app.services import products
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


@router.post("/demo-activity", response_model=DemoActivityResponse)
async def load_demo_activity(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DemoActivityResponse:
    customer = await _customer_for_user_or_404(db, user)

    existing = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(Account.customer_id == customer.id)
    )
    if int(existing or 0) > _ALREADY_LOADED_THRESHOLD:
        raise HTTPException(status_code=409, detail="Demo activity is already loaded")

    # Deterministic persona per customer: same user always gets the same history.
    persona_seed = int.from_bytes(customer.id.bytes[:4], "big")
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

    # Enrich the profile so the agents' usage/feature extraction has substance.
    customer.persona = persona.model_dump(mode="json")
    customer.occupation = customer.occupation or persona.occupation
    customer.city = customer.city or persona.city
    customer.annual_income_paise = customer.annual_income_paise or (
        persona.monthly_income_paise * 12
    )
    customer.segment = customer.segment or _SEGMENT_BY_ARCHETYPE.get(persona.archetype)
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
    windfall = Txn(
        event_id=str(uuid.uuid4()),
        customer_id=str(customer.id),
        ts=datetime.now(UTC) - timedelta(minutes=1),
        amount_paise=windfall_amount,
        direction=Direction.CREDIT,
        channel=Channel.NEFT,
        merchant=persona.employer or "Employer",
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
