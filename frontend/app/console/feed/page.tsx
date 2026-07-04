import { Badge } from "@/components/ui/badge"
import { ConsolePageHeader } from "@/components/console/page-header"
import { ListRowSkeleton } from "@/components/console/list-row-skeleton"

export default function LiveFeedPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <ConsolePageHeader
          title="Live Feed"
          description="Real-time agent activity across every customer session."
        />
        <Badge variant="secondary" className="shrink-0">
          Waiting for sim
        </Badge>
      </div>
      <ListRowSkeleton count={6} />
    </div>
  )
}
