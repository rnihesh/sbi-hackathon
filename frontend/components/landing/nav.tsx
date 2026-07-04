"use client"

import Link from "next/link"

import { Button } from "@/components/ui/button"
import { ThemeToggle } from "@/components/nav/theme-toggle"
import { useMe } from "@/lib/auth"
import { useSignInSheet } from "@/components/auth/sign-in-sheet-context"
import { SarathiLogo } from "@/components/brand/logo"

export function LandingNav() {
  const { status } = useMe()
  const { setOpen } = useSignInSheet()

  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center">
          <SarathiLogo className="text-sm" markClassName="text-primary" />
        </Link>

        <div className="flex items-center gap-1 sm:gap-2">
          <ThemeToggle />
          {status === "authenticated" ? (
            <Button variant="ghost" size="sm" asChild>
              <Link href="/app/home">Open app</Link>
            </Button>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
              Sign in
            </Button>
          )}
        </div>
      </div>
    </header>
  )
}
