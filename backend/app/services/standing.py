"""Standing instructions: recurring auto-transfers, executed deterministically.

A standing instruction debits a chosen account on a fixed cadence toward a
purpose (a savings ``goal``, a fixed deposit ``fd``, or plain ``savings``). This
module owns both the CRUD surface (shared by the REST API and the agent-approved
proposal path) and the scheduler execution semantics.

Execution semantics (honest, no fabricated numbers):

- The scheduler tick calls :func:`execute_due_instructions`, which finds ``active``
  instructions with ``next_run_date <= today`` (capped at :data:`MAX_PER_TICK`).
- For each, it checks the source account has at least ``amount + `` a
  :data:`FLOOR_BUFFER_PAISE` (Rs 1,000) cushion. If so it posts a REAL debit via
  the ledger (channel ``auto_debit``, merchant "Sarathi Auto-Transfer"). If not,
  it records a "balance too low" notification and skips - it does NOT retry until
  the next cadence date.
- **Goal accounting.** A goal measures balance *growth* since it was set
  (``progress = current_balance - baseline``). A debit reduces the balance, which
  would *reduce* goal progress - penalising the customer for saving toward the
  very goal. To resolve this honestly, a ``purpose == goal`` run posts the debit
  AND decrements the goal's ``baseline_paise`` by the same amount. Algebraically
  that leaves progress unchanged by the transfer (``(B-amt) - (base-amt) == B-base``):
  the cash simply moves from the spendable balance into the goal envelope rather
  than being destroyed. Only genuine new balance growth still advances the goal.
- Every run advances ``next_run_date`` by the cadence and, on a successful debit,
  bumps ``runs_count`` and stamps ``last_run_at``.
- **Idempotency.** Before acting on an instruction the tick takes a Redis
  ``SETNX`` lock keyed by ``(instruction_id, due_date)`` so a duplicate/overlapping
  tick cannot double-post the same run. The key carries a short TTL so a crashed
  tick self-heals.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.banking import Account
from app.models.enums import (
    AccountStatus,
    GoalStatus,
    NotificationKind,
    StandingCadence,
    StandingPurpose,
    StandingStatus,
    TxnChannel,
    TxnDirection,
)
from app.models.goal import SavingsGoal
from app.models.standing import StandingInstruction
from app.services import ledger
from app.services.notifications import notify

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

FLOOR_BUFFER_PAISE = 1_000 * 100
"""A Rs 1,000 cushion left untouched: a run only fires if balance >= amount + this."""

MAX_ACTIVE = 5
"""A customer may hold at most this many non-terminal (active/paused) instructions."""

MAX_PER_TICK = 20
"""Hard cap on instructions executed per scheduler tick (spend/load safety rail)."""

_IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24 * 3
"""Idempotency lock lives 3 days: long enough to stop a same-day double-post, short
enough that a crashed (uncommitted) tick self-heals before the next cadence date."""

_ACTIVE_STATES = (StandingStatus.ACTIVE, StandingStatus.PAUSED)


class StandingError(Exception):
    """Raised on an invalid standing-instruction operation (bad input)."""


class StandingLimitError(StandingError):
    """The customer is already at the :data:`MAX_ACTIVE` instruction cap."""


@dataclass(slots=True)
class StandingInstructionView:
    """An instruction paired with its linked goal name (``None`` for fd/savings)."""

    instruction: StandingInstruction
    goal_name: str | None


def _today() -> date:
    return datetime.now(UTC).date()


def advance_date(current: date, cadence: StandingCadence) -> date:
    """Return the next run date one ``cadence`` period after ``current``.

    Weekly adds 7 days; monthly adds one calendar month, clamping the day to the
    target month's length (e.g. Jan 31 -> Feb 28)."""
    if cadence is StandingCadence.WEEKLY:
        return current + timedelta(days=7)
    month = current.month + 1
    year = current.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(current.day, last_day))


def _coerce_purpose(purpose: StandingPurpose | str) -> StandingPurpose:
    try:
        return purpose if isinstance(purpose, StandingPurpose) else StandingPurpose(purpose)
    except ValueError as exc:
        raise StandingError(f"unknown purpose {purpose!r}") from exc


def _coerce_cadence(cadence: StandingCadence | str) -> StandingCadence:
    try:
        return cadence if isinstance(cadence, StandingCadence) else StandingCadence(cadence)
    except ValueError as exc:
        raise StandingError(f"unknown cadence {cadence!r}") from exc


def purpose_label(instruction: StandingInstruction, goal_name: str | None) -> str:
    """Human-readable label for a run's transaction description / notifications."""
    if instruction.purpose is StandingPurpose.GOAL:
        return f"goal '{goal_name}'" if goal_name else "savings goal"
    if instruction.purpose is StandingPurpose.FD:
        return "fixed deposit"
    return "savings"


async def count_active(session: AsyncSession, customer_id: uuid.UUID) -> int:
    """Count a customer's non-terminal (active or paused) instructions."""
    count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(StandingInstruction)
        .where(
            StandingInstruction.customer_id == customer_id,
            StandingInstruction.status.in_(_ACTIVE_STATES),
        )
    )
    return int(count or 0)


