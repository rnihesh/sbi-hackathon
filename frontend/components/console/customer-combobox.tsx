"use client"

import * as React from "react"
import { Check, ChevronsUpDown, Loader2 } from "lucide-react"

import { cn } from "@/lib/utils"
import { api, API_V1 } from "@/lib/api"
import type { CustomerSearchResult } from "@/lib/console-types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

const SEARCH_DEBOUNCE_MS = 250

/** Debounced search input + results list for picking a customer - the shared
 * guts behind `CustomerCombobox` below. Exported separately so a caller that
 * already owns its own popover shell (the console topbar's search button)
 * can embed just the list, instead of nesting a second trigger+popover inside
 * its own. Only ever mounted while its containing popover is open, so the
 * debounced search effect runs unconditionally from mount rather than
 * gating on an `open` flag. */
export function CustomerSearchResults({
  value,
  onSelect,
}: {
  value: CustomerSearchResult | null
  onSelect: (customer: CustomerSearchResult) => void
}) {
  const [query, setQuery] = React.useState("")
  const [options, setOptions] = React.useState<CustomerSearchResult[]>([])
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    setLoading(true)
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
          if (!cancelled) setLoading(false)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      cancelled = true
      controller.abort()
      clearTimeout(handle)
    }
  }, [query])

  return (
    <>
      <div className="border-b border-border p-2">
        <Input
          autoFocus
          placeholder="Search by name..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="max-h-56 overflow-y-auto p-1">
        {loading ? (
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
              onClick={() => onSelect(opt)}
              className={cn(
                "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                value?.id === opt.id && "bg-muted"
              )}
            >
              <span className="min-w-0 truncate">
                {opt.full_name}
                {opt.city && <span className="text-muted-foreground"> - {opt.city}</span>}
              </span>
              {value?.id === opt.id && <Check className="size-3.5 shrink-0" />}
            </button>
          ))
        )}
      </div>
    </>
  )
}

/** Full customer picker: a combobox-styled button trigger + popover around
 * `CustomerSearchResults` - used where the selection sits inline in a form
 * (the sim life-event injector's customer field). */
export function CustomerCombobox({
  value,
  onChange,
  placeholder = "Search customers...",
  triggerId,
  className,
}: {
  value: CustomerSearchResult | null
  onChange: (customer: CustomerSearchResult) => void
  placeholder?: string
  triggerId?: string
  className?: string
}) {
  const [open, setOpen] = React.useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={triggerId}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn("w-full justify-between font-normal", className)}
        >
          <span className="truncate">
            {value ? `${value.full_name}${value.city ? ` - ${value.city}` : ""}` : placeholder}
          </span>
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-(--radix-popover-trigger-width) p-0">
        <CustomerSearchResults
          value={value}
          onSelect={(customer) => {
            onChange(customer)
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
