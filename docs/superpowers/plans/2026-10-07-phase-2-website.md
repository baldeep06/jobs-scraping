# Phase 2 — Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Next.js site on Vercel that shows the scraped internships as a filterable table with US / Canada tabs, styled per `design/DESIGN.md`, reading Supabase with the read-only anon key.

**Architecture:** A Next.js 16 App Router app in `web/`. Each request renders `/[region]` on the server: URL query params → `parseFilters()` → `applyFilters()` on a supabase-js query against the `jobs_feed` view → presentational components. Pure logic (`lib/`) is unit-tested with Vitest. Components are plain (non-async) React rendered to static markup in tests. No client JavaScript is needed in Phase 2: filters are a GET form, and row details use `<details>`.

**Tech Stack:** Next.js 16 (App Router, TypeScript), React 19, Tailwind CSS v4, @supabase/supabase-js 2, Vitest, pnpm 11, Vercel Hobby.

**Spec:** `docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md` — this plan implements §8 Website for spec §11 phase 2. The Realtime banner, owner auth with the "You" column, and `/status` belong to phase 4 and are out of scope here. Visual rules: `design/DESIGN.md`, especially "Adaptations for the Job Table".

## Global Constraints

- **Commits list only the repo owner as author — no `Co-Authored-By` or "Generated with" lines.**
- All web code lives in `web/`; pnpm is the package manager (`"packageManager": "pnpm@11.10.0"`).
- The site reads Supabase **only** through `jobs_feed` and `job_sources` with the anon/publishable key, from server code only. Server-only env: `SUPABASE_URL`, `SUPABASE_ANON_KEY`. Never use or expose the service-role/secret key.
- `/[region]` pages are `force-dynamic`, so every request sees fresh data. No build-time data fetching.
- Region → countries: `us` → `US, BOTH, UNKNOWN`; `ca` → `CA, BOTH, UNKNOWN`.
- Default visa filter: US tab hides `blocked`; the Canada tab shows all.
- 50 rows per page; sort `new` = `first_seen_at desc`; sort `pay` = `pay_hourly_max desc nulls last`, then newest.
- Colors, fonts, radii and shadows come from `design/DESIGN.md` tokens. Poppins is used for headings only, Inter for everything else. Electric Signal `#1b55f5` is only used for primary buttons, links on hover, the active tab and the "New" badge.
- Links render only for `http:`/`https:` URLs.
- Mobile: no horizontal page scroll at 375px; 16px side gutter.

## Review Focus

1. **A `best_url` that isn't http(s)** (e.g. `javascript:alert(1)`) renders as plain text, never an `<a href>` → test in Task 2 and Task 6.
2. **Search text containing PostgREST metacharacters** (`,` `(` `)` `"` `%` `*`) is sanitized and never breaks or extends the `or=` filter → tests in Task 3 and Task 5.
3. **Garbage query params** (`visa=foo`, `page=-3`, `category=<script>`, `term=x%`, repeated params) fall back to defaults and never throw → test in Task 3.
4. **Jobs with no parsed location or in both countries**: `location_unclear` rows show "Location unclear" and `BOTH`/`UNKNOWN` rows appear under both tabs → tests in Task 2 and Task 5.
5. **No matching jobs** renders an empty state with a "Clear filters" link, not a blank table → test in Task 6.

## File Map

```
web/
  package.json, pnpm-lock.yaml, tsconfig.json, next.config.ts, postcss.config.mjs,
  vitest.config.ts, .env.example
  app/
    globals.css             Tailwind v4 + design tokens (@theme)
    layout.tsx              fonts, header
    page.tsx                redirect → /us
    [region]/page.tsx       data loading + composition
    [region]/error.tsx      friendly error state
  lib/
    types.ts                JobRow, JobSource, Region, …
    format.ts               relativeTime, formatPay, formatLocation, safeUrl, faviconUrl
    filters.ts              parseFilters, toQuery, defaultVisa, CATEGORIES
    badges.ts               visaBadge, flagBadges, freshnessBadge
    jobs.ts                 applyFilters, fetchJobs, fetchSources, fetchCounts, fetchTermOptions
    supabase.ts             server-only client factory
  components/
    Badge.tsx, Header.tsx, Hero.tsx, RegionTabs.tsx, FilterBar.tsx, JobList.tsx, Pagination.tsx
  tests/
    format.test.ts, filters.test.ts, badges.test.ts, jobs.test.ts, components.test.tsx
.github/workflows/ci.yml    + web job
```

---

### Task 1: Scaffold the Next.js app with design tokens

**Files:**
- Create: `web/` via create-next-app, then replace `web/app/globals.css`, `web/app/layout.tsx`, `web/app/page.tsx`; create `web/components/Header.tsx`, `web/vitest.config.ts`, `web/.env.example`, `web/tests/smoke.test.ts`
- Modify: `web/package.json` (scripts, packageManager)

**Interfaces:**
- Produces: Tailwind utilities `bg-signal bg-canvas bg-surface text-ink text-graphite text-slate border-divider border-input-steel bg-blue-mist border-sky-edge bg-peach-paper border-tangerine-edge bg-lilac-wash border-orchid-edge bg-apricot rounded-card rounded-control rounded-nav shadow-subtle font-display bg-horizon`; scripts `pnpm dev|build|test|typecheck`.

- [ ] **Step 1: Scaffold**

```bash
cd /Users/baldeeppannu/jobs-scraping
pnpm create next-app@latest web --ts --tailwind --app --no-src-dir --import-alias "@/*" \
  --use-pnpm --no-linter --turbopack --yes
cd web && pnpm add @supabase/supabase-js server-only && pnpm add -D vitest
```
Expected: `web/` exists with `app/`, `package.json`, `pnpm-lock.yaml`. If create-next-app asks anything interactively, answer: TypeScript yes, Tailwind yes, App Router yes, src dir no, import alias `@/*`, linter none, React Compiler no. Delete any generated `web/.git`, plus `web/README.md` and `web/public/*.svg` if present. Keep `AGENTS.md`/`CLAUDE.md` if create-next-app generated them.

- [ ] **Step 2: Set scripts** — in `web/package.json` make `"scripts"` exactly:

```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "test": "vitest run",
  "typecheck": "tsc --noEmit"
},
"packageManager": "pnpm@11.10.0"
```

- [ ] **Step 3: Write the failing smoke test** — `web/vitest.config.ts`:

```ts
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: { environment: "node", include: ["tests/**/*.test.{ts,tsx}"] },
});
```

`web/tests/smoke.test.ts`:
```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("design tokens", () => {
  const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
  it.each([
    ["--color-signal", "#1b55f5"],
    ["--color-canvas", "#f4f4f6"],
    ["--color-graphite", "#454554"],
    ["--radius-card", "24px"],
  ])("defines %s = %s", (token, value) => {
    expect(css).toContain(`${token}: ${value}`);
  });
});
```

Run: `cd web && pnpm test`
Expected: FAIL (the scaffolded globals.css has none of these tokens).

- [ ] **Step 4: Implement tokens, layout, header, redirect**

`web/app/globals.css`:
```css
@import "tailwindcss";

/* Tokens from design/DESIGN.md */
@theme {
  --color-signal: #1b55f5;
  --color-apricot: #fad8ac;
  --color-orchid-edge: #eeaafd;
  --color-sky-edge: #8ec0ff;
  --color-tangerine-edge: #ffae70;
  --color-ink: #000000;
  --color-charcoal: #2b2d32;
  --color-graphite: #454554;
  --color-slate: #67677e;
  --color-input-steel: #d8d8df;
  --color-divider: #e6e6ea;
  --color-peach-paper: #f4e5d9;
  --color-lilac-wash: #f9e8ff;
  --color-blue-mist: #eaf0ff;
  --color-canvas: #f4f4f6;
  --color-surface: #ffffff;

  --font-display: var(--font-poppins), system-ui, sans-serif;
  --font-sans: var(--font-inter), system-ui, sans-serif;

  --radius-card: 24px;
  --radius-control: 8px;
  --radius-nav: 4px;

  --shadow-subtle: 0 0 0 1px rgb(0 0 0 / 0.05), 0 1px 3px 0 rgb(0 0 0 / 0.1);
}

@utility bg-horizon {
  background-image: linear-gradient(120deg, #f7bfa3 10%, #e6b3e6 40%, #a3d8f7 75%, #7be7e7);
}

html {
  color-scheme: light;
}

body {
  background: var(--color-canvas);
  color: var(--color-ink);
  font-family: var(--font-sans);
}

/* <details> rows: hide the default disclosure triangle */
summary {
  list-style: none;
}
summary::-webkit-details-marker {
  display: none;
}
```

`web/components/Header.tsx`:
```tsx
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
```