async def create_standing_instruction(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    from_account_id: uuid.UUID,
    purpose: StandingPurpose | str,
    amount_paise: int,
    cadence: StandingCadence | str,
    goal_id: uuid.UUID | None = None,
    start_date: date | None = None,
) -> StandingInstruction:
    """Create an active standing instruction after validating ownership + guards.

    Raises :class:`StandingLimitError` at the active cap and :class:`StandingError`
    on any invalid input (bad account/goal, amount too large, missing goal link).
    """
    purpose = _coerce_purpose(purpose)
    cadence = _coerce_cadence(cadence)

    if amount_paise <= 0:
        raise StandingError("transfer amount must be positive")

    account = await session.get(Account, from_account_id)
    if account is None or account.customer_id != customer_id:
        raise StandingError("source account not found")
    if account.status is AccountStatus.CLOSED:
        raise StandingError("source account is closed")

    # Sanity guard: never let a single recurring transfer exceed half the account's
    # current balance at setup - a standing instruction is disciplined saving, not
    # a way to drain the account in two runs.
    if amount_paise > account.balance_paise // 2:
        raise StandingError(
            "transfer amount cannot exceed 50% of the account balance at setup"
        )

    if purpose is StandingPurpose.GOAL:
        if goal_id is None:
            raise StandingError("a goal-linked auto-transfer needs a goal")
        goal = await session.get(SavingsGoal, goal_id)
        if goal is None or goal.customer_id != customer_id:
            raise StandingError("goal not found")
        if goal.status is not GoalStatus.ACTIVE:
            raise StandingError("goal is not active")
    else:
        goal_id = None  # fd / savings never carry a goal link

    if await count_active(session, customer_id) >= MAX_ACTIVE:
        raise StandingLimitError(
            f"you already have {MAX_ACTIVE} active auto-transfers - "
            "pause or cancel one to add another"
        )

    instruction = StandingInstruction(
        customer_id=customer_id,
        from_account_id=from_account_id,
        purpose=purpose,
        goal_id=goal_id,
        amount_paise=amount_paise,
        cadence=cadence,
        next_run_date=start_date or _today(),
        status=StandingStatus.ACTIVE,
    )
    session.add(instruction)
    await session.flush()
    return instruction


async def list_for_customer(
    session: AsyncSession, customer_id: uuid.UUID
) -> list[StandingInstructionView]:
    """Return a customer's non-cancelled instructions (newest first) with goal name."""
    rows = (
        await session.execute(
            sa.select(StandingInstruction, SavingsGoal.name)
            .join(
                SavingsGoal,
                SavingsGoal.id == StandingInstruction.goal_id,
                isouter=True,
            )
            .where(
                StandingInstruction.customer_id == customer_id,
                StandingInstruction.status != StandingStatus.CANCELLED,
            )
            .order_by(StandingInstruction.created_at.desc())
        )
    ).all()
    return [StandingInstructionView(instruction=si, goal_name=name) for si, name in rows]


async def _owned_or_none(
    session: AsyncSession, customer_id: uuid.UUID, instruction_id: uuid.UUID
) -> StandingInstruction | None:
    instruction = await session.get(StandingInstruction, instruction_id)
    if instruction is None or instruction.customer_id != customer_id:
        return None
    return instruction


async def set_status(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    instruction_id: uuid.UUID,
    action: str,
) -> StandingInstruction | None:
    """Apply a ``pause`` / ``resume`` / ``cancel`` transition. Returns ``None`` if
    the instruction is not owned by ``customer_id`` (caller maps that to 404)."""
    instruction = await _owned_or_none(session, customer_id, instruction_id)
    if instruction is None:
        return None

    if action == "pause":
        if instruction.status is StandingStatus.ACTIVE:
            instruction.status = StandingStatus.PAUSED
        elif instruction.status is not StandingStatus.PAUSED:
            raise StandingError(f"cannot pause a {instruction.status.value} auto-transfer")
    elif action == "resume":
        if instruction.status is StandingStatus.PAUSED:
            instruction.status = StandingStatus.ACTIVE
            # Never fire a backlog of missed runs: resume from today onward.
            if instruction.next_run_date < _today():
                instruction.next_run_date = _today()
        elif instruction.status is not StandingStatus.ACTIVE:
            raise StandingError(f"cannot resume a {instruction.status.value} auto-transfer")
    elif action == "cancel":
        instruction.status = StandingStatus.CANCELLED
    else:
        raise StandingError(f"unknown action {action!r}")

    await session.flush()
    return instruction


# ---------------------------------------------------------------------------
# Scheduler execution
# ---------------------------------------------------------------------------


def _idempotency_key(instruction_id: uuid.UUID, due: date) -> str:
    return f"standing:exec:{instruction_id}:{due.isoformat()}"


