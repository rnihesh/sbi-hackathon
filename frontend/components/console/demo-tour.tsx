"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowUpRight, Check, ExternalLink, Presentation, RotateCcw } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  DEMO_TOUR_STEPS,
  loadTourProgress,
  saveTourProgress,
} from "@/lib/demo-tour"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"

const STEP_COUNT = DEMO_TOUR_STEPS.length

/**
 * Presenter-facing checklist of the 8-step jury flow. Pure frontend: each step
 * carries a "say this" line and a deep link to the surface. Ticked steps are
 * persisted to localStorage so the run survives a reload mid-demo. Console
 * links navigate in place (and close the sheet); customer app / landing links
 * open in a new tab so the console stays where it is.
 */
export function DemoTour() {
  const [open, setOpen] = React.useState(false)
  const [checked, setChecked] = React.useState<boolean[]>(() =>
    new Array<boolean>(STEP_COUNT).fill(false)
  )

  React.useEffect(() => {
    setChecked(loadTourProgress(STEP_COUNT))
  }, [])

  const persist = React.useCallback((next: boolean[]) => {
    setChecked(next)
    saveTourProgress(next)
  }, [])

  function toggle(index: number) {
    persist(checked.map((v, i) => (i === index ? !v : v)))
  }

  function reset() {
    persist(new Array<boolean>(STEP_COUNT).fill(false))
  }

  const doneCount = checked.filter(Boolean).length
  const allDone = doneCount === STEP_COUNT
  const progress = Math.round((doneCount / STEP_COUNT) * 100)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Demo tour">
          <Presentation className="size-4" />
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b border-border p-4">
          <SheetTitle className="flex items-center gap-2">
            <Presentation className="size-4 text-primary" />
            Demo tour
          </SheetTitle>
          <SheetDescription>
            The 8-step jury flow, about 5 minutes. Tick each step as you go.
          </SheetDescription>
          <div className="mt-3 flex items-center gap-3">
            <div
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuenow={doneCount}
              aria-valuemin={0}
              aria-valuemax={STEP_COUNT}
              aria-label="Demo tour progress"
            >
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {allDone ? "All done" : `${doneCount} of ${STEP_COUNT}`}
            </span>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Reset tour progress"
              onClick={reset}
              disabled={doneCount === 0}
            >
              <RotateCcw />
            </Button>
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <ol className="flex flex-col gap-2 p-4">
            {DEMO_TOUR_STEPS.map((step, index) => {
              const done = checked[index]
              return (
                <li
                  key={step.n}
                  className={cn(
                    "rounded-xl border border-border/70 bg-card p-3 transition-colors",
                    done && "bg-muted/40"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <button
                      type="button"
                      onClick={() => toggle(index)}
                      aria-pressed={done}
                      aria-label={
                        done
                          ? `Mark step ${step.n} not done`
                          : `Mark step ${step.n} done`
                      }
                      className={cn(
                        "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-medium tabular-nums transition-[background-color,border-color,transform] duration-150 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:border-primary/60 active:scale-90 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                        done &&
                          "border-primary bg-primary text-primary-foreground"
                      )}
                    >
                      {done ? <Check className="size-3.5" /> : step.n}
                    </button>
                    <div className="min-w-0 flex-1">
                      <p
                        className={cn(
                          "text-sm font-medium",
                          done && "text-muted-foreground line-through"
                        )}
                      >
                        {step.title}
                      </p>
                      <p className="mt-1 border-l-2 border-border pl-2.5 text-xs leading-relaxed text-muted-foreground">
                        <span className="mr-1 font-medium text-foreground/70">
                          Say:
                        </span>
                        {step.say}
                      </p>
                      <DeepLink
                        href={step.href}
                        target={step.target}
                        external={step.external}
                        onNavigate={() => setOpen(false)}
                      />
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}

function DeepLink({
  href,
  target,
  external,
  onNavigate,
}: {
  href: string
  target: string
  external: boolean
  onNavigate: () => void
}) {
  const className =
    "mt-2 inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"

  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={className}
      >
        {target}
        <ExternalLink className="size-3 text-muted-foreground" />
      </a>
    )
  }

  return (
    <Link href={href} onClick={onNavigate} className={className}>
      {target}
      <ArrowUpRight className="size-3 text-muted-foreground" />
    </Link>
  )
}
