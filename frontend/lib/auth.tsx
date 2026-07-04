"use client"

/**
 * Auth state for the whole app: a single `GET /me` fetch on mount, exposed via
 * `useMe()`. Login flows (OTP verify, passkey login) already get a `MeResponse`
 * back from their own endpoint — they call `setMe()` directly instead of waiting
 * on a refetch. A 401 that survives the `lib/api.ts` refresh-retry dispatches
 * `SESSION_EXPIRED_EVENT`, which this provider listens for to hard-reset to
 * anonymous (e.g. logout in another tab, or a revoked refresh token).
 */

import * as React from "react"

import { api, API_V1, ApiError, SESSION_EXPIRED_EVENT } from "@/lib/api"

export interface UserOut {
  id: string
  email: string
  created_at: string
}

export interface CustomerOut {
  id: string
  full_name: string
  email: string | null
  phone: string | null
  city: string | null
  state: string | null
  segment: string | null
  digital_maturity: string
}

export interface MeResponse {
  user: UserOut
  customer: CustomerOut | null
}

export type AuthStatus = "loading" | "authenticated" | "anonymous"

interface AuthContextValue {
  me: MeResponse | null
  status: AuthStatus
  /** Hydrate auth state directly from a login endpoint's response — avoids an
   * extra round trip to `/me` right after signing in. */
  setMe: (me: MeResponse) => void
  /** Re-fetch `/me` (e.g. after chat onboarding creates a customer for an
   * anonymous session). */
  refresh: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = React.createContext<AuthContextValue | null>(null)

async function fetchMe(): Promise<MeResponse | null> {
  try {
    return await api.get<MeResponse>(`${API_V1}/me`)
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null
    // Backend not reachable yet (e.g. not started) — degrade to anonymous rather
    // than hanging the app in a loading state forever.
    console.warn("me_fetch_failed", err)
    return null
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMeState] = React.useState<MeResponse | null>(null)
  const [status, setStatus] = React.useState<AuthStatus>("loading")

  const refresh = React.useCallback(async () => {
    const next = await fetchMe()
    setMeState(next)
    setStatus(next ? "authenticated" : "anonymous")
  }, [])

  React.useEffect(() => {
    refresh()
  }, [refresh])

  React.useEffect(() => {
    function onSessionExpired() {
      setMeState(null)
      setStatus("anonymous")
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
  }, [])

  const setMe = React.useCallback((next: MeResponse) => {
    setMeState(next)
    setStatus("authenticated")
  }, [])

  const logout = React.useCallback(async () => {
    try {
      await api.post(`${API_V1}/auth/logout`)
    } catch {
      // Logout is idempotent server-side; clear local state regardless.
    }
    setMeState(null)
    setStatus("anonymous")
  }, [])

  const value = React.useMemo<AuthContextValue>(
    () => ({ me, status, setMe, refresh, logout }),
    [me, status, setMe, refresh, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useMe(): AuthContextValue {
  const ctx = React.useContext(AuthContext)
  if (!ctx) throw new Error("useMe must be used within an AuthProvider")
  return ctx
}
