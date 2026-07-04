"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { AnimatePresence } from "framer-motion"
import { PartyPopper, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError } from "@/lib/api"
import { ctaUrl } from "@/lib/customer-types"
import type { DashboardResponse, Nudge } from "@/lib/customer-types"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { NudgeCard } from "@/components/customer/nudge-card"

/** While a demo-activity load (or the sim engine) is still working through the
 * event pipeline, transactions exist before the worker has produced any
 * nudges from them yet. Re-poll gently during that gap instead of leaving the
 * "all caught up" empty state up, which reads as "nothing will ever show up"
 * rather than "still thinking." */
const ANALYZING_POLL_MS = 20_000

export default function NudgesPage() {
  const router = useRouter()
  const [nudges, setNudges] = React.useState<Nudge[] | null>(null)
  const [hasActivity, setHasActivity] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [busyIds, setBusyIds] = React.useState<Set<string>>(new Set())
  const seenSentRef = React.useRef<Set<string>>(new Set())

  const loadNudges = React.useCallback(async () => {
    const res = await api.get<{ nudges: Nudge[] }>(`${API_V1}/me/nudges`)
    return res.nudges.filter((n) => n.status !== "dismissed" && n.status !== "acted")
  }, [])

  React.useEffect(() => {
    let cancelled = false
    Promise.all([
      loadNudges(),
      api.get<DashboardResponse>(`${API_V1}/me/dashboard`).catch(() => null),
    ])
      .then(([nextNudges, dashboard]) => {
        if (cancelled) return
        setNudges(nextNudges)
        setHasActivity((dashboard?.recent_transactions.length ?? 0) > 0)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load your nudges.")
        setNudges([])
      })
    return () => {
      cancelled = true
    }
  }, [loadNudges])

  // Sarathi's nudge-generating agents run async off the event stream - if
  // there's activity but nothing to show yet, keep checking quietly rather
  // than making the customer refresh the page themselves.
  React.useEffect(() => {
    if (!hasActivity || nudges === null || nudges.length > 0) return
    const interval = setInterval(() => {
      loadNudges()
        .then((next) => {
          if (next.length > 0) setNudges(next)
        })
        .catch(() => {
          // Transient poll failure - the next tick will retry.
        })
    }, ANALYZING_POLL_MS)
    return () => clearInterval(interval)
  }, [hasActivity, nudges, loadNudges])

  function setBusy(id: string, value: boolean) {
    setBusyIds((prev) => {
      const next = new Set(prev)
      if (value) next.add(id)
      else next.delete(id)
      return next
    })
  }

  async function act(id: string, action: "seen" | "acted" | "dismissed") {
    try {
      await api.post(`${API_V1}/me/nudges/${id}/act`, { action })
    } catch (err) {
      if (action !== "seen") {
        toast.error(err instanceof ApiError ? err.message : "Couldn't update that nudge")
      }
      throw err
    }
  }

  function handleSeen(id: string) {
    if (seenSentRef.current.has(id)) return
    seenSentRef.current.add(id)
    void act(id, "seen")
  }

  async function handleAct(nudge: Nudge) {
    setBusy(nudge.id, true)
    try {
      await act(nudge.id, "acted")
      setNudges((prev) => prev?.filter((n) => n.id !== nudge.id) ?? null)
      const url = ctaUrl(nudge)
      if (url) {
        if (url.startsWith("/")) router.push(url)
        else window.open(url, "_blank", "noopener,noreferrer")
      }
    } catch {
      setBusy(nudge.id, false)
    }
  }

  async function handleDismiss(id: string) {
    setBusy(id, true)
    try {
      await act(id, "dismissed")
      setNudges((prev) => prev?.filter((n) => n.id !== id) ?? null)
    } catch {
      setBusy(id, false)
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Nudges</h1>
        <p className="text-sm text-muted-foreground">Timely suggestions, never spam.</p>
      </div>

      {error && (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {nudges === null ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="flex items-center gap-3">
                <Skeleton className="size-10 shrink-0 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : nudges.length === 0 ? (
        hasActivity ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="flex size-12 items-center justify-center rounded-full bg-muted">
              <Sparkles className="size-5 animate-pulse text-muted-foreground" />
            </div>
            <p className="text-sm font-medium">Sarathi is analyzing your activity</p>
            <p className="max-w-xs text-sm text-muted-foreground">
              New nudges usually show up within a few minutes of fresh activity. This page will
              update on its own - no need to refresh.
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="flex size-12 items-center justify-center rounded-full bg-muted">
              <PartyPopper className="size-5 text-muted-foreground" />
            </div>
            <p className="text-sm font-medium">All caught up</p>
            <p className="max-w-xs text-sm text-muted-foreground">
              No nudges right now - Sarathi will let you know when something&apos;s worth a look.
            </p>
          </div>
        )
      ) : (
        <div className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {nudges.map((nudge) => (
              <NudgeCard
                key={nudge.id}
                nudge={nudge}
                onSeen={handleSeen}
                onAct={handleAct}
                onDismiss={handleDismiss}
                busy={busyIds.has(nudge.id)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
