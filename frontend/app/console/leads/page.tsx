"use client"

import * as React from "react"

import { api, API_V1, ApiError } from "@/lib/api"
import { formatRelativeTime, humanizeIdentifier } from "@/lib/format"
import { normalizeLead } from "@/lib/console-types"
import type { Lead } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { CustomerLink } from "@/components/console/customer-link"
import { IntentScoreBar } from "@/components/console/intent-score-bar"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const COLUMNS = ["Customer", "Stage", "Intent", "Created"]

function stageBadgeVariant(stage: string): "default" | "destructive" | "secondary" {
  if (stage === "converted") return "default"
  if (stage === "lost") return "destructive"
  return "secondary"
}

/** The lead's display name - linked to the 360 view once it has converted to a
 * linked `Customer` (prospects with no `customer` yet have nowhere to link). */
function LeadName({ lead }: { lead: Lead }) {
  const name = lead.name ?? lead.customer?.full_name ?? "Unnamed lead"
  if (!lead.customer) return <>{name}</>
  return <CustomerLink id={lead.customer.id}>{name}</CustomerLink>
}

export default function LeadsPage() {
  const [leads, setLeads] = React.useState<Lead[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .get<unknown[]>(`${API_V1}/console/leads`)
      .then((res) => {
        if (!cancelled) setLeads(res.map(normalizeLead).filter((l): l is Lead => l !== null))
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load leads.")
        setLeads([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="mx-auto max-w-5xl">
      <ConsolePageHeader
        title="Leads"
        description="Acquisition candidates surfaced by the AcquisitionAgent."
      />

      {error && (
        <Card className="mb-4">
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {leads === null ? (
        <LeadsSkeleton />
      ) : leads.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">No leads yet.</p>
        </div>
      ) : (
        <>
          {/* Cards - mobile */}
          <div className="flex flex-col gap-3 md:hidden">
            {leads.map((lead) => (
              <Card key={lead.id}>
                <CardContent className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium">
                      <LeadName lead={lead} />
                    </span>
                    <Badge variant={stageBadgeVariant(lead.stage)} className="shrink-0 capitalize">
                      {humanizeIdentifier(lead.stage)}
                    </Badge>
                  </div>
                  <span className="block truncate text-xs text-muted-foreground">
                    {lead.email ?? lead.phone ?? "No contact on file"} &middot; via {lead.source}
                  </span>
                  <IntentScoreBar score={lead.intent_score} />
                  <span className="text-xs text-muted-foreground">
                    {formatRelativeTime(lead.created_at)}
                  </span>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Table - desktop */}
          <div className="hidden overflow-x-auto rounded-xl border border-border md:block">
            <table className="w-full min-w-[560px] text-sm">
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
                {leads.map((lead) => (
                  <tr key={lead.id}>
                    <td className="px-4 py-3">
                      <p className="font-medium">
                        <LeadName lead={lead} />
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {lead.email ?? lead.phone ?? "No contact on file"} &middot; via {lead.source}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={stageBadgeVariant(lead.stage)} className="capitalize">
                        {humanizeIdentifier(lead.stage)}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <IntentScoreBar score={lead.intent_score} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                      {formatRelativeTime(lead.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

function LeadsSkeleton() {
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[560px] text-sm">
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
          {Array.from({ length: 6 }).map((_, row) => (
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
