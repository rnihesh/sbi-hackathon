"use client"

import * as React from "react"
import Link from "next/link"
import { AnimatePresence, motion } from "framer-motion"
import { Brain, ChevronLeft, Sparkles, Trash2, X } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import { formatPaise, formatRelativeTime, humanizeIdentifier } from "@/lib/format"
import { languageLabel } from "@/lib/languages"
import { springSoft } from "@/lib/motion"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { useFocusReturn } from "@/lib/use-focus-return"

type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "ghost" | "link"

interface MemoryItem {
  id: string
  kind: string
  text: string
  created_at: string
}

interface MemoryPayload {
  memories: MemoryItem[]
  profile_facts: Record<string, unknown>
}

/** Friendly label + chip style for each memory kind the backend stores. */
const KIND_META: Record<string, { label: string; variant: BadgeVariant }> = {
  episodic: { label: "Conversation", variant: "secondary" },
  fact: { label: "Fact", variant: "outline" },
  preference: { label: "Preference", variant: "secondary" },
}

function kindMeta(kind: string): { label: string; variant: BadgeVariant } {
  return KIND_META[kind] ?? { label: humanizeIdentifier(kind), variant: "secondary" }
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []
}

interface FactRow {
  label: string
  value: string
}

/** Turn the raw agent-facing `profile_facts` snapshot into a humanised,
 * customer-readable list. Internal keys (ids, churn scores, the duplicate
 * `income` alias, and the fact/preference arrays already shown as memory
 * rows) are intentionally left out. */
function buildFactRows(facts: Record<string, unknown>): FactRow[] {
  const rows: FactRow[] = []
  const push = (label: string, value: string | null) => {
    if (value) rows.push({ label, value })
  }

  push("Name", asString(facts.name))
  push("City", asString(facts.city))
  push("State", asString(facts.state))
  push("Occupation", asString(facts.occupation))

  const segment = asString(facts.segment)
  push("Segment", segment ? humanizeIdentifier(segment) : null)

  const income = asFiniteNumber(facts.annual_income_paise)
  push("Annual income", income !== null ? formatPaise(income) : null)

  const risk = asString(facts.risk)
  push("Risk appetite", risk ? humanizeIdentifier(risk) : null)

  const maturity = asString(facts.digital_maturity)
  push("Digital comfort", maturity ? humanizeIdentifier(maturity) : null)

  const held = asStringList(facts.held_product_codes)
  push("Products held", held.length ? held.map(humanizeIdentifier).join(", ") : null)

  const language = asString(facts.preferred_language)
  push("Chat language", language ? languageLabel(language) : null)

  return rows
}

