"use client"

import * as React from "react"
import { motion } from "framer-motion"
import {
  Check,
  Clock,
  CreditCard,
  Landmark,
  Package,
  Shield,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"

import { api, API_V1, ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { humanizeIdentifier } from "@/lib/format"
import { staggerContainer, staggerItem } from "@/lib/motion"
import type {
  ProductApplyResponse,
  ProductBrowseItem,
  ProductsBrowseResponse,
} from "@/lib/product-types"
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
import { Skeleton } from "@/components/ui/skeleton"
import { SarathiMark } from "@/components/brand/logo"

interface CategoryMeta {
  label: string
  icon: LucideIcon
  order: number
}

// Matches the real catalog's categories (backend/app/services/products.py) -
// unrecognized categories still render, just without a curated label/icon/order.
const CATEGORY_META: Record<string, CategoryMeta> = {
  deposit: { label: "Deposits", icon: Wallet, order: 0 },
  investment: { label: "Investments", icon: TrendingUp, order: 1 },
  insurance: { label: "Insurance", icon: Shield, order: 2 },
  card: { label: "Cards", icon: CreditCard, order: 3 },
  loan: { label: "Loans", icon: Landmark, order: 4 },
}

function categoryMeta(category: string): CategoryMeta {
  return (
    CATEGORY_META[category] ?? { label: humanizeIdentifier(category), icon: Package, order: 99 }
  )
}

export default function ProductsPage() {
  const [products, setProducts] = React.useState<ProductBrowseItem[] | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [justRequested, setJustRequested] = React.useState<Set<string>>(new Set())
  const [busyCode, setBusyCode] = React.useState<string | null>(null)
  const [confirmItem, setConfirmItem] = React.useState<ProductBrowseItem | null>(null)

  const load = React.useCallback(async () => {
    try {
      const res = await api.get<ProductsBrowseResponse>(`${API_V1}/me/products`)
      setProducts(res.products)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load products.")
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    setLoading(true)
    void load()
  }, [load])

  async function handleApply(item: ProductBrowseItem) {
    setConfirmItem(null)
    setBusyCode(item.code)
    try {
      await api.post<ProductApplyResponse>(`${API_V1}/me/products/${item.code}/apply`)
      setJustRequested((prev) => new Set(prev).add(item.code))
      toast.success("Request sent", {
        description: `A relationship manager will review your request for ${item.name}.`,
      })
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't send that request")
    } finally {
      setBusyCode(null)
    }
  }

  const groups = React.useMemo(() => {
    if (!products) return []
    const byCategory = new Map<string, ProductBrowseItem[]>()
    for (const item of products) {
      const list = byCategory.get(item.category) ?? []
      list.push(item)
      byCategory.set(item.category, list)
    }
    return Array.from(byCategory.entries())
      .map(([category, items]) => ({ category, meta: categoryMeta(category), items }))
      .sort((a, b) => a.meta.order - b.meta.order)
  }, [products])

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Products</h1>
        <p className="text-sm text-muted-foreground">Everything SBI offers, matched to you.</p>
      </div>

      {error && (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{error}</CardContent>
        </Card>
      )}

      {loading ? (
        <ProductsSkeleton />
      ) : products !== null && products.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <Package className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">No products to show right now</p>
          <p className="max-w-xs text-sm text-muted-foreground">
            Check back later - Sarathi is still setting up your catalog.
          </p>
        </div>
      ) : products !== null ? (
        <motion.div
          initial="initial"
          animate="animate"
          variants={staggerContainer}
          className="flex flex-col gap-8"
        >
          {groups.map((group) => (
            <motion.div key={group.category} variants={staggerItem} className="flex flex-col gap-3">
              <h2 className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <group.meta.icon className="size-4" />
                {group.meta.label}
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {group.items.map((item) => (
                  <ProductCard
                    key={item.code}
                    item={item}
                    requested={item.pending || justRequested.has(item.code)}
                    busy={busyCode === item.code}
                    onApply={() => setConfirmItem(item)}
                  />
                ))}
              </div>
            </motion.div>
          ))}
        </motion.div>
      ) : null}

      <Dialog open={confirmItem !== null} onOpenChange={(open) => !open && setConfirmItem(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Request {confirmItem?.name}</DialogTitle>
            <DialogDescription>
              A relationship manager will review your request before it&apos;s approved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmItem(null)}>
              Cancel
            </Button>
            <Button
              disabled={busyCode !== null}
              onClick={() => confirmItem && void handleApply(confirmItem)}
            >
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ProductCard({
  item,
  requested,
  busy,
  onApply,
}: {
  item: ProductBrowseItem
  requested: boolean
  busy: boolean
  onApply: () => void
}) {
  return (
    <motion.div variants={staggerItem} className="h-full">
      <Card className={cn("h-full", !item.eligible && "opacity-60")}>
        <CardContent className="flex h-full flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <span className="text-sm font-medium">{item.name}</span>
            {item.held && (
              <Badge variant="secondary" className="shrink-0 gap-1">
                <Check className="size-3" />
                Held
              </Badge>
            )}
          </div>

          {item.description && (
            <p className="text-sm text-muted-foreground">{item.description}</p>
          )}

          {item.eligible && item.reason && (
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground italic">
              <SarathiMark className="mt-0.5 size-3 shrink-0 text-primary" />
              <span>Why for you: {item.reason}</span>
            </p>
          )}
          {!item.eligible && (
            <p className="text-xs text-muted-foreground">
              {item.reason ?? "Not available for your profile yet"}
            </p>
          )}

          {item.eligible && !item.held && (
            <div className="mt-auto pt-1">
              {requested ? (
                <Badge variant="outline" className="gap-1.5">
                  <Clock className="size-3" />
                  Requested
                </Badge>
              ) : (
                <Button size="sm" variant="outline" disabled={busy} onClick={onApply}>
                  {busy ? "Sending…" : "Apply"}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  )
}

function ProductsSkeleton() {
  return (
    <div className="flex flex-col gap-8">
      {Array.from({ length: 2 }).map((_, g) => (
        <div key={g} className="flex flex-col gap-3">
          <Skeleton className="h-4 w-24" />
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <Card key={i}>
                <CardContent className="flex flex-col gap-2">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-1/2" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
