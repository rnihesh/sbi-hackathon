import { Reveal, RevealGroup, RevealItem } from "@/components/landing/reveal"

const STEPS = [
  {
    title: "Chat to open an account",
    description: "Tell Sarathi what you need - it handles KYC and setup in one conversation.",
  },
  {
    title: "Sarathi watches for what you need",
    description: "It notices life events and moments that matter, quietly, in the background.",
  },
  {
    title: "You approve, it acts",
    description: "Every suggestion is yours to accept - nothing happens without your say-so.",
  },
] as const

export function HowItWorks() {
  return (
    <section className="border-t border-border/70">
      <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <Reveal>
          <p className="text-center font-mono text-xs tracking-wide text-primary uppercase">
            How it works
          </p>
        </Reveal>

        <RevealGroup className="mt-8 grid gap-8 sm:grid-cols-3">
          {STEPS.map((step, index) => (
            <RevealItem key={step.title} className="flex flex-col gap-1.5">
              <span className="font-mono text-sm text-primary">
                {String(index + 1).padStart(2, "0")}
              </span>
              <p className="text-sm font-medium">{step.title}</p>
              <p className="text-sm text-muted-foreground">{step.description}</p>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  )
}
