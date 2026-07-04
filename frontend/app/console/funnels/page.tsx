import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ConsolePageHeader } from "@/components/console/page-header"

const STAGES = [
  { label: "Visited", height: "h-32" },
  { label: "Started KYC", height: "h-24" },
  { label: "Completed KYC", height: "h-16" },
  { label: "Funded", height: "h-10" },
]

export default function FunnelsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <ConsolePageHeader
        title="Funnels"
        description="Onboarding conversion, stage by stage."
      />

      <Card>
        <CardHeader>
          <CardTitle>Account opening funnel</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-6 pt-4 pb-2">
            {STAGES.map((stage) => (
              <div key={stage.label} className="flex flex-1 flex-col items-center gap-2">
                <Skeleton className={`w-full ${stage.height} rounded-t-lg`} />
                <span className="text-xs text-muted-foreground">{stage.label}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
