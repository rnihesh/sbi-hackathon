"""Event consumer integration tests: idempotency, unknown-customer skip, and the
prefilter -> cooldown -> run_event_trigger -> console-feed publish path.

Runs against the real `sarathi_test` DB (via `tests/workers/conftest.py`'s
app-wide engine override) and a real Redis logical DB (flushed per test).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import orjson
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import AGENT_ACTIONS, get_redis
from app.models.banking import Account, Transaction
from app.models.customer import Customer
from app.models.enums import AccountStatus, AccountType
from app.workers.event_consumer import process_envelope


def _envelope(
    *, customer_id: str, event_id: str, amount_paise: int = 500_00, direction: str = "debit",
    category: str = "groceries", channel: str = "upi",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "customer_id": customer_id,
        "type": "transaction",
        "ts": datetime.now(UTC).isoformat(),
        "payload": {
            "event_id": event_id,
            "customer_id": customer_id,
            "ts": datetime.now(UTC).isoformat(),
            "amount_paise": amount_paise,
            "direction": direction,
            "channel": channel,
            "merchant": "Test Merchant",
            "mcc": None,
            "category": category,
            "description": "test txn",
        },
    }


async def _make_customer_with_account(
    db: AsyncSession, *, balance_paise: int = 10_000_00, upi_active: bool = True
) -> tuple[Customer, Account]:
    customer = Customer(
        full_name="Sim Persona",
        persona={"upi_active": upi_active, "archetype": "young_salaried_techie"},
    )
    db.add(customer)
    await db.flush()
    account = Account(
        customer_id=customer.id, type=AccountType.SAVINGS,
        balance_paise=balance_paise, status=AccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()
    await db.commit()
    return customer, account


async def test_unknown_customer_is_skipped(db: AsyncSession) -> None:
    envelope = _envelope(customer_id=str(uuid.uuid4()), event_id="evt-unknown")
    await process_envelope(envelope)  # must not raise

    result = await db.execute(sa.select(Transaction).where(Transaction.event_id == "evt-unknown"))
    assert result.scalar_one_or_none() is None


async def test_duplicate_event_id_applies_once(db: AsyncSession) -> None:
    customer, account = await _make_customer_with_account(db, balance_paise=10_000_00)
    envelope = _envelope(customer_id=str(customer.id), event_id="evt-dup", amount_paise=500_00)

    await process_envelope(envelope)
    await process_envelope(envelope)  # duplicate delivery

    result = await db.execute(sa.select(Transaction).where(Transaction.event_id == "evt-dup"))
    rows = result.scalars().all()
    assert len(rows) == 1

    refreshed = await db.get(Account, account.id)
    assert refreshed is not None
    await db.refresh(refreshed)
    assert refreshed.balance_paise == 10_000_00 - 500_00


async def test_customer_without_account_is_skipped(db: AsyncSession) -> None:
    customer = Customer(full_name="No Account Yet", persona={"upi_active": True})
    db.add(customer)
    await db.flush()
    await db.commit()

    envelope = _envelope(customer_id=str(customer.id), event_id="evt-no-account")
    await process_envelope(envelope)  # must not raise

    result = await db.execute(
        sa.select(Transaction).where(Transaction.event_id == "evt-no-account")
    )
    assert result.scalar_one_or_none() is None


async def test_windfall_rule_triggers_run_and_publishes_feed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.agents.entrypoints as entrypoints
    from tests.agents.conftest import FakeEmbedder, FakeRouter, ScriptedHandler

    customer, _account = await _make_customer_with_account(db, balance_paise=100_000_00)

    # One prior salary credit establishes a trailing median for the windfall check.
    prior = _envelope(
        customer_id=str(customer.id), event_id="evt-salary-1",
        amount_paise=50_000_00, direction="credit", category="salary", channel="neft",
    )
    await process_envelope(prior)

    handler = ScriptedHandler(default_text="Congratulations on the bonus!")
    fake_router = FakeRouter(handler)
    monkeypatch.setattr(entrypoints, "get_router", lambda: fake_router)
    monkeypatch.setattr(entrypoints, "get_embedder", lambda: FakeEmbedder())

    windfall = _envelope(
        customer_id=str(customer.id), event_id="evt-windfall",
        amount_paise=250_000_00, direction="credit", category="bonus", channel="neft",
    )
    await process_envelope(windfall)

    redis = get_redis()
    entries = await redis.xrange(AGENT_ACTIONS, min="-", max="+")
    kinds = [orjson.loads(fields["data"])["type"] for _id, fields in entries]
    assert "agent_run" in kinds
