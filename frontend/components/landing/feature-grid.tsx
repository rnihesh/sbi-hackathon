import {
  BrainCircuit,
  CalendarClock,
  Handshake,
  Languages,
  LineChart,
  MessageCircle,
  Radar,
  Target,
  type LucideIcon,
} from "lucide-react"

import { SectionHeading } from "@/components/landing/section-heading"
import { Reveal, RevealGroup, RevealItem } from "@/components/landing/reveal"
import { Card, CardContent } from "@/components/ui/card"

const FEATURES: ReadonlyArray<{ icon: LucideIcon; title: string; description: string }> = [
  {
    icon: MessageCircle,
    title: "Conversational onboarding",
    description: "Open an account by talking. KYC happens through dialogue, gated in code.",
  },
  {
    icon: Languages,
    title: "Vernacular chat",
    description: "Hindi, Hinglish, Telugu, Tamil, Kannada, Bengali, Marathi, or auto-detect.",
  },
  {
    icon: Radar,
    title: "Life-event detection",
    description: "Job changes, new children, home intent: read from transaction patterns.",
  },
  {
    icon: Target,
    title: "Savings goals",
    description: "Name a goal, set an amount, and watch real balance growth close the gap.",
  },
  {
    icon: LineChart,
    title: "Spending insights",
    description: "Category breakdowns, movers, and recurring merchants from real activity.",
  },
  {
    icon: CalendarClock,
    title: "Proactive reviews",
    description: "Sarathi checks in on a schedule too, not only when you chat or something happens.",
  },
  {
    icon: Handshake,
    title: "Human handoff",
    description: "Ask for a person, and your request lands directly in a staff queue.",
  },
  {
    icon: BrainCircuit,
    title: "Memory you control",
    description: "See exactly what Sarathi remembers, and forget any of it, any time.",
  },
]

export function FeatureGrid() {
  return (
    <section className="border-t border-border/70">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading eyebrow="The everyday work" title="What Sarathi does" />
        </Reveal>

        <RevealGroup className="mt-12 grid grid-cols-1 gap-4 sm:mt-16 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, description }) => (
            <RevealItem key={title}>
              <Card
                size="sm"
                className="h-full transition-transform duration-200 ease-out hover:-translate-y-0.5 hover:ring-primary/25"
              >
                <CardContent className="flex h-full flex-col gap-3">
                  <span className="inline-flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-4.5" aria-hidden />
                  </span>
                  <p className="font-heading text-sm font-medium">{title}</p>
                  <p className="text-sm text-muted-foreground">{description}</p>
                </CardContent>
              </Card>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  )
}