`web/app/layout.tsx`:
```tsx
import type { Metadata } from "next";
import { Inter, Poppins } from "next/font/google";
import { Header } from "@/components/Header";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const poppins = Poppins({ subsets: ["latin"], weight: ["500", "600"], variable: "--font-poppins" });

export const metadata: Metadata = {
  title: "Intern Radar",
  description: "Tech internships in Canada and the US, scraped every 5 minutes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${poppins.variable}`}>
      <body className="min-h-screen antialiased">
        <Header />
        {children}
      </body>
    </html>
  );
}
```

`web/app/page.tsx`:
```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/us");
}
```

`web/.env.example`:
```
# Supabase project URL and anon/publishable key (read-only through RLS). Server-only.
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<anon or publishable key>
```

- [ ] **Step 5: Verify**

Run: `cd web && pnpm test && pnpm typecheck && pnpm build`
Expected: 4 tests pass; typecheck clean; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "Scaffold Next.js website with design tokens"
```

---

### Task 2: Types and formatters

**Files:**
- Create: `web/lib/types.ts`, `web/lib/format.ts`, `web/tests/format.test.ts`, `web/tests/fixtures.ts`

**Interfaces:**
- Produces:
  - Types: `Region = "us" | "ca"`, `Country`, `VisaStatus`, `Freshness`, `WorkMode`, `Loc`, `JobRow`, `JobSource`.
  - `relativeTime(iso: string, now: Date): string`
  - `formatPay(min: number | null, max: number | null, currency: string | null): string | null`
  - `formatLocation(job: Pick<JobRow, "locations" | "location_unclear" | "location_raw">): string`
  - `safeUrl(url: string | null | undefined): string | null`
  - `faviconUrl(domain: string | null): string | null`
  - Test helper `makeJob(overrides?: Partial<JobRow>): JobRow` in `tests/fixtures.ts`.

- [ ] **Step 1: Write types** — `web/lib/types.ts`

```ts
export type Region = "us" | "ca";
export type Country = "CA" | "US" | "BOTH" | "UNKNOWN";
export type VisaStatus = "open" | "blocked" | "unknown";
export type Freshness = "fresh" | "repost" | "reopened" | "refreshed" | "recurring";
export type WorkMode = "onsite" | "hybrid" | "remote" | "unknown";

export interface Loc {
  city: string | null;
  region: string | null;
  country: "CA" | "US";
}

/** One row of the `jobs_feed` view (only the columns the site uses). */
export interface JobRow {
  id: string;
  title: string;
  company_name: string;
  company_domain: string | null;
  category: string;
  term: string | null;
  location_raw: string;
  locations: Loc[];
  country: Country;
  work_mode: WorkMode;
  location_unclear: boolean;
  pay_hourly_min: number | null;
  pay_hourly_max: number | null;
  pay_currency: string | null;
  pay_raw: string | null;
  visa_status: VisaStatus;
  visa_signals: string[];
  flags: string[];
  evidence: Record<string, string>;
  freshness: Freshness;
  repost_count: number;
  first_seen_at: string;
  best_url: string;
  h1b_count: number | null;
}

export interface JobSource {
  job_id: string;
  source: string;
  url: string;
  first_seen_at: string;
}
```

- [ ] **Step 2: Write the failing tests**

`web/tests/fixtures.ts`:
```ts
import type { JobRow } from "@/lib/types";

export function makeJob(overrides: Partial<JobRow> = {}): JobRow {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    title: "Software Engineer Intern",
    company_name: "Acme",
    company_domain: "acme.com",
    category: "SWE",
    term: "Summer 2027",
    location_raw: "Toronto, ON",
    locations: [{ city: "Toronto", region: "ON", country: "CA" }],
    country: "CA",
    work_mode: "onsite",
    location_unclear: false,
    pay_hourly_min: 30,
    pay_hourly_max: 38,
    pay_currency: "CAD",
    pay_raw: "CA$30 - CA$38 per hour",
    visa_status: "open",
    visa_signals: [],
    flags: ["pay_listed"],
    evidence: {},
    freshness: "fresh",
    repost_count: 0,
    first_seen_at: "2026-10-07T10:00:00Z",
    best_url: "https://boards.greenhouse.io/acme/jobs/1",
    h1b_count: null,
    ...overrides,
  };
}
```

`web/tests/format.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { faviconUrl, formatLocation, formatPay, relativeTime, safeUrl } from "@/lib/format";

const NOW = new Date("2026-10-07T12:00:00Z");

describe("relativeTime", () => {
  it.each([
    ["2026-10-07T11:59:30Z", "just now"],
    ["2026-10-07T11:48:00Z", "12m ago"],
    ["2026-10-07T07:00:00Z", "5h ago"],
    ["2026-10-04T12:00:00Z", "3d ago"],
    ["2026-07-01T12:00:00Z", "3mo ago"],
    ["2026-10-07T12:05:00Z", "just now"],
  ])("%s → %s", (iso, expected) => {
    expect(relativeTime(iso, NOW)).toBe(expected);
  });
});

describe("formatPay", () => {
  it("formats ranges with currency symbols", () => {
    expect(formatPay(30, 38, "CAD")).toBe("C$30–38/h");
    expect(formatPay(28, 35, "USD")).toBe("$28–35/h");
  });
  it("collapses equal bounds and trims decimals", () => {
    expect(formatPay(57.7, 57.7, "USD")).toBe("$57.70/h");
    expect(formatPay(33.65, 40.87, "CAD")).toBe("C$33.65–40.87/h");
  });
  it("handles a missing bound and no pay", () => {
    expect(formatPay(null, 50, "USD")).toBe("$50/h");
    expect(formatPay(null, null, null)).toBeNull();
  });
});

describe("formatLocation", () => {
  it("lists up to two places then counts the rest", () => {
    expect(
      formatLocation({
        location_raw: "",
        location_unclear: false,
        locations: [
          { city: "New York", region: "NY", country: "US" },
          { city: "Seattle", region: "WA", country: "US" },
          { city: null, region: null, country: "CA" },
        ],
      }),
    ).toBe("New York, NY · Seattle, WA · +1 more");
  });
  it("names the country when there is no city", () => {
    expect(
      formatLocation({
        location_raw: "Remote - Canada",
        location_unclear: false,
        locations: [{ city: null, region: null, country: "CA" }],
      }),
    ).toBe("Canada");
  });
  it("says when the location is unclear", () => {
    expect(formatLocation({ location_raw: "Remote", location_unclear: true, locations: [] })).toBe(
      "Location unclear",
    );
  });
});

describe("safeUrl", () => {
  it("allows http and https only", () => {
    expect(safeUrl("https://jobs.lever.co/x/1")).toBe("https://jobs.lever.co/x/1");
    expect(safeUrl("http://example.com/a")).toBe("http://example.com/a");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("JaVaScRiPt:alert(1)")).toBeNull();
    expect(safeUrl("data:text/html,hi")).toBeNull();
    expect(safeUrl("not a url")).toBeNull();
    expect(safeUrl(null)).toBeNull();
  });
});

describe("faviconUrl", () => {
  it("uses Google's favicon service", () => {
    expect(faviconUrl("stripe.com")).toBe(
      "https://www.google.com/s2/favicons?domain=stripe.com&sz=64",
    );
    expect(faviconUrl(null)).toBeNull();
  });
});
```

Run: `cd web && pnpm test`
Expected: FAIL — cannot resolve `@/lib/format`.

- [ ] **Step 3: Implement** — `web/lib/format.ts`

```ts
import type { JobRow } from "@/lib/types";

export function relativeTime(iso: string, now: Date): string {
  const seconds = Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function money(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

export function formatPay(
  min: number | null,
  max: number | null,
  currency: string | null,
): string | null {
  if (min == null && max == null) return null;
  const lo = (min ?? max) as number;
  const hi = (max ?? min) as number;
  const symbol = currency === "CAD" ? "C$" : "$";
  const range = lo === hi ? money(lo) : `${money(lo)}–${money(hi)}`;
  return `${symbol}${range}/h`;
}

const COUNTRY_NAMES = { CA: "Canada", US: "United States" } as const;

export function formatLocation(
  job: Pick<JobRow, "locations" | "location_unclear" | "location_raw">,
): string {
  if (job.locations.length === 0) {
    return job.location_unclear ? "Location unclear" : job.location_raw || "—";
  }
  const names = job.locations.map((l) =>
    l.city ? (l.region ? `${l.city}, ${l.region}` : l.city) : COUNTRY_NAMES[l.country],
  );
  const shown = names.slice(0, 2);
  const extra = names.length - shown.length;
  return extra > 0 ? `${shown.join(" · ")} · +${extra} more` : shown.join(" · ");
}

export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? url : null;
  } catch {
    return null;
  }
}

export function faviconUrl(domain: string | null): string | null {
  return domain
    ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`
    : null;
}
```

Note `formatPay(57.7, 57.7)` → `"$57.70/h"` (two decimals whenever non-integer — consistent column width).

- [ ] **Step 4: Run tests**

Run: `cd web && pnpm test && pnpm typecheck`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/lib web/tests
git commit -m "Add job types and display formatters"
```

---

### Task 3: URL filters

**Files:**
- Create: `web/lib/filters.ts`, `web/tests/filters.test.ts`

