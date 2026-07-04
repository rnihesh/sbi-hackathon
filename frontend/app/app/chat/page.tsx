"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { History, PlusCircle } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, sseStream } from "@/lib/api"
import { useMe } from "@/lib/auth"
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
import { ChatHistoryList } from "@/components/chat/chat-history"
import type { ChatSessionSummary } from "@/components/chat/chat-history"
import { SarathiMark } from "@/components/brand/logo"

const CONVERSATION_KEY = "sarathi:conversation_id"
const DRAFT_PREFIX = "sarathi:draft:"

function draftKey(id: string | null): string {
  return `${DRAFT_PREFIX}${id ?? "new"}`
}

function loadDraft(id: string | null): string {
  try {
    return sessionStorage.getItem(draftKey(id)) ?? ""
  } catch {
    return ""
  }
}

function saveDraft(id: string | null, text: string): void {
  try {
    if (text) sessionStorage.setItem(draftKey(id), text)
    else sessionStorage.removeItem(draftKey(id))
  } catch {
    // sessionStorage unavailable (private mode / SSR) - drafts are best-effort.
  }
}

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
      setInput(loadDraft(null))
      setRestoring(false)
      return
    }
    setConversationId(stored)
    setInput(loadDraft(stored))
    autoScrollRef.current = true
    api
      .get<{ messages: { role: string; content: string; created_at: string }[] }>(
        `${API_V1}/chat/sessions/${stored}`
      )
      .then((res) => {
        autoScrollRef.current = true
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
        // Backend no longer has this thread (404 / not-yours) - drop the stale
        // pointer and its draft, and fall back to a fresh composer.
        sessionStorage.removeItem(CONVERSATION_KEY)
        saveDraft(stored, "")
        setConversationId(null)
        setInput(loadDraft(null))
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

    // Hoisted out of the `try` below so the `catch` can still target the
    // right conversation's draft key on failure (a brand-new conversation's
    // id is only known once the POST to create it resolves).
    let convId = conversationId

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
              // If tokens already streamed, keep the partial reply visible and
              // attach an inline error notice instead of nuking everything.
              if (assistantContent.trim()) {
                updateMessage(assistantId, { streamError: message, retryText: text })
              } else {
                replaceWithError(message)
              }
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
        const message =
          err instanceof ApiError ? err.message : "Connection lost. Please try again."
        if (assistantContent.trim() && placedPlaceholder) {
          updateMessage(assistantId, { streamError: message, retryText: text })
        } else {
          replaceWithError(message)
        }
        // Rate-limited: the message never actually sent, so put it back in the
        // composer (and persist it as the draft) instead of only relying on
        // the error bubble's Retry button - nothing typed should feel lost.
        if (err instanceof ApiError && err.status === 429) {
          setInput(text)
          saveDraft(convId, text)
        }
      }
    } finally {
      setIsStreaming(false)
      abortControllerRef.current = null
    }
  }

  function handleInputChange(value: string) {
    setInput(value)
    saveDraft(conversationId, value)
  }

  function handleSend(overrideText?: string) {
    const text = (overrideText ?? input).trim()
    if (!text || isStreaming) return
    setInput("")
    saveDraft(conversationId, "")
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

  /** Return the UI to a clean, unbound "New conversation" state (shared by the
   * New button and by deleting the currently-open thread). */
  function resetToFresh() {
    if (isStreaming) abortControllerRef.current?.abort()
    sessionStorage.removeItem(CONVERSATION_KEY)
    setConversationId(null)
    setMessages([])
    autoScrollRef.current = true
    setInput(loadDraft(null))
  }

  function handleNewConversation() {
    resetToFresh()
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
    setInput(loadDraft(session.conversation_id))
    // Opening an old thread should jump straight to the latest turn, not
    // smooth-scroll up through its whole history.
    autoScrollRef.current = true
    try {
      const res = await api.get<{
        messages: { role: string; content: string; created_at: string }[]
      }>(`${API_V1}/chat/sessions/${session.conversation_id}`)
      autoScrollRef.current = true
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

  async function handleRenameSession(id: string, title: string) {
    const prev = sessions
    setSessions((s) => s?.map((x) => (x.conversation_id === id ? { ...x, title } : x)) ?? s)
    try {
      await api.patch(`${API_V1}/chat/sessions/${id}`, { title })
    } catch {
      setSessions(prev) // rollback optimistic rename
      toast.error("Couldn't rename conversation")
    }
  }

  async function handleDeleteSession(id: string) {
    const prev = sessions
    setSessions((s) => s?.filter((x) => x.conversation_id !== id) ?? s)
    try {
      await api.delete(`${API_V1}/chat/sessions/${id}`)
      saveDraft(id, "")
      if (id === conversationId) resetToFresh()
    } catch {
      setSessions(prev) // rollback optimistic removal
      toast.error("Couldn't delete conversation")
      throw new Error("delete-failed") // keep the confirm dialog open for retry
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
                <div className="overflow-y-auto px-2 pb-4">
                  <ChatHistoryList
                    sessions={sessions}
                    activeId={conversationId}
                    onOpen={(session) => void handleOpenConversation(session)}
                    onRename={handleRenameSession}
                    onDelete={handleDeleteSession}
                  />
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
          onChange={handleInputChange}
          onSend={() => handleSend()}
          onStop={handleStop}
          isStreaming={isStreaming}
        />
      </div>
    </div>
  )
}
