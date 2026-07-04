import { Check, X } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatSecondsHuman, formatRelativeTime, humanizeIdentifier } from "@/lib/format"
import type { DetectionResponse, DetectionRow } from "@/lib/console-types"
import { CustomerLink } from "@/components/console/customer-link"
import { StatTile } from "@/components/console/stat-tile"

/** A check (matched) / cross (missed) chip in the single clay hue - clay fill for
 * a hit, muted stone for a miss. No second accent colour (Aperture rule). */
function MatchChip({ matched }: { matched: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        matched
          ? "bg-primary/12 text-primary"
          : "bg-muted text-muted-foreground"
      )}
    >
      {matched ? <Check className="size-3" /> : <X className="size-3" />}
      {matched ? "Match" : "Miss"}
    </span>
  )
}

function DetectionCell({ row }: { row: DetectionRow }) {
  if (row.detected && row.detected_type) {
    return (
      <span className="font-medium text-foreground">
        {humanizeIdentifier(row.detected_type)}
      </span>
    )
  }
  if (row.expected_types.length === 0) {
    return <span className="text-muted-foreground">None (as expected)</span>
  }
  return <span className="text-muted-foreground">Not detected</span>
}

/** Detection scorecard: injected ground-truth events graded against what the agent
 * mesh actually detected. Summary tiles + an honest injections-vs-detections table
 * with match chips and human-unit lag. */
export function DetectionScorecard({ data }: { data: DetectionResponse }) {
  const { summary, rows } = data
  const matchRate =
    summary.injected > 0 ? Math.round((summary.matched / summary.injected) * 100) : null

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Injected" value={summary.injected.toLocaleString("en-IN")} />
        <StatTile
          label="Detected"
          value={`${summary.detected.toLocaleString("en-IN")}/${summary.injected.toLocaleString("en-IN")}`}
        />
        <StatTile
          label="Matched"
          value={matchRate !== null ? `${matchRate}%` : "-"}
        />
        <StatTile
          label="Unprompted"
          value={summary.detections_with_no_injection.toLocaleString("en-IN")}
        />
      </div>

      {rows.length === 0 ? (
        <div className="flex min-h-24 items-center justify-center rounded-lg border border-dashed border-border p-6 text-center">
          <p className="text-sm text-muted-foreground">
            Inject a life event to measure detection.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="py-2 pr-4 font-medium">Injected</th>
                <th className="py-2 pr-4 font-medium">Customer</th>
                <th className="py-2 pr-4 font-medium">Detected</th>
                <th className="py-2 pr-4 font-medium">Match</th>
                <th className="py-2 pr-4 text-right font-medium">Lag</th>
                <th className="py-2 text-right font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.injection_id} className="border-b border-border/60 last:border-0">
                  <td className="py-2.5 pr-4">
                    <span className="font-medium text-foreground">
                      {humanizeIdentifier(row.injected_type)}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {formatRelativeTime(row.injected_at)}
                    </span>
                  </td>
                  <td className="max-w-[10rem] truncate py-2.5 pr-4 text-muted-foreground">
                    <CustomerLink id={row.customer_id}>{row.customer_name}</CustomerLink>
                  </td>
                  <td className="py-2.5 pr-4">
                    <DetectionCell row={row} />
                  </td>
                  <td className="py-2.5 pr-4">
                    <MatchChip matched={row.matched} />
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                    {formatSecondsHuman(row.lag_seconds)}
                  </td>
                  <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground">
                    {row.confidence !== null ? `${Math.round(row.confidence * 100)}%` : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
