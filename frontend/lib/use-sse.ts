"use client"

import * as React from "react"

import { sseStream } from "@/lib/api"

export type SseConnectionStatus = "connecting" | "open" | "reconnecting" | "closed"

const MAX_BACKOFF_MS = 30_000
const MAX_ITEMS = 200

/**
 * Subscribes to a JSON-per-event SSE endpoint (GET), reconnecting with capped
 * exponential backoff whenever the stream ends - whether from a clean server
 * close or a network error. Pause via `enabled: false` (e.g. tab hidden) to
 * cut the connection without losing accumulated items.
 */
export function useSse<T>(path: string, options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true
  const [items, setItems] = React.useState<T[]>([])
  const [status, setStatus] = React.useState<SseConnectionStatus>("connecting")

  React.useEffect(() => {
    if (!enabled) {
      setStatus("closed")
      return
    }

    let cancelled = false
    let attempt = 0
    let controller: AbortController | null = null
    let retryTimeout: ReturnType<typeof setTimeout> | null = null

    async function connect() {
      if (cancelled) return
      setStatus(attempt === 0 ? "connecting" : "reconnecting")
      controller = new AbortController()

      try {
        await sseStream(
          path,
          (event) => {
            if (cancelled) return
            setStatus("open")
            attempt = 0
            try {
              const parsed = JSON.parse(event.data) as T
              // Append (not prepend) - the feed reads oldest-to-newest, top-to-
              // bottom, like a log tail, so the page can auto-scroll down.
              setItems((prev) => [...prev, parsed].slice(-MAX_ITEMS))
            } catch {
              // Malformed payload - drop the event rather than crash the feed.
            }
          },
          { method: "GET", signal: controller.signal }
        )
      } catch {
        // Connection error - fall through to the reconnect scheduling below.
      }

      if (cancelled) return
      attempt += 1
      const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (attempt - 1))
      setStatus("reconnecting")
      retryTimeout = setTimeout(connect, delay)
    }

    connect()

    return () => {
      cancelled = true
      controller?.abort()
      if (retryTimeout) clearTimeout(retryTimeout)
    }
  }, [path, enabled])

  return { items, status }
}
