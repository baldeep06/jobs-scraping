# Phase 3 — Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Workday, SmartRecruiters and Workable adapters, auto-discover companies from the SimplifyJobs list, tier companies by activity, poll the non-hot ones on a 30-minute sweep, and keep the repo alive with a weekly maintenance job that commits `STATS.md`.

**Architecture:** New adapters follow the existing `async fetch(fetcher, company) -> FetchResult` contract and register in `ADAPTERS`. The three new ATSes are *search-based* (the API is asked for "intern"), so a successful search that returns zero hits must be able to close the last open job (`confirmed_empty`). Discovery reads Simplify's `listings.json` only when the repo's latest commit SHA changed (SHA kept in `source_state`), extracts ATS board URLs, and inserts new `warm` companies. Tiering is SQL (`retier`, promotion on ingest); the sweep picks the least-recently-polled warm/cold companies.

**Tech Stack:** Python 3.12, httpx (MockTransport in tests), pydantic v2, psycopg3, pytest, ruff, GitHub Actions. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md` (§3 Sources, §6 Scheduling, §11 Phase 3)

## Global Constraints

- Python line length 100, ruff rules `E,F,I,UP,B`; `uv run ruff check . && uv run ruff format --check .` must pass.
- Tests: `uv run pytest -q`; DB tests need `TEST_DATABASE_URL` (local container `jobs-pg` on port 54329: `postgresql://postgres:postgres@localhost:54329/postgres`), and refuse URLs containing "supabase".
- User-Agent `intern-job-scraper (+https://github.com/baldeep06/jobs-scraping)`; per-host concurrency 5 (already in `Fetcher`).
- HTTP: 15 s timeout, 3 retries (already in `Fetcher`).
- Every workflow: `concurrency` group with `cancel-in-progress: false`.
- Tiering: `hot` = curated-hot OR intern job seen in the last 30 days; `warm` = default; `cold` = no intern job in 90 days; `inactive` = 5 consecutive 404s (already implemented, never overwritten by re-tiering).
- Sweep: 500 least-recently-polled warm/cold companies per run; cold only if last poll > 6 h ago.
- **Authorship:** every commit is authored by `baldeep06 <92562237+baldeep06@users.noreply.github.com>`; **no** `Co-Authored-By` line and no "Generated with" line in any commit message or PR body (user rule, overrides default attribution). Verify with `git log --format='%an <%ae>%n%b' main..HEAD` before pushing.
- Secrets (DATABASE_URL etc.) are never printed or committed. No new secrets are needed in this phase (`GITHUB_TOKEN` is built in).
- Work on branch `phase-3-coverage`, not `main`.

## Rulings made while planning (carried into execution)

- **Simplify as a job source is deferred.** Phase 3 uses Simplify for *discovery only*: jobs arrive by polling the discovered companies' own ATS boards, which has better data (pay, descriptions) than Simplify rows. Simplify-only jobs (TikTok, Tesla, Oracle HCM … no supported ATS) would need a `companies.ats` value for "no ATS"; revisit in a later phase.
- **Discovery runs in `scrape-sweep`**, not `scrape-hot` (the spec says hot): it feeds warm companies, and the sweep is where they are polled. Cost is one authenticated GitHub API call per run.
- **Workday `source_posted_at` stays `None`.** Workday only gives "Posted 21 Days Ago"; deriving a date from `now` would drift daily and could trip the "refreshed" classifier. `first_seen_at` is the freshness basis.
- **A detail-fetch failure drops that one posting from the poll** (not the company): a 404 on one job's detail must never count toward the company's 404-inactive streak.

## Review Focus

- **Last intern posting removed** (search returns `total: 0` with HTTP 200): the open job must close after two polls; an HTTP error or malformed payload must never close anything. (Task 1, Tasks 3–5)
- **Workday multi-location rows** ("2 Locations" in the list): location must come from the detail call, not the list's `locationsText`. (Task 5)
- **Workday "US, CA, Santa Clara"** — `CA` here is California, not Canada: must parse as US/CA-region, while "CA, ON, Toronto" parses as Canada. (Task 5)
- **Search noise** — `searchText: intern` matches "International"/"Internal"; detail GETs must only be made for titles that pass `wanted()`. (Tasks 3–5)
- **Simplify URLs** with locale prefixes (`/en-US/`), trailing paths/query strings, unknown hosts, `boards.greenhouse.io/embed/...`, and the same company repeated hundreds of times: each board is discovered once, junk is ignored. (Task 6)
- **Simplify SHA unchanged / GitHub API failing**: no 7 MB download, no DB writes, exit code 0, old SHA kept. (Task 6)

## File Structure

- Modify `scraper/models.py` — `Company.workday_host/site`, `FetchResult.confirmed_empty`, `CompanyOutcome.confirmed_empty`.
- Modify `scraper/pipeline.py` — pass `confirmed_empty` through `process`.
- Modify `scraper/db.py` — workday columns, `confirmed_empty` closure rule, `discover_companies`, state SHA get/set, `retier`, hot promotion on ingest, `get_sweep_companies`, `prune`, `stats`.
- Modify `scraper/adapters/base.py` — `wanted()`, `get_details()`.
- Create `scraper/adapters/workable.py`, `smartrecruiters.py`, `workday.py`; modify `scraper/adapters/__init__.py`.
- Create `scraper/discovery.py` — URL → board parsing, Simplify fetch + SHA check.
- Create `scraper/stats.py` — renders `STATS.md`.
- Modify `scraper/__main__.py` — `discover`, `maintenance` commands, `run --sweep`, workday seed validation.
- Create `.github/workflows/scrape-sweep.yml`, `maintenance.yml`.
- Modify `data/companies.seed.yml` (curated Workday/SmartRecruiters/Workable entries), `README.md`, `.env.example` (none needed).
- Tests: `scraper/tests/test_adapters_new.py`, `test_discovery.py`, `test_tiering.py`, `test_stats.py`, plus additions to `test_db_ingest.py`, `test_cli.py`; fixtures in `scraper/tests/fixtures/`.

---

### Task 1: Company workday fields and `confirmed_empty`

**Files:**
- Modify: `scraper/models.py`, `scraper/pipeline.py`, `scraper/db.py` (`upsert_companies`, `get_companies`, `ingest`), `scraper/__main__.py` (`load_seeds`)
- Test: `scraper/tests/test_db_ingest.py`, `scraper/tests/test_pipeline.py`, `scraper/tests/test_cli.py`

**Interfaces:**
- Produces: `Company.workday_host: str | None`, `Company.workday_site: str | None`; `FetchResult.confirmed_empty: bool = False`; `CompanyOutcome.confirmed_empty: bool = False`. Seeds with `ats: workday` require `workday_host` and `workday_site`.

- [ ] **Step 1: Branch**

```bash
cd /Users/baldeeppannu/jobs-scraping && git checkout -b phase-3-coverage
```

- [ ] **Step 2: Write the failing tests**

Append to `scraper/tests/test_db_ingest.py`:

```python
def test_workday_fields_round_trip(conn):
    db.upsert_companies(
        conn,
        [{"name": "Nvidia", "ats": "workday", "slug": "nvidia/Site", "hot": True,
          "workday_host": "nvidia.wd5.myworkdayjobs.com", "workday_site": "Site"}],
    )  # fmt: skip
    c = db.get_companies(conn, ats=["workday"])[0]
    assert (c.workday_host, c.workday_site) == ("nvidia.wd5.myworkdayjobs.com", "Site")


def _empty_outcome(c, confirmed):
    return CompanyOutcome(
        company=c, ok=True, seen_ids=set(), ids_hash=ids_hash(set()), confirmed_empty=confirmed
    )


def test_confirmed_empty_board_closes_after_two_polls(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")] + other()), T0)
    for i in (1, 2):
        c = db.get_companies(conn, ats=["greenhouse"], slug="acme")[0]
        db.ingest(conn, _empty_outcome(c, True), T0 + timedelta(minutes=5 * i))
    assert jobs(conn)[0]["status"] == "closed"


def test_unconfirmed_empty_board_never_closes(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")] + other()), T0)
    for i in (1, 2, 3):
        c = db.get_companies(conn, ats=["greenhouse"], slug="acme")[0]
        db.ingest(conn, _empty_outcome(c, False), T0 + timedelta(minutes=5 * i))
    assert jobs(conn)[0]["status"] == "open"
```

Append to `scraper/tests/test_pipeline.py` (reuse its imports; add `FetchResult` if missing):

```python
def test_process_carries_confirmed_empty():
    from scraper.models import Company, FetchResult
    from scraper.pipeline import process

    c = Company(id=1, name="A", ats="workday", slug="a/b")
    out = process(c, FetchResult(jobs=[], confirmed_empty=True))
    assert out.ok and out.confirmed_empty
```

Append to `scraper/tests/test_cli.py`:

```python
def test_workday_seed_needs_host_and_site(tmp_path):
    bad = tmp_path / "seed.yml"
    bad.write_text("- {name: X, ats: workday, slug: x/y}\n")
    with pytest.raises(ValueError, match="workday"):
        load_seeds(bad)
```

