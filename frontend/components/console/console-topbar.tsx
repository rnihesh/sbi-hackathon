"use client"

import { usePathname } from "next/navigation"

import { ThemeToggle } from "@/components/nav/theme-toggle"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { ConsoleMobileNav } from "@/components/console/console-mobile-nav"
import { CONSOLE_NAV_ITEMS } from "@/components/console/nav-items"

export function ConsoleTopbar() {
  const pathname = usePathname()
  const active = CONSOLE_NAV_ITEMS.find((item) => pathname.startsWith(item.href))

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60 sm:px-6">
      <div className="flex items-center gap-2">
        <ConsoleMobileNav />
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Console</span>
          <span className="text-muted-foreground/50">/</span>
          <span className="font-medium">{active?.label ?? "Overview"}</span>
        </nav>
      </div>

      <div className="flex items-center gap-2">
        <ThemeToggle />
        <Avatar className="size-8">
          <AvatarFallback className="bg-accent text-xs text-accent-foreground">
            SB
          </AvatarFallback>
        </Avatar>
      </div>
    </header>
  )
}
