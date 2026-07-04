"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { ArrowUp, Mic, MicOff, Square } from "lucide-react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import { pressable } from "@/lib/motion"
import { CHAT_PLACEHOLDER_HINTS, preferredLanguageToBcp47 } from "@/lib/languages"
import { getSpeechRecognitionCtor, type SpeechRecognition } from "@/lib/speech-recognition"
import { Button } from "@/components/ui/button"

const DEFAULT_PLACEHOLDER = "Ask Sarathi anything about your money…"
const PLACEHOLDER_ROTATE_MS = 3200
const LISTENING_PLACEHOLDER = "Listening…"

export function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
  preferredLanguage,
}: {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  isStreaming: boolean
  /** The customer's chat language preference (`null`/`undefined`/"english" -
   * auto, no rotation). A recognised non-English value rotates the empty-state
   * placeholder between English and a native-script hint. */
  preferredLanguage?: string | null
}) {
  const textareaRef = React.useRef<HTMLTextAreaElement>(null)

  const nativeHint = preferredLanguage ? CHAT_PLACEHOLDER_HINTS[preferredLanguage] : undefined
  const placeholders = React.useMemo(
    () => (nativeHint ? [DEFAULT_PLACEHOLDER, `${nativeHint}…`] : [DEFAULT_PLACEHOLDER]),
    [nativeHint]
  )
  const [placeholderIndex, setPlaceholderIndex] = React.useState(0)

  React.useEffect(() => {
    setPlaceholderIndex(0)
    if (placeholders.length < 2) return
    const id = setInterval(() => {
      setPlaceholderIndex((i) => (i + 1) % placeholders.length)
    }, PLACEHOLDER_ROTATE_MS)
    return () => clearInterval(id)
  }, [placeholders])

  React.useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !isStreaming) onSend()
    }
  }

  // --- Voice input (Web Speech API) -----------------------------------------
  // Zero-cost, browser-only: audio goes straight from the mic to the browser's
  // own built-in speech recognizer (see lib/speech-recognition.ts) and never
  // touches Sarathi's servers - only the recognized text comes back to us,
  // exactly like it would for typed text.
  const [micSupported, setMicSupported] = React.useState(false)
  const [listening, setListening] = React.useState(false)
  const recognitionRef = React.useRef<SpeechRecognition | null>(null)
  // Text already in the box when listening started; interim/final results are
  // appended after it with a separating space rather than replacing it.
  const baseTextRef = React.useRef("")
  const onChangeRef = React.useRef(onChange)
  onChangeRef.current = onChange

  React.useEffect(() => {
    setMicSupported(!!getSpeechRecognitionCtor())
  }, [])

  const stopListening = React.useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  // Stop listening if the assistant starts streaming (e.g. a suggestion chip
  // sent the message while voice input was still open) and on unmount.
  React.useEffect(() => {
    if (isStreaming) stopListening()
  }, [isStreaming, stopListening])
  React.useEffect(() => stopListening, [stopListening])

  function handleMicToggle() {
    if (listening) {
      stopListening()
      return
    }
    const RecognitionCtor = getSpeechRecognitionCtor()
    if (!RecognitionCtor) return

    const recognition = new RecognitionCtor()
    recognition.lang = preferredLanguageToBcp47(preferredLanguage)
    recognition.continuous = false
    recognition.interimResults = true
    recognition.maxAlternatives = 1
    baseTextRef.current = value.trim() ? `${value.trim()} ` : ""

    recognition.onresult = (event) => {
      let finalText = ""
      let interimText = ""
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i]
        const transcript = result[0]?.transcript ?? ""
        if (result.isFinal) finalText += transcript
        else interimText += transcript
      }
      const spoken = `${finalText}${interimText}`.trim()
      onChangeRef.current(spoken ? `${baseTextRef.current}${spoken}` : baseTextRef.current.trim())
    }
    recognition.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        toast.error("Microphone permission needed")
      }
      // "no-speech" / "aborted" / network hiccups: just quietly stop listening,
      // whatever was already transcribed stays in the box.
    }
    recognition.onend = () => {
      setListening(false)
      recognitionRef.current = null
    }

    recognitionRef.current = recognition
    setListening(true)
    recognition.start()
  }

  const composerPlaceholder = listening ? LISTENING_PLACEHOLDER : placeholders[placeholderIndex]

  return (
    <div className="flex flex-col gap-1.5">
      {isStreaming && (
        <div className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
          <span className="flex gap-0.5" aria-hidden>
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="size-1 animate-bounce rounded-full bg-muted-foreground/70 motion-reduce:animate-none"
                style={{ animationDelay: `${i * 120}ms` }}
              />
            ))}
          </span>
          Sarathi is thinking…
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border border-input bg-background p-1.5 shadow-sm focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
        <textarea
          ref={textareaRef}
          id="chat-composer-input"
          name="message"
          aria-label="Message"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          rows={1}
          placeholder={composerPlaceholder}
          className="max-h-[200px] min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
        />
        {micSupported && (
          <motion.div {...pressable}>
            <Button
              type="button"
              size="icon"
              variant={listening ? "default" : "outline"}
              onClick={handleMicToggle}
              disabled={isStreaming}
              aria-label={listening ? "Stop voice input" : "Start voice input"}
              aria-pressed={listening}
              className={cn(listening && "mic-listening")}
            >
              {listening ? <MicOff /> : <Mic />}
            </Button>
          </motion.div>
        )}
        {isStreaming ? (
          <Button size="icon" variant="destructive" onClick={onStop} aria-label="Stop generating">
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button size="icon" onClick={onSend} disabled={!value.trim()} aria-label="Send message">
            <ArrowUp />
          </Button>
        )}
      </div>
    </div>
  )
}
