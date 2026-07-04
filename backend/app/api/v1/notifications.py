"""Customer-facing notification inbox (auth required, ownership enforced)."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.customer import Customer
from app.models.engagement import Notification
from app.models.identity import User
from app.schemas.customer import (
    NotificationListResponse,
    NotificationOut,
    NotificationReadRequest,
    NotificationReadResponse,
)

from .customers import _customer_for_user_or_404

router = APIRouter(prefix="/me/notifications", tags=["notifications"])

_DEFAULT_LIMIT = 30
_MAX_LIMIT = 100


async def _unread_count(db: AsyncSession, customer: Customer) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.customer_id == customer.id, Notification.read.is_(False))
    )
    return int(count or 0)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
) -> NotificationListResponse:
    customer = await _customer_for_user_or_404(db, user)
    result = await db.execute(
        select(Notification)
        .where(Notification.customer_id == customer.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    notifications = result.scalars().all()
    return NotificationListResponse(
        notifications=[NotificationOut.model_validate(n) for n in notifications],
        unread=await _unread_count(db, customer),
    )


@router.post("/read", response_model=NotificationReadResponse)
async def mark_notifications_read(
    payload: NotificationReadRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> NotificationReadResponse:
    customer = await _customer_for_user_or_404(db, user)

    # Ownership is enforced in the WHERE clause: only this customer's rows are
    # ever touched, so an id belonging to someone else is silently a no-op.
    stmt = (
        update(Notification)
        .where(Notification.customer_id == customer.id, Notification.read.is_(False))
        .values(read=True)
    )
    if not payload.mark_all:
        if not payload.ids:
            return NotificationReadResponse(marked=0, unread=await _unread_count(db, customer))
        stmt = stmt.where(Notification.id.in_(payload.ids))

    result = cast("CursorResult[Any]", await db.execute(stmt))
    marked = max(result.rowcount, 0)
    return NotificationReadResponse(marked=marked, unread=await _unread_count(db, customer))
