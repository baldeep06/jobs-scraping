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

**Sources:** Greenhouse, Lever, Ashby, Workday, SmartRecruiters and Workable boards. New boards are
discovered from the SimplifyJobs lists (checked whenever that repo has a new commit).

**Tiers:** `hot` (curated, or an internship seen in the last 30 days; polled every 5 minutes by
`scrape-hot`), `warm` and `cold` (polled in a 30-minute sweep by `scrape-sweep`; cold only every 6 h),
`inactive` (board gone). The weekly `maintenance` workflow re-tiers, prunes old run logs and
commits `STATS.md`, which also keeps GitHub from disabling the schedules.

**Fresh vs repost:** a posting is `fresh` only if it appeared after we started watching its company.
Postings already open when we first saw them are `existing` ("Already open"). A new ID that matches a
closed posting (same title words, or the same description, in the same country, within 120 days)
is a `repost`; a new term of the same role (Summer 2026 → Summer 2027) is a new opportunity.

- Spec: [`docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md`](docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md)
- Design reference: [`design/DESIGN.md`](design/DESIGN.md)

WIP 


## Daily digest and status

`python -m scraper digest` emails new internships from the last 24 hours (`digest.config.yml` picks
categories, hides blocked visas, keeps fresh postings only) and ends with a health line. A GitHub
workflow runs it daily at 12:17 UTC. It needs the repository secrets `RESEND_API_KEY` and `DIGEST_TO`
(optionally `DIGEST_FROM`; set `DIGEST_TRANSPORT=smtp` with `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`
to use SMTP instead). `--dry-run --out digest.html` previews it without sending. The website's
`/status` page shows the same health check: a workflow is degraded if it has not finished a run within
60 minutes (`scrape-hot`) or 120 minutes (`scrape-sweep`).
