"use client"

import * as React from "react"
import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { motion } from "framer-motion"
import { ArrowLeft, Bell, FileCheck, Mail, MapPin, Phone, Sparkles } from "lucide-react"

import { api, API_V1, ApiError } from "@/lib/api"
import {
  formatCount,
  formatPaise,
  formatRelativeTime,
  formatUsd,
  humanizeIdentifier,
} from "@/lib/format"
import { staggerContainer, staggerItem } from "@/lib/motion"
import type {
  CustomerDetailResponse,
  TimelineAgentRunData,
  TimelineItem,
  TimelineLifeEventData,
  TimelineNotificationData,
  TimelineNudgeData,
  TimelineProposalData,
} from "@/lib/console-types"
import { SarathiMark } from "@/components/brand/logo"
import { IntentScoreBar } from "@/components/console/intent-score-bar"
import { StatTile } from "@/components/console/stat-tile"
import { TraceStatusBadge } from "@/components/console/trace-status-badge"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const TIMELINE_LIMIT = 50

function proposalStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "executed") return "default"
  if (status === "rejected") return "destructive"
  if (status === "approved") return "secondary"
  return "outline" // pending
}

function nudgeStatusVariant(status: string): "default" | "secondary" | "outline" {
  if (status === "acted") return "default"
  if (status === "seen") return "secondary"
  return "outline" // sent, dismissed
}

function TimelineTypeIcon({ type }: { type: TimelineItem["type"] }) {
  switch (type) {
    case "agent_run":
      return <SarathiMark className="size-3" />
    case "life_event":
      return <Sparkles className="size-3" />
    case "proposal":
      return <FileCheck className="size-3" />
    case "nudge":
      return <Bell className="size-3" />
    case "notification":
      return <Mail className="size-3" />
    default:
      return null
  }
}

function AgentRunBody({ data }: { data: TimelineAgentRunData }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Link
        href={`/console/traces/${data.run_id}`}
        className="text-sm font-medium underline-offset-2 decoration-primary/40 hover:underline"
      >
        {humanizeIdentifier(data.agent)} agent run
      </Link>
      <TraceStatusBadge status={data.status} />
      <span className="text-xs text-muted-foreground">{formatUsd(data.cost_usd)}</span>
    </div>
  )
}

function LifeEventBody({ data }: { data: TimelineLifeEventData }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium">{humanizeIdentifier(data.type)}</span>
      <span className="text-xs text-muted-foreground">
        {Math.round(Math.min(1, Math.max(0, data.confidence)) * 100)}% confidence
      </span>
    </div>
  )
}

function ProposalBody({ data }: { data: TimelineProposalData }) {
  const body = (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium">{data.title}</span>
      <Badge variant={proposalStatusVariant(data.status)} className="capitalize">
        {data.status}
      </Badge>
    </div>
  )
  // Only a pending proposal has anywhere useful to send a reviewer - decided
  // ones have already left the approvals queue.
  if (data.status !== "pending") return body
  return (
    <Link href="/console/approvals" className="block w-fit underline-offset-2 decoration-primary/40 hover:underline">
      {body}
    </Link>
  )
}

function NudgeBody({ data }: { data: TimelineNudgeData }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium">{data.title}</span>
      <Badge variant={nudgeStatusVariant(data.status)} className="capitalize">
        {data.status}
      </Badge>
    </div>
  )
}

function NotificationBody({ data }: { data: TimelineNotificationData }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium">{data.title}</span>
      <Badge variant="outline" className="capitalize">
        {humanizeIdentifier(data.kind)}
      </Badge>
    </div>
  )
}

/** The row's inner content only (no `<li>`) - the caller renders this inside
 * a `motion.li` directly, so the animated element stays a real list item
 * rather than a `<div>` wrapping one (invalid `<ol>` nesting). */
function TimelineRowContent({ item }: { item: TimelineItem }) {
  return (
    <>
      <span className="absolute -left-[1.6rem] top-0.5 flex size-5 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <TimelineTypeIcon type={item.type} />
      </span>
      <p className="mb-0.5 text-xs text-muted-foreground">{formatRelativeTime(item.ts)}</p>
      {item.type === "agent_run" && <AgentRunBody data={item.data} />}
      {item.type === "life_event" && <LifeEventBody data={item.data} />}
      {item.type === "proposal" && <ProposalBody data={item.data} />}
      {item.type === "nudge" && <NudgeBody data={item.data} />}
      {item.type === "notification" && <NotificationBody data={item.data} />}
    </>
  )
}

function TimelineSkeleton() {
  return (
    <ol className="relative flex flex-col gap-6 border-l border-border pl-6">
      {Array.from({ length: 5 }).map((_, i) => (
        <li key={i} className="relative">
          <span className="absolute -left-[1.6rem] top-0.5 size-5 rounded-full bg-muted" />
          <Skeleton className="mb-2 h-3.5 w-24" />
          <Skeleton className="h-4 w-2/3" />
        </li>
      ))}
    </ol>
  )
}

function CustomerDetailSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-4 w-64" />
        <div className="flex flex-wrap gap-2">
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-5 w-24 rounded-full" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
      <TimelineSkeleton />
    </div>
  )
}

