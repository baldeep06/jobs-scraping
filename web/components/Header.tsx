import Link from "next/link";

export function Header() {
  return (
    <header className="border-b border-divider bg-surface">
      <nav className="mx-auto flex h-14 max-w-[1280px] items-center justify-between px-4 md:px-8">
        <Link href="/us" className="font-display text-lg font-semibold tracking-tight">
          Intern Radar
        </Link>
        <div className="flex gap-1 text-[13px] font-medium text-slate">
          <Link href="/us" className="rounded-nav px-3 py-1.5 hover:bg-canvas hover:text-ink">
            Jobs
          </Link>
          <Link href="/status" className="rounded-nav px-3 py-1.5 hover:bg-canvas hover:text-ink">
            Status
          </Link>
          <a
            href="https://github.com/baldeep06/jobs-scraping"
            className="rounded-nav px-3 py-1.5 hover:bg-canvas hover:text-ink"
          >
            Source
          </a>
        </div>
      </nav>
    </header>
  );
}
