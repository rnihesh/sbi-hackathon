"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import {
  CalendarDays,
  Landmark,
  MoreVertical,
  Pause,
  PiggyBank,
  Play,
  Plus,
  Repeat,
  Target,
  X,
} from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import { formatPaise, humanizeIdentifier } from "@/lib/format"
import { springSoft } from "@/lib/motion"
import type {
  DashboardAccount,
  Goal,
  GoalListResponse,
  StandingInstruction,
  StandingInstructionListResponse,
} from "@/lib/customer-types"
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

type Purpose = "goal" | "fd" | "savings"
type Cadence = "weekly" | "monthly"

const PURPOSE_OPTIONS: { value: Purpose; label: string }[] = [
  { value: "goal", label: "Goal" },
  { value: "fd", label: "Fixed deposit" },
  { value: "savings", label: "Savings" },
]

const CADENCE_OPTIONS: { value: Cadence; label: string }[] = [
  { value: "monthly", label: "Monthly" },
  { value: "weekly", label: "Weekly" },
]

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

function purposeLabel(si: StandingInstruction): string {
  if (si.purpose === "goal") return si.goal_name ?? "Savings goal"
  if (si.purpose === "fd") return "Fixed deposit"
  return "Savings"
}

function PurposeIcon({ purpose }: { purpose: Purpose }) {
  const Icon = purpose === "goal" ? Target : purpose === "fd" ? Landmark : PiggyBank
  return <Icon className="size-4 shrink-0 text-primary" />
}

const STATUS_META: Record<
  StandingInstruction["status"],
  { label: string; variant: "default" | "secondary" | "outline" }
> = {
  active: { label: "Active", variant: "default" },
  paused: { label: "Paused", variant: "secondary" },
  completed: { label: "Completed", variant: "outline" },
  cancelled: { label: "Cancelled", variant: "outline" },
}

/**
 * Auto-transfers surface on the customer home, sitting under Goals. Each row is a
 * real recurring standing instruction: the backend posts genuine ledger debits on
 * the cadence (never fabricated), keeping a small cushion in the account. Customers
 * pause, resume, or cancel from the kebab; new transfers open the dialog below.
 */
export function StandingInstructionsSection({
  accounts,
}: {
  accounts: DashboardAccount[]
}) {
  const [data, setData] = React.useState<StandingInstructionListResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [goals, setGoals] = React.useState<Goal[]>([])
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [busyId, setBusyId] = React.useState<string | null>(null)
  const { captureFocus, onCloseAutoFocus } = useFocusReturn()

  const activeAccounts = React.useMemo(
    () => accounts.filter((a) => a.status !== "closed"),
    [accounts]
  )

  const fetchInstructions = React.useCallback(async () => {
    try {
      const res = await api.get<StandingInstructionListResponse>(
        `${API_V1}/me/standing-instructions`
      )
      setData(res)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your auto-transfers.")
      setData({ instructions: [], active_count: 0, max_active: 5 })
    }
  }, [])

  React.useEffect(() => {
    void fetchInstructions()
  }, [fetchInstructions])

  const loadGoals = React.useCallback(async () => {
    try {
      const res = await api.get<GoalListResponse>(`${API_V1}/me/goals`)
      setGoals(res.goals.filter((g) => g.status === "active"))
    } catch {
      setGoals([])
    }
  }, [])

  const atCap = data !== null && data.active_count >= data.max_active
  const canCreate = activeAccounts.length > 0 && !atCap

  function openDialog() {
    captureFocus()
    void loadGoals()
    setDialogOpen(true)
  }

  async function handleAction(si: StandingInstruction, action: "pause" | "resume" | "cancel") {
    setBusyId(si.id)
    try {
      await api.patch<StandingInstruction>(
        `${API_V1}/me/standing-instructions/${si.id}`,
        { action }
      )
      toast.success(
        action === "cancel"
          ? "Auto-transfer cancelled"
          : action === "pause"
            ? "Auto-transfer paused"
            : "Auto-transfer resumed"
      )
      await fetchInstructions()
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't update that auto-transfer"))
    } finally {
      setBusyId(null)
    }
  }

  const instructions = data?.instructions ?? null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">Auto-transfers</h2>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={!canCreate}
          title={
            activeAccounts.length === 0
              ? "Open an account to set up an auto-transfer"
              : atCap
                ? "Pause or cancel one to add another (max 5)"
                : undefined
          }
          onClick={openDialog}
        >
          <Plus className="size-3.5" />
          New auto-transfer
        </Button>
      </div>

      {error && <p className="text-sm text-muted-foreground">{error}</p>}

      {instructions === null ? (
        <Skeleton className="h-16 w-full rounded-xl" />
      ) : instructions.length === 0 ? (
        <Card>
          <CardContent className="flex items-center gap-3 text-sm text-muted-foreground">
            <Repeat className="size-4 shrink-0 text-primary" />
            Set up a recurring transfer and Sarathi saves for you automatically.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
            <AnimatePresence initial={false}>
              {instructions.map((si) => (
                <InstructionRow
                  key={si.id}
                  si={si}
                  busy={busyId === si.id}
                  onAction={(action) => void handleAction(si, action)}
                />
              ))}
            </AnimatePresence>
          </div>
          <p className="text-xs text-muted-foreground">
            Each run posts a real transfer while keeping a ₹1,000 cushion in your account.
          </p>
        </>
      )}

      <NewTransferDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onCloseAutoFocus={onCloseAutoFocus}
        accounts={activeAccounts}
        goals={goals}
        onCreated={fetchInstructions}
      />
    </div>
  )
}

