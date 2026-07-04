"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { AnimatePresence, motion } from "framer-motion"
import {
  Bell,
  CheckCheck,
  InfoIcon,
  PartyPopper,
  PlusCircle,
  Sparkles,
  type LucideIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { springSoft } from "@/lib/motion"
import { formatRelativeTime } from "@/lib/format"
import { useNotifications } from "@/lib/notifications"
import type { AppNotification, NotificationKind } from "@/lib/notification-types"
import { Button } from "@/components/ui/button"

const KIND_ICON: Record<NotificationKind, LucideIcon> = {
  offer: Sparkles,
  life_event: PartyPopper,
  account: PlusCircle,
  nudge: Bell,
  system: InfoIcon,
}

function NotificationRow({
  notification,
  onSelect,
}: {
  notification: AppNotification
  onSelect: (n: AppNotification) => void
}) {
  const Icon = KIND_ICON[notification.kind] ?? Bell
  const unread = !notification.read
  return (
    <motion.button
      layout
      type="button"
      onClick={() => onSelect(notification)}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springSoft}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors",
        "hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        unread && "bg-primary/[0.06]"
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full",
          unread ? "bg-primary/12 text-primary" : "bg-secondary text-muted-foreground"
        )}
      >
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className={cn("truncate text-sm", unread ? "font-semibold" : "font-medium")}>
            {notification.title}
          </span>
          {unread && <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />}
        </span>
        <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
          {notification.body}
        </span>
        <span className="mt-1 block text-[11px] text-muted-foreground/80">
          {formatRelativeTime(notification.created_at)}
        </span>
      </span>
    </motion.button>
  )
}

export function NotificationPanel({
  onClose,
  closeButtonSpace = false,
}: {
  onClose?: () => void
  /** Reserve header space on the right for a host's close button (mobile sheet). */
  closeButtonSpace?: boolean
}) {
  const router = useRouter()
  const { notifications, unread, loading, markRead, markAllRead } = useNotifications()

  const handleSelect = React.useCallback(
    (n: AppNotification) => {
      if (!n.read) void markRead([n.id])
      onClose?.()
      if (n.link && n.link.startsWith("/")) router.push(n.link)
    },
    [markRead, onClose, router]
  )

  return (
    <div className="flex max-h-[70dvh] flex-col sm:max-h-[26rem]">
      <div
        className={cn(
          "flex items-center justify-between gap-2 border-b border-border px-3 py-2.5",
          closeButtonSpace && "pr-11"
        )}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold tracking-tight">Notifications</span>
          {unread > 0 && (
            <span className="rounded-full bg-primary/12 px-1.5 py-0.5 text-[11px] font-medium text-primary">
              {unread} new
            </span>
          )}
        </div>
        {unread > 0 && (
          <Button variant="ghost" size="xs" onClick={() => void markAllRead()}>
            <CheckCheck className="size-3" />
            Mark all read
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {loading && notifications.length === 0 ? (
          <div className="flex flex-col gap-2 p-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-start gap-3 px-1.5 py-1.5">
                <div className="size-8 shrink-0 animate-pulse rounded-full bg-muted" />
                <div className="flex-1 space-y-1.5 py-0.5">
                  <div className="h-3 w-3/4 animate-pulse rounded bg-muted" />
                  <div className="h-2.5 w-1/2 animate-pulse rounded bg-muted" />
                </div>
              </div>
            ))}
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
            <span className="flex size-10 items-center justify-center rounded-full bg-muted">
              <Bell className="size-4 text-muted-foreground" />
            </span>
            <p className="text-sm font-medium">Nothing yet</p>
            <p className="max-w-[15rem] text-xs text-muted-foreground">
              Sarathi will let you know here when something happens on your accounts.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            <AnimatePresence initial={false}>
              {notifications.map((n) => (
                <NotificationRow key={n.id} notification={n} onSelect={handleSelect} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}
