"use client"

import * as React from "react"

import { api, API_V1, ApiError } from "@/lib/api"
import type { FunnelsResponse } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { FunnelBars } from "@/components/console/funnel-bars"
import { HoldingsCategoryBars } from "@/components/console/holdings-category-bars"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const ACQUISITION_STAGES = [
  { key: "leads", label: "Leads" },
  { key: "qualified", label: "Qualified" },
  { key: "kyc_verified", label: "KYC Verified" },
  { key: "account_opened", label: "Account Opened" },
] as const

const NUDGE_STAGES = [
  { key: "sent", label: "Sent" },
  { key: "seen", label: "Seen" },
  { key: "acted", label: "Acted" },
] as const

export default function FunnelsPage() {
  const [data, setData] = React.useState<FunnelsResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .get<FunnelsResponse>(`${API_V1}/console/funnels`)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load funnels.")
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <ConsolePageHeader
        title="Funnels"
        description="Onboarding conversion and adoption, stage by stage."
      />

      {error && (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {!data && !error ? (
        <Card>
          <CardHeader>
            <CardTitle>Acquisition funnel</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full rounded-md" />
            ))}
          </CardContent>
        </Card>
      ) : data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Acquisition funnel</CardTitle>
            </CardHeader>
            <CardContent>
              <FunnelBars
                stages={ACQUISITION_STAGES.map((s) => ({
                  label: s.label,
                  count: data.acquisition[s.key] ?? 0,
                }))}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Nudge adoption</CardTitle>
            </CardHeader>
            <CardContent>
              <FunnelBars
                stages={NUDGE_STAGES.map((s) => ({
                  label: s.label,
                  count: data.nudges[s.key] ?? 0,
                }))}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Holdings by category</CardTitle>
            </CardHeader>
            <CardContent>
              <HoldingsCategoryBars categories={data.holdings_by_category} />
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  )
}
