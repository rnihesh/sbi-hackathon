"use client"

import Link from "next/link"
import { motion } from "framer-motion"
import { ArrowRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { fadeIn } from "@/lib/motion"
import { useMe } from "@/lib/auth"
import { useSignInSheet } from "@/components/auth/sign-in-sheet-context"
import { SarathiMark } from "@/components/brand/logo"
import { HowItWorks } from "@/components/landing/how-it-works"
import { AgentTrio } from "@/components/landing/agent-trio"
import { FeatureGrid } from "@/components/landing/feature-grid"
import { TrustGrid } from "@/components/landing/trust-grid"
import { BankPanel } from "@/components/landing/bank-panel"
import { FinalCta } from "@/components/landing/final-cta"

export default function LandingPage() {
  const { status } = useMe()
  const { setOpen } = useSignInSheet()

  return (
    <>
      <section className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-4 py-20 text-center sm:gap-8 sm:px-6 sm:py-32">
        <motion.div
          initial="initial"
          animate="animate"
          variants={fadeIn}
          className="flex flex-col items-center gap-6 sm:gap-8"
        >
          <SarathiMark className="size-12 text-primary sm:size-14" />

          <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-6xl">
            Sarathi
            <span className="mt-2 block text-2xl font-normal text-muted-foreground sm:text-3xl">
              A banker in every pocket
            </span>
          </h1>

          <p className="max-w-xl text-balance text-sm text-muted-foreground sm:text-base">
            One quiet assistant for every banking moment - onboarding, saving,
            and the life events in between. No queues, no jargon, no waiting.
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
        </motion.div>
      </section>

      <HowItWorks />
      <AgentTrio />
      <FeatureGrid />
      <TrustGrid />
      <BankPanel />
      <FinalCta />
    </>
  )
}
