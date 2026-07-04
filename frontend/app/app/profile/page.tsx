"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { startRegistration } from "@simplewebauthn/browser"
import type { PublicKeyCredentialCreationOptionsJSON } from "@simplewebauthn/browser"
import { Fingerprint, LogOut, Moon, Sun } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError } from "@/lib/api"
import { useMe } from "@/lib/auth"
import { useTheme } from "next-themes"
import { humanizeIdentifier } from "@/lib/format"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

interface PasskeyRegisterCompleteResponse {
  credential_id: string
  label: string
  transport: string
}

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "S"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export default function ProfilePage() {
  const router = useRouter()
  const { me, logout } = useMe()
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = React.useState(false)
  const [addingPasskey, setAddingPasskey] = React.useState(false)

  React.useEffect(() => setMounted(true), [])

  if (!me) return null

  const displayName = me.customer?.full_name ?? me.user.email
  const isDark = mounted && resolvedTheme === "dark"

  const profileFields: Array<[string, string | null]> = [
    ["Email", me.user.email],
    ["Phone", me.customer?.phone ?? null],
    ["City", me.customer?.city ?? null],
    ["State", me.customer?.state ?? null],
    ["Segment", me.customer?.segment ? humanizeIdentifier(me.customer.segment) : null],
    ["Digital maturity", me.customer ? humanizeIdentifier(me.customer.digital_maturity) : null],
  ]

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
    } catch (err) {
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        // User dismissed the platform prompt.
      } else {
        toast.error(err instanceof ApiError ? err.message : "Couldn't add that passkey")
      }
    } finally {
      setAddingPasskey(false)
    }
  }

  async function handleLogout() {
    await logout()
    toast.success("Signed out")
    router.push("/")
  }

  return (
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
        {profileFields
          .filter(([, value]) => value)
          .map(([label, value], i, arr) => (
            <div key={label}>
              <div className="flex items-center justify-between px-4 py-3">
                <span className="text-sm text-muted-foreground">{label}</span>
                <span className="text-sm font-medium">{value}</span>
              </div>
              {i < arr.length - 1 && <Separator />}
            </div>
          ))}
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Security</h2>
        <Card>
          <CardContent className="flex items-center justify-between gap-3 pt-4">
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
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Preferences</h2>
        <Card>
          <CardContent className="flex items-center justify-between gap-3 pt-4">
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
          </CardContent>
        </Card>
      </div>

      <Button variant="destructive" className="gap-1.5" onClick={() => void handleLogout()}>
        <LogOut className="size-4" />
        Log out
      </Button>
    </div>
  )
}
