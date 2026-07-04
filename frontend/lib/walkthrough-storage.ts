/**
 * Client-only persistence for interactive walkthrough checklists (chat
 * "structured" cards - see components/chat/structured-card.tsx). Keyed by
 * conversation + topic so reopening the same walkthrough, even across a page
 * reload, restores exactly which steps a customer already ticked off.
 * Best-effort: any storage failure (SSR, private browsing, quota) just falls
 * back to an unchecked walkthrough rather than throwing.
 */

const STORAGE_PREFIX = "sarathi:walkthrough:v1"

function slugify(input: string): string {
  const slug = input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
  return slug.slice(0, 60) || "untitled"
}

/** `topic` is the walkthrough's title when it has one, otherwise a stable
 * fallback derived from its step titles (so two different untitled
 * walkthroughs in the same conversation don't collide). */
export function walkthroughStorageKey(
  conversationId: string | null | undefined,
  topic: string
): string {
  return `${STORAGE_PREFIX}:${conversationId ?? "draft"}:${slugify(topic)}`
}

export function loadWalkthroughProgress(key: string, stepCount: number): boolean[] {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return new Array<boolean>(stepCount).fill(false)
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length !== stepCount) {
      return new Array<boolean>(stepCount).fill(false)
    }
    return parsed.map((v) => v === true)
  } catch {
    return new Array<boolean>(stepCount).fill(false)
  }
}

export function saveWalkthroughProgress(key: string, checked: boolean[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(checked))
  } catch {
    // Best-effort - private browsing / storage disabled / quota exceeded.
  }
}
