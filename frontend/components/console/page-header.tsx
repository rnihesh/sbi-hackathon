import type * as React from "react"

export function ConsolePageHeader({
  title,
  description,
  actions,
}: {
  title: React.ReactNode
  description: string
  /** Optional right-aligned controls (e.g. a CSV download button). */
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
