"""Customer standing-instructions API (``/me/standing-instructions``, auth required).

Recurring auto-transfers a customer manages themselves. Ownership is enforced on
every path; the same :mod:`app.services.standing` guards the agent-approved
proposal path uses apply here, so there is no divergent logic.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.identity import User
from app.schemas.standing import (
    StandingInstructionCreateRequest,
    StandingInstructionListResponse,
    StandingInstructionOut,
    StandingInstructionUpdateRequest,
)
from app.services import standing

from .customers import _customer_for_user_or_404

router = APIRouter(prefix="/me/standing-instructions", tags=["standing-instructions"])


@router.get("", response_model=StandingInstructionListResponse)
async def list_standing_instructions(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> StandingInstructionListResponse:
    customer = await _customer_for_user_or_404(db, user)
    views = await standing.list_for_customer(db, customer.id)
    active = await standing.count_active(db, customer.id)
    return StandingInstructionListResponse(
        instructions=[StandingInstructionOut.from_view(v) for v in views],
        active_count=active,
        max_active=standing.MAX_ACTIVE,
    )


@router.post("", response_model=StandingInstructionOut, status_code=201)
async def create_standing_instruction(
    payload: StandingInstructionCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> StandingInstructionOut:
    customer = await _customer_for_user_or_404(db, user)
    try:
        instruction = await standing.create_standing_instruction(
            db,
            customer_id=customer.id,
            from_account_id=payload.from_account_id,
            purpose=payload.purpose,
            goal_id=payload.goal_id,
            amount_paise=payload.amount_paise,
            cadence=payload.cadence,
            start_date=payload.start_date,
        )
    except standing.StandingLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except standing.StandingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    views = await standing.list_for_customer(db, customer.id)
    for view in views:
        if view.instruction.id == instruction.id:
            return StandingInstructionOut.from_view(view)
    # Unreachable in practice (we just created it); fall back to a goal-less view.
    return StandingInstructionOut.from_view(
        standing.StandingInstructionView(instruction=instruction, goal_name=None)
    )


@router.patch("/{instruction_id}", response_model=StandingInstructionOut)
async def update_standing_instruction(
    instruction_id: uuid.UUID,
    payload: StandingInstructionUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> StandingInstructionOut:
    customer = await _customer_for_user_or_404(db, user)
    try:
        instruction = await standing.set_status(
            db,
            customer_id=customer.id,
            instruction_id=instruction_id,
            action=payload.action,
        )
    except standing.StandingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if instruction is None:
        raise HTTPException(status_code=404, detail="Auto-transfer not found")

    views = await standing.list_for_customer(db, customer.id)
    for view in views:
        if view.instruction.id == instruction.id:
            return StandingInstructionOut.from_view(view)
    return StandingInstructionOut.from_view(
        standing.StandingInstructionView(instruction=instruction, goal_name=None)
    )
