/** Wire types for the `/me/dashboard` and `/me/nudges` customer endpoints. */

export interface DashboardCustomer {
  id: string
  full_name: string
  email: string | null
  phone: string | null
  city: string | null
  state: string | null
  segment: string | null
  digital_maturity: string
}

export interface DashboardAccount {
  id: string
  type: string
  balance_paise: number
  status: string
}

export interface DashboardTransaction {
  id: string
  ts: string
  amount_paise: number
  direction: "credit" | "debit"
  channel: string
  merchant: string | null
  category: string | null
  description: string | null
}

export interface DashboardHolding {
  id: string
  product: {
    code: string
    name: string
    category: string
  }
  status: string
}

export interface DashboardResponse {
  customer: DashboardCustomer
  accounts: DashboardAccount[]
  recent_transactions: DashboardTransaction[]
  holdings: DashboardHolding[]
  unseen_nudges: number
}

export interface Nudge {
  id: string
  title: string
  body: string
  /** Free-form JSONB on the backend - read defensively via `ctaLabel`/`ctaUrl`
   * below rather than assuming an exact shape. */
  cta: Record<string, unknown> | null
  status: "sent" | "seen" | "acted" | "dismissed"
  created_at: string
}

export function ctaLabel(nudge: Nudge): string {
  const label = nudge.cta?.label ?? nudge.cta?.text
  return typeof label === "string" && label.trim() ? label : "Take a look"
}

export function ctaUrl(nudge: Nudge): string | null {
  const url = nudge.cta?.url ?? nudge.cta?.href
  return typeof url === "string" && url.trim() ? url : null
}

/** A customer savings goal with its computed progress. `progress_paise` is how
 * much the total balance has grown since the goal was set (see the API's honest
 * progress model), and `pct` is that clamped to 0..100. */
export interface Goal {
  id: string
  name: string
  target_paise: number
  baseline_paise: number
  target_date: string | null
  status: "active" | "achieved" | "archived"
  achieved_at: string | null
  created_at: string
  progress_paise: number
  pct: number
}

export interface GoalListResponse {
  goals: Goal[]
  active_count: number
  max_active: number
}
