import Link from "next/link"
import { ShieldAlert } from "lucide-react"

import { Button } from "@/components/ui/button"

export function StaffRequiredPanel() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-24 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-muted">
        <ShieldAlert className="size-5 text-muted-foreground" />
      </div>
      <h1 className="text-base font-semibold tracking-tight">Staff access required</h1>
      <p className="text-sm text-muted-foreground">
        This console is reserved for Sarathi relationship-manager staff. Sign in with a
        staff account, or reach out to your administrator for access.
      </p>
      <Button asChild size="sm" variant="outline" className="mt-2">
        <Link href="/app/home">Back to your account</Link>
      </Button>
    </div>
  )
}
