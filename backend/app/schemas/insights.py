"""Pydantic v2 schemas for ``GET /me/insights`` (spending insights)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CategoryBreakdownOut(BaseModel):
    category: str
    amount_paise: int
    share_pct: float
    txn_count: int


class MonthlyInsightOut(BaseModel):
    month: str
    total_in_paise: int
    total_out_paise: int
    by_category: list[CategoryBreakdownOut]


class TopCategoryChangeOut(BaseModel):
    category: str
    prev_paise: int
    curr_paise: int
    delta_pct: float | None


class LargestTransactionOut(BaseModel):
    amount_paise: int
    merchant: str | None
    category: str | None
    ts: datetime


class RecurringMerchantOut(BaseModel):
    merchant: str
    monthly_avg_paise: int
    count: int


class InsightsTrendsOut(BaseModel):
    top_category_change: TopCategoryChangeOut | None
    largest_txn_30d: LargestTransactionOut | None
    recurring: list[RecurringMerchantOut]


class InsightsResponse(BaseModel):
    months: list[MonthlyInsightOut]
    trends: InsightsTrendsOut
    note: str | None