- [ ] **Step 3: Run to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest scraper/tests/test_db_ingest.py scraper/tests/test_pipeline.py scraper/tests/test_cli.py -q`
Expected: FAIL (`confirmed_empty` unknown keyword, `ats: workday` rejected by `load_seeds`, workday columns missing).

- [ ] **Step 4: Implement**

`scraper/models.py` — extend:

```python
class Company(BaseModel):
    id: int
    name: str
    ats: str
    slug: str
    job_ids_hash: str | None = None
    workday_host: str | None = None
    workday_site: str | None = None
```

In `FetchResult` add `confirmed_empty: bool = False` (after `invalid`); in `CompanyOutcome` add `confirmed_empty: bool = False` (after `unchanged`).

`scraper/pipeline.py` — in `process`, construct the outcome with `confirmed_empty=result.confirmed_empty`:

```python
    outcome = CompanyOutcome(
        company=company,
        ok=True,
        seen_ids=seen,
        ids_hash=board_hash(seen),
        invalid=result.invalid,
        confirmed_empty=result.confirmed_empty,
    )
```

`scraper/db.py`:

- `upsert_companies`: add `workday_host, workday_site` to the column list and values (`%(workday_host)s, %(workday_site)s`), to the `do update set` (`workday_host = excluded.workday_host, workday_site = excluded.workday_site`), and to the params dict (`"workday_host": s.get("workday_host"), "workday_site": s.get("workday_site")`).
- `get_companies`: select `id, name, ats, slug, job_ids_hash, workday_host, workday_site`.
- `ingest`: change the closure guard to

```python
        if (outcome.seen_ids or outcome.confirmed_empty) and not outcome.invalid:
```

`scraper/__main__.py` — in `load_seeds`, after the existing check:

```python
        if s["ats"] == "workday" and not (s.get("workday_host") and s.get("workday_site")):
            raise ValueError(f"workday seed needs workday_host and workday_site: {s}")
```

(The ADAPTERS check comes first, so `workday` must already be registered for this error to be reached: do the registration in Task 5. Until then this test is expected to fail on the "ats not in ADAPTERS" `ValueError` whose message does not contain "workday" — see Step 5.)

- [ ] **Step 5: Run to verify**

Run the Step 3 command. Expected: db + pipeline tests PASS; `test_workday_seed_needs_host_and_site` PASSES only once Task 5 registers the adapter. To keep this task self-contained, temporarily make the existing check message include the ats: change the bad-entry message to `f"bad seed entry (ats={s.get('ats')}): {s}"`. Then the test passes now ("workday" appears in the message via `ats=workday`) and continues to pass after Task 5.

- [ ] **Step 6: Full suite + commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all PASS.

```bash
git add scraper && git commit -m "feat: workday company fields and confirmed-empty boards"
```

---

### Task 2: Shared adapter helpers (`wanted`, `get_details`)

**Files:**
- Modify: `scraper/adapters/base.py`
- Test: `scraper/tests/test_adapters_new.py` (create)

**Interfaces:**
- Produces: `wanted(title: str, employment_type: str | None = None) -> bool` (True when the title is an intern title *and* has a tech category); `async get_details(fetcher: Fetcher, urls: dict[str, str]) -> dict[str, dict]` (GET each URL concurrently; keys whose request fails or isn't a JSON object are omitted).

- [ ] **Step 1: Write the failing test** — create `scraper/tests/test_adapters_new.py`:

```python
import json
from pathlib import Path

import httpx

from scraper.adapters.base import get_details, wanted
from scraper.http import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def test_wanted_needs_intern_and_tech():
    assert wanted("Software Engineer Intern")
    assert not wanted("International Sales Manager")
    assert not wanted("Marketing Intern")  # intern but no tech category
    assert not wanted("Senior Software Engineer")
    assert wanted("Software Engineer", "Intern")  # employment type counts


async def test_get_details_skips_failures():
    def handler(request):
        if request.url.path.endswith("/bad"):
            return httpx.Response(404)
        if request.url.path.endswith("/list"):
            return httpx.Response(200, json=[1])
        return httpx.Response(200, json={"ok": request.url.path})

    async with make_fetcher(handler) as f:
        got = await get_details(
            f, {"a": "https://x.test/a", "b": "https://x.test/bad", "c": "https://x.test/list"}
        )
    assert got == {"a": {"ok": "/a"}}

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_details'`.

- [ ] **Step 3: Implement** — replace the imports at the top of `scraper/adapters/base.py` and append the helpers:

```python
import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import ValidationError

from scraper.enrich.category import categorize, is_intern_title
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult, RawJob
```

```python
def wanted(title: str, employment_type: str | None = None) -> bool:
    """Cheap pre-check so search-based adapters only fetch details for plausible postings."""
    return is_intern_title(title, employment_type) and categorize(title) is not None


async def get_details(fetcher: Fetcher, urls: dict[str, str]) -> dict[str, dict[str, Any]]:
    """GET every url concurrently. A failed or non-object response just omits that key, so one
    removed posting can never fail (or 404-deactivate) the whole company."""

    async def one(key: str, url: str) -> tuple[str, Any]:
        try:
            return key, await fetcher.json("GET", url)
        except FetchError:
            return key, None

    pairs = await asyncio.gather(*(one(k, u) for k, u in urls.items()))
    return {k: v for k, v in pairs if isinstance(v, dict)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q`
Expected: 2 passed. Then the full suite: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest -q` → PASS (check there is no circular import).

- [ ] **Step 5: Commit**

```bash
git add scraper && git commit -m "feat: shared adapter helpers for search-based ATSes"
```

---

### Task 3: Workable adapter

**Files:**
- Create: `scraper/adapters/workable.py`, `scraper/tests/fixtures/workable_list.json`, `scraper/tests/fixtures/workable_detail.json`
- Modify: `scraper/adapters/__init__.py`, `scraper/tests/test_adapters_new.py`

**Interfaces:**
- Consumes: `wanted`, `get_details`, `validate`, `Fetcher.json`, `html_to_text`.
- Produces: `workable.fetch(fetcher, company) -> FetchResult`; `workable.SOURCE = "workable"`; registered as `ADAPTERS["workable"]`.

- [ ] **Step 1: Fixtures**

`scraper/tests/fixtures/workable_list.json`:

```json
{
  "total": 3,
  "results": [
    {"id": 1, "shortcode": "AAA111", "title": "Software Engineer Intern", "remote": false,
     "location": {"country": "Canada", "countryCode": "CA", "city": "Toronto", "region": "Ontario"},
     "state": "published", "published": "2026-09-30T00:00:00.000Z", "type": "intern",
     "workplace": "hybrid"},
    {"id": 2, "shortcode": "BBB222", "title": "International Sales Manager", "remote": false,
     "location": {"country": "United States", "countryCode": "US", "city": "Austin", "region": "Texas"},
     "state": "published", "published": "2026-09-01T00:00:00.000Z", "type": "full",
     "workplace": "on_site"},
    {"id": 3, "shortcode": "CCC333", "title": "Data Science Intern", "remote": true,
     "location": {"country": "United States", "countryCode": "US", "city": "", "region": null},
     "state": "published", "published": "2026-10-01T00:00:00.000Z", "type": "intern",
     "workplace": "remote"}
  ]
}
```

`scraper/tests/fixtures/workable_detail.json`:

```json
{"shortcode": "AAA111", "description": "<p>Build things.</p>", "requirements": "<ul><li>Python</li></ul>", "benefits": "<p>Pay: CA$30 - CA$35 per hour.</p>"}
```

- [ ] **Step 2: Write the failing tests** — append to `scraper/tests/test_adapters_new.py`:

```python
from datetime import UTC, datetime

import pytest

from scraper.adapters import ADAPTERS, workable
from scraper.http import FetchError
from scraper.models import Company


async def test_workable_fetch_details_only_for_wanted_titles():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json=load("workable_list.json"))
        if request.url.path.endswith("AAA111"):
            return httpx.Response(200, json=load("workable_detail.json"))
        return httpx.Response(404)  # CCC333's detail vanished

    company = Company(id=1, name="Acme", ats="workable", slug="acme")
    async with make_fetcher(handler) as f:
        result = await ADAPTERS["workable"](f, company)

    assert ("GET", "/api/v2/accounts/acme/jobs/BBB222") not in seen  # not an intern title
    assert ("GET", "/api/v2/accounts/acme/jobs/AAA111") in seen
    # AAA111 has details; BBB222 is kept (no details needed, enrich drops it);
    # CCC333 wanted a detail that 404'd, so it is dropped from this poll.
    assert [j.source_job_id for j in result.jobs] == ["AAA111", "BBB222"]
    first = result.jobs[0]
    assert first.url == "https://apply.workable.com/acme/j/AAA111/"
    assert first.location_raw == "Toronto, Ontario, Canada"
    assert first.country_hint == "CA"
    assert first.work_mode_hint == "hybrid"
    assert first.employment_type_hint == "intern"
    assert first.source_posted_at == datetime(2026, 9, 30, tzinfo=UTC)
    assert first.description_text == "Build things.\nPython\nPay: CA$30 - CA$35 per hour."
    assert not result.confirmed_empty


