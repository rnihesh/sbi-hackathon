"use client"

import * as React from "react"
import { Bell } from "lucide-react"

import { cn } from "@/lib/utils"
import { useNotifications } from "@/lib/notifications"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { NotificationPanel } from "@/components/customer/notification-panel"

function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <span
      className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-foreground ring-2 ring-background"
      aria-label={`${count} unread`}
    >
      {count > 9 ? "9+" : count}
    </span>
  )
}

/** Desktop: a sidebar row that opens a popover. */
export function SidebarNotificationBell() {
  const { unread } = useNotifications()
  const [open, setOpen] = React.useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className={cn(
          "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
          "text-sidebar-foreground/70 outline-none transition-colors",
          "hover:-translate-y-px hover:bg-secondary/70 hover:text-sidebar-foreground",
          "focus-visible:ring-2 focus-visible:ring-ring aria-expanded:bg-secondary/70 aria-expanded:text-sidebar-foreground"
        )}
      >
        <span className="relative flex items-center">
          <Bell className="size-4 transition-transform duration-200 group-hover:scale-110" />
          <CountBadge count={unread} />
        </span>
        Notifications
      </PopoverTrigger>
      <PopoverContent
        side="right"
        align="end"
        sideOffset={12}
        className="w-80 p-0"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <NotificationPanel onClose={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  )
}

/** Mobile: an icon button (in the top bar) that opens a side sheet. */
export function MobileNotificationBell() {
  const { unread } = useNotifications()
  const [open, setOpen] = React.useState(false)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        className={cn(
          "relative flex size-9 items-center justify-center rounded-full text-foreground/80",
          "outline-none transition-transform duration-150 ease-[cubic-bezier(0.34,1.56,0.64,1)]",
          "hover:bg-secondary/70 active:scale-90 focus-visible:ring-2 focus-visible:ring-ring"
        )}
      >
        <Bell className="size-5" />
        <CountBadge count={unread} />
      </SheetTrigger>
      <SheetContent side="right" showCloseButton className="w-[86vw] max-w-sm gap-0 p-0">
        <SheetTitle className="sr-only">Notifications</SheetTitle>
        <NotificationPanel onClose={() => setOpen(false)} closeButtonSpace />
      </SheetContent>
    </Sheet>
  )
}
