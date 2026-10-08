# Phase 5 — Big-Tech Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect US/Canada tech internships from Amazon, Microsoft, Apple and Google, which run their own career sites instead of a standard job-board system.

**Architecture:** Each company is one `companies` row (`ats` = `amazon|microsoft|apple|google`, `slug` = the same word) and one adapter with the usual `async fetch(fetcher, company) -> FetchResult` contract, so tiering, ingest, dedupe, repost detection and the looping workflows apply unchanged. All four are search-based: they search "intern" and "co-op" restricted to US + Canada, page through results with a cap, set `confirmed_empty` only when the site answers "0 results", and mark detail-fetch failures as `pending_ids` (listed but unreadable, never "gone"). `Fetcher` gains `text()` (Google serves HTML) and header access (Apple needs a CSRF token).

**Tech Stack:** Python 3.12, httpx (MockTransport tests), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md` (§3 "Big tech custom (phase 5)", §11 Phase 5)

## Global Constraints

- Lint/test as before: `uv run ruff check . && uv run ruff format --check .`; `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres uv run pytest -q`. **Always `set -o pipefail` when gating a commit on a test run** (a piped `tail` once hid a failing test).
- Same politeness as every adapter: our `User-Agent`, per-host concurrency 5, 15 s timeout, retries via `Fetcher`. Small page caps (below) so a hot cycle stays cheap.
- Output is validated by `RawJob`; only US/CA jobs matter (the pipeline's `enrich` drops others); `source_job_id` must be unique per source.
- Commits authored only by baldeep06 `<92562237+baldeep06@users.noreply.github.com>`; **no** `Co-Authored-By` / "Generated with" lines. Work on branch `phase-5-bigtech`.
- No secrets are involved; these endpoints are public and unauthenticated (Apple's CSRF token is issued to anyone by its own API).

## Rulings made while planning

- **Meta is out of this phase.** `metacareers.com/graphql` rejects an unauthenticated request without rotating page tokens (`lsd`/`fb_dtsg`) and persisted-query ids that change with Meta's deploys. It would break silently and often. Revisit with a headless browser only if wanted. (Spec listed Meta; this is a recorded deviation.)
- **Google dates:** the results page embeds two timestamps per job whose meaning is not documented; `source_posted_at` stays `None` (like Workday) so a wrong guess can never mislabel fresh vs. already-open. `first_seen_at` is the freshness basis; a new company's first poll is baseline backlog.
- **Apple descriptions** are the search result's `jobSummary` only (no per-job detail call): enough for pay/visa phrases when present, and it avoids one request per posting. Visa/pay evidence may be thinner than for other sources.
- **Page caps** (per query): Amazon 5 pages × 100, Microsoft 20 pages × 10, Apple 10 pages × 20, Google 10 pages × 20. Searching both "intern" and "co-op"; results merged by id.

## Review Focus

- **Zero results vs error:** a 200 answer of "0 results" closes the last job after two polls; an HTTP error, a blocked/HTML-instead-of-JSON answer, or a changed page shape must raise (never close anything). (All adapter tasks)
- **Google page-shape change:** if the embedded data blob is missing or has a different shape the adapter raises `FetchError`, it does not return an empty board. (Task 5)
- **Apple CSRF:** token fetched per poll, never logged; a missing token header raises. (Task 4)
- **Multi-country postings:** Amazon/Microsoft/Apple list jobs outside US/CA when the filter is loose; only US/CA survive `enrich`, and country hints map 3-letter codes (`USA`, `CAN`) correctly. (Tasks 2–5)
- **Cost:** a hot cycle adds four companies × (2 queries × ≤ pages) requests; check live that this is a few seconds, not minutes. (Task 6)

## File Structure

- Modify `scraper/http.py` — `Fetcher.text()`, `Fetcher.json_with_headers()` (shared `_request`).
- Create `supabase/migrations/20261008000000_bigtech_ats.sql`; modify `scraper/tests/test_db_schema.py`.
- Create `scraper/adapters/{amazon,microsoft,apple,google}.py`; modify `scraper/adapters/__init__.py`.
- Tests: `scraper/tests/test_http.py` (additions), `scraper/tests/test_bigtech.py` (create); modify `data/companies.seed.yml`, `scraper/tests/test_cli.py` (allowed-ats set), `README.md`.

---

### Task 1: Fetcher text/headers + migration

**Files:** Modify `scraper/http.py`, `scraper/tests/test_http.py`, `scraper/tests/test_db_schema.py`; Create `supabase/migrations/20261008000000_bigtech_ats.sql`

**Interfaces:**
- Produces: `await fetcher.text(method, url, **kw) -> str`; `await fetcher.json_with_headers(method, url, **kw) -> tuple[Any, httpx.Headers]`. `json()` keeps its signature. DB accepts `ats in ('amazon','microsoft','apple','google')`.

- [ ] **Step 1: Write the failing tests** — append to `scraper/tests/test_http.py` (reuse its imports; add `import httpx` if missing):

```python
async def test_text_returns_the_body_and_retries_like_json():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, text="<html>ok</html>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with Fetcher(client=client, base_delay=0) as f:
        assert await f.text("GET", "https://x.test/p") == "<html>ok</html>"
    assert len(calls) == 2


async def test_json_with_headers_returns_both():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"a": 1}, headers={"x-token": "t0"})
        )
    )
    async with Fetcher(client=client, base_delay=0) as f:
        data, headers = await f.json_with_headers("GET", "https://x.test/j")
    assert data == {"a": 1} and headers["x-token"] == "t0"


