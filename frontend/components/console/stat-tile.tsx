import { Card, CardContent } from "@/components/ui/card"

export function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <Card size="sm">
      <CardContent className="space-y-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="font-mono text-sm tabular-nums">{value}</p>
      </CardContent>
    </Card>
  )
}
