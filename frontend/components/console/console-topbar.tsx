"use client"

import { usePathname, useRouter } from "next/navigation"
import { LogOut } from "lucide-react"
import { toast } from "sonner"

import { useMe } from "@/lib/auth"
import { ThemeToggle } from "@/components/nav/theme-toggle"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ConsoleMobileNav } from "@/components/console/console-mobile-nav"
import { WorkerHealthIndicator } from "@/components/console/worker-health-indicator"
import { CONSOLE_NAV_ITEMS } from "@/components/console/nav-items"

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "SB"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function ConsoleTopbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { me, logout } = useMe()
  const active = CONSOLE_NAV_ITEMS.find((item) => pathname.startsWith(item.href))

  const displayName = me?.customer?.full_name ?? me?.user.email ?? "Staff"

  async function handleLogout() {
    await logout()
    toast.success("Signed out")
    router.push("/")
  }

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
        <WorkerHealthIndicator />
        <ThemeToggle />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="Account menu"
              className="rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Avatar className="size-8">
                <AvatarFallback className="bg-accent text-xs text-accent-foreground">
                  {initialsFor(displayName)}
                </AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel className="max-w-48 truncate font-normal text-foreground">
              {displayName}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => void handleLogout()}>
              <LogOut />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