async def test_workable_zero_total_is_confirmed_empty():
    def handler(request):
        return httpx.Response(200, json={"total": 0, "results": []})

    async with make_fetcher(handler) as f:
        result = await workable.fetch(f, Company(id=1, name="A", ats="workable", slug="a"))
    assert result.jobs == [] and result.confirmed_empty


async def test_workable_bad_payload_is_an_error():
    def handler(request):
        return httpx.Response(200, json={"oops": 1})

    async with make_fetcher(handler) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await workable.fetch(f, Company(id=1, name="A", ats="workable", slug="a"))
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q`
Expected: FAIL (`cannot import name 'workable'`).

- [ ] **Step 4: Implement** — `scraper/adapters/workable.py`:

```python
from typing import Any

from scraper.adapters.base import get_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "workable"
MAX_PAGES = 5
_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on_site": "onsite"}


def list_url(slug: str) -> str:
    return f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"


def detail_url(slug: str, shortcode: str) -> str:
    return f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}"


def _location(item: dict[str, Any]) -> str:
    loc = item.get("location") or {}
    return ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)


def _description(detail: dict[str, Any]) -> str:
    parts = (html_to_text(detail.get(k) or "") for k in ("description", "requirements", "benefits"))
    return "\n".join(p for p in parts if p)


def _record(slug: str, item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    code = item.get("shortcode") or ""
    return {
        "source": SOURCE,
        "source_job_id": code,
        "title": item.get("title") or "",
        "url": f"https://apply.workable.com/{slug}/j/{code}/",
        "location_raw": _location(item),
        "description_text": _description(detail),
        "source_posted_at": item.get("published"),
        "work_mode_hint": _WORKPLACE.get(item.get("workplace") or ""),
        "country_hint": (item.get("location") or {}).get("countryCode"),
        "employment_type_hint": item.get("type"),
    }


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    items: list[dict[str, Any]] = []
    total: int | None = None
    token = None
    for page_no in range(MAX_PAGES):
        body: dict[str, Any] = {
            "query": "intern", "location": [], "department": [], "worktype": [], "remote": []
        }  # fmt: skip
        if token:
            body["token"] = token
        page = await fetcher.json("POST", list_url(company.slug), json=body)
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            raise FetchError("unexpected Workable payload")
        items.extend(page["results"])
        if page_no == 0:
            total = page.get("total")
        token = page.get("nextPage")
        if not token:
            break

    want = {
        i["shortcode"]: detail_url(company.slug, i["shortcode"])
        for i in items
        if i.get("shortcode") and wanted(i.get("title") or "", i.get("type"))
    }
    details = await get_details(fetcher, want)
    records = [
        _record(company.slug, i, details.get(i.get("shortcode") or "", {}))
        for i in items
        if i.get("shortcode") not in want or i["shortcode"] in details
    ]
    result = validate(records)
    result.confirmed_empty = not items and total == 0
    return result
```

`scraper/adapters/__init__.py`:

```python
from scraper.adapters import ashby, greenhouse, lever, workable
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "workable": workable.fetch,
}
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q`
Expected: all PASS. Fix the fixture/assertion mismatch if the description join differs (the plan's expected text is the contract).

- [ ] **Step 6: Live check** (one real board; no DB):

Run: `uv run python -m scraper run --dry-run --company huggingface --ats workable`
Expected: `✓ workable/huggingface: N postings…` or `0` postings with no `✗`. Record the result in the ledger.

- [ ] **Step 7: Full suite + commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest -q && uv run ruff check . && uv run ruff format --check .` → PASS.

```bash
git add scraper && git commit -m "feat: Workable adapter"
```

---

### Task 4: SmartRecruiters adapter

**Files:**
- Create: `scraper/adapters/smartrecruiters.py`, `scraper/tests/fixtures/smartrecruiters_list.json`, `scraper/tests/fixtures/smartrecruiters_detail.json`
- Modify: `scraper/adapters/__init__.py`, `scraper/tests/test_adapters_new.py`

**Interfaces:**
- Produces: `smartrecruiters.fetch`; `ADAPTERS["smartrecruiters"]`.

- [ ] **Step 1: Fixtures**

`smartrecruiters_list.json`:

```json
{
  "offset": 0, "limit": 100, "totalFound": 2,
  "content": [
    {"id": "111", "name": "Software Engineer Intern (Summer 2027)",
     "releasedDate": "2026-10-01T10:00:00.000Z",
     "location": {"city": "Toronto", "region": "ON", "country": "ca", "remote": false,
                  "hybrid": true, "fullLocation": "Toronto, ON, Canada"},
     "typeOfEmployment": {"id": "intern", "label": "Intern"}},
    {"id": "222", "name": "Internal Audit Director",
     "releasedDate": "2026-09-01T10:00:00.000Z",
     "location": {"city": "Chicago", "region": "IL", "country": "us", "remote": true,
                  "hybrid": false, "fullLocation": "Chicago, IL, United States"},
     "typeOfEmployment": {"id": "permanent", "label": "Full-time"}}
  ]
}
```

`smartrecruiters_detail.json`:

```json
{"id": "111", "postingUrl": "https://jobs.smartrecruiters.com/Acme/111-software-engineer-intern",
 "jobAd": {"sections": {
   "companyDescription": {"title": "Company", "text": "<p>We build.</p>"},
   "jobDescription": {"title": "Job", "text": "<p>Write code.</p>"},
   "qualifications": {"title": "Quals", "text": "<ul><li>Python</li></ul>"},
   "additionalInformation": {"title": "More", "text": "<p>Pay: US$40 - US$45 per hour.</p>"}}}}
```

- [ ] **Step 2: Write the failing tests** — append to `test_adapters_new.py`:

```python
from scraper.adapters import smartrecruiters


async def test_smartrecruiters_fetch():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.endswith("/postings") and request.method == "GET":
            return httpx.Response(200, json=load("smartrecruiters_list.json"))
        return httpx.Response(200, json=load("smartrecruiters_detail.json"))

    company = Company(id=1, name="Acme", ats="smartrecruiters", slug="Acme")
    async with make_fetcher(handler) as f:
        result = await ADAPTERS["smartrecruiters"](f, company)

    assert "https://api.smartrecruiters.com/v1/companies/Acme/postings/222" not in seen
    assert "https://api.smartrecruiters.com/v1/companies/Acme/postings/111" in seen
    assert [j.source_job_id for j in result.jobs] == ["111", "222"]
    job = result.jobs[0]
    assert job.url == "https://jobs.smartrecruiters.com/Acme/111-software-engineer-intern"
    assert job.location_raw == "Toronto, ON, Canada"
    assert job.country_hint == "CA"
    assert job.work_mode_hint == "hybrid"
    assert job.employment_type_hint == "Intern"
    assert job.source_posted_at == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert job.description_text.splitlines()[-1] == "Pay: US$40 - US$45 per hour."
    assert result.jobs[1].work_mode_hint == "remote"


async def test_smartrecruiters_paginates_until_total():
    offsets = []

    def handler(request):
        offsets.append(request.url.params["offset"])
        n = int(request.url.params["offset"])
        content = [{"id": str(n + i), "name": "Account Executive", "location": {}}
                   for i in range(100)]  # fmt: skip
        return httpx.Response(200, json={"totalFound": 250, "content": content})

    async with make_fetcher(handler) as f:
        result = await smartrecruiters.fetch(
            f, Company(id=1, name="A", ats="smartrecruiters", slug="A")
        )
    assert offsets == ["0", "100", "200"]
    assert len(result.jobs) == 300


async def test_smartrecruiters_zero_total_is_confirmed_empty():
    def handler(request):
        return httpx.Response(200, json={"totalFound": 0, "content": []})

    async with make_fetcher(handler) as f:
        result = await smartrecruiters.fetch(
            f, Company(id=1, name="A", ats="smartrecruiters", slug="A")
        )
    assert result.confirmed_empty
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q` → FAIL (`cannot import name 'smartrecruiters'`).

- [ ] **Step 4: Implement** — `scraper/adapters/smartrecruiters.py`:

```python
from typing import Any

from scraper.adapters.base import get_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "smartrecruiters"
PAGE = 100
MAX_PAGES = 5
_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def list_url(slug: str, offset: int) -> str:
    return (
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        f"?q=intern&limit={PAGE}&offset={offset}"
    )


def detail_url(slug: str, posting_id: str) -> str:
    return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"


def _description(detail: dict[str, Any]) -> str:
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    parts = (html_to_text((sections.get(k) or {}).get("text") or "") for k in _SECTIONS)
    return "\n".join(p for p in parts if p)


def _work_mode(loc: dict[str, Any]) -> str | None:
    if loc.get("remote"):
        return "remote"
    return "hybrid" if loc.get("hybrid") else None


def _record(slug: str, item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    loc = item.get("location") or {}
    country = (loc.get("country") or "").upper() or None
    raw_loc = loc.get("fullLocation") or ", ".join(
        p for p in (loc.get("city"), loc.get("region"), country) if p
    )
    pid = str(item.get("id") or "")
    return {
        "source": SOURCE,
        "source_job_id": pid,
        "title": item.get("name") or "",
        "url": detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{slug}/{pid}",
        "location_raw": raw_loc,
        "description_text": _description(detail),
        "source_posted_at": item.get("releasedDate"),
        "work_mode_hint": _work_mode(loc),
        "country_hint": country,
        "employment_type_hint": (item.get("typeOfEmployment") or {}).get("label"),
    }


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    items: list[dict[str, Any]] = []
    total = 0
    for page_no in range(MAX_PAGES):
        page = await fetcher.json("GET", list_url(company.slug, page_no * PAGE))
        if not isinstance(page, dict) or not isinstance(page.get("content"), list):
            raise FetchError("unexpected SmartRecruiters payload")
        if page_no == 0:
            total = int(page.get("totalFound") or 0)
        items.extend(page["content"])
        if not page["content"] or len(items) >= total:
            break

    def hint(i: dict[str, Any]) -> str | None:
        return (i.get("typeOfEmployment") or {}).get("label")

    want = {
        str(i["id"]): detail_url(company.slug, str(i["id"]))
        for i in items
        if i.get("id") and wanted(i.get("name") or "", hint(i))
    }
    details = await get_details(fetcher, want)
    records = [
        _record(company.slug, i, details.get(str(i.get("id")), {}))
        for i in items
        if str(i.get("id")) not in want or str(i["id"]) in details
    ]
    result = validate(records)
    result.confirmed_empty = not items and total == 0
    return result
```

