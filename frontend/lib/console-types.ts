/** Wire types for the `/console/*` staff endpoints. */

export type FeedItemType = "agent_run" | "proposal" | "life_event" | "nudge" | "handoff"

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

// ---------------------------------------------------------------------------
// Customer 360 - mirrors `app.schemas.console.{CustomerDetailOut,
// CustomerAccountOut,CustomerHoldingOut,CustomerStatsOut,CustomerDetailResponse,
// TimelineItemOut}` (`GET /console/customers/{id}`, `GET
// /console/customers/{id}/timeline`).
// ---------------------------------------------------------------------------

export interface CustomerDetail {
  id: string
  full_name: string
  email: string | null
  phone: string | null
  city: string | null
  segment: string | null
  digital_maturity: string
  churn_risk: number
  preferred_language: string | null
  created_at: string
}

export interface CustomerAccountSummary {
  type: string
  balance_paise: number
  status: string
}

export interface CustomerHoldingProduct {
  code: string
  name: string
  category: string
}

export interface CustomerHoldingSummary {
  product: CustomerHoldingProduct
  status: string
}

export interface CustomerStats {
  transactions_90d: number
  agent_runs_total: number
  proposals_pending: number
  nudges_sent: number
  life_events: number
}

export interface CustomerDetailResponse {
  customer: CustomerDetail
  accounts: CustomerAccountSummary[]
  holdings: CustomerHoldingSummary[]
  stats: CustomerStats
}

export type TimelineItemType = "agent_run" | "life_event" | "proposal" | "nudge" | "notification"

export interface TimelineAgentRunData {
  run_id: string
  agent: string
  trigger: string
  status: string
  cost_usd: string
  started_at: string
}

export interface TimelineLifeEventData {
  type: string
  confidence: number
  detected_at: string
}

export interface TimelineProposalData {
  title: string
  status: string
  created_at: string
  decided_at: string | null
}

export interface TimelineNudgeData {
  title: string
  status: string
  created_at: string
}

export interface TimelineNotificationData {
  kind: string
  title: string
  created_at: string
}

export interface TimelineAgentRunItem {
  type: "agent_run"
  ts: string
  data: TimelineAgentRunData
}

export interface TimelineLifeEventItem {
  type: "life_event"
  ts: string
  data: TimelineLifeEventData
}

export interface TimelineProposalItem {
  type: "proposal"
  ts: string
  data: TimelineProposalData
}

export interface TimelineNudgeItem {
  type: "nudge"
  ts: string
  data: TimelineNudgeData
}

export interface TimelineNotificationItem {
  type: "notification"
  ts: string
  data: TimelineNotificationData
}

/** One merged-feed entry - a discriminated union on `type`, so a `switch`/
 * narrowing check on it also narrows `data` to the matching `Timeline*Data`
 * shape without a manual cast. */
export type TimelineItem =
  | TimelineAgentRunItem
  | TimelineLifeEventItem
  | TimelineProposalItem
  | TimelineNudgeItem
  | TimelineNotificationItem

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

// ---------------------------------------------------------------------------
// Churn cockpit - mirrors `app.schemas.console.{ChurnBucketOut,
// ChurnAtRiskCustomerOut,ChurnCockpitResponse,ChurnReengageResult}`
// (`GET /console/churn`, `POST /console/churn/{id}/re-engage`).
// ---------------------------------------------------------------------------

export type ChurnBucketLabel = "0-20" | "20-40" | "40-60" | "60-80" | "80-100"

export interface ChurnBucket {
  bucket: ChurnBucketLabel
  count: number
}

export interface ChurnAtRiskCustomer {
  id: string
  full_name: string
  churn_risk: number
  last_activity_at: string | null
  balance_paise: number
  nudges_last_30d: number
  reengage_requested: boolean
}

export interface ChurnCockpitResponse {
  distribution: ChurnBucket[]
  at_risk: ChurnAtRiskCustomer[]
  unscored: number
}

export interface ChurnReengageResult {
  proposal_id: string
  status: string
}

// ---------------------------------------------------------------------------
// Human handoffs - mirrors `app.schemas.console.{HandoffOut,HandoffQueueResponse}`
// (`GET /console/handoffs`, `POST /console/handoffs/{id}/{claim,resolve}`). This
// is the "agent knows when to step aside" queue: open first, high urgency
// accented, claim -> resolve-with-note -> collapsed resolved section.
// ---------------------------------------------------------------------------

export type HandoffUrgency = "low" | "normal" | "high"
export type HandoffStatus = "open" | "claimed" | "resolved"

export interface HandoffCustomer {
  id: string
  full_name: string
}

export interface Handoff {
  id: string
  customer: HandoffCustomer | null
  conversation_id: string
  reason: string
  urgency: HandoffUrgency
  status: HandoffStatus
  claimed_by: string | null
  resolution_note: string | null
  created_at: string
  claimed_at: string | null
  resolved_at: string | null
}

export interface HandoffQueue {
  active: Handoff[]
  resolved: Handoff[]
}

// ---------------------------------------------------------------------------
// Staff notes - mirrors `app.schemas.console.StaffNoteOut` (customer 360's
// "notes" card: `GET/POST /console/customers/{id}/notes`, `DELETE
// /console/notes/{id}`).
// ---------------------------------------------------------------------------

export interface StaffNote {
  id: string
  customer_id: string
  author_email: string
  text: string
  created_at: string
}
