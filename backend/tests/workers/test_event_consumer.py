"""Event consumer integration tests: idempotency, unknown-customer skip, and the
prefilter -> cooldown -> run_event_trigger -> console-feed publish path.

Runs against the real `sarathi_test` DB (via `tests/workers/conftest.py`'s
app-wide engine override) and a real Redis logical DB (flushed per test).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import orjson
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.workers.event_consumer as event_consumer
from app.core.redis import (
    AGENT_ACTIONS,
    GROUP_AGENTS,
    TXN_EVENTS,
    TXN_EVENTS_DLQ,
    get_redis,
)
from app.models.banking import Account, Transaction
from app.models.customer import Customer
from app.models.enums import AccountStatus, AccountType
from app.workers.event_consumer import _parse_event_ts, ensure_group, process_envelope
from app.workers.prefilter import RuleMatch, TxnLike


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

    # Install the fake router/embedder BEFORE any processing: the UPI-active persona
    # means the non-UPI prior salary credit also trips the dormancy rule, so a live
    # LLM call would otherwise fire here (HARD BUDGET rule forbids it).
    handler = ScriptedHandler(default_text="Congratulations on the bonus!")
    fake_router = FakeRouter(handler)
    monkeypatch.setattr(entrypoints, "get_router", lambda: fake_router)
    monkeypatch.setattr(entrypoints, "get_embedder", lambda: FakeEmbedder())

    # One prior salary credit establishes a trailing median for the windfall check.
    prior = _envelope(
        customer_id=str(customer.id), event_id="evt-salary-1",
        amount_paise=50_000_00, direction="credit", category="salary", channel="neft",
    )
    await process_envelope(prior)

    windfall = _envelope(
        customer_id=str(customer.id), event_id="evt-windfall",
        amount_paise=250_000_00, direction="credit", category="bonus", channel="neft",
    )
    await process_envelope(windfall)

    redis = get_redis()
    entries = await redis.xrange(AGENT_ACTIONS, min="-", max="+")
    kinds = [orjson.loads(fields["data"])["type"] for _id, fields in entries]
    assert "agent_run" in kinds


def test_parse_event_ts_makes_naive_aware() -> None:
    """Naive ISO timestamps (sim/generator, console inject) become aware; already-aware
    timestamps pass through unchanged."""
    naive = _parse_event_ts("2026-07-04T12:00:00")
    assert naive.tzinfo is not None
    aware = _parse_event_ts("2026-07-04T12:00:00+05:30")
    assert aware.utcoffset() is not None


async def test_naive_timestamp_event_matches_rule_without_crash(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: an event whose payload ts is a *naive* ISO string must process
    against DB-loaded (tz-aware) history without raising
    'can't compare offset-naive and offset-aware datetimes', and still fire the rule.
    """
    import app.agents.entrypoints as entrypoints
    from tests.agents.conftest import FakeEmbedder, FakeRouter, ScriptedHandler

    customer, _account = await _make_customer_with_account(db, balance_paise=100_000_00)

    # Fakes installed before any processing so the dormancy rule the prior salary
    # credit also trips cannot reach a live LLM (HARD BUDGET rule).
    handler = ScriptedHandler(default_text="Congratulations on the bonus!")
    monkeypatch.setattr(entrypoints, "get_router", lambda: FakeRouter(handler))
    monkeypatch.setattr(entrypoints, "get_embedder", lambda: FakeEmbedder())

    # Prior salary credit (aware envelope) -> stored, then loaded back tz-aware.
    prior = _envelope(
        customer_id=str(customer.id), event_id="evt-naive-salary-1",
        amount_paise=50_000_00, direction="credit", category="salary", channel="neft",
    )
    await process_envelope(prior)

    # Windfall credit with a NAIVE timestamp (no offset) - the failure trigger.
    naive_ts = datetime.now(UTC).replace(tzinfo=None).isoformat()
    windfall = _envelope(
        customer_id=str(customer.id), event_id="evt-naive-windfall",
        amount_paise=250_000_00, direction="credit", category="bonus", channel="neft",
    )
    windfall["ts"] = naive_ts
    windfall["payload"]["ts"] = naive_ts
    assert "+" not in naive_ts and "Z" not in naive_ts  # guard: really naive

    await process_envelope(windfall)  # must not raise

    redis = get_redis()
    entries = await redis.xrange(AGENT_ACTIONS, min="-", max="+")
    kinds = [orjson.loads(fields["data"])["type"] for _id, fields in entries]
    assert "agent_run" in kinds