async def test_text_raises_on_client_errors():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    async with Fetcher(client=client, base_delay=0) as f:
        with pytest.raises(FetchError) as exc:
            await f.text("GET", "https://x.test/missing")
    assert exc.value.status == 404
```

and to `scraper/tests/test_db_schema.py`:

```python
def test_bigtech_ats_values_are_accepted_and_junk_is_not(conn):
    for ats in ("amazon", "microsoft", "apple", "google"):
        conn.execute("insert into companies (name, ats, slug) values (%s, %s, %s)", (ats, ats, ats))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into companies (name, ats, slug) values ('x','taleo','x')")
```
and extend the migration-name list assertion in `test_migrate_is_idempotent` with `"20261008000000_bigtech_ats.sql"` (after the existing entries, in order).

- [ ] **Step 2: Run to verify they fail** — `uv run pytest scraper/tests/test_http.py scraper/tests/test_db_schema.py -q` → FAIL (no `text`, constraint violation on `amazon`).

- [ ] **Step 3: Implement** — in `scraper/http.py` replace `json` with a shared request loop:

```python
    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urlsplit(url).hostname or ""
        limit = self._limits.setdefault(host, asyncio.Semaphore(PER_HOST_LIMIT))
        last: FetchError | None = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt:
                await asyncio.sleep(self._base_delay * 2 ** (attempt - 1) * (1 + random.random()))
            try:
                async with limit:
                    resp = await self._client.request(method, url, **kwargs)
            except httpx.TransportError as e:
                last = FetchError(f"{type(e).__name__}: {e}")
                continue
            if resp.status_code in RETRY_STATUSES:
                last = FetchError(f"HTTP {resp.status_code}", resp.status_code)
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}", resp.status_code)
            return resp
        assert last is not None
        raise last

    async def json_with_headers(self, method: str, url: str, **kwargs: Any) -> tuple[Any, httpx.Headers]:
        resp = await self._request(method, url, **kwargs)
        try:
            return resp.json(), resp.headers
        except ValueError as e:
            raise FetchError(f"invalid JSON: {e}") from e

    async def json(self, method: str, url: str, **kwargs: Any) -> Any:
        return (await self.json_with_headers(method, url, **kwargs))[0]

    async def text(self, method: str, url: str, **kwargs: Any) -> str:
        return (await self._request(method, url, **kwargs)).text
```

`supabase/migrations/20261008000000_bigtech_ats.sql`:

```sql
-- Companies with their own career sites (no standard job-board system).
alter table companies drop constraint companies_ats_check;
alter table companies add constraint companies_ats_check
  check (ats in ('greenhouse','lever','ashby','workday','smartrecruiters','workable',
                 'amazon','microsoft','apple','google'));
```

- [ ] **Step 4: Run to verify they pass** — same command → PASS; then the full suite + ruff (all existing `Fetcher.json` users still pass).
- [ ] **Step 5: Commit** — `git add scraper supabase && git commit -m "feat: fetcher text/headers and big-tech ats values"`

---

### Task 2: Amazon adapter

**Files:** Create `scraper/adapters/amazon.py`; Test `scraper/tests/test_bigtech.py` (create); Modify `scraper/adapters/__init__.py`

**Interfaces:**
- Produces: `amazon.fetch`; `ADAPTERS["amazon"]`. Search URL: `GET https://www.amazon.jobs/en/search.json?base_query={q}&country[]=USA&country[]=CAN&result_limit=100&offset={n}&sort=recent` → `{"hits": int, "jobs": [...]}`. Job keys used: `id_icims` (source id), `title`, `job_path` (URL = `https://www.amazon.jobs` + path), `location`/`normalized_location`, `country_code` (`USA`/`CAN`), `posted_date` (`"October  8, 2026"`), `job_schedule_type`, and the text fields `description`, `basic_qualifications`, `preferred_qualifications` (HTML-ish text; run through `html_to_text`).

- [ ] **Step 1: Write the failing tests** — `scraper/tests/test_bigtech.py`:

