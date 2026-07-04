/** Wire types for the `/console/*` staff endpoints. */

export type FeedItemType = "agent_run" | "proposal" | "life_event" | "nudge"

export interface FeedItem {
  type: FeedItemType
  ts: string
  customer_id: string | null
  summary: string
  ref_id: string
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

/**
 * `GET /console/leads` isn't pinned to an exact response schema in the Wave 3
 * contract - this reads the `Lead` ORM model's field names (`name`, `email`,
 * `phone`, `intent_score`, `stage`) but tolerates a couple of common alternate
 * key spellings defensively via `normalizeLead`.
 */
export interface Lead {
  id: string
  name: string | null
  email: string | null
  phone: string | null
  intent_score: number
  stage: string
  created_at: string
}

export interface LifeEventItem {
  id: string
  customer_id: string
  type: string
  confidence: number
  evidence: Record<string, unknown>
  detected_at: string
  status: string
}

export interface FunnelStageCounts {
  [stage: string]: number
}

export interface FunnelsResponse {
  acquisition: FunnelStageCounts
  adoption: {
    nudges: FunnelStageCounts
    holdings: FunnelStageCounts
  }
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

/** Normalizes a raw lead row, tolerating `full_name`/`contact` alternates. */
export function normalizeLead(raw: unknown, index: number): Lead | null {
  const obj = asRecord(raw)
  if (!obj) return null
  return {
    id: str(obj.id) ?? `lead-${index}`,
    name: str(obj.name) ?? str(obj.full_name),
    email: str(obj.email),
    phone: str(obj.phone) ?? str(obj.contact),
    intent_score: num(obj.intent_score ?? obj.score),
    stage: str(obj.stage) ?? str(obj.funnel_stage) ?? "new",
    created_at: str(obj.created_at) ?? new Date(0).toISOString(),
  }
}

export function normalizeLifeEvent(raw: unknown, index: number): LifeEventItem | null {
  const obj = asRecord(raw)
  if (!obj) return null
  return {
    id: str(obj.id) ?? `life-event-${index}`,
    customer_id: str(obj.customer_id) ?? "",
    type: str(obj.type) ?? "unknown",
    confidence: num(obj.confidence),
    evidence: asRecord(obj.evidence) ?? {},
    detected_at: str(obj.detected_at) ?? str(obj.created_at) ?? new Date(0).toISOString(),
    status: str(obj.status) ?? "detected",
  }
}
