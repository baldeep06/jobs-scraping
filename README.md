# Intern Job Scraper

A $0-cost internship job board for **Canada** and the **US**. Continuously scrapes
company ATS portals (Greenhouse, Lever, Ashby, Workday, …) and job boards, flags
visa sponsorship, pay, and reposts, and serves everything in a filterable table.

**Status:** Phase 1 — scraper core (Greenhouse, Lever, Ashby → Supabase every 5 min).

## Local development

```bash
uv sync
docker run -d --name jobs-pg -e POSTGRES_PASSWORD=postgres -p 54329:5432 postgres:17
cp .env.example .env            # fill in DATABASE_URL
uv run --env-file .env pytest   # TEST_DATABASE_URL from .env
uv run python -m scraper run --dry-run --company stripe --ats greenhouse   # no DB needed
```

Commands: `python -m scraper migrate | seed [--verify] | discover | digest [--dry-run] | run [--tier hot | --sweep] [--ats X] [--dry-run] | maintenance`.

**Sources:** Greenhouse, Lever, Ashby, Workday, SmartRecruiters and Workable boards, plus the
career sites of Amazon, Microsoft, Apple and Google, and Meta (read from its published job sitemap and
each job page's structured data, because its API needs rotating tokens).

**Meta:** Meta's `robots.txt` states that automated collection is prohibited without written
permission. The Meta adapter is deliberately gentle (one sitemap request per poll, never-seen pages
only, at most 120 per poll, each page remembered once read). To stop every request to
metacareers.com, add `disabled: true` to the `meta` line in `data/companies.seed.yml` and run
`python -m scraper seed`: the company goes inactive and its open jobs are closed. (Removing the line
alone changes nothing; `seed` never deletes companies.) New boards are
discovered from the SimplifyJobs lists (checked whenever that repo has a new commit).

**Tiers:** `hot` (curated, or an internship seen in the last 30 days), `warm`, `cold` and
`inactive` (board gone). Hot companies are polled in three lanes, each its own workflow:
`scrape-express` every minute (curated companies), `scrape-fast` every 2 minutes (other hot companies
on one-request boards: Greenhouse, Lever, Ashby, Pinpoint, ...) and `scrape-heavy` every 5 minutes (Workday,
Workable, Oracle, Eightfold, Avature, SuccessFactors, Phenom, D. E. Shaw, Shopify and the big-tech sites,
TikTok included). `scrape-sweep` polls warm companies, cold ones every 6 h,
the Simplify and intern-list aggregators, and any company that failed 3 times in a row, every 30
minutes. Requests are capped at 5 per host and 20 per vendor (8 for Workday, whose tenants share one
cap; each Workday tenant is polled at most every 15 minutes), and a `Retry-After` longer than a minute
drops the request instead of stalling the pass. A vendor that mostly answers 403/429 or non-JSON pages
in a pass is left alone for the rest of it, and its ATS rests (30 minutes, doubling up to 6 hours
while the blocking lasts; reset once it answers normally). The weekly `maintenance` workflow re-tiers, prunes old run logs and
commits `STATS.md`, which also keeps GitHub from disabling the schedules.

**Fresh vs repost:** a posting is `fresh` only if it appeared after we started watching its company.
Postings already open when we first saw them are `existing` ("Already open"). A new ID that matches a
closed posting (same title words, or the same description, in the same country, within 120 days)
is a `repost`; a new term of the same role (Summer 2026 → Summer 2027) is a new opportunity.

- Spec: [`docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md`](docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md)
- Design reference: [`design/DESIGN.md`](design/DESIGN.md)

WIP 


## Daily digest and status

**Priority alerts:** every scrape pass also emails new SWE internships at FAANG+, big-tech,
big-tech-adjacent, unicorn and AI-lab companies (company groups in `data/company_groups.yml`) within
minutes of finding them (never between midnight and 8 am Toronto time; those go out at 8): fresh
postings only (no reposts or backlog), first seen in the last 12 hours,
visa-blocked US roles skipped, at most 20 jobs an hour, each job once. It uses the digest's email
settings (`RESEND_API_KEY`, `DIGEST_TO`); without them it does nothing. Rules live in
`scraper/digest/alerts.py`.

`python -m scraper digest` emails new internships from the last 24 hours (`digest.config.yml` picks
categories, hides blocked visas, keeps fresh postings only) and ends with a health line. A GitHub
workflow runs it daily at 13:17 UTC (08:17 Toronto in winter, 09:17 in summer). It needs the repository secrets `RESEND_API_KEY` and `DIGEST_TO`
(optionally `DIGEST_FROM`; set `DIGEST_TRANSPORT=smtp` with `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`
to use SMTP instead). `--dry-run --out digest.html` previews it without sending. The website's
`/status` page shows the same health check: a workflow is degraded if it has not finished a run within
10, 15, 30 or 120 minutes (`scrape-express`, `scrape-fast`, `scrape-heavy`, `scrape-sweep`).
