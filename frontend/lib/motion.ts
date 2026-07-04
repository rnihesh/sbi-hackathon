/**
 * Shared framer-motion primitives for Sarathi's signature micro-interactions.
 * Keep these subtle — motion should read as "quiet confidence", never gimmicky.
 */
import type { Transition, Variants } from "framer-motion"

/** Snappy spring for small, immediate feedback (nav pills, toggles). */
export const springSnappy: Transition = {
  type: "spring",
  stiffness: 500,
  damping: 32,
  mass: 0.6,
}

/** Softer spring for larger surface movement (sheets, panels). */
export const springSoft: Transition = {
  type: "spring",
  stiffness: 260,
  damping: 28,
}

/** Fast, quiet fade/slide for route transitions (150-200ms). */
export const pageTransition: Transition = {
  duration: 0.18,
  ease: [0.4, 0, 0.2, 1],
}

export const pageVariants: Variants = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0, transition: pageTransition },
  exit: { opacity: 0, y: -6, transition: { ...pageTransition, duration: 0.12 } },
}

/** Active nav-item pill — pair with `layoutId` on the element that should morph. */
export const navPillTransition: Transition = springSnappy

export const fadeIn: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.2 } },
}

export const scaleIn: Variants = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1, transition: springSnappy },
}

/** Shared "press" affordance for interactive, non-button surfaces (cards, nav items). */
export const pressable = {
  whileTap: { scale: 0.98 },
  transition: springSnappy,
}

/** Parent container for a staggered list reveal — pair with `staggerItem` on
 * each child and `initial="initial" animate="animate"` on both. */
export const staggerContainer: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.06 } },
}

export const staggerItem: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: springSnappy },
}
