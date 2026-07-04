"""Pydantic v2 schemas for the customer-facing product browse/apply surface."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class ProductBrowseItem(BaseModel):
    code: str
    name: str
    category: str
    description: str | None
    eligible: bool
    held: bool
    pending: bool
    reason: str | None


class ProductsBrowseResponse(BaseModel):
    products: list[ProductBrowseItem]


class ProductApplyResponse(BaseModel):
    proposal_id: uuid.UUID
    status: str
