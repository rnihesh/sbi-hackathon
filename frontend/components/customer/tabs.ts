import { Bell, Home, MessageCircle, User, type LucideIcon } from "lucide-react"

export interface CustomerTab {
  href: string
  label: string
  icon: LucideIcon
}

export const CUSTOMER_TABS: CustomerTab[] = [
  { href: "/app/chat", label: "Chat", icon: MessageCircle },
  { href: "/app/home", label: "Home", icon: Home },
  { href: "/app/nudges", label: "Nudges", icon: Bell },
  { href: "/app/profile", label: "Profile", icon: User },
]
