"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { X } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import { formatRelativeTime } from "@/lib/format"
import { springSoft } from "@/lib/motion"
import type { StaffNote } from "@/lib/console-types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useFocusReturn } from "@/lib/use-focus-return"

const NOTE_MAX_LENGTH = 1000

/**
 * Staff-only notes on a customer's 360 profile - deliberately its own card,
 * not folded into the activity timeline (a note is a staff observation, not
 * something that happened). Any staff member may delete any note (small
 * team tool), confirmed via a shared dialog rather than a bare `confirm()`.
 */
export function StaffNotesCard({ customerId }: { customerId: string }) {
  const [notes, setNotes] = React.useState<StaffNote[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [draft, setDraft] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [pendingDelete, setPendingDelete] = React.useState<StaffNote | null>(null)
  const [deleting, setDeleting] = React.useState(false)
  const { captureFocus, onCloseAutoFocus } = useFocusReturn()

  React.useEffect(() => {
    let cancelled = false
    setNotes(null)
    setError(null)
    api
      .get<StaffNote[]>(`${API_V1}/console/customers/${customerId}/notes`)
      .then((res) => {
        if (!cancelled) setNotes(res)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load notes.")
        setNotes([])
      })
    return () => {
      cancelled = true
    }
  }, [customerId])

  async function handleAdd() {
    const text = draft.trim()
    if (!text || submitting) return
    setSubmitting(true)
    try {
      const note = await api.post<StaffNote>(
        `${API_V1}/console/customers/${customerId}/notes`,
        { text }
      )
      setNotes((prev) => [note, ...(prev ?? [])])
      setDraft("")
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't add that note"))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete() {
    if (!pendingDelete) return
    const target = pendingDelete
    setDeleting(true)
    try {
      await api.delete(`${API_V1}/console/notes/${target.id}`)
      setNotes((prev) => (prev ? prev.filter((n) => n.id !== target.id) : prev))
      setPendingDelete(null)
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't delete that note"))
    } finally {
      setDeleting(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void handleAdd()
    }
  }

  return (
    <>
      <Card className="flex h-full flex-col">
        <CardHeader>
          <CardTitle>Notes</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-1 flex-col gap-3">
          <div className="flex flex-col gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value.slice(0, NOTE_MAX_LENGTH))}
              onKeyDown={handleKeyDown}
              placeholder="Add a note for other staff..."
              rows={3}
              maxLength={NOTE_MAX_LENGTH}
              disabled={submitting}
              className="w-full resize-none rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30"
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                {draft.length}/{NOTE_MAX_LENGTH} &middot; Enter (Cmd/Ctrl) to add
              </span>
              <Button
                size="sm"
                disabled={!draft.trim() || submitting}
                onClick={() => void handleAdd()}
              >
                {submitting ? "Adding..." : "Add"}
              </Button>
            </div>
          </div>

          {error && <p className="text-sm text-muted-foreground">{error}</p>}

          {notes === null ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full rounded-lg" />
              ))}
            </div>
          ) : notes.length === 0 ? (
            <p className="text-sm text-muted-foreground">No notes yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              <AnimatePresence initial={false}>
                {notes.map((note) => (
                  <motion.li
                    key={note.id}
                    layout
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0, transition: { duration: 0.18 } }}
                    transition={springSoft}
                    className="overflow-hidden rounded-lg border border-border/70 bg-card"
                  >
                    <div className="flex flex-col gap-1 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-medium text-foreground/80">
                          {note.author_email}
                        </span>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">
                            {formatRelativeTime(note.created_at)}
                          </span>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Delete note"
                            onClick={() => {
                              captureFocus()
                              setPendingDelete(note)
                            }}
                          >
                            <X className="size-3.5" />
                          </Button>
                        </div>
                      </div>
                      <p className="text-sm leading-relaxed whitespace-pre-wrap">{note.text}</p>
                    </div>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null)
        }}
      >
        <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
          <DialogHeader>
            <DialogTitle>Delete this note?</DialogTitle>
            <DialogDescription>
              {pendingDelete && `"${pendingDelete.text}" will be removed for everyone.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={deleting} onClick={() => void handleDelete()}>
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
