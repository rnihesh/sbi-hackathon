"use client"

import * as React from "react"

import { api, API_V1, ApiError } from "@/lib/api"
import { normalizeLifeEvent } from "@/lib/console-types"
import type { LifeEventItem } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { LifeEventRow } from "@/components/console/life-event-row"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export default function LifeEventsPage() {
  const [events, setEvents] = React.useState<LifeEventItem[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .get<unknown[]>(`${API_V1}/console/life-events`)
      .then((res) => {
        if (!cancelled) {
          setEvents(res.map(normalizeLifeEvent).filter((e): e is LifeEventItem => e !== null))
        }
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load life events.")
        setEvents([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="mx-auto max-w-3xl">
      <ConsolePageHeader
        title="Life Events"
        description="Job changes, new children, home intent - detected as they happen."
      />

      {error && (
        <Card className="mb-4">
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {events === null ? (
        <ol className="relative flex flex-col gap-6 border-l border-border pl-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <li key={i} className="relative">
              <span className="absolute -left-[1.6rem] top-1 size-2.5 rounded-full bg-primary/60" />
              <Skeleton className="mb-2 h-3.5 w-24" />
              <Skeleton className="h-4 w-2/3" />
            </li>
          ))}
        </ol>
      ) : events.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">No life events detected yet.</p>
        </div>
      ) : (
        <ol className="relative flex flex-col gap-6 border-l border-border pl-6">
          {events.map((event) => (
            <LifeEventRow key={event.id} event={event} />
          ))}
        </ol>
      )}
    </div>
  )
}
