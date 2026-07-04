"use client"

import * as React from "react"
import {
  Baby,
  Briefcase,
  ChevronDown,
  Gift,
  Heart,
  Home,
  Plane,
  TrendingUp,
  Truck,
  type LucideIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { formatRelativeTime, humanizeIdentifier } from "@/lib/format"
import { ConfidenceRing } from "@/components/console/confidence-ring"
import type { LifeEventItem } from "@/lib/console-types"

const TYPE_ICON: Record<string, LucideIcon> = {
  job_change: Briefcase,
  new_child: Baby,
  home_intent: Home,
  bonus: Gift,
  salary_hike: TrendingUp,
  marriage: Heart,
  relocation: Truck,
  travel: Plane,
}

export function LifeEventRow({ event }: { event: LifeEventItem }) {
  const [expanded, setExpanded] = React.useState(false)
  const Icon = TYPE_ICON[event.type] ?? Briefcase
  const hasEvidence = Object.keys(event.evidence).length > 0

  return (
    <li className="relative">
      <span className="absolute -left-[1.6rem] top-1 flex size-5 items-center justify-center rounded-full bg-muted">
        <Icon className="size-3 text-muted-foreground" />
      </span>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{formatRelativeTime(event.detected_at)}</p>
          <p className="text-sm font-medium">{humanizeIdentifier(event.type)}</p>
          <p className="text-xs text-muted-foreground">
            {event.customer.full_name} &middot; <span className="capitalize">{event.status}</span>
          </p>
          {hasEvidence && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ChevronDown className={cn("size-3.5 transition-transform", expanded && "rotate-180")} />
              {expanded ? "Hide evidence" : "Show evidence"}
            </button>
          )}
          {expanded && (
            <pre className="mt-2 max-h-56 max-w-md overflow-auto rounded-lg bg-muted p-3 font-mono text-xs">
              {JSON.stringify(event.evidence, null, 2)}
            </pre>
          )}
        </div>
        <ConfidenceRing value={event.confidence} />
      </div>
    </li>
  )
}
