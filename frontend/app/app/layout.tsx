import { AppSidebar } from "@/components/customer/app-sidebar"
import { BottomTabBar } from "@/components/customer/bottom-tab-bar"

export default function CustomerAppLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <div className="flex min-h-dvh">
      <AppSidebar />
      <main className="min-w-0 flex-1 pb-20 md:pb-0">{children}</main>
      <BottomTabBar />
    </div>
  )
}
