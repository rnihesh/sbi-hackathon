"use client"

import * as React from "react"
import { motion } from "framer-motion"
import {
  AlertTriangle,
  Receipt,
  Repeat,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { staggerContainer, staggerItem } from "@/lib/motion"
import { formatPaise, formatRelativeTime, formatSignedPaise, humanizeIdentifier } from "@/lib/format"
import { categoryIcon } from "@/lib/category-icons"
import type { CategoryBreakdown, InsightsResponse, InsightsTrends } from "@/lib/insights-types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { InsightsSkeleton } from "@/components/customer/insights-skeleton"

const _MONTHS_TO_FETCH = 6

export default function InsightsPage() {
  const [insights, setInsights] = React.useState<InsightsResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [loadingDemo, setLoadingDemo] = React.useState(false)
  const [selectedIndex, setSelectedIndex] = React.useState(0)

  const fetchInsights = React.useCallback(async () => {
    try {
      const res = await api.get<InsightsResponse>(
        `${API_V1}/me/insights?months=${_MONTHS_TO_FETCH}`
      )
      setInsights(res)
      setSelectedIndex(0)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your spending insights.")
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    setLoading(true)
    void fetchInsights()
  }, [fetchInsights])

  async function handleLoadDemoActivity() {
    setLoadingDemo(true)
    try {
      const res = await api.post<{ transactions: number; months: number }>(
        `${API_V1}/me/demo-activity`
      )
      toast.success("Demo activity loaded", {
        description: `${res.transactions} transactions over ${res.months} months.`,
      })
      await fetchInsights()
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't load demo activity"))
    } finally {
      setLoadingDemo(false)
    }
  }

  const isEmpty =
    insights !== null &&
    insights.months.every((m) => m.total_in_paise === 0 && m.total_out_paise === 0)
  const selected = insights?.months[selectedIndex] ?? null

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Insights</h1>
        <p className="text-sm text-muted-foreground">Where your money went.</p>
      </div>

      {error && (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {loading ? (
        <InsightsSkeleton />
      ) : insights && isEmpty ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-4 py-16 text-center">
          <Receipt className="size-8 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">No transactions yet</p>
            <p className="mx-auto mt-1 max-w-xs text-sm text-muted-foreground">
              Load demo activity or start using your account to see where your money goes.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={loadingDemo}
            onClick={() => void handleLoadDemoActivity()}
          >
            <Sparkles className="size-3.5" />
            {loadingDemo ? "Loading…" : "Load demo activity"}
          </Button>
        </div>
      ) : insights && selected ? (
        <motion.div
          initial="initial"
          animate="animate"
          variants={staggerContainer}
          className="flex flex-col gap-6"
        >
          {insights.note && (
            <motion.div variants={staggerItem}>
              <div className="flex items-start gap-2.5 rounded-xl border border-primary/20 bg-accent px-4 py-3 text-sm text-accent-foreground">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>{insights.note}</span>
              </div>
            </motion.div>
          )}

          <motion.div variants={staggerItem} className="flex flex-wrap gap-2">
            {insights.months.map((m, idx) => (
              <button
                key={m.month}
                type="button"
                onClick={() => setSelectedIndex(idx)}
                aria-pressed={idx === selectedIndex}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  idx === selectedIndex
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground"
                )}
              >
                {monthLabel(m.month, idx === 0)}
              </button>
            ))}
          </motion.div>

          <motion.div variants={staggerItem} className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-border p-4">
              <p className="text-xs text-muted-foreground">Money in</p>
              <p className="font-mono text-xl font-semibold tabular-nums">
                {formatSignedPaise(selected.total_in_paise, "credit")}
              </p>
            </div>
            <div className="rounded-xl border border-border p-4">
              <p className="text-xs text-muted-foreground">Money out</p>
              <p className="font-mono text-xl font-semibold tabular-nums">
                {formatSignedPaise(selected.total_out_paise, "debit")}
              </p>
            </div>
          </motion.div>

          <motion.div variants={staggerItem}>
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Where it went</CardTitle>
              </CardHeader>
              <CardContent>
                {selected.by_category.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No spending recorded this month.
                  </p>
                ) : (
                  <div className="flex flex-col gap-4">
                    {selected.by_category.map((item) => (
                      <CategoryBar key={item.category} item={item} />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>

          <motion.div variants={staggerItem}>
            <TrendsCard trends={insights.trends} />
          </motion.div>
        </motion.div>
      ) : null}
    </div>
  )
}

function monthLabel(monthKey: string, isCurrent: boolean): string {
  if (isCurrent) return "This month"
  const [year, month] = monthKey.split("-").map(Number)
  const date = new Date(Date.UTC(year, month - 1, 1))
  return new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric", timeZone: "UTC" }).format(
    date
  )
}

function CategoryBar({ item }: { item: CategoryBreakdown }) {
  const Icon = categoryIcon(item.category)
  const width = Math.max(item.share_pct, item.amount_paise > 0 ? 2 : 0)

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="flex min-w-0 items-center gap-2 font-medium">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{humanizeIdentifier(item.category)}</span>
        </span>
        <span className="flex shrink-0 items-baseline gap-2 font-mono text-xs tabular-nums text-muted-foreground">
          {formatPaise(item.amount_paise)}
          <span className="text-foreground">{Math.round(item.share_pct)}%</span>
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  )
}

function TrendsCard({ trends }: { trends: InsightsTrends }) {
  const mover = trends.top_category_change
  const largest = trends.largest_txn_30d
  const recurring = trends.recurring

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Trends</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <p className="mb-1.5 text-xs text-muted-foreground">Biggest mover</p>
          {mover ? (
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="flex items-center gap-2 font-medium">
                {mover.delta_pct !== null && mover.delta_pct < 0 ? (
                  <TrendingDown className="size-4 shrink-0 text-muted-foreground" />
                ) : (
                  <TrendingUp className="size-4 shrink-0 text-muted-foreground" />
                )}
                {humanizeIdentifier(mover.category)}
              </span>
              <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                {formatPaise(mover.prev_paise)} {"->"} {formatPaise(mover.curr_paise)}
                {mover.delta_pct !== null && (
                  <span className="ml-1 text-foreground">
                    ({mover.delta_pct >= 0 ? "+" : ""}
                    {Math.round(mover.delta_pct)}%)
                  </span>
                )}
              </span>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Not enough history yet to spot a mover.</p>
          )}
        </div>

        <Separator />

        <div>
          <p className="mb-1.5 text-xs text-muted-foreground">Largest expense (30 days)</p>
          {largest ? (
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate font-medium">
                {largest.merchant ?? humanizeIdentifier(largest.category ?? "expense")}
                <span className="ml-2 text-xs text-muted-foreground">
                  {formatRelativeTime(largest.ts)}
                </span>
              </span>
              <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                {formatPaise(largest.amount_paise)}
              </span>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No large expenses in the last 30 days.</p>
          )}
        </div>

        <Separator />

        <div>
          <p className="mb-1.5 text-xs text-muted-foreground">Recurring</p>
          {recurring.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recurring merchants detected yet.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {recurring.map((r) => (
                <li key={r.merchant} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex min-w-0 items-center gap-2">
                    <Repeat className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{r.merchant}</span>
                  </span>
                  <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                    {formatPaise(r.monthly_avg_paise)}/mo
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
