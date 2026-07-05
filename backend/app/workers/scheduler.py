"""Proactive periodic scheduler: sweep quiet customers for adoption opportunities.

Real relationship managers do periodic account reviews. Sarathi's event path
(:mod:`app.workers.event_consumer`) only acts when a transaction event fires, so a
dormant customer whose account is quiet never gets an adoption sweep. This module
closes that gap: it runs *inside the event-consumer process* as a sibling asyncio
task (one process to deploy, one set of graph/checkpointer/Redis handles to warm),
and on each tick picks up to ``sweep_batch_size`` customers who have accounts but
have had no agent run in ``sweep_customer_cooldown_days`` and runs the adoption
agent for them via :func:`app.agents.entrypoints.run_event_trigger` (trigger
``scheduled``, so the run is distinguishable in traces).

Design choices:

- **In-process sibling task, not a separate deployable.** ``event_consumer._amain``
  starts :func:`run_scheduler_forever` alongside the stream consumer under one
  ``TaskGroup`` sharing the same ``stop_event``. The scheduler reuses the
  consumer's global agent-run semaphore (:func:`event_consumer._agent_run_semaphore`)
  so scheduled and event-driven runs share one concurrency budget.
- **Safety rails on an unattended path.** A per-customer Redis cooldown, a hard
  per-UTC-day sweep cap (Redis counter), the daily LLM budget guard, and a kill
  switch (`scheduler_enabled`, re-checked between customers) all bound spend and
  load. A tick over budget or over the daily cap is skipped quietly.
- **Never auto-acts.** Sweeps run the ordinary adoption path, whose impactful
  actions become HITL Proposals - a sweep can draft in-app nudges and propose
  offers, but it can NEVER send an email or take an impactful action on its own.
- **Testable ticks.** :func:`run_scheduler_tick` does exactly one tick's work and
  is called directly by tests; :func:`run_scheduler_forever` only adds the jitter
  + sleep loop around it.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.agents.entrypoints import AgentRunResult, run_event_trigger
from app.agents.memory import prune_memories
from app.core import runtime_settings
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.llm.budget import BudgetExceeded
from app.llm.router import get_router
from app.models.banking import Account
from app.models.customer import Customer
from app.models.enums import AgentTriggerType
from app.models.tracing import AgentRun
from app.services.goals import evaluate_all_active_goals
from app.services.standing import execute_due_instructions

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

SWEEP_EVENT_SUMMARY = "Scheduled periodic review: check dormancy and adoption opportunities"
"""Fed to the adoption path as the system-event summary for every sweep."""

# --- Redis keys (single source of truth; the console health panel reads these) ---
LAST_TICK_KEY = "scheduler:last_tick_at"
"""ISO-8601 timestamp of the most recent (non-disabled) tick."""

SWEPT_COUNTER_PREFIX = "scheduler:swept"
"""Per-UTC-day sweep counter key prefix (``scheduler:swept:{YYYY-MM-DD}``)."""

COOLDOWN_PREFIX = "scheduler:cooldown"
"""Per-customer cooldown key prefix (``scheduler:cooldown:{customer_id}``)."""

_SWEPT_TTL_SECONDS = 60 * 60 * 48
"""Two days: the current UTC day's counter never expires under it, yesterday's self-evicts."""

_JITTER_FRACTION = 0.1
"""Sleep between ticks is ``sweep_interval_seconds`` * (1 +- 10%)."""

_CANDIDATE_POOL_MULTIPLIER = 4
"""Fetch a small buffer of DB-eligible candidates beyond the batch so per-customer
Redis-cooldown skips don't under-fill a tick."""


@dataclass(slots=True)
class SweepTickResult:
    """Outcome of one :func:`run_scheduler_tick` call (returned for tests/logging)."""

    reason: str  # "ok" | "disabled" | "budget" | "daily_cap"
    swept: list[str] = field(default_factory=list)


def _swept_key(now: datetime) -> str:
    return f"{SWEPT_COUNTER_PREFIX}:{now.astimezone(UTC).date().isoformat()}"


def _cooldown_key(customer_id: uuid.UUID | str) -> str:
    return f"{COOLDOWN_PREFIX}:{customer_id}"


def cooldown_cutoff(now: datetime | None = None) -> datetime:
    """The ``started_at`` floor for the 'no recent agent run' eligibility test."""
    now = now or datetime.now(UTC)
    return now - timedelta(days=get_settings().sweep_customer_cooldown_days)


