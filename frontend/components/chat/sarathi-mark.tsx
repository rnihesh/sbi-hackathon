import { Sparkles } from "lucide-react"

import { cn } from "@/lib/utils"

export function SarathiMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground",
        className
      )}
      aria-hidden
    >
      <Sparkles className="size-3.5" />
    </div>
  )
}
