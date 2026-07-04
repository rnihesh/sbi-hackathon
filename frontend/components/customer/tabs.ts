import { Bell, Home, MessageCircle, Package, User, type LucideIcon } from "lucide-react"

export interface CustomerTab {
  href: string
  label: string
  icon: LucideIcon
}

export const CUSTOMER_TABS: CustomerTab[] = [
  { href: "/app/chat", label: "Chat", icon: MessageCircle },
  { href: "/app/home", label: "Home", icon: Home },
  { href: "/app/products", label: "Products", icon: Package },
  { href: "/app/nudges", label: "Nudges", icon: Bell },
  { href: "/app/profile", label: "Profile", icon: User },
]

/** Page title for the mobile top bar's center slot, derived from the current
 * pathname - `null` for anything outside the five tabs (so the bar falls
 * back to just showing the wordmark). */
export function pageTitleForPath(pathname: string): string | null {
  const tab = CUSTOMER_TABS.find(
    (t) => pathname === t.href || pathname.startsWith(`${t.href}/`)
  )
  return tab?.label ?? null
}
