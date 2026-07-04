"use client"

import { ErrorFallback } from "@/components/error-fallback"

// Same rationale as `app/app/error.tsx` - keeps the console sidebar/topbar
// (and the staff session) mounted when a single console page throws.
export default function ConsoleError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return <ErrorFallback error={error} reset={reset} fullHeight={false} />
}
