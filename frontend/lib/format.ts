/** Formatting helpers shared across customer + console surfaces. */

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
})

/** Formats paise (integer, may be negative) as a lakh/crore-grouped rupee amount. */
export function formatPaise(paise: number): string {
  return inr.format(paise / 100)
}

/** Signed paise amount for transaction rows - `+`/`-` prefix, no currency symbol
 * repetition needed since the sign already communicates direction. */
export function formatSignedPaise(paise: number, direction: "credit" | "debit"): string {
  const amount = inr.format(Math.abs(paise) / 100)
  return direction === "credit" ? `+${amount}` : `-${amount}`
}

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 6,
})

/** Formats an LLM cost (USD, may arrive as a `Decimal` wire string) with at
 * least 4 decimal places - tiny per-call costs (e.g. $0.000059) stay legible
 * instead of rounding to zero. */
export function formatUsd(value: number | string): string {
  const n = typeof value === "string" ? Number(value) : value
  return usd.format(Number.isFinite(n) ? n : 0)
}

const integerFormatter = new Intl.NumberFormat("en-US")

/** Thousands-grouped integer (token counts, call counts). */
export function formatCount(value: number): string {
  return integerFormatter.format(Math.round(value))
}

/** Renders a millisecond duration as "342ms" / "1.4s" / "13.2s". */
export function formatLatency(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return "-"
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/** Picks the singular or plural form of a noun for `count` (e.g. "1 call" vs
 * "83 calls"). */
export function pluralize(count: number, singular: string, plural: string = `${singular}s`): string {
  return count === 1 ? singular : plural
}

const relativeTimeFormatter = new Intl.RelativeTimeFormat("en-IN", { numeric: "auto" })

const DIVISIONS: Array<{ amount: number; unit: Intl.RelativeTimeFormatUnit }> = [
  { amount: 60, unit: "seconds" },
  { amount: 60, unit: "minutes" },
  { amount: 24, unit: "hours" },
  { amount: 7, unit: "days" },
  { amount: 4.34524, unit: "weeks" },
  { amount: 12, unit: "months" },
  { amount: Number.POSITIVE_INFINITY, unit: "years" },
]

/** Renders `iso` relative to now - "3 minutes ago", "yesterday", etc. */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  let duration = (new Date(iso).getTime() - now.getTime()) / 1000

  for (const division of DIVISIONS) {
    if (Math.abs(duration) < division.amount) {
      return relativeTimeFormatter.format(Math.round(duration), division.unit)
    }
    duration /= division.amount
  }
  return relativeTimeFormatter.format(Math.round(duration), "years")
}

export function formatTimeOfDay(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
}

export function timeOfDayGreeting(now: Date = new Date()): string {
  const hour = now.getHours()
  if (hour < 5) return "Still up"
  if (hour < 12) return "Good morning"
  if (hour < 17) return "Good afternoon"
  if (hour < 21) return "Good evening"
  return "Good night"
}

/** Title-cases a snake_case / kebab-case / camelCase identifier, upper-casing
 * known banking acronyms ("kyc" -> "KYC"). */
export function humanizeIdentifier(id: string): string {
  const ACRONYMS = new Set([
    "kyc", "otp", "sbi", "upi", "cbs", "nba", "id", "faq", "ifsc",
    "neft", "imps", "rtgs", "atm", "emi", "fd", "rd",
  ])
  const words = id
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)

  return words
    .map((word) => {
      const lower = word.toLowerCase()
      return ACRONYMS.has(lower) ? lower.toUpperCase() : lower.charAt(0).toUpperCase() + lower.slice(1)
    })
    .join(" ")
}

const TOOL_VERB_PREFIXES: Array<{ prefixes: string[]; verb: string }> = [
  { prefixes: ["check", "verify", "validate", "confirm"], verb: "Verifying" },
  { prefixes: ["get", "fetch", "lookup", "read", "load"], verb: "Looking up" },
  { prefixes: ["search", "find", "query"], verb: "Searching" },
  { prefixes: ["create", "open", "setup", "start", "init"], verb: "Setting up" },
  { prefixes: ["send", "notify", "email"], verb: "Sending" },
  { prefixes: ["update", "set"], verb: "Updating" },
  { prefixes: ["calculate", "compute", "estimate"], verb: "Calculating" },
  { prefixes: ["match", "recommend", "suggest"], verb: "Matching" },
  { prefixes: ["save", "store", "write", "remember"], verb: "Saving" },
]

/** Turns a tool name like `check_kyc_status` into "Verifying KYC status…" for the
 * chat activity chips. Falls back to "Running {name}…" for anything unrecognized. */
export function humanizeToolActivity(tool: string): string {
  const parts = tool
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[_-]+/)
    .filter(Boolean)

  if (parts.length === 0) return `Running ${tool}…`

  const [head, ...rest] = parts
  const match = TOOL_VERB_PREFIXES.find((entry) => entry.prefixes.includes(head))
  const restLabel = humanizeIdentifier(rest.join("_")) || humanizeIdentifier(head)

  if (match) {
    return rest.length > 0 ? `${match.verb} ${restLabel}…` : `${match.verb}…`
  }
  return `Running ${humanizeIdentifier(tool)}…`
}
