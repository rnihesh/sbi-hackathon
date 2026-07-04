"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

const LENGTH = 6

/** Six auto-advancing digit boxes for email OTP entry. Supports paste (splits a
 * full 6-digit paste across boxes) and backspace-to-previous navigation. */
export function OtpInput({
  value,
  onChange,
  onComplete,
  disabled,
  autoFocus = true,
}: {
  value: string
  onChange: (value: string) => void
  onComplete?: (value: string) => void
  disabled?: boolean
  autoFocus?: boolean
}) {
  const inputRefs = React.useRef<Array<HTMLInputElement | null>>([])
  const digits = React.useMemo(() => {
    const arr = value.split("").slice(0, LENGTH)
    while (arr.length < LENGTH) arr.push("")
    return arr
  }, [value])

  React.useEffect(() => {
    if (autoFocus) inputRefs.current[0]?.focus()
  }, [autoFocus])

  function setDigit(index: number, digit: string) {
    const next = [...digits]
    next[index] = digit
    const joined = next.join("")
    onChange(joined)
    if (joined.length === LENGTH && next.every((d) => d !== "")) {
      onComplete?.(joined)
    }
  }

  function handleChange(index: number, raw: string) {
    const clean = raw.replace(/\D/g, "")
    if (clean.length === 0) {
      setDigit(index, "")
      return
    }
    if (clean.length > 1) {
      // Pasted content landed in a single box — distribute across the rest.
      const next = [...digits]
      let cursor = index
      for (const char of clean) {
        if (cursor >= LENGTH) break
        next[cursor] = char
        cursor += 1
      }
      const joined = next.join("")
      onChange(joined)
      const focusIndex = Math.min(cursor, LENGTH - 1)
      inputRefs.current[focusIndex]?.focus()
      if (joined.length === LENGTH && next.every((d) => d !== "")) onComplete?.(joined)
      return
    }
    setDigit(index, clean)
    if (index < LENGTH - 1) inputRefs.current[index + 1]?.focus()
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && digits[index] === "" && index > 0) {
      inputRefs.current[index - 1]?.focus()
    }
    if (e.key === "ArrowLeft" && index > 0) inputRefs.current[index - 1]?.focus()
    if (e.key === "ArrowRight" && index < LENGTH - 1) inputRefs.current[index + 1]?.focus()
  }

  return (
    <div className="flex justify-between gap-2" role="group" aria-label="Verification code">
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(el) => {
            inputRefs.current[index] = el
          }}
          value={digit}
          disabled={disabled}
          onChange={(e) => handleChange(index, e.target.value)}
          onKeyDown={(e) => handleKeyDown(index, e)}
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          maxLength={LENGTH}
          aria-label={`Digit ${index + 1}`}
          className={cn(
            "h-12 w-full min-w-0 rounded-lg border border-input bg-transparent text-center text-lg font-medium font-mono tabular-nums transition-colors outline-none",
            "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            "disabled:pointer-events-none disabled:opacity-50 dark:bg-input/30"
          )}
        />
      ))}
    </div>
  )
}
