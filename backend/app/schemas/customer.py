"""Pydantic v2 schemas for the customer-facing ``/me/*`` API surface."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import CustomerOut


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    balance_paise: int
    status: str


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ts: datetime
    amount_paise: int
    direction: str
    channel: str
    merchant: str | None
    category: str | None
    description: str | None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    category: str


class HoldingOut(BaseModel):
    id: uuid.UUID
    product: ProductOut
    status: str


class DashboardResponse(BaseModel):
    customer: CustomerOut
    accounts: list[AccountOut]
    recent_transactions: list[TransactionOut]
    holdings: list[HoldingOut]
    unseen_nudges: int


class NudgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    cta: dict[str, object]
    status: str
    created_at: datetime


class NudgeListResponse(BaseModel):
    nudges: list[NudgeOut]


class NudgeActRequest(BaseModel):
    action: Literal["seen", "acted", "dismissed"] = Field(...)
