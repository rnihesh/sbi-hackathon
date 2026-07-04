import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

/** Shared between `/app/home`'s own `loading` state (while fetching the
 * dashboard) and its route-level `loading.tsx` (shown before the page even
 * mounts) - kept out of `page.tsx` since Next.js route files may only export
 * the reserved route-config names (`default`, `metadata`, etc). */
export function HomeSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Balance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-4 w-48" />
        </CardContent>
      </Card>
      <div className="flex flex-col gap-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    </div>
  )
}
