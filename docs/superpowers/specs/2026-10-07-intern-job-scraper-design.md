# Intern Job Scraper — Design Spec

**Date:** 2026-10-07
**Status:** Approved design, pending spec review

## 1. Goal & Context

A personal, $0-cost job board that surfaces **tech internships in Canada and the
US** within minutes of posting, with the details needed to decide whether to
apply: pay, location, term, visa feasibility, and whether the posting is fresh or
a repost.

**User:** one person (the owner) — a Canadian citizen studying in Canada. The
site is publicly reachable but not designed for other users yet. Data model keeps
raw signals separate from user-specific judgments so it can go multi-user later.

**Success criteria**
- New postings on tracked company job boards appear on the site within ~5–20 min.
- Every job shows: company, role, category, location, term, pay (if listed),
  visa status for the owner, flags, freshness label, first-seen time.
- Fresh vs repost/reopened/refreshed/recurring is labeled correctly for the
  cases in §4.
- Daily email digest of new matching jobs at ~8 AM ET.
- Monthly cost: $0.

**Non-goals (for now):** multi-user accounts, non-tech roles, Indeed/Glassdoor
scraping, LLM-based enrichment, push notifications (Discord/Telegram).

## 2. Architecture

```
GitHub Actions (cron, public repo)          Supabase (free tier)          Vercel (Hobby)
┌──────────────────────────────┐   upsert   ┌──────────────────────┐ read ┌───────────────────┐
│ Python scraper               │ ─────────▶ │ Postgres             │ ◀─── │ Next.js App Router│
│  adapters → normalize →      │            │  companies, jobs,    │      │  /us  /ca /status │
│  enrich → dedupe → db        │            │  job_sources, ...    │ ───▶ │  Realtime banner  │
│ digest (Jinja → Resend)      │            │ Auth (owner only)    │ RT   └───────────────────┘
└──────────────────────────────┘            │ Realtime             │
                                            └──────────────────────┘
```

- **Scrapers:** Python 3.12, `httpx` (async), `pydantic`, `selectolax` for HTML,
  run by GitHub Actions on cron. Public repo → unlimited Actions minutes.
- **DB:** Supabase Postgres, SQL migrations in `supabase/migrations/`.
- **Web:** Next.js (App Router, TypeScript) + Tailwind v4 mapped to
  `design/tokens.css`, deployed on Vercel Hobby.
