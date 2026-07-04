"use client"

import * as React from "react"
import { Check, ChevronsUpDown, Loader2, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import { api, API_V1, ApiError } from "@/lib/api"
import type { CustomerSearchResult } from "@/lib/console-types"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

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

const SEARCH_DEBOUNCE_MS = 250

export function InjectEventDialog() {
  const [open, setOpen] = React.useState(false)
  const [customerPickerOpen, setCustomerPickerOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")
  const [options, setOptions] = React.useState<CustomerSearchResult[]>([])
  const [loadingOptions, setLoadingOptions] = React.useState(false)
  const [customer, setCustomer] = React.useState<CustomerSearchResult | null>(null)
  const [eventType, setEventType] = React.useState<string>("")
  const [submitting, setSubmitting] = React.useState(false)
  const submittingRef = React.useRef(false)

  React.useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    let cancelled = false
    setLoadingOptions(true)
    const handle = setTimeout(() => {
      const params = new URLSearchParams({ limit: "20" })
      if (query.trim()) params.set("q", query.trim())
      api
        .get<CustomerSearchResult[]>(`${API_V1}/console/customers?${params.toString()}`, {
          signal: controller.signal,
        })
        .then((res) => {
          if (!cancelled) setOptions(res)
        })
        .catch(() => {
          // Non-critical search failure - leave the previous options in place.
        })
        .finally(() => {
          if (!cancelled) setLoadingOptions(false)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      cancelled = true
      controller.abort()
      clearTimeout(handle)
    }
  }, [open, query])

  function resetAndClose() {
    setOpen(false)
    setCustomerPickerOpen(false)
    setCustomer(null)
    setEventType("")
    setQuery("")
    setOptions([])
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
      toast.error(err instanceof ApiError ? err.message : "Couldn't inject that event")
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        <Sparkles /> Inject event
      </Button>

      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : resetAndClose())}>
        <DialogContent className="sm:max-w-lg">
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
              <Popover open={customerPickerOpen} onOpenChange={setCustomerPickerOpen}>
                <PopoverTrigger asChild>
                  <Button
                    id="inject-event-customer"
                    type="button"
                    variant="outline"
                    role="combobox"
                    aria-expanded={customerPickerOpen}
                    className="w-full justify-between font-normal"
                  >
                    <span className="truncate">
                      {customer
                        ? `${customer.full_name}${customer.city ? ` - ${customer.city}` : ""}`
                        : "Search customers..."}
                    </span>
                    <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent
                  align="start"
                  className="w-(--radix-popover-trigger-width) p-0"
                >
                  <div className="border-b border-border p-2">
                    <Input
                      autoFocus
                      placeholder="Search by name..."
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </div>
                  <div className="max-h-56 overflow-y-auto p-1">
                    {loadingOptions ? (
                      <div className="flex items-center justify-center gap-2 py-6 text-xs text-muted-foreground">
                        <Loader2 className="size-3.5 animate-spin" /> Searching...
                      </div>
                    ) : options.length === 0 ? (
                      <p className="px-2 py-4 text-center text-xs text-muted-foreground">
                        No customers found.
                      </p>
                    ) : (
                      options.map((opt) => (
                        <button
                          key={opt.id}
                          type="button"
                          onClick={() => {
                            setCustomer(opt)
                            setCustomerPickerOpen(false)
                          }}
                          className={cn(
                            "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted",
                            customer?.id === opt.id && "bg-muted"
                          )}
                        >
                          <span className="min-w-0 truncate">
                            {opt.full_name}
                            {opt.city && <span className="text-muted-foreground"> - {opt.city}</span>}
                          </span>
                          {customer?.id === opt.id && <Check className="size-3.5 shrink-0" />}
                        </button>
                      ))
                    )}
                  </div>
                </PopoverContent>
              </Popover>
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
                      "flex flex-col gap-0.5 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:bg-muted",
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
