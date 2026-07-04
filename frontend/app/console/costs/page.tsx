"use client"

import * as React from "react"

import { api, API_V1, ApiError } from "@/lib/api"
import { formatCount, formatLatency, formatUsd } from "@/lib/format"
import type { CostsResponse } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { StatTile } from "@/components/console/stat-tile"
import { CostBreakdownBars } from "@/components/console/cost-breakdown-bars"
import { CostSeriesChart } from "@/components/console/cost-series-chart"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const BREAKDOWNS = [
  { key: "by_provider", title: "By provider" },
  { key: "by_model", title: "By model" },
  { key: "by_tier", title: "By policy tier" },
  { key: "by_purpose", title: "By purpose" },
] as const

export default function CostsPage() {
  const [data, setData] = React.useState<CostsResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .get<CostsResponse>(`${API_V1}/console/costs`)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load costs.")
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="mx-auto max-w-4xl">
      <ConsolePageHeader
        title="Costs"
        description="LLM spend across providers, models, and policy tiers - every call, real."
      />

      {error && (
        <Card className="mb-6">
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {!data && !error ? (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {["Total spend", "Tokens in/out", "Calls", "Avg. latency"].map((tile) => (
              <Card key={tile}>
                <CardContent className="space-y-2">
                  <p className="text-xs text-muted-foreground">{tile}</p>
                  <Skeleton className="h-5 w-20" />
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Spend over time (24h)</CardTitle>
            </CardHeader>
            <CardContent>
              <Skeleton className="h-[200px] w-full rounded-lg" />
            </CardContent>
          </Card>
        </>
      ) : data ? (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Total spend" value={formatUsd(data.total_cost_usd)} />
            <StatTile
              label="Tokens in/out"
              value={`${formatCount(data.total_tokens_in)}/${formatCount(data.total_tokens_out)}`}
            />
            <StatTile label="Calls" value={formatCount(data.total_calls)} />
            <StatTile label="Avg. latency" value={formatLatency(data.avg_latency_ms)} />
          </div>

          <Card className="mb-6">
            <CardHeader>
              <CardTitle>Spend over time (24h)</CardTitle>
            </CardHeader>
            <CardContent>
              <CostSeriesChart points={data.last_24h} />
            </CardContent>
          </Card>

          <div className="grid gap-6 sm:grid-cols-2">
            {BREAKDOWNS.map((b) => (
              <Card key={b.key}>
                <CardHeader>
                  <CardTitle>{b.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <CostBreakdownBars rows={data[b.key]} />
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
}
