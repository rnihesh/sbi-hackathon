"""Pydantic v2 schemas for the standing-instructions API (``/me/standing-instructions``)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.services.standing import StandingInstructionView


class StandingInstructionOut(BaseModel):
    """A standing instruction with its linked goal name (``None`` for fd/savings)."""

    id: uuid.UUID
    from_account_id: uuid.UUID
    purpose: str
    goal_id: uuid.UUID | None
    goal_name: str | None
    amount_paise: int
    cadence: str
    next_run_date: date
    status: str
    last_run_at: datetime | None
    runs_count: int
    created_at: datetime

    @classmethod
    def from_view(cls, view: StandingInstructionView) -> StandingInstructionOut:
        si = view.instruction
        return cls(
            id=si.id,
            from_account_id=si.from_account_id,
            purpose=si.purpose.value,
            goal_id=si.goal_id,
            goal_name=view.goal_name,
            amount_paise=si.amount_paise,
            cadence=si.cadence.value,
            next_run_date=si.next_run_date,
            status=si.status.value,
            last_run_at=si.last_run_at,
            runs_count=si.runs_count,
            created_at=si.created_at,
        )


class StandingInstructionListResponse(BaseModel):
    instructions: list[StandingInstructionOut]
    active_count: int
    max_active: int


class StandingInstructionCreateRequest(BaseModel):
    """Body for ``POST /me/standing-instructions``. Amounts are in paise."""

    from_account_id: uuid.UUID
    purpose: Literal["goal", "fd", "savings"]
    goal_id: uuid.UUID | None = None
    amount_paise: int = Field(..., gt=0)
    cadence: Literal["weekly", "monthly"]
    start_date: date | None = None


class StandingInstructionUpdateRequest(BaseModel):
    """Body for ``PATCH /me/standing-instructions/{id}``: a lifecycle action."""

    action: Literal["pause", "resume", "cancel"]
