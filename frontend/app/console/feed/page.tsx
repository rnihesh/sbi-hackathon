"use client"

import * as React from "react"
import { Radio } from "lucide-react"

import { API_V1 } from "@/lib/api"
import { useSse } from "@/lib/use-sse"
import type { FeedItem } from "@/lib/console-types"
import { ConsolePageHeader } from "@/components/console/page-header"
import { ConnectionStatusDot } from "@/components/console/connection-status-dot"
import { FeedItemRow } from "@/components/console/feed-item-row"

export default function LiveFeedPage() {
  const { items, status } = useSse<FeedItem>(`${API_V1}/console/feed`)
  const containerRef = React.useRef<HTMLDivElement>(null)
  const paused = React.useRef(false)

  React.useEffect(() => {
    if (paused.current) return
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items])

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <ConsolePageHeader
          title="Live Feed"
          description="Real-time agent activity across every customer session."
        />
        <ConnectionStatusDot status={status} />
      </div>

      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <Radio className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {status === "open" ? "Listening - nothing has happened yet." : "Connecting to the live feed…"}
          </p>
        </div>
      ) : (
        <div
          ref={containerRef}
          onMouseEnter={() => {
            paused.current = true
          }}
          onMouseLeave={() => {
            paused.current = false
            const el = containerRef.current
            if (el) el.scrollTop = el.scrollHeight
          }}
          className="max-h-[70vh] divide-y divide-border overflow-y-auto rounded-xl border border-border"
        >
          {items.map((item, index) => (
            <FeedItemRow key={`${item.ref_id}-${index}`} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
