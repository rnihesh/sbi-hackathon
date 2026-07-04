import { Activity, Bell, ClipboardCheck, Sparkles, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatRelativeTime } from "@/lib/format"
import type { FeedItem, FeedItemType } from "@/lib/console-types"

const TYPE_ICON: Record<FeedItemType, LucideIcon> = {
  agent_run: Activity,
  proposal: ClipboardCheck,
  life_event: Sparkles,
  nudge: Bell,
}

const TYPE_LABEL: Record<FeedItemType, string> = {
  agent_run: "Agent run",
  proposal: "Proposal",
  life_event: "Life event",
  nudge: "Nudge",
}

export function FeedItemRow({ item }: { item: FeedItem }) {
  const Icon = TYPE_ICON[item.type] ?? Activity
  // Proposals need a human decision - give them the one spot of accent color.
  const isActionable = item.type === "proposal"

  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <div
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-full",
          isActionable ? "bg-accent text-accent-foreground" : "bg-muted text-muted-foreground"
        )}
      >
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">{item.summary}</p>
        <p className="text-xs text-muted-foreground">
          {TYPE_LABEL[item.type] ?? item.type}
          {item.customer_id && <> &middot; customer {item.customer_id.slice(0, 8)}</>}
        </p>
      </div>
      <span className="shrink-0 text-xs text-muted-foreground">{formatRelativeTime(item.ts)}</span>
    </div>
  )
}