Register: add `smartrecruiters` to the import and `"smartrecruiters": smartrecruiters.fetch,` to `ADAPTERS`.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q` → PASS.

- [ ] **Step 6: Live check**

Run: `uv run python -m scraper run --dry-run --company ServiceNow --ats smartrecruiters`
Expected: `✓ smartrecruiters/ServiceNow: N postings…` with no `✗`. Record in the ledger.

- [ ] **Step 7: Full suite + commit**

Run the full suite + ruff (as in Task 3 Step 7) → PASS.

```bash
git add scraper && git commit -m "feat: SmartRecruiters adapter"
```

---

### Task 5: Workday adapter

**Files:**
- Create: `scraper/adapters/workday.py`, `scraper/tests/fixtures/workday_list.json`, `scraper/tests/fixtures/workday_detail.json`
- Modify: `scraper/adapters/__init__.py`, `scraper/tests/test_adapters_new.py`

**Interfaces:**
- Consumes: `Company.workday_host`, `Company.workday_site` (Task 1).
- Produces: `workday.fetch`; `workday.clean_location(text: str) -> str`; `ADAPTERS["workday"]`.

Workday facts (verified live against NVIDIA): list is `POST https://{host}/wday/cxs/{tenant}/{site}/jobs` with `{"appliedFacets":{}, "limit":20, "offset":N, "searchText":"intern"}`; `limit` > 20 returns HTTP 400; `total` is reliable on page 0 only; items carry `title`, `externalPath` (starts with `/job/`), `locationsText` (may be "2 Locations"), `bulletFields[0]` (requisition id). Detail is `GET https://{host}/wday/cxs/{tenant}/{site}{externalPath}` → `jobPostingInfo` with `jobDescription` (HTML), `location` ("US, CA, Santa Clara"), `additionalLocations` (list of strings), `externalUrl`. `tenant` is the first label of the host.

- [ ] **Step 1: Fixtures**

`workday_list.json`:

```json
{"total": 3, "jobPostings": [
  {"title": "Software Engineer Intern - Fall 2026", "externalPath": "/job/US-CA-Santa-Clara/Software-Engineer-Intern_JR1",
   "locationsText": "2 Locations", "postedOn": "Posted 3 Days Ago", "bulletFields": ["JR1"]},
  {"title": "Director, International Tax Planning", "externalPath": "/job/US-CA-Santa-Clara/Director_JR2",
   "locationsText": "US, CA, Santa Clara", "postedOn": "Posted 9 Days Ago", "bulletFields": ["JR2"]},
  {"title": "Data Science Intern", "externalPath": "/job/CA-ON-Toronto/Data-Science-Intern_JR3",
   "locationsText": "CA, ON, Toronto", "postedOn": "Posted 30+ Days Ago", "bulletFields": ["JR3"]}
]}
```

`workday_detail.json` (served for JR1):

```json
{"jobPostingInfo": {"jobDescription": "<p>Build GPUs.</p><p>The hourly rate is US$45 per hour.</p>",
  "location": "US, CA, Santa Clara", "additionalLocations": ["CA, ON, Toronto"],
  "externalUrl": "https://acme.wd5.myworkdayjobs.com/Site/job/US-CA-Santa-Clara/Software-Engineer-Intern_JR1"}}
```

- [ ] **Step 2: Write the failing tests** — append to `test_adapters_new.py`:

```python
from scraper.adapters import workday
from scraper.normalize.location import parse_location


def wd_company(**kw):
    base = dict(
        id=1, name="Acme", ats="workday", slug="acme/Site",
        workday_host="acme.wd5.myworkdayjobs.com", workday_site="Site",
    )  # fmt: skip
    return Company(**(base | kw))


@pytest.mark.parametrize(
    ("raw", "expected_country", "expected_region"),
    [
        ("US, CA, Santa Clara", "US", "CA"),  # CA here is California
        ("CA, ON, Toronto", "CA", "ON"),
        ("CA, BC, Vancouver", "CA", "BC"),
    ],
)
def test_workday_locations_parse_to_the_right_country(raw, expected_country, expected_region):
    parsed = parse_location(workday.clean_location(raw))
    assert parsed.country == expected_country
    assert parsed.locations[0].region == expected_region


def test_clean_location_leaves_other_shapes_alone():
    assert workday.clean_location("Toronto, ON, Canada") == "Toronto, ON, Canada"
    assert workday.clean_location("Remote") == "Remote"


async def test_workday_fetch():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["searchText"] == "intern" and body["limit"] == 20
            return httpx.Response(200, json=load("workday_list.json"))
        if request.url.path.endswith("JR1"):
            return httpx.Response(200, json=load("workday_detail.json"))
        return httpx.Response(404)  # JR3's detail vanished

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["workday"](f, wd_company())

    assert ("POST", "/wday/cxs/acme/Site/jobs") in seen
    assert ("GET", "/wday/cxs/acme/Site/job/US-CA-Santa-Clara/Director_JR2") not in seen
    assert [j.source_job_id for j in result.jobs] == ["JR1", "JR2"]  # JR3 dropped this poll
    job = result.jobs[0]
    assert job.url.endswith("Software-Engineer-Intern_JR1")
    assert job.location_raw == "Santa Clara, CA, US | Toronto, ON, CA"  # not "2 Locations"
    assert job.description_text == "Build GPUs.\nThe hourly rate is US$45 per hour."
    assert job.source_posted_at is None
    assert not result.confirmed_empty


async def test_workday_pages_by_20_up_to_total():
    offsets = []

    def handler(request):
        body = json.loads(request.content)
        offsets.append(body["offset"])
        n = body["offset"]
        posts = [
            {"title": "Account Executive", "externalPath": f"/job/x/y_{n + i}",
             "bulletFields": [f"R{n + i}"], "locationsText": "US"}
            for i in range(20)
        ]  # fmt: skip
        return httpx.Response(200, json={"total": 45 if n == 0 else 0, "jobPostings": posts})

    async with make_fetcher(handler) as f:
        result = await workday.fetch(f, wd_company())
    assert offsets == [0, 20, 40]
    assert len(result.jobs) == 60


async def test_workday_zero_total_is_confirmed_empty():
    def handler(request):
        return httpx.Response(200, json={"total": 0, "jobPostings": []})

    async with make_fetcher(handler) as f:
        result = await workday.fetch(f, wd_company())
    assert result.confirmed_empty


async def test_workday_needs_host_and_site():
    async with make_fetcher(lambda r: httpx.Response(200, json={})) as f:
        with pytest.raises(FetchError, match="workday_host"):
            await workday.fetch(f, wd_company(workday_host=None))
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q` → FAIL (`cannot import name 'workday'`).

- [ ] **Step 4: Implement** — `scraper/adapters/workday.py`:

```python
import re
from typing import Any

from scraper.adapters.base import get_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "workday"
PAGE = 20  # Workday rejects a larger limit with HTTP 400
MAX_PAGES = 15

# Workday writes "US, CA, Santa Clara" = country, region, city (CA is California here).
_COUNTRY_REGION_CITY = re.compile(r"^([A-Z]{2}), ([A-Z]{2,3}), (.+)$")


def clean_location(text: str) -> str:
    text = text.strip()
    m = _COUNTRY_REGION_CITY.match(text)
    if not m:
        return text
    country, region, city = m.groups()
    return f"{city}, {region}, {country}"


def _base(company: Company) -> tuple[str, str, str]:
    if not company.workday_host or not company.workday_site:
        raise FetchError("workday company is missing workday_host/workday_site")
    host, site = company.workday_host, company.workday_site
    return host, host.split(".")[0], site


def _record(host: str, item: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    path = item.get("externalPath") or ""
    bullets = item.get("bulletFields") or []
    locations = [info.get("location") or item.get("locationsText") or ""]
    locations += info.get("additionalLocations") or []
    return {
        "source": SOURCE,
        "source_job_id": str(bullets[0]) if bullets else path,
        "title": item.get("title") or "",
        "url": info.get("externalUrl") or f"https://{host}{path}",
        "location_raw": " | ".join(clean_location(x) for x in locations if x),
        "description_text": html_to_text(info.get("jobDescription") or ""),
        "source_posted_at": None,
    }


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host, tenant, site = _base(company)
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    items: list[dict[str, Any]] = []
    total = 0
    for page_no in range(MAX_PAGES):
        body = {"appliedFacets": {}, "limit": PAGE, "offset": page_no * PAGE, "searchText": "intern"}
        data = await fetcher.json("POST", f"{api}/jobs", json=body)
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            raise FetchError("unexpected Workday payload")
        if page_no == 0:
            total = int(data.get("total") or 0)  # later pages report 0
        items.extend(data["jobPostings"])
        if not data["jobPostings"] or len(items) >= total:
            break

    def key(i: dict[str, Any]) -> str:
        bullets = i.get("bulletFields") or []
        return str(bullets[0]) if bullets else (i.get("externalPath") or "")

    want = {
        key(i): f"{api}{i['externalPath']}"
        for i in items
        if i.get("externalPath") and wanted(i.get("title") or "")
    }
    details = await get_details(fetcher, want)
    records = [
        _record(host, i, (details.get(key(i)) or {}).get("jobPostingInfo") or {})
        for i in items
        if key(i) not in want or key(i) in details
    ]
    result = validate(records)
    result.confirmed_empty = not items and total == 0
    return result
```