# --- restart resilience --------------------------------------------------------------


# --- worker resilience: per-run timeout + concurrency semaphore ----------------------


def _fake_run_result() -> SimpleNamespace:
    """Minimal stand-in for `AgentRunResult` (only the fields `publish_run_result` reads)."""
    return SimpleNamespace(
        run_id="run-x", final_text="", proposals=[], life_events=[], nudges=[]
    )


async def test_agent_run_guard_dead_letters_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single agent run that overruns the timeout is dead-lettered (envelope +
    reason) and yields None so the caller can continue - never stalls the stream."""

    async def _hang(customer_id: str, summary: str, *, event: object = None) -> object:
        await asyncio.sleep(5)  # far exceeds the (patched) timeout
        return _fake_run_result()

    monkeypatch.setattr(event_consumer, "run_event_trigger", _hang)
    monkeypatch.setattr(event_consumer, "AGENT_RUN_TIMEOUT_SECONDS", 0.05)

    match = RuleMatch(rule="windfall", event_summary="big credit", evidence={"x": 1})
    txn: TxnLike = {
        "ts": datetime.now(UTC), "amount_paise": 250_000_00, "direction": "credit",
        "channel": "neft", "category": "bonus", "merchant": "Acme", "balance_after_paise": 1,
    }
    envelope = {"event_id": "evt-timeout", "customer_id": "c1", "payload": {}}

    result = await event_consumer._run_agent_guarded("c1", match, txn, envelope)
    assert result is None

    dlq = await get_redis().xrange(TXN_EVENTS_DLQ, min="-", max="+")
    assert len(dlq) == 1
    assert "agent_run_timeout" in dlq[0][1]["error"]
    assert dlq[0][1]["rule"] == "windfall"


async def test_process_envelope_continues_when_agent_run_times_out(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a matched rule whose agent run times out dead-letters the envelope
    and publishes NO console-feed activity, but process_envelope returns cleanly.

    ``upi_active=False`` keeps the dormancy rule (which would otherwise fire on the
    non-UPI salary credit) out of play, so the only match is the windfall - and
    ``run_event_trigger`` is stubbed *before any* processing so no real agent run
    (and no live LLM call) can ever occur on this path.
    """
    customer, _account = await _make_customer_with_account(
        db, balance_paise=100_000_00, upi_active=False
    )

    async def _hang(customer_id: str, summary: str, *, event: object = None) -> object:
        await asyncio.sleep(5)
        return _fake_run_result()

    monkeypatch.setattr(event_consumer, "run_event_trigger", _hang)
    monkeypatch.setattr(event_consumer, "AGENT_RUN_TIMEOUT_SECONDS", 0.05)

    prior = _envelope(
        customer_id=str(customer.id), event_id="evt-to-salary",
        amount_paise=50_000_00, direction="credit", category="salary", channel="neft",
    )
    await process_envelope(prior)  # establishes the trailing median (matches nothing)

    windfall = _envelope(
        customer_id=str(customer.id), event_id="evt-to-windfall",
        amount_paise=250_000_00, direction="credit", category="bonus", channel="neft",
    )
    await process_envelope(windfall)  # must not raise

    redis = get_redis()
    dlq = await redis.xrange(TXN_EVENTS_DLQ, min="-", max="+")
    assert any("agent_run_timeout" in fields.get("error", "") for _id, fields in dlq)

    feed = await redis.xrange(AGENT_ACTIONS, min="-", max="+")
    kinds = [orjson.loads(fields["data"])["type"] for _id, fields in feed]
    assert "agent_run" not in kinds  # timed-out run publishes nothing


