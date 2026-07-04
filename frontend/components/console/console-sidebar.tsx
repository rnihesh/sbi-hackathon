"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"
import { PanelLeftClose, PanelLeftOpen } from "lucide-react"

import { cn } from "@/lib/utils"
import { navPillTransition, springSoft } from "@/lib/motion"
import { Button } from "@/components/ui/button"
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
            <Link
              href={item.href}
              className={cn(
                "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/70 transition-colors hover:text-sidebar-foreground",
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
              <span
                className={cn(
                  "relative z-10 flex items-center gap-3",
                  isActive && "text-sidebar-accent-foreground"
                )}
              >
                <Icon className="size-4 shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </span>
            </Link>
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
          className="text-sidebar-foreground/70"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </Button>
      </div>
    </motion.aside>
  )
}
