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

export interface ProductOffer {
  code?: string
  name: string
  category?: string
  reason?: string
  cta?: string
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
  const product = asRecord(obj.product)
  const name = obj.name ?? product?.name
  if (typeof name !== "string") return null
  return {
    code: typeof obj.code === "string" ? obj.code : typeof product?.code === "string" ? product.code : undefined,
    name,
    category:
      typeof obj.category === "string"
        ? obj.category
        : typeof product?.category === "string"
          ? product.category
          : undefined,
    reason: typeof obj.reason === "string" ? obj.reason : typeof obj.rationale === "string" ? obj.rationale : undefined,
    cta: typeof obj.cta === "string" ? obj.cta : typeof obj.action === "string" ? obj.action : undefined,
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
    const offersRaw = obj.offers ?? obj.products ?? obj.product_offers
    if (Array.isArray(offersRaw) && (kind === undefined || kind.includes("product") || kind.includes("offer"))) {
      const offers = offersRaw.map(normalizeOffer).filter((o): o is ProductOffer => o !== null)
      if (offers.length > 0) return { kind: "product_offers", offers }
    }

    const stepsRaw = obj.steps ?? obj.walkthrough
    if (Array.isArray(stepsRaw) && (kind === undefined || kind.includes("walkthrough") || kind.includes("step"))) {
      const steps = stepsRaw.map(normalizeStep).filter((s): s is WalkthroughStep => s !== null)
      if (steps.length > 0) {
        return { kind: "walkthrough", title: typeof obj.title === "string" ? obj.title : undefined, steps }
      }
    }
  }
  return { kind: "unknown", raw: data }
}