**Interfaces:**
- Consumes: `Region`, `VisaStatus` (Task 2).
- Produces:
  - `CATEGORIES: readonly string[]`, `WITHIN = ["1h","24h","7d","all"] as const`, `PAGE_SIZE = 50`
  - `interface Filters { region: Region; q: string; category: string | null; term: string | null; visa: VisaStatus[]; within: Within; fresh: boolean; pay: boolean; remote: boolean; sort: "new" | "pay"; page: number }`
  - `type SearchParams = Record<string, string | string[] | undefined>`
  - `defaultVisa(region: Region): VisaStatus[]`
  - `parseFilters(region: Region, params: SearchParams): Filters`
  - `toQuery(f: Filters): string` — `""` or `"?a=b&…"`, only non-default values, stable order.
  - `sanitizeSearch(q: string): string`

- [ ] **Step 1: Write the failing test** — `web/tests/filters.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { defaultVisa, parseFilters, sanitizeSearch, toQuery } from "@/lib/filters";

describe("parseFilters", () => {
  it("uses region defaults", () => {
    const us = parseFilters("us", {});
    expect(us).toEqual({
      region: "us", q: "", category: null, term: null, visa: ["open", "unknown"],
      within: "all", fresh: false, pay: false, remote: false, sort: "new", page: 1,
    });
    expect(parseFilters("ca", {}).visa).toEqual(["open", "unknown", "blocked"]);
  });

  it("reads valid params", () => {
    const f = parseFilters("us", {
      q: "stripe", category: "Data/ML", term: "Summer 2027", visa: "open,blocked",
      within: "24h", fresh: "1", pay: "1", remote: "1", sort: "pay", page: "3",
    });
    expect(f).toMatchObject({
      q: "stripe", category: "Data/ML", term: "Summer 2027", visa: ["open", "blocked"],
      within: "24h", fresh: true, pay: true, remote: true, sort: "pay", page: 3,
    });
  });

  it("falls back to defaults for garbage", () => {
    const f = parseFilters("us", {
      visa: "foo", page: "-3", category: "<script>", term: "x%", within: "forever",
      sort: "drop table", fresh: "yes",
    });
    expect(f).toEqual(parseFilters("us", {}));
  });

  it("takes the first of repeated params and caps the page", () => {
    expect(parseFilters("us", { q: ["a", "b"], page: "999999" })).toMatchObject({
      q: "a", page: 1000,
    });
  });
});

describe("sanitizeSearch", () => {
  it("strips PostgREST and LIKE metacharacters", () => {
    expect(sanitizeSearch('a,b(c)"d%e*f\\g')).toBe("a b c d e f g");
    expect(sanitizeSearch("  C++ / .NET intern  ")).toBe("C++ / .NET intern");
    expect(sanitizeSearch("x".repeat(200))).toHaveLength(80);
  });
});

describe("toQuery", () => {
  it("omits defaults", () => {
    expect(toQuery(parseFilters("us", {}))).toBe("");
    expect(toQuery(parseFilters("ca", {}))).toBe("");
  });

  it("round-trips non-default values", () => {
    const params = { q: "data", category: "SWE", visa: "open", fresh: "1", sort: "pay", page: "2" };
    const f = parseFilters("us", params);
    const query = toQuery(f);
    expect(query).toBe("?q=data&category=SWE&visa=open&fresh=1&sort=pay&page=2");
    const back = Object.fromEntries(new URLSearchParams(query.slice(1)));
    expect(parseFilters("us", back)).toEqual(f);
  });

  it("encodes values", () => {
    expect(toQuery({ ...parseFilters("us", {}), category: "Data/ML" })).toBe("?category=Data%2FML");
  });
});

describe("defaultVisa", () => {
  it("hides blocked only in the US", () => {
    expect(defaultVisa("us")).toEqual(["open", "unknown"]);
    expect(defaultVisa("ca")).toEqual(["open", "unknown", "blocked"]);
  });
});
```

Run: `cd web && pnpm test tests/filters.test.ts`
Expected: FAIL — cannot resolve `@/lib/filters`.

- [ ] **Step 2: Implement** — `web/lib/filters.ts`

```ts
import type { Region, VisaStatus } from "@/lib/types";

export const CATEGORIES = [
  "SWE",
  "Data/ML",
  "Hardware/Embedded",
  "PM",
  "Design",
  "Quant",
  "IT/Security",
  "Other-tech",
] as const;
export const WITHIN = ["1h", "24h", "7d", "all"] as const;
export type Within = (typeof WITHIN)[number];
export const PAGE_SIZE = 50;
const VISA: VisaStatus[] = ["open", "unknown", "blocked"];
const TERM_RE = /^(Summer|Fall|Winter|Spring) 20\d\d$/;
const MAX_PAGE = 1000;

export type SearchParams = Record<string, string | string[] | undefined>;

export interface Filters {
  region: Region;
  q: string;
  category: string | null;
  term: string | null;
  visa: VisaStatus[];
  within: Within;
  fresh: boolean;
  pay: boolean;
  remote: boolean;
  sort: "new" | "pay";
  page: number;
}

export function defaultVisa(region: Region): VisaStatus[] {
  return region === "us" ? ["open", "unknown"] : ["open", "unknown", "blocked"];
}

const first = (v: string | string[] | undefined): string | undefined =>
  Array.isArray(v) ? v[0] : v;

/** Keeps letters, digits, spaces and . + # / - ; drops PostgREST/LIKE metacharacters. */
export function sanitizeSearch(q: string): string {
  return q
    .replace(/[^\p{L}\p{N} .+#/-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

export function parseFilters(region: Region, params: SearchParams): Filters {
  const visaParam = first(params.visa);
  const visa = visaParam
    ? VISA.filter((v) => visaParam.split(",").includes(v))
    : defaultVisa(region);
  const category = first(params.category) ?? "";
  const term = first(params.term) ?? "";
  const within = first(params.within) ?? "";
  const page = Number.parseInt(first(params.page) ?? "1", 10);
  return {
    region,
    q: sanitizeSearch(first(params.q) ?? ""),
    category: (CATEGORIES as readonly string[]).includes(category) ? category : null,
    term: TERM_RE.test(term) ? term : null,
    visa: visa.length ? visa : defaultVisa(region),
    within: (WITHIN as readonly string[]).includes(within) ? (within as Within) : "all",
    fresh: first(params.fresh) === "1",
    pay: first(params.pay) === "1",
    remote: first(params.remote) === "1",
    sort: first(params.sort) === "pay" ? "pay" : "new",
    page: Number.isFinite(page) && page >= 1 ? Math.min(page, MAX_PAGE) : 1,
  };
}

export function toQuery(f: Filters): string {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.category) p.set("category", f.category);
  if (f.term) p.set("term", f.term);
  if (f.visa.join(",") !== defaultVisa(f.region).join(",")) p.set("visa", f.visa.join(","));
  if (f.within !== "all") p.set("within", f.within);
  if (f.fresh) p.set("fresh", "1");
  if (f.pay) p.set("pay", "1");
  if (f.remote) p.set("remote", "1");
  if (f.sort !== "new") p.set("sort", f.sort);
  if (f.page !== 1) p.set("page", String(f.page));
  const s = p.toString();
  return s ? `?${s}` : "";
}
```

`visa` is always kept in canonical order (open, unknown, blocked), so `toQuery` comparisons are stable.

- [ ] **Step 3: Run tests**

Run: `cd web && pnpm test && pnpm typecheck`
Expected: all pass. If the round-trip test fails on `visa`, check that the canonical ordering comes from `VISA.filter(...)`.

- [ ] **Step 4: Commit**

```bash
git add web/lib/filters.ts web/tests/filters.test.ts
git commit -m "Add URL filter parsing and serialization"
```

---

### Task 4: Badges

**Files:**
- Create: `web/lib/badges.ts`, `web/tests/badges.test.ts`

**Interfaces:**
- Consumes: `JobRow` (Task 2).
- Produces: `type Tone = "signal" | "sky" | "tangerine" | "orchid" | "apricot" | "neutral"`; `interface BadgeSpec { label: string; tone: Tone; title?: string }`; `visaBadge(job: JobRow): BadgeSpec`; `flagBadges(job: JobRow): BadgeSpec[]`; `freshnessBadge(job: JobRow, now: Date): BadgeSpec`.

Badge rules (DESIGN.md "Flag badges", adapted):
- Visa: `open` → "Open" (sky), `unknown` → "Unknown" (neutral), `blocked` → "Blocked" (tangerine). The title is the evidence sentence of the first matching signal in order `no_sponsorship, us_citizen_only, clearance, us_school_required, sponsors`.
- Flags column, in this order: `clearance` → "Clearance" (tangerine), `us_school_required` → "US school only" (tangerine), `canadian_coop_required` → "Co-op enrolment" (apricot), `grad_students_only` → "Grad students" (orchid), `early_years_only` → "1st/2nd year" (orchid), `eligibility_restricted` → "Restricted eligibility" (orchid), each `grad_year:YYYY` → "Grad YYYY" (neutral), `relocation` → "Relocation" (sky). Each title is the evidence sentence when present. Pay and work mode have their own columns, so `pay_listed`, `remote` and `hybrid` are not badges.
- Freshness: first seen < 24h ago and freshness `fresh`/`recurring` → "New" (signal). Otherwise `repost` → "Repost" or "Repost ×N" when `repost_count > 1` (orchid), `reopened` → "Reopened" (orchid), `refreshed` → "Date bumped" (neutral), `recurring` → "Returning role" (neutral), `fresh` → "Fresh" (neutral).