Register `workday` in `scraper/adapters/__init__.py`.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest scraper/tests/test_adapters_new.py -q` → PASS. If a `test_workday_locations_parse_to_the_right_country` case fails, the cause is `parse_location` mis-reading the cleaned "City, REGION, CC" string: fix `scraper/normalize/location.py` (add a failing `test_location.py` case first) rather than weakening the test.

- [ ] **Step 6: Live check** — add NVIDIA to the seed later (Task 9); for now:

```bash
uv run python - <<'EOF'
import asyncio
from scraper.adapters import workday
from scraper.http import Fetcher
from scraper.models import Company
from scraper.pipeline import process

async def main():
    c = Company(id=1, name="NVIDIA", ats="workday", slug="nvidia/NVIDIAExternalCareerSite",
                workday_host="nvidia.wd5.myworkdayjobs.com", workday_site="NVIDIAExternalCareerSite")
    async with Fetcher() as f:
        out = process(c, await workday.fetch(f, c))
    print(out.ok, len(out.seen_ids), len(out.jobs), out.error)
    for j in out.jobs[:5]:
        print(j.location.country, j.raw.title, "|", j.raw.location_raw, "|", j.term)
asyncio.run(main())
EOF
```
Expected: `True <N> <M> None`, with US/CA countries on the printed jobs and real city names. Record the output summary in the ledger.

- [ ] **Step 7: Full suite + commit**

Run the full suite + ruff → PASS.

```bash
git add scraper && git commit -m "feat: Workday adapter"
```

---

### Task 6: Simplify discovery

**Files:**
- Create: `scraper/discovery.py`, `scraper/tests/test_discovery.py`
- Modify: `scraper/db.py`, `scraper/__main__.py`

**Interfaces:**
- Consumes: `Fetcher.json(method, url, headers=...)`.
- Produces: `parse_board_url(url: str) -> dict | None` returning `{"ats", "slug", "workday_host"?, "workday_site"?}`; `extract_boards(listings: list[dict]) -> list[dict]` (seed-shaped dicts with `name`, deduped by `(ats, slug)`, active+visible listings only); `async discover(fetcher, conn, repos=SIMPLIFY_REPOS) -> int`; `db.discover_companies(conn, seeds) -> int` (inserts only new `(ats, slug)`, tier `warm`, `discovered_from='simplify'`); `db.get_state_sha(conn, source) -> str | None`; `db.set_state_sha(conn, source, sha)`; CLI `python -m scraper discover`.

- [ ] **Step 1: Write the failing tests** — `scraper/tests/test_discovery.py`:

```python
import httpx
import pytest

from scraper import db, discovery
from scraper.http import Fetcher


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://job-boards.greenhouse.io/Stripe/jobs/123", {"ats": "greenhouse", "slug": "stripe"}),
        ("https://boards.greenhouse.io/airbnb/jobs/9?gh_src=x", {"ats": "greenhouse", "slug": "airbnb"}),
        ("https://jobs.lever.co/Palantir/abc-def", {"ats": "lever", "slug": "palantir"}),
        ("https://jobs.ashbyhq.com/openai/uuid", {"ats": "ashby", "slug": "openai"}),
        ("https://jobs.smartrecruiters.com/ServiceNow/744-title", {"ats": "smartrecruiters", "slug": "ServiceNow"}),
        ("https://apply.workable.com/huggingface/j/ABC123/", {"ats": "workable", "slug": "huggingface"}),
        (
            "https://thomsonreuters.wd5.myworkdayjobs.com/en-US/External_Career_Site/job/Toronto/X_JR1",
            {"ats": "workday", "slug": "thomsonreuters/External_Career_Site",
             "workday_host": "thomsonreuters.wd5.myworkdayjobs.com",
             "workday_site": "External_Career_Site"},
        ),
        (
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA/Y_JR2?q=1",
            {"ats": "workday", "slug": "nvidia/NVIDIAExternalCareerSite",
             "workday_host": "nvidia.wd5.myworkdayjobs.com",
             "workday_site": "NVIDIAExternalCareerSite"},
        ),
    ],
)  # fmt: skip
def test_parse_board_url(url, expected):
    assert discovery.parse_board_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tesla.com/careers/search/job/123",
        "https://boards.greenhouse.io/embed/job_app?for=acme&token=1",
        "https://apply.workable.com/",
        "https://acme.wd5.myworkdayjobs.com/",
        "not a url",
        "",
    ],
)
def test_parse_board_url_ignores_junk(url):
    assert discovery.parse_board_url(url) is None


def listing(url, name="Acme", active=True, visible=True):
    return {"company_name": name, "url": url, "active": active, "is_visible": visible}


def test_extract_boards_dedupes_and_skips_inactive():
    boards = discovery.extract_boards([
        listing("https://jobs.lever.co/acme/1"),
        listing("https://jobs.lever.co/acme/2", name="Acme Inc"),
        listing("https://jobs.lever.co/old/3", active=False),
        listing("https://jobs.lever.co/hidden/4", visible=False),
        listing("https://example.com/x"),
    ])  # fmt: skip
    assert boards == [{"name": "Acme", "ats": "lever", "slug": "acme"}]


def test_discover_companies_inserts_only_new_as_warm(conn):
    db.upsert_companies(conn, [{"name": "Acme", "ats": "lever", "slug": "acme", "hot": True}])
    n = db.discover_companies(
        conn,
        [{"name": "Acme", "ats": "lever", "slug": "acme"},
         {"name": "Beta", "ats": "ashby", "slug": "beta"}],
    )  # fmt: skip
    assert n == 1
    rows = {r["slug"]: r for r in conn.execute("select * from companies")}
    assert rows["acme"]["tier"] == "hot" and rows["acme"]["discovered_from"] is None
    assert rows["beta"]["tier"] == "warm" and rows["beta"]["discovered_from"] == "simplify"


def test_state_sha_round_trip(conn):
    assert db.get_state_sha(conn, "simplify:x") is None
    db.set_state_sha(conn, "simplify:x", "abc")
    db.set_state_sha(conn, "simplify:x", "def")
    assert db.get_state_sha(conn, "simplify:x") == "def"


REPO = "SimplifyJobs/Summer2027-Internships"


def routed(sha="s1", listings=None, sha_status=200):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.github.com":
            return httpx.Response(sha_status, json={"sha": sha})
        return httpx.Response(200, json=listings or [])

    fetcher = Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)
    return fetcher, calls


async def test_discover_downloads_only_when_sha_changed(conn):
    boards = [listing("https://jobs.lever.co/acme/1")]
    f, calls = routed(sha="s1", listings=boards)
    async with f:
        assert await discovery.discover(f, conn, [REPO]) == 1
    assert calls == ["api.github.com", "raw.githubusercontent.com"]

    f, calls = routed(sha="s1", listings=boards)
    async with f:
        assert await discovery.discover(f, conn, [REPO]) == 0
    assert calls == ["api.github.com"]  # unchanged: no download
    assert db.get_state_sha(conn, f"simplify:{REPO}") == "s1"


async def test_discover_survives_github_failure_and_keeps_old_sha(conn):
    db.set_state_sha(conn, f"simplify:{REPO}", "old")
    f, calls = routed(sha_status=403)
    async with f:
        assert await discovery.discover(f, conn, [REPO]) == 0
    assert calls == ["api.github.com"]
    assert db.get_state_sha(conn, f"simplify:{REPO}") == "old"
```

- [ ] **Step 2: Run to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest scraper/tests/test_discovery.py -q` → FAIL (`cannot import name 'discovery'`).

- [ ] **Step 3: Implement DB helpers** — append to `scraper/db.py`:

