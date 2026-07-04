"""Customer-facing nudge inbox (auth required)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.customer import Customer
from app.models.engagement import Nudge
from app.models.enums import NudgeStatus
from app.models.identity import User
from app.schemas.customer import NudgeActRequest, NudgeListResponse, NudgeOut

router = APIRouter(prefix="/me/nudges", tags=["nudges"])

_ACTION_TO_STATUS: dict[str, NudgeStatus] = {
    "seen": NudgeStatus.SEEN,
    "acted": NudgeStatus.ACTED,
    "dismissed": NudgeStatus.DISMISSED,
}


async def _customer_for_user_or_404(db: AsyncSession, user: User) -> Customer:
    result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="No customer profile for this account yet")
    return customer


@router.get("", response_model=NudgeListResponse)
async def list_nudges(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> NudgeListResponse:
    customer = await _customer_for_user_or_404(db, user)
    result = await db.execute(
        select(Nudge)
        .where(Nudge.customer_id == customer.id)
        .order_by(Nudge.created_at.desc())
    )
    nudges = result.scalars().all()
    return NudgeListResponse(nudges=[NudgeOut.model_validate(n) for n in nudges])


@router.post("/{nudge_id}/act", response_model=NudgeOut)
async def act_on_nudge(
    nudge_id: uuid.UUID,
    payload: NudgeActRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> NudgeOut:
    customer = await _customer_for_user_or_404(db, user)
    nudge = await db.get(Nudge, nudge_id)
    if nudge is None:
        raise HTTPException(status_code=404, detail="Nudge not found")
    if nudge.customer_id != customer.id:
        raise HTTPException(status_code=403, detail="Not your nudge")

    nudge.status = _ACTION_TO_STATUS[payload.action]
    await db.flush()
    return NudgeOut.model_validate(nudge)
