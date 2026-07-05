"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { CalendarDays, MoreVertical, PartyPopper, Plus, Target } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import { formatPaise } from "@/lib/format"
import { springSoft } from "@/lib/motion"
import type { Goal, GoalListResponse } from "@/lib/customer-types"
import { useFocusReturn } from "@/lib/use-focus-return"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"

const NAME_MAX = 80

function formatTargetDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

/**
 * Savings goals surface on the customer home. Progress is honest (see the API's
 * model): it reflects how much the total balance has grown since a goal was set,
 * so concurrent goals share that growth - the caption says so plainly. Goals a
 * customer reaches flip to an achieved state and stay until archived.
 */
export function GoalsSection() {
  const [data, setData] = React.useState<GoalListResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [name, setName] = React.useState("")
  const [amount, setAmount] = React.useState("")
  const [targetDate, setTargetDate] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [archivingId, setArchivingId] = React.useState<string | null>(null)
  const { captureFocus, onCloseAutoFocus } = useFocusReturn()

  const fetchGoals = React.useCallback(async () => {
    try {
      const res = await api.get<GoalListResponse>(`${API_V1}/me/goals`)
      setData(res)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your goals.")
      setData({ goals: [], active_count: 0, max_active: 5 })
    }
  }, [])

  React.useEffect(() => {
    void fetchGoals()
  }, [fetchGoals])

  const atCap = data !== null && data.active_count >= data.max_active

  function resetForm() {
    setName("")
    setAmount("")
    setTargetDate("")
  }

  async function handleCreate() {
    const trimmed = name.trim()
    const rupees = Number(amount)
    if (!trimmed || !Number.isFinite(rupees) || rupees <= 0 || submitting) return
    setSubmitting(true)
    try {
      await api.post<Goal>(`${API_V1}/me/goals`, {
        name: trimmed,
        target_paise: Math.round(rupees * 100),
        ...(targetDate ? { target_date: targetDate } : {}),
      })
      toast.success("Goal set", {
        description: `Sarathi will track your progress toward "${trimmed}".`,
      })
      setDialogOpen(false)
      resetForm()
      await fetchGoals()
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't set that goal"))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleArchive(goal: Goal) {
    setArchivingId(goal.id)
    try {
      await api.patch<Goal>(`${API_V1}/me/goals/${goal.id}`, { status: "archived" })
      toast.success("Goal archived")
      await fetchGoals()
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't archive that goal"))
    } finally {
      setArchivingId(null)
    }
  }

  const goals = data?.goals ?? null
  const canSubmit = name.trim().length > 0 && Number(amount) > 0 && !submitting

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">Goals</h2>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={atCap}
          title={atCap ? "Archive a goal to add another (max 5 active)" : undefined}
          onClick={() => {
            captureFocus()
            setDialogOpen(true)
          }}
        >
          <Plus className="size-3.5" />
          New goal
        </Button>
      </div>

      {error && <p className="text-sm text-muted-foreground">{error}</p>}

      {goals === null ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ) : goals.length === 0 ? (
        <Card>
          <CardContent className="flex items-center gap-3 text-sm text-muted-foreground">
            <Target className="size-4 shrink-0 text-primary" />
            Set a goal and Sarathi will track it.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-col gap-3">
            <AnimatePresence initial={false}>
              {goals.map((goal) => (
                <GoalCard
                  key={goal.id}
                  goal={goal}
                  onArchive={() => void handleArchive(goal)}
                  archiving={archivingId === goal.id}
                />
              ))}
            </AnimatePresence>
          </div>
          <p className="text-xs text-muted-foreground">
            Progress reflects balance growth since the goal was set.
          </p>
        </>
      )}

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open)
          if (!open) resetForm()
        }}
      >
        <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
          <DialogHeader>
            <DialogTitle>New savings goal</DialogTitle>
            <DialogDescription>
              Sarathi tracks progress as your balance grows after you set it.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="goal-name">What are you saving for?</Label>
              <Input
                id="goal-name"
                value={name}
                maxLength={NAME_MAX}
                placeholder="e.g. Emergency fund"
                onChange={(e) => setName(e.target.value.slice(0, NAME_MAX))}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && canSubmit) {
                    e.preventDefault()
                    void handleCreate()
                  }
                }}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="goal-amount">Target amount (₹)</Label>
              <Input
                id="goal-amount"
                type="number"
                inputMode="numeric"
                min={1}
                value={amount}
                placeholder="50000"
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="goal-date">Target date (optional)</Label>
              <Input
                id="goal-date"
                type="date"
                value={targetDate}
                onChange={(e) => setTargetDate(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button disabled={!canSubmit} onClick={() => void handleCreate()}>
              {submitting ? "Setting..." : "Set goal"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function GoalCard({
  goal,
  onArchive,
  archiving,
}: {
  goal: Goal
  onArchive: () => void
  archiving: boolean
}) {
  const achieved = goal.status === "achieved"
  // Once achieved, a goal stays visually complete even if the balance later dips
  // (the status is the source of truth for "done", not the live balance).
  const pct = achieved ? 100 : Math.max(0, Math.min(100, goal.pct))
  const shown = achieved ? goal.target_paise : Math.min(goal.progress_paise, goal.target_paise)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, transition: { duration: 0.18 } }}
      transition={springSoft}
    >
      <Card className={achieved ? "border-primary/30 bg-accent" : undefined}>
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              {achieved && <PartyPopper className="size-4 shrink-0 text-primary" />}
              <p className="truncate text-sm font-medium">{goal.name}</p>
              {achieved && (
                <Badge variant="default" className="h-4 shrink-0 px-1.5 text-[10px]">
                  Achieved
                </Badge>
              )}
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Goal options"
                  disabled={archiving}
                  className="-mt-1 -mr-1 shrink-0"
                >
                  <MoreVertical className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => onArchive()}>Archive</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <motion.div
              className="h-full rounded-full bg-primary"
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={springSoft}
            />
          </div>

          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="font-mono tabular-nums text-muted-foreground">
              {formatPaise(shown)} of {formatPaise(goal.target_paise)}
            </span>
            <div className="flex items-center gap-2">
              {goal.target_date && !achieved && (
                <span className="flex items-center gap-1 text-muted-foreground">
                  <CalendarDays className="size-3" />
                  {formatTargetDate(goal.target_date)}
                </span>
              )}
              <span className="font-medium text-foreground">{Math.round(pct)}%</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  )
}
