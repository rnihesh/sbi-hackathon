import * as React from "react"

import { ConsoleShell } from "./console-shell"

// Auth-gated, per-user console: render dynamically instead of prerendering to
// static HTML at build time. The inner shell reads live user context (useMe) on
// the client, so there is nothing meaningful to bake in. This config must live
// in a server component (route segment config is ignored in "use client" files).
export const dynamic = "force-dynamic"

export default function ConsoleLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return <ConsoleShell>{children}</ConsoleShell>
}
