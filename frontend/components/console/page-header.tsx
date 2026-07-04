import type * as React from "react"

export function ConsolePageHeader({
  title,
  description,
}: {
  title: React.ReactNode
  description: string
}) {
  return (
    <div className="mb-6">
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  )
}
