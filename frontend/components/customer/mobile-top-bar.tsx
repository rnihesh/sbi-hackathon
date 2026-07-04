"use client"

import Link from "next/link"

import { SarathiLogo } from "@/components/brand/logo"
import { MobileNotificationBell } from "@/components/customer/notification-bell"

/** Slim top bar shown on mobile only (desktop uses the sidebar). Gives the app
 * brand presence and hosts the notification bell where a top bar belongs. */
export function MobileTopBar() {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/75 md:hidden">
      <Link href="/app/home" className="flex items-center">
        <SarathiLogo className="text-sm" markClassName="text-primary" />
      </Link>
      <MobileNotificationBell />
    </header>
  )
}
