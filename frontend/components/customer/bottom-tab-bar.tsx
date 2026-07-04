"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"

import { cn } from "@/lib/utils"
import { navPillTransition } from "@/lib/motion"
import { CUSTOMER_TABS } from "@/components/customer/tabs"

export function BottomTabBar() {
  const pathname = usePathname()

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur supports-[backdrop-filter]:bg-background/80 md:hidden"
      aria-label="Primary"
    >
      <ul className="mx-auto flex max-w-md items-stretch justify-around px-2">
        {CUSTOMER_TABS.map((tab) => {
          const isActive = pathname === tab.href
          const Icon = tab.icon
          return (
            <li key={tab.href} className="flex-1">
              <Link
                href={tab.href}
                className="relative flex flex-col items-center justify-center gap-0.5 py-2.5 text-[11px] font-medium text-muted-foreground transition-transform duration-150 ease-[cubic-bezier(0.34,1.56,0.64,1)] active:scale-90 active:duration-100"
                aria-current={isActive ? "page" : undefined}
              >
                {isActive && (
                  <motion.span
                    layoutId="bottom-tab-pill"
                    className="absolute inset-1 rounded-xl bg-accent"
                    transition={navPillTransition}
                  />
                )}
                <span
                  className={cn(
                    "relative z-10 flex flex-col items-center gap-0.5 transition-colors duration-150",
                    isActive && "text-accent-foreground"
                  )}
                >
                  <Icon
                    className={cn(
                      "size-5 transition-transform duration-200",
                      isActive && "scale-110"
                    )}
                  />
                  {tab.label}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
