import { Skeleton } from "@/components/ui/skeleton"
import { HomeSkeleton } from "@/components/customer/home-skeleton"

/**
 * Route-level fallback for `/app/home` - shown instantly on navigation while
 * the segment's JS/RSC payload loads, before the page component itself has a
 * chance to mount and run its own `loading` state. Reuses the same
 * `HomeSkeleton` the page renders while fetching the dashboard, so there is
 * no visible swap between this and the page's own loading state. The title
 * is a skeleton bar (not literal text) since the real greeting depends on
 * data this boundary doesn't have yet.
 */
export default function Loading() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-56" />
      </div>
      <HomeSkeleton />
    </div>
  )
}
