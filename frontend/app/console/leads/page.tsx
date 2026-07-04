import { Skeleton } from "@/components/ui/skeleton"
import { ConsolePageHeader } from "@/components/console/page-header"

const COLUMNS = ["Customer", "Product", "Stage", "Score"]

export default function LeadsPage() {
  return (
    <div className="mx-auto max-w-5xl">
      <ConsolePageHeader
        title="Leads"
        description="Acquisition candidates surfaced by the AcquisitionAgent."
      />

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              {COLUMNS.map((col) => (
                <th key={col} className="px-4 py-2.5 font-medium">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {Array.from({ length: 6 }).map((_, row) => (
              <tr key={row}>
                {COLUMNS.map((col) => (
                  <td key={col} className="px-4 py-3">
                    <Skeleton className="h-3.5 w-20" />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
