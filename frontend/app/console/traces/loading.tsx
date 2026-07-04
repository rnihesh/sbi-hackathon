import { ConsolePageHeader } from "@/components/console/page-header"
import { ListRowSkeleton } from "@/components/console/list-row-skeleton"

/**
 * Route-level fallback for `/console/traces` - shown instantly on
 * navigation, before the page component (and its own `Suspense` fallback for
 * `useSearchParams`) mounts. Mirrors the loaded shell's header + row list so
 * there's no visible jump once the real data arrives.
 */
export default function Loading() {
  return (
    <div className="mx-auto max-w-5xl">
      <ConsolePageHeader
        title="Traces"
        description="Every agent run - node, tool, model, tokens, latency, cost."
      />
      <ListRowSkeleton count={6} />
    </div>
  )
}
