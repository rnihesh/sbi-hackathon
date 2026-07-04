import { LandingNav } from "@/components/landing/nav"
import { LandingFooter } from "@/components/landing/footer"
import { SignInSheetProvider } from "@/components/auth/sign-in-sheet-context"
import { SignInSheetHost } from "@/components/auth/sign-in-sheet-host"

export default function LandingLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <SignInSheetProvider>
      <div className="flex min-h-dvh flex-col">
        <LandingNav />
        <main className="flex-1">{children}</main>
        <LandingFooter />
      </div>
      <SignInSheetHost />
    </SignInSheetProvider>
  )
}
