import Link from "next/link"
import type { Metadata } from "next"
import { ArrowRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { SarathiMark } from "@/components/brand/logo"

export const metadata: Metadata = {
  title: "Page not found",
}

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-20 text-center">
      <SarathiMark className="size-10 text-primary" />
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          This page doesn&apos;t exist, or it moved. Let&apos;s get you back on track.
        </p>
      </div>
      <Button asChild className="px-6">
        <Link href="/">
          Back to Sarathi
          <ArrowRight data-icon="inline-end" />
        </Link>
      </Button>
    </div>
  )
}
