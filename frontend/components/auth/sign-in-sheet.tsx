"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { AnimatePresence, motion } from "framer-motion"
import { startAuthentication } from "@simplewebauthn/browser"
import type { PublicKeyCredentialRequestOptionsJSON } from "@simplewebauthn/browser"
import { Fingerprint, KeyRound, Loader2, Mail } from "lucide-react"
import { toast } from "sonner"

import { api, API_URL, API_V1, ApiError } from "@/lib/api"
import { useMe, type MeResponse } from "@/lib/auth"
import { fadeIn } from "@/lib/motion"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { OtpInput } from "@/components/auth/otp-input"
import { GoogleGlyph } from "@/components/auth/google-glyph"

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

type Step = "start" | "otp-code"
type LoadingKind = "google" | "passkey" | "otp-send" | "otp-verify" | null

export function SignInSheet({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const router = useRouter()
  const { setMe } = useMe()

  const [step, setStep] = React.useState<Step>("start")
  const [email, setEmail] = React.useState("")
  const [code, setCode] = React.useState("")
  const [loading, setLoading] = React.useState<LoadingKind>(null)

  function reset() {
    setStep("start")
    setEmail("")
    setCode("")
    setLoading(null)
  }

  function handleOpenChange(next: boolean) {
    onOpenChange(next)
    if (!next) reset()
  }

  function onSignedIn(me: MeResponse) {
    setMe(me)
    toast.success("Signed in", { description: `Welcome, ${me.customer?.full_name ?? me.user.email}.` })
    handleOpenChange(false)
    router.push("/app/home")
  }

  function handleGoogle() {
    window.location.href = `${API_URL}${API_V1}/auth/google`
  }

  async function handlePasskeySignIn() {
    setLoading("passkey")
    try {
      const options = await api.post<PublicKeyCredentialRequestOptionsJSON>(
        `${API_V1}/auth/passkey/login/begin`
      )
      const credential = await startAuthentication({ optionsJSON: options })
      const me = await api.post<MeResponse>(`${API_V1}/auth/passkey/login/complete`, {
        credential,
      })
      onSignedIn(me)
    } catch (err) {
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        // User dismissed the passkey prompt - no error toast needed.
      } else {
        toast.error(err instanceof ApiError ? err.message : "Passkey sign-in failed")
      }
    } finally {
      setLoading(null)
    }
  }

  async function requestOtp() {
    if (!EMAIL_PATTERN.test(email)) {
      toast.error("Enter a valid email address")
      return
    }
    setLoading("otp-send")
    try {
      await api.post(`${API_V1}/auth/otp/send`, { email })
      setStep("otp-code")
      toast.success("Code sent", { description: `Check ${email} for a 6-digit code.` })
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't send the code")
    } finally {
      setLoading(null)
    }
  }

  function handleSendOtp(e: React.FormEvent) {
    e.preventDefault()
    void requestOtp()
  }

  async function handleVerifyOtp(candidate: string) {
    setLoading("otp-verify")
    try {
      const me = await api.post<MeResponse>(`${API_V1}/auth/otp/verify`, {
        email,
        code: candidate,
      })
      onSignedIn(me)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Invalid or expired code")
      setCode("")
    } finally {
      setLoading(null)
    }
  }

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent className="flex flex-col gap-0 sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Sign in to Sarathi</SheetTitle>
          <SheetDescription>
            One account for chat, your accounts, and nudges.
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-4 pb-6">
          <div className="flex flex-col gap-2">
            <Button
              variant="outline"
              className="w-full justify-center gap-2"
              onClick={handleGoogle}
            >
              <GoogleGlyph className="size-4" />
              Continue with Google
            </Button>
            <Button
              variant="outline"
              className="w-full justify-center gap-2"
              disabled={loading === "passkey"}
              onClick={handlePasskeySignIn}
            >
              {loading === "passkey" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Fingerprint className="size-4" />
              )}
              {loading === "passkey" ? "Waiting for passkey…" : "Sign in with passkey"}
            </Button>
          </div>

          <div className="relative flex items-center">
            <Separator className="flex-1" />
            <span className="px-3 text-xs text-muted-foreground">or continue with email</span>
            <Separator className="flex-1" />
          </div>

          <AnimatePresence mode="wait" initial={false}>
            {step === "start" ? (
              <motion.form
                key="email"
                initial="initial"
                animate="animate"
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
                variants={fadeIn}
                onSubmit={handleSendOtp}
                className="flex flex-col gap-3"
              >
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="signin-email">Email</Label>
                  <Input
                    id="signin-email"
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={loading === "otp-send"}
                    required
                  />
                </div>
                <Button type="submit" disabled={loading === "otp-send"} className="gap-2">
                  {loading === "otp-send" ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Mail data-icon="inline-start" />
                  )}
                  Send code
                </Button>
              </motion.form>
            ) : (
              <motion.div
                key="otp"
                initial="initial"
                animate="animate"
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
                variants={fadeIn}
                className="flex flex-col gap-3"
              >
                <div className="flex flex-col gap-1">
                  <Label>Verification code</Label>
                  <p className="text-xs text-muted-foreground">
                    Sent to {email}.{" "}
                    <button
                      type="button"
                      className="font-medium text-foreground underline underline-offset-2"
                      onClick={() => {
                        setStep("start")
                        setCode("")
                      }}
                    >
                      Change email
                    </button>
                  </p>
                </div>
                <OtpInput
                  value={code}
                  onChange={setCode}
                  onComplete={handleVerifyOtp}
                  disabled={loading === "otp-verify"}
                />
                <Button
                  onClick={() => handleVerifyOtp(code)}
                  disabled={loading === "otp-verify" || code.length !== 6}
                  className="gap-2"
                >
                  {loading === "otp-verify" ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <KeyRound data-icon="inline-start" />
                  )}
                  Verify &amp; sign in
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={loading === "otp-send"}
                  onClick={() => void requestOtp()}
                  className="self-center text-xs text-muted-foreground"
                >
                  Resend code
                </Button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </SheetContent>
    </Sheet>
  )
}
