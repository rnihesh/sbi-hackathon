"use client"

import * as React from "react"
import { Download } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError } from "@/lib/api"
import { downloadFile } from "@/lib/download"
import { formatSecondsHuman } from "@/lib/format"
import type {
  DetectionResponse,
  ProposalOutcomesResponse,
  TimeseriesResponse,
} from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { StatTile } from "@/components/console/stat-tile"
import { DetectionScorecard } from "@/components/console/detection-scorecard"
import { MetricSparklines } from "@/components/console/metric-sparklines"
import { ProposalOutcomeBars } from "@/components/console/proposal-outcome-bars"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const TIMESERIES_DAYS = 14

/** Loads one analytics endpoint into `[data, error]` state on mount. */
function useAnalytics<T>(path: string, fallback: string): [T | null, string | null] {
  const [data, setData] = React.useState<T | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .get<T>(path)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : fallback)
      })
    return () => {
      cancelled = true
    }
  }, [path, fallback])

  return [data, error]
}

function SectionCard({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
        {actions && <CardAction>{actions}</CardAction>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

function ErrorOrSkeleton({ error, lines = 3 }: { error: string | null; lines?: number }) {
  if (error) return <p className="text-sm text-muted-foreground">{error}</p>
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="h-6 w-full rounded-md" />
      ))}
    </div>
  )
}

export default function AnalyticsPage() {
  const [detection, detectionError] = useAnalytics<DetectionResponse>(
    `${API_V1}/console/analytics/detection`,
    "Couldn't load detection accuracy."
  )
  const [series, seriesError] = useAnalytics<TimeseriesResponse>(
    `${API_V1}/console/analytics/timeseries?days=${TIMESERIES_DAYS}`,
    "Couldn't load trends."
  )
  const [proposals, proposalsError] = useAnalytics<ProposalOutcomesResponse>(
    `${API_V1}/console/analytics/proposals`,
    "Couldn't load proposal outcomes."
  )
  const [downloadingDetection, setDownloadingDetection] = React.useState(false)

  async function handleDownloadDetection() {
    setDownloadingDetection(true)
    try {
      await downloadFile(`${API_V1}/console/export/detection.csv`, "detection.csv")
    } catch {
      toast.error("Couldn't download the detection scorecard")
    } finally {
      setDownloadingDetection(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <ConsolePageHeader
        title="Analytics"
        description="Proof the agents work: detection accuracy, funnel trends, and proposal outcomes."
      />

      <SectionCard
        title="Detection accuracy"
        description="Injected life events vs. what the agent mesh detected, with match and lag."
        actions={
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5"
            disabled={downloadingDetection}
            onClick={() => void handleDownloadDetection()}
          >
            <Download className="size-3.5" />
            Download CSV
          </Button>
        }
      >
        {detection ? (
          <DetectionScorecard data={detection} />
        ) : (
          <ErrorOrSkeleton error={detectionError} lines={4} />
        )}
      </SectionCard>

      <SectionCard
        title={`Funnel trends (last ${TIMESERIES_DAYS} days)`}
        description="Daily agent runs, proposals, nudges, and LLM spend."
      >
        {series ? (
          <MetricSparklines points={series.points} />
        ) : (
          <ErrorOrSkeleton error={seriesError} lines={6} />
        )}
      </SectionCard>

      <SectionCard
        title="Proposal outcomes"
        description="Human-in-the-loop approvals, rejections, and decision speed."
      >
        {proposals ? (
          <div className="flex flex-col gap-5">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                label="Approved"
                value={(proposals.approved + proposals.executed).toLocaleString("en-IN")}
              />
              <StatTile label="Rejected" value={proposals.rejected.toLocaleString("en-IN")} />
              <StatTile label="Pending" value={proposals.pending.toLocaleString("en-IN")} />
              <StatTile
                label="Avg. decision"
                value={formatSecondsHuman(proposals.avg_decision_seconds)}
              />
            </div>
            <ProposalOutcomeBars rows={proposals.by_agent} />
          </div>
        ) : (
          <ErrorOrSkeleton error={proposalsError} lines={3} />
        )}
      </SectionCard>
    </div>
  )
}
