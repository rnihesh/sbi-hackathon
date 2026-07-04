"use client"

/**
 * Notification inbox state for the customer app: one polled `GET
 * /me/notifications` shared by the bell (sidebar + mobile top bar) and the
 * Nudges tab badge. Polls every 30s and refetches on window focus - simple and
 * robust, no SSE. Only runs while authenticated so anonymous sessions never
 * spam 401s.
 */

import * as React from "react"

import { api, API_V1 } from "@/lib/api"
import { useMe } from "@/lib/auth"
import {
  isNudgeRelated,
  type AppNotification,
  type NotificationListResponse,
  type NotificationReadResponse,
} from "@/lib/notification-types"

const POLL_MS = 30_000
const LIMIT = 30

interface NotificationsContextValue {
  notifications: AppNotification[]
  unread: number
  /** Unread count for notifications that belong to the Nudges tab. */
  nudgeUnread: number
  loading: boolean
  refetch: () => Promise<void>
  markRead: (ids: string[]) => Promise<void>
  markAllRead: () => Promise<void>
}

const NotificationsContext = React.createContext<NotificationsContextValue | null>(null)

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const { status } = useMe()
  const authed = status === "authenticated"

  const [notifications, setNotifications] = React.useState<AppNotification[]>([])
  const [loading, setLoading] = React.useState(true)

  const refetch = React.useCallback(async () => {
    if (!authed) return
    try {
      const res = await api.get<NotificationListResponse>(
        `${API_V1}/me/notifications?limit=${LIMIT}`
      )
      setNotifications(res.notifications)
    } catch {
      // Transient failure - the next poll (or focus) retries. Keep the last
      // good list rather than flashing an empty inbox.
    } finally {
      setLoading(false)
    }
  }, [authed])

  // Reset + fetch when auth flips; poll on an interval while authenticated.
  React.useEffect(() => {
    if (!authed) {
      setNotifications([])
      setLoading(false)
      return
    }
    setLoading(true)
    void refetch()
    const interval = setInterval(() => void refetch(), POLL_MS)
    return () => clearInterval(interval)
  }, [authed, refetch])

  // Refetch when the tab regains focus/visibility (catches events that landed
  // while the app was backgrounded, without waiting out the poll interval).
  React.useEffect(() => {
    if (!authed) return
    const onFocus = () => void refetch()
    const onVisible = () => {
      if (document.visibilityState === "visible") void refetch()
    }
    window.addEventListener("focus", onFocus)
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      window.removeEventListener("focus", onFocus)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [authed, refetch])

  const markRead = React.useCallback(async (ids: string[]) => {
    if (ids.length === 0) return
    const idSet = new Set(ids)
    setNotifications((prev) =>
      prev.map((n) => (idSet.has(n.id) && !n.read ? { ...n, read: true } : n))
    )
    try {
      await api.post<NotificationReadResponse>(`${API_V1}/me/notifications/read`, { ids })
    } catch {
      // Optimistic update stands; a later refetch reconciles if the write lost.
    }
  }, [])

  const markAllRead = React.useCallback(async () => {
    setNotifications((prev) =>
      prev.some((n) => !n.read) ? prev.map((n) => ({ ...n, read: true })) : prev
    )
    try {
      await api.post<NotificationReadResponse>(`${API_V1}/me/notifications/read`, { all: true })
    } catch {
      // See markRead.
    }
  }, [])

  const value = React.useMemo<NotificationsContextValue>(() => {
    const unread = notifications.reduce((acc, n) => acc + (n.read ? 0 : 1), 0)
    const nudgeUnread = notifications.reduce(
      (acc, n) => acc + (!n.read && isNudgeRelated(n) ? 1 : 0),
      0
    )
    return { notifications, unread, nudgeUnread, loading, refetch, markRead, markAllRead }
  }, [notifications, loading, refetch, markRead, markAllRead])

  return (
    <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
  )
}

export function useNotifications(): NotificationsContextValue {
  const ctx = React.useContext(NotificationsContext)
  if (!ctx) throw new Error("useNotifications must be used within a NotificationsProvider")
  return ctx
}