```python
import json
from datetime import UTC, datetime

import httpx
import pytest

from scraper.adapters import ADAPTERS, amazon
from scraper.http import Fetcher, FetchError
from scraper.models import Company


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def co(ats):
    return Company(id=1, name=ats.title(), ats=ats, slug=ats)


def amazon_job(i, title="Software Development Engineer Intern - 2027 (US)", **kw):
    base = {
        "id_icims": str(i), "title": title, "job_path": f"/en/jobs/{i}/sde-intern",
        "location": "US, WA, Seattle", "normalized_location": "Seattle, Washington, USA",
        "country_code": "USA", "posted_date": "October  8, 2026",
        "job_schedule_type": "full-time",
        "description": "Build services.<br/>Pay: $45 per hour.",
        "basic_qualifications": "- Currently enrolled in a BS",
        "preferred_qualifications": "- Python",
    }
    return base | kw


async def test_amazon_fetch_maps_fields_and_searches_both_queries():
    seen = []

    def handler(request):
        seen.append((request.url.params["base_query"], request.url.params["offset"]))
        assert request.url.params.get_list("country[]") == ["USA", "CAN"]
        if request.url.params["base_query"] == "intern":
            return httpx.Response(200, json={"hits": 2, "jobs": [amazon_job(1), amazon_job(2, "Account Executive")]})
        return httpx.Response(200, json={"hits": 1, "jobs": [amazon_job(3, "Software Engineer Co-op", country_code="CAN", location="CA, ON, Toronto")]})

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["amazon"](f, co("amazon"))
    assert seen == [("intern", "0"), ("co-op", "0")]
    assert [j.source_job_id for j in result.jobs] == ["1", "2", "3"]
    job = result.jobs[0]
    assert job.source == "amazon" and job.url == "https://www.amazon.jobs/en/jobs/1/sde-intern"
    assert job.location_raw == "Seattle, Washington, USA" and job.country_hint == "US"
    assert job.source_posted_at == datetime(2026, 10, 8, tzinfo=UTC)
    assert "Pay: $45 per hour." in job.description_text and "Python" in job.description_text
    assert result.jobs[2].country_hint == "CA" and not result.confirmed_empty


async def test_amazon_pages_until_hits():
    offsets = []

    def handler(request):
        n = int(request.url.params["offset"])
        if request.url.params["base_query"] != "intern":
            return httpx.Response(200, json={"hits": 0, "jobs": []})
        offsets.append(n)
        return httpx.Response(200, json={"hits": 230, "jobs": [amazon_job(n + i, "Sales Rep") for i in range(100)]})

    async with make_fetcher(handler) as f:
        result = await amazon.fetch(f, co("amazon"))
    assert offsets == [0, 100, 200] and len(result.jobs) == 300


async def test_amazon_zero_hits_is_confirmed_empty_and_bad_payload_raises():
    async with make_fetcher(lambda r: httpx.Response(200, json={"hits": 0, "jobs": []})) as f:
        assert (await amazon.fetch(f, co("amazon"))).confirmed_empty
    async with make_fetcher(lambda r: httpx.Response(200, json={"error": "x"})) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await amazon.fetch(f, co("amazon"))
    async with make_fetcher(lambda r: httpx.Response(200, text="<html>blocked</html>")) as f:
        with pytest.raises(FetchError):
            await amazon.fetch(f, co("amazon"))
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest scraper/tests/test_bigtech.py -q` → FAIL (`cannot import name 'amazon'`).

- [ ] **Step 3: Implement** — `scraper/adapters/amazon.py`:

```python
from datetime import UTC, datetime
from typing import Any

from scraper.adapters.base import dedupe_by, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "amazon"
PAGE = 100
MAX_PAGES = 5
QUERIES = ("intern", "co-op")
_COUNTRY = {"USA": "US", "CAN": "CA"}


def search_url(query: str, offset: int) -> str:
    return (
        "https://www.amazon.jobs/en/search.json?base_query="
        f"{query}&country[]=USA&country[]=CAN&result_limit={PAGE}&offset={offset}&sort=recent"
    )


def _posted(text: str | None) -> datetime | None:
    try:
        return datetime.strptime(" ".join((text or "").split()), "%B %d, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def _record(item: dict[str, Any]) -> dict[str, Any]:
    parts = (item.get(k) or "" for k in ("description", "basic_qualifications", "preferred_qualifications"))
    return {
        "source": SOURCE,
        "source_job_id": str(item.get("id_icims") or ""),
        "title": item.get("title") or "",
        "url": f"https://www.amazon.jobs{item.get('job_path') or ''}",
        "location_raw": item.get("normalized_location") or item.get("location") or "",
        "description_text": "\\n".join(p for p in (html_to_text(x) for x in parts) if p),
        "source_posted_at": _posted(item.get("posted_date")),
        "country_hint": _COUNTRY.get(item.get("country_code") or "", "OTHER"),
        "employment_type_hint": item.get("job_schedule_type"),
    }


async def _search(fetcher: Fetcher, query: str) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    hits = 0
    for page_no in range(MAX_PAGES):
        data = await fetcher.json("GET", search_url(query, page_no * PAGE))
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise FetchError("unexpected Amazon payload")
        if page_no == 0:
            hits = int(data.get("hits") or 0)
        items.extend(data["jobs"])
        if not data["jobs"] or len(items) >= hits:
            break
    return items, hits


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    found: list[dict[str, Any]] = []
    totals: list[int] = []
    for query in QUERIES:
        items, hits = await _search(fetcher, query)
        found.extend(items)
        totals.append(hits)
    items = dedupe_by(found, lambda i: str(i.get("id_icims") or ""))
    result = validate(_record(i) for i in items)
    result.confirmed_empty = not items and not any(totals)
    return result
```
(Use `"\n"` — a real newline — in the join; the escaped form above is only because this plan is a Markdown/heredoc.) Register `"amazon": amazon.fetch` in `scraper/adapters/__init__.py`.

- [ ] **Step 4: Run to verify they pass** — `uv run pytest scraper/tests/test_bigtech.py -q`; fix mismatches in the code, not the test. Full suite + ruff.
- [ ] **Step 5: Live check** — `uv run python - <<'EOF'` building `Company(id=1, name="Amazon", ats="amazon", slug="amazon")`, running `amazon.fetch` with a real `Fetcher` through `pipeline.process`, printing `(ok, len(seen_ids), len(jobs), error)` and the first five jobs' `(location.country, title, raw.location_raw, term)`. Expected: `True N M None` with US/CA countries and real cities; record in the ledger. If the site answers HTML/403, adjust headers (a browser-like `Accept`) and re-test before moving on.
- [ ] **Step 6: Commit** — `git add scraper && git commit -m "feat: Amazon adapter"`

---

### Task 3: Microsoft adapter

**Files:** Create `scraper/adapters/microsoft.py`; Test `scraper/tests/test_bigtech.py`; Modify `scraper/adapters/__init__.py`

