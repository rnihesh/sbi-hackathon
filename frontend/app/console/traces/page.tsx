import { ConsolePageHeader } from "@/components/console/page-header"
import { ListRowSkeleton } from "@/components/console/list-row-skeleton"

export default function TracesPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <ConsolePageHeader
        title="Traces"
        description="Every agent run — node, tool, model, tokens, latency, cost."
      />
      <ListRowSkeleton count={5} />
    </div>
  )
}
