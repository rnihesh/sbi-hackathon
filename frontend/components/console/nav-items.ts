import {
  Activity,
  ClipboardCheck,
  Users,
  Filter,
  BarChart3,
  UserMinus,
  Sparkles,
  Waypoints,
  Wallet,
  type LucideIcon,
} from "lucide-react"

export interface ConsoleNavItem {
  href: string
  label: string
  icon: LucideIcon
}

export const CONSOLE_NAV_ITEMS: ConsoleNavItem[] = [
  { href: "/console/feed", label: "Live Feed", icon: Activity },
  { href: "/console/approvals", label: "Approvals", icon: ClipboardCheck },
  { href: "/console/leads", label: "Leads", icon: Users },
  { href: "/console/funnels", label: "Funnels", icon: Filter },
  { href: "/console/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/console/churn", label: "Churn", icon: UserMinus },
  { href: "/console/life-events", label: "Life Events", icon: Sparkles },
  { href: "/console/traces", label: "Traces", icon: Waypoints },
  { href: "/console/costs", label: "Costs", icon: Wallet },
]
