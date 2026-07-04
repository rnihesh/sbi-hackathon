/** Wire types for the `/me/notifications` customer endpoints. */

export type NotificationKind = "offer" | "life_event" | "account" | "nudge" | "system"

export interface AppNotification {
  id: string
  kind: NotificationKind
  title: string
  body: string
  /** App-relative path (e.g. `/app/nudges`) to open on click, if any. */
  link: string | null
  read: boolean
  created_at: string
}

export interface NotificationListResponse {
  notifications: AppNotification[]
  unread: number
}

export interface NotificationReadResponse {
  marked: number
  unread: number
}

/** Notifications whose home is the Nudges tab (drive that tab's badge). */
export function isNudgeRelated(n: AppNotification): boolean {
  return n.kind === "nudge" || n.kind === "offer" || n.link === "/app/nudges"
}
