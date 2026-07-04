import { formatCount, formatUsd } from "@/lib/format"
import type { TimeseriesPoint } from "@/lib/console-types"

const SVG_W = 240
const SVG_H = 34
const PAD_Y = 4

/** A single tiny SVG line normalized to its own series max, clay stroke with an
 * endpoint dot. Pure SVG, no chart library. A flat/empty series renders a
 * hairline baseline rather than nothing, so the row still reads as "zero". */
function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(0, ...values)
  const n = values.length
  const innerH = SVG_H - PAD_Y * 2

  const xAt = (i: number) => (n > 1 ? (i / (n - 1)) * SVG_W : SVG_W / 2)
  const yAt = (v: number) => PAD_Y + innerH * (1 - (max > 0 ? v / max : 0))

  const path = values
    .map((v, i) => `${i === 0 ? "M" : "L"} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`)
    .join(" ")
  const lastX = xAt(n - 1)
  const lastY = yAt(values[n - 1] ?? 0)

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="h-[34px] w-full"
      preserveAspectRatio="none"
      role="img"
      aria-hidden="true"
    >
      <line
        x1={0}
        x2={SVG_W}
        y1={PAD_Y + innerH}
        y2={PAD_Y + innerH}
        className="stroke-border"
        strokeWidth={1}
      />
      <path
        d={path}
        className="stroke-primary"
        strokeWidth={1.5}
        fill="none"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={lastX} cy={lastY} r={2.5} className="fill-primary" />
    </svg>
  )
}

interface MetricSpec {
  key: keyof Pick<
    TimeseriesPoint,
    | "agent_runs"
    | "proposals_created"
    | "proposals_approved"
    | "nudges_sent"
    | "nudges_acted"
  >
  label: string
}

const METRICS: MetricSpec[] = [
  { key: "agent_runs", label: "Agent runs" },
  { key: "proposals_created", label: "Proposals" },
  { key: "proposals_approved", label: "Approved" },
  { key: "nudges_sent", label: "Nudges sent" },
  { key: "nudges_acted", label: "Nudges acted" },
]

function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  })
}

/** Multi-row sparkline strip: one small clay line per metric over a shared daily
 * x-axis, each row ending in a dot + last value. */
export function MetricSparklines({ points }: { points: TimeseriesPoint[] }) {
  if (points.length === 0) {
    return <p className="text-sm text-muted-foreground">No activity in this window.</p>
  }

  const rows = [
    ...METRICS.map((m) => ({
      label: m.label,
      values: points.map((p) => p[m.key]),
      last: formatCount(points[points.length - 1][m.key]),
    })),
    {
      label: "LLM spend",
      values: points.map((p) => Number(p.llm_cost_usd)),
      last: formatUsd(points[points.length - 1].llm_cost_usd),
    },
  ]

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-3">
          <span className="w-24 shrink-0 text-xs text-muted-foreground">{row.label}</span>
          <div className="min-w-0 flex-1">
            <Sparkline values={row.values} />
          </div>
          <span className="w-16 shrink-0 text-right font-mono text-xs tabular-nums text-foreground">
            {row.last}
          </span>
        </div>
      ))}
      <div className="flex justify-between pl-24 text-xs text-muted-foreground">
        <span>{shortDate(points[0].date)}</span>
        <span>{shortDate(points[points.length - 1].date)}</span>
      </div>
    </div>
  )
}
