"use client"

import * as React from "react"

import { formatCount, formatUsd } from "@/lib/format"
import type { CostSeriesPoint } from "@/lib/console-types"

interface HourBucket {
  hour: Date
  cost: number
  calls: number
}

/** Fills a trailing-24h series (one point per hour, ending at the current hour)
 * from sparse backend buckets - hours with no LLM calls are real zeros, not
 * missing data, so the chart's x-axis stays evenly time-spaced. */
function buildHourlySeries(points: CostSeriesPoint[], now: Date): HourBucket[] {
  const byHour = new Map<number, { cost: number; calls: number }>()
  for (const p of points) {
    const d = new Date(p.hour)
    d.setUTCMinutes(0, 0, 0)
    byHour.set(d.getTime(), { cost: Number(p.cost_usd), calls: p.calls })
  }

  const currentHour = new Date(now)
  currentHour.setUTCMinutes(0, 0, 0)

  const series: HourBucket[] = []
  for (let i = 23; i >= 0; i--) {
    const hour = new Date(currentHour.getTime() - i * 60 * 60 * 1000)
    const bucket = byHour.get(hour.getTime())
    series.push({ hour, cost: bucket?.cost ?? 0, calls: bucket?.calls ?? 0 })
  }
  return series
}

const WIDTH = 640
const HEIGHT = 200
const PAD_TOP = 12
const PAD_BOTTOM = 8
const PAD_X = 4

/** Minimal SVG line/area chart for the trailing-24h cost series - no chart
 * library, clay stroke + wash fill, hairline stone grid, crosshair + tooltip
 * on hover (per the dataviz skill's default interaction rules). */
export function CostSeriesChart({ points }: { points: CostSeriesPoint[] }) {
  // Captured once on mount rather than re-derived every render, so the 24
  // hourly buckets don't silently shift under the reader while they hover.
  const [now] = React.useState(() => new Date())
  const series = React.useMemo(() => buildHourlySeries(points, now), [points, now])
  const [hoverIndex, setHoverIndex] = React.useState<number | null>(null)
  const svgRef = React.useRef<SVGSVGElement>(null)

  const totalCalls = series.reduce((sum, p) => sum + p.calls, 0)
  const maxCost = Math.max(1e-9, ...series.map((p) => p.cost))
  const innerWidth = WIDTH - PAD_X * 2
  const innerHeight = HEIGHT - PAD_TOP - PAD_BOTTOM

  const xAt = (i: number) =>
    PAD_X + (series.length > 1 ? (i / (series.length - 1)) * innerWidth : innerWidth / 2)
  const yAt = (cost: number) => PAD_TOP + innerHeight * (1 - cost / maxCost)

  const linePath = series
    .map((p, i) => `${i === 0 ? "M" : "L"} ${xAt(i).toFixed(2)} ${yAt(p.cost).toFixed(2)}`)
    .join(" ")
  const baseline = PAD_TOP + innerHeight
  const areaPath = `${linePath} L ${xAt(series.length - 1).toFixed(2)} ${baseline} L ${xAt(0).toFixed(2)} ${baseline} Z`

  function handlePointer(e: React.PointerEvent<SVGSVGElement>) {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const relX = ((e.clientX - rect.left) / rect.width) * WIDTH
    const idx = Math.round(((relX - PAD_X) / innerWidth) * (series.length - 1))
    setHoverIndex(Math.min(series.length - 1, Math.max(0, idx)))
  }

  if (totalCalls === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed border-border">
        <p className="text-sm text-muted-foreground">No LLM calls in the last 24 hours.</p>
      </div>
    )
  }

  const hovered = hoverIndex !== null ? series[hoverIndex] : null
  const hoveredOnRightHalf = hoverIndex !== null && hoverIndex > series.length / 2

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-[200px] w-full touch-none"
        preserveAspectRatio="none"
        onPointerMove={handlePointer}
        onPointerLeave={() => setHoverIndex(null)}
        role="img"
        aria-label="LLM spend over the last 24 hours"
      >
        {[0, 0.5, 1].map((g) => {
          const y = PAD_TOP + innerHeight * (1 - g)
          return (
            <line
              key={g}
              x1={PAD_X}
              x2={WIDTH - PAD_X}
              y1={y}
              y2={y}
              className="stroke-border"
              strokeWidth={1}
            />
          )
        })}

        <path d={areaPath} className="fill-primary/10" stroke="none" />
        <path
          d={linePath}
          className="stroke-primary"
          strokeWidth={2}
          fill="none"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {hoverIndex !== null && (
          <>
            <line
              x1={xAt(hoverIndex)}
              x2={xAt(hoverIndex)}
              y1={PAD_TOP}
              y2={baseline}
              className="stroke-muted-foreground/40"
              strokeWidth={1}
            />
            <circle
              cx={xAt(hoverIndex)}
              cy={yAt(series[hoverIndex].cost)}
              r={4}
              className="fill-primary stroke-card"
              strokeWidth={2}
            />
          </>
        )}
      </svg>

      {hovered && hoverIndex !== null && (
        <div
          className="pointer-events-none absolute top-1 rounded-lg border border-border bg-popover px-2.5 py-1.5 text-xs whitespace-nowrap shadow-sm"
          style={{
            left: `${(xAt(hoverIndex) / WIDTH) * 100}%`,
            transform: hoveredOnRightHalf ? "translateX(-108%)" : "translateX(8%)",
          }}
        >
          <p className="font-medium text-popover-foreground">{formatUsd(hovered.cost)}</p>
          <p className="text-muted-foreground">
            {hovered.hour.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}
            {" · "}
            {formatCount(hovered.calls)} calls
          </p>
        </div>
      )}

      <div className="mt-1 flex justify-between text-xs text-muted-foreground">
        <span>{series[0].hour.toLocaleTimeString("en-IN", { hour: "numeric" })}</span>
        <span>now</span>
      </div>
    </div>
  )
}
