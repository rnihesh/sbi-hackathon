"use client"

import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Reveal } from "@/components/landing/reveal"
import { useMe } from "@/lib/auth"
import { useSignInSheet } from "@/components/auth/sign-in-sheet-context"

export function FinalCta() {
  const { status } = useMe()
  const { setOpen } = useSignInSheet()

  return (
    <section className="border-t border-border/70">
      <div className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-4 py-20 text-center sm:py-28">
        <Reveal className="flex flex-col items-center gap-6">
          <h2 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
            One conversation away from a banker of your own
          </h2>
          <p className="max-w-md text-sm text-balance text-muted-foreground sm:text-base">
            No forms, no branch visit, no queue. Just tell Sarathi what you need.
          </p>

          {status === "authenticated" ? (
            <Button size="lg" asChild className="px-6">
              <Link href="/app/home">
                Open an account in 5 minutes
                <ArrowRight data-icon="inline-end" />
              </Link>
            </Button>
          ) : (
            <Button size="lg" className="px-6" onClick={() => setOpen(true)}>
              Open an account in 5 minutes
              <ArrowRight data-icon="inline-end" />
            </Button>
          )}
        </Reveal>
      </div>
    </section>
  )
}
