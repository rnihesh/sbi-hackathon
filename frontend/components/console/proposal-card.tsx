"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { springSoft } from "@/lib/motion"
import { formatRelativeTime, humanizeIdentifier } from "@/lib/format"
import type { Proposal } from "@/lib/console-types"
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

export function ProposalCard({
  proposal,
  busy,
  onApprove,
  onReject,
}: {
  proposal: Proposal
  busy: boolean
  onApprove: (id: string) => void
  onReject: (id: string, reason?: string) => void
}) {
  const [expanded, setExpanded] = React.useState(false)
  const [rejectOpen, setRejectOpen] = React.useState(false)
  const [reason, setReason] = React.useState("")
  // The reject dialog opens from a plain button, not a `DialogTrigger`, so
  // Radix has no trigger ref of its own to restore focus to on close (it'd
  // otherwise fall back to `<body>` - verified live on the sign-in sheet,
  // same underlying gap). Track it directly instead.
  const rejectTriggerRef = React.useRef<HTMLButtonElement>(null)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.16 } }}
      transition={springSoft}
    >
      <Card>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">{humanizeIdentifier(proposal.agent)}</Badge>
              <Badge variant="outline" className="capitalize">
                {proposal.kind.replace(/_/g, " ")}
              </Badge>
            </div>
            <span className="text-xs text-muted-foreground">
              {formatRelativeTime(proposal.created_at)}
            </span>
          </div>

          <div>
            <p className="text-sm font-medium">{proposal.title}</p>
            <p className="text-sm text-muted-foreground">
              For {proposal.customer.full_name} &middot; {proposal.body}
            </p>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-1 rounded-sm text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ChevronDown className={cn("size-3.5 transition-transform", expanded && "rotate-180")} />
              {expanded ? "Hide action payload" : "Show action payload"}
            </button>
            {expanded && (
              <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-muted p-3 font-mono text-xs">
                {JSON.stringify(proposal.action, null, 2)}
              </pre>
            )}
          </div>

          <div className="flex gap-2 pt-1">
            <Button
              ref={rejectTriggerRef}
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => setRejectOpen(true)}
            >
              Reject
            </Button>
            <Button size="sm" disabled={busy} onClick={() => onApprove(proposal.id)}>
              Approve
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent
          onCloseAutoFocus={(e) => {
            e.preventDefault()
            rejectTriggerRef.current?.focus()
          }}
        >
          <DialogHeader>
            <DialogTitle>Reject proposal</DialogTitle>
            <DialogDescription>
              Optionally note why - this helps the agent mesh calibrate future proposals.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`reject-reason-${proposal.id}`}>Reason (optional)</Label>
            <Input
              id={`reject-reason-${proposal.id}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Not relevant right now"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => {
                setRejectOpen(false)
                onReject(proposal.id, reason.trim() || undefined)
              }}
            >
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  )
}
