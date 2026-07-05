"""Customer savings-goals API (``/me/goals``, auth required, ownership enforced).

Read paths evaluate achievement lazily (a goal that just crossed its target is
returned already ``achieved`` and its "Goal achieved!" notification is written)
so progress is always honest without a background job in the loop.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.customer import Customer
from app.models.enums import GoalStatus
from app.models.goal import SavingsGoal
from app.models.identity import User
from app.schemas.goals import (
    GoalCreateRequest,
    GoalListResponse,
    GoalOut,
    GoalUpdateRequest,
)
from app.services import goals, ledger

from .customers import _customer_for_user_or_404

router = APIRouter(prefix="/me/goals", tags=["goals"])


async def _goal_owned_or_404(
    db: AsyncSession, customer: Customer, goal_id: uuid.UUID
) -> SavingsGoal:
    goal = await db.get(SavingsGoal, goal_id)
    if goal is None or goal.customer_id != customer.id:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


async def _goal_out(db: AsyncSession, customer_id: uuid.UUID, goal: SavingsGoal) -> GoalOut:
    balance = await ledger.get_customer_balance(db, customer_id)
    progress, pct = goals.compute_progress(goal, balance)
    return GoalOut.from_progress(goals.GoalProgress(goal, progress, pct))


@router.get("", response_model=GoalListResponse)
async def list_goals(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> GoalListResponse:
    customer = await _customer_for_user_or_404(db, user)
    progresses = await goals.list_goals_with_progress(db, customer.id)
    active = sum(1 for p in progresses if p.goal.status == GoalStatus.ACTIVE)
    return GoalListResponse(
        goals=[GoalOut.from_progress(p) for p in progresses],
        active_count=active,
        max_active=goals.MAX_ACTIVE_GOALS,
    )


@router.post("", response_model=GoalOut, status_code=201)
async def create_goal(
    payload: GoalCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> GoalOut:
    customer = await _customer_for_user_or_404(db, user)
    try:
        goal = await goals.create_goal(
            db,
            customer_id=customer.id,
            name=payload.name,
            target_paise=payload.target_paise,
            target_date=payload.target_date,
        )
    except goals.GoalLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except goals.GoalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _goal_out(db, customer.id, goal)


@router.patch("/{goal_id}", response_model=GoalOut)
async def update_goal(
    goal_id: uuid.UUID,
    payload: GoalUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> GoalOut:
    customer = await _customer_for_user_or_404(db, user)
    goal = await _goal_owned_or_404(db, customer, goal_id)

    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        goal.name = payload.name
    if "target_date" in fields:
        goal.target_date = payload.target_date
    if "status" in fields and payload.status is not None:
        # Only "archived" is reachable (validated by the Literal on the schema).
        goal.status = GoalStatus.ARCHIVED
    await db.flush()
    return await _goal_out(db, customer.id, goal)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    customer = await _customer_for_user_or_404(db, user)
    goal = await _goal_owned_or_404(db, customer, goal_id)
    await db.delete(goal)
    await db.flush()
