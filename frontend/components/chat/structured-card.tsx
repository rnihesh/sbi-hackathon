"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { Check } from "lucide-react"

import { cn } from "@/lib/utils"
import { pressable } from "@/lib/motion"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { ProductOffer, StructuredPayload, WalkthroughStep } from "@/lib/chat-types"

function ProductOfferCard({ offer, onCta }: { offer: ProductOffer; onCta?: (offer: ProductOffer) => void }) {
  return (
    <Card size="sm" className="border-border/80">
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <span className="font-medium text-sm">{offer.name}</span>
          {offer.category && (
            <Badge variant="secondary" className="shrink-0 capitalize">
              {offer.category.replace(/_/g, " ")}
            </Badge>
          )}
        </div>
        {offer.reason && <p className="text-sm text-muted-foreground">{offer.reason}</p>}
        {onCta && (
          <motion.div {...pressable} className="self-start">
            <Button size="sm" variant="outline" onClick={() => onCta(offer)}>
              {offer.cta ?? "Tell me more"}
            </Button>
          </motion.div>
        )}
      </CardContent>
    </Card>
  )
}

function WalkthroughCard({ title, steps }: { title?: string; steps: WalkthroughStep[] }) {
  const [checked, setChecked] = React.useState<boolean[]>(() => steps.map(() => false))

  function toggle(index: number) {
    setChecked((prev) => prev.map((v, i) => (i === index ? !v : v)))
  }

  return (
    <Card size="sm" className="border-border/80">
      <CardContent className="flex flex-col gap-2">
        {title && <p className="text-sm font-medium">{title}</p>}
        <ol className="flex flex-col gap-1.5">
          {steps.map((step, index) => {
            const done = checked[index]
            return (
              <li key={index}>
                <button
                  type="button"
                  onClick={() => toggle(index)}
                  className="flex w-full items-start gap-2.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-muted/60"
                >
                  <span
                    className={cn(
                      "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-border text-[11px] font-medium tabular-nums transition-colors",
                      done && "border-primary bg-primary text-primary-foreground"
                    )}
                  >
                    {done ? <Check className="size-3" /> : index + 1}
                  </span>
                  <span className="flex flex-col">
                    <span className={cn("text-sm", done && "text-muted-foreground line-through")}>
                      {step.title}
                    </span>
                    {step.description && (
                      <span className="text-xs text-muted-foreground">{step.description}</span>
                    )}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      </CardContent>
    </Card>
  )
}

export function StructuredCard({
  payload,
  onOfferCta,
}: {
  payload: StructuredPayload
  onOfferCta?: (offer: ProductOffer) => void
}) {
  if (payload.kind === "product_offers") {
    return (
      <div className="flex flex-col gap-2">
        {payload.offers.map((offer, index) => (
          <ProductOfferCard key={`${offer.name}-${index}`} offer={offer} onCta={onOfferCta} />
        ))}
      </div>
    )
  }

  if (payload.kind === "walkthrough") {
    return <WalkthroughCard title={payload.title} steps={payload.steps} />
  }

  return (
    <Card size="sm" className="border-border/80">
      <CardContent>
        <pre className="overflow-x-auto text-xs text-muted-foreground">
          {JSON.stringify(payload.raw, null, 2)}
        </pre>
      </CardContent>
    </Card>
  )
}
