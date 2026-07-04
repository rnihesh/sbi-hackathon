import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export default function HomePage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Home</h1>
        <p className="text-sm text-muted-foreground">
          Your accounts, at a glance.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Balance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-4 w-48" />
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardContent className="space-y-2 pt-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-6 w-24" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 pt-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-6 w-24" />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