- [ ] **Step 1: Write the failing test** — `web/tests/badges.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { flagBadges, freshnessBadge, visaBadge } from "@/lib/badges";
import { makeJob } from "./fixtures";

const NOW = new Date("2026-10-07T12:00:00Z");

describe("visaBadge", () => {
  it("maps statuses and explains with evidence", () => {
    expect(visaBadge(makeJob())).toEqual({ label: "Open", tone: "sky", title: undefined });
    expect(visaBadge(makeJob({ visa_status: "unknown" }))).toMatchObject({
      label: "Unknown", tone: "neutral",
    });
    const blocked = makeJob({
      visa_status: "blocked",
      visa_signals: ["clearance", "no_sponsorship"],
      evidence: { clearance: "Needs clearance.", no_sponsorship: "We will not sponsor visas." },
    });
    expect(visaBadge(blocked)).toEqual({
      label: "Blocked", tone: "tangerine", title: "We will not sponsor visas.",
    });
  });
});

describe("flagBadges", () => {
  it("orders badges and skips pay/work-mode flags", () => {
    const job = makeJob({
      visa_signals: ["canadian_coop_required", "clearance"],
      flags: ["grad_year:2027", "grad_year:2028", "hybrid", "pay_listed", "relocation"],
      evidence: { relocation: "Relocation assistance is provided." },
    });
    expect(flagBadges(job).map((b) => b.label)).toEqual([
      "Clearance", "Co-op enrolment", "Grad 2027", "Grad 2028", "Relocation",
    ]);
    expect(flagBadges(job).at(-1)?.title).toBe("Relocation assistance is provided.");
  });

  it("is empty when nothing applies", () => {
    expect(flagBadges(makeJob())).toEqual([]);
  });
});

describe("freshnessBadge", () => {
  it("marks jobs first seen in the last day as New", () => {
    expect(freshnessBadge(makeJob({ first_seen_at: "2026-10-07T01:00:00Z" }), NOW)).toEqual({
      label: "New", tone: "signal",
    });
  });

  it.each([
    [{ freshness: "repost" as const, repost_count: 1 }, "Repost"],
    [{ freshness: "repost" as const, repost_count: 3 }, "Repost ×3"],
    [{ freshness: "reopened" as const }, "Reopened"],
    [{ freshness: "refreshed" as const }, "Date bumped"],
    [{ freshness: "recurring" as const }, "Returning role"],
    [{ freshness: "fresh" as const }, "Fresh"],
  ])("labels older %o as %s", (overrides, label) => {
    const job = makeJob({ first_seen_at: "2026-10-01T00:00:00Z", ...overrides });
    expect(freshnessBadge(job, NOW).label).toBe(label);
  });

  it("does not call a recent repost New", () => {
    const job = makeJob({ freshness: "repost", repost_count: 1, first_seen_at: "2026-10-07T11:00:00Z" });
    expect(freshnessBadge(job, NOW).label).toBe("Repost");
  });
});
```

Run: `cd web && pnpm test tests/badges.test.ts`
Expected: FAIL — cannot resolve `@/lib/badges`.

- [ ] **Step 2: Implement** — `web/lib/badges.ts`

```ts
import type { JobRow } from "@/lib/types";

export type Tone = "signal" | "sky" | "tangerine" | "orchid" | "apricot" | "neutral";

export interface BadgeSpec {
  label: string;
  tone: Tone;
  title?: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const VISA_EVIDENCE_ORDER = [
  "no_sponsorship",
  "us_citizen_only",
  "clearance",
  "us_school_required",
  "sponsors",
];

export function visaBadge(job: JobRow): BadgeSpec {
  const reason = VISA_EVIDENCE_ORDER.find((s) => job.visa_signals.includes(s));
  const title = reason ? job.evidence[reason] : undefined;
  if (job.visa_status === "blocked") return { label: "Blocked", tone: "tangerine", title };
  if (job.visa_status === "open") return { label: "Open", tone: "sky", title };
  return { label: "Unknown", tone: "neutral", title };
}

const SIGNAL_BADGES: [string, string, BadgeSpec["tone"]][] = [
  ["clearance", "Clearance", "tangerine"],
  ["us_school_required", "US school only", "tangerine"],
  ["canadian_coop_required", "Co-op enrolment", "apricot"],
];
const FLAG_BADGES: [string, string, BadgeSpec["tone"]][] = [
  ["grad_students_only", "Grad students", "orchid"],
  ["early_years_only", "1st/2nd year", "orchid"],
  ["eligibility_restricted", "Restricted eligibility", "orchid"],
];

export function flagBadges(job: JobRow): BadgeSpec[] {
  const out: BadgeSpec[] = [];
  for (const [key, label, tone] of SIGNAL_BADGES) {
    if (job.visa_signals.includes(key)) out.push({ label, tone, title: job.evidence[key] });
  }
  for (const [key, label, tone] of FLAG_BADGES) {
    if (job.flags.includes(key)) out.push({ label, tone, title: job.evidence[key] });
  }
  for (const flag of job.flags.filter((f) => f.startsWith("grad_year:")).sort()) {
    out.push({ label: `Grad ${flag.slice("grad_year:".length)}`, tone: "neutral", title: job.evidence[flag] });
  }
  if (job.flags.includes("relocation")) {
    out.push({ label: "Relocation", tone: "sky", title: job.evidence.relocation });
  }
  return out;
}

export function freshnessBadge(job: JobRow, now: Date): BadgeSpec {
  const recent = now.getTime() - new Date(job.first_seen_at).getTime() < DAY_MS;
  if (recent && (job.freshness === "fresh" || job.freshness === "recurring")) {
    return { label: "New", tone: "signal" };
  }
  switch (job.freshness) {
    case "repost":
      return { label: job.repost_count > 1 ? `Repost ×${job.repost_count}` : "Repost", tone: "orchid" };
    case "reopened":
      return { label: "Reopened", tone: "orchid" };
    case "refreshed":
      return { label: "Date bumped", tone: "neutral" };
    case "recurring":
      return { label: "Returning role", tone: "neutral" };
    default:
      return { label: "Fresh", tone: "neutral" };
  }
}
```

- [ ] **Step 3: Run tests**

Run: `cd web && pnpm test && pnpm typecheck`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add web/lib/badges.ts web/tests/badges.test.ts
git commit -m "Add visa, flag and freshness badge rules"
```

---

### Task 5: Supabase queries

**Files:**
- Create: `web/lib/jobs.ts`, `web/lib/supabase.ts`, `web/tests/jobs.test.ts`

**Interfaces:**
- Consumes: `Filters`, `PAGE_SIZE` (Task 3); `JobRow`, `JobSource`, `Region` (Task 2).
- Produces:
  - `REGION_COUNTRIES: Record<Region, Country[]>`
  - `interface FilterableQuery { in(column: string, values: readonly unknown[]): this; eq(column: string, value: unknown): this; ilike(column: string, pattern: string): this; gte(column: string, value: string): this; not(column: string, operator: string, value: unknown): this; or(filters: string): this; order(column: string, options: { ascending: boolean; nullsFirst?: boolean }): this; range(from: number, to: number): this }`
  - `applyFilters<Q extends FilterableQuery>(query: Q, f: Filters, now: Date): Q`
  - `fetchJobs(client: SupabaseClient, f: Filters, now: Date): Promise<{ rows: JobRow[]; total: number }>`
  - `fetchSources(client, ids: string[]): Promise<Record<string, JobSource[]>>`
  - `fetchCounts(client, region: Region, now: Date): Promise<{ open: number; today: number }>`
  - `fetchTermOptions(client, region: Region): Promise<string[]>` (season-year labels in chronological order)
  - `termOptions(terms: (string | null)[]): string[]` (pure helper used by `fetchTermOptions`)
  - `supabase(): SupabaseClient` in `lib/supabase.ts` (server-only).

- [ ] **Step 1: Write the failing test** — `web/tests/jobs.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { parseFilters } from "@/lib/filters";
import { applyFilters, type FilterableQuery, termOptions } from "@/lib/jobs";

type Call = [string, ...unknown[]];

class Recorder implements FilterableQuery {
  calls: Call[] = [];
  private rec(name: string, args: unknown[]): this {
    this.calls.push([name, ...args]);
    return this;
  }
  in(c: string, v: readonly unknown[]): this { return this.rec("in", [c, v]); }
  eq(c: string, v: unknown): this { return this.rec("eq", [c, v]); }
  ilike(c: string, p: string): this { return this.rec("ilike", [c, p]); }
  gte(c: string, v: string): this { return this.rec("gte", [c, v]); }
  not(c: string, o: string, v: unknown): this { return this.rec("not", [c, o, v]); }
  or(f: string): this { return this.rec("or", [f]); }
  order(c: string, o: { ascending: boolean; nullsFirst?: boolean }): this { return this.rec("order", [c, o]); }
  range(a: number, b: number): this { return this.rec("range", [a, b]); }
}

