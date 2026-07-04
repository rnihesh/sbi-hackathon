import { cn } from "@/lib/utils"

/*
  Sarathi mark: forward chevrons. Guidance as pure direction - the leading
  chevron solid, the trailing one echoed at reduced opacity, like the guide
  a step ahead of you. Draws in currentColor so it inherits text color;
  pass className="text-primary" for the clay version.
*/
export function SarathiMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("size-5", className)}
      aria-hidden
    >
      <path d="M6 5l7 7-7 7" />
      <path d="M13 5l7 7-7 7" opacity="0.45" />
    </svg>
  )
}

export function SarathiLogo({
  className,
  markClassName,
  children = "Sarathi",
}: {
  className?: string
  markClassName?: string
  children?: React.ReactNode
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <SarathiMark className={cn("text-primary", markClassName)} />
      <span className="font-semibold tracking-tight">{children}</span>
    </span>
  )
}