- **Email:** Resend free tier (`onboarding@resend.dev` → owner's account email);
  Gmail SMTP app password as fallback.

### Repo layout

```
scraper/
  adapters/      greenhouse.py lever.py ashby.py workday.py smartrecruiters.py
                 workable.py simplify.py linkedin.py  (phase 5: amazon.py google.py ...)
  normalize.py   title, location, term, pay
  enrich/        visa.py flags.py category.py
  dedupe.py      fingerprint + freshness classification
  db.py          Supabase client, batched upserts
  digest/        build.py templates/digest.html.j2
  cli.py         python -m scraper run --tier hot|warm|cold|linkedin [--company X] [--dry-run]
                 python -m scraper digest | h1b-import | maintenance
  tests/         fixtures/<ats>/*.json, test_*.py
web/             Next.js app
supabase/migrations/
design/          DESIGN.md tokens.css
data/companies.seed.yml
digest.config.yml
.github/workflows/
```

## 3. Sources

### Tier 1 — Public ATS APIs (backbone)
| ATS | Endpoint |
|---|---|
| Greenhouse | `GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` |
| Lever | `GET api.lever.co/v0/postings/{slug}?mode=json` |
| Ashby | `GET api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` |
| Workday | `POST {tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` with `searchText: "intern"`, then per-job detail GET |
| SmartRecruiters | `GET api.smartrecruiters.com/v1/companies/{id}/postings` |
| Workable | `POST apply.workable.com/api/v3/accounts/{slug}/jobs` |
| Big tech custom (phase 5) | Amazon, Google, Microsoft, Apple, Meta — one adapter each |

### Tier 2 — Community lists
- SimplifyJobs `Summer2027-Internships` (and successor/related repos) `listings.json`.
  Used as a job source **and** for company discovery. Re-fetched only when the
  repo's latest commit SHA changes.

### Tier 3 — Best effort
- LinkedIn guest endpoint
  `linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=intern&location={Canada|United States}&f_TPR=r3600`,
  6–10 requests per run, randomized delays, cooldown on block (§7).
- Explicitly **not** scraped: Indeed, Glassdoor.

### Company registry & discovery
- `companies` seeded from `data/companies.seed.yml` (curated few hundred tech
  companies with ATS + slug) plus all companies in the Simplify list.
- **Auto-discovery:** any job URL from Simplify/LinkedIn matching a known ATS
  pattern (`boards.greenhouse.io/{slug}`, `job-boards.greenhouse.io/{slug}`,
  `jobs.lever.co/{slug}`, `jobs.ashbyhq.com/{slug}`, `*.myworkdayjobs.com/...`,
  `jobs.smartrecruiters.com/{id}`, `apply.workable.com/{slug}`) → insert company
  (if new) with `discovered_from` set; it is then polled directly.

### Intern & tech filter
- Reject if title has a seniority word: `\b(senior|sr|staff|principal|director|head|vp)\b`.
- Accept if title has a strong intern word: `\b(interns?|internships?|co-?ops?|apprentices?|apprenticeships?)\b`
  or `PEY` (word boundaries mean "Internal"/"International" never match).
- Accept if the ATS employment type says intern/co-op (Lever `commitment`, Ashby `employmentType`).
- Accept a weak word (`student|placement`) only if the title has no
  `manager|coordinator|advisor|recruiter|success|services|officer|counsellor` word.
- Titles only, never descriptions.
- Category by title keywords: `SWE`, `Data/ML`, `Hardware/Embedded`, `PM`,
  `Design`, `Quant`, `IT/Security`, `Other-tech`. Titles that match no tech
  keyword are dropped.

## 4. Data Model

### Tables
**`companies`**
`id, name, ats, slug, workday_host, workday_site, domain, tier (hot|warm|cold|inactive),
last_polled_at, last_success_at, fail_count, consecutive_404s, job_ids_hash,
last_intern_seen_at, discovered_from, h1b_count, h1b_fiscal_year, created_at`
Unique: `(ats, slug)`.

**`jobs`**
`id uuid, company_id, title, normalized_title, category, term, duration_months,
location_raw, locations jsonb [{city, region, country}], country (CA|US|BOTH|UNKNOWN),
work_mode (onsite|hybrid|remote|unknown), location_unclear bool,
pay_min, pay_max, pay_currency, pay_period (hour|year|month|week), pay_hourly_min,
pay_hourly_max, pay_raw,
visa_signals text[], visa_status (open|blocked|unknown), flags text[],
evidence jsonb {signal: sentence},
fingerprint, first_seen_at, last_seen_at, source_posted_at, status (open|closed),
closed_at, miss_count, freshness (fresh|repost|reopened|refreshed|recurring),
repost_of uuid null, repost_count int, best_url, updated_at`
Index: `fingerprint`, `(status, country, first_seen_at desc)`.

**`job_sources`**
`id, job_id, source (greenhouse|lever|...|simplify|linkedin), source_job_id, url,
first_seen_at, last_seen_at`. Unique: `(source, source_job_id)`.

**`scrape_runs`**
`id, workflow, source, started_at, finished_at, companies_polled, jobs_seen,
jobs_new, jobs_closed, errors int, error_samples jsonb`.

**`source_state`**
`source pk, cooldown_until, backoff_seconds, last_commit_sha, notes`.

**`user_job_state`**
`user_id, job_id, state (saved|applied|hidden), updated_at`. PK `(user_id, job_id)`. Created in the phase 4 migration.

**View `jobs_feed`**: open jobs joined with company name/domain/h1b fields,
ordered by `first_seen_at desc`.

### Fingerprint
`sha1(company_id | normalized_title | sorted(normalized location keys))` where
`normalized_title` = lowercase, remove years (`20\d\d`), season words
(`summer|fall|autumn|winter|spring`), term phrases (`\d+[- ]month`), punctuation,
and collapse whitespace.

### Freshness classification (on ingest)
Evaluated in order:
1. `(source, source_job_id)` exists and job is `closed` → **reopened**; reopen
   the row, `status=open`, `closed_at=null`.
2. `(source, source_job_id)` exists and `source_posted_at` advanced while
   `first_seen_at` is > 7 days old → **refreshed** (row kept, date not trusted).
3. `(source, source_job_id)` exists → update `last_seen_at`, no label change.
4. New source ID, fingerprint matches an **open** job → attach as additional
   `job_sources` row (cross-source duplicate), no label change.
5. New source ID, fingerprint matches a job last seen ≤ 120 days ago → new row,
   **repost**, `repost_of` = that job, `repost_count` = prior + 1.
6. New source ID, fingerprint matches a job last seen > 120 days ago → new row,
   **recurring** (treated as fresh in filters, labeled differently).
7. Otherwise → new row, **fresh**.

"Seen" age in the UI always uses `first_seen_at`.

### Closing
- ATS sources: after a **successful** poll of a company, open jobs from that
  source not in the response get `miss_count += 1`; at 2 → `closed`. Seen again
  resets `miss_count`.
- Simplify-only jobs: closed when Simplify marks `active: false`.
- LinkedIn-only jobs: closed after 21 days unseen.

### Storage budget
Full descriptions are **not** stored — only `evidence` sentences. Weekly
maintenance deletes closed jobs older than 12 months and `scrape_runs` older
than 30 days. Target < 100 MB.

## 5. Enrichment

All rule-based (regex), applied to title + description text. Each emitted
signal/flag records its matching sentence in `evidence`.

### Visa signals
| Signal | Patterns (illustrative, case-insensitive) |
|---|---|
| `no_sponsorship` | `will not sponsor`, `unable to sponsor`, `not (able\|eligible) to (provide\|offer) sponsorship`, `without (the need for )?(current or future )?(visa )?sponsorship` |
| `us_citizen_only` | `must be a U\.?S\.? citizen`, `U\.?S\.? persons?`, `green card`, `lawful permanent resident` (US jobs), `ITAR`, `export control` |
| `clearance` | `security clearance`, `\b(secret\|top secret\|TS/SCI)\b`, `reliability status` |
| `us_school_required` | `enrolled (at\|in) a U\.?S\.?`, `CPT`, `OPT` |
| `sponsors` | `sponsorship (is )?available`, `will sponsor`, `\bJ-1\b`, `international (students\|candidates) (are )?(welcome\|encouraged)` |
| `canadian_coop_required` | `co-?op (program\|student).{0,40}canad`, `enrolled .{0,40}canadian (university\|institution\|college)` |

### Visa status (owner profile: Canadian citizen in Canada)
- `country` includes US and job is US-only → `blocked` if any of
  `no_sponsorship | us_citizen_only | clearance | us_school_required`;
  else `open` if `sponsors`; else `unknown`.
- `country = CA` → `open`; `canadian_coop_required`, `clearance` shown as info flags.
- `country = BOTH` → `open` (Canadian location available).
- `country = UNKNOWN` → computed as US.

Profile lives in a single config constant (`OWNER_PROFILE`) so status logic is
one function: `visa_status(signals, country, profile)`.

### H-1B sponsorship hint
Quarterly `h1b-import` downloads the DOL OFLC LCA disclosure file, aggregates
certified H-1B filings per employer, fuzzy-matches to `companies.name`
(normalized: lowercase, strip `inc|llc|corp|ltd|co`), stores `h1b_count` +
fiscal year. Displayed as a hint only.

### Pay
1. Structured fields first: Ashby `compensation`, Lever `salaryRange`,
   Greenhouse pay ranges when present.
2. Else regex over description: currency (`$`, `USD`, `CAD`, `C$`), range or
   single value, period (`/hr|per hour|hourly`, `/yr|per year|annually|salary`,
   `/month`, `/week`). Values < 200 with no period → hour; > 10,000 → year.
3. Currency default: CAD for Canada-only jobs, USD otherwise.
4. Hourly equivalents: year ÷ 2080, month ÷ 173.3, week ÷ 40.

### Location
- Parse segments split on `;`, `|`, ` / `, ` or `, newline.
- Match `City, XX` against US state and Canadian province code/name lists.
- `Remote - US`, `Remote (Canada)`, `US Remote` etc. → country + `work_mode=remote`.
- `hybrid` keyword → `work_mode=hybrid`.
- Bare `Remote` → fallback to company's dominant country from its other jobs; if
  none → `country=UNKNOWN`, `location_unclear=true` (shown in both tabs).

### Term
Regex: `(summer|fall|autumn|winter|spring)\s*20\d\d`, `(\d{1,2})[- ]month`,
`PEY`, `12[- ]16 month`. Output `term` string + `duration_months`.

### Other flags
`new` (computed at query time: first_seen < 24h), `pay_listed`, `remote`,
`hybrid`, `grad_year:<YYYY>` (`graduat\w* .{0,20}(20\d\d)`), `grad_students_only`
(title/desc `phd|master'?s` requirement), `early_years_only`
(`first[- ]year|second[- ]year|freshman|sophomore|STEP`), `eligibility_restricted`
(program restricted to specific groups; evidence shown), `relocation`
(`relocation|housing (stipend|provided)`).

## 6. Scheduling & Operations

| Workflow | Cron (UTC) | Work |
|---|---|---|
| `scrape-hot.yml` | `*/5 * * * *` | tier=hot companies + Simplify (if SHA changed) |
| `scrape-sweep.yml` | `7,37 * * * *` | 500 least-recently-polled warm/cold companies (cold only if last poll > 6h) |
| `scrape-linkedin.yml` | `13,33,53 * * * *` | LinkedIn guest search, US + Canada |
| `digest.yml` | `17 12 * * *` | daily email |
| `h1b-import.yml` | `0 9 1 1,4,7,10 *` | DOL data refresh |
| `maintenance.yml` | `0 8 * * 0` | prune, re-tier, commit `STATS.md` |
| `ci.yml` | on push/PR | ruff, pytest, migration test, `next build` |

- Every workflow has a `concurrency` group with `cancel-in-progress: false`.
- **Tiering (maintenance + on ingest):** `hot` = curated-hot in seed OR intern
  job seen in last 30 days; `warm` = default; `cold` = no intern job in 90 days;
  `inactive` = 5 consecutive 404s.
- **Change detection:** `job_ids_hash` of sorted source IDs per company; if
  unchanged, skip parse/enrich and bulk-update `last_seen_at`.
- **Politeness:** per-ATS-host concurrency limit 5, `User-Agent:
  intern-job-scraper (+https://github.com/baldeep06/jobs-scraping)`.
- **Keepalive:** `maintenance` commits `STATS.md` weekly so GitHub doesn't
  disable schedules after 60 days of inactivity. Scraper writes keep Supabase
  from pausing.
- **Secrets:** `DATABASE_URL` (Supabase **session pooler** URI — GitHub runners
  have no IPv6, so the direct connection won't work), `RESEND_API_KEY`, `DIGEST_TO`
  in GitHub Secrets; never logged (logs are public). The scraper talks to Postgres
  directly via `psycopg`; the website uses `SUPABASE_URL` + anon key.
- **Health:** a source is `degraded` if no successful run in 60 min; shown on
  `/status` and in the digest. GitHub's default failure emails cover crashes.

## 7. Error Handling

- Per-company isolation: each company fetch is wrapped; failures increment
  `fail_count` and are sampled into `scrape_runs.error_samples`.
- HTTP: 15 s timeout, 3 retries with exponential backoff + jitter on
  429/5xx/network errors.
- Adapter outputs validated by a `RawJob` pydantic model; invalid records are
  dropped and counted.
- All writes are idempotent upserts keyed on `(source, source_job_id)`.
- Closing only happens after a successful poll and 2 consecutive misses.
- LinkedIn: 429/999 or redirect to `/authwall` → `source_state.cooldown_until`
  = now + backoff (start 1h, double each time, max 24h; reset on success).

## 8. Website

- **Data access:** server components query `jobs_feed` with the anon key; RLS
  allows anon `select` on open jobs and companies only. `user_job_state`
  read/write only for the authenticated owner (Supabase Auth magic link;
  sign-ups disabled, owner account created manually).
- **Routes:** `/` → redirect `/us`; `/us`, `/ca` (job table); `/status`.
- **Header:** White Surface nav bar (Jobs · Status).
- **Hero:** Horizon gradient band, Poppins headline with live counts
  ("N open tech internships · M new today"), search field.
- **Region tabs:** US | Canada. `BOTH` and `location_unclear` jobs in both.
- **Filters (URL query params):** `q`, `category`, `term`, `visa`
  (default for US: hide `blocked`), `within` (1h|24h|7d|all), `fresh`, `pay`,
  `remote`, `state` (applied|saved), `sort` (new|pay). 50 rows/page, server-side.
- **Columns:** Company (favicon via Google s2, H-1B hint tooltip on US), Role
  (link to `best_url`), Category, Location (+ work-mode badge), Term, Pay
  (hourly; raw on hover), Visa badge (evidence tooltip), Flags, Freshness, Seen
  (relative from `first_seen_at`), You (applied ✓ / hide ✕ when logged in).
- **Row expand:** all evidence sentences, all source links, repost history,
  raw pay text.
- **Realtime:** subscribe to `jobs` inserts → "N new jobs — refresh" banner.
- **Mobile (< 768px):** rows render as stacked cards.
- **Styling:** follows `design/DESIGN.md`, including "Adaptations for the Job
  Table" badge colors.

## 9. Daily Digest

- Content: jobs with `first_seen_at` in last 24h matching
  `digest.config.yml` (categories, `hide_blocked`, `fresh_only`,
  `min_hourly_pay`), grouped US / Canada:
  1. Top picks — visa open (or Canada) + pay listed + fresh.
  2. All other new matches (company · role · location · pay · visa · link).
  3. Saved jobs that closed since last digest.
  4. Health line.
- Sent even when empty. Recipient from `DIGEST_TO` secret.
- Rendered with Jinja (`scraper/digest/templates/digest.html.j2`), inline styles
  from design tokens. Sent via Resend; SMTP fallback via env switch.

## 10. Testing

- **Adapters:** recorded API responses per ATS in `scraper/tests/fixtures/`;
  assert parsed `RawJob` lists.
- **Enrichment:** table-driven tests (~100 real phrases to start) for visa
  signals, visa status, pay, location, term, flags. Every misclassification
  found in production becomes a new case.
- **Dedupe:** one test per freshness rule (§4) plus closing logic, with an
  injected clock.
- **DB:** CI spins up Postgres (service container), applies
  `supabase/migrations`, checks `jobs_feed` and RLS policies.
- **Web:** `next build` + typecheck in CI; filter-param parsing unit-tested.
- **Smoke:** `python -m scraper run --dry-run --company <slug>` prints enriched
  jobs without writing.

## 11. Phases

1. Supabase schema; Greenhouse/Lever/Ashby adapters; normalize, enrich, dedupe;
   `scrape-hot` workflow; CI. → real jobs in DB.
2. Website: tabs, table, filters, row expand, design system.
3. Workday + SmartRecruiters + Workable adapters; Simplify source + discovery;
   tiering; `scrape-sweep`.
4. Digest; LinkedIn; H-1B import; `/status`; Realtime banner; owner auth +
   applied/hide.
5. Big-tech custom adapters (Amazon, Google, Microsoft, Apple, Meta).

## 12. Risks

- **GitHub cron latency** can exceed 5 min under load. Mitigation later: a
  Supabase `pg_cron` watchdog that triggers `workflow_dispatch` if
  `scrape-hot` hasn't run in 15 min.
- **LinkedIn blocking/ToS:** best-effort only; system works without it.
- **ATS endpoint changes:** fixture tests + `/status` degradation surfacing.
- **Regex enrichment accuracy:** evidence sentences make errors visible;
  test suite grows from real misses.