**Interfaces:**
- Search: `GET https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query={q}&location={loc}&start={n}&sort_by=timestamp` for `loc` in `United States`, `Canada`; response `{"data": {"positions": [...], "count": int}}`, 10 positions per page. Position keys: `displayJobId` (source id), `id`, `name`, `standardizedLocations` (`["Redmond, WA, US"]`), `postedTs` (epoch seconds), `workLocationOption` (`onsite|hybrid|remote`), `publicUrl`/`positionUrl`.
- Detail: `GET https://apply.careers.microsoft.com/api/pcsx/position_details?position_id={id}&domain=microsoft.com&hl=en` → `data.jobDescription` (HTML), `data.publicUrl`, `data.efcustomTextEmploymentType` (list, e.g. `["Internship"]`).
- Produces: `microsoft.fetch`; `ADAPTERS["microsoft"]`.

- [ ] **Step 1: Write the failing tests** — append to `test_bigtech.py`:

```python
from scraper.adapters import microsoft


def ms_pos(i, name="Software Engineer Intern", locs=("Redmond, WA, US",), **kw):
    base = {
        "id": 1000 + i, "displayJobId": f"2000{i}", "name": name,
        "standardizedLocations": list(locs), "postedTs": 1791482125,
        "workLocationOption": "hybrid", "positionUrl": f"/careers/job/{1000 + i}",
    }
    return base | kw


def ms_handler(positions_by_loc, details=None, count=None):
    seen = []

    def handler(request):
        if request.url.path.endswith("/search"):
            q = request.url.params
            seen.append((q["query"], q["location"], q["start"]))
            items = positions_by_loc.get((q["query"], q["location"]), [])
            start = int(q["start"])
            return httpx.Response(200, json={"data": {"positions": items[start:start + 10], "count": len(items)}})
        pid = request.url.params["position_id"]
        if details is None or pid not in details:
            return httpx.Response(404)
        return httpx.Response(200, json={"data": details[pid]})

    handler.seen = seen
    return handler


async def test_microsoft_fetch_searches_each_country_and_reads_details():
    detail = {"jobDescription": "<p>Build.</p><p>Pay: $50 per hour.</p>",
              "publicUrl": "https://apply.careers.microsoft.com/careers/job/1001",
              "efcustomTextEmploymentType": ["Internship"]}  # fmt: skip
    h = ms_handler(
        {("intern", "United States"): [ms_pos(1), ms_pos(2, "Account Executive")],
         ("co-op", "Canada"): [ms_pos(3, "Software Engineer Co-op", locs=("Toronto, ON, CA",))]},
        details={"1001": detail, "1003": {"jobDescription": "<p>Co-op.</p>"}},
    )  # fmt: skip
    async with make_fetcher(h) as f:
        result = await ADAPTERS["microsoft"](f, co("microsoft"))
    assert {(q, loc) for q, loc, _ in h.seen} == {
        (q, loc) for q in ("intern", "co-op") for loc in ("United States", "Canada")
    }
    assert [j.source_job_id for j in result.jobs] == ["20001", "20002", "20003"]
    job = result.jobs[0]
    assert job.url == "https://apply.careers.microsoft.com/careers/job/1001"
    assert job.location_raw == "Redmond, WA, US" and job.work_mode_hint == "hybrid"
    assert job.employment_type_hint == "Internship" and "Pay: $50 per hour." in job.description_text
    assert job.source_posted_at == datetime.fromtimestamp(1791482125, UTC)


async def test_microsoft_failed_detail_is_pending_not_gone():
    h = ms_handler({("intern", "United States"): [ms_pos(1)]}, details={})
    async with make_fetcher(h) as f:
        result = await microsoft.fetch(f, co("microsoft"))
    assert result.jobs == [] and result.pending_ids == {"20001"}


async def test_microsoft_pages_by_ten():
    h = ms_handler({("intern", "United States"): [ms_pos(i, "Sales Rep") for i in range(25)]})
    async with make_fetcher(h) as f:
        result = await microsoft.fetch(f, co("microsoft"))
    starts = [s for q, loc, s in h.seen if (q, loc) == ("intern", "United States")]
    assert starts == ["0", "10", "20"] and len(result.jobs) == 25


async def test_microsoft_zero_count_confirmed_empty_and_bad_payload_raises():
    async with make_fetcher(ms_handler({})) as f:
        assert (await microsoft.fetch(f, co("microsoft"))).confirmed_empty
    async with make_fetcher(lambda r: httpx.Response(200, json={"status": 200})) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await microsoft.fetch(f, co("microsoft"))
```

- [ ] **Step 2: Run to verify they fail** — import error for `microsoft`.

- [ ] **Step 3: Implement** — `scraper/adapters/microsoft.py`:

