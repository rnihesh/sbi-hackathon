"use client"

import { AnimatePresence, motion } from "framer-motion"
import { Check, Loader2 } from "lucide-react"

import { cn } from "@/lib/utils"
import { springSnappy } from "@/lib/motion"
import { humanizeToolActivity } from "@/lib/format"
import type { ToolActivity } from "@/lib/chat-types"

export function ToolActivityChip({ activity }: { activity: ToolActivity }) {
  const done = activity.status === "done"

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/60 px-2.5 py-1 text-xs text-muted-foreground transition-colors",
        done && "text-foreground/70"
      )}
    >
      <span className="relative flex size-3 items-center justify-center">
        <AnimatePresence mode="wait" initial={false}>
          {done ? (
            <motion.span
              key="done"
              initial={{ opacity: 0, scale: 0.5 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={springSnappy}
              className="absolute inset-0 flex items-center justify-center"
            >
              <Check className="size-3 text-primary" />
            </motion.span>
          ) : (
            <motion.span
              key="running"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 flex items-center justify-center"
            >
              <Loader2 className="size-3 animate-spin" />
            </motion.span>
          )}
        </AnimatePresence>
      </span>
      {humanizeToolActivity(activity.tool)}
    </span>
  )
}
