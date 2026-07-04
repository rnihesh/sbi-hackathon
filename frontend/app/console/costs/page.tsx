import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ConsolePageHeader } from "@/components/console/page-header"

const TILES = ["Spend today", "Spend this month", "Avg. cost / run", "Fallback rate"]

export default function CostsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <ConsolePageHeader
        title="Costs"
        description="LLM spend across providers and policy tiers."
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {TILES.map((tile) => (
          <Card key={tile}>
            <CardContent className="space-y-2 pt-4">
              <p className="text-xs text-muted-foreground">{tile}</p>
              <Skeleton className="h-6 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Spend over time</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full rounded-lg" />
        </CardContent>
      </Card>
    </div>
  )
}
