"""Pydantic v2 schemas for the customer savings-goals API (``/me/goals``)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.goals import GoalProgress


class GoalOut(BaseModel):
    """A goal with its computed progress (paise + clamped percentage)."""

    id: uuid.UUID
    name: str
    target_paise: int
    baseline_paise: int
    target_date: date | None
    status: str
    achieved_at: datetime | None
    created_at: datetime
    progress_paise: int
    pct: float

    @classmethod
    def from_progress(cls, gp: GoalProgress) -> GoalOut:
        g = gp.goal
        return cls(
            id=g.id,
            name=g.name,
            target_paise=g.target_paise,
            baseline_paise=g.baseline_paise,
            target_date=g.target_date,
            status=g.status.value,
            achieved_at=g.achieved_at,
            created_at=g.created_at,
            progress_paise=gp.progress_paise,
            pct=gp.pct,
        )


class GoalListResponse(BaseModel):
    goals: list[GoalOut]
    active_count: int
    max_active: int


class GoalCreateRequest(BaseModel):
    """Body for ``POST /me/goals``. Amounts are in paise (integer money)."""

    name: str = Field(..., min_length=1, max_length=80)
    target_paise: int = Field(..., gt=0)
    target_date: date | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("goal name is required")
        return stripped


class GoalUpdateRequest(BaseModel):
    """Body for ``PATCH /me/goals/{id}``.

    Partial update via ``model_fields_set`` - only present fields are touched.
    ``status`` may only be set to ``archived`` (a soft hide); anything else is a
    422. ``target_date`` accepts ``null`` to clear the date.
    """

    name: str | None = Field(default=None, max_length=80)
    target_date: date | None = None
    status: Literal["archived"] | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        # Only runs when `name` is present in the body; `None` means the client
        # sent `"name": null`, which cannot clear a non-nullable column.
        if value is None:
            raise ValueError("goal name cannot be cleared")
        stripped = value.strip()
        if not stripped:
            raise ValueError("goal name is required")
        return stripped
