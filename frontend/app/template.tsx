"use client"

import { motion } from "framer-motion"

import { pageVariants } from "@/lib/motion"

export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial="initial"
      animate="animate"
      exit="exit"
      variants={pageVariants}
    >
      {children}
    </motion.div>
  )
}