const NOW = new Date("2026-10-07T12:00:00Z");

describe("applyFilters", () => {
  it("applies region, default visa, newest-first and first page", () => {
    const q = applyFilters(new Recorder(), parseFilters("us", {}), NOW);
    expect(q.calls).toEqual([
      ["in", "country", ["US", "BOTH", "UNKNOWN"]],
      ["in", "visa_status", ["open", "unknown"]],
      ["order", "first_seen_at", { ascending: false }],
      ["range", 0, 49],
    ]);
  });

  it("includes BOTH and UNKNOWN in the Canada tab too", () => {
    const q = applyFilters(new Recorder(), parseFilters("ca", {}), NOW);
    expect(q.calls[0]).toEqual(["in", "country", ["CA", "BOTH", "UNKNOWN"]]);
  });

  it("applies every filter", () => {
    const f = parseFilters("ca", {
      q: "data", category: "SWE", term: "Fall 2026", visa: "open", within: "24h",
      fresh: "1", pay: "1", remote: "1", sort: "pay", page: "3",
    });
    expect(applyFilters(new Recorder(), f, NOW).calls).toEqual([
      ["in", "country", ["CA", "BOTH", "UNKNOWN"]],
      ["in", "visa_status", ["open"]],
      ["eq", "category", "SWE"],
      ["ilike", "term", "%Fall 2026%"],
      ["gte", "first_seen_at", "2026-10-06T12:00:00.000Z"],
      ["in", "freshness", ["fresh", "recurring"]],
      ["not", "pay_hourly_max", "is", null],
      ["eq", "work_mode", "remote"],
      ["or", 'title.ilike."%data%",company_name.ilike."%data%"'],
      ["order", "pay_hourly_max", { ascending: false, nullsFirst: false }],
      ["order", "first_seen_at", { ascending: false }],
      ["range", 100, 149],
    ]);
  });

  it("only ever puts sanitized text into the or filter", () => {
    const f = parseFilters("us", { q: 'x",id.eq.1),(y' });
    const or = applyFilters(new Recorder(), f, NOW).calls.find((c) => c[0] === "or");
    expect(or).toEqual(["or", 'title.ilike."%x id.eq.1 y%",company_name.ilike."%x id.eq.1 y%"']);
  });
});

describe("termOptions", () => {
  it("extracts season-years in chronological order", () => {
    expect(
      termOptions(["Summer 2027", "Fall 2026 · 4-month", null, "8-month", "Winter 2027", "Summer 2027"]),
    ).toEqual(["Fall 2026", "Winter 2027", "Summer 2027"]);
  });
});
```

Run: `cd web && pnpm test tests/jobs.test.ts`
Expected: FAIL — cannot resolve `@/lib/jobs`.

- [ ] **Step 2: Implement**

`web/lib/supabase.ts`:
```ts
import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/** Read-only client (anon/publishable key; RLS limits it to SELECT on public data). */
export function supabase(): SupabaseClient {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_ANON_KEY;
  if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_ANON_KEY must be set");
  return createClient(url, key, { auth: { persistSession: false } });
}
```

`web/lib/jobs.ts`:
```ts
import type { SupabaseClient } from "@supabase/supabase-js";
import { type Filters, PAGE_SIZE } from "@/lib/filters";
import type { Country, JobRow, JobSource, Region } from "@/lib/types";

export const REGION_COUNTRIES: Record<Region, Country[]> = {
  us: ["US", "BOTH", "UNKNOWN"],
  ca: ["CA", "BOTH", "UNKNOWN"],
};

const WITHIN_MS = { "1h": 3_600_000, "24h": 86_400_000, "7d": 604_800_000 } as const;

export interface FilterableQuery {
  in(column: string, values: readonly unknown[]): this;
  eq(column: string, value: unknown): this;
  ilike(column: string, pattern: string): this;
  gte(column: string, value: string): this;
  not(column: string, operator: string, value: unknown): this;
  or(filters: string): this;
  order(column: string, options: { ascending: boolean; nullsFirst?: boolean }): this;
  range(from: number, to: number): this;
}

export function applyFilters<Q extends FilterableQuery>(query: Q, f: Filters, now: Date): Q {
  let q = query.in("country", REGION_COUNTRIES[f.region]).in("visa_status", f.visa);
  if (f.category) q = q.eq("category", f.category);
  if (f.term) q = q.ilike("term", `%${f.term}%`);
  if (f.within !== "all") {
    q = q.gte("first_seen_at", new Date(now.getTime() - WITHIN_MS[f.within]).toISOString());
  }
  if (f.fresh) q = q.in("freshness", ["fresh", "recurring"]);
  if (f.pay) q = q.not("pay_hourly_max", "is", null);
  if (f.remote) q = q.eq("work_mode", "remote");
  if (f.q) {
    // f.q is sanitized by parseFilters (no quotes, commas, parens or %), so quoting is safe.
    q = q.or(`title.ilike."%${f.q}%",company_name.ilike."%${f.q}%"`);
  }
  if (f.sort === "pay") q = q.order("pay_hourly_max", { ascending: false, nullsFirst: false });
  q = q.order("first_seen_at", { ascending: false });
  const from = (f.page - 1) * PAGE_SIZE;
  return q.range(from, from + PAGE_SIZE - 1);
}

const COLUMNS =
  "id,title,company_name,company_domain,category,term,location_raw,locations,country," +
  "work_mode,location_unclear,pay_hourly_min,pay_hourly_max,pay_currency,pay_raw," +
  "visa_status,visa_signals,flags,evidence,freshness,repost_count,first_seen_at,best_url,h1b_count";

export async function fetchJobs(
  client: SupabaseClient,
  f: Filters,
  now: Date,
): Promise<{ rows: JobRow[]; total: number }> {
  const base = client.from("jobs_feed").select(COLUMNS, { count: "exact" });
  const { data, count, error } = await applyFilters(
    base as unknown as FilterableQuery,
    f,
    now,
  ) as unknown as Awaited<typeof base>;
  if (error) throw new Error(`jobs query failed: ${error.message}`);
  return { rows: (data ?? []) as unknown as JobRow[], total: count ?? 0 };
}

export async function fetchSources(
  client: SupabaseClient,
  ids: string[],
): Promise<Record<string, JobSource[]>> {
  if (ids.length === 0) return {};
  const { data, error } = await client
    .from("job_sources")
    .select("job_id,source,url,first_seen_at")
    .in("job_id", ids)
    .order("first_seen_at", { ascending: true });
  if (error) throw new Error(`sources query failed: ${error.message}`);
  const out: Record<string, JobSource[]> = {};
  for (const s of (data ?? []) as JobSource[]) (out[s.job_id] ??= []).push(s);
  return out;
}

export async function fetchCounts(
  client: SupabaseClient,
  region: Region,
  now: Date,
): Promise<{ open: number; today: number }> {
  const countries = REGION_COUNTRIES[region];
  const since = new Date(now.getTime() - WITHIN_MS["24h"]).toISOString();
  const [open, today] = await Promise.all([
    client.from("jobs_feed").select("id", { count: "exact", head: true }).in("country", countries),
    client
      .from("jobs_feed")
      .select("id", { count: "exact", head: true })
      .in("country", countries)
      .gte("first_seen_at", since),
  ]);
  if (open.error || today.error) throw new Error("count query failed");
  return { open: open.count ?? 0, today: today.count ?? 0 };
}

const SEASON_YEAR = /(Summer|Fall|Winter|Spring) (20\d\d)/;
const SEASON_ORDER = { Winter: 0, Spring: 1, Summer: 2, Fall: 3 } as const;

export function termOptions(terms: (string | null)[]): string[] {
  const found = new Map<string, number>();
  for (const t of terms) {
    const m = t?.match(SEASON_YEAR);
    if (m) {
      const season = m[1] as keyof typeof SEASON_ORDER;
      found.set(`${season} ${m[2]}`, Number(m[2]) * 4 + SEASON_ORDER[season]);
    }
  }
  return [...found.entries()].sort((a, b) => a[1] - b[1]).map(([label]) => label);
}

