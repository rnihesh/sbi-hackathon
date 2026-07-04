/** Wire types for the `/console/*` staff endpoints. */

export type FeedItemType = "agent_run" | "proposal" | "life_event" | "nudge"

export interface FeedItem {
  type: FeedItemType
  ts: string
  customer_id: string | null
  summary: string
  // Mirrors `app.workers.activity.publish_activity` exactly - `ref_id` is `None`
  // (not merely absent) for some envelopes (e.g. the sim life-event injector's
  // "injected" marker), so this is nullable, not just optional.
  ref_id: string | null
}

export interface ProposalCustomer {
  id: string
  full_name: string
}

export interface Proposal {
  id: string
  customer: ProposalCustomer
  agent: string
  kind: string
  title: string
  body: string
  action: Record<string, unknown>
  status: "pending" | "approved" | "rejected" | "executed"
  created_at: string
}

/** Mirrors `app.schemas.console.ProposalActionResult` - the executed-action
 * detail returned by `POST /console/proposals/{id}/approve`. */
export interface ProposalActionResult {
  proposal_id: string
  action_kind: string
  status: string
  detail: Record<string, unknown>
}

/** Mirrors `app.schemas.console.CustomerSearchOut` (`GET /console/customers`). */
export interface CustomerSearchResult {
  id: string
  full_name: string
  city: string | null
}

/** Mirrors `app.schemas.console.ConsoleHealthResponse` (`GET /console/health`). */
export interface ConsoleHealth {
  worker: {
    alive: boolean
    last_event_at: string | null
    pending: number
    dlq: number
  }
  api: string
}

export interface LeadCustomer {
  id: string
  full_name: string
}

/** Mirrors `app.schemas.console.LeadOut` exactly (verified against a live
 * `GET /console/leads` response) - `customer` is `null` for prospects who
 * haven't converted into a linked `Customer` yet. */
export interface Lead {
  id: string
  customer: LeadCustomer | null
  source: string
  name: string | null
  email: string | null
  phone: string | null
  intent_score: number
  stage: string
  created_at: string
}

export interface LifeEventCustomer {
  id: string
  full_name: string
}

/** Mirrors `app.schemas.console.LifeEventOut` - note the wire field is the
 * nested `customer` object, not a bare `customer_id`. */
export interface LifeEventItem {
  id: string
  customer: LifeEventCustomer
  type: string
  confidence: number
  evidence: Record<string, unknown>
  detected_at: string
  status: string
}

/** Mirrors `app.schemas.console.AcquisitionFunnel`. */
export interface AcquisitionFunnel {
  leads: number
  qualified: number
  kyc_verified: number
  account_opened: number
}

/** Mirrors `app.schemas.console.NudgeFunnel`. */
export interface NudgeFunnel {
  sent: number
  seen: number
  acted: number
}

/** Mirrors `app.schemas.console.HoldingCategoryFunnel`. */
export interface HoldingCategoryFunnel {
  category: string
  offered: number
  active: number
}

/** Mirrors `app.schemas.console.FunnelResponse` exactly (verified against a
 * live `GET /console/funnels` response) - `nudges` is top-level (not nested
 * under an `adoption` key) and holdings are a per-category breakdown list,
 * not a flat stage-count map. */
