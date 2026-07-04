"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { Search } from "lucide-react"

import { CustomerSearchResults } from "@/components/console/customer-combobox"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

/** Topbar customer search: a plain icon button (no global hotkey - the console
 * already has enough of those) that opens a small popover to find a customer
 * by name and jump straight to their 360 view. */
export function CustomerSearchButton() {
  const router = useRouter()
  const [open, setOpen] = React.useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Search customers"
          className="text-muted-foreground"
        >
          <Search className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-0">
        <CustomerSearchResults
          value={null}
          onSelect={(customer) => {
            setOpen(false)
            router.push(`/console/customers/${customer.id}`)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