async def test_agent_run_concurrency_capped_at_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """The global semaphore admits at most `AGENT_RUN_CONCURRENCY` (2) runs at once;
    excess runs queue until a slot frees."""
    active = 0
    observed_max = 0
    release = asyncio.Event()

    async def _blocking_run(customer_id: str, summary: str, *, event: object = None) -> object:
        nonlocal active, observed_max
        active += 1
        observed_max = max(observed_max, active)
        try:
            await release.wait()
        finally:
            active -= 1
        return _fake_run_result()

    monkeypatch.setattr(event_consumer, "run_event_trigger", _blocking_run)

    match = RuleMatch(rule="windfall", event_summary="s", evidence={})
    txn: TxnLike = {
        "ts": datetime.now(UTC), "amount_paise": 1, "direction": "credit",
        "channel": "neft", "category": "salary", "merchant": None, "balance_after_paise": 1,
    }
    envelope = {"event_id": "e", "customer_id": "c", "payload": {}}

    tasks = [
        asyncio.create_task(
            event_consumer._run_agent_guarded(
                f"c{i}", match, txn, {**envelope, "event_id": f"e{i}"}
            )
        )
        for i in range(4)
    ]
    try:
        await asyncio.sleep(0.3)  # let all four reach the semaphore
        # Exactly two hold a slot; the other two are queued behind them.
        assert active == 2
        assert observed_max == 2
    finally:
        release.set()
        await asyncio.gather(*tasks)

    assert observed_max == 2  # the cap was never breached across the whole run


async def test_ensure_group_is_idempotent_across_restart(db: AsyncSession) -> None:
    """A restarted worker re-runs `ensure_group`; the pre-existing group (BUSYGROUP)
    must be swallowed, not crash the boot."""
    await ensure_group()
    await ensure_group()  # simulated restart - must not raise

    redis = get_redis()
    groups = await redis.xinfo_groups(TXN_EVENTS)
    assert any(g["name"] == GROUP_AGENTS for g in groups)


async def test_reclaim_stale_processes_pending_entry_from_dead_consumer(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry a crashed consumer delivered but never acked is reclaimed on the next
    pass and processed to completion (transaction applied, entry acked)."""
    customer, _account = await _make_customer_with_account(db, balance_paise=10_000_00)
    await ensure_group()
    redis = get_redis()

    envelope = _envelope(
        customer_id=str(customer.id), event_id="evt-reclaim", amount_paise=500_00
    )
    await redis.xadd(TXN_EVENTS, {"data": orjson.dumps(envelope).decode()})

    # A now-dead consumer picks the entry up but never acks it (crash mid-process).
    delivered = await redis.xreadgroup(
        GROUP_AGENTS, "dead-consumer", {TXN_EVENTS: ">"}, count=10
    )
    assert delivered  # entry is now pending under `dead-consumer`

    # Restart: reclaim ignores the idle-time gate so the test does not have to wait.
    monkeypatch.setattr(event_consumer, "CLAIM_MIN_IDLE_MS", 0)
    await event_consumer._reclaim_stale(redis)

    result = await db.execute(sa.select(Transaction).where(Transaction.event_id == "evt-reclaim"))
    assert result.scalar_one_or_none() is not None

    pending = await redis.xpending(TXN_EVENTS, GROUP_AGENTS)
    assert pending["pending"] == 0


async def test_poison_entry_escalates_to_dlq(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A structurally broken entry that keeps failing is moved to the DLQ and acked off
    the main stream after `MAX_DELIVERIES`, so it never blocks the loop forever."""
    customer, _account = await _make_customer_with_account(db)
    await ensure_group()
    redis = get_redis()
    monkeypatch.setattr(event_consumer, "MAX_DELIVERIES", 1)

    poison = {
        "event_id": "evt-poison",
        "customer_id": str(customer.id),
        "type": "transaction",
        "ts": datetime.now(UTC).isoformat(),
        # payload missing `amount_paise` -> process_envelope raises KeyError.
        "payload": {"event_id": "evt-poison", "direction": "debit", "channel": "upi"},
    }
    await redis.xadd(TXN_EVENTS, {"data": orjson.dumps(poison).decode()})

    resp = await redis.xreadgroup(
        GROUP_AGENTS, event_consumer.CONSUMER_NAME, {TXN_EVENTS: ">"}, count=10
    )
    (_stream, entries), = resp
    entry_id, fields = entries[0]
    await event_consumer._handle_delivery(redis, entry_id, fields)

    dlq = await redis.xrange(TXN_EVENTS_DLQ, min="-", max="+")
    assert len(dlq) == 1
    assert dlq[0][1]["error"]

    pending = await redis.xpending(TXN_EVENTS, GROUP_AGENTS)
    assert pending["pending"] == 0
