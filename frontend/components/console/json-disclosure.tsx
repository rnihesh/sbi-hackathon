"use client"

import * as React from "react"
import { ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === "object") return Object.keys(value as object).length === 0
  return false
}

/** Collapsible `<pre>` JSON viewer - the shared expand/collapse pattern already
 * used for proposal action payloads and life-event evidence, generalized so
 * trace steps can show both `input` and `output` without duplicating it. */
export function JsonDisclosure({
  label,
  value,
  defaultOpen = false,
}: {
  label: string
  value: unknown
  defaultOpen?: boolean
}) {
  const [open, setOpen] = React.useState(defaultOpen)

  if (isEmpty(value)) {
    return <p className="text-xs text-muted-foreground">{label}: none</p>
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
        {open ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
      </button>
      {open && (
        <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-muted p-3 font-mono text-xs whitespace-pre-wrap break-words">
          {JSON.stringify(value, null, 2)}
        </pre>
      )}
    </div>
  )
}
