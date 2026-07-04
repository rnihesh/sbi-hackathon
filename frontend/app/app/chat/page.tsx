import { Skeleton } from "@/components/ui/skeleton"

export default function ChatPage() {
  return (
    <div className="mx-auto flex h-dvh max-w-2xl flex-col gap-4 px-4 py-6 md:h-auto md:min-h-dvh sm:px-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Chat</h1>
        <p className="text-sm text-muted-foreground">
          Ask Sarathi anything about your money.
        </p>
      </div>

      <div className="flex flex-1 flex-col justify-end gap-3">
        <Skeleton className="h-16 w-2/3 self-start rounded-2xl rounded-bl-sm" />
        <Skeleton className="h-10 w-1/2 self-end rounded-2xl rounded-br-sm" />
        <Skeleton className="h-20 w-3/4 self-start rounded-2xl rounded-bl-sm" />
      </div>

      <Skeleton className="h-12 w-full shrink-0 rounded-xl" />
    </div>
  )
}
