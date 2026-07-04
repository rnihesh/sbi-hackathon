"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { AnimatePresence, motion } from "framer-motion"
import { startRegistration } from "@simplewebauthn/browser"
import type { PublicKeyCredentialCreationOptionsJSON } from "@simplewebauthn/browser"
import {
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Fingerprint,
  KeyRound,
  Languages,
  LogOut,
  Moon,
  Pencil,
  ShieldCheck,
  Smartphone,
  Sun,
  X,
} from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, describeApiError } from "@/lib/api"
import { useMe, type CustomerOut } from "@/lib/auth"
import { useTheme } from "next-themes"
import { springSoft } from "@/lib/motion"
import { cn } from "@/lib/utils"
import { formatRelativeTime, humanizeIdentifier } from "@/lib/format"
import { LANGUAGE_OPTIONS, languageLabel } from "@/lib/languages"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
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
import { Separator } from "@/components/ui/separator"
import { useFocusReturn } from "@/lib/use-focus-return"

interface PasskeyRegisterCompleteResponse {
  credential_id: string
  label: string
  transport: string
}

interface PasskeyCredential {
  id: string
  label: string
  transport: "platform" | "cross_platform"
  created_at: string
}

/** WebAuthn's own signal for "this authenticator is already registered" -
 * `startRegistration()` throws `InvalidStateError` when the platform
 * authenticator matches one of the `excludeCredentials` we sent, and some
 * browsers instead surface it as a message containing "excluded" or "already
 * registered". Either way it's not a real failure, just a no-op to explain. */
function isDuplicatePasskeyError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "InvalidStateError") return true
  const message = err instanceof Error ? err.message : ""
  return /excluded|already registered/i.test(message)
}

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "S"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

// --- Inline profile field editing -------------------------------------------
// Name/phone/city are edited in place (pencil -> input -> save/cancel) against
// `PATCH /me/preferences`. Email is the auth identity and stays read-only.

type EditableField = "full_name" | "phone" | "city"

const FIELD_LABELS: Record<EditableField, string> = {
  full_name: "Name",
  phone: "Phone",
  city: "City",
}

// Mirrors the backend's validation (`app/schemas/customer.py`) so a bad value
// gets an inline message immediately instead of a round trip for it.
const INDIAN_MOBILE_RE = /^(?:\+91[-\s]?|0)?[6-9]\d{9}$/

function validateEditValue(
  field: EditableField,
  raw: string
): { value: string | null } | { error: string } {
  const trimmed = raw.trim()
  if (field === "full_name") {
    if (trimmed.length < 2 || trimmed.length > 80) {
      return { error: "Name must be 2-80 characters" }
    }
    return { value: trimmed }
  }
  if (field === "phone") {
    if (trimmed === "") return { value: null }
    if (!INDIAN_MOBILE_RE.test(trimmed)) {
      return { error: "Enter a valid Indian mobile number" }
    }
    return { value: trimmed }
  }
  // city
  if (trimmed === "") return { value: null }
  if (trimmed.length < 2 || trimmed.length > 40) {
    return { error: "City must be 2-40 characters" }
  }
  return { value: trimmed }
}

type ProfileRow =
  | { kind: "static"; label: string; value: string | null }
  | { kind: "editable"; field: EditableField; value: string | null; placeholder: string }

