"use client"

import * as React from "react"
import { AnimatePresence } from "framer-motion"
import { CheckCheck } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import type { Proposal, ProposalActionResult } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { ListRowSkeleton } from "@/components/console/list-row-skeleton"
import { ProposalCard } from "@/components/console/proposal-card"
import { Card, CardContent } from "@/components/ui/card"

/** Turns the approve response's `action_kind`/`status`/`detail` into a plain
 * sentence for the success toast - "email sent to ..." vs "nudge created" -
 * so the reviewer knows what actually executed, not just that it did. */
function describeApprovalResult(result: ProposalActionResult): string {
  if (result.status === "skipped_no_creds") {
    const reason = typeof result.detail.reason === "string" ? result.detail.reason : undefined
    return reason ? `Email not sent - ${reason}` : "Email not sent - credentials not configured"
  }
  if (result.action_kind === "send_email" || result.action_kind === "email") {
    const to = typeof result.detail.to === "string" ? result.detail.to : undefined
    return to ? `Email sent to ${to}` : "Email sent"
  }
  if (result.action_kind === "send_nudge" || result.action_kind === "nudge") {
    return "Nudge created for the customer"
  }
  if (result.action_kind === "product_offer" || result.action_kind === "offer") {
    return "Product-offer nudge created for the customer"
  }
  return `${result.action_kind.replace(/_/g, " ")}: ${result.status}`
}

export default function ApprovalsPage() {
  const [proposals, setProposals] = React.useState<Proposal[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [busyIds, setBusyIds] = React.useState<Set<string>>(new Set())
  // Synchronous guard against a double-fire that races ahead of the `busy`
  // state's re-render (the `disabled` prop below already covers the common
  // case once React has re-rendered, but a ref check is immediate).
  const busyRef = React.useRef<Set<string>>(new Set())

  React.useEffect(() => {
    let cancelled = false
    api
      .get<Proposal[]>(`${API_V1}/console/proposals?status=pending`)
      .then((res) => {
        if (!cancelled) setProposals(res)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Couldn't load proposals.")
        setProposals([])
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

  async function handleApprove(id: string) {
    if (busyRef.current.has(id)) return
    busyRef.current.add(id)
    setBusy(id, true)
    try {
      const result = await api.post<ProposalActionResult>(`${API_V1}/console/proposals/${id}/approve`)
      setProposals((prev) => prev?.filter((p) => p.id !== id) ?? null)
      toast.success("Proposal approved", { description: describeApprovalResult(result) })
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't approve that proposal"))
    } finally {
      busyRef.current.delete(id)
      setBusy(id, false)
    }
  }

  async function handleReject(id: string, reason?: string) {
    if (busyRef.current.has(id)) return
    busyRef.current.add(id)
    setBusy(id, true)
    try {
      await api.post(`${API_V1}/console/proposals/${id}/reject`, reason ? { reason } : undefined)
      setProposals((prev) => prev?.filter((p) => p.id !== id) ?? null)
      toast.success("Proposal rejected")
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't reject that proposal"))
    } finally {
      busyRef.current.delete(id)
      setBusy(id, false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <ConsolePageHeader
        title="Approvals"
        description="Proposals from agents awaiting human-in-the-loop sign-off."
      />

      {error && (
        <Card className="mb-4">
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {proposals === null ? (
        <ListRowSkeleton count={3} />
      ) : proposals.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <CheckCheck className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Nothing pending - all proposals are handled.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {proposals.map((proposal) => (
              <ProposalCard
                key={proposal.id}
                proposal={proposal}
                busy={busyIds.has(proposal.id)}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