def _eligible_where(cutoff: datetime) -> tuple[Any, Any]:
    """The shared WHERE terms: has an account AND no agent run since ``cutoff``."""
    has_account = select(Account.id).where(Account.customer_id == Customer.id).exists()
    recent_run = (
        select(AgentRun.id)
        .where(AgentRun.customer_id == Customer.id, AgentRun.started_at >= cutoff)
        .exists()
    )
    return (has_account, ~recent_run)


async def eligible_candidate_ids(
    session: AsyncSession, *, cutoff: datetime, limit: int
) -> list[uuid.UUID]:
    """Customer ids eligible for a sweep (has account, no agent run since ``cutoff``),
    oldest-created first, capped at ``limit``. Redis cooldown is applied by the caller."""
    stmt = (
        select(Customer.id)
        .where(*_eligible_where(cutoff))
        .order_by(Customer.created_at)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def count_eligible_customers(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Count of currently DB-eligible customers (health ``next_eligible_estimate``).

    Counts the has-account / no-recent-run set; the per-customer Redis cooldown may
    trim a few more at sweep time, so this is an estimate (and an upper bound)."""
    cutoff = cooldown_cutoff(now)
    stmt = select(func.count()).select_from(Customer).where(*_eligible_where(cutoff))
    return int((await session.scalar(stmt)) or 0)


async def swept_today_count(redis: Redis, *, now: datetime | None = None) -> int:
    """Number of sweeps performed on ``now``'s UTC day (0 on any read failure)."""
    now = now or datetime.now(UTC)
    try:
        raw = await redis.get(_swept_key(now))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("scheduler_swept_read_failed", error=str(exc))
        return 0
    try:
        return int(raw or 0)
    except (TypeError, ValueError):  # pragma: no cover - malformed counter
        return 0


async def read_last_tick(redis: Redis) -> datetime | None:
    """Parse the last-tick timestamp Redis key (None if unset/malformed)."""
    try:
        raw = await redis.get(LAST_TICK_KEY)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("scheduler_last_tick_read_failed", error=str(exc))
        return None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:  # pragma: no cover - malformed timestamp
        return None


async def _acquire_cooldown(redis: Redis, customer_id: uuid.UUID) -> bool:
    """``SETNX``+TTL: True if this call won the per-customer cooldown window."""
    ttl = max(1, get_settings().sweep_customer_cooldown_days) * 24 * 60 * 60
    acquired = await redis.set(_cooldown_key(customer_id), "1", ex=ttl, nx=True)
    return bool(acquired)


async def _increment_swept(redis: Redis, now: datetime) -> None:
    key = _swept_key(now)
    await redis.incr(key)
    await redis.expire(key, _SWEPT_TTL_SECONDS)


async def _run_sweep(customer_id: uuid.UUID) -> AgentRunResult:
    """Run the adoption path for one customer under the shared agent-run semaphore."""
    from app.workers.event_consumer import _agent_run_semaphore

    async with _agent_run_semaphore():
        return await run_event_trigger(
            str(customer_id),
            SWEEP_EVENT_SUMMARY,
            trigger=AgentTriggerType.SCHEDULED,
        )


async def run_scheduler_tick() -> SweepTickResult:
    """Run exactly one sweep tick. Returns what it did (drive this directly in tests).

    Order of guards: disabled -> record liveness -> standing instructions (budget
    independent) -> budget -> daily cap -> select -> per-customer (kill switch,
    daily-cap re-check, Redis cooldown) -> run.
    """
    settings = get_settings()
    # Effective master switch: a Redis runtime override (set from the console)
    # takes precedence over the static config, so the loop can be paused live
    # without a redeploy. Redis down -> falls back to the static flag.
    if not await runtime_settings.scheduler_enabled():
        logger.debug("scheduler_tick_skipped_disabled")
        return SweepTickResult(reason="disabled")

    redis = get_redis()
    now = datetime.now(UTC)
    # Record liveness for the health panel before any early return below.
    try:
        await redis.set(LAST_TICK_KEY, now.isoformat())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("scheduler_last_tick_write_failed", error=str(exc))

    # Standing instructions run first and unconditionally (subject only to their own
    # kill switch): they post real ledger debits with no LLM cost, so neither the
    # daily budget pause nor the sweep caps below must ever block them. Keeping this
    # ahead of the budget/daily-cap early returns is what lets recurring auto-transfers
    # keep firing even on a tick where the LLM sweep is paused for spend.
    await _execute_standing_instructions(redis)

    # Daily LLM budget guard: pause the whole tick quietly when over budget.
    try:
        await get_router().raise_if_over_budget()
    except BudgetExceeded as exc:
        logger.info("scheduler_tick_budget_paused", error=str(exc))
        return SweepTickResult(reason="budget")

    swept_today = await swept_today_count(redis, now=now)
    if swept_today >= settings.sweep_daily_cap:
        logger.info(
            "scheduler_tick_daily_cap_reached",
            cap=settings.sweep_daily_cap,
            swept_today=swept_today,
        )
        return SweepTickResult(reason="daily_cap")

    batch = min(settings.sweep_batch_size, settings.sweep_daily_cap - swept_today)
    cutoff = cooldown_cutoff(now)

    sm = get_sessionmaker()
    async with sm() as session:
        candidates = await eligible_candidate_ids(
            session, cutoff=cutoff, limit=max(batch * _CANDIDATE_POOL_MULTIPLIER, batch)
        )

    swept: list[str] = []
    for customer_id in candidates:
        if len(swept) >= batch:
            break
        # Kill switch honored mid-tick (re-read the live effective value, so a
        # console toggle mid-sweep stops it between customers).
        if not await runtime_settings.scheduler_enabled():
            logger.info("scheduler_kill_switch_mid_tick", swept=len(swept))
            break
        # Daily-cap re-check (defensive against a concurrent instance/tick).
        if await swept_today_count(redis, now=now) >= settings.sweep_daily_cap:
            logger.info("scheduler_daily_cap_reached_mid_tick", swept=len(swept))
            break
        if not await _acquire_cooldown(redis, customer_id):
            logger.debug("scheduler_customer_cooldown_active", customer_id=str(customer_id))
            continue
        try:
            result = await _run_sweep(customer_id)
        except BudgetExceeded as exc:
            # Spend crossed the cap mid-tick: pause quietly, no dead-letter.
            logger.info("scheduler_run_budget_paused", customer_id=str(customer_id), error=str(exc))
            return SweepTickResult(reason="budget", swept=swept)
        except Exception as exc:
            logger.exception(
                "scheduler_sweep_failed", customer_id=str(customer_id), error=str(exc)
            )
            continue
        await _increment_swept(redis, now)
        swept.append(str(customer_id))
        logger.info(
            "scheduler_customer_swept",
            customer_id=str(customer_id),
            run_id=result.run_id,
            status=result.status,
        )

    # Memory maintenance: prune stale episodic memories once per tick. DB-only (no
    # LLM, no spend), tiny, and fully guarded so it can never destabilise the sweep.
    try:
        async with sm() as session:
            pruned = await prune_memories(session)
            await session.commit()
        if pruned:
            logger.info("scheduler_memory_pruned", pruned=pruned)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("scheduler_memory_prune_failed", error=str(exc))

    # Savings-goal achievement: flip any goal that has reached target and notify
    # the customer. DB-only (no LLM, no spend), guarded exactly like the prune
    # above so a goal-eval failure can never destabilise the sweep.
    try:
        async with sm() as session:
            achieved = await evaluate_all_active_goals(session)
            await session.commit()
        if achieved:
            logger.info("scheduler_goals_achieved", achieved=achieved)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("scheduler_goal_eval_failed", error=str(exc))

    logger.info(
        "scheduler_tick_complete", swept=len(swept), batch=batch, candidates=len(candidates)
    )
    return SweepTickResult(reason="ok", swept=swept)


async def _execute_standing_instructions(redis: Redis) -> None:
    """Run any due standing instructions (recurring auto-transfers).

    DB-only: real ledger debits, no LLM and no spend, so it is deliberately NOT
    gated by the daily budget or sweep caps - it runs on every enabled tick, even
    one where the LLM sweep is paused for budget. Its own kill switch
    (``standing_instructions_enabled``) disables just this sub-step. Guarded exactly
    like the goal/prune hooks so an execution failure can never destabilise the tick.
    """
    if not await runtime_settings.standing_instructions_enabled():
        logger.debug("scheduler_standing_disabled")
        return
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            executed = await execute_due_instructions(session, redis)
            await session.commit()
        if executed:
            logger.info("scheduler_standing_executed", executed=executed)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("scheduler_standing_exec_failed", error=str(exc))


def _jittered_interval() -> float:
    base = float(get_settings().sweep_interval_seconds)
    return base * (1.0 + random.uniform(-_JITTER_FRACTION, _JITTER_FRACTION))


async def run_scheduler_forever(stop_event: asyncio.Event) -> None:
    """Sibling loop: run a tick, then sleep a jittered interval (waking early on stop)."""
    logger.info(
        "scheduler_started",
        enabled=get_settings().scheduler_enabled,
        interval_s=get_settings().sweep_interval_seconds,
    )
    while not stop_event.is_set():
        try:
            await run_scheduler_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduler_loop_error")
        delay = _jittered_interval()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
    logger.info("scheduler_stopped")