```python
from datetime import UTC, datetime
from typing import Any

from scraper.adapters.base import dedupe_by, fetch_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "microsoft"
BASE = "https://apply.careers.microsoft.com"
PAGE = 10
MAX_PAGES = 20
QUERIES = ("intern", "co-op")
LOCATIONS = ("United States", "Canada")
_WORK_MODE = {"onsite": "onsite", "hybrid": "hybrid", "remote": "remote"}


def search_url(query: str, location: str, start: int) -> str:
    return (
        f"{BASE}/api/pcsx/search?domain=microsoft.com&query={query}"
        f"&location={location.replace(' ', '%20')}&start={start}&sort_by=timestamp"
    )


def detail_url(position_id: object) -> str:
    return f"{BASE}/api/pcsx/position_details?position_id={position_id}&domain=microsoft.com&hl=en"


def _key(item: dict[str, Any]) -> str:
    return str(item.get("displayJobId") or "")


def _record(item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    posted = item.get("postedTs")
    types = detail.get("efcustomTextEmploymentType") or []
    return {
        "source": SOURCE,
        "source_job_id": _key(item),
        "title": item.get("name") or "",
        "url": detail.get("publicUrl") or f"{BASE}{item.get('positionUrl') or ''}",
        "location_raw": " | ".join(item.get("standardizedLocations") or item.get("locations") or []),
        "description_text": html_to_text(detail.get("jobDescription") or ""),
        "source_posted_at": datetime.fromtimestamp(posted, UTC) if isinstance(posted, int | float) else None,
        "work_mode_hint": _WORK_MODE.get(item.get("workLocationOption") or ""),
        "employment_type_hint": types[0] if types else None,
    }


async def _search(fetcher: Fetcher, query: str, location: str) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    count = 0
    for page_no in range(MAX_PAGES):
        data = await fetcher.json("GET", search_url(query, location, page_no * PAGE))
        body = data.get("data") if isinstance(data, dict) else None
        if not isinstance(body, dict) or not isinstance(body.get("positions"), list):
            raise FetchError("unexpected Microsoft payload")
        if page_no == 0:
            count = int(body.get("count") or 0)
        items.extend(body["positions"])
        if not body["positions"] or len(items) >= count:
            break
    return items, count


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    found: list[dict[str, Any]] = []
    counts: list[int] = []
    for query in QUERIES:
        for location in LOCATIONS:
            items, count = await _search(fetcher, query, location)
            found.extend(items)
            counts.append(count)
    items = dedupe_by(found, _key)

    want = {_key(i): detail_url(i["id"]) for i in items if i.get("id") and wanted(i.get("name") or "")}
    details, pending = await fetch_details(fetcher, company, {_key(i) for i in items}, want)
    records = [
        _record(i, (details.get(_key(i)) or {}).get("data") or details.get(_key(i)) or {})
        for i in items
        if _key(i) not in pending
    ]
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items and not any(counts)
    return result
```
`get_details` returns the parsed JSON object per key; the Microsoft detail response is `{"data": {...}}`, so `_record` receives the inner dict (the `or` chain above handles both shapes; the tests serve `{"data": details[pid]}`). Register in `ADAPTERS`.

- [ ] **Step 4: Run to verify they pass** → `uv run pytest scraper/tests/test_bigtech.py -q`; full suite + ruff.
- [ ] **Step 5: Live check** — as Task 2 Step 5 with `Company(... ats="microsoft", slug="microsoft")`; expect US and CA jobs with `Redmond, WA, US`-style locations, and `description_text` populated for interns.
- [ ] **Step 6: Commit** — `git commit -m "feat: Microsoft adapter"`

---

### Task 4: Apple adapter

**Files:** Create `scraper/adapters/apple.py`; Test `scraper/tests/test_bigtech.py`; Modify `scraper/adapters/__init__.py`

**Interfaces:**
- Token: `GET https://jobs.apple.com/api/v1/CSRFToken` → response header `x-apple-csrf-token`.
- Search: `POST https://jobs.apple.com/api/v1/search` with headers `x-apple-csrf-token`, `Origin: https://jobs.apple.com` and body `{"query": q, "filters": {"locations": ["postLocation-USA", "postLocation-CAN"]}, "page": n, "locale": "en-us", "sort": "newest", "format": {...}}` → `{"res": {"searchResults": [...], "totalRecords": int}}`, 20 per page. Result keys: `positionId` (source id), `postingTitle`, `transformedPostingTitle`, `jobSummary`, `locations` (list of `{city, stateProvince, countryName}`), `postDateInGMT` (ISO).
- URL: `https://jobs.apple.com/en-us/details/{positionId}/{transformedPostingTitle}`.
- Produces: `apple.fetch`; `ADAPTERS["apple"]`.

- [ ] **Step 1: Write the failing tests** — append:

