"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { SarathiLogo } from "@/components/brand/logo"
import { MobileNotificationBell } from "@/components/customer/notification-bell"
import { pageTitleForPath } from "@/components/customer/tabs"

/** Slim top bar shown on mobile only (desktop uses the sidebar). Gives the app
 * brand presence, hosts the notification bell, and (grid layout, not flex)
 * centers the current page's title so mobile users always know where they
 * are - the outer 1fr/auto/1fr columns keep the title truly centered even
 * though the wordmark and the bell button are different widths. */
export function MobileTopBar() {
  const pathname = usePathname()
  const title = pageTitleForPath(pathname)

  return (
    <header className="sticky top-0 z-30 grid h-14 grid-cols-[1fr_auto_1fr] items-center border-b border-border bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/75 md:hidden">
      <Link href="/app/home" className="flex items-center justify-self-start">
        <SarathiLogo className="text-sm" markClassName="text-primary" />
      </Link>
      {title && (
        <span className="max-w-[45vw] truncate justify-self-center text-sm font-medium text-foreground">
          {title}
        </span>
      )}
      <div className="justify-self-end">
        <MobileNotificationBell />
      </div>
    </header>
  )
}