export default function ProfilePage() {
  const router = useRouter()
  const { me, setMe, logout } = useMe()
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = React.useState(false)
  const [addingPasskey, setAddingPasskey] = React.useState(false)
  const [passkeys, setPasskeys] = React.useState<PasskeyCredential[] | null>(null)
  const [pendingRemoval, setPendingRemoval] = React.useState<PasskeyCredential | null>(null)
  const { captureFocus, onCloseAutoFocus } = useFocusReturn()
  const [removingPasskey, setRemovingPasskey] = React.useState(false)
  const [languagePending, setLanguagePending] = React.useState(false)
  const [editingField, setEditingField] = React.useState<EditableField | null>(null)
  const [editValue, setEditValue] = React.useState("")
  const [editError, setEditError] = React.useState<string | null>(null)
  const [savingField, setSavingField] = React.useState<EditableField | null>(null)
  const editInputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => setMounted(true), [])

  const loadPasskeys = React.useCallback(async () => {
    try {
      const res = await api.get<{ credentials: PasskeyCredential[] }>(
        `${API_V1}/auth/passkey/credentials`
      )
      setPasskeys(res.credentials)
    } catch {
      setPasskeys([])
    }
  }, [])

  React.useEffect(() => {
    void loadPasskeys()
  }, [loadPasskeys])

  React.useEffect(() => {
    if (editingField) {
      editInputRef.current?.focus()
      editInputRef.current?.select()
    }
  }, [editingField])

  if (!me) return null

  const displayName = me.customer?.full_name ?? me.user.email
  const isDark = mounted && resolvedTheme === "dark"

  const profileRows: ProfileRow[] = []
  if (me.customer) {
    profileRows.push({ kind: "editable", field: "full_name", value: me.customer.full_name, placeholder: "Add your name" })
  }
  profileRows.push({ kind: "static", label: "Email", value: me.user.email })
  if (me.customer) {
    profileRows.push({ kind: "editable", field: "phone", value: me.customer.phone, placeholder: "Add phone number" })
    profileRows.push({ kind: "editable", field: "city", value: me.customer.city, placeholder: "Add city" })
  }
  profileRows.push({ kind: "static", label: "State", value: me.customer?.state ?? null })
  profileRows.push({
    kind: "static",
    label: "Segment",
    value: me.customer?.segment ? humanizeIdentifier(me.customer.segment) : null,
  })
  profileRows.push({
    kind: "static",
    label: "Digital maturity",
    value: me.customer ? humanizeIdentifier(me.customer.digital_maturity) : null,
  })
  const visibleRows = profileRows.filter((row) => row.kind === "editable" || row.value !== null)

  function startEdit(field: EditableField, currentValue: string | null) {
    setEditingField(field)
    setEditValue(currentValue ?? "")
    setEditError(null)
  }

  function cancelEdit() {
    setEditingField(null)
    setEditError(null)
  }

  function handleEditKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault()
      void commitEdit()
    } else if (e.key === "Escape") {
      e.preventDefault()
      cancelEdit()
    }
  }

  async function commitEdit() {
    const currentMe = me
    if (!editingField || !currentMe?.customer) return
    const field = editingField
    const customer = currentMe.customer
    const validated = validateEditValue(field, editValue)
    if ("error" in validated) {
      setEditError(validated.error)
      return
    }

    let nextCustomer: CustomerOut
    let patchBody: Record<string, string | null>
    let unchanged: boolean
    if (field === "full_name") {
      const value = validated.value ?? customer.full_name
      nextCustomer = { ...customer, full_name: value }
      patchBody = { full_name: value }
      unchanged = value === customer.full_name
    } else if (field === "phone") {
      nextCustomer = { ...customer, phone: validated.value }
      patchBody = { phone: validated.value }
      unchanged = validated.value === customer.phone
    } else {
      nextCustomer = { ...customer, city: validated.value }
      patchBody = { city: validated.value }
      unchanged = validated.value === customer.city
    }

    setEditingField(null)
    setEditError(null)
    if (unchanged) return

    setSavingField(field)
    // Optimistic: show the new value immediately, roll back on failure.
    setMe({ ...currentMe, customer: nextCustomer })
    try {
      const updated = await api.patch<CustomerOut>(`${API_V1}/me/preferences`, patchBody)
      setMe({ ...currentMe, customer: updated })
      toast.success(`${FIELD_LABELS[field]} updated`)
    } catch (err) {
      setMe(currentMe)
      toast.error(describeApiError(err, `Couldn't update ${FIELD_LABELS[field].toLowerCase()}`))
    } finally {
      setSavingField(null)
    }
  }

  function renderEditableRow(field: EditableField, value: string | null, placeholder: string) {
    const label = FIELD_LABELS[field]
    const isEditing = editingField === field
    const isSaving = savingField === field

    if (!isEditing) {
      return (
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <span className="text-sm text-muted-foreground">{label}</span>
          <div className="flex items-center gap-1">
            <span
              className={cn(
                "text-sm font-medium",
                !value && "font-normal text-muted-foreground italic"
              )}
            >
              {value ?? placeholder}
            </span>
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={isSaving}
              onClick={() => startEdit(field, value)}
              aria-label={`Edit ${label}`}
            >
              <Pencil className="size-3.5" />
            </Button>
          </div>
        </div>
      )
    }

    return (
      <div className="flex flex-col gap-1.5 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-muted-foreground">{label}</span>
          <div className="flex flex-1 items-center justify-end gap-1">
            <input
              ref={editInputRef}
              type={field === "phone" ? "tel" : "text"}
              value={editValue}
              onChange={(e) => {
                setEditValue(e.target.value)
                if (editError) setEditError(null)
              }}
              onKeyDown={handleEditKeyDown}
              aria-label={`Edit ${label}`}
              aria-invalid={editError ? true : undefined}
              className="w-full min-w-0 max-w-48 rounded-md border border-input bg-background px-2 py-1 text-right text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/50"
            />
            <Button variant="ghost" size="icon-sm" onClick={() => void commitEdit()} aria-label="Save">
              <Check className="size-3.5" />
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={cancelEdit} aria-label="Cancel">
              <X className="size-3.5" />
            </Button>
          </div>
        </div>
        {editError && <p className="text-right text-xs text-destructive">{editError}</p>}
      </div>
    )
  }

  async function handleAddPasskey() {
    setAddingPasskey(true)
    try {
      const options = await api.post<PublicKeyCredentialCreationOptionsJSON>(
        `${API_V1}/auth/passkey/register/begin`
      )
      const credential = await startRegistration({ optionsJSON: options })
      const result = await api.post<PasskeyRegisterCompleteResponse>(
        `${API_V1}/auth/passkey/register/complete`,
        { credential }
      )
      toast.success("Passkey added", { description: result.label })
      await loadPasskeys()
    } catch (err) {
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        // User dismissed the platform prompt.
      } else if (isDuplicatePasskeyError(err)) {
        toast.error("A passkey for this account already exists on this device")
      } else {
        toast.error(describeApiError(err, "Couldn't add that passkey"))
      }
    } finally {
      setAddingPasskey(false)
    }
  }

  async function handleRemovePasskey() {
    if (!pendingRemoval) return
    setRemovingPasskey(true)
    try {
      await api.delete(`${API_V1}/auth/passkey/credentials/${pendingRemoval.id}`)
      setPasskeys((prev) => prev?.filter((p) => p.id !== pendingRemoval.id) ?? prev)
      toast.success("Passkey removed")
      setPendingRemoval(null)
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't remove that passkey"))
    } finally {
      setRemovingPasskey(false)
    }
  }

  async function handleLanguageChange(value: string | null) {
    if (!me?.customer || languagePending || value === me.customer.preferred_language) return
    const previousMe = me
    setLanguagePending(true)
    // Optimistic: flip the local preference immediately, roll back on failure.
    setMe({ ...me, customer: { ...me.customer, preferred_language: value } })
    try {
      const updated = await api.patch<CustomerOut>(`${API_V1}/me/preferences`, {
        preferred_language: value,
      })
      setMe({ ...previousMe, customer: updated })
      toast.success("Chat language updated", { description: languageLabel(value) })
    } catch (err) {
      setMe(previousMe)
      toast.error(describeApiError(err, "Couldn't update chat language"))
    } finally {
      setLanguagePending(false)
    }
  }

  async function handleLogout() {
    await logout()
    toast.success("Signed out")
    router.push("/")
  }

  return (
    <>
      <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Profile</h1>
          <p className="text-sm text-muted-foreground">Your details, security, and preferences.</p>
        </div>

        <div className="flex items-center gap-4">
          <Avatar size="lg">
            <AvatarFallback className="bg-accent text-accent-foreground">
              {initialsFor(displayName)}
            </AvatarFallback>
          </Avatar>
          <div>
            <p className="text-base font-medium">{displayName}</p>
            <p className="text-sm text-muted-foreground">{me.user.email}</p>
          </div>
        </div>

        <div className="rounded-xl border border-border">
          {visibleRows.map((row, i) => (
            <div key={row.kind === "editable" ? row.field : row.label}>
              {row.kind === "editable" ? (
                renderEditableRow(row.field, row.value, row.placeholder)
              ) : (
                <div className="flex items-center justify-between px-4 py-3">
                  <span className="text-sm text-muted-foreground">{row.label}</span>
                  <span className="text-sm font-medium">{row.value}</span>
                </div>
              )}
              {i < visibleRows.length - 1 && <Separator />}
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-muted-foreground">Privacy</h2>
          <Card>
            <CardContent>
              <Link
                href="/app/memory"
                className="flex items-center justify-between gap-3 text-sm font-medium"
              >
                <span className="flex items-center gap-2.5">
                  <Brain className="size-4 text-muted-foreground" />
                  What Sarathi knows about me
                </span>
                <ChevronRight className="size-4 text-muted-foreground" />
              </Link>
            </CardContent>
          </Card>
        </div>

        {me.is_staff && (
          <div className="flex flex-col gap-3 md:hidden">
            <h2 className="text-sm font-medium text-muted-foreground">Staff</h2>
            <Card>
              <CardContent>
                <Link
                  href="/console"
                  className="flex items-center justify-between gap-3 text-sm font-medium"
                >
                  <span className="flex items-center gap-2.5">
                    <ShieldCheck className="size-4 text-muted-foreground" />
                    Admin console
                  </span>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </Link>
              </CardContent>
            </Card>
          </div>
        )}

        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-muted-foreground">Security</h2>
          <Card>
            <CardContent className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">Passkeys</p>
                  <p className="text-sm text-muted-foreground">
                    Sign in without a password using Face ID, Touch ID, or a security key.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0 gap-1.5"
                  disabled={addingPasskey}
                  onClick={handleAddPasskey}
                >
                  <Fingerprint className="size-3.5" />
                  {addingPasskey ? "Adding…" : "Add passkey"}
                </Button>
              </div>

              {passkeys && passkeys.length > 0 && (
                <div className="flex flex-col border-t border-border pt-3">
                  <AnimatePresence initial={false}>
                    {passkeys.map((passkey) => {
                      const TransportIcon = passkey.transport === "platform" ? Smartphone : KeyRound
                      return (
                        <motion.div
                          key={passkey.id}
                          layout
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0, transition: { duration: 0.16 } }}
                          transition={springSoft}
                          className="flex items-center gap-3 overflow-hidden py-1.5"
                        >
                          <TransportIcon className="size-4 shrink-0 text-muted-foreground" />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium">{passkey.label}</p>
                            <p className="text-xs text-muted-foreground">
                              Added {formatRelativeTime(passkey.created_at)}
                            </p>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Remove ${passkey.label}`}
                            onClick={() => {
                              captureFocus()
                              setPendingRemoval(passkey)
                            }}
                          >
                            <X className="size-3.5" />
                          </Button>
                        </motion.div>
                      )
                    })}
                  </AnimatePresence>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-muted-foreground">Preferences</h2>
          <Card>
            <CardContent className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5 text-sm font-medium">
                  {isDark ? <Moon className="size-4" /> : <Sun className="size-4" />}
                  Appearance
                </div>
                <div className="flex gap-1 rounded-lg bg-muted p-1">
                  <Button
                    variant={!isDark ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => setTheme("light")}
                  >
                    Light
                  </Button>
                  <Button
                    variant={isDark ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => setTheme("dark")}
                  >
                    Dark
                  </Button>
                </div>
              </div>

              {me.customer && (
                <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
                  <div>
                    <div className="flex items-center gap-2.5 text-sm font-medium">
                      <Languages className="size-4" />
                      Chat language
                    </div>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      Sarathi replies in this language across chat.
                    </p>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        className="shrink-0 gap-1.5"
                        disabled={languagePending}
                      >
                        {languageLabel(me.customer.preferred_language)}
                        <ChevronDown className="size-3.5 text-muted-foreground" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                      {LANGUAGE_OPTIONS.map((option) => (
                        <DropdownMenuItem
                          key={option.label}
                          onSelect={() => void handleLanguageChange(option.value)}
                        >
                          <span className="flex-1">{option.label}</span>
                          {me.customer?.preferred_language === option.value && (
                            <Check className="size-3.5" />
                          )}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Button variant="destructive" className="gap-1.5" onClick={() => void handleLogout()}>
          <LogOut className="size-4" />
          Log out
        </Button>
      </div>

      <Dialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => {
          if (!open) setPendingRemoval(null)
        }}
      >
        <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
          <DialogHeader>
            <DialogTitle>Remove passkey</DialogTitle>
            <DialogDescription>
              {pendingRemoval &&
                `"${pendingRemoval.label}" will no longer be able to sign in to this account.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingRemoval(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={removingPasskey}
              onClick={() => void handleRemovePasskey()}
            >
              {removingPasskey ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
