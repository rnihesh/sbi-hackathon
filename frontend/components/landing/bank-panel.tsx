import { Radar, ScrollText, Target, type LucideIcon } from "lucide-react"

import { SectionHeading } from "@/components/landing/section-heading"
import { Reveal, RevealGroup, RevealItem } from "@/components/landing/reveal"
import { Card } from "@/components/ui/card"

const CONSOLE_NOTES: ReadonlyArray<{ icon: LucideIcon; title: string; description: string }> = [
  {
    icon: ScrollText,
    title: "Glass-box traces",
    description: "Every run: node, tool, model, tokens, cost, and latency, per step.",
  },
  {
    icon: Target,
    title: "Detection scorecard",
    description: "Life-event detection scored against ground truth, precision and recall.",
  },
  {
    icon: Radar,
    title: "Churn cockpit",
    description: "At-risk customers surfaced early, with one-click re-engagement.",
  },
]

export function BankPanel() {
  return (
    <section className="border-t border-border/70">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="Behind the counter"
            title="For the bank"
            description="Every customer-facing agent has a staff-facing mirror. Your staff stay in command, never in the dark."
          />
        </Reveal>

        <Reveal className="mt-10 sm:mt-12">
          <Card className="mx-auto max-w-4xl overflow-hidden p-0">
            <RevealGroup className="grid grid-cols-1 divide-y divide-border/70 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              {CONSOLE_NOTES.map(({ icon: Icon, title, description }) => (
                <RevealItem key={title} className="flex flex-col gap-2.5 p-6">
                  <Icon className="size-5 text-foreground/60" aria-hidden />
                  <p className="font-heading text-sm font-medium">{title}</p>
                  <p className="text-sm text-muted-foreground">{description}</p>
                </RevealItem>
              ))}
            </RevealGroup>
          </Card>
        </Reveal>
      </div>
    </section>
  )
}
