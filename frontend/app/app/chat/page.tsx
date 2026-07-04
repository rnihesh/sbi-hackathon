"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { PlusCircle } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, sseStream } from "@/lib/api"
import { useMe } from "@/lib/auth"
import { springSnappy } from "@/lib/motion"
import { normalizeStructuredPayload } from "@/lib/chat-types"
import type { ChatMessage, ProductOffer, ToolActivity } from "@/lib/chat-types"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { MessageBubble } from "@/components/chat/message-bubble"
import { ChatComposer } from "@/components/chat/chat-composer"

const CONVERSATION_KEY = "sarathi:conversation_id"

const SUGGESTIONS = [
  "What's my account balance?",
  "Any new offers for me?",
  "Help me open a fixed deposit",
]

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/** Best-effort JSON parse for an SSE `data:` payload — falls back to `null` so
 * callers can defensively fall back to the raw string for schema drift. */
function tryParseJson(raw: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

export default function ChatPage() {
  const { me, refresh } = useMe()

  const [conversationId, setConversationId] = React.useState<string | null>(null)
  const [messages, setMessages] = React.useState<ChatMessage[]>([])
  const [input, setInput] = React.useState("")
  const [isStreaming, setIsStreaming] = React.useState(false)
  const [restoring, setRestoring] = React.useState(true)

  const abortControllerRef = React.useRef<AbortController | null>(null)
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const autoScrollRef = React.useRef(true)
  const meRef = React.useRef(me)
  meRef.current = me

  // Restore a prior conversation from sessionStorage, if any.
  React.useEffect(() => {
    const stored = sessionStorage.getItem(CONVERSATION_KEY)
    if (!stored) {
      setRestoring(false)
      return
    }
    setConversationId(stored)
    api
      .get<{ messages: { role: string; content: string; created_at: string }[] }>(
        `${API_V1}/chat/sessions/${stored}`
      )
      .then((res) => {
        setMessages(
          res.messages
            .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "system")
            .map((m) => ({
              id: newId(),
              role: m.role as ChatMessage["role"],
              content: m.content,
              createdAt: m.created_at,
            }))
        )
      })
      .catch(() => {
        sessionStorage.removeItem(CONVERSATION_KEY)
        setConversationId(null)
      })
      .finally(() => setRestoring(false))
  }, [])

  React.useEffect(() => {
    if (autoScrollRef.current) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    }
  }, [messages])

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  function updateMessage(id: string, patch: Partial<ChatMessage>) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)))
  }

  async function streamAssistantReply(text: string) {
    setIsStreaming(true)
    autoScrollRef.current = true

    const assistantId = newId()
    let assistantContent = ""
    let toolActivity: ToolActivity[] = []
    let structured: ChatMessage["structured"] = []
    let toolCounter = 0
    let placedPlaceholder = false

    const controller = new AbortController()
    abortControllerRef.current = controller

    function ensurePlaceholder() {
      if (placedPlaceholder) return
      placedPlaceholder = true
      setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }])
    }

    function replaceWithError(text: string) {
      setMessages((prev) => {
        const withoutPlaceholder = prev.filter((m) => m.id !== assistantId)
        return [
          ...withoutPlaceholder,
          { id: newId(), role: "system", content: text, isError: true, retryText: text },
        ]
      })
    }

    try {
      let convId = conversationId
      if (!convId) {
        const created = await api.post<{ conversation_id: string }>(
          `${API_V1}/chat/sessions`,
          meRef.current?.customer ? { customer_id: meRef.current.customer.id } : {}
        )
        convId = created.conversation_id
        setConversationId(convId)
        sessionStorage.setItem(CONVERSATION_KEY, convId)
      }

      await sseStream(
        `${API_V1}/chat/sessions/${convId}/messages`,
        (evt) => {
          switch (evt.event) {
            case "tool_start": {
              ensurePlaceholder()
              const data = tryParseJson(evt.data)
              const tool = typeof data?.tool === "string" ? data.tool : undefined
              if (!tool) break
              toolCounter += 1
              toolActivity = [
                ...toolActivity,
                { id: `${assistantId}-tool-${toolCounter}`, tool, status: "running" },
              ]
              updateMessage(assistantId, { toolActivity })
              break
            }
            case "tool_end": {
              const data = tryParseJson(evt.data)
              const tool = typeof data?.tool === "string" ? data.tool : undefined
              if (!tool) break
              const idx = toolActivity.findIndex((t) => t.tool === tool && t.status === "running")
              if (idx !== -1) {
                toolActivity = toolActivity.map((t, i) =>
                  i === idx ? { ...t, status: "done", result: data?.result } : t
                )
                updateMessage(assistantId, { toolActivity })
              }
              break
            }
            case "token": {
              ensurePlaceholder()
              const data = tryParseJson(evt.data)
              const chunk =
                typeof data?.text === "string"
                  ? data.text
                  : typeof data?.token === "string"
                    ? data.token
                    : typeof data?.delta === "string"
                      ? data.delta
                      : typeof data?.content === "string"
                        ? data.content
                        : data === null
                          ? evt.data
                          : ""
              if (chunk) {
                assistantContent += chunk
                updateMessage(assistantId, { content: assistantContent })
              }
              break
            }
            case "structured": {
              ensurePlaceholder()
              const data = tryParseJson(evt.data)
              const payload = normalizeStructuredPayload(data && "data" in data ? data.data : data)
              structured = [...(structured ?? []), payload]
              updateMessage(assistantId, { structured })
              break
            }
            case "done": {
              const data = tryParseJson(evt.data)
              const finalText = typeof data?.final_text === "string" ? data.final_text : undefined
              if (finalText && finalText.trim()) {
                assistantContent = finalText
                ensurePlaceholder()
                updateMessage(assistantId, { content: assistantContent })
              }
              const customerId = typeof data?.customer_id === "string" ? data.customer_id : undefined
              if (customerId && !meRef.current?.customer) {
                toast.success("Account created", {
                  description: "Sarathi set up your customer profile from this chat.",
                })
                void refresh()
              }
              break
            }
            case "error": {
              const data = tryParseJson(evt.data)
              const message =
                (typeof data?.message === "string" && data.message) ||
                (typeof data?.detail === "string" && data.detail) ||
                "Sarathi ran into a problem answering that."
              replaceWithError(message)
              break
            }
            default:
              break
          }
        },
        { method: "POST", body: { text }, signal: controller.signal }
      )
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        replaceWithError(err instanceof ApiError ? err.message : "Connection lost. Please try again.")
      }
    } finally {
      setIsStreaming(false)
      abortControllerRef.current = null
    }
  }

  function handleSend(overrideText?: string) {
    const text = (overrideText ?? input).trim()
    if (!text || isStreaming) return
    setInput("")
    setMessages((prev) => [...prev, { id: newId(), role: "user", content: text }])
    void streamAssistantReply(text)
  }

  function handleRetry(message: ChatMessage) {
    if (!message.retryText) return
    setMessages((prev) => prev.filter((m) => m.id !== message.id))
    void streamAssistantReply(message.retryText)
  }

  function handleStop() {
    abortControllerRef.current?.abort()
  }

  function handleNewConversation() {
    if (isStreaming) abortControllerRef.current?.abort()
    sessionStorage.removeItem(CONVERSATION_KEY)
    setConversationId(null)
    setMessages([])
    setInput("")
  }

  function handleOfferCta(offer: ProductOffer) {
    handleSend(`Tell me more about ${offer.name}`)
  }

  return (
    <div className="mx-auto flex h-dvh max-w-2xl flex-col px-4 py-4 sm:px-6 md:h-auto md:min-h-dvh md:py-6">
      <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Chat</h1>
          <p className="text-sm text-muted-foreground">Ask Sarathi anything about your money.</p>
        </div>
        {(messages.length > 0 || conversationId) && (
          <Button variant="ghost" size="sm" className="gap-1.5" onClick={handleNewConversation}>
            <PlusCircle className="size-3.5" />
            New
          </Button>
        )}
      </div>

      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto py-2">
        {restoring ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-16 w-2/3 self-start rounded-2xl rounded-bl-sm" />
            <Skeleton className="h-10 w-1/2 self-end rounded-2xl rounded-br-sm" />
            <Skeleton className="h-20 w-3/4 self-start rounded-2xl rounded-bl-sm" />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-center">
            <p className="text-sm text-muted-foreground">
              Ask about your balance, a new deposit, or anything on your mind — Sarathi will
              walk you through it.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => handleSend(suggestion)}
                  className="rounded-full border border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <AnimatePresence initial={false}>
              {messages.map((message) => (
                <motion.div
                  key={message.id}
                  layout="position"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={springSnappy}
                >
                  <MessageBubble
                    message={message}
                    onRetry={message.retryText ? () => handleRetry(message) : undefined}
                    onOfferCta={handleOfferCta}
                  />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>

      <div className="shrink-0 pt-2">
        <ChatComposer
          value={input}
          onChange={setInput}
          onSend={() => handleSend()}
          onStop={handleStop}
          isStreaming={isStreaming}
        />
      </div>
    </div>
  )
}
