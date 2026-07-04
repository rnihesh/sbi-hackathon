"use client"

import * as React from "react"
import Link from "next/link"
import { motion } from "framer-motion"
import { Check } from "lucide-react"

import { cn } from "@/lib/utils"
import { pressable } from "@/lib/motion"
import {
  loadWalkthroughProgress,
  saveWalkthroughProgress,
  walkthroughStorageKey,
} from "@/lib/walkthrough-storage"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { SarathiMark } from "@/components/brand/logo"
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
        {offer.reasons.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {offer.reasons.map((reason, i) => (
              <li key={i} className="text-sm text-muted-foreground">
                {reason}
              </li>
            ))}
          </ul>
        )}
        {onCta && (
          <motion.div {...pressable} className="self-start">
            <Button size="sm" variant="outline" onClick={() => onCta(offer)}>
              Tell me more
            </Button>
          </motion.div>
        )}
      </CardContent>
    </Card>
  )
}

function WalkthroughCard({
  title,
  steps,
  conversationId,
}: {
  title?: string
  steps: WalkthroughStep[]
  /** Chat thread this walkthrough belongs to - part of the localStorage key
   * so the same walkthrough in a different conversation tracks separately.
   * `null`/`undefined` (not-yet-created draft thread) falls back to "draft". */
  conversationId?: string | null
}) {
  // Stable even when untitled: falls back to the steps' own titles so two
  // different untitled walkthroughs in one conversation don't share a key.
  const topic = title ?? steps.map((s) => s.title).join(" ")
  const storageKey = React.useMemo(
    () => walkthroughStorageKey(conversationId, topic),
    [conversationId, topic]
  )

  const [checked, setChecked] = React.useState<boolean[]>(() =>
    loadWalkthroughProgress(storageKey, steps.length)
  )

  // Re-sync from storage if this card is now tracking a different
  // walkthrough (key changed) rather than just re-rendering the same one.
  React.useEffect(() => {
    setChecked(loadWalkthroughProgress(storageKey, steps.length))
  }, [storageKey, steps.length])

  React.useEffect(() => {
    saveWalkthroughProgress(storageKey, checked)
  }, [storageKey, checked])

  function toggle(index: number) {
    setChecked((prev) => prev.map((v, i) => (i === index ? !v : v)))
  }

  const doneCount = checked.filter(Boolean).length
  const allDone = steps.length > 0 && doneCount === steps.length

  return (
    <Card size="sm" className="border-border/80">
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          {title ? (
            <p className="text-sm font-medium">{title}</p>
          ) : (
            <span />
          )}
          {allDone ? (
            <Badge className="gap-1 shrink-0">
              <SarathiMark className="size-3" />
              Done!
            </Badge>
          ) : (
            steps.length > 0 && (
              <span className="shrink-0 text-xs text-muted-foreground">
                {doneCount} of {steps.length} done
              </span>
            )
          )}
        </div>
        <ol className="flex flex-col gap-1.5">
          {steps.map((step, index) => {
            const done = checked[index]
            return (
              <li key={index}>
                <button
                  type="button"
                  onClick={() => toggle(index)}
                  aria-pressed={done}
                  className="flex w-full items-start gap-2.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                    <span className={cn("text-sm", done && "text-muted-foreground")}>
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
  conversationId,
}: {
  payload: StructuredPayload
  onOfferCta?: (offer: ProductOffer) => void
  /** Threaded through to `WalkthroughCard` for its localStorage key - unused
   * by the other card kinds. */
  conversationId?: string | null
}) {
  if (payload.kind === "product_offers") {
    return (
      <div className="flex flex-col gap-2">
        {payload.offers.map((offer, index) => (
          <ProductOfferCard key={`${offer.name}-${index}`} offer={offer} onCta={onOfferCta} />
        ))}
        <Link
          href="/app/products"
          className="self-start text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
        >
          See all products
        </Link>
      </div>
    )
  }

  if (payload.kind === "walkthrough") {
    return (
      <WalkthroughCard title={payload.title} steps={payload.steps} conversationId={conversationId} />
    )
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
