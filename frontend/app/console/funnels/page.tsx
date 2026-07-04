"use client"

import * as React from "react"

import { api, API_V1, ApiError } from "@/lib/api"
import type { FunnelsResponse } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { FunnelBars } from "@/components/console/funnel-bars"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const ACQUISITION_STAGES = [
  { key: "lead", label: "Lead" },
  { key: "qualified", label: "Qualified" },
  { key: "kyc", label: "KYC" },
  { key: "opened", label: "Opened" },
]

const NUDGE_STAGES = [
  { key: "sent", label: "Sent" },
  { key: "seen", label: "Seen" },
  { key: "acted", label: "Acted" },
]

const HOLDING_STAGES = [
  { key: "offered", label: "Offered" },
  { key: "active", label: "Active" },
]

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
          <CardContent className="py-4 text-sm text-muted-foreground">{error}</CardContent>
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
                  count: data.acquisition?.[s.key] ?? 0,
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
                  count: data.adoption?.nudges?.[s.key] ?? 0,
                }))}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Holding adoption</CardTitle>
            </CardHeader>
            <CardContent>
              <FunnelBars
                stages={HOLDING_STAGES.map((s) => ({
                  label: s.label,
                  count: data.adoption?.holdings?.[s.key] ?? 0,
                }))}
              />
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  )
}
