"use client"

import * as React from "react"
import { toast } from "sonner"
import { RotateCcw } from "lucide-react"

import { api, API_V1, describeApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { ConsolePageHeader } from "@/components/console/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

interface RuntimeSetting {
  key: string
  value: boolean | number | string
  default: boolean | number | string
  source: "override" | "default"
  type: "bool" | "float" | "enum"
  options: string[] | null
  min: number | null
  max: number | null
}

// Human-facing copy for each allowlisted key. Anything not listed still renders
// via a humanized fallback, so a new backend key never breaks the page.
const SETTING_META: Record<string, { label: string; help: string; group: string }> = {
  scheduler_enabled: {
    label: "Proactive scheduler",
    help: "Periodic autonomous reviews of quiet customers. Off pauses all scheduled agent runs.",
    group: "Autonomy",
  },
  standing_instructions_enabled: {
    label: "Standing instructions",
    help: "Recurring auto-transfers executed against the ledger on schedule.",
    group: "Autonomy",
  },
  llm_daily_budget_usd: {
    label: "Daily LLM budget (USD)",
    help: "Event and scheduled agent runs pause once the day's spend crosses this. Chat is never gated.",
    group: "LLM budget and models",
  },
  openai_model_smart: {
    label: "Smart tier model",
    help: "gpt-4o for demo day, gpt-4o-mini for low cost.",
    group: "LLM budget and models",
  },
  openai_model_fast: {
    label: "Fast tier model",
    help: "Used for classification and cheap sub-tasks.",
    group: "LLM budget and models",
  },
}

const GROUP_ORDER = ["Autonomy", "LLM budget and models"]

function humanizeKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function ConsoleSettingsPage() {
  const [settings, setSettings] = React.useState<RuntimeSetting[] | null>(null)
  const [busyKey, setBusyKey] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    try {
      const res = await api.get<{ settings: RuntimeSetting[] }>(`${API_V1}/console/settings`)
      setSettings(res.settings)
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't load settings"))
      setSettings([])
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  async function writeSetting(key: string, value: boolean | number | string) {
    setBusyKey(key)
    try {
      const res = await api.patch<{ setting: RuntimeSetting }>(`${API_V1}/console/settings`, {
        key,
        value,
      })
      setSettings((prev) => prev?.map((s) => (s.key === key ? res.setting : s)) ?? null)
      toast.success("Setting updated")
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't update setting"))
    } finally {
      setBusyKey(null)
    }
  }

  async function revertSetting(key: string) {
    setBusyKey(key)
    try {
      const res = await api.delete<{ setting: RuntimeSetting }>(`${API_V1}/console/settings/${key}`)
      setSettings((prev) => prev?.map((s) => (s.key === key ? res.setting : s)) ?? null)
      toast.success("Reverted to default")
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't revert setting"))
    } finally {
      setBusyKey(null)
    }
  }

  const grouped = React.useMemo(() => {
    const map = new Map<string, RuntimeSetting[]>()
    for (const s of settings ?? []) {
      const group = SETTING_META[s.key]?.group ?? "Other"
      const list = map.get(group) ?? []
      list.push(s)
      map.set(group, list)
    }
    return map
  }, [settings])

  const groupNames = [...GROUP_ORDER, ...[...grouped.keys()].filter((g) => !GROUP_ORDER.includes(g))]

  return (
    <div className="mx-auto max-w-2xl">
      <ConsolePageHeader
        title="Settings"
        description="Operate the system live. Changes take effect immediately, no restart."
      />

      {settings === null ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-40 w-full rounded-xl" />
          <Skeleton className="h-56 w-full rounded-xl" />
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {groupNames.map((group) => {
            const items = grouped.get(group)
            if (!items || items.length === 0) return null
            return (
              <Card key={group}>
                <CardHeader>
                  <CardTitle className="text-sm text-muted-foreground">{group}</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col divide-y divide-border">
                  {items.map((setting) => (
                    <SettingRow
                      key={setting.key}
                      setting={setting}
                      busy={busyKey === setting.key}
                      onWrite={(v) => void writeSetting(setting.key, v)}
                      onRevert={() => void revertSetting(setting.key)}
                    />
                  ))}
                </CardContent>
              </Card>
            )
          })}

          <DangerZone onDone={() => void load()} />
        </div>
      )}
    </div>
  )
}

function SettingRow({
  setting,
  busy,
  onWrite,
  onRevert,
}: {
  setting: RuntimeSetting
  busy: boolean
  onWrite: (value: boolean | number | string) => void
  onRevert: () => void
}) {
  const meta = SETTING_META[setting.key]
  return (
    <div className="flex items-start justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">{meta?.label ?? humanizeKey(setting.key)}</p>
          {setting.source === "override" && (
            <button
              type="button"
              onClick={onRevert}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[11px] font-medium text-accent-foreground transition-colors hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
              aria-label={`Revert ${meta?.label ?? setting.key} to default`}
            >
              <RotateCcw className="size-2.5" />
              Overridden
            </button>
          )}
        </div>
        {meta?.help && <p className="mt-1 text-xs text-muted-foreground">{meta.help}</p>}
      </div>
      <div className="shrink-0">
        <SettingControl setting={setting} busy={busy} onWrite={onWrite} />
      </div>
    </div>
  )
}

function SettingControl({
  setting,
  busy,
  onWrite,
}: {
  setting: RuntimeSetting
  busy: boolean
  onWrite: (value: boolean | number | string) => void
}) {
  if (setting.type === "bool") {
    const on = setting.value === true
    return (
      <div className="flex gap-1 rounded-lg bg-muted p-1" role="group" aria-label="Toggle">
        {[
          { label: "On", val: true },
          { label: "Off", val: false },
        ].map((opt) => (
          <Button
            key={opt.label}
            size="sm"
            variant={on === opt.val ? "secondary" : "ghost"}
            disabled={busy}
            onClick={() => on !== opt.val && onWrite(opt.val)}
          >
            {opt.label}
          </Button>
        ))}
      </div>
    )
  }

  if (setting.type === "enum" && setting.options) {
    return (
      <div className="flex gap-1 rounded-lg bg-muted p-1" role="group" aria-label="Options">
        {setting.options.map((opt) => (
          <Button
            key={opt}
            size="sm"
            variant={setting.value === opt ? "secondary" : "ghost"}
            disabled={busy}
            className="font-mono text-xs"
            onClick={() => setting.value !== opt && onWrite(opt)}
          >
            {opt}
          </Button>
        ))}
      </div>
    )
  }

  // float
  return <FloatControl setting={setting} busy={busy} onWrite={onWrite} />
}

function FloatControl({
  setting,
  busy,
  onWrite,
}: {
  setting: RuntimeSetting
  busy: boolean
  onWrite: (value: number) => void
}) {
  const [draft, setDraft] = React.useState(String(setting.value))
  React.useEffect(() => setDraft(String(setting.value)), [setting.value])

  const parsed = Number(draft)
  const valid =
    Number.isFinite(parsed) &&
    (setting.min === null || parsed >= setting.min) &&
    (setting.max === null || parsed <= setting.max)
  const dirty = parsed !== Number(setting.value)

  return (
    <div className="flex items-center gap-2">
      <Input
        type="number"
        inputMode="decimal"
        value={draft}
        min={setting.min ?? undefined}
        max={setting.max ?? undefined}
        step="0.05"
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
        className={cn("w-24 font-mono tabular-nums", !valid && "border-destructive")}
        aria-label="Value"
      />
      <Button size="sm" disabled={busy || !valid || !dirty} onClick={() => onWrite(parsed)}>
        Save
      </Button>
    </div>
  )
}

function DangerZone({ onDone }: { onDone: () => void }) {
  const [confirm, setConfirm] = React.useState("")
  const [running, setRunning] = React.useState(false)

  async function reset() {
    setRunning(true)
    try {
      const res = await api.post<{
        reseeded: Record<string, number>
        redis_flushed: Record<string, number>
      }>(`${API_V1}/console/admin/reset-demo`, { confirm })
      const customers = res.reseeded.customers ?? 0
      const txns = res.reseeded.transactions ?? 0
      toast.success("Demo data reset", {
        description: `${customers} customers, ${txns} transactions reseeded. Refresh other tabs.`,
      })
      setConfirm("")
      onDone()
    } catch (err) {
      toast.error(describeApiError(err, "Reset failed"))
    } finally {
      setRunning(false)
    }
  }

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-sm text-destructive">Danger zone</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Reset demo data: truncates and reseeds the synthetic customer cohort and flushes the
          event stream. Accounts and credentials are never touched. Type{" "}
          <span className="font-mono font-medium text-foreground">RESET</span> to confirm.
        </p>
        <div className="flex items-center gap-2">
          <Input
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="RESET"
            disabled={running}
            className="w-40 font-mono"
            aria-label="Type RESET to confirm"
          />
          <Button
            variant="destructive"
            size="sm"
            disabled={running || confirm !== "RESET"}
            onClick={() => void reset()}
          >
            {running ? "Resetting…" : "Reset demo data"}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
