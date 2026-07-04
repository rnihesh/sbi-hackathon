"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { useMe } from "@/lib/auth"
import { useConsoleAccess } from "@/lib/use-console-access"
import { ConsoleSidebar } from "@/components/console/console-sidebar"
import { ConsoleTopbar } from "@/components/console/console-topbar"
import { StaffRequiredPanel } from "@/components/console/staff-required-panel"
import { Skeleton } from "@/components/ui/skeleton"

export default function ConsoleLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const { status } = useMe()
  const router = useRouter()
  const access = useConsoleAccess(status === "authenticated")

  React.useEffect(() => {
    if (status === "anonymous") router.replace("/?signin=1")
  }, [status, router])

  const isLoading = status === "loading" || (status === "authenticated" && access === "loading")

  return (
    <div className="flex min-h-dvh">
      <ConsoleSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <ConsoleTopbar />
        <main className="flex-1 px-4 py-6 sm:px-6">
          {isLoading ? (
            <div className="mx-auto flex max-w-4xl flex-col gap-3">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-40 w-full rounded-xl" />
              <Skeleton className="h-40 w-full rounded-xl" />
            </div>
          ) : status === "authenticated" && access === "granted" ? (
            children
          ) : status === "authenticated" && access === "forbidden" ? (
            <StaffRequiredPanel />
          ) : null /* anonymous — redirect effect above is firing */}
        </main>
      </div>
    </div>
  )
}
