"""Pydantic v2 schemas for the memory-transparency surface (``/me/memory``).

Kept in their own module (rather than ``schemas/customer.py``) so the privacy
surface owns its wire shapes independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MemoryItemOut(BaseModel):
    """A single thing Sarathi remembers about the customer."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str  # episodic | fact | preference
    text: str
    created_at: datetime


class MemoryResponse(BaseModel):
    """Everything Sarathi knows: recalled memories + the structured facts the
    agents actually see (the same snapshot the suitability gate consumes)."""

    memories: list[MemoryItemOut]
    profile_facts: dict[str, Any]


class MemoryDeleteAllResponse(BaseModel):
    deleted: int
