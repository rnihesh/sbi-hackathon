import type { ChurnBucket, ChurnBucketLabel } from "@/lib/console-types"
import { cn } from "@/lib/utils"

/** Clay intensity scales with risk band - opacity steps of the single clay
 * hue (`bg-primary`), not new colors, per the Aperture theme's one-accent rule. */
const BUCKET_INTENSITY: Record<ChurnBucketLabel, string> = {
  "0-20": "bg-primary/20",
  "20-40": "bg-primary/40",
  "40-60": "bg-primary/60",
  "60-80": "bg-primary/80",
  "80-100": "bg-primary",
}

/** Vertical churn-risk distribution bars - pure CSS, no chart library (mirrors
 * `FunnelBars`'s horizontal-bar approach, just rotated). */
export function ChurnDistributionBars({ buckets }: { buckets: ChurnBucket[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.count))

  return (
    <div className="flex items-end gap-3 sm:gap-4">
      {buckets.map((b) => {
        const heightPct = Math.round((b.count / max) * 100)
        return (
          <div key={b.bucket} className="flex flex-1 flex-col items-center gap-2">
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {b.count.toLocaleString("en-IN")}
            </span>
            <div className="flex h-32 w-full items-end overflow-hidden rounded-md bg-muted">
              <div
                className={cn("w-full rounded-md transition-all", BUCKET_INTENSITY[b.bucket])}
                style={{ height: `${b.count > 0 ? Math.max(heightPct, 4) : 0}%` }}
              />
            </div>
            <span className="text-xs text-muted-foreground">{b.bucket}%</span>
          </div>
        )
      })}
    </div>
  )
}
