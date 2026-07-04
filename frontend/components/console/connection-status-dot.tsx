import { cn } from "@/lib/utils"
import type { SseConnectionStatus } from "@/lib/use-sse"

const LABELS: Record<SseConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  closed: "Disconnected",
}

export function ConnectionStatusDot({ status }: { status: SseConnectionStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="relative flex size-2">
        {status === "open" && (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:animate-none" />
        )}
        <span
          className={cn(
            "relative inline-flex size-2 rounded-full",
            status === "open" && "bg-primary",
            status === "connecting" && "bg-muted-foreground/50",
            status === "reconnecting" && "bg-muted-foreground",
            status === "closed" && "bg-destructive/70"
          )}
        />
      </span>
      {LABELS[status]}
    </span>
  )
}