```python
def discover_companies(conn: psycopg.Connection, seeds: list[dict[str, Any]]) -> int:
    """Insert boards we don't know yet as warm companies. Never touches existing rows."""
    added = 0
    with conn.transaction():
        for s in seeds:
            cur = conn.execute(
                """insert into companies (name, ats, slug, workday_host, workday_site,
                                          tier, discovered_from)
                   values (%(name)s, %(ats)s, %(slug)s, %(workday_host)s, %(workday_site)s,
                           'warm', 'simplify')
                   on conflict (ats, slug) do nothing""",
                {
                    "name": s["name"],
                    "ats": s["ats"],
                    "slug": s["slug"],
                    "workday_host": s.get("workday_host"),
                    "workday_site": s.get("workday_site"),
                },
            )
            added += cur.rowcount
    return added


def get_state_sha(conn: psycopg.Connection, source: str) -> str | None:
    row = conn.execute(
        "select last_commit_sha from source_state where source = %s", (source,)
    ).fetchone()
    return row["last_commit_sha"] if row else None


def set_state_sha(conn: psycopg.Connection, source: str, sha: str) -> None:
    conn.execute(
        """insert into source_state (source, last_commit_sha) values (%s, %s)
           on conflict (source) do update set last_commit_sha = excluded.last_commit_sha""",
        (source, sha),
    )
```

- [ ] **Step 4: Implement discovery** — `scraper/discovery.py`:

```python
import os
import re
from typing import Any

import psycopg

from scraper import db
from scraper.http import Fetcher, FetchError

SIMPLIFY_REPOS = ["SimplifyJobs/Summer2027-Internships"]
BRANCH = "dev"

_SEG = r"([^/?#]+)"
_WORKDAY = re.compile(
    r"^https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?" + _SEG, re.I
)
_SIMPLE = [
    ("greenhouse", re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/" + _SEG, re.I), True),
    ("lever", re.compile(r"^https?://jobs\.lever\.co/" + _SEG, re.I), True),
    ("ashby", re.compile(r"^https?://jobs\.ashbyhq\.com/" + _SEG, re.I), True),
    ("smartrecruiters", re.compile(r"^https?://jobs\.smartrecruiters\.com/" + _SEG, re.I), False),
    ("workable", re.compile(r"^https?://apply\.workable\.com/" + _SEG, re.I), True),
]
_NOT_A_BOARD = {"embed", "oneclick-ui", "j", "login", "api"}


def parse_board_url(url: str) -> dict[str, str] | None:
    """A job/board URL on a supported ATS -> the board we can poll directly, else None."""
    for ats, pattern, lower in _SIMPLE:
        m = pattern.match(url or "")
        if m and m.group(1).lower() not in _NOT_A_BOARD:
            slug = m.group(1)
            return {"ats": ats, "slug": slug.lower() if lower else slug}
    m = _WORKDAY.match(url or "")
    if m and m.group(3).lower() not in _NOT_A_BOARD:
        tenant, wd, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
        return {
            "ats": "workday",
            "slug": f"{tenant}/{site}",
            "workday_host": f"{tenant}.{wd}.myworkdayjobs.com",
            "workday_site": site,
        }
    return None


def extract_boards(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boards: dict[tuple[str, str], dict[str, Any]] = {}
    for item in listings:
        if not (item.get("active") and item.get("is_visible", True)):
            continue
        board = parse_board_url(item.get("url") or "")
        name = (item.get("company_name") or "").strip()
        if board and name:
            boards.setdefault((board["ats"], board["slug"]), {"name": name, **board})
    return list(boards.values())


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def discover(
    fetcher: Fetcher, conn: psycopg.Connection, repos: list[str] = SIMPLIFY_REPOS
) -> int:
    """Add boards found in the Simplify lists. Downloads a list only if its repo has a new commit."""
    added = 0
    for repo in repos:
        state = f"simplify:{repo}"
        try:
            head = await fetcher.json(
                "GET",
                f"https://api.github.com/repos/{repo}/commits/{BRANCH}",
                headers=_headers(),
            )
            sha = head["sha"]
            if sha == db.get_state_sha(conn, state):
                continue
            listings = await fetcher.json(
                "GET",
                f"https://raw.githubusercontent.com/{repo}/{BRANCH}/.github/scripts/listings.json",
            )
        except (FetchError, KeyError, TypeError) as e:
            print(f"discovery skipped for {repo}: {type(e).__name__}: {e}")
            continue
        if not isinstance(listings, list):
            print(f"discovery skipped for {repo}: unexpected listings payload")
            continue
        added += db.discover_companies(conn, extract_boards(listings))
        db.set_state_sha(conn, state, sha)  # only after a fully successful import
    return added
```

`Fetcher.json` already forwards `**kwargs` (including `headers`) to `client.request`, so no HTTP changes are needed.

- [ ] **Step 5: CLI** — in `scraper/__main__.py` add `from scraper.discovery import discover`, then:

```python
def cmd_discover(_: argparse.Namespace) -> int:
    async def go(conn: psycopg.Connection) -> int:
        async with Fetcher() as fetcher:
            return await discover(fetcher, conn)

    print(f"discovered {asyncio.run(go(_connect()))} new companies")
    return 0
```

Register `sub.add_parser("discover", help="add companies found in the Simplify lists")` and `"discover": cmd_discover` in `handlers`.

- [ ] **Step 6: Run to verify they pass**

Run the Step 2 command → PASS. If a `parse_board_url` case fails, fix the regex, not the test.

- [ ] **Step 7: Full suite + commit**

Run the full suite + ruff → PASS.

```bash
git add scraper && git commit -m "feat: discover companies from the Simplify lists"
```

---

### Task 7: Tiering and the sweep selector

**Files:**
- Modify: `scraper/db.py`, `scraper/__main__.py`
- Test: `scraper/tests/test_tiering.py` (create)

**Interfaces:**
- Produces: `db.retier(conn, now) -> None` (never touches `inactive`); ingest promotes `warm|cold → hot` when a poll found internships; `db.get_sweep_companies(conn, *, ats, now, limit=500) -> list[Company]`; CLI `run --sweep`.

- [ ] **Step 1: Write the failing tests** — `scraper/tests/test_tiering.py`:

```python
from datetime import UTC, datetime, timedelta

from scraper import db
from scraper.tests.test_db_ingest import company, outcome, raw

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def add(conn, slug, *, hot=False, intern_days=None, created_days=0, polled_hours=None, tier=None):
    db.upsert_companies(conn, [{"name": slug, "ats": "lever", "slug": slug, "hot": hot}])
    conn.execute(
        """update companies set created_at = %s, last_intern_seen_at = %s, last_polled_at = %s,
             tier = coalesce(%s, tier) where slug = %s""",
        (
            NOW - timedelta(days=created_days),
            None if intern_days is None else NOW - timedelta(days=intern_days),
            None if polled_hours is None else NOW - timedelta(hours=polled_hours),
            tier,
            slug,
        ),
    )  # fmt: skip


def tiers(conn):
    return {r["slug"]: r["tier"] for r in conn.execute("select slug, tier from companies")}


def test_retier_rules(conn):
    add(conn, "curated", hot=True, intern_days=200)
    add(conn, "recent", intern_days=10)
    add(conn, "middling", intern_days=60, tier="hot")
    add(conn, "stale", intern_days=120)
    add(conn, "never-old", created_days=100)
    add(conn, "never-new", created_days=5, tier="cold")
    add(conn, "dead", intern_days=1, tier="inactive")
    db.retier(conn, NOW)
    assert tiers(conn) == {
        "curated": "hot", "recent": "hot", "middling": "warm", "stale": "cold",
        "never-old": "cold", "never-new": "warm", "dead": "inactive",
    }  # fmt: skip


def test_ingest_promotes_to_hot_when_interns_found(conn):
    c = company(conn, "promo")
    conn.execute("update companies set tier = 'cold' where id = %s", (c.id,))
    db.ingest(conn, outcome(c, [raw("1")]), NOW)
    assert tiers(conn)["promo"] == "hot"


def test_ingest_without_interns_keeps_tier(conn):
    c = company(conn, "quiet")
    conn.execute("update companies set tier = 'cold' where id = %s", (c.id,))
    db.ingest(conn, outcome(c, [raw("1", title="Account Executive")]), NOW)
    assert tiers(conn)["quiet"] == "cold"


def test_sweep_selection(conn):
    add(conn, "hot-one", hot=True)
    add(conn, "warm-never", tier="warm")
    add(conn, "warm-recent", tier="warm", polled_hours=1)
    add(conn, "cold-recent", tier="cold", polled_hours=2)
    add(conn, "cold-due", tier="cold", polled_hours=7)
    add(conn, "dead", tier="inactive")
    got = [c.slug for c in db.get_sweep_companies(conn, ats=["lever"], now=NOW)]
    # least recently polled first (never polled first); hot/inactive/not-due-cold excluded
    assert got == ["warm-never", "cold-due", "warm-recent"]
    assert [c.slug for c in db.get_sweep_companies(conn, ats=["lever"], now=NOW, limit=1)] == [
        "warm-never"
    ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest scraper/tests/test_tiering.py -q` → FAIL (`retier`/`get_sweep_companies` missing).

- [ ] **Step 3: Implement** — in `scraper/db.py` append:

