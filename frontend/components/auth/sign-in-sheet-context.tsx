"use client"

import * as React from "react"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"

interface SignInSheetContextValue {
  open: boolean
  setOpen: (open: boolean) => void
}

const SignInSheetContext = React.createContext<SignInSheetContextValue | null>(null)

export function SignInSheetProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)

  const value = React.useMemo(() => ({ open, setOpen }), [open])

  return (
    <SignInSheetContext.Provider value={value}>
      <Suspense fallback={null}>
        <AutoOpenFromQuery />
      </Suspense>
      {children}
    </SignInSheetContext.Provider>
  )
}

/** `?signin=1` (e.g. from the `/app/*` and `/console/*` guards redirecting an
 * anonymous visitor home) auto-opens the sheet. Isolated in its own component
 * since `useSearchParams` requires a Suspense boundary. */
function AutoOpenFromQuery() {
  const searchParams = useSearchParams()
  const ctx = React.useContext(SignInSheetContext)

  React.useEffect(() => {
    if (searchParams.get("signin") === "1") ctx?.setOpen(true)
  }, [searchParams, ctx])

  return null
}

export function useSignInSheet(): SignInSheetContextValue {
  const ctx = React.useContext(SignInSheetContext)
  if (!ctx) throw new Error("useSignInSheet must be used within a SignInSheetProvider")
  return ctx
}
