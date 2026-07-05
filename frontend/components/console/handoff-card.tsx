"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { Headset, UserRound } from "lucide-react"

import { cn } from "@/lib/utils"
import { springSoft } from "@/lib/motion"
import { formatRelativeTime } from "@/lib/format"
import type { Handoff, HandoffUrgency } from "@/lib/console-types"
import { CustomerLink } from "@/components/console/customer-link"
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
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"

const URGENCY_LABEL: Record<HandoffUrgency, string> = {
  high: "High urgency",
  normal: "Normal",
  low: "Low urgency",
}

function UrgencyBadge({ urgency }: { urgency: HandoffUrgency }) {
  if (urgency === "high") {
    // The one spot of clay accent: a high-urgency handoff is waiting on a person.
    return (
      <Badge className="border border-primary bg-primary/10 text-primary">
        {URGENCY_LABEL.high}
      </Badge>
    )
  }
  return (
    <Badge variant={urgency === "normal" ? "secondary" : "outline"} className="capitalize">
      {URGENCY_LABEL[urgency]}
    </Badge>
  )
}

/** Who the handoff is for: a linked customer, or an anonymous prospect keyed by
 * their conversation id so staff can still find the exact thread. */
function HandoffSubject({ handoff }: { handoff: Handoff }) {
  if (handoff.customer) {
    return (
      <span>
        For <CustomerLink id={handoff.customer.id}>{handoff.customer.full_name}</CustomerLink>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1">
      <UserRound className="size-3.5" />
      Anonymous prospect
      <span className="text-muted-foreground/70">&middot; {handoff.conversation_id.slice(0, 12)}</span>
    </span>
  )
}

export function HandoffCard({
  handoff,
  busy,
  onClaim,
  onResolve,
}: {
  handoff: Handoff
  busy: boolean
  onClaim: (id: string) => void
  onResolve: (id: string, note: string) => void
}) {
  const [resolveOpen, setResolveOpen] = React.useState(false)
  const [note, setNote] = React.useState("")
  const resolveTriggerRef = React.useRef<HTMLButtonElement>(null)
  const noteValid = note.trim().length > 0 && note.trim().length <= 1000

  const isHigh = handoff.urgency === "high"

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.16 } }}
      transition={springSoft}
    >
      <Card className={cn(isHigh && "border border-primary/60")}>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <UrgencyBadge urgency={handoff.urgency} />
              {handoff.status === "claimed" && (
                <Badge variant="outline" className="gap-1">
                  <Headset className="size-3" />
                  Claimed
                </Badge>
              )}
            </div>
            <span className="text-xs text-muted-foreground">
              {formatRelativeTime(handoff.created_at)}
            </span>
          </div>

          <div>
            <p className="text-sm font-medium">{handoff.reason}</p>
            <p className="text-sm text-muted-foreground">
              <HandoffSubject handoff={handoff} />
              {handoff.claimed_by && (
                <>
                  {" "}&middot; claimed by {handoff.claimed_by}
                </>
              )}
            </p>
          </div>

          <div className="flex gap-2 pt-1">
            {handoff.status === "open" ? (
              <Button size="sm" disabled={busy} onClick={() => onClaim(handoff.id)}>
                Claim
              </Button>
            ) : (
              <Button
                ref={resolveTriggerRef}
                size="sm"
                disabled={busy}
                onClick={() => setResolveOpen(true)}
              >
                Resolve
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Dialog open={resolveOpen} onOpenChange={setResolveOpen}>
        <DialogContent
          onCloseAutoFocus={(e) => {
            e.preventDefault()
            resolveTriggerRef.current?.focus()
          }}
        >
          <DialogHeader>
            <DialogTitle>Resolve handoff</DialogTitle>
            <DialogDescription>
              Note how you handled it - the customer is notified with a short summary.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`resolve-note-${handoff.id}`}>Resolution note</Label>
            <Input
              id={`resolve-note-${handoff.id}`}
              value={note}
              maxLength={1000}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Called the customer and filed the dispute"
              onKeyDown={(e) => {
                if (e.key === "Enter" && noteValid && !busy) {
                  setResolveOpen(false)
                  onResolve(handoff.id, note.trim())
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResolveOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={busy || !noteValid}
              onClick={() => {
                setResolveOpen(false)
                onResolve(handoff.id, note.trim())
              }}
            >
              Resolve
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  )
}

/** Compact read-only card for the collapsed "Resolved" section. */
export function ResolvedHandoffRow({ handoff }: { handoff: Handoff }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-muted/30 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-sm">{handoff.reason}</p>
        <span className="shrink-0 text-xs text-muted-foreground">
          {handoff.resolved_at ? formatRelativeTime(handoff.resolved_at) : ""}
        </span>
      </div>
      {handoff.resolution_note && (
        <p className="text-xs text-muted-foreground">
          <span className="text-foreground/70">Resolution:</span> {handoff.resolution_note}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        <HandoffSubject handoff={handoff} />
        {handoff.claimed_by && <> &middot; by {handoff.claimed_by}</>}
      </p>
    </div>
  )
}