export interface FunnelsResponse {
  acquisition: AcquisitionFunnel
  nudges: NudgeFunnel
  holdings_by_category: HoldingCategoryFunnel[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function customerRef(value: unknown): { id: string; full_name: string } | null {
  const obj = asRecord(value)
  if (!obj) return null
  const id = str(obj.id)
  const fullName = str(obj.full_name)
  return id && fullName ? { id, full_name: fullName } : null
}

/** Runtime guard for a raw `GET /console/leads` row - the wire shape is pinned to
 * `LeadOut` (verified live), so this only guards against malformed/missing fields
 * rather than guessing alternate key spellings. */
export function normalizeLead(raw: unknown, index: number): Lead | null {
  const obj = asRecord(raw)
  if (!obj) return null
  return {
    id: str(obj.id) ?? `lead-${index}`,
    customer: customerRef(obj.customer),
    source: str(obj.source) ?? "unknown",
    name: str(obj.name),
    email: str(obj.email),
    phone: str(obj.phone),
    intent_score: num(obj.intent_score),
    stage: str(obj.stage) ?? "new",
    created_at: str(obj.created_at) ?? new Date(0).toISOString(),
  }
}

/** Runtime guard for a raw `GET /console/life-events` row - pinned to
 * `LifeEventOut` (verified live); `customer` is always present, not `customer_id`. */
export function normalizeLifeEvent(raw: unknown, index: number): LifeEventItem | null {
  const obj = asRecord(raw)
  if (!obj) return null
  return {
    id: str(obj.id) ?? `life-event-${index}`,
    customer: customerRef(obj.customer) ?? { id: "", full_name: "Unknown customer" },
    type: str(obj.type) ?? "unknown",
    confidence: num(obj.confidence),
    evidence: asRecord(obj.evidence) ?? {},
    detected_at: str(obj.detected_at) ?? new Date(0).toISOString(),
    status: str(obj.status) ?? "detected",
  }
}

// ---------------------------------------------------------------------------
// Traces (glass box) - mirrors `app.schemas.console.{TraceOut,TraceStepOut,
// TraceDetailResponse}` exactly (verified against live `GET /console/traces`
// and `GET /console/traces/{run_id}` responses). `cost_usd` is a backend
// `Decimal`, which FastAPI/Pydantic serializes as a JSON string - parse with
// `Number(...)` before formatting.
// ---------------------------------------------------------------------------

export type AgentTrigger = "chat" | "event"
export type AgentRunStatusValue = "running" | "completed" | "failed" | "cancelled"
export type AgentStepKind = "llm" | "tool" | "guardrail"

export interface TraceCustomer {
  id: string
  full_name: string
}

export interface TraceSummary {
  run_id: string
  agent: string
  trigger: string
  status: string
  customer: TraceCustomer | null
  started_at: string
  latency_ms: number | null
  tokens_in: number
  tokens_out: number
  cost_usd: string
  steps_count: number
}

export interface TraceStep {
  seq: number
  node: string
  kind: string
  name: string
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  model: string | null
  tokens_in: number
  tokens_out: number
  cost_usd: string
  latency_ms: number | null
}

export interface TraceDetail {
  run_id: string
  agent: string
  trigger: string
  status: string
  customer: TraceCustomer | null
  started_at: string
  finished_at: string | null
  tokens_in: number
  tokens_out: number
  cost_usd: string
  latency_ms: number | null
  steps: TraceStep[]
}

// ---------------------------------------------------------------------------
// Costs (glass box) - mirrors `app.schemas.console.{CostBreakdownRow,
// CostSeriesPoint,CostsResponse}` exactly (verified against a live
// `GET /console/costs` response).
// ---------------------------------------------------------------------------

export interface CostBreakdownRow {
  key: string
  calls: number
  tokens_in: number
  tokens_out: number
  cost_usd: string
}

export interface CostSeriesPoint {
  hour: string
  cost_usd: string
  calls: number
}

export interface CostsResponse {
  total_calls: number
  total_tokens_in: number
  total_tokens_out: number
  total_cost_usd: string
  avg_latency_ms: number | null
  by_provider: CostBreakdownRow[]
  by_model: CostBreakdownRow[]
  by_tier: CostBreakdownRow[]
  by_purpose: CostBreakdownRow[]
  last_24h: CostSeriesPoint[]
}

// ---------------------------------------------------------------------------
// Analytics - mirrors `app.schemas.console.{DetectionResponse,DetectionRow,
// DetectionSummary,TimeseriesResponse,TimeseriesPoint,ProposalOutcomesResponse,
// ProposalAgentRow}` exactly. `cost_usd` figures are backend `Decimal`s, which
// serialize as JSON strings - parse with `Number(...)` before formatting.
// ---------------------------------------------------------------------------

/** Mirrors `app.schemas.console.DetectionRow` (one injection vs. its detection). */
export interface DetectionRow {
  injection_id: string
  customer_id: string
  customer_name: string
  injected_type: string
  injected_at: string
  expected_types: string[]
  detected: boolean
  detected_type: string | null
  confidence: number | null
  lag_seconds: number | null
  matched: boolean
}

/** Mirrors `app.schemas.console.DetectionSummary`. */
export interface DetectionSummary {
  injected: number
  detected: number
  matched: number
  detections_with_no_injection: number
}

/** Mirrors `app.schemas.console.DetectionResponse`. */
export interface DetectionResponse {
  summary: DetectionSummary
  rows: DetectionRow[]
}

/** Mirrors `app.schemas.console.TimeseriesPoint`. */
export interface TimeseriesPoint {
  date: string
  agent_runs: number
  proposals_created: number
  proposals_approved: number
  nudges_sent: number
  nudges_acted: number
  llm_cost_usd: string
}

/** Mirrors `app.schemas.console.TimeseriesResponse`. */
export interface TimeseriesResponse {
  days: number
  points: TimeseriesPoint[]
}

/** Mirrors `app.schemas.console.ProposalAgentRow`. */
export interface ProposalAgentRow {
  agent: string
  created: number
  approved: number
  rejected: number
}

/** Mirrors `app.schemas.console.ProposalOutcomesResponse`. */
export interface ProposalOutcomesResponse {
  pending: number
  approved: number
  rejected: number
  executed: number
  avg_decision_seconds: number | null
  by_agent: ProposalAgentRow[]
}
