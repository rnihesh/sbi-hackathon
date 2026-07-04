/** Wire types for the `/me/products` browse + apply customer endpoints. */

export interface ProductBrowseItem {
  code: string
  name: string
  category: string
  description: string | null
  eligible: boolean
  held: boolean
  /** A request for this product has a real HITL proposal awaiting RM review -
   * survives a reload, unlike client-only "just clicked apply" state. */
  pending: boolean
  /** "Why for you" (eligible + not held, LLM-ranked, may be absent) for
   * eligible products, or the rule that blocks it for ineligible ones - null
   * for anything held. */
  reason: string | null
}

export interface ProductsBrowseResponse {
  products: ProductBrowseItem[]
}

export interface ProductApplyResponse {
  proposal_id: string
  status: string
}
