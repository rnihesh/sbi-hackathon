"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { MessageSquare, MoreVertical, Pencil, Trash2 } from "lucide-react"

import { formatRelativeTime, pluralize } from "@/lib/format"
import { springSnappy } from "@/lib/motion"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

export interface ChatSessionSummary {
  conversation_id: string
  title: string
  message_count: number
  preview?: string | null
  updated_at: string
}

interface ChatHistoryListProps {
  sessions: ChatSessionSummary[] | null
  activeId: string | null
  onOpen: (session: ChatSessionSummary) => void
  onRename: (id: string, title: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

export function ChatHistoryList({
  sessions,
  activeId,
  onOpen,
  onRename,
  onDelete,
}: ChatHistoryListProps) {
  if (sessions === null) {
    return (
      <div className="flex flex-col gap-2 px-2 pt-2">
        <Skeleton className="h-14 w-full rounded-lg" />
        <Skeleton className="h-14 w-full rounded-lg" />
        <Skeleton className="h-14 w-full rounded-lg" />
      </div>
    )
  }

  if (sessions.length === 0) {
    return (
      <p className="px-2 pt-2 text-sm text-muted-foreground">
        No conversations yet. Start one and it will show up here.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <AnimatePresence initial={false}>
        {sessions.map((session) => (
          <motion.div
            key={session.conversation_id}
            layout="position"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, x: -12, height: 0, marginTop: 0 }}
            transition={springSnappy}
          >
            <ConversationRow
              session={session}
              active={session.conversation_id === activeId}
              onOpen={onOpen}
              onRename={onRename}
              onDelete={onDelete}
            />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}

function ConversationRow({
  session,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  session: ChatSessionSummary
  active: boolean
  onOpen: (session: ChatSessionSummary) => void
  onRename: (id: string, title: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}) {
  const [renaming, setRenaming] = React.useState(false)
  const [draft, setDraft] = React.useState(session.title)
  const [confirmOpen, setConfirmOpen] = React.useState(false)
  const [busy, setBusy] = React.useState(false)

  function startRename() {
    setDraft(session.title)
    setRenaming(true)
  }

  async function commitRename() {
    const next = draft.trim().slice(0, 100)
    setRenaming(false)
    if (!next || next === session.title) return
    await onRename(session.conversation_id, next)
  }

  async function confirmDelete() {
    setBusy(true)
    try {
      await onDelete(session.conversation_id)
      setConfirmOpen(false)
    } catch {
      // The page handler already rolled back + surfaced a toast; keep the
      // dialog open so the user can retry.
    } finally {
      setBusy(false)
    }
  }

  if (renaming) {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void commitRename()
        }}
        className="px-1 py-1"
      >
        <Input
          autoFocus
          value={draft}
          maxLength={100}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commitRename()}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault()
              setRenaming(false)
            }
          }}
          aria-label="Rename conversation"
          className="h-9 text-sm"
        />
      </form>
    )
  }

  return (
    <div
      className={cn(
        "group flex items-stretch gap-1 rounded-lg pr-1 transition-colors hover:bg-muted",
        active && "bg-muted"
      )}
    >
      <button
        onClick={() => onOpen(session)}
        className="flex min-w-0 flex-1 items-start gap-2.5 rounded-lg px-2.5 py-2 text-left"
      >
        <MessageSquare className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{session.title}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {session.preview ?? "No messages yet"}
          </span>
          <span className="mt-0.5 block text-[11px] text-muted-foreground/70">
            {formatRelativeTime(session.updated_at)} ·{" "}
            {pluralize(session.message_count, "message")}
          </span>
        </span>
      </button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Conversation actions"
            className="size-7 shrink-0 self-center text-muted-foreground opacity-100 transition-opacity focus-visible:opacity-100 data-[state=open]:opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
          >
            <MoreVertical className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-36">
          <DropdownMenuItem onSelect={() => startRename()}>
            <Pencil className="size-3.5" />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => setConfirmOpen(true)}
          >
            <Trash2 className="size-3.5" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete conversation?</DialogTitle>
            <DialogDescription>
              This permanently removes &ldquo;{session.title}&rdquo; and its messages. This
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => void confirmDelete()} disabled={busy}>
              {busy ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
