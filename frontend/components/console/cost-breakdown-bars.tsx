import { formatCount, formatUsd, pluralize } from "@/lib/format"
import type { CostBreakdownRow } from "@/lib/console-types"

/** Horizontal cost breakdown bars (by provider/model/tier/purpose) - same thin
 * single-hue bar language as `FunnelBars`, sized by cost share. */
export function CostBreakdownBars({ rows }: { rows: CostBreakdownRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No LLM calls recorded yet.</p>
  }

  const max = Math.max(1e-9, ...rows.map((r) => Number(r.cost_usd)))

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => {
        const cost = Number(row.cost_usd)
        const pct = Math.max((cost / max) * 100, cost > 0 ? 2 : 0)

        return (
          <div key={row.key} className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate font-medium text-foreground">{row.key}</span>
              <span className="flex shrink-0 items-center gap-3 font-mono tabular-nums text-muted-foreground">
                <span>
                  {formatCount(row.calls)} {pluralize(row.calls, "call")}
                </span>
                <span className="w-20 text-right text-foreground">{formatUsd(row.cost_usd)}</span>
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary/80 transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
