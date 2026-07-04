"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"

import { cn } from "@/lib/utils"
import { navPillTransition } from "@/lib/motion"
import { CUSTOMER_TABS } from "@/components/customer/tabs"

export function AppSidebar() {
  const pathname = usePathname()

  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-6 md:flex">
      <Link href="/" className="mb-8 flex items-center gap-2 px-2">
        <span className="size-2 rounded-full bg-primary" aria-hidden />
        <span className="text-sm font-semibold tracking-tight text-sidebar-foreground">
          Sarathi
        </span>
      </Link>

      <nav className="flex flex-1 flex-col gap-1" aria-label="Primary">
        {CUSTOMER_TABS.map((tab) => {
          const isActive = pathname === tab.href
          const Icon = tab.icon
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className="relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/70 transition-colors hover:text-sidebar-foreground"
              aria-current={isActive ? "page" : undefined}
            >
              {isActive && (
                <motion.span
                  layoutId="app-sidebar-pill"
                  className="absolute inset-0 rounded-lg bg-sidebar-accent"
                  transition={navPillTransition}
                />
              )}
              <span
                className={cn(
                  "relative z-10 flex items-center gap-3",
                  isActive && "text-sidebar-accent-foreground"
                )}
              >
                <Icon className="size-4" />
                {tab.label}
              </span>
            </Link>
          )
        })}
      </nav>
    </aside>
  )
}
