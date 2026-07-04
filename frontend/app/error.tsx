"use client"

import { ErrorFallback } from "@/components/error-fallback"

// Root error boundary - catches anything not caught by a more specific
// nested `error.tsx` (e.g. the marketing/landing pages). Note this is NOT
// `global-error.tsx`: it renders inside the root layout (fonts, theme,
// toaster stay mounted), it just replaces the page content below it.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return <ErrorFallback error={error} reset={reset} />
}
