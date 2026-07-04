import Link from "next/link"

import { Button } from "@/components/ui/button"
import { ThemeToggle } from "@/components/nav/theme-toggle"

export function LandingNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight">Sarathi</span>
        </Link>

        <div className="flex items-center gap-1 sm:gap-2">
          <ThemeToggle />
          <Button variant="ghost" size="sm" asChild>
            <Link href="/app/home">Sign in</Link>
          </Button>
        </div>
      </div>
    </header>
  )
}
