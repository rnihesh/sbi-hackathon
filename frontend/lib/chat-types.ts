/**
 * Chat domain types + SSE payload normalizers.
 *
 * The `structured` SSE event's `data` shape isn't pinned to a single schema in
 * the contract ("walkthrough steps / product offers") - these normalizers read
 * a few reasonable field-name variants defensively rather than assuming one
 * exact backend shape, and fall back to a raw-JSON card so nothing is ever
 * silently dropped.
 */

export interface ToolActivity {
  id: string
  tool: string
  status: "running" | "done"
  result?: unknown
}

/** Mirrors the acquisition agent's `match_products` structured payload exactly
 * (verified live: `{code, name, category, score, reasons}` - `reasons` is a
 * list, not a single string). */
export interface ProductOffer {
  code: string
  name: string
  category: string
  score: number
  reasons: string[]
}

export interface WalkthroughStep {
  title: string
  description?: string
}

export type StructuredPayload =
  | { kind: "product_offers"; offers: ProductOffer[] }
  | { kind: "walkthrough"; title?: string; steps: WalkthroughStep[] }
  | { kind: "unknown"; raw: unknown }

export interface ChatMessage {
  id: string
  role: "user" | "assistant" | "system"
  content: string
  createdAt?: string
  isError?: boolean
  /** Set on an assistant bubble when the stream failed *after* partial tokens
   * already arrived: the partial text stays visible and this renders as a subtle
   * inline notice (with retry) instead of nuking the whole reply. */
  streamError?: string
  /** Original user text to resend - set on error bubbles so their retry button
   * doesn't need a separate "last failed message" side-channel. */
  retryText?: string
  toolActivity?: ToolActivity[]
  structured?: StructuredPayload[]
  agent?: string
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function normalizeOffer(raw: unknown): ProductOffer | null {
  const obj = asRecord(raw)
  if (!obj) return null
  const name = obj.name
  if (typeof name !== "string") return null
  const reasonsRaw = Array.isArray(obj.reasons) ? obj.reasons : []
  return {
    code: typeof obj.code === "string" ? obj.code : "",
    name,
    category: typeof obj.category === "string" ? obj.category : "",
    score: typeof obj.score === "number" && Number.isFinite(obj.score) ? obj.score : 0,
    reasons: reasonsRaw.filter((r): r is string => typeof r === "string"),
  }
}

function normalizeStep(raw: unknown, index: number): WalkthroughStep | null {
  if (typeof raw === "string") return { title: raw }
  const obj = asRecord(raw)
  if (!obj) return null
  const title = obj.title ?? obj.name ?? obj.step
  return {
    title: typeof title === "string" ? title : `Step ${index + 1}`,
    description: typeof obj.description === "string" ? obj.description : typeof obj.detail === "string" ? obj.detail : undefined,
  }
}

export function normalizeStructuredPayload(data: unknown): StructuredPayload {
  const obj = asRecord(data)
  if (obj) {
    const kind = typeof obj.type === "string" ? obj.type : typeof obj.kind === "string" ? obj.kind : undefined
    const offersRaw = obj.offers
    if (Array.isArray(offersRaw) && (kind === undefined || kind.includes("product") || kind.includes("offer"))) {
      const offers = offersRaw.map(normalizeOffer).filter((o): o is ProductOffer => o !== null)
      if (offers.length > 0) return { kind: "product_offers", offers }
    }

    // Real wire shape: obj.walkthrough is an object {topic, title, steps: string[]},
    // with obj.steps as a tolerated flat fallback.
    const walkthrough = asRecord(obj.walkthrough)
    const stepsRaw = Array.isArray(obj.steps)
      ? obj.steps
      : walkthrough && Array.isArray(walkthrough.steps)
        ? walkthrough.steps
        : undefined
    if (stepsRaw && (kind === undefined || kind.includes("walkthrough") || kind.includes("step"))) {
      const steps = stepsRaw.map(normalizeStep).filter((s): s is WalkthroughStep => s !== null)
      if (steps.length > 0) {
        const title = walkthrough?.title ?? walkthrough?.topic ?? obj.title
        return { kind: "walkthrough", title: typeof title === "string" ? title : undefined, steps }
      }
    }
  }
  return { kind: "unknown", raw: data }
}
