"use client"

import * as React from "react"
import Link from "next/link"
import { Sparkles, X } from "lucide-react"

import { cn } from "@/lib/utils"
import { loadWelcomeDismissed, saveWelcomeDismissed } from "@/lib/onboarding-storage"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { SarathiMark } from "@/components/brand/logo"

/**
 * The zero-accounts slot on `/app/home`. Two variants of the same empty state,
 * never both at once:
 *
 * - First run (nothing dismissed yet): a friendly "Welcome to Sarathi" card
 *   explaining what the app does, with the same two actions below, plus a
 *   dismiss control. Dismissing persists to localStorage and this variant
 *   never shows again for this browser.
 * - Every other time an account-less customer lands here (including right
 *   after dismissing): the quieter, undismissable panel that always shows
 *   for a zero-accounts customer.
 *
 * Deliberately not a multi-step tour - one card, two sentences, two buttons.
 */
export function WelcomeCard({
  loadingDemo,
  onLoadDemoActivity,
}: {
  loadingDemo: boolean
  onLoadDemoActivity: () => void
}) {
  const [showWelcome, setShowWelcome] = React.useState(false)

  React.useEffect(() => {
    setShowWelcome(!loadWelcomeDismissed())
  }, [])

  function dismiss() {
    setShowWelcome(false)
    saveWelcomeDismissed()
  }

  if (!showWelcome) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-4 py-16 text-center">
        <SarathiMark className="size-8 text-primary" />
        <div>
          <p className="text-sm font-medium">No accounts yet</p>
          <p className="mx-auto mt-1 max-w-xs text-sm text-muted-foreground">
            Open your first account in a 5-minute conversation.
          </p>
        </div>
        <ActionButtons
          loadingDemo={loadingDemo}
          onLoadDemoActivity={onLoadDemoActivity}
          className="justify-center"
        />
        <p className="max-w-xs text-xs text-muted-foreground">
          Demo activity fills your account with 6 months of realistic synthetic transactions so
          you can see every feature working.
        </p>
      </div>
    )
  }

  return (
    <Card className="relative border border-primary/20 bg-accent">
      <CardContent className="flex flex-col gap-3 text-accent-foreground">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Dismiss welcome"
          className="absolute top-2 right-2 text-accent-foreground/70 hover:text-accent-foreground"
          onClick={dismiss}
        >
          <X className="size-3.5" />
        </Button>
        <div className="flex items-center gap-2 pr-8">
          <SarathiMark className="size-5 text-primary" />
          <p className="text-sm font-semibold">Welcome to Sarathi</p>
        </div>
        <p className="text-sm leading-relaxed">
          Sarathi is your agentic banker: open accounts by chatting instead of filling forms,
          get proactive nudges as your money and life change, and see every decision it makes
          laid out plainly, never a black box.
        </p>
        <ActionButtons loadingDemo={loadingDemo} onLoadDemoActivity={onLoadDemoActivity} />
      </CardContent>
    </Card>
  )
}

function ActionButtons({
  loadingDemo,
  onLoadDemoActivity,
  className,
}: {
  loadingDemo: boolean
  onLoadDemoActivity: () => void
  className?: string
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <Button asChild size="sm">
        <Link href="/app/chat">Chat to open an account</Link>
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5"
        disabled={loadingDemo}
        onClick={onLoadDemoActivity}
      >
        <Sparkles className="size-3.5" />
        {loadingDemo ? "Loading…" : "Load demo activity to explore"}
      </Button>
    </div>
  )
}
