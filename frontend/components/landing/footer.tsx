import Link from "next/link"

export function LandingFooter() {
  const year = new Date().getFullYear()

  return (
    <footer className="border-t border-border/70">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-3 px-4 py-8 text-xs text-muted-foreground sm:flex-row sm:justify-between sm:px-6">
        <p>&copy; {year} Sarathi. A banker in every pocket.</p>
        <nav className="flex items-center gap-4" aria-label="Legal">
          <Link href="/terms" className="transition-colors hover:text-foreground">
            Terms
          </Link>
          <Link href="/policy" className="transition-colors hover:text-foreground">
            Privacy
          </Link>
        </nav>
        <p>Built for SBI - agentic banking, done quietly.</p>
      </div>
    </footer>
  )
}
