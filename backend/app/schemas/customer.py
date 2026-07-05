"""Pydantic v2 schemas for the customer-facing ``/me/*`` API surface."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.language import SUPPORTED_LANGUAGES
from app.schemas.auth import CustomerOut

# Mirrors `app.agents.acquisition._PHONE_RE` - kept as a separate constant
# (rather than importing) since acquisition's regex is private to that
# module's KYC field validation and the two surfaces evolving independently
# is fine; this is the same Indian mobile shape either way.
_PHONE_RE = re.compile(r"^(?:\+91[\-\s]?|0)?[6-9]\d{9}$")


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


class ActivityItemOut(BaseModel):
    """One entry in the ``GET /me/activity`` account activity log.

    ``action`` is a short, humanised label (e.g. "Account opened"); ``summary`` is a
    one-line, plain-language sentence with the specifics (e.g. "Your savings account
    was opened."). See ``app.api.v1.customers`` for exactly which audit-log actions are
    surfaced here and why the rest are excluded.
    """

    ts: datetime
    action: str
    summary: str


class ActivityResponse(BaseModel):
    activity: list[ActivityItemOut]


class PreferencesUpdateRequest(BaseModel):
    """Body for ``PATCH /me/preferences``.

    Every field is optional; the endpoint only touches the ones actually
    present in the request body (partial update via ``model_fields_set``), so
    a client can PATCH a single field without resending the rest.

    - ``preferred_language``: ``None`` means "auto" (the agents follow
      whatever language the customer writes in), or one of
      :data:`SUPPORTED_LANGUAGES`. Anything else is rejected with a 422.
    - ``full_name``: 2-80 chars after stripping. Cannot be cleared with
      ``null`` - the column is not nullable - so an explicit ``null`` is a
      422, not a no-op.
    - ``phone``: an Indian mobile number (same shape the acquisition KYC flow
      accepts), or ``null`` to clear it.
    - ``city``: 2-40 chars after stripping, or ``null`` to clear it.
    """

    preferred_language: str | None = Field(default=None)
    full_name: str | None = Field(default=None)
    phone: str | None = Field(default=None)
    city: str | None = Field(default=None)

    @field_validator("preferred_language")
    @classmethod
    def _validate_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"unsupported language '{value}' - expected one of "
                f"{', '.join(SUPPORTED_LANGUAGES)}"
            )
        return normalized

    @field_validator("full_name")
    @classmethod
    def _validate_full_name(cls, value: str | None) -> str | None:
        # Only runs when the field is explicitly present in the request body
        # (pydantic skips validators on an unset default), so `None` here
        # means the client sent `"full_name": null`, which isn't supported.
        if value is None:
            raise ValueError("full_name cannot be cleared")
        stripped = value.strip()
        if not (2 <= len(stripped) <= 80):
            raise ValueError("full_name must be between 2 and 80 characters")
        return stripped

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not _PHONE_RE.match(stripped):
            raise ValueError("invalid Indian mobile number")
        return stripped

    @field_validator("city")
    @classmethod
    def _validate_city(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not (2 <= len(stripped) <= 40):
            raise ValueError("city must be between 2 and 40 characters")
        return stripped