```python
from scraper.adapters import apple


def apple_res(i, title="Software Engineering Intern", **kw):
    base = {
        "positionId": f"1000{i}", "postingTitle": title,
        "transformedPostingTitle": title.lower().replace(" ", "-"),
        "jobSummary": "Build things. Pay: $48 per hour.",
        "locations": [{"city": "Cupertino", "stateProvince": "California", "countryName": "United States"}],
        "postDateInGMT": "2026-10-08T19:37:18.420Z",
    }
    return base | kw


def apple_handler(results_by_query, token="tok123"):
    seen = {"tokens": [], "bodies": []}

    def handler(request):
        if request.url.path.endswith("/CSRFToken"):
            headers = {"x-apple-csrf-token": token} if token else {}
            return httpx.Response(200, json={}, headers=headers)
        seen["tokens"].append(request.headers.get("x-apple-csrf-token"))
        body = json.loads(request.content)
        seen["bodies"].append(body)
        rows = results_by_query.get(body["query"], [])
        page = body["page"]
        return httpx.Response(200, json={"res": {"searchResults": rows[(page - 1) * 20: page * 20], "totalRecords": len(rows)}})

    handler.seen = seen
    return handler


async def test_apple_fetch_sends_csrf_and_maps_fields():
    h = apple_handler({"intern": [apple_res(1)], "co-op": [apple_res(2, "Hardware Co-op", locations=[{"city": "Toronto", "stateProvince": "Ontario", "countryName": "Canada"}])]})
    async with make_fetcher(h) as f:
        result = await ADAPTERS["apple"](f, co("apple"))
    assert set(h.seen["tokens"]) == {"tok123"}
    assert h.seen["bodies"][0]["filters"]["locations"] == ["postLocation-USA", "postLocation-CAN"]
    assert [j.source_job_id for j in result.jobs] == ["10001", "10002"]
    job = result.jobs[0]
    assert job.url == "https://jobs.apple.com/en-us/details/10001/software-engineering-intern"
    assert job.location_raw == "Cupertino, California, United States" and job.country_hint == "US"
    assert job.source_posted_at == datetime(2026, 10, 8, 19, 37, 18, 420000, tzinfo=UTC)
    assert "Pay: $48 per hour." in job.description_text
    assert result.jobs[1].country_hint == "CA"


async def test_apple_pages_by_twenty():
    h = apple_handler({"intern": [apple_res(i, "Sales Rep") for i in range(45)]})
    async with make_fetcher(h) as f:
        result = await apple.fetch(f, co("apple"))
    pages = [b["page"] for b in h.seen["bodies"] if b["query"] == "intern"]
    assert pages == [1, 2, 3] and len(result.jobs) == 45


async def test_apple_missing_token_or_bad_payload_raises_and_zero_is_confirmed_empty():
    async with make_fetcher(apple_handler({}, token=None)) as f:
        with pytest.raises(FetchError, match="CSRF"):
            await apple.fetch(f, co("apple"))
    async with make_fetcher(apple_handler({})) as f:
        assert (await apple.fetch(f, co("apple"))).confirmed_empty

    def bad(request):
        if request.url.path.endswith("/CSRFToken"):
            return httpx.Response(200, json={}, headers={"x-apple-csrf-token": "t"})
        return httpx.Response(200, json={"res": {}})

    async with make_fetcher(bad) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await apple.fetch(f, co("apple"))
```

- [ ] **Step 2: Run to verify they fail** — import error for `apple`.

- [ ] **Step 3: Implement** — `scraper/adapters/apple.py`:

```python
from datetime import datetime
from typing import Any

from scraper.adapters.base import dedupe_by, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult

SOURCE = "apple"
BASE = "https://jobs.apple.com"
MAX_PAGES = 10
QUERIES = ("intern", "co-op")
_COUNTRY = {"United States": "US", "United States of America": "US", "Canada": "CA"}


async def _csrf(fetcher: Fetcher) -> str:
    _, headers = await fetcher.json_with_headers("GET", f"{BASE}/api/v1/CSRFToken")
    token = headers.get("x-apple-csrf-token")
    if not token:
        raise FetchError("Apple did not issue a CSRF token")
    return token


def _body(query: str, page: int) -> dict[str, Any]:
    return {
        "query": query,
        "filters": {"locations": ["postLocation-USA", "postLocation-CAN"]},
        "page": page,
        "locale": "en-us",
        "sort": "newest",
        "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
    }


def _location(loc: dict[str, Any]) -> str:
    return ", ".join(p for p in (loc.get("city"), loc.get("stateProvince"), loc.get("countryName")) if p)


def _posted(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _record(item: dict[str, Any]) -> dict[str, Any]:
    locs = item.get("locations") or []
    country = _COUNTRY.get((locs[0].get("countryName") if locs else "") or "", "OTHER")
    pid = str(item.get("positionId") or "")
    return {
        "source": SOURCE,
        "source_job_id": pid,
        "title": item.get("postingTitle") or "",
        "url": f"{BASE}/en-us/details/{pid}/{item.get('transformedPostingTitle') or ''}",
        "location_raw": " | ".join(_location(x) for x in locs if _location(x)),
        "description_text": item.get("jobSummary") or "",
        "source_posted_at": _posted(item.get("postDateInGMT")),
        "country_hint": country,
    }


async def _search(fetcher: Fetcher, token: str, query: str) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    total = 0
    headers = {"x-apple-csrf-token": token, "Origin": BASE}
    for page_no in range(1, MAX_PAGES + 1):
        data = await fetcher.json("POST", f"{BASE}/api/v1/search", json=_body(query, page_no), headers=headers)
        res = data.get("res") if isinstance(data, dict) else None
        if not isinstance(res, dict) or not isinstance(res.get("searchResults"), list):
            raise FetchError("unexpected Apple payload")
        if page_no == 1:
            total = int(res.get("totalRecords") or 0)
        items.extend(res["searchResults"])
        if not res["searchResults"] or len(items) >= total:
            break
    return items, total


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    token = await _csrf(fetcher)
    found: list[dict[str, Any]] = []
    totals: list[int] = []
    for query in QUERIES:
        items, total = await _search(fetcher, token, query)
        found.extend(items)
        totals.append(total)
    items = dedupe_by(found, lambda i: str(i.get("positionId") or ""))
    result = validate(_record(i) for i in items)
    result.confirmed_empty = not items and not any(totals)
    return result
```
Register in `ADAPTERS`.

- [ ] **Step 4: Run to verify they pass**; full suite + ruff.
- [ ] **Step 5: Live check** as Task 2 Step 5 (`ats="apple"`); expect US/CA locations and non-empty summaries.
- [ ] **Step 6: Commit** — `git commit -m "feat: Apple adapter"`

---

### Task 5: Google adapter

**Files:** Create `scraper/adapters/google.py`; Test `scraper/tests/test_bigtech.py`; Modify `scraper/adapters/__init__.py`