export async function fetchTermOptions(client: SupabaseClient, region: Region): Promise<string[]> {
  const { data, error } = await client
    .from("jobs_feed")
    .select("term")
    .in("country", REGION_COUNTRIES[region])
    .not("term", "is", null)
    .limit(5000);
  if (error) throw new Error(`terms query failed: ${error.message}`);
  return termOptions((data ?? []).map((r: { term: string | null }) => r.term));
}
```

- [ ] **Step 3: Run tests**

Run: `cd web && pnpm test && pnpm typecheck`
Expected: all pass. If `typecheck` rejects the casts in `fetchJobs`, keep the `as unknown as` double-casts. The goal is to keep supabase-js's deep generics out of `applyFilters`, not to type-check the builder.

- [ ] **Step 4: Commit**

```bash
git add web/lib/jobs.ts web/lib/supabase.ts web/tests/jobs.test.ts
git commit -m "Add Supabase job queries with tested filter builder"
```

---

### Task 6: Components

**Files:**
- Create: `web/components/Badge.tsx`, `web/components/Hero.tsx`, `web/components/RegionTabs.tsx`, `web/components/FilterBar.tsx`, `web/components/JobList.tsx`, `web/components/Pagination.tsx`, `web/tests/components.test.tsx`

**Interfaces:**
- Consumes: `Filters`, `toQuery`, `CATEGORIES`, `PAGE_SIZE`, `defaultVisa` (Task 3); `visaBadge`, `flagBadges`, `freshnessBadge`, `BadgeSpec` (Task 4); format helpers (Task 2); `JobRow`, `JobSource`, `Region`.
- Produces (all synchronous components):
  - `Badge({ spec }: { spec: BadgeSpec })`
  - `Hero({ region, counts, filters }: { region: Region; counts: { open: number; today: number }; filters: Filters })`
  - `RegionTabs({ filters }: { filters: Filters })`
  - `FilterBar({ filters, terms }: { filters: Filters; terms: string[] })` — a `<form id="filters" method="get">`
  - `JobList({ rows, sources, now, filters }: { rows: JobRow[]; sources: Record<string, JobSource[]>; now: Date; filters: Filters })`
  - `Pagination({ filters, total }: { filters: Filters; total: number })`

- [ ] **Step 1: Write the failing test** — `web/tests/components.test.tsx`

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FilterBar } from "@/components/FilterBar";
import { JobList } from "@/components/JobList";
import { Pagination } from "@/components/Pagination";
import { RegionTabs } from "@/components/RegionTabs";
import { parseFilters } from "@/lib/filters";
import { makeJob } from "./fixtures";

const NOW = new Date("2026-10-07T12:00:00Z");
const US = parseFilters("us", {});

describe("JobList", () => {
  it("renders a row with link, pay, visa, freshness and details", () => {
    const job = makeJob({
      visa_status: "blocked",
      visa_signals: ["no_sponsorship"],
      evidence: { no_sponsorship: "We will not sponsor visas." },
      first_seen_at: "2026-10-07T11:00:00Z",
    });
    const html = renderToStaticMarkup(
      <JobList
        rows={[job]}
        sources={{ [job.id]: [{ job_id: job.id, source: "greenhouse", url: job.best_url, first_seen_at: job.first_seen_at }] }}
        now={NOW}
        filters={US}
      />,
    );
    expect(html).toContain('href="https://boards.greenhouse.io/acme/jobs/1"');
    expect(html).toContain("Software Engineer Intern");
    expect(html).toContain("C$30–38/h");
    expect(html).toContain("Blocked");
    expect(html).toContain("New");
    expect(html).toContain("1h ago");
    expect(html).toContain("We will not sponsor visas.");
    expect(html).toContain("greenhouse");
    expect(html).toContain("<details");
  });

  it("never links a non-http URL", () => {
    const html = renderToStaticMarkup(
      <JobList rows={[makeJob({ best_url: "javascript:alert(1)" })]} sources={{}} now={NOW} filters={US} />,
    );
    expect(html).not.toContain("javascript:");
    expect(html).toContain("Software Engineer Intern");
  });

  it("shows an empty state with a clear-filters link", () => {
    const filtered = parseFilters("us", { category: "Quant" });
    const html = renderToStaticMarkup(<JobList rows={[]} sources={{}} now={NOW} filters={filtered} />);
    expect(html).toContain("No internships match");
    expect(html).toContain('href="/us"');
  });

  it("shows Location unclear", () => {
    const html = renderToStaticMarkup(
      <JobList
        rows={[makeJob({ locations: [], location_unclear: true, country: "UNKNOWN" })]}
        sources={{}}
        now={NOW}
        filters={US}
      />,
    );
    expect(html).toContain("Location unclear");
  });
});

describe("RegionTabs", () => {
  it("keeps filters but resets visa defaults and page when switching", () => {
    const f = parseFilters("us", { category: "SWE", page: "3" });
    const html = renderToStaticMarkup(<RegionTabs filters={f} />);
    expect(html).toContain('href="/ca?category=SWE"');
    expect(html).toContain('aria-current="page"');
  });
});

describe("Pagination", () => {
  it("links previous and next pages", () => {
    const f = parseFilters("us", { page: "2" });
    const html = renderToStaticMarkup(<Pagination filters={f} total={160} />);
    expect(html).toContain('href="/us"');
    expect(html).toContain('href="/us?page=3"');
    expect(html).toContain("Page 2 of 4");
  });

  it("renders nothing for a single page", () => {
    expect(renderToStaticMarkup(<Pagination filters={US} total={10} />)).toBe("");
  });
});

describe("FilterBar", () => {
  it("is a GET form that preserves current choices", () => {
    const f = parseFilters("us", { category: "PM", fresh: "1", term: "Summer 2027" });
    const html = renderToStaticMarkup(<FilterBar filters={f} terms={["Summer 2027"]} />);
    expect(html).toContain('method="get"');
    expect(html).toContain('id="filters"');
    expect(html).toMatch(/<option value="PM" selected="">/);
    expect(html).toMatch(/<option value="Summer 2027" selected="">/);
    expect(html).toMatch(/name="fresh" value="1" checked=""/);
  });
});
```

Run: `cd web && pnpm test tests/components.test.tsx`
Expected: FAIL — cannot resolve `@/components/FilterBar`.

- [ ] **Step 2: Implement components**

`web/components/Badge.tsx`:
```tsx
import type { BadgeSpec, Tone } from "@/lib/badges";

const TONES: Record<Tone, string> = {
  signal: "bg-signal border-signal text-white",
  sky: "bg-blue-mist border-sky-edge text-ink",
  tangerine: "bg-peach-paper border-tangerine-edge text-ink",
  orchid: "bg-lilac-wash border-orchid-edge text-ink",
  apricot: "bg-apricot border-tangerine-edge text-ink",
  neutral: "bg-canvas border-divider text-graphite",
};

export function Badge({ spec }: { spec: BadgeSpec }) {
  return (
    <span
      title={spec.title}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${TONES[spec.tone]}`}
    >
      {spec.label}
    </span>
  );
}
```

`web/components/Hero.tsx`:
```tsx
import type { Filters } from "@/lib/filters";
import type { Region } from "@/lib/types";

const NAMES: Record<Region, string> = { us: "the US", ca: "Canada" };

export function Hero({
  region,
  counts,
  filters,
}: {
  region: Region;
  counts: { open: number; today: number };
  filters: Filters;
}) {
  return (
    <section className="bg-horizon">
      <div className="mx-auto max-w-[1280px] px-4 py-12 md:px-8 md:py-16">
        <h1 className="font-display text-4xl font-semibold tracking-[-1.2px] md:text-6xl md:tracking-[-1.5px]">
          Tech internships in {NAMES[region]}
        </h1>
        <p className="mt-3 text-base text-graphite">
          {counts.open.toLocaleString("en-US")} open · {counts.today.toLocaleString("en-US")} new
          in the last 24 hours · updated every 5 minutes
        </p>
        <div className="relative mt-6 max-w-2xl">
          <input
            form="filters"
            type="search"
            name="q"
            defaultValue={filters.q}
            placeholder="Search roles or companies"
            aria-label="Search roles or companies"
            className="w-full rounded-control border border-input-steel bg-surface px-4 py-3 text-base outline-none focus:border-signal"
          />
          <button
            form="filters"
            type="submit"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-control bg-signal px-3.5 pb-[9px] pt-[7px] text-sm font-medium text-white"
          >
            Search
          </button>
        </div>
      </div>
    </section>
  );
}
```

`web/components/RegionTabs.tsx`:
```tsx
import { defaultVisa, type Filters, toQuery } from "@/lib/filters";
import type { Region } from "@/lib/types";

const TABS: [Region, string][] = [
  ["us", "United States"],
  ["ca", "Canada"],
];

export function RegionTabs({ filters }: { filters: Filters }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-divider">
      {TABS.map(([region, label]) => {
        const active = region === filters.region;
        const href = `/${region}${toQuery({ ...filters, region, page: 1, visa: defaultVisa(region) })}`;
        return (
          <a
            key={region}
            href={href}
            role="tab"
            aria-selected={active}
            aria-current={active ? "page" : undefined}
            className={`-mb-px rounded-t-nav border-b-2 px-4 py-2.5 text-sm font-medium ${
              active ? "border-signal text-ink" : "border-transparent text-slate hover:text-ink"
            }`}
          >
            {label}
          </a>
        );
      })}
    </div>
  );
}
```

`web/components/FilterBar.tsx`:
```tsx
import { CATEGORIES, type Filters } from "@/lib/filters";

const select =
  "rounded-control border border-input-steel bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-signal";
