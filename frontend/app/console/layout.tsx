import { ConsoleSidebar } from "@/components/console/console-sidebar"
import { ConsoleTopbar } from "@/components/console/console-topbar"

export default function ConsoleLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <div className="flex min-h-dvh">
      <ConsoleSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <ConsoleTopbar />
        <main className="flex-1 px-4 py-6 sm:px-6">{children}</main>
      </div>
    </div>
  )
}
