/**
 * Demo tour content + client-only progress persistence for the jury flow.
 *
 * The tour is a pure-frontend checklist rendered in the console topbar (see
 * components/console/demo-tour.tsx). Each step carries a one-line narration
 * ("say this") and a deep link to the surface the presenter should be on.
 * Progress (which steps are ticked) is stored in localStorage, best-effort:
 * any storage failure (SSR, private browsing, quota) just yields an unchecked
 * tour rather than throwing.
 */

export interface DemoTourStep {
  /** 1-based step number, shown in the check circle. */
  n: number
  title: string
  /** One or two lines the presenter says out loud on this step. */
  say: string
  /** Deep link to the surface for this step. */
  href: string
  /** Human label for the link target (the surface name). */
  target: string
  /** Customer app / landing surfaces open in a new tab so the console (and
   * this tour) stays put; console surfaces navigate in place. */
  external: boolean
}

export const DEMO_TOUR_STEPS: DemoTourStep[] = [
  {
    n: 1,
    title: "Landing + pitch line",
    say: "YONO put a bank in every pocket. Sarathi puts a banker in every pocket: proactive, supervised, auditable.",
    href: "/",
    target: "Landing page",
    external: true,
  },
  {
    n: 2,
    title: "Conversational onboarding",
    say: "A prospect just talks, no forms. KYC by dialogue, PAN validated, and the account opens only after a code-enforced KYC gate.",
    href: "/app/chat",
    target: "Customer chat",
    external: true,
  },
  {
    n: 3,
    title: "Load demo activity",
    say: "Load a customer's six months of synthetic transactions: the raw signal our agents watch, zero real data.",
    href: "/app/home",
    target: "Customer home",
    external: true,
  },
  {
    n: 4,
    title: "Inject a life event",
    say: "Inject a job change. Sarathi does not wait to be asked; it watches the transaction stream and reacts.",
    href: "/console/life-events",
    target: "Life Events",
    external: false,
  },
  {
    n: 5,
    title: "Watch feed, approve proposal",
    say: "A rule flags the salary jump, the Engagement Agent reasons and drafts a proposal. The agent proposes; the bank approves.",
    href: "/console/approvals",
    target: "Approvals",
    external: false,
  },
  {
    n: 6,
    title: "Customer gets notified",
    say: "Approval fires a real in-app nudge and a real SES email. Nothing impactful auto-fires.",
    href: "/app/nudges",
    target: "Customer notifications",
    external: true,
  },
  {
    n: 7,
    title: "Detection scorecard",
    say: "Measured detection accuracy against ground truth. Not a vibe, a number the jury can hold us to.",
    href: "/console/analytics",
    target: "Analytics",
    external: false,
  },
  {
    n: 8,
    title: "Glass box: traces + cost",
    say: "Every decision is a glass box: nodes, tools, model, tokens, cost, latency. Auditable to the rupee, then open Costs.",
    href: "/console/traces",
    target: "Traces",
    external: false,
  },
]

const STORAGE_KEY = "sarathi:demo-tour:v1"

export function loadTourProgress(stepCount: number): boolean[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
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

export function saveTourProgress(checked: boolean[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(checked))
  } catch {
    // Best-effort - private browsing / storage disabled / quota exceeded.
  }
}
