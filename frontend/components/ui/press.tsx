"use client"

import * as React from "react"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/*
  Press: a reusable tactile wrapper.

  On pointer-down the element visibly moves DOWN and compresses
  (translate-y + scale + inset shadow). On release it springs back UP and
  overshoots slightly before settling. Pure CSS: the release transition uses
  an easeOutBack curve (cubic-bezier(0.34, 1.56, 0.64, 1)) so the transform
  overshoots on the way back to rest; the downstroke is shorter and snappier.
  No JS timers, no dependencies.

  Use `asChild` to render the press behaviour onto an existing element such
  as a Next.js <Link>.
*/

const pressBase = cn(
  "will-change-transform",
  "transition-[transform,box-shadow,color,background-color] duration-150 ease-[cubic-bezier(0.34,1.56,0.64,1)]",
  "active:translate-y-[1.5px] active:scale-[0.97] active:duration-100 active:ease-[cubic-bezier(0.4,0,1,1)]",
  "active:shadow-[inset_0_1px_2px_rgba(28,25,23,0.16)]",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
)

export interface PressProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Render the press behaviour onto the single child element instead. */
  asChild?: boolean
}

export const Press = React.forwardRef<HTMLButtonElement, PressProps>(
  ({ asChild = false, className, type, ...props }, ref) => {
    const Comp = asChild ? Slot.Root : "button"
    return (
      <Comp
        ref={ref as React.Ref<HTMLButtonElement>}
        {...(asChild ? {} : { type: type ?? "button" })}
        className={cn(pressBase, className)}
        {...props}
      />
    )
  }
)
Press.displayName = "Press"
