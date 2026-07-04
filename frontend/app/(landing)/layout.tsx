import { LandingNav } from "@/components/landing/nav"
import { LandingFooter } from "@/components/landing/footer"

export default function LandingLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <div className="flex min-h-dvh flex-col">
      <LandingNav />
      <main className="flex-1">{children}</main>
      <LandingFooter />
    </div>
  )
}