**Interfaces:**
- Page: `GET https://www.google.com/about/careers/applications/jobs/results/?q={q}&location={loc}&page={n}` for `loc` in `United States`, `Canada`. The HTML contains `AF_initDataCallback({key: 'ds:1', hash: '2', data:<JSON>, sideChannel: {}});`. The JSON is `[jobs, ?, total, page_size]`; each job is an array: `[0]` id, `[1]` title, `[2]` apply URL, `[3][1]` responsibilities HTML, `[4][1]` minimum-qualifications HTML, `[7]` company, `[9]` locations (`[[display, [address…], …], …]`, `display` like `"Mountain View, CA, USA"`), `[10][1]` about HTML, `[19][1]` preferred-qualifications HTML.
- Produces: `google.parse_page(html) -> tuple[list, int]` (jobs, total); `google.fetch`; `ADAPTERS["google"]`.

- [ ] **Step 1: Write the failing tests** — append:

```python
from scraper.adapters import google


def g_job(i, title="Software Engineering Intern, Summer 2027", loc="Mountain View, CA, USA"):
    row = [None] * 21
    row[0], row[1] = f"9100{i}", title
    row[2] = f"https://www.google.com/about/careers/applications/signin?jobId=abc{i}&loc=US"
    row[3] = [None, "<ul><li>Write code.</li></ul>"]
    row[4] = [None, "<p>Pay: $52 per hour.</p>"]
    row[7] = "Google"
    row[9] = [[loc, ["addr"], "Mountain View", "94043", "CA", "US"]]
    row[10] = [None, "<p>About the team.</p>"]
    row[19] = [None, "<p>Python</p>"]
    return row


def g_page(jobs, total=None):
    blob = json.dumps([jobs, None, len(jobs) if total is None else total, 20])
    return f"<html><script>AF_initDataCallback({{key: 'ds:1', hash: '2', data:{blob}, sideChannel: {{}}}});</script></html>"


def test_google_parse_page():
    jobs, total = google.parse_page(g_page([g_job(1)], total=25))
    assert total == 25 and jobs[0][1].startswith("Software Engineering Intern")


def test_google_parse_page_raises_when_the_page_shape_changes():
    for html in ("<html>no data</html>", "<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:{}, sideChannel: {}});</script>"):
        with pytest.raises(FetchError, match="unexpected"):
            google.parse_page(html)


async def test_google_fetch_maps_fields_for_both_countries():
    seen = []

    def handler(request):
        p = request.url.params
        seen.append((p["q"], p["location"], p["page"]))
        if (p["q"], p["location"]) == ("intern", "United States"):
            return httpx.Response(200, text=g_page([g_job(1), g_job(2, "Sales Manager")]))
        if (p["q"], p["location"]) == ("co-op", "Canada"):
            return httpx.Response(200, text=g_page([g_job(3, "Software Engineer Co-op", "Waterloo, ON, Canada")]))
        return httpx.Response(200, text=g_page([], total=0))

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["google"](f, co("google"))
    assert [j.source_job_id for j in result.jobs] == ["91001", "91002", "91003"]
    job = result.jobs[0]
    assert job.url.startswith("https://www.google.com/about/careers/applications/signin?jobId=")
    assert job.location_raw == "Mountain View, CA, USA" and job.country_hint == "US"
    assert job.source_posted_at is None
    assert "Pay: $52 per hour." in job.description_text and "Write code." in job.description_text
    assert result.jobs[2].country_hint == "CA" and not result.confirmed_empty


async def test_google_pages_until_total_and_zero_is_confirmed_empty():
    pages = []

    def handler(request):
        p = request.url.params
        if (p["q"], p["location"]) != ("intern", "United States"):
            return httpx.Response(200, text=g_page([], total=0))
        pages.append(int(p["page"]))
        n = int(p["page"])
        return httpx.Response(200, text=g_page([g_job(n * 100 + i, "Sales Rep") for i in range(20)], total=45))

    async with make_fetcher(handler) as f:
        result = await google.fetch(f, co("google"))
    assert pages == [1, 2, 3] and len(result.jobs) == 60

    async with make_fetcher(lambda r: httpx.Response(200, text=g_page([], total=0))) as f:
        assert (await google.fetch(f, co("google"))).confirmed_empty
```

- [ ] **Step 2: Run to verify they fail** — import error for `google`.

- [ ] **Step 3: Implement** — `scraper/adapters/google.py`:

