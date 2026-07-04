"use client"

import * as React from "react"
import { useTheme } from "next-themes"
import { AnimatePresence, motion } from "framer-motion"
import { Moon, Sun } from "lucide-react"

import { Button } from "@/components/ui/button"
import { springSnappy } from "@/lib/motion"

export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = React.useState(false)

  React.useEffect(() => setMounted(true), [])

  const isDark = mounted && resolvedTheme === "dark"

  return (
    <Button
      variant="ghost"
      size="icon"
      className={className}
      aria-label="Toggle theme"
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      <span className="relative flex size-4 items-center justify-center overflow-hidden">
        <AnimatePresence mode="wait" initial={false}>
          {mounted ? (
            <motion.span
              key={isDark ? "moon" : "sun"}
              initial={{ opacity: 0, rotate: -90, scale: 0.6 }}
              animate={{ opacity: 1, rotate: 0, scale: 1 }}
              exit={{ opacity: 0, rotate: 90, scale: 0.6 }}
              transition={springSnappy}
              className="absolute inset-0 flex items-center justify-center"
            >
              {isDark ? <Moon className="size-4" /> : <Sun className="size-4" />}
            </motion.span>
          ) : (
            <Sun className="size-4 opacity-0" />
          )}
        </AnimatePresence>
      </span>
    </Button>
  )
}
