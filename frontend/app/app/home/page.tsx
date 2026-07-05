"use client"

import * as React from "react"
import Link from "next/link"
import { motion } from "framer-motion"
import { ArrowDownLeft, ArrowUpRight, Bell, ChevronRight, TrendingUp } from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError, describeApiError } from "@/lib/api"
import { useMe } from "@/lib/auth"
import { staggerContainer, staggerItem } from "@/lib/motion"
import { formatPaise, formatRelativeTime, humanizeIdentifier, timeOfDayGreeting } from "@/lib/format"
import { categoryIcon } from "@/lib/category-icons"
import type { DashboardResponse } from "@/lib/customer-types"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { GoalsSection } from "@/components/customer/goals-section"
import { StandingInstructionsSection } from "@/components/customer/standing-instructions-section"
import { HomeSkeleton } from "@/components/customer/home-skeleton"
import { WelcomeCard } from "@/components/customer/welcome-card"

export default function HomePage() {
  const { me } = useMe()
  const [dashboard, setDashboard] = React.useState<DashboardResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [loadingDemo, setLoadingDemo] = React.useState(false)

  const fetchDashboard = React.useCallback(async () => {
    try {
      const res = await api.get<DashboardResponse>(`${API_V1}/me/dashboard`)
      setDashboard(res)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your dashboard.")
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    setLoading(true)
    void fetchDashboard()
  }, [fetchDashboard])

  async function handleLoadDemoActivity() {
    setLoadingDemo(true)
    try {
      const res = await api.post<{ transactions: number; months: number }>(
        `${API_V1}/me/demo-activity`
      )
      toast.success("Demo activity loaded", {
        description: `${res.transactions} transactions over ${res.months} months. Sarathi's agents are now watching your account.`,
      })
      await fetchDashboard()
    } catch (err) {
      toast.error(describeApiError(err, "Couldn't load demo activity"))
    } finally {
      setLoadingDemo(false)
    }
  }

  const firstName = (dashboard?.customer.full_name ?? me?.customer?.full_name ?? "").split(" ")[0]
  const greeting = firstName ? `${timeOfDayGreeting()}, ${firstName}` : timeOfDayGreeting()

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{greeting}</h1>
        <p className="text-sm text-muted-foreground">Your accounts, at a glance.</p>
      </div>

      {error && (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {loading ? (
        <HomeSkeleton />
      ) : dashboard ? (
        <motion.div initial="initial" animate="animate" variants={staggerContainer} className="flex flex-col gap-6">
          {dashboard.unseen_nudges > 0 && (
            <motion.div variants={staggerItem}>
              <Link
                href="/app/nudges"
                className="flex items-center justify-between gap-3 rounded-xl border border-primary/20 bg-accent px-4 py-3 text-accent-foreground transition-colors hover:bg-accent/80"
              >
                <span className="flex items-center gap-2.5 text-sm font-medium">
                  <Bell className="size-4" />
                  {dashboard.unseen_nudges} new {dashboard.unseen_nudges === 1 ? "nudge" : "nudges"} for you
                </span>
                <ChevronRight className="size-4" />
              </Link>
            </motion.div>
          )}

          {dashboard.accounts.length > 0 ? (
            <motion.div variants={staggerItem}>
              <AccountsCard accounts={dashboard.accounts} />
            </motion.div>
          ) : (
            <motion.div variants={staggerItem}>
              <WelcomeCard
                loadingDemo={loadingDemo}
                onLoadDemoActivity={() => void handleLoadDemoActivity()}
              />
            </motion.div>
          )}

          <motion.div variants={staggerItem} className="flex flex-col gap-6">
            <GoalsSection />
            <StandingInstructionsSection accounts={dashboard.accounts} />
          </motion.div>

          <motion.div variants={staggerItem} className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-muted-foreground">Recent activity</h2>
              <Link
                href="/app/insights"
                className="flex items-center gap-1.5 text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
              >
                <TrendingUp className="size-3.5" />
                Insights
              </Link>
            </div>
            {dashboard.recent_transactions.length === 0 ? (
              <EmptyPanel label="No transactions yet - they'll show up here as they happen." />
            ) : (
              <div className="divide-y divide-border rounded-xl border border-border">
                {dashboard.recent_transactions.map((txn) => {
                  const Icon = categoryIcon(txn.category)
                  const signed = txn.direction === "credit"
                  return (
                    <div key={txn.id} className="flex items-center gap-3 px-4 py-3">
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted">
                        <Icon className="size-4 text-muted-foreground" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {txn.merchant ?? txn.description ?? humanizeIdentifier(txn.channel)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatRelativeTime(txn.ts)} &middot; {humanizeIdentifier(txn.channel)}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1 font-mono text-sm tabular-nums">
                        {signed ? (
                          <ArrowDownLeft className="size-3.5 text-muted-foreground" />
                        ) : (
                          <ArrowUpRight className="size-3.5 text-muted-foreground" />
                        )}
                        {signed ? "+" : "-"}
                        {formatPaise(Math.abs(txn.amount_paise))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </motion.div>

          <motion.div variants={staggerItem} className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-muted-foreground">Holdings</h2>
              <Link
                href="/app/products"
                className="text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
              >
                Browse products
              </Link>
            </div>
            {dashboard.holdings.length === 0 ? (
              <EmptyPanel label="No products yet - Sarathi will suggest some as you chat." />
            ) : (
              <div className="flex flex-wrap gap-2">
                {dashboard.holdings.map((holding) => (
                  <span
                    key={holding.id}
                    className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs"
                  >
                    {holding.product.name}
                    <Badge variant={holding.status === "active" ? "default" : "secondary"} className="h-4 px-1.5 text-[10px] capitalize">
                      {holding.status}
                    </Badge>
                  </span>
                ))}
              </div>
            )}
          </motion.div>
        </motion.div>
      ) : null}
    </div>
  )
}

function AccountsCard({ accounts }: { accounts: DashboardResponse["accounts"] }) {
  const primary = accounts[0]
  const rest = accounts.slice(1)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Balance</span>
          <Badge variant="secondary" className="capitalize">
            {humanizeIdentifier(primary.type)}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <p className="font-mono text-3xl font-semibold tabular-nums">{formatPaise(primary.balance_paise)}</p>
        <p className="text-sm text-muted-foreground capitalize">{primary.status}</p>
      </CardContent>
      {rest.length > 0 && (
        <CardContent className="grid gap-3 border-t pt-4 sm:grid-cols-2">
          {rest.map((account) => (
            <div key={account.id} className="space-y-1">
              <p className="text-xs text-muted-foreground capitalize">{humanizeIdentifier(account.type)}</p>
              <p className="font-mono text-lg font-medium tabular-nums">{formatPaise(account.balance_paise)}</p>
            </div>
          ))}
        </CardContent>
      )}
    </Card>
  )
}

function EmptyPanel({ label }: { label: string }) {
  return (
    <Card>
      <CardContent className="text-sm text-muted-foreground">{label}</CardContent>
    </Card>
  )
}
