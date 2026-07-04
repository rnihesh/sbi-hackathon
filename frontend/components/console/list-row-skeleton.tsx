import { Skeleton } from "@/components/ui/skeleton"

export function ListRowSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="divide-y divide-border rounded-xl border border-border">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3">
          <Skeleton className="size-9 shrink-0 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="h-3 w-14 shrink-0" />
        </div>
      ))}
    </div>
  )
}
