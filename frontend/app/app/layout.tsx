import * as React from "react"

import { AppShell } from "./app-shell"

// Auth-gated, per-user customer app: render dynamically instead of prerendering
// to static HTML at build time. The inner shell reads live user context (useMe)
// on the client, so there is nothing meaningful to bake in. This config must
// live in a server component (route segment config is ignored in "use client").
export const dynamic = "force-dynamic"

export default function CustomerAppLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return <AppShell>{children}</AppShell>
}
