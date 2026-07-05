"use client"

/**
 * Scroll-reveal primitives for the landing page. Built on the same quiet
 * spring/fade language as `lib/motion.ts` (no new easing curves invented) -
 * these just trigger on scroll into view instead of on mount, and only once,
 * so revisiting a section on the way back up does not replay the animation.
 */
import * as React from "react"
import { motion, useReducedMotion, type Variants } from "framer-motion"

import { staggerContainer, staggerItem } from "@/lib/motion"

const VIEWPORT = { once: true, margin: "-80px 0px" } as const

type RevealProps = React.ComponentProps<typeof motion.div> & {
  variants?: Variants
}

/** Standalone fade + rise-in for a single element (section headings, panels). */
export function Reveal({ variants = staggerItem, children, ...props }: RevealProps) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.div
      initial={reduceMotion ? false : "initial"}
      whileInView="animate"
      viewport={VIEWPORT}
      variants={variants}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/** Parent for a staggered group reveal - pair each direct visual child with `RevealItem`. */
export function RevealGroup({ children, ...props }: RevealProps) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.div
      initial={reduceMotion ? false : "initial"}
      whileInView="animate"
      viewport={VIEWPORT}
      variants={staggerContainer}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/** A single staggered child inside `RevealGroup`. */
export function RevealItem({ variants = staggerItem, children, ...props }: RevealProps) {
  return (
    <motion.div variants={variants} {...props}>
      {children}
    </motion.div>
  )
}
