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

Commands: `python -m scraper migrate | seed [--verify] | run [--tier hot] [--dry-run]`.

- Spec: [`docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md`](docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md)
- Design reference: [`design/DESIGN.md`](design/DESIGN.md)

WIP 
