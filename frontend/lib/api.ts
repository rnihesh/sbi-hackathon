/**
 * Typed fetch wrapper for the Sarathi backend (FastAPI).
 *
 * All requests go to `NEXT_PUBLIC_API_URL` (default http://localhost:8000) with
 * `credentials: "include"` so httpOnly session cookies flow automatically.
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
export const API_V1 = "/api/v1"

/** Fired on `window` when a session could not be refreshed after a 401 - callers
 * (see `lib/auth.tsx`) listen for this to hard-reset auth state to anonymous. */
export const SESSION_EXPIRED_EVENT = "sarathi:session-expired"

function notifySessionExpired() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  }
}

/** Endpoints that legitimately 401 without an existing session - never worth a
 * refresh+retry round-trip (refresh itself would also 401). */
const NO_AUTH_RETRY_SUFFIXES = [
  "/auth/refresh",
  "/auth/logout",
  "/auth/otp/send",
  "/auth/otp/verify",
  "/auth/passkey/login/begin",
  "/auth/passkey/login/complete",
]

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
  /** Internal: set on the retried request to prevent a refresh-retry loop. */
  skipAuthRetry?: boolean
}

function hasDetail(value: unknown): value is { detail: unknown } {
  return typeof value === "object" && value !== null && "detail" in value
}

let refreshInFlight: Promise<boolean> | null = null

/** Rotates the session via `POST /auth/refresh`, de-duped across concurrent 401s. */
function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = request<{ message: string }>(`${API_V1}/auth/refresh`, {
      method: "POST",
      skipAuthRetry: true,
    })
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers, skipAuthRetry, ...rest } = options

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
    // 403 is included alongside 401: routes behind *optional* auth (chat's
    // session/message endpoints - anonymous prospects are a valid caller)
    // resolve an expired access token to "anonymous" rather than a 401, so an
    // ownership check ("is this your conversation") fails as a 403 instead.
    // Every other 403 in this API sits behind hard-required auth (a 401
    // already fires first for a stale token), so retrying once after a
    // refresh costs at most one harmless extra round trip there.
    if (
      (res.status === 401 || res.status === 403) &&
      !skipAuthRetry &&
      !NO_AUTH_RETRY_SUFFIXES.some((suffix) => path.endsWith(suffix))
    ) {
      const refreshed = await refreshSession()
      if (refreshed) {
        return request<T>(path, { ...options, skipAuthRetry: true })
      }
      notifySessionExpired()
    }

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
  /** Internal: set on the retried connection to prevent a refresh-retry loop. */
  skipAuthRetry?: boolean
  /** Fired once the HTTP stream is actually connected (before the first event
   * arrives) - callers use this to flip a "connecting" indicator to "live"
   * even if the stream stays idle (e.g. a keep-alive-only SSE ping) for a
   * while before the first real event. */
  onOpen?: () => void
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
 * EventSource API - we need POST bodies, custom headers and cookie credentials,
 * none of which EventSource supports).
 */
export async function sseStream(
  path: string,
  onEvent: (event: SseEvent) => void,
  options: SseStreamOptions = {}
): Promise<void> {
  const { method = "POST", body, signal, skipAuthRetry, onOpen } = options

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
    // Chat's ownership check (`_authorize_conversation`) sits behind *optional*
    // auth (anonymous prospects are a valid caller) - an expired access token
    // therefore resolves to "anonymous" rather than a 401, and only then fails
    // the "is this your conversation" check as a 403. So a stale-token retry
    // has to cover 403 here too, not just 401, or a chat session silently stops
    // recovering the moment its 15-minute access token first expires.
    if ((res.status === 401 || res.status === 403) && !skipAuthRetry) {
      const refreshed = await refreshSession()
      if (refreshed) {
        return sseStream(path, onEvent, { ...options, skipAuthRetry: true })
      }
      notifySessionExpired()
    }
    throw new ApiError(`SSE request failed: ${res.statusText}`, res.status, undefined)
  }

  onOpen?.()

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let done = false

  while (!done) {
    const result = await reader.read()
    done = result.done

    if (result.value) {
      // The SSE spec permits "\r\n", "\r", or bare "\n" as the line terminator,
      // and `sse_starlette` (the backend's implementation) defaults to "\r\n" -
      // normalize to "\n" so the "\n\n" event-boundary split below actually
      // matches instead of silently buffering (and eventually discarding)
      // every event of the stream.
      const decoded = decoder
        .decode(result.value, { stream: true })
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n")
      buffer += decoded
      const chunks = buffer.split("\n\n")
      buffer = chunks.pop() ?? ""

      for (const chunk of chunks) {
        const event = parseSseChunk(chunk)
        if (event) onEvent(event)
      }
    }
  }
}
