/**
 * Typed fetch wrapper for the Sarathi backend (FastAPI).
 *
 * All requests go to `NEXT_PUBLIC_API_URL` (default http://localhost:8000) with
 * `credentials: "include"` so httpOnly session cookies flow automatically.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

type JsonBody = Record<string, unknown> | unknown[]

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: JsonBody
}

function hasDetail(value: unknown): value is { detail: unknown } {
  return typeof value === "object" && value !== null && "detail" in value
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers, ...rest } = options

  const res = await fetch(`${API_URL}${path}`, {
    ...rest,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  const contentType = res.headers.get("content-type") ?? ""
  const payload: unknown = contentType.includes("application/json")
    ? await res.json().catch(() => undefined)
    : await res.text().catch(() => undefined)

  if (!res.ok) {
    const message = hasDetail(payload) ? String(payload.detail) : res.statusText
    throw new ApiError(message, res.status, payload)
  }

  return payload as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: JsonBody, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: JsonBody, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(path: string, body?: JsonBody, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
}

export interface SseEvent {
  event: string
  data: string
  id?: string
}

interface SseStreamOptions {
  method?: "GET" | "POST"
  body?: JsonBody
  signal?: AbortSignal
}

function parseSseChunk(chunk: string): SseEvent | null {
  const lines = chunk.split("\n").filter((line) => line.length > 0)
  if (lines.length === 0) return null

  let event = "message"
  let id: string | undefined
  const dataLines: string[] = []

  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim())
    else if (line.startsWith("id:")) id = line.slice(3).trim()
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join("\n"), id }
}

/**
 * Consumes a `text/event-stream` endpoint via fetch + ReadableStream (not the
 * EventSource API — we need POST bodies, custom headers and cookie credentials,
 * none of which EventSource supports).
 */
export async function sseStream(
  path: string,
  onEvent: (event: SseEvent) => void,
  options: SseStreamOptions = {}
): Promise<void> {
  const { method = "POST", body, signal } = options

  const res = await fetch(`${API_URL}${path}`, {
    method,
    credentials: "include",
    signal,
    headers: {
      Accept: "text/event-stream",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!res.ok || !res.body) {
    throw new ApiError(`SSE request failed: ${res.statusText}`, res.status, undefined)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let done = false

  while (!done) {
    const result = await reader.read()
    done = result.done

    if (result.value) {
      buffer += decoder.decode(result.value, { stream: true })
      const chunks = buffer.split("\n\n")
      buffer = chunks.pop() ?? ""

      for (const chunk of chunks) {
        const event = parseSseChunk(chunk)
        if (event) onEvent(event)
      }
    }
  }
}
