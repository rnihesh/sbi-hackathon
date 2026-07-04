"""Pydantic v2 schemas for the staff console API surface."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class CustomerSearchOut(BaseModel):
    """One row of the staff customer-search picker (`GET /console/customers`)."""

    id: uuid.UUID
    full_name: str
    city: str | None


# ===========================================================================
# Customer 360 (`GET /console/customers/{id}`, `GET /console/customers/{id}/timeline`)
# ===========================================================================


class CustomerDetailOut(BaseModel):
    """The full staff-facing profile for one customer."""

    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    city: str | None
    segment: str | None
    digital_maturity: str
    churn_risk: float
    preferred_language: str | None
    created_at: datetime


class CustomerAccountOut(BaseModel):
    type: str
    balance_paise: int
    status: str


class CustomerHoldingProductOut(BaseModel):
    code: str
    name: str
    category: str


class CustomerHoldingOut(BaseModel):
    product: CustomerHoldingProductOut
    status: str


class CustomerStatsOut(BaseModel):
    """At-a-glance counters for the 360 view's stat tile row."""

    transactions_90d: int
    agent_runs_total: int
    proposals_pending: int
    nudges_sent: int
    life_events: int


class CustomerDetailResponse(BaseModel):
    customer: CustomerDetailOut
    accounts: list[CustomerAccountOut]
    holdings: list[CustomerHoldingOut]
    stats: CustomerStatsOut


class TimelineItemOut(BaseModel):
    """One entry in a customer's merged, reverse-chronological activity feed.

    ``data`` is a plain JSON-safe dict (not a discriminated sub-model) whose
    shape depends on ``type`` - every value the endpoint puts in it is a
    pre-stringified primitive (str/float/bool/None), never a raw UUID/Decimal/
    datetime, so serialization is unambiguous regardless of the `Any` typing:

    - ``agent_run``: ``run_id, agent, trigger, status, cost_usd, started_at``
    - ``life_event``: ``type, confidence, detected_at``
    - ``proposal``: ``title, status, created_at, decided_at``
    - ``nudge``: ``title, status, created_at``
    - ``notification``: ``kind, title, created_at``
    """

    type: Literal["agent_run", "life_event", "proposal", "nudge", "notification"]
    ts: datetime
    data: dict[str, Any]


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
    avg_latency_ms: int | None
    by_provider: list[CostBreakdownRow]
    by_model: list[CostBreakdownRow]
    by_tier: list[CostBreakdownRow]
    by_purpose: list[CostBreakdownRow]
    last_24h: list[CostSeriesPoint]


class WorkerHealthOut(BaseModel):
    """Liveness of the `event_consumer` worker, derived from the `sarathi-agents`
    consumer group on the `txn.events` Redis Stream (see `_worker_health`)."""

    alive: bool
    last_event_at: datetime | None
    pending: int
    dlq: int


class LlmBudgetOut(BaseModel):
    """Today's LLM spend (UTC day), from the `llm_calls` cost ledger, against the
    configured daily budget guard."""

    calls_today: int
    cost_usd_today: Decimal
    budget_usd: Decimal
    over_budget: bool


class DlqEntrySummaryOut(BaseModel):
    """One dead-letter entry summary (id + truncated error) for the health panel."""

    id: str
    error: str | None


class SchedulerHealthOut(BaseModel):
    """State of the proactive sweep loop (`app.workers.scheduler`) for the console.

    `swept_today` and `last_tick_at` come from Redis keys the loop writes;
    `next_eligible_estimate` is the current count of sweep-eligible customers
    (has an account, no agent run in the cooldown window)."""

    enabled: bool
    last_tick_at: datetime | None
    swept_today: int
    next_eligible_estimate: int


class ConsoleHealthResponse(BaseModel):
    worker: WorkerHealthOut
    api: str
    db_latency_ms: float | None
    redis_latency_ms: float | None
    llm_budget: LlmBudgetOut
    dlq_recent: list[DlqEntrySummaryOut]
    scheduler: SchedulerHealthOut


class ErrorLogEntryOut(BaseModel):
    """One recent unhandled-error record from the Redis error ring."""

    ts: str | None = None
    request_id: str | None = None
    path: str | None = None
    method: str | None = None
    status: int | None = None
    error_class: str | None = None


class ConsoleErrorsResponse(BaseModel):
    errors: list[ErrorLogEntryOut]


class SimInjectEventRequest(BaseModel):
    customer_id: uuid.UUID
    type: str


class SimInjectEventResponse(BaseModel):
    customer_id: uuid.UUID
    type: str
    mode: str
    detail: dict[str, Any]


# ===========================================================================
# Analytics (detection scorecard, funnel time series, proposal outcomes)
# ===========================================================================


class DetectionRow(BaseModel):
    """One injected ground-truth event, paired with the detection it produced."""

    injection_id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    injected_type: str
    injected_at: datetime
    # The `life_events.type` values that count as a correct detection for this
    # injected type (empty = none expected, e.g. churn_risk).
    expected_types: list[str]
    detected: bool
    detected_type: str | None
    confidence: float | None
    lag_seconds: float | None
    matched: bool


class DetectionSummary(BaseModel):
    injected: int
    detected: int
    matched: int
    # Life events detected that fall outside any injection's attribution window -
    # a rough false-positive / unprompted-detection count.
    detections_with_no_injection: int


class DetectionResponse(BaseModel):
    summary: DetectionSummary
    rows: list[DetectionRow]


class TimeseriesPoint(BaseModel):
    """One UTC-day bucket of funnel + spend counters."""

    date: str
    agent_runs: int
    proposals_created: int
    proposals_approved: int
    nudges_sent: int
    nudges_acted: int
    llm_cost_usd: Decimal


class TimeseriesResponse(BaseModel):
    days: int
    points: list[TimeseriesPoint]


class ProposalAgentRow(BaseModel):
    agent: str
    created: int
    approved: int
    rejected: int


class ProposalOutcomesResponse(BaseModel):
    pending: int
    approved: int
    rejected: int
    executed: int
    avg_decision_seconds: float | None
    by_agent: list[ProposalAgentRow]