export default function MemoryPage() {
  const [payload, setPayload] = React.useState<MemoryPayload | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [noProfile, setNoProfile] = React.useState(false)
  const [pendingForget, setPendingForget] = React.useState<MemoryItem | null>(null)
  const [forgettingOne, setForgettingOne] = React.useState(false)
  const [confirmForgetAll, setConfirmForgetAll] = React.useState(false)
  const [forgettingAll, setForgettingAll] = React.useState(false)
  const { captureFocus, onCloseAutoFocus } = useFocusReturn()

  const load = React.useCallback(async (showSkeleton: boolean) => {
    if (showSkeleton) setLoading(true)
    try {
      const res = await api.get<MemoryPayload>(`${API_V1}/me/memory`)
      setPayload(res)
      setError(null)
      setNoProfile(false)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNoProfile(true)
        setError(null)
      } else {
        setError(describeApiError(err, "Couldn't load your memory."))
      }
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void load(true)
  }, [load])

  async function handleForgetOne() {
    if (!pendingForget) return
    const target = pendingForget
    setForgettingOne(true)
    try {
      await api.delete(`${API_V1}/me/memory/${target.id}`)
      // Remove after the API confirms so the exit animation only plays on success.
      setPayload((prev) =>
        prev ? { ...prev, memories: prev.memories.filter((m) => m.id !== target.id) } : prev
      )
      setPendingForget(null)
      toast.success("Forgotten", { description: "Sarathi no longer remembers that." })
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't forget that memory"))
    } finally {
      setForgettingOne(false)
    }
  }

  async function handleForgetAll() {
    setForgettingAll(true)
    try {
      const res = await api.delete<{ deleted: number }>(`${API_V1}/me/memory`)
      setConfirmForgetAll(false)
      toast.success("Cleared", {
        description:
          res.deleted > 0
            ? `Sarathi forgot ${res.deleted} ${res.deleted === 1 ? "memory" : "memories"}.`
            : "There was nothing left to forget.",
      })
      // Refetch so any facts derived from those memories update too.
      await load(false)
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't clear your memory"))
    } finally {
      setForgettingAll(false)
    }
  }

  const factRows = React.useMemo(
    () => (payload ? buildFactRows(payload.profile_facts) : []),
    [payload]
  )
  const memories = payload?.memories ?? []

  return (
    <>
      <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
        <div className="flex flex-col gap-3">
          <Link
            href="/app/profile"
            className="flex w-fit items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronLeft className="size-4" />
            Profile
          </Link>
          <div>
            <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
              <Brain className="size-5 text-primary" />
              What Sarathi knows about you
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Sarathi remembers context from your conversations to serve you better. It is your
              information: you can forget any of it, any time.
            </p>
          </div>
        </div>

        {error && (
          <Card>
            <CardContent className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <span>{error}</span>
              <Button variant="outline" size="sm" onClick={() => void load(true)}>
                Retry
              </Button>
            </CardContent>
          </Card>
        )}

        {loading ? (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-40 w-full rounded-xl" />
            <Skeleton className="h-24 w-full rounded-xl" />
            <Skeleton className="h-24 w-full rounded-xl" />
          </div>
        ) : noProfile ? (
          <EmptyState
            title="Nothing on file yet"
            body="Sarathi hasn't started a profile for you. Chat with it and it will begin learning what matters to you - and you'll be able to review and forget it right here."
          />
        ) : payload ? (
          <>
            <section className="flex flex-col gap-3">
              <h2 className="text-sm font-medium text-muted-foreground">Your profile</h2>
              {factRows.length > 0 ? (
                <div className="rounded-xl border border-border">
                  {factRows.map((row, i) => (
                    <div key={row.label}>
                      <div className="flex items-center justify-between gap-4 px-4 py-3">
                        <span className="text-sm text-muted-foreground">{row.label}</span>
                        <span className="text-right text-sm font-medium">{row.value}</span>
                      </div>
                      {i < factRows.length - 1 && <Separator />}
                    </div>
                  ))}
                </div>
              ) : (
                <Card>
                  <CardContent className="text-sm text-muted-foreground">
                    No profile details on file yet.
                  </CardContent>
                </Card>
              )}
            </section>

            <section className="flex flex-col gap-3">
              <h2 className="text-sm font-medium text-muted-foreground">
                Memories {memories.length > 0 && `(${memories.length})`}
              </h2>

              {memories.length === 0 ? (
                <EmptyState
                  title="No saved memories"
                  body="Sarathi hasn't saved anything from your conversations yet. As you chat, the useful context it picks up will appear here for you to review."
                />
              ) : (
                <>
                  <div className="flex flex-col gap-3">
                    <AnimatePresence initial={false}>
                      {memories.map((item) => {
                        const meta = kindMeta(item.kind)
                        return (
                          <motion.div
                            key={item.id}
                            layout
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0, transition: { duration: 0.18 } }}
                            transition={springSoft}
                            className="overflow-hidden"
                          >
                            <Card>
                              <CardContent className="flex flex-col gap-2">
                                <div className="flex items-center justify-between gap-2">
                                  <Badge variant={meta.variant}>{meta.label}</Badge>
                                  <div className="flex items-center gap-1">
                                    <span className="text-xs text-muted-foreground">
                                      {formatRelativeTime(item.created_at)}
                                    </span>
                                    <Button
                                      variant="ghost"
                                      size="icon-sm"
                                      aria-label="Forget this memory"
                                      onClick={() => {
                                        captureFocus()
                                        setPendingForget(item)
                                      }}
                                    >
                                      <X className="size-3.5" />
                                    </Button>
                                  </div>
                                </div>
                                <p className="text-sm leading-relaxed">{item.text}</p>
                              </CardContent>
                            </Card>
                          </motion.div>
                        )
                      })}
                    </AnimatePresence>
                  </div>

                  <Button
                    variant="outline"
                    className="mt-1 gap-1.5 self-start text-destructive hover:text-destructive"
                    onClick={() => {
                      captureFocus()
                      setConfirmForgetAll(true)
                    }}
                  >
                    <Trash2 className="size-4" />
                    Forget everything
                  </Button>
                </>
              )}
            </section>

            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Sparkles className="mt-0.5 size-3 shrink-0 text-primary" />
              <span>
                Sarathi only uses these to give you more relevant, personal help. Forgetting a
                memory removes it from what the assistant can see.
              </span>
            </p>
          </>
        ) : null}
      </div>

      <Dialog
        open={pendingForget !== null}
        onOpenChange={(open) => {
          if (!open) setPendingForget(null)
        }}
      >
        <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
          <DialogHeader>
            <DialogTitle>Forget this memory?</DialogTitle>
            <DialogDescription>
              {pendingForget && `Sarathi will no longer remember: "${pendingForget.text}"`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingForget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={forgettingOne}
              onClick={() => void handleForgetOne()}
            >
              {forgettingOne ? "Forgetting…" : "Forget"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmForgetAll}
        onOpenChange={(open) => {
          if (!open) setConfirmForgetAll(false)
        }}
      >
        <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
          <DialogHeader>
            <DialogTitle>Forget everything?</DialogTitle>
            <DialogDescription>
              This permanently clears every memory Sarathi has saved from your conversations. Your
              account details stay unchanged. This can&apos;t be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmForgetAll(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={forgettingAll}
              onClick={() => void handleForgetAll()}
            >
              {forgettingAll ? "Clearing…" : "Forget everything"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-14 text-center">
      <Brain className="size-8 text-muted-foreground" />
      <p className="text-sm font-medium">{title}</p>
      <p className="max-w-sm text-sm text-muted-foreground">{body}</p>
    </div>
  )
}
