import { ChevronRight } from "lucide-react"

import { SectionHeading } from "@/components/landing/section-heading"
import { Reveal, RevealGroup, RevealItem } from "@/components/landing/reveal"

const AGENTS = [
  {
    index: "01",
    name: "Acquisition",
    description: "Turns a conversation into a funded account: KYC by dialogue, not forms.",
  },
  {
    index: "02",
    name: "Adoption",
    description: "Notices the products you already have sitting idle and nudges you to use them.",
  },
  {
    index: "03",
    name: "Engagement",
    description: "Reads the moments that matter, job changes and milestones alike, and proposes what helps next.",
  },
] as const

export function AgentTrio() {
  return (
    <section className="border-t border-border/70">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="Supervised by Sarathi Core"
            title="Three agents, one relationship"
            description="One customer, one memory, one thread of accountability, handed off between three specialists as the relationship moves forward."
          />
        </Reveal>

        <RevealGroup className="mt-12 flex flex-col items-stretch gap-6 sm:mt-16 sm:flex-row sm:items-start sm:gap-4">
          {AGENTS.map((agent, i) => (
            <div key={agent.name} className="flex flex-1 items-start gap-4 sm:items-stretch">
              <RevealItem className="flex flex-1 flex-col gap-2 rounded-xl p-2">
                <span className="font-mono text-sm text-primary">{agent.index}</span>
                <p className="font-heading text-base font-medium">{agent.name}</p>
                <p className="text-sm text-muted-foreground">{agent.description}</p>
              </RevealItem>

              {i < AGENTS.length - 1 ? (
                <ChevronRight
                  aria-hidden
                  className="mt-3 hidden size-4 shrink-0 text-muted-foreground/40 sm:block"
                />
              ) : null}
            </div>
          ))}
        </RevealGroup>
      </div>
    </section>
  )
}