```python
HOT_WINDOW = "30 days"
COLD_AFTER = "90 days"
COLD_REPOLL = "6 hours"


def retier(conn: psycopg.Connection, now: datetime) -> None:
    """hot = curated or an intern posting in the last 30 days; cold = none in 90; else warm."""
    conn.execute(
        """update companies set tier = case
             when curated_hot or last_intern_seen_at >= %(now)s - %(hot)s::interval then 'hot'
             when coalesce(last_intern_seen_at, created_at) < %(now)s - %(cold)s::interval
               then 'cold'
             else 'warm' end
           where tier <> 'inactive'""",
        {"now": now, "hot": HOT_WINDOW, "cold": COLD_AFTER},
    )


def get_sweep_companies(
    conn: psycopg.Connection, *, ats: list[str], now: datetime, limit: int = 500
) -> list[Company]:
    rows = conn.execute(
        """select id, name, ats, slug, job_ids_hash, workday_host, workday_site from companies
           where ats = any(%(ats)s) and tier in ('warm', 'cold')
             and (tier = 'warm' or last_polled_at is null
                  or last_polled_at < %(now)s - %(repoll)s::interval)
           order by last_polled_at nulls first, id
           limit %(limit)s""",
        {"ats": ats, "now": now, "repoll": COLD_REPOLL, "limit": limit},
    ).fetchall()
    return [Company(**r) for r in rows]
```

In `ingest`'s final `update companies` statement add (after `last_intern_seen_at` assignment):

```sql
                 tier = case when %(interns)s and tier in ('warm', 'cold') then 'hot'
                             else tier end
```
(remember the comma after the preceding `end`).

`scraper/__main__.py`: add `run.add_argument("--sweep", action="store_true", help="poll the least-recently-polled warm/cold companies")`; in `cmd_run` replace the `db.get_companies(...)` call with:

```python
    if args.sweep:
        companies = db.get_sweep_companies(
            conn, ats=[args.ats] if args.ats else list(ADAPTERS), now=started, limit=min(args.limit, 500)
        )
    else:
        companies = db.get_companies(
            conn,
            ats=[args.ats] if args.ats else list(ADAPTERS),
            tier=args.tier,
            slug=args.company,
            limit=args.limit,
        )
```
and the `record_run` workflow name to `"scrape-sweep" if args.sweep else f"scrape-{args.tier or 'manual'}"`.

- [ ] **Step 4: Run to verify they pass**

Run the Step 2 command → PASS; then the full suite + ruff. (Existing ingest tests must still pass: promotion only changes warm/cold rows, and `company()` helper creates hot rows.)

- [ ] **Step 5: Commit**

```bash
git add scraper && git commit -m "feat: activity tiers and the sweep selector"
```

---

### Task 8: Maintenance, STATS.md and workflows

**Files:**
- Create: `scraper/stats.py`, `scraper/tests/test_stats.py`, `.github/workflows/scrape-sweep.yml`, `.github/workflows/maintenance.yml`
- Modify: `scraper/db.py`, `scraper/__main__.py`

**Interfaces:**
- Produces: `db.prune(conn, now) -> int` (deletes `scrape_runs` older than 30 days, returns rows deleted); `db.stats(conn, now) -> dict`; `stats.render(stats: dict, now: datetime) -> str`; CLI `python -m scraper maintenance [--stats-path STATS.md]`.

- [ ] **Step 1: Write the failing tests** — `scraper/tests/test_stats.py`:

```python
from datetime import UTC, datetime, timedelta

from scraper import db, stats
from scraper.tests.test_db_ingest import company, outcome, raw

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_prune_drops_old_runs_only(conn):
    for age in (45, 5):
        db.record_run(
            conn, workflow="w", source="ats", started_at=NOW - timedelta(days=age),
            finished_at=NOW - timedelta(days=age), companies_polled=1, jobs_seen=0,
            jobs_new=0, jobs_closed=0, errors=0, error_samples=[],
        )  # fmt: skip
    assert db.prune(conn, NOW) == 1
    assert conn.execute("select count(*) as n from scrape_runs").fetchone()["n"] == 1


def test_stats_and_render(conn):
    c = company(conn, "acme")
    db.ingest(conn, outcome(c, [raw("1")]), NOW)
    data = db.stats(conn, NOW)
    assert data["companies_by_tier"]["hot"] == 1
    assert data["companies_by_ats"]["greenhouse"] == 1
    assert data["open_jobs_by_country"]["CA"] == 1
    text = stats.render(data, NOW)
    assert text.startswith("# Intern Radar stats")
    assert "2026-10-07" in text and "| hot | 1 |" in text and "| CA | 1 |" in text
    assert "\n\n\n" not in text and text.endswith("\n")
```

- [ ] **Step 2: Run to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest scraper/tests/test_stats.py -q` → FAIL.

- [ ] **Step 3: Implement** — append to `scraper/db.py`:

```python
RUN_RETENTION = "30 days"


def prune(conn: psycopg.Connection, now: datetime) -> int:
    cur = conn.execute(
        "delete from scrape_runs where finished_at < %s - %s::interval", (now, RUN_RETENTION)
    )
    return cur.rowcount


def _counts(conn: psycopg.Connection, sql: str) -> dict[str, int]:
    return {r["k"]: r["n"] for r in conn.execute(sql).fetchall()}


def stats(conn: psycopg.Connection, now: datetime) -> dict[str, Any]:
    last = conn.execute(
        "select workflow, finished_at from scrape_runs order by finished_at desc limit 1"
    ).fetchone()
    return {
        "companies_by_tier": _counts(
            conn, "select tier as k, count(*) as n from companies group by 1 order by 1"
        ),
        "companies_by_ats": _counts(
            conn, "select ats as k, count(*) as n from companies group by 1 order by 1"
        ),
        "open_jobs_by_country": _counts(
            conn,
            "select country as k, count(*) as n from jobs where status = 'open' group by 1 order by 1",
        ),
        "last_run": last,
    }
```

`scraper/stats.py`:

```python
from datetime import datetime
from typing import Any


