"use client"

import * as React from "react"
import { AnimatePresence } from "framer-motion"
import { CheckCheck } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError } from "@/lib/api"
import type { Proposal } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { ListRowSkeleton } from "@/components/console/list-row-skeleton"
import { ProposalCard } from "@/components/console/proposal-card"
import { Card, CardContent } from "@/components/ui/card"

export default function ApprovalsPage() {
  const [proposals, setProposals] = React.useState<Proposal[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [busyIds, setBusyIds] = React.useState<Set<string>>(new Set())

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
    setBusy(id, true)
    try {
      await api.post(`${API_V1}/console/proposals/${id}/approve`)
      setProposals((prev) => prev?.filter((p) => p.id !== id) ?? null)
      toast.success("Proposal approved")
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't approve that proposal")
      setBusy(id, false)
    }
  }

  async function handleReject(id: string, reason?: string) {
    setBusy(id, true)
    try {
      await api.post(`${API_V1}/console/proposals/${id}/reject`, reason ? { reason } : undefined)
      setProposals((prev) => prev?.filter((p) => p.id !== id) ?? null)
      toast.success("Proposal rejected")
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't reject that proposal")
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
          <CardContent className="py-4 text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {proposals === null ? (
        <ListRowSkeleton count={3} />
      ) : proposals.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <CheckCheck className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Nothing pending — all proposals are handled.</p>
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
