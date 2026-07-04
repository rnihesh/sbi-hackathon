import { MessageCircle, Zap } from "lucide-react"

import { Badge } from "@/components/ui/badge"

const ICON = { chat: MessageCircle, event: Zap } as const

export function TriggerChip({ trigger }: { trigger: string }) {
  const Icon = ICON[trigger as keyof typeof ICON]
  return (
    <Badge variant="outline" className="capitalize">
      {Icon && <Icon className="size-3" />}
      {trigger}
    </Badge>
  )
}
