/**
 * Client-only persistence for the first-run welcome card on `/app/home` (see
 * `components/customer/welcome-card.tsx`). Once a customer dismisses it, it
 * never reappears - best-effort like the other storage helpers here (SSR,
 * private browsing, quota failures just leave it "not dismissed" rather than
 * throwing).
 */

const STORAGE_KEY = "sarathi:welcome-dismissed:v1"

export function loadWelcomeDismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1"
  } catch {
    return false
  }
}

export function saveWelcomeDismissed(): void {
  try {
    localStorage.setItem(STORAGE_KEY, "1")
  } catch {
    // Best-effort - private browsing / storage disabled / quota exceeded.
  }
}
