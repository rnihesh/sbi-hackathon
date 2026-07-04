"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"
import { PanelLeftClose, PanelLeftOpen } from "lucide-react"

import { cn } from "@/lib/utils"
import { navPillTransition, springSoft } from "@/lib/motion"
import { Button } from "@/components/ui/button"
import { Press } from "@/components/ui/press"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { CONSOLE_NAV_ITEMS } from "@/components/console/nav-items"

export function ConsoleSidebar() {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = React.useState(false)

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 232 }}
      transition={springSoft}
      className="sticky top-0 hidden h-dvh shrink-0 flex-col overflow-hidden border-r border-sidebar-border bg-sidebar py-4 md:flex"
    >
      <div className={cn("mb-6 flex items-center gap-2 px-4", collapsed && "justify-center px-0")}>
        <span className="size-2 shrink-0 rounded-full bg-primary" aria-hidden />
        {!collapsed && (
          <span className="truncate text-sm font-semibold tracking-tight text-sidebar-foreground">
            Sarathi Console
          </span>
        )}
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-2" aria-label="Console">
        {CONSOLE_NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href)
          const Icon = item.icon
          const link = (
            <Press asChild>
              <Link
                href={item.href}
                className={cn(
                  "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
                  isActive
                    ? "text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/70 hover:-translate-y-px hover:bg-secondary/70 hover:text-sidebar-foreground",
                  collapsed && "justify-center px-0"
                )}
                aria-current={isActive ? "page" : undefined}
              >
                {isActive && (
                  <motion.span
                    layoutId="console-nav-pill"
                    className="absolute inset-0 rounded-lg bg-sidebar-accent"
                    transition={navPillTransition}
                  />
                )}
                {/* Clay rail: slides in on the active route. */}
                <span
                  className={cn(
                    "absolute -left-2 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary transition-opacity duration-200",
                    isActive ? "opacity-100" : "opacity-0"
                  )}
                  aria-hidden
                />
                <span className="relative z-10 flex items-center gap-3">
                  <Icon
                    className={cn(
                      "size-4 shrink-0 transition-transform duration-200",
                      !isActive && "group-hover:scale-110"
                    )}
                  />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </span>
              </Link>
            </Press>
          )

          if (!collapsed) {
            return <React.Fragment key={item.href}>{link}</React.Fragment>
          }

          return (
            <Tooltip key={item.href}>
              <TooltipTrigger asChild>{link}</TooltipTrigger>
              <TooltipContent side="right">{item.label}</TooltipContent>
            </Tooltip>
          )
        })}
      </nav>

      <div className={cn("px-2", collapsed && "flex justify-center px-0")}>
        <Button
          variant="ghost"
          size="icon"
          className="text-sidebar-foreground/70 transition-transform hover:scale-105 active:scale-95"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </Button>
      </div>
    </motion.aside>
  )
}