```python
import json
import re
from typing import Any

from scraper.adapters.base import dedupe_by, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "google"
BASE = "https://www.google.com/about/careers/applications/jobs/results/"
MAX_PAGES = 10
QUERIES = ("intern", "co-op")
LOCATIONS = ("United States", "Canada")
_BLOB = re.compile(r"AF_initDataCallback\(\{key: 'ds:1', hash: '\d+', data:(.*?), sideChannel", re.S)
_COUNTRY = {"USA": "US", "United States": "US", "Canada": "CA"}


def page_url(query: str, location: str, page: int) -> str:
    return f"{BASE}?q={query}&location={location.replace(' ', '%20')}&page={page}"


def parse_page(html: str) -> tuple[list[list[Any]], int]:
    """The results page ships its data as a JS array: [jobs, ?, total, page_size]."""
    m = _BLOB.search(html)
    try:
        data = json.loads(m.group(1)) if m else None
    except ValueError:
        data = None
    if not (isinstance(data, list) and len(data) >= 3 and isinstance(data[0], list)
            and isinstance(data[2], int)):  # fmt: skip
        raise FetchError("unexpected Google careers page (data blob missing or changed)")
    return data[0], data[2]


def _section(job: list[Any], i: int) -> str:
    cell = job[i] if len(job) > i else None
    return html_to_text(cell[1]) if isinstance(cell, list) and len(cell) > 1 and cell[1] else ""


def _record(job: list[Any]) -> dict[str, Any]:
    locs = job[9] if len(job) > 9 and isinstance(job[9], list) else []
    displays = [x[0] for x in locs if isinstance(x, list) and x and isinstance(x[0], str)]
    last = displays[0].rsplit(",", 1)[-1].strip() if displays else ""
    body = (_section(job, i) for i in (10, 3, 4, 19))
    return {
        "source": SOURCE,
        "source_job_id": str(job[0]),
        "title": job[1],
        "url": job[2] if len(job) > 2 and isinstance(job[2], str) else "",
        "location_raw": " | ".join(displays),
        "description_text": "\n".join(p for p in body if p),
        "source_posted_at": None,  # the two embedded timestamps are undocumented
        "country_hint": _COUNTRY.get(last, "OTHER") if displays else None,
    }


async def _search(fetcher: Fetcher, query: str, location: str) -> tuple[list[list[Any]], int]:
    jobs: list[list[Any]] = []
    total = 0
    for page_no in range(1, MAX_PAGES + 1):
        page_jobs, page_total = parse_page(await fetcher.text("GET", page_url(query, location, page_no)))
        if page_no == 1:
            total = page_total
        jobs.extend(page_jobs)
        if not page_jobs or len(jobs) >= total:
            break
    return jobs, total


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    found: list[list[Any]] = []
    totals: list[int] = []
    for query in QUERIES:
        for location in LOCATIONS:
            jobs, total = await _search(fetcher, query, location)
            found.extend(jobs)
            totals.append(total)
    unique = {str(j[0]): j for j in found if j and j[0]}
    result = validate(_record(j) for j in unique.values() if len(j) > 2 and isinstance(j[1], str))
    result.confirmed_empty = not unique and not any(totals)
    return result
```
(`dedupe_by` is not needed here; remove its import if unused so ruff passes.) Register in `ADAPTERS`.

- [ ] **Step 4: Run to verify they pass**; full suite + ruff.
- [ ] **Step 5: Live check** as Task 2 Step 5 (`ats="google"`). Expect real Google internships with `City, ST, USA` locations that `parse_location` turns into US/CA; if Google serves a consent/blocked page to our `User-Agent`, the adapter raises `unexpected Google careers page` — then try a browser-like `Accept-Language`/`Accept` header via `Fetcher.text(..., headers=…)` and re-test.
- [ ] **Step 6: Commit** — `git commit -m "feat: Google careers adapter"`

---

### Task 6: Seeds, live verification, docs

**Files:** Modify `data/companies.seed.yml`, `scraper/tests/test_cli.py`, `README.md`

- [ ] **Step 1: Update the seed test** — in `test_seed_file_is_valid` extend the allowed-ats set with `"amazon", "microsoft", "apple", "google"`.
- [ ] **Step 2: Add seeds** — append to `data/companies.seed.yml`:

```yaml
# Companies with their own career sites (one adapter each; slug = adapter name).
- {name: Amazon, ats: amazon, slug: amazon, domain: amazon.jobs, hot: true}
- {name: Microsoft, ats: microsoft, slug: microsoft, domain: microsoft.com, hot: true}
- {name: Apple, ats: apple, slug: apple, domain: apple.com, hot: true}
- {name: Google, ats: google, slug: google, domain: google.com, hot: true}
```
- [ ] **Step 3: Verify live** — `uv run python -m scraper seed --verify 2>&1 | grep -E "amazon|microsoft|apple|google|boards OK"` → all four `✓` with non-zero "CA/US tech internships" for at least three of them; the summary line shows no new failures. Time the four-company poll (`time uv run python -m scraper run --dry-run --ats apple --company apple` is not supported for these; use the seed `--verify` timing) and record it: it must be seconds, not minutes.
- [ ] **Step 4: Apply and ingest** (needs `DATABASE_URL` in the gitignored `.env`; never print it): `set -a && . ./.env && set +a && uv run python -m scraper migrate && uv run python -m scraper seed && uv run python -m scraper run --tier hot --ats amazon && uv run python -m scraper run --tier hot --ats microsoft` then Apple and Google; each prints `polled=1 … errors=0`. A second run of each prints `new=0`. Check `select freshness, count(*) from jobs j join companies c on c.id=j.company_id where c.ats in ('amazon','microsoft','apple','google') group by 1`: the first-poll backlog is `existing`, not `fresh`.
- [ ] **Step 5: README** — add Amazon, Microsoft, Apple, Google to the **Sources** line and a one-line note that Meta is not supported (its careers API needs rotating page tokens).
- [ ] **Step 6: Full verification and commit** — full Python suite + ruff + format check; `git log --format='%an <%ae>%n%b' main..HEAD | sort | uniq -c` shows only baldeep06 and no `Co-Authored-By`; `git add -A data scraper README.md && git commit -m "feat: seed Amazon, Microsoft, Apple and Google and document sources"`.

---

## Self-Review

- **Spec coverage (§3 / §11 Phase 5):** Amazon, Microsoft, Apple, Google adapters → Tasks 2–5; Meta deliberately dropped (ruled above); registry/seed/docs → Task 6; schema → Task 1.
- **Placeholders:** none; live-check steps give exact commands and expectations.
- **Type consistency:** every adapter uses the existing `FetchResult` / `pending_ids` / `confirmed_empty` contract and `dedupe_by`/`fetch_details`/`validate` from `scraper/adapters/base.py`; `Fetcher.text` / `json_with_headers` (Task 1) are what Tasks 4–5 consume.
