"""Customer-facing spending insights (``GET /me/insights``) - auth required."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.identity import User
from app.schemas.insights import InsightsResponse
from app.services import insights as insights_service

from .customers import _customer_for_user_or_404

router = APIRouter(prefix="/me/insights", tags=["insights"])


@router.get("", response_model=InsightsResponse)
async def get_insights(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    months: Annotated[int, Query(ge=1, le=12)] = 3,
) -> InsightsResponse:
    customer = await _customer_for_user_or_404(db, user)
    breakdown = await insights_service.monthly_breakdown(db, customer.id, months=months)
    trend_data = await insights_service.trends(db, customer.id)
    return InsightsResponse.model_validate(
        {
            "months": breakdown["months"],
            "trends": trend_data,
            "note": breakdown["note"],
        }
    )
