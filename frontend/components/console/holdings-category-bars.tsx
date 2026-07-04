import { humanizeIdentifier } from "@/lib/format"
import type { HoldingCategoryFunnel } from "@/lib/console-types"

/** Per-category holding breakdown - active vs. offered-but-not-yet-active,
 * bar width relative to the busiest category. Parallel categories (not a
 * sequential funnel), so this is deliberately not `FunnelBars`. */
export function HoldingsCategoryBars({ categories }: { categories: HoldingCategoryFunnel[] }) {
  const max = Math.max(1, ...categories.map((c) => c.active + c.offered))

  if (categories.length === 0) {
    return <p className="text-sm text-muted-foreground">No holdings yet.</p>
  }

  return (
    <div className="flex flex-col gap-3">
      {categories.map((c) => {
        const total = c.active + c.offered
        const activePct = Math.max(total > 0 ? (c.active / max) * 100 : 0, c.active > 0 ? 3 : 0)
        const offeredPct = Math.max(c.offered > 0 ? (c.offered / max) * 100 : 0, c.offered > 0 ? 3 : 0)

        return (
          <div key={c.category} className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-foreground">{humanizeIdentifier(c.category)}</span>
              <span className="flex items-center gap-3 text-muted-foreground">
                {c.offered > 0 && <span>{c.offered.toLocaleString("en-IN")} offered</span>}
                <span className="font-mono tabular-nums">
                  {c.active.toLocaleString("en-IN")} active
                </span>
              </span>
            </div>
            <div className="flex h-6 w-full gap-0.5 overflow-hidden rounded-md bg-muted">
              <div
                className="h-full rounded-md bg-primary/80 transition-all"
                style={{ width: `${activePct}%` }}
              />
              {c.offered > 0 && (
                <div
                  className="h-full rounded-md bg-primary/30 transition-all"
                  style={{ width: `${offeredPct}%` }}
                />
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
