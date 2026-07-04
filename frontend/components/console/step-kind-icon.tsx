import { Bot, ShieldCheck, Wrench, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

const KIND_ICON: Record<string, LucideIcon> = {
  llm: Bot,
  tool: Wrench,
  guardrail: ShieldCheck,
}

const KIND_STYLE: Record<string, string> = {
  llm: "bg-accent text-accent-foreground",
  tool: "bg-muted text-muted-foreground",
  guardrail: "bg-secondary text-secondary-foreground",
}

export function StepKindIcon({ kind, className }: { kind: string; className?: string }) {
  const Icon = KIND_ICON[kind] ?? Bot
  return (
    <div
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full",
        KIND_STYLE[kind] ?? "bg-muted text-muted-foreground",
        className
      )}
    >
      <Icon className="size-3.5" />
    </div>
  )
}