async def _acquire_run_lock(redis: Redis, instruction_id: uuid.UUID, due: date) -> bool:
    """SETNX+TTL guard so overlapping ticks never double-post the same run."""
    acquired = await redis.set(
        _idempotency_key(instruction_id, due), "1", ex=_IDEMPOTENCY_TTL_SECONDS, nx=True
    )
    return bool(acquired)


async def _resolve_goal(
    session: AsyncSession, instruction: StandingInstruction
) -> tuple[SavingsGoal | None, str | None]:
    """For a goal-linked instruction, load its goal and return ``(goal, terminal)``.

    ``terminal`` is a non-None :class:`StandingStatus` value when the linked goal is
    gone or no longer active, telling the caller to close the instruction instead of
    debiting.
    """
    if instruction.goal_id is None:
        return None, None
    goal = await session.get(SavingsGoal, instruction.goal_id)
    if goal is None:
        return None, StandingStatus.CANCELLED.value
    if goal.status is GoalStatus.ACHIEVED:
        return goal, StandingStatus.COMPLETED.value
    if goal.status is not GoalStatus.ACTIVE:  # archived
        return goal, StandingStatus.CANCELLED.value
    return goal, None


async def _run_one(
    session: AsyncSession, instruction: StandingInstruction, goal: SavingsGoal | None
) -> bool:
    """Execute a single due instruction. Returns True if a debit was posted."""
    account = await session.get(Account, instruction.from_account_id)
    label = purpose_label(instruction, goal.name if goal else None)

    if account is None or account.status is AccountStatus.CLOSED:
        # Source account vanished/closed: stop the instruction honestly.
        instruction.status = StandingStatus.CANCELLED
        await notify(
            session,
            instruction.customer_id,
            NotificationKind.SYSTEM,
            "Auto-transfer stopped",
            (
                f"Your recurring transfer toward {label} was stopped - "
                "the source account is no longer available."
            ),
            link="/app/home",
        )
        return False

    if account.balance_paise < instruction.amount_paise + FLOOR_BUFFER_PAISE:
        # Insufficient balance: skip this run, notify, wait for the next cadence date.
        await notify(
            session,
            instruction.customer_id,
            NotificationKind.SYSTEM,
            "Auto-transfer skipped - balance too low",
            (
                f"We skipped your ₹{instruction.amount_paise // 100:,} transfer toward {label} "
                "to keep a ₹1,000 cushion in your account. We'll try again next cycle."
            ),
            link="/app/home",
        )
        instruction.next_run_date = advance_date(instruction.next_run_date, instruction.cadence)
        return False

    await ledger.post_transaction(
        session,
        account_id=account.id,
        amount_paise=instruction.amount_paise,
        direction=TxnDirection.DEBIT,
        channel=TxnChannel.AUTO_DEBIT,
        merchant="Sarathi Auto-Transfer",
        category="standing_instruction",
        description=f"Auto-transfer toward {label}",
    )

    # Goal envelope accounting (see the module docstring): decrement the goal's
    # baseline by the same amount so moving cash into the goal does not read as a
    # loss of goal progress.
    if goal is not None:
        goal.baseline_paise = goal.baseline_paise - instruction.amount_paise

    instruction.runs_count += 1
    instruction.last_run_at = datetime.now(UTC)
    instruction.next_run_date = advance_date(instruction.next_run_date, instruction.cadence)
    return True


async def execute_due_instructions(session: AsyncSession, redis: Redis) -> int:
    """Run all due standing instructions (scheduler hook). Returns debits posted.

    Mirrors :func:`app.services.goals.evaluate_all_active_goals` and
    :func:`app.agents.memory.prune_memories`: DB-only (no LLM, no spend), fully
    guarded by the caller, and it flushes but does not commit - the scheduler owns
    the surrounding transaction.
    """
    today = _today()
    due = (
        await session.scalars(
            sa.select(StandingInstruction)
            .where(
                StandingInstruction.status == StandingStatus.ACTIVE,
                StandingInstruction.next_run_date <= today,
            )
            .order_by(StandingInstruction.next_run_date, StandingInstruction.created_at)
            .limit(MAX_PER_TICK)
        )
    ).all()

    executed = 0
    for instruction in due:
        due_date = instruction.next_run_date
        if not await _acquire_run_lock(redis, instruction.id, due_date):
            logger.debug("standing_run_lock_held", instruction_id=str(instruction.id))
            continue

        goal, terminal = await _resolve_goal(session, instruction)
        if terminal is not None:
            instruction.status = StandingStatus(terminal)
            label = purpose_label(instruction, goal.name if goal else None)
            title = (
                "Goal reached - auto-transfer completed"
                if terminal == StandingStatus.COMPLETED.value
                else "Auto-transfer stopped"
            )
            await notify(
                session,
                instruction.customer_id,
                NotificationKind.SYSTEM,
                title,
                f"Your recurring transfer toward {label} has ended.",
                link="/app/home",
            )
            continue

        if await _run_one(session, instruction, goal):
            executed += 1

    if due:
        await session.flush()
    return executed
