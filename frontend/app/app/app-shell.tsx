"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { useMe } from "@/lib/auth"
import { NotificationsProvider } from "@/lib/notifications"
import { AppSidebar } from "@/components/customer/app-sidebar"
import { BottomTabBar } from "@/components/customer/bottom-tab-bar"
import { MobileTopBar } from "@/components/customer/mobile-top-bar"
import { Skeleton } from "@/components/ui/skeleton"

export function AppShell({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const { status } = useMe()
  const router = useRouter()

  React.useEffect(() => {
    if (status === "anonymous") router.replace("/?signin=1")
  }, [status, router])

  return (
    <NotificationsProvider>
      <div className="flex min-h-dvh">
        <AppSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <MobileTopBar />
          <main className="min-w-0 flex-1 pb-20 md:pb-0">
            {status === "authenticated" ? (
              children
            ) : status === "loading" ? (
              <div className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-6 sm:px-6">
                <Skeleton className="h-6 w-40" />
                <Skeleton className="h-32 w-full rounded-xl" />
                <Skeleton className="h-32 w-full rounded-xl" />
              </div>
            ) : null /* anonymous - redirect effect above is firing */}
          </main>
        </div>
        <BottomTabBar />
      </div>
    </NotificationsProvider>
  )
}
