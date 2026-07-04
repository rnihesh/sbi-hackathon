"""Pydantic v2 schemas for the staff console API surface."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class LeadCustomerOut(BaseModel):
    id: uuid.UUID
    full_name: str


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer: LeadCustomerOut | None
    source: str
    name: str | None
    email: str | None
    phone: str | None
    intent_score: float
    stage: str
    created_at: datetime


class ProposalCustomerOut(BaseModel):
    id: uuid.UUID
    full_name: str


class ProposalOut(BaseModel):
    id: uuid.UUID
    customer: ProposalCustomerOut
    agent: str
    kind: str
    title: str
    body: str
    action: dict[str, Any]
    status: str
    created_at: datetime


class ProposalActionResult(BaseModel):
    proposal_id: str
    action_kind: str
    status: str
    detail: dict[str, Any]


class ProposalRejectRequest(BaseModel):
    reason: str | None = None


class LifeEventCustomerOut(BaseModel):
    id: uuid.UUID
    full_name: str


class LifeEventOut(BaseModel):
    id: uuid.UUID
    customer: LifeEventCustomerOut
    type: str
    confidence: float
    evidence: dict[str, Any]
    detected_at: datetime
    status: str


class AcquisitionFunnel(BaseModel):
    leads: int
    qualified: int
    kyc_verified: int
    account_opened: int


class NudgeFunnel(BaseModel):
    sent: int
    seen: int
    acted: int


class HoldingCategoryFunnel(BaseModel):
    category: str
    offered: int
    active: int


class FunnelResponse(BaseModel):
    acquisition: AcquisitionFunnel
    nudges: NudgeFunnel
    holdings_by_category: list[HoldingCategoryFunnel]


class TraceCustomerOut(BaseModel):
    id: uuid.UUID
    full_name: str


class TraceOut(BaseModel):
    run_id: uuid.UUID
    agent: str
    trigger: str
    status: str
    customer: TraceCustomerOut | None
    started_at: datetime
    latency_ms: int | None
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    steps_count: int


class TraceStepOut(BaseModel):
    seq: int
    node: str
    kind: str
    name: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    model: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    latency_ms: int | None


class TraceDetailResponse(BaseModel):
    run_id: uuid.UUID
    agent: str
    trigger: str
    status: str
    customer: TraceCustomerOut | None
    started_at: datetime
    finished_at: datetime | None
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    latency_ms: int | None
    steps: list[TraceStepOut]


class CostBreakdownRow(BaseModel):
    key: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


class CostSeriesPoint(BaseModel):
    hour: datetime
    cost_usd: Decimal
    calls: int


class CostsResponse(BaseModel):
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: Decimal
    by_provider: list[CostBreakdownRow]
    by_model: list[CostBreakdownRow]
    by_tier: list[CostBreakdownRow]
    by_purpose: list[CostBreakdownRow]
    last_24h: list[CostSeriesPoint]


class SimInjectEventRequest(BaseModel):
    customer_id: uuid.UUID
    type: str


class SimInjectEventResponse(BaseModel):
    customer_id: uuid.UUID
    type: str
    mode: str
    detail: dict[str, Any]
