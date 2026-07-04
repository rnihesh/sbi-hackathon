"use client"

import * as React from "react"

/**
 * Restores keyboard focus to whatever triggered a Dialog/Sheet, for the cases
 * where the trigger can't be a static `DialogTrigger`/`SheetTrigger` - e.g. a
 * single confirm dialog shared across many list rows, each with its own
 * "Delete"/"Remove" button. Radix's own close-focus-return only works through
 * `DialogTrigger`'s ref; a bare `onClick={() => setOpen(true)}` button leaves
 * Radix nothing to refocus, so on close focus silently falls back to
 * `<body>` - a real keyboard-navigation dead end, verified live.
 *
 * Usage: call `captureFocus()` in the same click handler that opens the
 * dialog, then pass `onCloseAutoFocus` to `DialogContent`/`SheetContent`.
 */
export function useFocusReturn() {
  const lastActiveRef = React.useRef<HTMLElement | null>(null)

  const captureFocus = React.useCallback(() => {
    if (typeof document !== "undefined" && document.activeElement instanceof HTMLElement) {
      lastActiveRef.current = document.activeElement
    }
  }, [])

  const onCloseAutoFocus = React.useCallback((event: Event) => {
    const target = lastActiveRef.current
    if (target && target !== document.body && document.contains(target)) {
      event.preventDefault()
      target.focus()
    }
  }, [])

  return { captureFocus, onCloseAutoFocus }
}
