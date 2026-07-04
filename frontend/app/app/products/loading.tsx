import { ProductsSkeleton } from "@/components/customer/products-skeleton"

/**
 * Route-level fallback for `/app/products` - shown instantly on navigation,
 * before the page component mounts. The header is static copy (not
 * data-dependent), so it's rendered literally here too - identical to the
 * loaded page's header, so there's no layout shift when the real page takes
 * over.
 */
export default function Loading() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Products</h1>
        <p className="text-sm text-muted-foreground">Everything SBI offers, matched to you.</p>
      </div>
      <ProductsSkeleton />
    </div>
  )
}
