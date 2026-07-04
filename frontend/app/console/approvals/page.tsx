import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { ConsolePageHeader } from "@/components/console/page-header"

export default function ApprovalsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <ConsolePageHeader
        title="Approvals"
        description="Proposals from agents awaiting human-in-the-loop sign-off."
      />

      <div className="flex flex-col gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="flex flex-col gap-4 pt-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/3" />
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled>
                  Reject
                </Button>
                <Button size="sm" disabled>
                  Approve
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
