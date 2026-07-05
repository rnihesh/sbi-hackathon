"""Proactive scheduler tests: eligibility, Redis cooldown, batch + daily caps,
budget/disabled/kill-switch skips, `scheduled` trigger provenance, health fields.

Ticks are driven directly via `run_scheduler_tick` (no loop, no sleeps). LLM runs
are faked - either by stubbing `scheduler.run_event_trigger` (cap/cooldown tests)
or by wiring a `FakeRouter`/`FakeEmbedder` through the real run (provenance test),
so no live LLM call ever fires (HARD BUDGET rule).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.workers.scheduler as scheduler
from app.agents import memory
from app.core.config import get_settings
from app.core.redis import get_redis
from app.llm.budget import BudgetExceeded
from app.models.banking import Account
from app.models.customer import Customer
from app.models.enums import (
    AccountStatus,
    AccountType,
    AgentRunStatus,
    AgentTriggerType,
    MemoryKind,
    StandingCadence,
    StandingPurpose,
    StandingStatus,
)
from app.models.memory import AgentMemory
from app.models.standing import StandingInstruction
from app.models.tracing import AgentRun

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _FakeRouter:
    """Router double exposing only the budget guard the scheduler calls."""

    def __init__(self, *, over_budget: bool = False) -> None:
        self._over = over_budget

    async def raise_if_over_budget(self) -> None:
        if self._over:
            raise BudgetExceeded("daily LLM budget reached")


async def _add_customer_with_account(
    db: AsyncSession, *, name: str = "Sweep Persona", with_account: bool = True
) -> Customer:
    customer = Customer(full_name=name, persona={"upi_active": True})
    db.add(customer)
    await db.flush()
    if with_account:
        db.add(
            Account(
                customer_id=customer.id,
                type=AccountType.SAVINGS,
                balance_paise=10_000_00,
                status=AccountStatus.ACTIVE,
            )
        )
        await db.flush()
    await db.commit()
    return customer


async def _add_agent_run(
    db: AsyncSession, customer_id: uuid.UUID, *, age_days: float
) -> None:
    run = AgentRun(
        agent="supervisor",
        trigger=AgentTriggerType.EVENT,
        status=AgentRunStatus.COMPLETED,
        customer_id=customer_id,
        started_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db.add(run)
    await db.commit()


def _install_router(monkeypatch: pytest.MonkeyPatch, *, over_budget: bool = False) -> None:
    monkeypatch.setattr(scheduler, "get_router", lambda: _FakeRouter(over_budget=over_budget))


def _stub_runs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the LLM-spending run with a counter; returns the list of swept ids."""
    swept: list[str] = []

    async def _fake_run(customer_id: str, summary: str, *, event: Any = None, trigger: Any = None):
        swept.append(customer_id)
        return scheduler.AgentRunResult(
            run_id=str(uuid.uuid4()), status="completed", final_text="", intent="adoption",
            agent="adoption",
        )

    monkeypatch.setattr(scheduler, "run_event_trigger", _fake_run)
    return swept


# ---------------------------------------------------------------------------
# 1. Eligibility query
# ---------------------------------------------------------------------------


async def test_eligibility_requires_account_and_no_recent_run(db: AsyncSession) -> None:
    eligible = await _add_customer_with_account(db, name="Eligible")
    no_account = await _add_customer_with_account(db, name="No Account", with_account=False)
    recently_run = await _add_customer_with_account(db, name="Recently Run")
    await _add_agent_run(db, recently_run.id, age_days=1)  # inside the 7-day cooldown
    long_ago = await _add_customer_with_account(db, name="Ran Long Ago")
    await _add_agent_run(db, long_ago.id, age_days=30)  # outside the window -> eligible again

    cutoff = scheduler.cooldown_cutoff()
    ids = await scheduler.eligible_candidate_ids(db, cutoff=cutoff, limit=50)

    assert eligible.id in ids
    assert long_ago.id in ids
    assert no_account.id not in ids
    assert recently_run.id not in ids
    assert await scheduler.count_eligible_customers(db) == 2


# ---------------------------------------------------------------------------
# 2. Redis cooldown respected
# ---------------------------------------------------------------------------


