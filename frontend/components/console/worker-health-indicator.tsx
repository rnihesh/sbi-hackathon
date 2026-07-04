"use client"

import * as React from "react"
import { AlertTriangle } from "lucide-react"

import { cn } from "@/lib/utils"
import { api, API_V1 } from "@/lib/api"
import { formatRelativeTime } from "@/lib/format"
import type { ConsoleHealth } from "@/lib/console-types"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

const POLL_INTERVAL_MS = 20_000

type Severity = "green" | "amber" | "red" | "unknown"

const DOT_CLASS: Record<Severity, string> = {
  green: "bg-primary",
  amber: "bg-amber-500",
  red: "bg-destructive",
  unknown: "bg-muted-foreground/40",
}

const LABEL: Record<Severity, string> = {
  green: "Worker healthy",
  amber: "Worker degraded",
  red: "Worker down",
  unknown: "Worker status unknown",
}

function severityOf(health: ConsoleHealth | null): Severity {
  if (!health) return "unknown"
  if (!health.worker.alive) return "red"
  if (health.worker.dlq > 0) return "amber"
  return "green"
}

/** Polls `GET /console/health` and renders a small traffic-light dot for the
 * `event_consumer` worker's liveness - the demo's only non-obvious moving
 * part (chat/dashboard work with no worker at all; only sim-driven life-event
 * detection depends on it running). */
export function WorkerHealthIndicator() {
  const [health, setHealth] = React.useState<ConsoleHealth | null>(null)

  React.useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const res = await api.get<ConsoleHealth>(`${API_V1}/console/health`)
        if (!cancelled) setHealth(res)
      } catch {
        if (!cancelled) setHealth(null)
      }
    }

    void poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const severity = severityOf(health)

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex items-center gap-1.5 rounded-full border border-border px-2 py-1 text-xs text-muted-foreground">
          <span className="relative flex size-2">
            {severity === "green" && (
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:animate-none" />
            )}
            <span className={cn("relative inline-flex size-2 rounded-full", DOT_CLASS[severity])} />
          </span>
          <span className="hidden sm:inline">Worker</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="flex flex-col items-start gap-0.5">
        <p className="font-medium text-background">{LABEL[severity]}</p>
        <p className="text-background/70">
          {health?.worker.last_event_at
            ? `Last event ${formatRelativeTime(health.worker.last_event_at)}`
            : "No events processed yet"}
        </p>
        {health && health.worker.pending > 0 && (
          <p className="text-background/70">{health.worker.pending} pending</p>
        )}
        {health && health.worker.dlq > 0 && (
          <p className="flex items-center gap-1 text-amber-400">
            <AlertTriangle className="size-3" /> {health.worker.dlq} in dead-letter queue
          </p>
        )}
      </TooltipContent>
    </Tooltip>
  )
}
