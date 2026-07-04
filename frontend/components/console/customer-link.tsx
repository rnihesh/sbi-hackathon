import Link from "next/link"
import type { ComponentProps } from "react"

import { cn } from "@/lib/utils"

/** Quiet link to a customer's 360 view (`/console/customers/{id}`) - used
 * everywhere a customer name/id renders across the console (leads, life
 * events, detection scorecard, approvals, feed, traces). Deliberately no
 * color shift beyond the underline: a name isn't a call to action, so it
 * doesn't get the clay accent - only a subtle hover underline says "this is
 * clickable". Forwards any extra `<Link>` props (e.g. `onClick` for
 * `stopPropagation` when nested inside a row that's itself clickable). */
export function CustomerLink({
  id,
  children,
  className,
  ...rest
}: {
  id: string
  children: React.ReactNode
  className?: string
} & Omit<ComponentProps<typeof Link>, "href">) {
  return (
    <Link
      href={`/console/customers/${id}`}
      className={cn("underline-offset-2 decoration-primary/40 hover:underline", className)}
      {...rest}
    >
      {children}
    </Link>
  )
}
