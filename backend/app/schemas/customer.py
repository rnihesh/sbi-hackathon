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


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationOut]
    unread: int


class NotificationReadRequest(BaseModel):
    """Mark notifications read by id, or every unread one with ``all=true``."""

    model_config = ConfigDict(populate_by_name=True)

    ids: list[uuid.UUID] = Field(default_factory=list)
    # ``all`` shadows a builtin, so expose it under a safe attribute name while
    # keeping the wire key ``all`` the frontend sends.
    mark_all: bool = Field(default=False, alias="all")


class NotificationReadResponse(BaseModel):
    marked: int
    unread: int
