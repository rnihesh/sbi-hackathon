/** Wire types for `GET /me/insights` (spending insights). */

export interface CategoryBreakdown {
  category: string
  amount_paise: number
  share_pct: number
  txn_count: number
}

export interface MonthlyInsight {
  /** UTC calendar-month key, e.g. "2026-07". */
  month: string
  total_in_paise: number
  total_out_paise: number
  by_category: CategoryBreakdown[]
}

export interface TopCategoryChange {
  category: string
  prev_paise: number
  curr_paise: number
  /** Null when there's nothing in the prior month to compute a percentage from. */
  delta_pct: number | null
}

export interface LargestTransaction {
  amount_paise: number
  merchant: string | null
  category: string | null
  ts: string
}

export interface RecurringMerchant {
  merchant: string
  monthly_avg_paise: number
  count: number
}

export interface InsightsTrends {
  top_category_change: TopCategoryChange | null
  largest_txn_30d: LargestTransaction | null
  recurring: RecurringMerchant[]
}

export interface InsightsResponse {
  months: MonthlyInsight[]
  trends: InsightsTrends
  /** Factual "spending is up X%" callout, or null when nothing spiked. */
  note: string | null
}
