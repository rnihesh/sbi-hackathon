"use client"

import * as React from "react"
import { Suspense } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { motion } from "framer-motion"
import { Waypoints } from "lucide-react"

import { api, API_V1, ApiError } from "@/lib/api"
import { formatCount, formatLatency, formatRelativeTime, formatUsd, pluralize } from "@/lib/format"
import { staggerContainer, staggerItem } from "@/lib/motion"
import type { TraceSummary } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { TraceStatusBadge } from "@/components/console/trace-status-badge"
import { TriggerChip } from "@/components/console/trigger-chip"
import { ListRowSkeleton } from "@/components/console/list-row-skeleton"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

const TRIGGER_FILTERS = [
  { value: "all", label: "All" },
  { value: "chat", label: "Chat" },
  { value: "event", label: "Event" },
] as const

type TriggerFilter = (typeof TRIGGER_FILTERS)[number]["value"]

function parseTriggerFilter(value: string | null): TriggerFilter {
  return value === "chat" || value === "event" ? value : "all"
}

export default function TracesPage() {
  // `useSearchParams` requires an enclosing Suspense boundary (see
  // `components/auth/sign-in-sheet-context.tsx` for the same pattern) - the
  // fallback mirrors the loaded page's shell so there's no layout shift.
  return (
    <Suspense fallback={<TracesPageFallback />}>
      <TracesPageContent />
    </Suspense>
  )
}

function TracesPageContent() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [traces, setTraces] = React.useState<TraceSummary[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [filter, setFilter] = React.useState<TriggerFilter>(() =>
    parseTriggerFilter(searchParams.get("trigger"))
  )

  function updateFilter(next: TriggerFilter) {
    setFilter(next)
    const params = new URLSearchParams(searchParams.toString())
    if (next === "all") params.delete("trigger")
    else params.set("trigger", next)
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }

  React.useEffect(() => {
    let cancelled = false
    setTraces(null)
    const query = filter === "all" ? "" : `?trigger=${filter}`
    api
      .get<TraceSummary[]>(`${API_V1}/console/traces${query}`)
      .then((res) => {
        if (!cancelled) setTraces(res)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load traces.")
        setTraces([])
      })
    return () => {
      cancelled = true
    }
  }, [filter])

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <ConsolePageHeader
          title="Traces"
          description="Every agent run - node, tool, model, tokens, latency, cost."
        />
        <Tabs value={filter} onValueChange={(v) => updateFilter(v as TriggerFilter)}>
          <TabsList>
            {TRIGGER_FILTERS.map((f) => (
              <TabsTrigger key={f.value} value={f.value}>
                {f.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {error && (
        <Card className="mb-4">
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {traces === null ? (
        <ListRowSkeleton count={6} />
      ) : traces.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <Waypoints className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No {filter === "all" ? "" : `${filter} `}agent runs yet - traces appear as soon as an
            agent executes.
          </p>
        </div>
      ) : (
        <motion.div variants={staggerContainer} initial="initial" animate="animate">
          {/* Cards - mobile */}
          <div className="flex flex-col gap-3 md:hidden">
            {traces.map((trace) => (
              <motion.div key={trace.run_id} variants={staggerItem}>
                <Link href={`/console/traces/${trace.run_id}`}>
                  <Card className="transition-colors hover:bg-muted/50">
                    <CardContent className="flex flex-col gap-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary" className="capitalize">
                            {trace.agent}
                          </Badge>
                          <TriggerChip trigger={trace.trigger} />
                        </div>
                        <TraceStatusBadge status={trace.status} />
                      </div>
                      <p className="text-sm font-medium">
                        {trace.customer?.full_name ?? "No customer"}
                      </p>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs tabular-nums text-muted-foreground">
                        <span>{formatRelativeTime(trace.started_at)}</span>
                        <span>{formatLatency(trace.latency_ms)}</span>
                        <span>
                          {formatCount(trace.tokens_in)}/{formatCount(trace.tokens_out)} tok
                        </span>
                        <span>{formatUsd(trace.cost_usd)}</span>
                        <span>
                          {trace.steps_count} {pluralize(trace.steps_count, "step")}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              </motion.div>
            ))}
          </div>

          {/* Table - desktop */}
          <div className="hidden overflow-x-auto rounded-xl border border-border md:block">
            <table className="w-full min-w-[860px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2.5 font-medium">Agent</th>
                  <th className="px-4 py-2.5 font-medium">Trigger</th>
                  <th className="px-4 py-2.5 font-medium">Customer</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Started</th>
                  <th className="px-4 py-2.5 text-right font-medium">Latency</th>
                  <th className="px-4 py-2.5 text-right font-medium">Tokens in/out</th>
                  <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                  <th className="px-4 py-2.5 text-right font-medium">Steps</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {traces.map((trace) => (
                  <motion.tr
                    key={trace.run_id}
                    variants={staggerItem}
                    onClick={() => router.push(`/console/traces/${trace.run_id}`)}
                    className="cursor-pointer transition-colors hover:bg-muted/50"
                  >
                    <td className="p-0">
                      <Link
                        href={`/console/traces/${trace.run_id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="flex items-center px-4 py-3"
                      >
                        <Badge variant="secondary" className="capitalize">
                          {trace.agent}
                        </Badge>
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <TriggerChip trigger={trace.trigger} />
                    </td>
                    <td className="px-4 py-3">{trace.customer?.full_name ?? "-"}</td>
                    <td className="px-4 py-3">
                      <TraceStatusBadge status={trace.status} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                      {formatRelativeTime(trace.started_at)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-muted-foreground">
                      {formatLatency(trace.latency_ms)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-muted-foreground">
                      {formatCount(trace.tokens_in)}/{formatCount(trace.tokens_out)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums">
                      {formatUsd(trace.cost_usd)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-muted-foreground">
                      {trace.steps_count}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>
      )}
    </div>
  )
}

/** Mirrors `TracesPageContent`'s loaded shell so the Suspense boundary above it
 * never causes a visible layout jump. */
function TracesPageFallback() {
  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <ConsolePageHeader
          title="Traces"
          description="Every agent run - node, tool, model, tokens, latency, cost."
        />
        <Tabs value="all">
          <TabsList>
            {TRIGGER_FILTERS.map((f) => (
              <TabsTrigger key={f.value} value={f.value} disabled>
                {f.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
      <ListRowSkeleton count={6} />
    </div>
  )
}