export default function CustomerDetailPage() {
  const params = useParams<{ customerId: string }>()
  const router = useRouter()
  const [detail, setDetail] = React.useState<CustomerDetailResponse | null>(null)
  const [timeline, setTimeline] = React.useState<TimelineItem[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [notFound, setNotFound] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    setDetail(null)
    setTimeline(null)
    setError(null)
    setNotFound(false)

    api
      .get<CustomerDetailResponse>(`${API_V1}/console/customers/${params.customerId}`)
      .then((res) => {
        if (!cancelled) setDetail(res)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else setError(err instanceof ApiError ? err.message : "Couldn't load this customer.")
      })

    api
      .get<TimelineItem[]>(
        `${API_V1}/console/customers/${params.customerId}/timeline?limit=${TIMELINE_LIMIT}`
      )
      .then((res) => {
        if (!cancelled) setTimeline(res)
      })
      .catch(() => {
        if (!cancelled) setTimeline([]) // non-fatal - the profile above still renders
      })

    return () => {
      cancelled = true
    }
  }, [params.customerId])

  return (
    <div className="mx-auto max-w-3xl">
      <button
        type="button"
        onClick={() => router.back()}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Back
      </button>

      {notFound ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">
            No customer found for id <span className="font-mono">{params.customerId}</span>.
          </p>
        </div>
      ) : error ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      ) : detail === null ? (
        <CustomerDetailSkeleton />
      ) : (
        <>
          <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold tracking-tight">
                {detail.customer.full_name}
              </h1>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                {detail.customer.email && (
                  <span className="inline-flex items-center gap-1.5">
                    <Mail className="size-3.5" />
                    {detail.customer.email}
                  </span>
                )}
                {detail.customer.phone && (
                  <span className="inline-flex items-center gap-1.5">
                    <Phone className="size-3.5" />
                    {detail.customer.phone}
                  </span>
                )}
                {detail.customer.city && (
                  <span className="inline-flex items-center gap-1.5">
                    <MapPin className="size-3.5" />
                    {detail.customer.city}
                  </span>
                )}
              </div>
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                {detail.customer.segment && (
                  <Badge variant="secondary" className="capitalize">
                    {detail.customer.segment}
                  </Badge>
                )}
                <Badge variant="outline" className="capitalize">
                  {humanizeIdentifier(detail.customer.digital_maturity)} digital maturity
                </Badge>
                {detail.customer.preferred_language && (
                  <Badge variant="outline" className="uppercase">
                    {detail.customer.preferred_language}
                  </Badge>
                )}
              </div>
            </div>

            <div className="w-full shrink-0 sm:w-40">
              <p className="mb-1 text-xs text-muted-foreground">Churn risk</p>
              <IntentScoreBar score={detail.customer.churn_risk} />
            </div>
          </div>

          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
            <StatTile label="Transactions (90d)" value={formatCount(detail.stats.transactions_90d)} />
            <StatTile label="Agent runs" value={formatCount(detail.stats.agent_runs_total)} />
            <StatTile label="Pending proposals" value={formatCount(detail.stats.proposals_pending)} />
            <StatTile label="Nudges sent" value={formatCount(detail.stats.nudges_sent)} />
            <StatTile label="Life events" value={formatCount(detail.stats.life_events)} />
          </div>

          <div className="mb-6 grid gap-4 sm:grid-cols-2">
            <Card size="sm">
              <CardHeader>
                <CardTitle>Accounts</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2.5">
                {detail.accounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No accounts on file.</p>
                ) : (
                  detail.accounts.map((account, i) => (
                    <div key={i} className="flex items-center justify-between gap-2 text-sm">
                      <span className="capitalize">{humanizeIdentifier(account.type)}</span>
                      <span className="font-mono tabular-nums">
                        {formatPaise(account.balance_paise)}
                      </span>
                      <Badge variant="outline" className="shrink-0 capitalize">
                        {account.status}
                      </Badge>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>

            <Card size="sm">
              <CardHeader>
                <CardTitle>Holdings</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2.5">
                {detail.holdings.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No holdings yet.</p>
                ) : (
                  detail.holdings.map((holding, i) => (
                    <div key={i} className="flex items-center justify-between gap-2 text-sm">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{holding.product.name}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {humanizeIdentifier(holding.product.category)}
                        </p>
                      </div>
                      <Badge variant="outline" className="shrink-0 capitalize">
                        {holding.status}
                      </Badge>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>

          <h2 className="mb-3 text-sm font-semibold">Activity timeline</h2>
          {timeline === null ? (
            <TimelineSkeleton />
          ) : timeline.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
              <p className="text-sm text-muted-foreground">No activity recorded yet.</p>
            </div>
          ) : (
            <motion.ol
              variants={staggerContainer}
              initial="initial"
              animate="animate"
              className="relative flex flex-col gap-6 border-l border-border pl-6"
            >
              {timeline.map((item, i) => (
                <motion.li key={i} variants={staggerItem} className="relative">
                  <TimelineRowContent item={item} />
                </motion.li>
              ))}
            </motion.ol>
          )}
        </>
      )}
    </div>
  )
}