function InstructionRow({
  si,
  busy,
  onAction,
}: {
  si: StandingInstruction
  busy: boolean
  onAction: (action: "pause" | "resume" | "cancel") => void
}) {
  const status = STATUS_META[si.status]
  const cadenceWord = si.cadence === "monthly" ? "month" : "week"
  const terminal = si.status === "completed" || si.status === "cancelled"

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, transition: { duration: 0.18 } }}
      transition={springSoft}
      className="flex items-center gap-3 px-4 py-3"
    >
      <PurposeIcon purpose={si.purpose} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium">
            {formatPaise(si.amount_paise)}
            <span className="text-muted-foreground"> / {cadenceWord}</span>
          </p>
          <Badge variant={status.variant} className="h-4 shrink-0 px-1.5 text-[10px]">
            {status.label}
          </Badge>
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {purposeLabel(si)}
          {!terminal && (
            <>
              {" · "}
              <span className="inline-flex items-center gap-1 align-middle">
                <CalendarDays className="size-3" />
                Next {formatDate(si.next_run_date)}
              </span>
            </>
          )}
        </p>
      </div>

      {!terminal && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Auto-transfer options"
              disabled={busy}
              className="shrink-0"
            >
              <MoreVertical className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {si.status === "active" ? (
              <DropdownMenuItem onSelect={() => onAction("pause")}>
                <Pause className="size-3.5" />
                Pause
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={() => onAction("resume")}>
                <Play className="size-3.5" />
                Resume
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => onAction("cancel")}
            >
              <X className="size-3.5" />
              Cancel
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </motion.div>
  )
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className="inline-flex w-full rounded-lg border border-input p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`flex-1 rounded-md px-2 py-1 text-sm font-medium transition-colors ${
            value === opt.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30"

function NewTransferDialog({
  open,
  onOpenChange,
  onCloseAutoFocus,
  accounts,
  goals,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCloseAutoFocus: (e: Event) => void
  accounts: DashboardAccount[]
  goals: Goal[]
  onCreated: () => Promise<void>
}) {
  const [accountId, setAccountId] = React.useState("")
  const [purpose, setPurpose] = React.useState<Purpose>("goal")
  const [goalId, setGoalId] = React.useState("")
  const [amount, setAmount] = React.useState("")
  const [cadence, setCadence] = React.useState<Cadence>("monthly")
  const [startDate, setStartDate] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)

  // Seed defaults whenever the dialog opens or its option lists change.
  React.useEffect(() => {
    if (!open) return
    setAccountId((prev) => prev || (accounts[0]?.id ?? ""))
  }, [open, accounts])

  React.useEffect(() => {
    if (purpose === "goal") setGoalId((prev) => prev || (goals[0]?.id ?? ""))
  }, [purpose, goals])

  function reset() {
    setAccountId("")
    setPurpose("goal")
    setGoalId("")
    setAmount("")
    setCadence("monthly")
    setStartDate("")
  }

  const selectedAccount = accounts.find((a) => a.id === accountId)
  const rupees = Number(amount)
  const maxRupees = selectedAccount ? Math.floor(selectedAccount.balance_paise / 100 / 2) : 0
  const amountValid =
    Number.isFinite(rupees) && rupees > 0 && (!selectedAccount || rupees <= maxRupees)
  const goalValid = purpose !== "goal" || goalId !== ""
  const canSubmit = accountId !== "" && amountValid && goalValid && !submitting

  async function handleCreate() {
    if (!canSubmit) return
    setSubmitting(true)
    try {
      await api.post<StandingInstruction>(`${API_V1}/me/standing-instructions`, {
        from_account_id: accountId,
        purpose,
        ...(purpose === "goal" ? { goal_id: goalId } : {}),
        amount_paise: Math.round(rupees * 100),
        cadence,
        ...(startDate ? { start_date: startDate } : {}),
      })
      toast.success("Auto-transfer set up", {
        description: "Sarathi will run it automatically on schedule.",
      })
      onOpenChange(false)
      reset()
      await onCreated()
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't set up that auto-transfer"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) reset()
      }}
    >
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>New auto-transfer</DialogTitle>
          <DialogDescription>
            A recurring transfer Sarathi runs for you. Pause or cancel it anytime.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="si-account">From account</Label>
            <select
              id="si-account"
              className={selectClass}
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {humanizeIdentifier(a.type)} · {formatPaise(a.balance_paise)}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Save toward</Label>
            <Segmented options={PURPOSE_OPTIONS} value={purpose} onChange={setPurpose} />
          </div>

          {purpose === "goal" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="si-goal">Goal</Label>
              {goals.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No active goals yet - set a goal above first, or choose Savings.
                </p>
              ) : (
                <select
                  id="si-goal"
                  className={selectClass}
                  value={goalId}
                  onChange={(e) => setGoalId(e.target.value)}
                >
                  {goals.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="si-amount">Amount (₹)</Label>
            <Input
              id="si-amount"
              type="number"
              inputMode="numeric"
              min={1}
              value={amount}
              placeholder="2000"
              onChange={(e) => setAmount(e.target.value)}
            />
            {selectedAccount && (
              <p className="text-xs text-muted-foreground">
                Up to {formatPaise(maxRupees * 100)} per run (half this account&apos;s balance).
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>How often</Label>
            <Segmented options={CADENCE_OPTIONS} value={cadence} onChange={setCadence} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="si-start">Start date (optional)</Label>
            <Input
              id="si-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!canSubmit} onClick={() => void handleCreate()}>
            {submitting ? "Setting up..." : "Set up transfer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
