"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { X } from "lucide-react"

import { springSoft } from "@/lib/motion"
import { formatRelativeTime } from "@/lib/format"
import { ctaLabel } from "@/lib/customer-types"
import type { Nudge } from "@/lib/customer-types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

export function NudgeCard({
  nudge,
  onSeen,
  onAct,
  onDismiss,
  busy,
}: {
  nudge: Nudge
  onSeen: (id: string) => void
  onAct: (nudge: Nudge) => void
  onDismiss: (id: string) => void
  busy: boolean
}) {
  const ref = React.useRef<HTMLDivElement>(null)
  const seenRef = React.useRef(false)

  React.useEffect(() => {
    const el = ref.current
    if (!el || nudge.status !== "sent") return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !seenRef.current) {
            seenRef.current = true
            onSeen(nudge.id)
          }
        }
      },
      { threshold: 0.6 }
    )
    observer.observe(el)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nudge.id, nudge.status])

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 40, transition: { duration: 0.16 } }}
      transition={springSoft}
    >
      <Card>
        <CardContent className="flex items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="text-sm font-medium">{nudge.title}</p>
            <p className="text-sm text-muted-foreground">{nudge.body}</p>
            <div className="flex items-center gap-2 pt-1">
              <Button size="sm" disabled={busy} onClick={() => onAct(nudge)}>
                {ctaLabel(nudge)}
              </Button>
              <span className="text-xs text-muted-foreground">
                {formatRelativeTime(nudge.created_at)}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Dismiss"
            disabled={busy}
            onClick={() => onDismiss(nudge.id)}
          >
            <X className="size-3.5" />
          </Button>
        </CardContent>
      </Card>
    </motion.div>
  )
}
