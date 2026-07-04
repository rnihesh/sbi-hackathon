"use client"

import * as React from "react"

import { api, API_V1, ApiError } from "@/lib/api"

export type ConsoleAccess = "loading" | "granted" | "forbidden"

/**
 * Probes a lightweight console endpoint to determine whether the signed-in user
 * is staff. The backend has no `is_staff` field on `/me` - `get_current_staff`
 * gates individual console routes instead - so this is the only way to know
 * before rendering the console shell.
 *
 * Only an explicit `403` is treated as forbidden. Any other failure (network
 * error, 404 because a route isn't deployed yet, 5xx) resolves to "granted" so
 * the console pages can render their own honest loading/error/empty state
 * instead of blocking the whole section on an unrelated outage.
 */
export function useConsoleAccess(enabled: boolean): ConsoleAccess {
  const [access, setAccess] = React.useState<ConsoleAccess>("loading")

  React.useEffect(() => {
    if (!enabled) return
    let cancelled = false

    api
      .get(`${API_V1}/console/leads`)
      .then(() => {
        if (!cancelled) setAccess("granted")
      })
      .catch((err) => {
        if (cancelled) return
        setAccess(err instanceof ApiError && err.status === 403 ? "forbidden" : "granted")
      })

    return () => {
      cancelled = true
    }
  }, [enabled])

  return access
}
