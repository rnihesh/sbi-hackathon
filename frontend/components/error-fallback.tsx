"use client"

import * as React from "react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { SarathiMark } from "@/components/brand/logo"

/**
 * Shared body for every route-segment `error.tsx` boundary (root, `/app`,
 * `/console`). A nested `error.tsx` only replaces its own segment's content -
 * the enclosing layout (and its nav chrome: sidebar, bottom tab bar, top bar)
 * stays mounted and interactive - so this only ever needs to render the
 * message itself, never the surrounding shell.
 */
export function ErrorFallback({
  error,
  reset,
  fullHeight = true,
}: {
  error: Error & { digest?: string }
  reset: () => void
  /** false inside `/app` and `/console`: their layout's nav chrome already
   * takes up the rest of the viewport, so this only needs to fill the main
   * content area, not the full screen. */
  fullHeight?: boolean
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-6 px-4 py-20 text-center",
        fullHeight ? "min-h-dvh" : "min-h-[60dvh]"
      )}
    >
      <SarathiMark className="size-10 text-primary" />
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Something went wrong</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          Sarathi hit an unexpected error. Try again, or come back in a moment.
        </p>
        {error.digest && (
          <p className="font-mono text-xs text-muted-foreground/70">ref: {error.digest}</p>
        )}
      </div>
      <Button className="px-6" onClick={() => reset()}>
        Try again
      </Button>
    </div>
  )
}
