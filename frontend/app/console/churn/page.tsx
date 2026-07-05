"use client"

import * as React from "react"
import { ShieldCheck } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import { formatCount, formatPaise, formatRelativeTime } from "@/lib/format"
import type { ChurnAtRiskCustomer, ChurnCockpitResponse } from "@/lib/console-types"
import { ChurnDistributionBars } from "@/components/console/churn-distribution-bars"
import { ConsolePageHeader } from "@/components/console/page-header"
import { CustomerLink } from "@/components/console/customer-link"
import { IntentScoreBar } from "@/components/console/intent-score-bar"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const COLUMNS = ["Customer", "Risk", "Last activity", "Balance", "Nudges (30d)", ""]

function ReengageButton({
  requested,
  busy,
  onRequest,
}: {
  requested: boolean
  busy: boolean
  onRequest: () => void
}) {
  return (
    <Button
      size="sm"
      variant={requested ? "outline" : "default"}
      disabled={requested || busy}
      onClick={onRequest}
      className="shrink-0"
    >
      {requested ? "Requested" : busy ? "Requesting..." : "Request re-engagement"}
    </Button>
  )
}

export default function ChurnPage() {
  const [data, setData] = React.useState<ChurnCockpitResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [requestedIds, setRequestedIds] = React.useState<Set<string>>(new Set())
  const [busyIds, setBusyIds] = React.useState<Set<string>>(new Set())
  const busyRef = React.useRef<Set<string>>(new Set())

  React.useEffect(() => {
    let cancelled = false
    api
      .get<ChurnCockpitResponse>(`${API_V1}/console/churn`)
      .then((res) => {
        if (cancelled) return
        setData(res)
        setRequestedIds(
          new Set(res.at_risk.filter((c) => c.reengage_requested).map((c) => c.id))
        )
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load the churn cockpit.")
        setData({ distribution: [], at_risk: [], unscored: 0 })
      })
    return () => {
      cancelled = true
    }
  }, [])

  function setBusy(id: string, value: boolean) {
    setBusyIds((prev) => {
      const next = new Set(prev)
      if (value) next.add(id)
      else next.delete(id)
      return next
    })
  }

  async function handleReengage(customer: ChurnAtRiskCustomer) {
    if (busyRef.current.has(customer.id) || requestedIds.has(customer.id)) return
    busyRef.current.add(customer.id)
    setBusy(customer.id, true)
    try {
      await api.post(`${API_V1}/console/churn/${customer.id}/re-engage`)
      setRequestedIds((prev) => new Set(prev).add(customer.id))
      toast.success("Re-engagement requested", {
        description: `A pending proposal was created for ${customer.full_name}.`,
      })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Another staff member already requested this - the roster was just
        // stale, not the action failing. Same end state as success.
        setRequestedIds((prev) => new Set(prev).add(customer.id))
        toast.success("Already requested", {
          description: "A re-engagement proposal is already pending for this customer.",
        })
      } else {
        toast.error(describeApiError(err, "Couldn't request re-engagement"))
      }
    } finally {
      busyRef.current.delete(customer.id)
      setBusy(customer.id, false)
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <ConsolePageHeader
        title="Churn cockpit"
        description="Risk distribution across the book and the customers most likely to leave."
      />

      {error && (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Risk distribution</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {data === null ? (
            <Skeleton className="h-40 w-full rounded-xl" />
          ) : (
            <ChurnDistributionBars buckets={data.distribution} />
          )}
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-3 shrink-0 text-primary" />
            <span>
              {data === null
                ? "Loading..."
                : `${formatCount(data.unscored)} customer${data.unscored === 1 ? "" : "s"} not yet scored - scored when the engagement agent reviews their activity.`}
            </span>
          </p>
        </CardContent>
      </Card>

      <div>
        <h2 className="mb-3 text-sm font-semibold">
          At risk (churn risk 60%+){" "}
          {data && data.at_risk.length > 0 && (
            <span className="font-normal text-muted-foreground">({data.at_risk.length})</span>
          )}
        </h2>

        {data === null ? (
          <AtRiskSkeleton />
        ) : data.at_risk.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
            <p className="text-sm text-muted-foreground">
              Nobody is currently at high churn risk.
            </p>
          </div>
        ) : (
          <>
            {/* Cards - mobile */}
            <div className="flex flex-col gap-3 md:hidden">
              {data.at_risk.map((customer) => (
                <Card key={customer.id}>
                  <CardContent className="flex flex-col gap-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-sm font-medium">
                        <CustomerLink id={customer.id}>{customer.full_name}</CustomerLink>
                      </span>
                    </div>
                    <IntentScoreBar score={customer.churn_risk} />
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>
                        {customer.last_activity_at
                          ? formatRelativeTime(customer.last_activity_at)
                          : "No activity on file"}
                      </span>
                      <span className="font-mono tabular-nums text-foreground">
                        {formatPaise(customer.balance_paise)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-muted-foreground">
                        {customer.nudges_last_30d} nudge
                        {customer.nudges_last_30d === 1 ? "" : "s"} in last 30d
                      </span>
                      <ReengageButton
                        requested={requestedIds.has(customer.id)}
                        busy={busyIds.has(customer.id)}
                        onRequest={() => void handleReengage(customer)}
                      />
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* Table - desktop */}
            <div className="hidden overflow-x-auto rounded-xl border border-border md:block">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    {COLUMNS.map((col) => (
                      <th key={col} className="px-4 py-2.5 font-medium">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.at_risk.map((customer) => (
                    <tr key={customer.id}>
                      <td className="px-4 py-3">
                        <p className="font-medium">
                          <CustomerLink id={customer.id}>{customer.full_name}</CustomerLink>
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        <IntentScoreBar score={customer.churn_risk} />
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                        {customer.last_activity_at
                          ? formatRelativeTime(customer.last_activity_at)
                          : "No activity on file"}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap font-mono tabular-nums">
                        {formatPaise(customer.balance_paise)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                        {customer.nudges_last_30d}
                      </td>
                      <td className="px-4 py-3">
                        <ReengageButton
                          requested={requestedIds.has(customer.id)}
                          busy={busyIds.has(customer.id)}
                          onRequest={() => void handleReengage(customer)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function AtRiskSkeleton() {
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            {COLUMNS.map((col) => (
              <th key={col} className="px-4 py-2.5 font-medium">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {Array.from({ length: 4 }).map((_, row) => (
            <tr key={row}>
              {COLUMNS.map((col) => (
                <td key={col} className="px-4 py-3">
                  <Skeleton className="h-3.5 w-20" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
