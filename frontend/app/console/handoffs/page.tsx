"use client"

import * as React from "react"
import { AnimatePresence } from "framer-motion"
import { ChevronDown, Headset } from "lucide-react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import type { Handoff, HandoffQueue } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { ListRowSkeleton } from "@/components/console/list-row-skeleton"
import { HandoffCard, ResolvedHandoffRow } from "@/components/console/handoff-card"
import { Card, CardContent } from "@/components/ui/card"

const RESOLVED_CAP = 20

export default function HandoffsPage() {
  const [queue, setQueue] = React.useState<HandoffQueue | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [busyIds, setBusyIds] = React.useState<Set<string>>(new Set())
  const [resolvedOpen, setResolvedOpen] = React.useState(false)
  const busyRef = React.useRef<Set<string>>(new Set())

  const load = React.useCallback(async (signal?: { cancelled: boolean }) => {
    try {
      const res = await api.get<HandoffQueue>(`${API_V1}/console/handoffs`)
      if (!signal?.cancelled) setQueue(res)
    } catch (err) {
      if (signal?.cancelled) return
      setError(err instanceof ApiError ? err.message : "Couldn't load the handoff queue.")
      setQueue({ active: [], resolved: [] })
    }
  }, [])

  React.useEffect(() => {
    const signal = { cancelled: false }
    void load(signal)
    return () => {
      signal.cancelled = true
    }
  }, [load])

  function setBusy(id: string, value: boolean) {
    setBusyIds((prev) => {
      const next = new Set(prev)
      if (value) next.add(id)
      else next.delete(id)
      return next
    })
  }

  async function handleClaim(id: string) {
    if (busyRef.current.has(id)) return
    busyRef.current.add(id)
    setBusy(id, true)
    // Optimistic: flip to claimed immediately so the Resolve action appears.
    setQueue((prev) =>
      prev
        ? {
            ...prev,
            active: prev.active.map((h) => (h.id === id ? { ...h, status: "claimed" } : h)),
          }
        : prev
    )
    try {
      const updated = await api.post<Handoff>(`${API_V1}/console/handoffs/${id}/claim`)
      setQueue((prev) =>
        prev ? { ...prev, active: prev.active.map((h) => (h.id === id ? updated : h)) } : prev
      )
      toast.success("Handoff claimed", { description: "It's yours to resolve." })
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't claim that handoff"))
      await load() // reconcile (e.g. a colleague claimed it first)
    } finally {
      busyRef.current.delete(id)
      setBusy(id, false)
    }
  }

  async function handleResolve(id: string, note: string) {
    if (busyRef.current.has(id)) return
    busyRef.current.add(id)
    setBusy(id, true)
    try {
      const updated = await api.post<Handoff>(`${API_V1}/console/handoffs/${id}/resolve`, { note })
      setQueue((prev) =>
        prev
          ? {
              active: prev.active.filter((h) => h.id !== id),
              resolved: [updated, ...prev.resolved].slice(0, RESOLVED_CAP),
            }
          : prev
      )
      toast.success("Handoff resolved", { description: "The customer has been notified." })
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't resolve that handoff"))
      await load()
    } finally {
      busyRef.current.delete(id)
      setBusy(id, false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <ConsolePageHeader
        title="Handoffs"
        description="When Sarathi steps aside for a person - conversations queued for a human relationship manager."
      />

      {error && (
        <Card className="mb-4">
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {queue === null ? (
        <ListRowSkeleton count={3} />
      ) : queue.active.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <Headset className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Nothing waiting - Sarathi is handling every conversation.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {queue.active.map((handoff) => (
              <HandoffCard
                key={handoff.id}
                handoff={handoff}
                busy={busyIds.has(handoff.id)}
                onClaim={handleClaim}
                onResolve={handleResolve}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      {queue && queue.resolved.length > 0 && (
        <div className="mt-8">
          <button
            type="button"
            onClick={() => setResolvedOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-sm text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronDown className={cn("size-4 transition-transform", resolvedOpen && "rotate-180")} />
            Resolved ({queue.resolved.length})
          </button>
          {resolvedOpen && (
            <div className="mt-3 flex flex-col gap-2">
              {queue.resolved.map((handoff) => (
                <ResolvedHandoffRow key={handoff.id} handoff={handoff} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
