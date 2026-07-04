export function LandingFooter() {
  const year = new Date().getFullYear()

  return (
    <footer className="border-t border-border/70">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-2 px-4 py-8 text-xs text-muted-foreground sm:flex-row sm:justify-between sm:px-6">
        <p>&copy; {year} Sarathi. A banker in every pocket.</p>
        <p>Built for SBI &mdash; agentic banking, done quietly.</p>
      </div>
    </footer>
  )
}
