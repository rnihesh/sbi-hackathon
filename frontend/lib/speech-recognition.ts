/**
 * Minimal Web Speech API (`SpeechRecognition`) typings - TypeScript's DOM lib
 * doesn't ship these yet, and the spec is still a "living standard" with a
 * webkit-prefixed shim on Safari/older Chrome.
 *
 * Privacy note: this app never touches the raw audio. It flows straight from
 * the microphone into the browser's own built-in speech service (e.g.
 * Chrome's on-device/cloud recognizer) - the same as any other page using
 * this API - and only the recognized text comes back to our code. No audio
 * is uploaded to Sarathi's servers.
 */

export interface SpeechRecognitionAlternative {
  transcript: string
  confidence: number
}

export interface SpeechRecognitionResult {
  readonly length: number
  readonly isFinal: boolean
  item(index: number): SpeechRecognitionAlternative
  [index: number]: SpeechRecognitionAlternative
}

export interface SpeechRecognitionResultList {
  readonly length: number
  item(index: number): SpeechRecognitionResult
  [index: number]: SpeechRecognitionResult
}

export interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number
  readonly results: SpeechRecognitionResultList
}

export interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string
}

export interface SpeechRecognition extends EventTarget {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  onresult: ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => void) | null
  onerror: ((this: SpeechRecognition, ev: SpeechRecognitionErrorEvent) => void) | null
  onend: ((this: SpeechRecognition, ev: Event) => void) | null
  onstart: ((this: SpeechRecognition, ev: Event) => void) | null
  start(): void
  stop(): void
  abort(): void
}

export interface SpeechRecognitionConstructor {
  new (): SpeechRecognition
}

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
}

/** Feature-detects the constructor (standard name first, then the
 * webkit-prefixed fallback Safari/older Chrome expose). Returns `undefined`
 * on browsers with no support at all (Firefox as of writing), so callers can
 * skip rendering the mic control entirely instead of showing a button that
 * would only ever error. */
export function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | undefined {
  if (typeof window === "undefined") return undefined
  return window.SpeechRecognition ?? window.webkitSpeechRecognition
}
