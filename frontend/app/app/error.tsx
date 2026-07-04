"use client"

import { ErrorFallback } from "@/components/error-fallback"

// `error.tsx` only replaces this segment's content, not `app/app/layout.tsx`
// above it - `AppShell` (sidebar, mobile top bar, bottom tab bar) stays
// mounted and interactive, so a broken tab doesn't strand the user without
// navigation.
export default function CustomerAppError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return <ErrorFallback error={error} reset={reset} fullHeight={false} />
}
