import * as React from "react"
import type { Metadata } from "next"

import { AppShell } from "./app-shell"

// Auth-gated, per-user customer app: render dynamically instead of prerendering
// to static HTML at build time. The inner shell reads live user context (useMe)
// on the client, so there is nothing meaningful to bake in. This config must
// live in a server component (route segment config is ignored in "use client").
export const dynamic = "force-dynamic"

// `absolute` skips the root layout's "%s · Sarathi" template - "Sarathi · Sarathi"
// would be a redundant tab title for the app's own top-level segment.
export const metadata: Metadata = {
  title: { absolute: "Sarathi" },
}

export default function CustomerAppLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return <AppShell>{children}</AppShell>
}