def _table(title: str, rows: dict[str, int]) -> str:
    lines = [f"## {title}", "", "| | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows.items()]
    return "\n".join(lines)


def render(data: dict[str, Any], now: datetime) -> str:
    last = data["last_run"]
    last_line = (
        f"Last scrape: {last['workflow']} at {last['finished_at']:%Y-%m-%d %H:%M} UTC"
        if last
        else "Last scrape: none yet"
    )
    parts = [
        "# Intern Radar stats",
        f"Updated {now:%Y-%m-%d} (weekly by the maintenance workflow, which also keeps "
        "GitHub from disabling the schedules). " + last_line,
        _table("Companies by tier", data["companies_by_tier"]),
        _table("Companies by ATS", data["companies_by_ats"]),
        _table("Open internships by country", data["open_jobs_by_country"]),
    ]
    return "\n\n".join(parts) + "\n"
```

CLI — in `scraper/__main__.py`:

```python
from scraper import stats as stats_report


def cmd_maintenance(args: argparse.Namespace) -> int:
    conn = _connect()
    now = datetime.now(UTC)
    db.retier(conn, now)
    pruned = db.prune(conn, now)
    args.stats_path.write_text(stats_report.render(db.stats(conn, now), now))
    print(f"retiered, pruned {pruned} old runs, wrote {args.stats_path}")
    return 0
```
Register: `m = sub.add_parser("maintenance", help="re-tier, prune, write STATS.md")`, `m.add_argument("--stats-path", type=Path, default=Path("STATS.md"))`, and `"maintenance": cmd_maintenance` in `handlers`.

- [ ] **Step 4: Run to verify they pass**

Run the Step 2 command → PASS; full suite + ruff → PASS.

- [ ] **Step 5: Workflows**

`.github/workflows/scrape-sweep.yml`:

```yaml
name: scrape-sweep
on:
  schedule:
    - cron: "7,37 * * * *"
  workflow_dispatch:

concurrency:
  group: scrape-sweep
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  sweep:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen --no-dev
      - name: Discover new boards from Simplify
        run: uv run python -m scraper discover
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GITHUB_TOKEN: ${{ github.token }}
      - name: Sweep warm and cold companies
        run: uv run python -m scraper run --sweep
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

`.github/workflows/maintenance.yml`:

```yaml
name: maintenance
on:
  schedule:
    - cron: "0 8 * * 0"
  workflow_dispatch:

concurrency:
  group: maintenance
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  maintenance:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen --no-dev
      - run: uv run python -m scraper maintenance
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
      - name: Commit STATS.md (keeps scheduled workflows enabled)
        run: |
          git config user.name "baldeep06"
          git config user.email "92562237+baldeep06@users.noreply.github.com"
          git add STATS.md
          git commit -m "chore: weekly stats" || echo "nothing to commit"
          git push
```

- [ ] **Step 6: Validate workflow YAML and commit**

Run: `uv run python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('yaml ok')"` → `yaml ok`.

```bash
git add scraper .github && git commit -m "feat: sweep and maintenance workflows with STATS.md"
```

---

### Task 9: Curated seeds for the new ATSes

**Files:**
- Modify: `data/companies.seed.yml`, `scraper/tests/test_cli.py`

- [ ] **Step 1: Update the seed test** — in `test_seed_file_is_valid` change the set assertion to

```python
    assert {s["ats"] for s in seeds} <= {
        "greenhouse", "lever", "ashby", "workday", "smartrecruiters", "workable"
    }  # fmt: skip
```

- [ ] **Step 2: Add candidates** — append to `data/companies.seed.yml` (candidates; unverified entries are removed in Step 3):

```yaml
# Workday / SmartRecruiters / Workable. slug for workday is "tenant/site".
- {name: NVIDIA, ats: workday, slug: nvidia/NVIDIAExternalCareerSite, workday_host: nvidia.wd5.myworkdayjobs.com, workday_site: NVIDIAExternalCareerSite, domain: nvidia.com, hot: true}
- {name: Salesforce, ats: workday, slug: salesforce/External_Career_Site, workday_host: salesforce.wd12.myworkdayjobs.com, workday_site: External_Career_Site, domain: salesforce.com, hot: true}
- {name: Adobe, ats: workday, slug: adobe/external_experienced, workday_host: adobe.wd5.myworkdayjobs.com, workday_site: external_experienced, domain: adobe.com, hot: true}
- {name: Workday, ats: workday, slug: workday/Workday, workday_host: workday.wd5.myworkdayjobs.com, workday_site: Workday, domain: workday.com, hot: true}
- {name: Mastercard, ats: workday, slug: mastercard/CorporateCareers, workday_host: mastercard.wd1.myworkdayjobs.com, workday_site: CorporateCareers, domain: mastercard.com, hot: true}
- {name: Thomson Reuters, ats: workday, slug: thomsonreuters/External_Career_Site, workday_host: thomsonreuters.wd5.myworkdayjobs.com, workday_site: External_Career_Site, domain: thomsonreuters.com, hot: true}
- {name: RBC, ats: workday, slug: rbc/RBCGlobal, workday_host: rbc.wd3.myworkdayjobs.com, workday_site: RBCGlobal, domain: rbc.com, hot: true}
- {name: ServiceNow, ats: smartrecruiters, slug: ServiceNow, domain: servicenow.com, hot: true}
- {name: Hugging Face, ats: workable, slug: huggingface, domain: huggingface.co, hot: true}
```

- [ ] **Step 3: Verify against the live ATSes and prune**

Run: `uv run python -m scraper seed --verify`
Expected: the summary line `N/N boards OK. Failed: [...]`. For every failed new entry, look up the correct tenant/site from a real job URL (Simplify's `listings.json` has many: `curl -s https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json | grep -o 'https://[a-z0-9-]*\.wd[0-9]*\.myworkdayjobs\.com/[^/"]*/[^/"]*' | grep -i <company> | head`), fix it, and re-verify; remove entries that still fail (record each removal in the ledger, as in Phase 1). Do **not** keep unverified entries.

- [ ] **Step 4: Seed the database** (needs `DATABASE_URL` in the gitignored `.env`; never print it):

```bash
set -a && . ./.env && set +a && uv run python -m scraper seed && uv run python -m scraper discover && uv run python -m scraper maintenance --stats-path /tmp/STATS.preview.md
```
Expected: `upserted N companies`, `discovered M new companies` (hundreds to a few thousand), and a maintenance line. Do not commit the preview file.

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add data scraper && git commit -m "feat: curated workday, smartrecruiters and workable companies"
```

---

### Task 10: Live end-to-end, docs, final checks

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Live sweep, small** (writes to the real database; the same work the cron will do):

```bash
set -a && . ./.env && set +a && uv run python -m scraper run --sweep --limit 25 && uv run python -m scraper run --sweep --limit 25
```
Expected: the first prints `polled=25 … errors=<small>`; the second prints `new=0` for those same companies once they are no longer the least-recently-polled (re-polling must not create duplicates). Run `uv run python -m scraper run --tier hot --ats workday` and confirm `errors=0`. Record the numbers in the ledger.

- [ ] **Step 2: README** — replace the commands line with:

```
Commands: `python -m scraper migrate | seed [--verify] | discover | run [--tier hot | --sweep] [--ats X] [--dry-run] | maintenance`.
```
and add a short "Sources" paragraph: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable; Simplify lists for company discovery; tiers hot/warm/cold/inactive; workflows `scrape-hot` (5 min), `scrape-sweep` (30 min), `maintenance` (weekly, commits `STATS.md`).

- [ ] **Step 3: Whole-project verification**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest -q
uv run ruff check . && uv run ruff format --check .
git log --format='%an <%ae>%n%b' main..HEAD | sort | uniq -c
```
Expected: all tests pass; lint clean; the only author line is `baldeep06 <92562237+baldeep06@users.noreply.github.com>` and no `Co-Authored-By`/`Generated with` text.

- [ ] **Step 4: Commit**

```bash
git add README.md && git commit -m "docs: phase 3 sources, tiers and workflows"
```

---

## Self-Review

- **Spec coverage (§11 Phase 3):** Workday/SmartRecruiters/Workable adapters → Tasks 3–5; Simplify discovery → Task 6 (job-source half deferred, ruled above); tiering → Task 7; `scrape-sweep` → Tasks 7–8; maintenance/`STATS.md` keepalive → Task 8; curated companies → Task 9.
- **Placeholders:** none; Task 9 Step 3 is a live-verification loop with the exact command, not a deferred decision.
- **Type consistency:** `confirmed_empty` is defined on `FetchResult` and `CompanyOutcome` (Task 1) and set by Tasks 3–5; `wanted`/`get_details` (Task 2) are used by Tasks 3–5; `Company.workday_*` (Task 1) feed Task 5 and `get_sweep_companies` (Task 7) selects them; `db.discover_companies/get_state_sha/set_state_sha` (Task 6) are used by `discovery.discover`.
- **Review Focus coverage:** confirmed-empty closing (Task 1 tests), multi-location + California-vs-Canada (Task 5 tests), search-noise detail fetches (Tasks 3–5 tests assert the non-intern GET never happens), URL junk and dedupe (Task 6 tests), SHA unchanged/failure (Task 6 tests).

---

## Addendum (requested after plan approval): reposts must not be labelled fresh

**Evidence (live DB, 2026-10-07):** all 124 jobs were `fresh`; 95 had a source posted date >14 days before we first saw them and 23 were >350 days old. Two causes: (1) the first poll of any board imports its existing backlog, which the classifier calls `fresh`; (2) a repost with a new ATS id is only caught when title *and* the exact location set match a job we already stored. Discovery (Task 6) would multiply cause (1) across thousands of boards, so this runs **before** Task 9's live import.

**Design (rulings, see ledger):**
- New freshness value `existing` = open posting we are seeing for the first time but that was posted more than `FRESH_MAX_AGE = 3 days` ago, or that has no posted date and arrived on a company's first successful poll (baseline). It is never "new", never in the `fresh only` filter.
- Fuzzy repost matching against **closed** jobs of the same company, compatible country, within the 120-day window: first `desc_hash` (normalised description body, digits/seasons stripped, ≥300 chars), then `title_key` (sorted token set of the normalised title minus intern/co-op/stop words, ≥2 tokens). Open fuzzy matches are ignored — two openings with the same title in different cities are different postings; only an exact fingerprint attaches to an open job (unchanged).
- Terms both known and different (e.g. Summer 2026 vs Summer 2027) are a new cycle → `fresh`, even when a closed match exists.
- Web: `existing` shows an "Open since <date>" badge, never "New"; the freshness filter keeps excluding it.

### Task R1: Repost signals (migration, `title_key`, `desc_hash`)
**Files:** create `supabase/migrations/20261007120000_repost_signals.sql`, `scraper/signals.py`, `scraper/tests/test_signals.py`; modify `scraper/models.py` (`EnrichedJob.title_key/desc_hash: str | None = None`), `scraper/enrich/__init__.py`, `scraper/db.py` (`_job_fields`, `_FIELD_NAMES`), `scraper/pipeline.py` (`ENRICH_VERSION = 3`), `scraper/tests/test_db_schema.py`.
**Produces:** `signals.title_key(normalized_title) -> str | None`, `signals.desc_hash(text) -> str | None`; columns `jobs.title_key`, `jobs.desc_hash`; freshness check allows `existing`; existing `fresh` rows posted >3 days before first seen become `existing`.
Tests: title_key ignores intern/co-op words and order, needs ≥2 tokens; desc_hash ignores years/seasons/digits/punctuation, None under 300 chars; migration accepts `existing` and backfills.

### Task R2: Classifier and matcher
**Files:** modify `scraper/dedupe.py` (`FRESH_MAX_AGE`, `classify(..., baseline=False)`), `scraper/db.py` (`_ingest_job` match query, `ingest` computes `baseline`), tests in `scraper/tests/test_dedupe.py`, `scraper/tests/test_db_ingest.py`.
Tests: old posted date → `existing`; undated + baseline → `existing`; undated, not baseline → `fresh`; recent date → `fresh`; terms differ with a closed match → `fresh`; closed job + new id with changed title word order / changed location (same country) → `repost`; same title in another city while the first is open → separate `fresh`/`existing`, never attached; closed match in another country → not a repost; description-identical retitled posting → `repost`.

### Task R3: Website
**Files:** modify `web/lib/types.ts` (`Freshness` + `"existing"`), `web/lib/badges.ts` (`existing` → neutral "Open since …"), web tests.
Tests: badge for `existing` is not "New" even when first seen <24h ago; `?fresh` filter query excludes `existing`.
