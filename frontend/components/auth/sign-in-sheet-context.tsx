"use client"

import * as React from "react"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"

interface SignInSheetContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  /** The element that had focus right before the sheet opened - not tracked
   * by Radix's own focus-return-on-close since this sheet's trigger buttons
   * (nav, other CTAs, `?signin=1`) aren't wired through `SheetTrigger`, they
   * just call `setOpen(true)` directly. `SignInSheet` reads this to restore
   * focus itself instead of it falling back to `<body>` on close. */
  lastActiveRef: React.RefObject<HTMLElement | null>
}

const SignInSheetContext = React.createContext<SignInSheetContextValue | null>(null)

export function SignInSheetProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpenState] = React.useState(false)
  const lastActiveRef = React.useRef<HTMLElement | null>(null)

  const setOpen = React.useCallback((next: boolean) => {
    if (next && typeof document !== "undefined" && document.activeElement instanceof HTMLElement) {
      lastActiveRef.current = document.activeElement
    }
    setOpenState(next)
  }, [])

  const value = React.useMemo(() => ({ open, setOpen, lastActiveRef }), [open, setOpen])

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