async def test_redis_cooldown_blocks_second_sweep(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    swept = _stub_runs(monkeypatch)
    await _add_customer_with_account(db, name="Only One")

    first = await scheduler.run_scheduler_tick()
    assert first.reason == "ok"
    assert len(swept) == 1  # swept once, Redis cooldown now set

    # Second tick: still DB-eligible (fake run created no AgentRun row) but the
    # per-customer Redis cooldown must gate it out.
    second = await scheduler.run_scheduler_tick()
    assert second.swept == []
    assert len(swept) == 1


# ---------------------------------------------------------------------------
# 3. Batch cap
# ---------------------------------------------------------------------------


async def test_batch_cap_limits_sweeps_per_tick(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    swept = _stub_runs(monkeypatch)
    monkeypatch.setattr(get_settings(), "sweep_batch_size", 2)
    for i in range(5):
        await _add_customer_with_account(db, name=f"Cust {i}")

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "ok"
    assert len(result.swept) == 2
    assert len(swept) == 2


# ---------------------------------------------------------------------------
# 4. Daily cap stops the loop
# ---------------------------------------------------------------------------


async def test_daily_cap_stops_tick(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    swept = _stub_runs(monkeypatch)
    monkeypatch.setattr(get_settings(), "sweep_daily_cap", 3)
    for i in range(4):
        await _add_customer_with_account(db, name=f"Cust {i}")

    redis = get_redis()
    # Pretend 3 sweeps already happened today: the counter is at the cap.
    await redis.set(scheduler._swept_key(datetime.now(UTC)), 3)

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "daily_cap"
    assert swept == []


async def test_batch_clamped_to_remaining_daily_cap(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    _stub_runs(monkeypatch)
    monkeypatch.setattr(get_settings(), "sweep_batch_size", 5)
    monkeypatch.setattr(get_settings(), "sweep_daily_cap", 4)
    for i in range(6):
        await _add_customer_with_account(db, name=f"Cust {i}")

    redis = get_redis()
    await redis.set(scheduler._swept_key(datetime.now(UTC)), 3)  # only 1 left under the cap

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "ok"
    assert len(result.swept) == 1  # min(batch_size=5, cap_remaining=1)
    assert await scheduler.swept_today_count(redis) == 4


# ---------------------------------------------------------------------------
# 5. Budget-exceeded skips quietly
# ---------------------------------------------------------------------------


async def test_budget_exceeded_skips_tick_quietly(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch, over_budget=True)
    swept = _stub_runs(monkeypatch)
    await _add_customer_with_account(db, name="Would Be Swept")

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "budget"
    assert swept == []
    # No sweep happened, so no cooldown key was written either.
    assert await scheduler.swept_today_count(get_redis()) == 0


# ---------------------------------------------------------------------------
# 6. Disabled no-ops + kill switch mid-tick
# ---------------------------------------------------------------------------


async def test_disabled_scheduler_no_ops(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    swept = _stub_runs(monkeypatch)
    monkeypatch.setattr(get_settings(), "scheduler_enabled", False)
    await _add_customer_with_account(db, name="Ignored While Disabled")

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "disabled"
    assert swept == []
    # A disabled tick is a true no-op: it never even records liveness.
    assert await scheduler.read_last_tick(get_redis()) is None


async def test_kill_switch_honored_mid_tick(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    monkeypatch.setattr(get_settings(), "sweep_batch_size", 5)
    for i in range(5):
        await _add_customer_with_account(db, name=f"Cust {i}")

    swept: list[str] = []

    async def _fake_run(customer_id: str, summary: str, *, event: Any = None, trigger: Any = None):
        swept.append(customer_id)
        get_settings().scheduler_enabled = False  # operator flips the kill switch
        return scheduler.AgentRunResult(
            run_id=str(uuid.uuid4()), status="completed", final_text="", intent="adoption",
            agent="adoption",
        )

    monkeypatch.setattr(scheduler, "run_event_trigger", _fake_run)
    monkeypatch.setattr(get_settings(), "scheduler_enabled", True)

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "ok"
    assert len(swept) == 1  # stopped after the switch flipped, despite 5 eligible


# ---------------------------------------------------------------------------
# 7. `scheduled` trigger recorded on the AgentRun (real run, faked model)
# ---------------------------------------------------------------------------


async def test_sweep_records_scheduled_trigger(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.agents.entrypoints as entrypoints
    from tests.agents.conftest import FakeEmbedder, FakeRouter, ScriptedHandler

    customer = await _add_customer_with_account(db, name="Real Sweep")

    fake_router = FakeRouter(ScriptedHandler(default_text="Here to help you adopt features."))
    monkeypatch.setattr(entrypoints, "get_router", lambda: fake_router)
    monkeypatch.setattr(entrypoints, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(scheduler, "get_router", lambda: fake_router)

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "ok"
    assert result.swept == [str(customer.id)]

    rows = (
        await db.execute(sa.select(AgentRun).where(AgentRun.customer_id == customer.id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].trigger == AgentTriggerType.SCHEDULED


# ---------------------------------------------------------------------------
# 8. Health fields populated
# ---------------------------------------------------------------------------


async def test_health_fields_populated_after_tick(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    _stub_runs(monkeypatch)
    monkeypatch.setattr(get_settings(), "sweep_batch_size", 1)
    await _add_customer_with_account(db, name="A")
    await _add_customer_with_account(db, name="B")

    redis = get_redis()
    assert await scheduler.count_eligible_customers(db) == 2  # both eligible pre-tick

    before = datetime.now(UTC) - timedelta(seconds=1)
    result = await scheduler.run_scheduler_tick()
    assert len(result.swept) == 1

    last_tick = await scheduler.read_last_tick(redis)
    assert last_tick is not None and last_tick >= before
    assert await scheduler.swept_today_count(redis) == 1


# ---------------------------------------------------------------------------
# 9. Memory maintenance hook prunes stale episodic memories
# ---------------------------------------------------------------------------


async def test_tick_prunes_stale_episodic_memories(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    _stub_runs(monkeypatch)
    customer = await _add_customer_with_account(db, name="Prunable")

    now = datetime.now(UTC)
    rows: list[AgentMemory] = []
    # One row beyond the keep window, every row older than the 90-day cutoff:
    # exactly the single oldest is prunable.
    for i in range(memory.EPISODIC_KEEP_RECENT + 1):
        row = AgentMemory(customer_id=customer.id, kind=MemoryKind.EPISODIC, text=f"ep{i}")
        row.created_at = now - timedelta(days=100 + i)
        rows.append(row)
    db.add_all(rows)
    await db.commit()

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "ok"

    remaining = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AgentMemory)
        .where(AgentMemory.customer_id == customer.id)
    )
    assert remaining == memory.EPISODIC_KEEP_RECENT  # the oldest one was pruned


# ---------------------------------------------------------------------------
# 10. Standing instructions run even when the LLM sweep is paused for budget
# ---------------------------------------------------------------------------


async def _add_due_instruction(
    db: AsyncSession, customer_id: uuid.UUID, account_id: uuid.UUID, *, amount_paise: int
) -> StandingInstruction:
    si = StandingInstruction(
        customer_id=customer_id,
        from_account_id=account_id,
        purpose=StandingPurpose.SAVINGS,
        amount_paise=amount_paise,
        cadence=StandingCadence.MONTHLY,
        next_run_date=date(2020, 1, 1),  # long overdue -> due
        status=StandingStatus.ACTIVE,
    )
    db.add(si)
    await db.commit()
    return si


async def test_standing_runs_even_when_budget_exceeded(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Over budget: the LLM sweep is paused, but standing execution is pure ledger
    # work (no spend) and must still fire on the same tick.
    _install_router(monkeypatch, over_budget=True)
    swept = _stub_runs(monkeypatch)
    customer = await _add_customer_with_account(db, name="Has Standing")
    account = await db.scalar(sa.select(Account).where(Account.customer_id == customer.id))
    assert account is not None
    await _add_due_instruction(db, customer.id, account.id, amount_paise=2_000_00)

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "budget"  # LLM sweep paused
    assert swept == []  # no LLM run happened

    # But the due auto-transfer still posted a real debit (committed in the tick's
    # own session, so read the balance with a fresh query, not the cached object).
    balance = await db.scalar(sa.select(Account.balance_paise).where(Account.id == account.id))
    assert balance == 10_000_00 - 2_000_00


async def test_standing_kill_switch_freezes_execution(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_router(monkeypatch)
    _stub_runs(monkeypatch)
    monkeypatch.setattr(get_settings(), "standing_instructions_enabled", False)
    customer = await _add_customer_with_account(db, name="Frozen Standing")
    account = await db.scalar(sa.select(Account).where(Account.customer_id == customer.id))
    assert account is not None
    await _add_due_instruction(db, customer.id, account.id, amount_paise=2_000_00)

    result = await scheduler.run_scheduler_tick()
    assert result.reason == "ok"

    # Kill switch on: no debit posted, balance untouched, instruction still due.
    balance = await db.scalar(sa.select(Account.balance_paise).where(Account.id == account.id))
    assert balance == 10_000_00
    row = (
        await db.execute(
            sa.select(StandingInstruction.next_run_date, StandingInstruction.runs_count)
        )
    ).one()
    assert row.next_run_date == date(2020, 1, 1) and row.runs_count == 0
