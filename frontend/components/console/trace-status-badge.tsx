import { Loader2 } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

const VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  running: "default",
  completed: "secondary",
  failed: "destructive",
  cancelled: "outline",
}

export function TraceStatusBadge({ status, className }: { status: string; className?: string }) {
  const variant = VARIANT[status] ?? "outline"
  return (
    <Badge variant={variant} className={cn("capitalize", className)}>
      {status === "running" && <Loader2 className="size-3 animate-spin" />}
      {status}
    </Badge>
  )
}
