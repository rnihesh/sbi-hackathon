"""Customer-facing ``/me/*`` API surface (auth required)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.catalog import Holding
from app.models.customer import Customer
from app.models.engagement import Nudge
from app.models.enums import NudgeStatus
from app.models.identity import User
from app.schemas.auth import CustomerOut
from app.schemas.customer import (
    AccountOut,
    DashboardResponse,
    HoldingOut,
    ProductOut,
    TransactionOut,
)
from app.services import ledger

router = APIRouter(prefix="/me", tags=["customers"])

_RECENT_TRANSACTIONS_LIMIT = 20


async def _customer_for_user_or_404(db: AsyncSession, user: User) -> Customer:
    result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="No customer profile for this account yet")
    return customer


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    customer = await _customer_for_user_or_404(db, user)

    accounts = await ledger.list_accounts(db, customer.id)

    # Spans every account belonging to the customer (joined on Account.customer_id).
    txns = await ledger.get_latest_transactions(db, customer.id, limit=_RECENT_TRANSACTIONS_LIMIT)

    holdings_result = await db.execute(
        select(Holding)
        .where(Holding.customer_id == customer.id)
        .options(selectinload(Holding.product))
    )
    holdings = holdings_result.scalars().all()

    unseen_count = await db.scalar(
        select(func.count())
        .select_from(Nudge)
        .where(Nudge.customer_id == customer.id, Nudge.status == NudgeStatus.SENT)
    )

    return DashboardResponse(
        customer=CustomerOut.model_validate(customer),
        accounts=[AccountOut.model_validate(a) for a in accounts],
        recent_transactions=[TransactionOut.model_validate(t) for t in txns],
        holdings=[
            HoldingOut(id=h.id, product=ProductOut.model_validate(h.product), status=h.status.value)
            for h in holdings
        ],
        unseen_nudges=int(unseen_count or 0),
    )
