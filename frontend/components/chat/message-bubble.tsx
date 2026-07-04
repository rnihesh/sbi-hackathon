"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { AlertCircle, RotateCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { SarathiMark } from "@/components/brand/logo"
import { ToolActivityChip } from "@/components/chat/tool-activity-chip"
import { StructuredCard } from "@/components/chat/structured-card"
import type { ChatMessage, ProductOffer } from "@/lib/chat-types"

export function MessageBubble({
  message,
  onRetry,
  onOfferCta,
}: {
  message: ChatMessage
  onRetry?: () => void
  onOfferCta?: (offer: ProductOffer) => void
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary/10 px-4 py-2.5 text-sm whitespace-pre-wrap text-foreground sm:max-w-[75%]">
          {message.content}
        </div>
      </div>
    )
  }

  if (message.isError) {
    return (
      <div className="flex justify-start">
        <div className="flex max-w-[85%] flex-col gap-2 rounded-2xl rounded-bl-sm border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-sm text-destructive sm:max-w-[75%]">
          <p>{message.content}</p>
          {onRetry && (
            <Button
              size="sm"
              variant="outline"
              className="w-fit gap-1.5 border-destructive/40 text-destructive hover:bg-destructive/10"
              onClick={onRetry}
            >
              <RotateCw className="size-3.5" />
              Retry
            </Button>
          )}
        </div>
      </div>
    )
  }

  const hasContent = message.content.trim().length > 0
  const hasToolActivity = (message.toolActivity?.length ?? 0) > 0
  const hasStructured = (message.structured?.length ?? 0) > 0
  const hasStreamError = Boolean(message.streamError)

  if (!hasContent && !hasToolActivity && !hasStructured && !hasStreamError) return null

  return (
    <div className="flex items-start gap-2">
      <SarathiMark className="mt-1 text-primary" />
      <div className="flex min-w-0 max-w-[85%] flex-col gap-2 sm:max-w-[75%]">
        {hasToolActivity && (
          <div className="flex flex-wrap gap-1.5">
            {message.toolActivity!.map((activity) => (
              <ToolActivityChip key={activity.id} activity={activity} />
            ))}
          </div>
        )}
        {hasContent && (
          <div className="min-w-0 rounded-2xl rounded-bl-sm bg-muted/60 px-4 py-2.5 text-sm break-words">
            <div className="prose-sarathi prose prose-sm max-w-none dark:prose-invert">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
                  // GFM tables can be wider than the chat bubble - scroll the
                  // table itself instead of blowing out the layout.
                  table: ({ ...props }) => (
                    <div className="overflow-x-auto rounded-lg border border-border">
                      <table {...props} />
                    </div>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          </div>
        )}
        {message.structured?.map((payload, index) => (
          <StructuredCard key={index} payload={payload} onOfferCta={onOfferCta} />
        ))}
        {hasStreamError && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
            <AlertCircle className="size-3.5 shrink-0" />
            <span className="flex-1">{message.streamError}</span>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="inline-flex items-center gap-1 font-medium underline-offset-2 hover:underline"
              >
                <RotateCw className="size-3" />
                Retry
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
