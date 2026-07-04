import { humanizeIdentifier } from "@/lib/format"
import type { ProposalAgentRow } from "@/lib/console-types"

const SEGMENTS = [
  { key: "approved", label: "Approved", className: "bg-primary" },
  { key: "rejected", label: "Rejected", className: "bg-foreground/45" },
  { key: "pending", label: "Pending", className: "bg-foreground/12" },
] as const

function LegendDot({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`size-2.5 rounded-full ${className}`} />
      {label}
    </span>
  )
}

/** Per-agent proposal outcome mix as a compact horizontal stacked bar (approved
 * clay, rejected dark stone, pending light stone), sized within each agent's own
 * total, with the approval rate alongside. Single clay hue + stone neutrals. */
export function ProposalOutcomeBars({ rows }: { rows: ProposalAgentRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No proposals yet.</p>
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {SEGMENTS.map((s) => (
          <LegendDot key={s.key} className={s.className} label={s.label} />
        ))}
      </div>

      {rows.map((row) => {
        const pending = Math.max(0, row.created - row.approved - row.rejected)
        const decided = row.approved + row.rejected
        const approvalRate = decided > 0 ? Math.round((row.approved / decided) * 100) : null
        const total = Math.max(1, row.created)
        const counts = { approved: row.approved, rejected: row.rejected, pending }

        return (
          <div key={row.agent} className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-foreground">
                {humanizeIdentifier(row.agent)}
              </span>
              <span className="flex items-center gap-3 text-muted-foreground">
                <span className="font-mono tabular-nums">
                  {row.created.toLocaleString("en-IN")} total
                </span>
                {approvalRate !== null && (
                  <span className="font-mono tabular-nums text-foreground">
                    {approvalRate}% approved
                  </span>
                )}
              </span>
            </div>
            <div className="flex h-6 w-full gap-0.5 overflow-hidden rounded-md bg-muted">
              {SEGMENTS.map((s) => {
                const count = counts[s.key]
                if (count <= 0) return null
                const pct = Math.max((count / total) * 100, 3)
                return (
                  <div
                    key={s.key}
                    className={`h-full rounded-sm transition-all ${s.className}`}
                    style={{ width: `${pct}%` }}
                    title={`${s.label}: ${count}`}
                  />
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
