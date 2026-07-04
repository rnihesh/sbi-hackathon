import Link from "next/link"
import { Activity, Bell, ClipboardCheck, Sparkles, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatRelativeTime } from "@/lib/format"
import type { FeedItem, FeedItemType } from "@/lib/console-types"
import { Button } from "@/components/ui/button"

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

/** Where each feed-item type's action button goes - `agent_run` deep-links to
 * the specific trace (its `ref_id` *is* the run id, see
 * `app.workers.activity.publish_run_result`); `proposal`/`life_event` route to
 * their (unfiltered) list pages rather than a specific row, since there's no
 * per-item deep link for either yet and re-approving inline here would risk a
 * double-execution race with the approvals page - just get the staff member to
 * the right page. */
function actionFor(item: FeedItem): { href: string; label: string } | null {
  if (item.type === "agent_run") {
    return item.ref_id ? { href: `/console/traces/${item.ref_id}`, label: "Trace" } : null
  }
  if (item.type === "proposal") return { href: "/console/approvals", label: "Review" }
  if (item.type === "life_event") return { href: "/console/life-events", label: "View" }
  return null
}

export function FeedItemRow({ item }: { item: FeedItem }) {
  const Icon = TYPE_ICON[item.type] ?? Activity
  // Proposals need a human decision - give them the one spot of accent color.
  const isActionable = item.type === "proposal"
  const action = actionFor(item)

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
      {action && (
        <Button asChild variant="ghost" size="xs" className="shrink-0">
          <Link href={action.href}>{action.label}</Link>
        </Button>
      )}
      <span className="shrink-0 text-xs text-muted-foreground">{formatRelativeTime(item.ts)}</span>
    </div>
  )
}
