import {
  Database,
  Fingerprint,
  Gauge,
  ScrollText,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react"

import { SectionHeading } from "@/components/landing/section-heading"
import { Reveal, RevealGroup, RevealItem } from "@/components/landing/reveal"

const TRUST_POINTS: ReadonlyArray<{ icon: LucideIcon; title: string; description: string }> = [
  {
    icon: ShieldCheck,
    title: "Human approval",
    description: "Every offer or outreach waits for a staff approval before it reaches you.",
  },
  {
    icon: Fingerprint,
    title: "PII redaction",
    description: "Phone, PAN, and Aadhaar patterns are stripped before any model sees them.",
  },
  {
    icon: ScrollText,
    title: "Audit trail",
    description: "Every agent action writes an immutable, hash-chained record.",
  },
  {
    icon: Gauge,
    title: "Budget-governed",
    description: "A daily spend ceiling protects the pipeline; chat itself is never blocked.",
  },
  {
    icon: Database,
    title: "Synthetic data",
    description: "The demo runs on a simulated India. No real customer data, anywhere.",
  },
]

export function TrustGrid() {
  return (
    <section className="border-t border-border/70">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading eyebrow="Trust, not a promise" title="Built for trust" />
        </Reveal>

        <RevealGroup className="mt-12 grid grid-cols-1 gap-x-8 gap-y-8 sm:mt-16 sm:grid-cols-2 lg:grid-cols-5">
          {TRUST_POINTS.map(({ icon: Icon, title, description }) => (
            <RevealItem key={title} className="flex flex-col items-start gap-2.5">
              <Icon className="size-5 text-foreground/60" aria-hidden />
              <p className="font-heading text-sm font-medium">{title}</p>
              <p className="text-sm text-muted-foreground">{description}</p>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  )
}
