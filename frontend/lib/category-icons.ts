import {
  ArrowRightLeft,
  Banknote,
  Car,
  Clapperboard,
  Fuel,
  GraduationCap,
  HeartPulse,
  Home,
  Landmark,
  Plane,
  Receipt,
  Repeat,
  Shield,
  ShoppingBag,
  ShoppingCart,
  TrendingUp,
  UtensilsCrossed,
  Wallet,
  Zap,
  type LucideIcon,
} from "lucide-react"

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  groceries: ShoppingCart,
  food: UtensilsCrossed,
  dining: UtensilsCrossed,
  transport: Car,
  travel: Plane,
  entertainment: Clapperboard,
  utilities: Zap,
  rent: Home,
  housing: Home,
  salary: Wallet,
  income: Wallet,
  shopping: ShoppingBag,
  healthcare: HeartPulse,
  medical: HeartPulse,
  transfer: ArrowRightLeft,
  atm: Banknote,
  cash: Banknote,
  fuel: Fuel,
  subscription: Repeat,
  education: GraduationCap,
  insurance: Shield,
  investment: TrendingUp,
  emi: Landmark,
  loan: Landmark,
}

/** Maps a transaction/spend category string to a Lucide icon, falling back to a
 * generic receipt for anything not in the map (new sim categories, typos). */
export function categoryIcon(category: string | null | undefined): LucideIcon {
  if (!category) return Receipt
  return CATEGORY_ICONS[category.toLowerCase().replace(/\s+/g, "_")] ?? Receipt
}