const VISA_OPTIONS: [string, string][] = [
  ["open,unknown", "Hide blocked"],
  ["open", "Open only"],
  ["open,unknown,blocked", "Show all"],
];
const WITHIN_OPTIONS: [string, string][] = [
  ["all", "Any time"],
  ["1h", "Last hour"],
  ["24h", "Last 24 hours"],
  ["7d", "Last 7 days"],
];

function Check({ name, label, checked }: { name: string; label: string; checked: boolean }) {
  return (
    <label className="flex items-center gap-2 text-sm text-graphite">
      <input type="checkbox" name={name} value="1" defaultChecked={checked} className="accent-signal" />
      {label}
    </label>
  );
}

export function FilterBar({ filters, terms }: { filters: Filters; terms: string[] }) {
  const visa = filters.visa.join(",");
  return (
    <form id="filters" method="get" className="flex flex-wrap items-center gap-3 py-4">
      <select name="category" defaultValue={filters.category ?? ""} aria-label="Category" className={select}>
        <option value="">All categories</option>
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      <select name="term" defaultValue={filters.term ?? ""} aria-label="Term" className={select}>
        <option value="">Any term</option>
        {terms.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <select name="visa" defaultValue={visa} aria-label="Visa" className={select}>
        {VISA_OPTIONS.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <select name="within" defaultValue={filters.within} aria-label="Posted within" className={select}>
        {WITHIN_OPTIONS.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <select name="sort" defaultValue={filters.sort} aria-label="Sort" className={select}>
        <option value="new">Newest</option>
        <option value="pay">Highest pay</option>
      </select>
      <Check name="fresh" label="Fresh only" checked={filters.fresh} />
      <Check name="pay" label="Pay listed" checked={filters.pay} />
      <Check name="remote" label="Remote" checked={filters.remote} />
      <button
        type="submit"
        className="rounded-control bg-signal px-3.5 pb-[9px] pt-[7px] text-sm font-medium text-white"
      >
        Apply
      </button>
      <a href={`/${filters.region}`} className="text-sm text-slate hover:text-ink">
        Reset
      </a>
    </form>
  );
}
```

React renders `defaultValue` on `<select>` as `selected=""` on the matching `<option>` in static markup, and `defaultChecked` as `checked=""`. The FilterBar test relies on this.

`web/components/JobList.tsx`:
```tsx
import { Badge } from "@/components/Badge";
import { flagBadges, freshnessBadge, visaBadge } from "@/lib/badges";
import type { Filters } from "@/lib/filters";
import { faviconUrl, formatLocation, formatPay, relativeTime, safeUrl } from "@/lib/format";
import type { JobRow, JobSource } from "@/lib/types";

// Company | Role | Location | Term | Pay | Visa | Flags | Seen
const GRID =
  "md:grid md:grid-cols-[minmax(140px,1.1fr)_minmax(200px,2fr)_minmax(140px,1.2fr)_110px_110px_90px_minmax(120px,1.2fr)_90px] md:items-center md:gap-4";

const EVIDENCE_LABELS: Record<string, string> = {
  no_sponsorship: "No sponsorship",
  us_citizen_only: "US citizens only",
  clearance: "Security clearance",
  us_school_required: "US school only",
  sponsors: "Sponsors visas",
  canadian_coop_required: "Co-op enrolment",
  pay_listed: "Pay",
  grad_students_only: "Grad students",
  early_years_only: "1st/2nd year",
  eligibility_restricted: "Eligibility",
  relocation: "Relocation",
};

function evidenceLabel(key: string): string {
  if (key.startsWith("grad_year:")) return `Grad ${key.slice(10)}`;
  return EVIDENCE_LABELS[key] ?? key;
}

function Row({ job, sources, now }: { job: JobRow; sources: JobSource[]; now: Date }) {
  const url = safeUrl(job.best_url);
  const pay = formatPay(job.pay_hourly_min, job.pay_hourly_max, job.pay_currency);
  const icon = faviconUrl(job.company_domain);
  const mode = job.work_mode === "remote" || job.work_mode === "hybrid" ? job.work_mode : null;
  const flags = flagBadges(job);
  const evidence = Object.entries(job.evidence);
  return (
    <li className="border-b border-divider last:border-b-0">
      <details className="group">
        <summary className={`cursor-pointer px-4 py-3 hover:bg-canvas/60 md:px-6 ${GRID}`}>
          <div className="flex items-center gap-2 text-sm font-medium text-ink">
            {icon && <img src={icon} alt="" width={16} height={16} className="h-4 w-4 rounded-sm" />}
            <span className="truncate">{job.company_name}</span>
          </div>
          <div className="mt-1 text-sm md:mt-0">
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer" className="font-medium text-ink hover:text-signal">
                {job.title}
              </a>
            ) : (
              <span className="font-medium text-ink">{job.title}</span>
            )}
            <span className="ml-2 text-xs text-slate">{job.category}</span>
          </div>
          <div className="mt-1 text-sm text-graphite md:mt-0">
            {formatLocation(job)}
            {mode && <span className="ml-2 text-xs capitalize text-slate">{mode}</span>}
          </div>
          <div className="text-sm text-graphite">{job.term ?? "—"}</div>
          <div className="text-sm text-ink" title={job.pay_raw ?? undefined}>
            {pay ?? <span className="text-slate">—</span>}
          </div>
          <div className="mt-2 md:mt-0">
            <Badge spec={visaBadge(job)} />
          </div>
          <div className="mt-2 flex flex-wrap gap-1 md:mt-0">
            {flags.map((b) => (
              <Badge key={b.label} spec={b} />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 md:mt-0 md:flex-col md:items-start md:gap-1">
            <Badge spec={freshnessBadge(job, now)} />
            <span className="text-xs text-slate">{relativeTime(job.first_seen_at, now)}</span>
          </div>
        </summary>
        <div className="grid gap-4 bg-canvas/50 px-4 py-4 text-sm text-graphite md:grid-cols-2 md:px-6">
          <div>
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate">Why these labels</h3>
            {evidence.length ? (
              <ul className="space-y-1.5">
                {evidence.map(([key, sentence]) => (
                  <li key={key}>
                    <span className="font-medium text-ink">{evidenceLabel(key)}:</span> {sentence}
                  </li>
                ))}
              </ul>
            ) : (
              <p>The posting doesn&apos;t mention visas, pay or eligibility limits.</p>
            )}
          </div>
          <div className="space-y-2">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate">Details</h3>
            <p>First seen {new Date(job.first_seen_at).toUTCString().slice(5, 16)} · location as posted: {job.location_raw || "—"}</p>
            {job.repost_count > 0 && <p>Posted before: this role has been reposted {job.repost_count}×.</p>}
            {job.h1b_count != null && <p>{job.company_name} filed {job.h1b_count.toLocaleString("en-US")} H-1B LCAs recently.</p>}
            {sources.length > 0 && (
              <p>
                Listed on:{" "}
                {sources.map((s, i) => {
                  const href = safeUrl(s.url);
                  return (
                    <span key={`${s.source}-${s.url}`}>
                      {i > 0 && ", "}
                      {href ? (
                        <a href={href} target="_blank" rel="noopener noreferrer" className="underline hover:text-signal">
                          {s.source}
                        </a>
                      ) : (
                        s.source
                      )}
                    </span>
                  );
                })}
              </p>
            )}
          </div>
        </div>
      </details>
    </li>
  );
}

export function JobList({
  rows,
  sources,
  now,
  filters,
}: {
  rows: JobRow[];
  sources: Record<string, JobSource[]>;
  now: Date;
  filters: Filters;
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-card bg-surface px-6 py-16 text-center shadow-subtle">
        <p className="font-display text-xl font-semibold">No internships match these filters</p>
        <a href={`/${filters.region}`} className="mt-3 inline-block text-sm text-signal hover:underline">
          Clear filters
        </a>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-card bg-surface shadow-subtle">
      <div className={`hidden border-b border-divider px-6 py-3 text-[13px] font-medium text-slate ${GRID}`}>
        <span>Company</span>
        <span>Role</span>
        <span>Location</span>
        <span>Term</span>
        <span>Pay</span>
        <span>Visa</span>
        <span>Flags</span>
        <span>Seen</span>
      </div>
      <ul>
        {rows.map((job) => (
          <Row key={job.id} job={job} sources={sources[job.id] ?? []} now={now} />
        ))}
      </ul>
    </div>
  );
}
```

`web/components/Pagination.tsx`:
```tsx
import { type Filters, PAGE_SIZE, toQuery } from "@/lib/filters";

export function Pagination({ filters, total }: { filters: Filters; total: number }) {
  const pages = Math.ceil(total / PAGE_SIZE);
  if (pages <= 1) return null;
  const link = (page: number) => `/${filters.region}${toQuery({ ...filters, page })}`;
  const btn = "rounded-control border border-divider bg-surface px-3 py-1.5 text-sm hover:border-input-steel";
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between py-6 text-sm text-graphite">
      {filters.page > 1 ? <a href={link(filters.page - 1)} className={btn}>Previous</a> : <span />}
      <span>
        Page {filters.page} of {pages}
      </span>
      {filters.page < pages ? <a href={link(filters.page + 1)} className={btn}>Next</a> : <span />}
    </nav>
  );
}
```

- [ ] **Step 3: Run tests**

Run: `cd web && pnpm test && pnpm typecheck`
Expected: all pass. If the FilterBar `selected=""` assertion fails, check React's static output for `<select defaultValue>`. Adjust the assertion, not the component, only if React's markup differs (e.g. puts `selected` before `value`).

- [ ] **Step 4: Commit**

```bash
git add web/components web/tests/components.test.tsx
git commit -m "Add job list, filters, tabs, hero and pagination components"
```

---

### Task 7: Region page wiring

**Files:**
- Create: `web/app/[region]/page.tsx`, `web/app/[region]/error.tsx`

**Interfaces:**
- Consumes: everything above; `supabase()`.

- [ ] **Step 1: Implement** — `web/app/[region]/page.tsx`

```tsx
import { notFound } from "next/navigation";
import { FilterBar } from "@/components/FilterBar";
import { Hero } from "@/components/Hero";
import { JobList } from "@/components/JobList";
import { Pagination } from "@/components/Pagination";
import { RegionTabs } from "@/components/RegionTabs";
import { parseFilters, type SearchParams } from "@/lib/filters";
import { fetchCounts, fetchJobs, fetchSources, fetchTermOptions } from "@/lib/jobs";
import { supabase } from "@/lib/supabase";
import type { Region } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function RegionPage({
  params,
  searchParams,
}: {
  params: Promise<{ region: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { region } = await params;
  if (region !== "us" && region !== "ca") notFound();
  const filters = parseFilters(region as Region, await searchParams);
  const now = new Date();
  const client = supabase();
  const [{ rows, total }, counts, terms] = await Promise.all([
    fetchJobs(client, filters, now),
    fetchCounts(client, filters.region, now),
    fetchTermOptions(client, filters.region),
  ]);
  const sources = await fetchSources(
    client,
    rows.map((r) => r.id),
  );

  return (
    <>
      <Hero region={filters.region} counts={counts} filters={filters} />
      <main className="mx-auto max-w-[1280px] px-4 pb-16 md:px-8">
        <div className="pt-8">
          <RegionTabs filters={filters} />
          <FilterBar filters={filters} terms={terms} />
        </div>
        <p className="pb-3 text-[13px] text-slate">
          {total.toLocaleString("en-US")} {total === 1 ? "internship" : "internships"}
        </p>
        <JobList rows={rows} sources={sources} now={now} filters={filters} />
        <Pagination filters={filters} total={total} />
      </main>
    </>
  );
}
```

`web/app/[region]/error.tsx`:
```tsx
"use client";

export default function RegionError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto max-w-[1280px] px-4 py-16 md:px-8">
      <div className="rounded-card bg-surface px-6 py-16 text-center shadow-subtle">
        <p className="font-display text-xl font-semibold">Couldn&apos;t load internships</p>
        <p className="mt-2 text-sm text-graphite">The database didn&apos;t respond. Try again in a moment.</p>
        <button
          type="button"
          onClick={reset}
          className="mt-4 rounded-control bg-signal px-3.5 pb-[9px] pt-[7px] text-sm font-medium text-white"
        >
          Retry
        </button>
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Create local env from Supabase (never print keys)**

```bash
cd /Users/baldeeppannu/jobs-scraping
supabase orgs list -o json | grep -q ozfvtziqfkbkirgbwinp || echo "WRONG SUPABASE ACCOUNT"
supabase projects api-keys --project-ref gbdqiarnypkagzwmlkte -o json | python3 -c "
import json, sys
keys = json.load(sys.stdin)
pick = next((k for k in keys if k.get('type') == 'publishable'), None) or \
       next(k for k in keys if k.get('name') == 'anon')
open('web/.env.local', 'w').write(
    'SUPABASE_URL=https://gbdqiarnypkagzwmlkte.supabase.co\nSUPABASE_ANON_KEY=' + pick['api_key'] + '\n')
print('wrote web/.env.local with', pick.get('type') or pick.get('name'), 'key')
"
git check-ignore -q web/.env.local && echo "web/.env.local is gitignored"
```
Expected: "wrote web/.env.local with publishable key" (or anon), and gitignored. Never select a `secret` or `service_role` key.

- [ ] **Step 3: Verify against real data**

```bash
cd web && pnpm build && (pnpm start -p 3100 > /tmp/web.log 2>&1 &) && sleep 4
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" localhost:3100/
curl -s localhost:3100/us | grep -o "Tech internships in the US\|internships</p>\|<details" | sort | uniq -c
curl -s "localhost:3100/ca?category=SWE&fresh=1" | grep -c "<details"
curl -s "localhost:3100/us?q=%22%2C%28%29" -o /dev/null -w "%{http_code}\n"
curl -s localhost:3100/xx -o /dev/null -w "%{http_code}\n"
pkill -f "next start -p 3100"
```
Expected: `/` → 307 to `/us`; `/us` contains the headline and many `<details`; the Canada SWE query returns ≥ 0 rows without error (200); the metacharacter search returns 200; `/xx` returns 404.

Then open `http://localhost:3100/us` in a browser at desktop width and at 375px. Check against DESIGN.md:
- canvas background with white header;
- horizon-gradient hero with a Poppins headline;
- one white 24px-radius card holding the rows;
- pill badges in pastel tones;
- no horizontal scroll at 375px.

Fix any visual defect before committing.

- [ ] **Step 4: Commit**

```bash
git add web/app
git commit -m "Wire region pages to Supabase"
```

---

### Task 8: CI for the website

**Files:**
- Modify: `.github/workflows/ci.yml` (add a `web` job)

- [ ] **Step 1: Add the job** — append under `jobs:` in `.github/workflows/ci.yml`:

```yaml
  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          package_json_file: web/package.json
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: web/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm typecheck
      - run: pnpm test
      - run: pnpm build
```

- [ ] **Step 2: Verify locally, push the branch, watch CI**

```bash
cd web && pnpm install --frozen-lockfile && pnpm typecheck && pnpm test && pnpm build && cd ..
git add .github/workflows/ci.yml
git commit -m "Run website typecheck, tests and build in CI"
git push -u origin HEAD
gh run watch $(gh run list --branch "$(git branch --show-current)" --workflow ci.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```
Expected: both `scraper` and `web` jobs succeed.

---

### Task 9: Deploy to Vercel (needs the owner)

**Files:** none (configuration). `web/.vercel/` is gitignored by the root `.gitignore` (`.vercel/`).

- [ ] **Step 1 (owner): Log in to Vercel** — run `! vercel login` here and finish in the browser with the account you want to own the site. Then confirm with `vercel whoami`.

- [ ] **Step 2: Link and configure** (from repo root)

```bash
cd web
vercel link --yes --project jobs-scraping
for env in production preview development; do
  grep '^SUPABASE_URL=' .env.local | cut -d= -f2- | tr -d '\n' | vercel env add SUPABASE_URL "$env" --force > /dev/null
  grep '^SUPABASE_ANON_KEY=' .env.local | cut -d= -f2- | tr -d '\n' | vercel env add SUPABASE_ANON_KEY "$env" --force > /dev/null
done
vercel env ls
```
Expected: both variables are listed for all three environments. Values are read from the file and never printed.

- [ ] **Step 3: Deploy and verify**

```bash
vercel deploy --prod --yes
```
Expected: prints a production URL. Then:

```bash
URL=<the printed production URL>
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" "$URL/"
curl -s "$URL/us" | grep -c "<details"
```
Expected: `/` redirects to `/us`; `/us` lists jobs.

- [ ] **Step 4 (owner, optional): Auto-deploy on push** — in the Vercel dashboard → Project → Settings → Git, connect `baldeep06/jobs-scraping` and set **Root Directory** to `web`. Data is fetched per request, so the site only needs redeploying when its code changes.

---

## Self-Review Notes

- **Spec §8 coverage:**
  - Data access through the anon key and RLS: Tasks 5 and 7.
  - Routes `/` → `/us`, `/us`, `/ca`: Tasks 1 and 7.
  - Header, hero and tabs: Tasks 1 and 6.
  - URL filters with 50 rows per page: Tasks 3 and 5.
  - All columns except "You", plus row expand: Task 6.
  - Mobile cards: the `md:grid` layout in Task 6, checked in Task 7.
  - DESIGN.md styling: Tasks 1 and 6.
- **Deviations from spec §8 (ledger them as rulings at execution):**
  - Pages render per request with no caching (personal tool, fresh data).
  - Row expand shows the repost count, not the original posting date. RLS hides closed jobs from the anon key, so the original's dates can't be read.
  - Filters apply on submit (no client JS).
  - `pay_listed`, `remote` and `hybrid` are not shown as badges because the Pay and Location columns already show them.
- **Deferred to phase 4, per spec:** the Realtime "N new jobs" banner, owner login with the applied/hide column, and `/status`.
- **Phase 1 minor M10** (link scheme validation) is fixed by `safeUrl` in Tasks 2 and 6.
