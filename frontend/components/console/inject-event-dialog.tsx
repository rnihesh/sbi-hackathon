"use client"

import * as React from "react"
import { Loader2, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import { api, API_V1, describeApiError } from "@/lib/api"
import type { CustomerSearchResult } from "@/lib/console-types"
import { CustomerCombobox } from "@/components/console/customer-combobox"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"

/** The 6 sim life-event scripts `POST /console/sim/inject-event` accepts - labels
 * and descriptions mirror `app.sim.events`'s script docstrings exactly, so this
 * never drifts from what actually happens to the persona's transaction stream. */
const EVENT_TYPES = [
  {
    value: "job_change",
    label: "Job change",
    description: "Salary jumps 30-60% after one skipped pay cycle for the handover gap.",
  },
  {
    value: "new_child",
    label: "New child",
    description: "Pharmacy/baby-store spend ramps for ~6 months, school fees later.",
  },
  {
    value: "home_purchase_intent",
    label: "Home purchase intent",
    description: "Rent stops, builder debits appear, then a home-loan EMI.",
  },
  {
    value: "bonus_windfall",
    label: "Bonus windfall",
    description: "A one-off bonus credit, 3-5x the customer's monthly income.",
  },
  {
    value: "wedding",
    label: "Wedding",
    description: "Catering, jewellery and venue spend spikes over ~45 days.",
  },
  {
    value: "churn_risk",
    label: "Churn risk",
    description: "UPI activity decays to near-zero and the balance drains out.",
  },
] as const

export function InjectEventDialog() {
  const [open, setOpen] = React.useState(false)
  // Opened from a plain button, not a `DialogTrigger`, so Radix has no
  // trigger ref to restore focus to on close (falls back to `<body>` -
  // verified live on the sign-in sheet, same gap). Track it directly.
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const [customer, setCustomer] = React.useState<CustomerSearchResult | null>(null)
  const [eventType, setEventType] = React.useState<string>("")
  const [submitting, setSubmitting] = React.useState(false)
  const submittingRef = React.useRef(false)
  // `CustomerCombobox` owns its own search query/results state internally;
  // bumping its `key` on close forces a fresh instance next open instead of
  // carrying over a stale search from the previous session.
  const [comboboxResetKey, setComboboxResetKey] = React.useState(0)

  function resetAndClose() {
    setOpen(false)
    setCustomer(null)
    setEventType("")
    setComboboxResetKey((key) => key + 1)
  }

  async function handleSubmit() {
    if (submittingRef.current || !customer || !eventType) return
    submittingRef.current = true
    setSubmitting(true)
    try {
      await api.post(`${API_V1}/console/sim/inject-event`, {
        customer_id: customer.id,
        type: eventType,
      })
      const eventLabel = EVENT_TYPES.find((e) => e.value === eventType)?.label ?? eventType
      toast.success(`Injected "${eventLabel}" for ${customer.full_name}`, {
        description:
          "Replaying transactions through the live pipeline - detection appears in the feed/life events shortly.",
      })
      resetAndClose()
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't inject that event"))
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <>
      <Button ref={triggerRef} size="sm" onClick={() => setOpen(true)}>
        <Sparkles /> Inject event
      </Button>

      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : resetAndClose())}>
        <DialogContent
          className="sm:max-w-lg"
          onCloseAutoFocus={(e) => {
            e.preventDefault()
            triggerRef.current?.focus()
          }}
        >
          <DialogHeader>
            <DialogTitle>Inject a sim life event</DialogTitle>
            <DialogDescription>
              Replays this customer&apos;s persona forward through the chosen life-event script and
              pushes the resulting transactions onto the real event pipeline - the same path organic
              sim traffic takes.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="inject-event-customer">Customer</Label>
              <CustomerCombobox
                key={comboboxResetKey}
                value={customer}
                onChange={setCustomer}
                triggerId="inject-event-customer"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>Event type</Label>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {EVENT_TYPES.map((et) => (
                  <button
                    key={et.value}
                    type="button"
                    onClick={() => setEventType(et.value)}
                    aria-pressed={eventType === et.value}
                    className={cn(
                      "flex flex-col gap-0.5 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      eventType === et.value && "border-primary bg-accent/10 hover:bg-accent/10"
                    )}
                  >
                    <span className="text-sm font-medium">{et.label}</span>
                    <span className="text-xs text-muted-foreground">{et.description}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={resetAndClose} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={() => void handleSubmit()} disabled={!customer || !eventType || submitting}>
              {submitting ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" /> Injecting...
                </>
              ) : (
                "Inject event"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
