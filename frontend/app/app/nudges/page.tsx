"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { AnimatePresence } from "framer-motion"
import { PartyPopper } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError } from "@/lib/api"
import { ctaUrl } from "@/lib/customer-types"
import type { Nudge } from "@/lib/customer-types"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { NudgeCard } from "@/components/customer/nudge-card"

export default function NudgesPage() {
  const router = useRouter()
  const [nudges, setNudges] = React.useState<Nudge[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [busyIds, setBusyIds] = React.useState<Set<string>>(new Set())
  const seenSentRef = React.useRef<Set<string>>(new Set())

  React.useEffect(() => {
    let cancelled = false
    api
      .get<{ nudges: Nudge[] }>(`${API_V1}/me/nudges`)
      .then((res) => {
        if (!cancelled) setNudges(res.nudges.filter((n) => n.status !== "dismissed" && n.status !== "acted"))
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load your nudges.")
        setNudges([])
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
          <CardContent className="py-4 text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {nudges === null ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="flex items-center gap-3 pt-4">
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
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-muted">
            <PartyPopper className="size-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">All caught up</p>
          <p className="max-w-xs text-sm text-muted-foreground">
            No nudges right now - Sarathi will let you know when something&apos;s worth a look.
          </p>
        </div>
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
