"use client"

import * as React from "react"
import { ArrowUp, Square } from "lucide-react"

import { Button } from "@/components/ui/button"

export function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
}: {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  isStreaming: boolean
}) {
  const textareaRef = React.useRef<HTMLTextAreaElement>(null)

  React.useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !isStreaming) onSend()
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      {isStreaming && (
        <div className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
          <span className="flex gap-0.5" aria-hidden>
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="size-1 animate-bounce rounded-full bg-muted-foreground/70 motion-reduce:animate-none"
                style={{ animationDelay: `${i * 120}ms` }}
              />
            ))}
          </span>
          Sarathi is thinking…
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border border-input bg-background p-1.5 shadow-sm focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
        <textarea
          ref={textareaRef}
          id="chat-composer-input"
          name="message"
          aria-label="Message"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          rows={1}
          placeholder="Ask Sarathi anything about your money…"
          className="max-h-[200px] min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
        />
        {isStreaming ? (
          <Button size="icon" variant="destructive" onClick={onStop} aria-label="Stop generating">
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button size="icon" onClick={onSend} disabled={!value.trim()} aria-label="Send message">
            <ArrowUp />
          </Button>
        )}
      </div>
    </div>
  )
}
