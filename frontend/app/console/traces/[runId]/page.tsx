"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { motion } from "framer-motion"
import { ArrowLeft } from "lucide-react"

import { api, API_V1, ApiError } from "@/lib/api"
import { formatCount, formatLatency, formatRelativeTime, formatUsd } from "@/lib/format"
import { staggerContainer, staggerItem } from "@/lib/motion"
import type { TraceDetail } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { TraceStatusBadge } from "@/components/console/trace-status-badge"
import { TriggerChip } from "@/components/console/trigger-chip"
import { StepKindIcon } from "@/components/console/step-kind-icon"
import { JsonDisclosure } from "@/components/console/json-disclosure"
import { StatTile } from "@/components/console/stat-tile"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export default function TraceDetailPage() {
  const params = useParams<{ runId: string }>()
  const [trace, setTrace] = React.useState<TraceDetail | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [notFound, setNotFound] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    api
      .get<TraceDetail>(`${API_V1}/console/traces/${params.runId}`)
      .then((res) => {
        if (!cancelled) setTrace(res)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true)
        } else {
          setError(err instanceof ApiError ? err.message : "Couldn't load this trace.")
        }
      })
    return () => {
      cancelled = true
    }
  }, [params.runId])

  return (
    <div className="mx-auto max-w-3xl">
      <Link
        href="/console/traces"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        All traces
      </Link>

      {notFound ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">
            No trace found for run <span className="font-mono">{params.runId}</span>.
          </p>
        </div>
      ) : error ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      ) : trace === null ? (
        <TraceDetailSkeleton />
      ) : (
        <>
          <div className="mb-6">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className="capitalize">
                {trace.agent}
              </Badge>
              <TriggerChip trigger={trace.trigger} />
              <TraceStatusBadge status={trace.status} />
            </div>
            <ConsolePageHeader
              title={trace.customer?.full_name ?? "No linked customer"}
              description={`Started ${formatRelativeTime(trace.started_at)}${
                trace.finished_at ? ` - finished ${formatRelativeTime(trace.finished_at)}` : ""
              }`}
            />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatTile label="Latency" value={formatLatency(trace.latency_ms)} />
              <StatTile
                label="Tokens in/out"
                value={`${formatCount(trace.tokens_in)}/${formatCount(trace.tokens_out)}`}
              />
              <StatTile label="Cost" value={formatUsd(trace.cost_usd)} />
              <StatTile label="Steps" value={String(trace.steps.length)} />
            </div>
          </div>

          {trace.steps.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
              <p className="text-sm text-muted-foreground">
                This run has no recorded steps yet.
              </p>
            </div>
          ) : (
            <motion.ol
              variants={staggerContainer}
              initial="initial"
              animate="animate"
              className="relative flex flex-col gap-6 border-l border-border pl-8"
            >
              {trace.steps.map((step) => (
                <motion.li key={step.seq} variants={staggerItem} className="relative">
                  <span className="absolute -left-[2.55rem] top-0">
                    <StepKindIcon kind={step.kind} />
                  </span>
                  <Card>
                    <CardContent className="flex flex-col gap-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-muted-foreground">
                            #{step.seq}
                          </span>
                          <span className="text-sm font-medium">{step.name}</span>
                          <Badge variant="outline" className="capitalize">
                            {step.node}
                          </Badge>
                        </div>
                        <Badge variant="ghost" className="capitalize">
                          {step.kind}
                        </Badge>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs tabular-nums text-muted-foreground">
                        {step.model && <span>{step.model}</span>}
                        <span>
                          {formatCount(step.tokens_in)}/{formatCount(step.tokens_out)} tok
                        </span>
                        <span>{formatUsd(step.cost_usd)}</span>
                        <span>{formatLatency(step.latency_ms)}</span>
                      </div>

                      <div className="flex flex-col gap-2 sm:flex-row sm:gap-6">
                        <div className="flex-1">
                          <JsonDisclosure label="Input" value={step.input} />
                        </div>
                        <div className="flex-1">
                          <JsonDisclosure label="Output" value={step.output} />
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </motion.li>
              ))}
            </motion.ol>
          )}
        </>
      )}
    </div>
  )
}

function TraceDetailSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-4 w-64" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full rounded-xl" />
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-4 border-l border-border pl-8">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-xl" />
        ))}
      </div>
    </div>
  )
}
