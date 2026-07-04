"use client"

import { useSignInSheet } from "@/components/auth/sign-in-sheet-context"
import { SignInSheet } from "@/components/auth/sign-in-sheet"

/** Mounts the sign-in sheet controlled by the shared context — kept separate
 * from the (server) landing layout. */
export function SignInSheetHost() {
  const { open, setOpen } = useSignInSheet()
  return <SignInSheet open={open} onOpenChange={setOpen} />
}
