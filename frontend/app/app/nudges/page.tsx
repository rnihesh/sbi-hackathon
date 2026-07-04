import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export default function NudgesPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Nudges</h1>
        <p className="text-sm text-muted-foreground">
          Timely suggestions, never spam.
        </p>
      </div>

      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="flex items-center gap-3 pt-4">
            <Skeleton className="size-10 shrink-0 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
