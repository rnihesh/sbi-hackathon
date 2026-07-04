interface FunnelStage {
  label: string
  count: number
}

/** Horizontal funnel bars — pure CSS, no chart library. Bar width is relative
 * to the first stage's count; the caption between stages shows the raw
 * conversion percentage from the previous stage. */
export function FunnelBars({ stages }: { stages: FunnelStage[] }) {
  const max = Math.max(1, ...stages.map((s) => s.count))

  return (
    <div className="flex flex-col gap-3">
      {stages.map((stage, i) => {
        const widthPct = Math.round((stage.count / max) * 100)
        const prev = i > 0 ? stages[i - 1] : null
        const conversionPct = prev && prev.count > 0 ? Math.round((stage.count / prev.count) * 100) : null

        return (
          <div key={stage.label} className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-foreground">{stage.label}</span>
              <span className="flex items-center gap-2 text-muted-foreground">
                {conversionPct !== null && <span>{conversionPct}% of {prev!.label.toLowerCase()}</span>}
                <span className="font-mono tabular-nums">{stage.count.toLocaleString("en-IN")}</span>
              </span>
            </div>
            <div className="h-6 w-full overflow-hidden rounded-md bg-muted">
              <div
                className="h-full rounded-md bg-primary/80 transition-all"
                style={{ width: `${stage.count > 0 ? Math.max(widthPct, 3) : 0}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
