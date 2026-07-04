import { Skeleton } from "@/components/ui/skeleton"
import { ConsolePageHeader } from "@/components/console/page-header"

export default function LifeEventsPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <ConsolePageHeader
        title="Life Events"
        description="Job changes, new children, home intent — detected as they happen."
      />

      <ol className="relative flex flex-col gap-6 border-l border-border pl-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <li key={i} className="relative">
            <span className="absolute -left-[1.6rem] top-1 size-2.5 rounded-full bg-primary/60" />
            <Skeleton className="mb-2 h-3.5 w-24" />
            <Skeleton className="h-4 w-2/3" />
          </li>
        ))}
      </ol>
    </div>
  )
}
