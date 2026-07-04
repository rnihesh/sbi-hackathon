"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { History, MessageSquare, PlusCircle } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, sseStream } from "@/lib/api"
import { useMe } from "@/lib/auth"
import { formatRelativeTime, pluralize } from "@/lib/format"
import { springSnappy } from "@/lib/motion"
import { normalizeStructuredPayload } from "@/lib/chat-types"
import type { ChatMessage, ProductOffer, ToolActivity } from "@/lib/chat-types"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { MessageBubble } from "@/components/chat/message-bubble"
import { ChatComposer } from "@/components/chat/chat-composer"
import { SarathiMark } from "@/components/brand/logo"

interface ChatSessionSummary {
  conversation_id: string
  title: string
  message_count: number
  updated_at: string
}

const CONVERSATION_KEY = "sarathi:conversation_id"

const SUGGESTIONS = [
  "Open a savings account",
  "What can I invest in?",
  "Show me how to set up UPI",
  "What's my account balance?",
]

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/** Best-effort JSON parse for an SSE `data:` payload - falls back to `null` so
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
  const [historyOpen, setHistoryOpen] = React.useState(false)
  const [sessions, setSessions] = React.useState<ChatSessionSummary[] | null>(null)

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

  async function openHistory(open: boolean) {
    setHistoryOpen(open)
    if (!open) return
    try {
      const res = await api.get<{ sessions: ChatSessionSummary[] }>(`${API_V1}/chat/sessions`)
      setSessions(res.sessions)
    } catch {
      setSessions([])
    }
  }

  async function handleOpenConversation(session: ChatSessionSummary) {
    if (isStreaming) abortControllerRef.current?.abort()
    setHistoryOpen(false)
    if (session.conversation_id === conversationId) return
    setRestoring(true)
    setConversationId(session.conversation_id)
    sessionStorage.setItem(CONVERSATION_KEY, session.conversation_id)
    try {
      const res = await api.get<{
        messages: { role: string; content: string; created_at: string }[]
      }>(`${API_V1}/chat/sessions/${session.conversation_id}`)
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
    } catch {
      toast.error("Couldn't load that conversation")
    } finally {
      setRestoring(false)
    }
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
        <div className="flex items-center gap-1">
          {me?.customer && (
            <Sheet open={historyOpen} onOpenChange={(open) => void openHistory(open)}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-1.5">
                  <History className="size-3.5" />
                  History
                </Button>
              </SheetTrigger>
              <SheetContent side="right" className="w-80 sm:w-96">
                <SheetHeader>
                  <SheetTitle>Conversations</SheetTitle>
                </SheetHeader>
                <div className="flex flex-col gap-1 overflow-y-auto px-2 pb-4">
                  {sessions === null ? (
                    <div className="flex flex-col gap-2 px-2 pt-2">
                      <Skeleton className="h-12 w-full rounded-lg" />
                      <Skeleton className="h-12 w-full rounded-lg" />
                      <Skeleton className="h-12 w-full rounded-lg" />
                    </div>
                  ) : sessions.length === 0 ? (
                    <p className="px-2 pt-2 text-sm text-muted-foreground">
                      No conversations yet. Start one and it will show up here.
                    </p>
                  ) : (
                    sessions.map((session) => (
                      <button
                        key={session.conversation_id}
                        onClick={() => void handleOpenConversation(session)}
                        className={
                          "flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-muted " +
                          (session.conversation_id === conversationId ? "bg-muted" : "")
                        }
                      >
                        <MessageSquare className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">
                            {session.title}
                          </span>
                          <span className="block text-xs text-muted-foreground">
                            {formatRelativeTime(session.updated_at)} ·{" "}
                            {pluralize(session.message_count, "message")}
                          </span>
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </SheetContent>
            </Sheet>
          )}
          {(messages.length > 0 || conversationId) && (
            <Button variant="ghost" size="sm" className="gap-1.5" onClick={handleNewConversation}>
              <PlusCircle className="size-3.5" />
              New
            </Button>
          )}
        </div>
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
            <SarathiMark className="size-8 text-primary" />
            <p className="max-w-xs text-sm text-muted-foreground">
              I&apos;m Sarathi, your banker. Open an account, explore products, or ask anything.
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
