"""Savings goals: creation, progress computation, and achievement evaluation.

Progress model (deterministic and honest). A goal records the customer's total
balance across their (non-closed) accounts at creation time as
``baseline_paise``. Progress is then::

    progress_paise = max(0, current_total_balance - baseline_paise)

i.e. how much the balance has grown since the goal was set. There is no
per-goal earmarking of funds, so multiple concurrent goals SHARE the same
balance growth - the UI states this plainly ("progress reflects balance growth
since the goal was set"). A goal is achieved the moment progress reaches its
target; achievement is evaluated lazily on every read and once per scheduler
tick, never fabricated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import GoalStatus, NotificationKind
from app.models.goal import SavingsGoal
from app.services import ledger
from app.services.notifications import notify

MAX_ACTIVE_GOALS = 5
"""A customer may hold at most this many ``active`` goals at once."""

NAME_MAX = 80
"""Mirror of ``SavingsGoal.name`` column width."""


class GoalError(Exception):
    """Raised on an invalid goal operation (bad input)."""


class GoalLimitError(GoalError):
    """The customer already has :data:`MAX_ACTIVE_GOALS` active goals."""


@dataclass(slots=True)
class GoalProgress:
    """A goal paired with its computed progress (paise + percentage)."""

    goal: SavingsGoal
    progress_paise: int
    pct: float


def compute_progress(goal: SavingsGoal, current_balance_paise: int) -> tuple[int, float]:
    """Return ``(progress_paise, pct)`` for ``goal`` at the given total balance.

    ``pct`` is clamped to ``0..100`` (an over-target balance still reads 100%).
    """
    progress = max(0, current_balance_paise - goal.baseline_paise)
    if goal.target_paise <= 0:
        return progress, 0.0
    pct = round(min(100.0, progress / goal.target_paise * 100), 1)
    return progress, pct


async def count_active_goals(session: AsyncSession, customer_id: uuid.UUID) -> int:
    """Count a customer's currently ``active`` goals."""
    count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(SavingsGoal)
        .where(
            SavingsGoal.customer_id == customer_id,
            SavingsGoal.status == GoalStatus.ACTIVE,
        )
    )
    return int(count or 0)


async def create_goal(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    name: str,
    target_paise: int,
    target_date: date | None = None,
) -> SavingsGoal:
    """Create an active goal, capturing the balance baseline.

    Raises :class:`GoalError` on invalid input and :class:`GoalLimitError`
    when the customer is already at the active-goal cap.
    """
    name = (name or "").strip()
    if not name:
        raise GoalError("goal name is required")
    if len(name) > NAME_MAX:
        raise GoalError(f"goal name must be at most {NAME_MAX} characters")
    if target_paise <= 0:
        raise GoalError("target amount must be positive")

    if await count_active_goals(session, customer_id) >= MAX_ACTIVE_GOALS:
        raise GoalLimitError(
            f"you already have {MAX_ACTIVE_GOALS} active goals - archive one to add another"
        )

    baseline = await ledger.get_customer_balance(session, customer_id)
    goal = SavingsGoal(
        customer_id=customer_id,
        name=name,
        target_paise=target_paise,
        baseline_paise=baseline,
        target_date=target_date,
        status=GoalStatus.ACTIVE,
    )
    session.add(goal)
    await session.flush()
    return goal


async def _mark_achieved(session: AsyncSession, goal: SavingsGoal) -> None:
    """Flip a goal to ``achieved`` and record the customer notification."""
    goal.status = GoalStatus.ACHIEVED
    goal.achieved_at = datetime.now(UTC)
    await notify(
        session,
        goal.customer_id,
        NotificationKind.SYSTEM,
        "Goal achieved!",
        f"You reached your savings goal '{goal.name}'. Well done.",
        link="/app/home",
    )


async def evaluate_customer_goals(
    session: AsyncSession,
    customer_id: uuid.UUID,
    *,
    current_balance: int | None = None,
) -> int:
    """Flip any of a customer's active goals that have reached target.

    Returns the number newly marked achieved. Idempotent: an already-achieved
    goal is never re-notified.
    """
    if current_balance is None:
        current_balance = await ledger.get_customer_balance(session, customer_id)

    active = (
        await session.scalars(
            sa.select(SavingsGoal).where(
                SavingsGoal.customer_id == customer_id,
                SavingsGoal.status == GoalStatus.ACTIVE,
            )
        )
    ).all()

    flipped = 0
    for goal in active:
        progress, _ = compute_progress(goal, current_balance)
        if progress >= goal.target_paise:
            await _mark_achieved(session, goal)
            flipped += 1
    if flipped:
        await session.flush()
    return flipped


async def list_goals_with_progress(
    session: AsyncSession, customer_id: uuid.UUID
) -> list[GoalProgress]:
    """Return a customer's non-archived goals (newest first) with live progress.

    Evaluates achievement first (lazy flip) so a goal that just crossed its
    target is returned already ``achieved``.
    """
    balance = await ledger.get_customer_balance(session, customer_id)
    await evaluate_customer_goals(session, customer_id, current_balance=balance)

    goals = (
        await session.scalars(
            sa.select(SavingsGoal)
            .where(
                SavingsGoal.customer_id == customer_id,
                SavingsGoal.status != GoalStatus.ARCHIVED,
            )
            .order_by(SavingsGoal.created_at.desc())
        )
    ).all()
    return [GoalProgress(g, *compute_progress(g, balance)) for g in goals]


async def evaluate_all_active_goals(session: AsyncSession) -> int:
    """Scheduler hook: evaluate every customer holding active goals (DB-only).

    Mirrors :func:`app.agents.memory.prune_memories` - tiny, LLM-free, and fully
    guarded by the caller. Returns the total number of goals newly achieved.
    """
    customer_ids = (
        await session.scalars(
            sa.select(SavingsGoal.customer_id)
            .where(SavingsGoal.status == GoalStatus.ACTIVE)
            .distinct()
        )
    ).all()

    total = 0
    for customer_id in customer_ids:
        total += await evaluate_customer_goals(session, customer_id)
    return total
