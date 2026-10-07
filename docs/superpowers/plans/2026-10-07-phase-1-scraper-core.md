# Phase 1 — Scraper Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real tech-internship postings from Greenhouse, Lever and Ashby boards land in Supabase every 5 minutes, enriched (category, location, term, pay, visa, flags) and labeled fresh/repost/reopened/refreshed/recurring.

**Architecture:** A Python package (`scraper/`) run by GitHub Actions. Async `httpx` fetches each company's ATS board → adapter parses to `RawJob` → pure enrichment functions produce `EnrichedJob` → pure dedupe logic decides insert/touch/reopen/refresh/attach → `psycopg` writes to Supabase Postgres in one transaction per company. Pure logic is unit-tested; DB code is tested against a throwaway local Postgres.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, selectolax, psycopg 3, PyYAML, pytest (+pytest-asyncio), ruff, Postgres 17, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md` (this plan implements spec §11 phase 1: §3 tier-1 Greenhouse/Lever/Ashby, §4, §5 except H-1B, §6 `scrape-hot` + `ci`, §7, §10 scraper parts).

## Global Constraints

- Python `>=3.12`; dependencies managed with `uv` (`uv.lock` committed).
- **Commits list only the repo owner as author — never add `Co-Authored-By` or "Generated with" lines.**
- All datetimes are timezone-aware UTC.
- HTTP: 15 s timeout, 3 retries with exponential backoff + jitter on 429/500/502/503/504/network errors, max 5 concurrent requests per host, `User-Agent: intern-job-scraper (+https://github.com/baldeep06/jobs-scraping)`.
- Close a job only after a **successful** poll and **2** consecutive misses.
- Repost window **120 days**; "refreshed" requires the job to be first seen **> 7 days** ago.
- Hourly equivalents: year ÷ 2080, month ÷ 173.3, week ÷ 40, rounded to 2 decimals.
- Full job descriptions are never stored; only evidence sentences (≤ 300 chars).
- Scraper connects with `DATABASE_URL` = Supabase **session pooler** URI. Never print it.
- Tests that need Postgres read `TEST_DATABASE_URL`; they **drop the `public` schema**, so the fixture refuses any URL containing `supabase`.
- Ruff: line length 100 (formatter), lint rules `E,F,I,UP,B` with `E501` ignored.

## Review Focus

1. **Foreign-only locations** ("London, UK", "Bangalore, India", "Berlin, DE", Ashby country "United Kingdom") must be dropped, not shown as `UNKNOWN` in both tabs → tests in Task 5 and Task 11.
2. **Real intern titles containing trap words** ("Software Engineer Intern, Internal Tools", "Product Manager Intern") must be kept, while "Internal Audit Analyst" and "Student Success Manager" are dropped → tests in Task 4.
3. **One company lists the same role twice** (two IDs, same fingerprint): one `jobs` row with two `job_sources`; the job stays open while either ID is still listed → test in Task 16.
4. **A board fetch fails** (404, timeout, invalid JSON, unexpected shape): no jobs closed, other companies still ingested, 5 consecutive 404s → `inactive` → tests in Task 10, Task 15, Task 16.
5. **Dollar amounts that aren't pay** ("$50M Series B", "$5,000 relocation stipend") produce no pay; Canada-only jobs default to CAD → tests in Task 7.

## File Map

```
pyproject.toml, uv.lock, .python-version, .env.example
scraper/
  __init__.py
  __main__.py            CLI (migrate | seed | run)
  models.py              Company, RawJob, PayRange, Pay, Location, ParsedLocation,
                         EnrichedJob, FetchResult, CompanyOutcome
  text.py                html_to_text, sentence_at
  http.py                Fetcher (retries, per-host limits), FetchError
  dedupe.py              fingerprint, ids_hash, classify, plan_closures
  pipeline.py            dominant_country, process, poll
  db.py                  connect, migrate, upsert_companies, get_companies, ingest, record_run
  normalize/
    __init__.py
    geo.py               US_STATES, CA_PROVINCES, KNOWN_CITIES, FOREIGN_RE
    title.py             normalize_title
    location.py          parse_location
    term.py              parse_term
    pay.py               parse_pay
  enrich/
    __init__.py          enrich()
    category.py          is_intern_title, categorize
    visa.py              detect_visa_signals, visa_status, Profile, OWNER_PROFILE
    flags.py             detect_flags
  adapters/
    __init__.py          ADAPTERS registry
    base.py              Adapter type, validate()
    greenhouse.py, lever.py, ashby.py
  tests/
    conftest.py          Postgres fixture
    sql/supabase_shim.sql
    fixtures/greenhouse.json, lever.json, ashby.json
    test_*.py
supabase/migrations/20261007000000_init.sql
data/companies.seed.yml
.github/workflows/ci.yml, scrape-hot.yml
```

---

### Task 1: Project scaffold and models

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.env.example`, `scraper/__init__.py`, `scraper/models.py`, `scraper/tests/__init__.py`, `scraper/tests/test_models.py`

**Interfaces:**
- Produces (in `scraper/models.py`): `Company(id:int, name:str, ats:str, slug:str, job_ids_hash:str|None)`, `PayRange(min,max:float|None, currency:str|None, period:PayPeriod|None)`, `Pay(min,max:float, currency:str, period:PayPeriod, hourly_min,hourly_max:float, raw:str)`, `RawJob(...)`, `Location(city:str|None, region:str|None, country:"CA"|"US")` with `.key()->str`, `ParsedLocation(locations, country, work_mode, location_unclear, foreign_only)`, `EnrichedJob(...)`, `FetchResult(jobs:list[RawJob], invalid:int)`, `CompanyOutcome(...)`.

- [ ] **Step 1: Create project files**

`pyproject.toml`:
```toml
[project]
name = "jobs-scraping"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.7",
  "selectolax>=0.3.21",
  "psycopg[binary]>=3.2",
  "pyyaml>=6.0",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6"]

[tool.uv]
package = false

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["scraper/tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]  # ruff format handles line length
```

`.python-version`:
```
3.12
```

`.env.example`:
```
# Supabase → Project Settings → Database → Connection string → Session pooler (URI)
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
# Local throwaway Postgres for tests (NEVER Supabase — tests drop the public schema)
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres
```

`scraper/__init__.py` and `scraper/tests/__init__.py`: empty files.

Run: `uv sync`
Expected: creates `.venv` and `uv.lock`, installs packages.

- [ ] **Step 2: Write the failing test** — `scraper/tests/test_models.py`

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from scraper.models import Location, RawJob


def make(**kw):
    base = dict(source="greenhouse", source_job_id="1", title="Intern", url="https://x/1")
    return RawJob(**(base | kw))


def test_title_whitespace_collapsed():
    assert make(title="  Software   Engineer\nIntern ").title == "Software Engineer Intern"


def test_blank_title_rejected():
    with pytest.raises(ValidationError):
        make(title="   ")


def test_empty_source_job_id_rejected():
    with pytest.raises(ValidationError):
        make(source_job_id="")


def test_naive_datetime_becomes_utc():
    job = make(source_posted_at=datetime(2026, 10, 1, 12, 0))
    assert job.source_posted_at == datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_iso_string_parsed():
    job = make(source_posted_at="2026-09-28T09:00:00-04:00")
    assert job.source_posted_at == datetime(2026, 9, 28, 13, 0, tzinfo=UTC)


def test_location_key():
    assert Location(city="Toronto", region="ON", country="CA").key() == "toronto|ON|CA"
    assert Location(country="US").key() == "||US"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.models'`

- [ ] **Step 4: Implement** — `scraper/models.py`

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Country = Literal["CA", "US", "BOTH", "UNKNOWN"]
WorkMode = Literal["onsite", "hybrid", "remote", "unknown"]
PayPeriod = Literal["hour", "year", "month", "week"]
VisaStatus = Literal["open", "blocked", "unknown"]


class Company(BaseModel):
    id: int
    name: str
    ats: str
    slug: str
    job_ids_hash: str | None = None


class PayRange(BaseModel):
    """Structured pay as provided by an ATS (any field may be missing)."""

    min: float | None = None
    max: float | None = None
    currency: str | None = None
    period: PayPeriod | None = None


class Pay(BaseModel):
    """Normalized pay attached to an enriched job."""

    min: float
    max: float
    currency: str
    period: PayPeriod
    hourly_min: float
    hourly_max: float
    raw: str


class RawJob(BaseModel):
    source: str
    source_job_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    location_raw: str = ""
    description_text: str = ""
    source_posted_at: datetime | None = None
    pay_structured: PayRange | None = None
    work_mode_hint: WorkMode | None = None
    # "CA", "US", any other ISO code, or "OTHER" (= somewhere outside CA/US)
    country_hint: str | None = None
    employment_type_hint: str | None = None

    @field_validator("title")
    @classmethod
    def _collapse_title(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("empty title")
        return v

    @field_validator("source_posted_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class Location(BaseModel):
    city: str | None = None
    region: str | None = None  # 2-letter state/province code
    country: Literal["CA", "US"]

    def key(self) -> str:
        return f"{(self.city or '').lower()}|{self.region or ''}|{self.country}"


class ParsedLocation(BaseModel):
    locations: list[Location] = []
    country: Country
    work_mode: WorkMode = "unknown"
    location_unclear: bool = False
    foreign_only: bool = False


class EnrichedJob(BaseModel):
    raw: RawJob
    company_id: int
    normalized_title: str
    category: str
    term: str | None
    duration_months: int | None
    location: ParsedLocation
    pay: Pay | None
    visa_signals: list[str]
    visa_status: VisaStatus
    flags: list[str]
    evidence: dict[str, str]
    fingerprint: str


@dataclass
class FetchResult:
    jobs: list[RawJob]
    invalid: int = 0


@dataclass
class CompanyOutcome:
    """Result of polling one company, ready for db.ingest()."""

    company: Company
    ok: bool
    jobs: list[EnrichedJob] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    ids_hash: str | None = None
    unchanged: bool = False
    invalid: int = 0
    error: str | None = None
    status: int | None = None
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest scraper/tests/test_models.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: 6 passed; ruff clean (run `uv run ruff format .` if format check fails).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version .env.example scraper/
git commit -m "Add scraper project scaffold and data models"
```

---

### Task 2: Text utilities

**Files:**
- Create: `scraper/text.py`, `scraper/tests/test_text.py`

**Interfaces:**
- Produces: `html_to_text(raw: str) -> str` (block elements become newlines, entity-escaped HTML handled), `sentence_at(text: str, index: int, max_len: int = 300) -> str` (sentence/line containing `index`).

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_text.py`

```python
from scraper.text import html_to_text, sentence_at


def test_html_to_text_handles_escaped_html():
    raw = "&lt;p&gt;Join our team.&lt;/p&gt;&lt;p&gt;Pay is &lt;b&gt;$30&lt;/b&gt; per hour &amp;amp; more.&lt;/p&gt;"
    assert html_to_text(raw) == "Join our team.\nPay is $30 per hour & more."


def test_html_to_text_list_items_and_br():
    assert html_to_text("<ul><li>One</li><li>Two</li></ul>Three<br/>Four") == "One\nTwo\nThree\nFour"


def test_html_to_text_empty():
    assert html_to_text("") == ""


def test_sentence_at_picks_containing_sentence():
    text = "Great team. We will not sponsor visas. Apply now."
    assert sentence_at(text, text.index("sponsor")) == "We will not sponsor visas."


def test_sentence_at_does_not_split_on_us_abbreviation():
    text = "Applicants must be U.S. Citizens to apply. Thanks."
    assert sentence_at(text, text.index("must")) == "Applicants must be U.S. Citizens to apply."


def test_sentence_at_splits_on_newlines_and_truncates():
    text = "Line one\n" + "x" * 400
    assert sentence_at(text, 2) == "Line one"
    out = sentence_at(text, 20)
    assert len(out) == 300 and out.endswith("…")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.text'`

- [ ] **Step 3: Implement** — `scraper/text.py`

```python
import html
import re

from selectolax.parser import HTMLParser

_BLOCK_END = re.compile(r"(?i)<\s*(?:br\s*/?|/p|/li|/div|/h[1-6]|/tr|/ul|/ol)\s*>")
# Split after . ! ? when preceded by a lowercase letter/digit/bracket (so "U.S. Citizens"
# stays together) and followed by an uppercase/digit/quote; or on newlines.
_SENTENCE_BREAK = re.compile(r"(?<=[a-z0-9)\]][.!?])\s+(?=[A-Z0-9(\"'])|\n+")


def html_to_text(raw: str) -> str:
    """HTML (possibly entity-escaped, as Greenhouse returns it) -> plain text, one block per line."""
    if not raw:
        return ""
    marked = _BLOCK_END.sub("\n", html.unescape(raw))
    text = HTMLParser(marked).text(separator="")
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in _SENTENCE_BREAK.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def sentence_at(text: str, index: int, max_len: int = 300) -> str:
    for start, end in _spans(text):
        if start <= index <= end:
            s = text[start:end].strip()
            return s if len(s) <= max_len else s[: max_len - 1].rstrip() + "…"
    return ""
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_text.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scraper/text.py scraper/tests/test_text.py
git commit -m "Add HTML-to-text and sentence extraction helpers"
```

---

### Task 3: Title normalization and dedupe primitives

**Files:**
- Create: `scraper/normalize/__init__.py` (empty), `scraper/normalize/title.py`, `scraper/dedupe.py`, `scraper/tests/test_dedupe.py`

**Interfaces:**
- Consumes: `Location` (Task 1).
- Produces:
  - `normalize_title(title: str) -> str`
  - `fingerprint(company_id: int, normalized_title: str, locations: list[Location]) -> str`
  - `ids_hash(ids: Iterable[str]) -> str`
  - `ExistingSource(job_id, job_status, job_first_seen_at, source_posted_at)`, `FingerprintMatch(job_id, status, last_seen_at, repost_count)`, `Decision(action, job_id=None, freshness=None, repost_of=None, repost_count=0)`
  - `classify(existing: ExistingSource|None, incoming_posted_at: datetime|None, fp_match: FingerprintMatch|None, now: datetime) -> Decision`
  - `OpenJob(job_id, miss_count, source_job_ids: frozenset[str])`, `ClosurePlan(reset, increment, close: list[str])`
  - `plan_closures(open_jobs: list[OpenJob], seen_ids: set[str]) -> ClosurePlan`

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_dedupe.py`

```python
from datetime import UTC, datetime, timedelta

from scraper.dedupe import (
    Decision,
    ExistingSource,
    FingerprintMatch,
    OpenJob,
    classify,
    fingerprint,
    ids_hash,
    plan_closures,
)
from scraper.models import Location
from scraper.normalize.title import normalize_title

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
TOR = Location(city="Toronto", region="ON", country="CA")
NYC = Location(city="New York", region="NY", country="US")


def test_normalize_title_strips_terms_years_punctuation():
    a = normalize_title("Software Engineer Intern (Summer 2027)")
    b = normalize_title("Software Engineer Intern - Summer 2028")
    assert a == b == "software engineer intern"
    assert normalize_title("Co-op, 4-Month Software Developer") == "co op software developer"
    assert normalize_title("Data Intern (12-16 months)") == "data intern"


def test_fingerprint_ignores_location_order_and_differs_by_company():
    assert fingerprint(1, "swe intern", [TOR, NYC]) == fingerprint(1, "swe intern", [NYC, TOR])
    assert fingerprint(1, "swe intern", [TOR]) != fingerprint(2, "swe intern", [TOR])


def test_ids_hash_order_independent():
    assert ids_hash(["b", "a"]) == ids_hash({"a", "b"})


def existing(status="open", first_seen_days=30, posted=None):
    return ExistingSource("job-1", status, NOW - timedelta(days=first_seen_days), posted)


def test_new_job_is_fresh_insert():
    assert classify(None, None, None, NOW) == Decision("insert", freshness="fresh")


def test_closed_existing_source_reopens():
    assert classify(existing("closed"), None, None, NOW) == Decision(
        "reopen", job_id="job-1", freshness="reopened"
    )


def test_posted_date_bump_on_old_job_is_refresh():
    old = NOW - timedelta(days=40)
    d = classify(existing(posted=old), NOW - timedelta(days=1), None, NOW)
    assert d == Decision("refresh", job_id="job-1", freshness="refreshed")


def test_posted_date_bump_on_young_job_is_touch():
    old = NOW - timedelta(days=3)
    d = classify(existing(first_seen_days=2, posted=old), NOW, None, NOW)
    assert d == Decision("touch", job_id="job-1")


def test_same_posted_date_is_touch():
    p = NOW - timedelta(days=40)
    assert classify(existing(posted=p), p, None, NOW) == Decision("touch", job_id="job-1")


def test_new_id_matching_open_fingerprint_attaches():
    fp = FingerprintMatch("job-9", "open", NOW, 0)
    assert classify(None, None, fp, NOW) == Decision("attach", job_id="job-9")


def test_new_id_matching_recent_closed_fingerprint_is_repost():
    fp = FingerprintMatch("job-9", "closed", NOW - timedelta(days=30), 1)
    assert classify(None, None, fp, NOW) == Decision(
        "insert", freshness="repost", repost_of="job-9", repost_count=2
    )


def test_new_id_matching_old_fingerprint_is_recurring():
    fp = FingerprintMatch("job-9", "closed", NOW - timedelta(days=200), 0)
    assert classify(None, None, fp, NOW) == Decision("insert", freshness="recurring")


def test_plan_closures():
    jobs = [
        OpenJob("seen", 1, frozenset({"a"})),
        OpenJob("first-miss", 0, frozenset({"b"})),
        OpenJob("second-miss", 1, frozenset({"c"})),
        OpenJob("one-of-two-ids-seen", 0, frozenset({"d", "e"})),
    ]
    plan = plan_closures(jobs, {"a", "e"})
    assert plan.reset == ["seen"]
    assert plan.increment == ["first-miss"]
    assert plan.close == ["second-miss"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_dedupe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.dedupe'`

- [ ] **Step 3: Implement** — `scraper/normalize/title.py`

```python
import re

_MONTHS = re.compile(r"\b\d{1,2}\s*(?:-|–|to)?\s*(?:\d{1,2}\s*)?[- ]?months?\b", re.I)
_YEAR = re.compile(r"\b20\d\d\b")
_SEASON = re.compile(r"\b(?:summer|fall|autumn|winter|spring)\b", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    """Lowercase title without term/year/duration words or punctuation (for fingerprints)."""
    t = title.lower()
    t = _MONTHS.sub(" ", t)
    t = _YEAR.sub(" ", t)
    t = _SEASON.sub(" ", t)
    t = _NON_ALNUM.sub(" ", t)
    return " ".join(t.split())
```

`scraper/dedupe.py`:
```python
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from scraper.models import Location

REPOST_WINDOW = timedelta(days=120)
REFRESH_MIN_AGE = timedelta(days=7)
CLOSE_AFTER_MISSES = 2

Action = Literal["touch", "reopen", "refresh", "attach", "insert"]
Freshness = Literal["fresh", "repost", "reopened", "refreshed", "recurring"]


def fingerprint(company_id: int, normalized_title: str, locations: list[Location]) -> str:
    keys = ",".join(sorted({loc.key() for loc in locations}))
    return hashlib.sha1(f"{company_id}|{normalized_title}|{keys}".encode()).hexdigest()


def ids_hash(ids: Iterable[str]) -> str:
    return hashlib.sha1("\n".join(sorted(ids)).encode()).hexdigest()


@dataclass(frozen=True)
class ExistingSource:
    """A job_sources row already stored for the incoming (source, source_job_id)."""

    job_id: str
    job_status: str
    job_first_seen_at: datetime
    source_posted_at: datetime | None


@dataclass(frozen=True)
class FingerprintMatch:
    """Most recently seen job with the incoming job's fingerprint."""

    job_id: str
    status: str
    last_seen_at: datetime
    repost_count: int


@dataclass(frozen=True)
class Decision:
    action: Action
    job_id: str | None = None
    freshness: Freshness | None = None
    repost_of: str | None = None
    repost_count: int = 0


def classify(
    existing: ExistingSource | None,
    incoming_posted_at: datetime | None,
    fp_match: FingerprintMatch | None,
    now: datetime,
) -> Decision:
    """Spec §4 freshness rules, evaluated in order."""
    if existing is not None:
        if existing.job_status == "closed":
            return Decision("reopen", job_id=existing.job_id, freshness="reopened")
        bumped = (
            incoming_posted_at is not None
            and existing.source_posted_at is not None
            and incoming_posted_at > existing.source_posted_at
        )
        if bumped and now - existing.job_first_seen_at > REFRESH_MIN_AGE:
            return Decision("refresh", job_id=existing.job_id, freshness="refreshed")
        return Decision("touch", job_id=existing.job_id)
    if fp_match is not None:
        if fp_match.status == "open":
            return Decision("attach", job_id=fp_match.job_id)
        if now - fp_match.last_seen_at <= REPOST_WINDOW:
            return Decision(
                "insert",
                freshness="repost",
                repost_of=fp_match.job_id,
                repost_count=fp_match.repost_count + 1,
            )
        return Decision("insert", freshness="recurring")
    return Decision("insert", freshness="fresh")


@dataclass(frozen=True)
class OpenJob:
    job_id: str
    miss_count: int
    source_job_ids: frozenset[str]


@dataclass
class ClosurePlan:
    reset: list[str] = field(default_factory=list)
    increment: list[str] = field(default_factory=list)
    close: list[str] = field(default_factory=list)


def plan_closures(open_jobs: list[OpenJob], seen_ids: set[str]) -> ClosurePlan:
    """A job is missing only if none of its source IDs (for this company+source) were seen."""
    plan = ClosurePlan()
    for job in open_jobs:
        if job.source_job_ids & seen_ids:
            if job.miss_count:
                plan.reset.append(job.job_id)
        elif job.miss_count + 1 >= CLOSE_AFTER_MISSES:
            plan.close.append(job.job_id)
        else:
            plan.increment.append(job.job_id)
    return plan
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_dedupe.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add scraper/normalize scraper/dedupe.py scraper/tests/test_dedupe.py
git commit -m "Add title normalization, fingerprinting and freshness classification"
```

---

### Task 4: Intern filter and category

**Files:**
- Create: `scraper/enrich/__init__.py` (empty for now), `scraper/enrich/category.py`, `scraper/tests/test_category.py`

**Interfaces:**
- Produces: `is_intern_title(title: str, employment_type: str | None = None) -> bool`, `categorize(title: str) -> str | None` (one of `Quant, PM, Design, Data/ML, Hardware/Embedded, IT/Security, SWE, Other-tech`; `None` = not tech → drop).

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_category.py`

```python
import pytest

from scraper.enrich.category import categorize, is_intern_title


@pytest.mark.parametrize(
    ("title", "employment", "expected"),
    [
        ("Software Engineer Intern", None, True),
        ("Software Engineering Internship - Summer 2027", None, True),
        ("Co-op Student, Data", None, True),
        ("PEY Co-op", None, True),
        ("Software Engineer Intern, Internal Tools", None, True),
        ("Product Manager Intern", None, True),
        ("Student Researcher", None, True),
        ("Software Engineer, Summer 2027", "Intern", True),
        ("Software Engineer, Summer 2027", "Internship", True),
        ("Senior Software Engineer", None, False),
        ("Sr. Intern Program Manager", None, False),
        ("Staff Engineer", None, False),
        ("Internal Audit Analyst", None, False),
        ("International Sales Lead", None, False),
        ("Student Success Manager", None, False),
        ("Software Engineer", "Full-time", False),
    ],
)
def test_is_intern_title(title, employment, expected):
    assert is_intern_title(title, employment) is expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineer Intern", "SWE"),
        ("Backend Developer Co-op", "SWE"),
        ("UI Engineer Intern", "SWE"),
        ("Quantum Computing Intern", "SWE"),
        ("Machine Learning Intern", "Data/ML"),
        ("Data Analyst Intern", "Data/ML"),
        ("Firmware Engineering Co-op", "Hardware/Embedded"),
        ("Mechanical Engineering Intern", "Hardware/Embedded"),
        ("Security Engineer Intern", "IT/Security"),
        ("IT Support Co-op", "IT/Security"),
        ("Product Manager Intern", "PM"),
        ("AI Product Manager Intern", "PM"),
        ("Product Design Intern", "Design"),
        ("UX Research Intern", "Design"),
        ("Quantitative Research Intern", "Quant"),
        ("Trading Intern", "Quant"),
        ("Technical Writer Intern", "Other-tech"),
        ("Marketing Intern", None),
        ("Civil Engineering Intern", None),
        ("Chemical Engineer Co-op", None),
    ],
)
def test_categorize(title, expected):
    assert categorize(title) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_category.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.enrich.category'`

- [ ] **Step 3: Implement** — `scraper/enrich/category.py`

```python
import re

_SENIOR = re.compile(r"\b(?:senior|sr|staff|principal|director|head|vp)\b", re.I)
_STRONG = re.compile(
    r"\b(?:interns?|internships?|co-?ops?|apprentices?|apprenticeships?)\b|(?-i:\bPEY\b)", re.I
)
_WEAK = re.compile(r"\b(?:students?|placements?)\b", re.I)
_NOT_STUDENT_ROLE = re.compile(
    r"\b(?:manager|coordinator|advisor|adviser|recruiter|success|services|officer|counsell?or)\b",
    re.I,
)
_INTERN_EMPLOYMENT = re.compile(r"intern|co-?op", re.I)


def is_intern_title(title: str, employment_type: str | None = None) -> bool:
    if _SENIOR.search(title):
        return False
    if _STRONG.search(title):
        return True
    if employment_type and _INTERN_EMPLOYMENT.search(employment_type):
        return True
    return bool(_WEAK.search(title)) and not _NOT_STUDENT_ROLE.search(title)


_NON_TECH_ENGINEERING = re.compile(
    r"\b(?:civil|chemical|structural|environmental|geotechnical|petroleum|mining|nuclear|"
    r"biomedical|process)\s+engineer",
    re.I,
)

# First match wins, so order matters (e.g. "Security Engineer" must hit IT/Security before SWE).
CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Quant", re.compile(r"\b(?:quant(?:itative)?|trading|trader)\b", re.I)),
    (
        "PM",
        re.compile(
            r"\b(?:product manag\w*|program manag\w*|technical program|apm)\b|(?-i:\bPM\b)", re.I
        ),
    ),
    (
        "Design",
        re.compile(
            r"\b(?:ux|ui/ux|ux/ui|user experience|product design\w*|designer|interaction design|"
            r"visual design)\b",
            re.I,
        ),
    ),
    (
        "Data/ML",
        re.compile(
            r"\b(?:data|machine learning|ml|ai|artificial intelligence|analytics|deep learning|"
            r"nlp|computer vision|research scientist|applied scientist)\b",
            re.I,
        ),
    ),
    (
        "Hardware/Embedded",
        re.compile(
            r"\b(?:hardware|embedded|firmware|fpga|asic|silicon|electrical|electronics?|circuits?|"
            r"rtl|robotics|mechatronics|mechanical|manufacturing)\b",
            re.I,
        ),
    ),
    (
        "IT/Security",
        re.compile(
            r"\b(?:security|cyber\w*|infosec|network\w*|help ?desk|systems? admin\w*)\b"
            r"|(?-i:\bIT\b)",
            re.I,
        ),
    ),
    (
        "SWE",
        re.compile(
            r"\b(?:software|developer|engineer\w*|swe|sde|back-?end|front-?end|full[- ]?stack|"
            r"mobile|ios|android|devops|sre|site reliability|platform|infrastructure|cloud|web|"
            r"programmer|qa|quality assurance|test automation|computer science|computing)\b",
            re.I,
        ),
    ),
    ("Other-tech", re.compile(r"\b(?:technical|technology|tech|solutions|developer relations)\b", re.I)),
]


def categorize(title: str) -> str | None:
    if _NON_TECH_ENGINEERING.search(title):
        return None
    for category, pattern in CATEGORY_RULES:
        if pattern.search(title):
            return category
    return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_category.py -v`
Expected: 36 passed. If a case fails, adjust the regex — not the test — unless the test contradicts the spec.

- [ ] **Step 5: Commit**

```bash
git add scraper/enrich scraper/tests/test_category.py
git commit -m "Add intern title filter and tech category rules"
```

---

### Task 5: Location parsing

**Files:**
- Create: `scraper/normalize/geo.py`, `scraper/normalize/location.py`, `scraper/tests/test_location.py`

**Interfaces:**
- Consumes: `Location`, `ParsedLocation` (Task 1).
- Produces: `parse_location(raw: str, country_hint: str | None = None, work_mode_hint: str | None = None, default_country: str | None = None) -> ParsedLocation`.

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_location.py`

```python
import pytest

from scraper.models import Location
from scraper.normalize.location import parse_location


@pytest.mark.parametrize(
    ("raw", "country", "locs"),
    [
        ("Toronto, ON", "CA", [("Toronto", "ON", "CA")]),
        ("New York, NY", "US", [("New York", "NY", "US")]),
        ("London, ON", "CA", [("London", "ON", "CA")]),
        ("Toronto, ON; New York, NY", "BOTH", [("Toronto", "ON", "CA"), ("New York", "NY", "US")]),
        ("San Francisco, CA | Toronto, ON", "BOTH", [("San Francisco", "CA", "US"), ("Toronto", "ON", "CA")]),
        ("Waterloo, Ontario, Canada", "CA", [("Waterloo", "ON", "CA")]),
        ("Seattle", "US", [("Seattle", "WA", "US")]),
        ("Hybrid - Vancouver, BC", "CA", [("Vancouver", "BC", "CA")]),
        ("Remote - Canada", "CA", [(None, None, "CA")]),
        ("Remote (US)", "US", [(None, None, "US")]),
        ("Remote, United States", "US", [(None, None, "US")]),
        ("Canada or United States", "BOTH", [(None, None, "CA"), (None, None, "US")]),
        (
            "New York, San Francisco, Seattle",
            "US",
            [("New York", "NY", "US"), ("San Francisco", "CA", "US"), ("Seattle", "WA", "US")],
        ),
        ("London, UK; Toronto, ON", "CA", [("Toronto", "ON", "CA")]),
    ],
)
def test_parse_known_locations(raw, country, locs):
    parsed = parse_location(raw)
    assert parsed.country == country
    assert parsed.locations == [Location(city=c, region=r, country=k) for c, r, k in locs]
    assert not parsed.foreign_only and not parsed.location_unclear


@pytest.mark.parametrize("raw", ["London, UK", "Bangalore, India", "Berlin, DE", "London"])
def test_foreign_only_locations_flagged(raw):
    parsed = parse_location(raw)
    assert parsed.foreign_only is True


def test_non_ca_us_country_hint_is_foreign():
    assert parse_location("", country_hint="GB").foreign_only is True
    assert parse_location("Remote", country_hint="OTHER").foreign_only is True


def test_bare_remote_is_unclear_without_hints():
    parsed = parse_location("Remote")
    assert parsed.country == "UNKNOWN"
    assert parsed.location_unclear is True
    assert parsed.work_mode == "remote"


def test_bare_remote_uses_country_hint_then_default():
    assert parse_location("Remote", country_hint="US").country == "US"
    assert parse_location("Remote", default_country="CA").country == "CA"


def test_work_modes():
    assert parse_location("Toronto, ON").work_mode == "onsite"
    assert parse_location("Toronto, ON (Hybrid)").work_mode == "hybrid"
    assert parse_location("Remote - US").work_mode == "remote"
    assert parse_location("Toronto, ON", work_mode_hint="remote").work_mode == "remote"
    assert parse_location("").work_mode == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_location.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.normalize.location'`

- [ ] **Step 3: Implement** — `scraper/normalize/geo.py`

```python
import re

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}  # fmt: skip

CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}  # fmt: skip

# Lowercase city -> (region code, country). Only unambiguous, commonly-posted tech cities.
KNOWN_CITIES = {
    "toronto": ("ON", "CA"), "waterloo": ("ON", "CA"), "kitchener": ("ON", "CA"),
    "ottawa": ("ON", "CA"), "mississauga": ("ON", "CA"), "markham": ("ON", "CA"),
    "montreal": ("QC", "CA"), "montréal": ("QC", "CA"), "quebec city": ("QC", "CA"),
    "vancouver": ("BC", "CA"), "burnaby": ("BC", "CA"), "calgary": ("AB", "CA"),
    "edmonton": ("AB", "CA"), "winnipeg": ("MB", "CA"), "halifax": ("NS", "CA"),
    "new york": ("NY", "US"), "new york city": ("NY", "US"), "nyc": ("NY", "US"),
    "brooklyn": ("NY", "US"), "jersey city": ("NJ", "US"), "san francisco": ("CA", "US"),
    "sf": ("CA", "US"), "bay area": ("CA", "US"), "san francisco bay area": ("CA", "US"),
    "mountain view": ("CA", "US"), "palo alto": ("CA", "US"), "menlo park": ("CA", "US"),
    "sunnyvale": ("CA", "US"), "san jose": ("CA", "US"), "cupertino": ("CA", "US"),
    "san mateo": ("CA", "US"), "santa clara": ("CA", "US"), "los angeles": ("CA", "US"),
    "san diego": ("CA", "US"), "seattle": ("WA", "US"), "redmond": ("WA", "US"),
    "bellevue": ("WA", "US"), "boston": ("MA", "US"), "austin": ("TX", "US"),
    "dallas": ("TX", "US"), "houston": ("TX", "US"), "chicago": ("IL", "US"),
    "denver": ("CO", "US"), "atlanta": ("GA", "US"), "pittsburgh": ("PA", "US"),
    "philadelphia": ("PA", "US"), "miami": ("FL", "US"), "salt lake city": ("UT", "US"),
    "portland": ("OR", "US"), "raleigh": ("NC", "US"), "washington dc": ("DC", "US"),
}  # fmt: skip

FOREIGN_RE = re.compile(
    r"\b(?:uk|united kingdom|england|scotland|london|dublin|ireland|germany|berlin|munich|"
    r"france|paris|netherlands|amsterdam|spain|madrid|barcelona|portugal|lisbon|italy|milan|"
    r"poland|warsaw|switzerland|zurich|sweden|stockholm|denmark|copenhagen|norway|finland|"
    r"india|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|singapore|japan|"
    r"tokyo|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|korea|seoul|australia|"
    r"sydney|melbourne|new zealand|israel|tel aviv|brazil|são paulo|sao paulo|mexico|"
    r"argentina|buenos aires|colombia|bogota|philippines|manila|vietnam|indonesia|uae|dubai|"
    r"emea|apac|latam|europe)\b",
    re.I,
)
```

`scraper/normalize/location.py`:
```python
import re

from scraper.models import Location, ParsedLocation
from scraper.normalize.geo import CA_PROVINCES, FOREIGN_RE, KNOWN_CITIES, US_STATES

_SPLIT = re.compile(r"\s*(?:;|\||\n|\s/\s|\sor\s|\s&\s)\s*", re.I)
_CITY_CODE = re.compile(r"^\s*(?P<city>[^,()]+?)\s*,\s*(?P<code>[A-Z]{2})\b")
_MODE_PREFIX = re.compile(r"^(?:remote|hybrid|on-?site)\s*[-–:]\s*", re.I)
_REMOTE = re.compile(r"\bremote\b|\bwork from home\b|\bwfh\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_CANADA = re.compile(r"\bcanada\b", re.I)
_USA = re.compile(r"\bunited states\b|\busa\b|(?<!\w)u\.s\.(?:a\.)?|(?-i:\bUS\b)", re.I)

_CA_NAMES = {name.lower(): code for code, name in CA_PROVINCES.items()} | {"québec": "QC"}
_US_NAMES = {name.lower(): code for code, name in US_STATES.items()}
_REGION_NAME = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _CA_NAMES | _US_NAMES), key=len, reverse=True)) + r")\b",
    re.I,
)
_KNOWN_CITY = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, KNOWN_CITIES), key=len, reverse=True)) + r")\b", re.I
)


def _clean_city(city: str) -> str | None:
    city = _MODE_PREFIX.sub("", city).strip(" -–")
    if not city or _REMOTE.search(city) or _CANADA.search(city) or _USA.search(city):
        return None
    if _REGION_NAME.fullmatch(city):
        return None
    return city


def _city_before(seg: str) -> str | None:
    return _clean_city(re.split(r"[,(]", seg, maxsplit=1)[0])


def _parse_segment(seg: str) -> tuple[list[Location], bool]:
    """Returns (locations, is_foreign). No locations and not foreign means unclear."""
    if m := _CITY_CODE.match(seg):
        city, code = m.group("city"), m.group("code")
        if code in CA_PROVINCES:
            return [Location(city=_clean_city(city), region=code, country="CA")], False
        foreign_city = FOREIGN_RE.search(city) and city.strip().lower() not in KNOWN_CITIES
        if code in US_STATES and not foreign_city:
            return [Location(city=_clean_city(city), region=code, country="US")], False

    parts = [p.strip() for p in seg.split(",") if p.strip()]
    if len(parts) > 1 and all(p.lower() in KNOWN_CITIES for p in parts):
        return [
            Location(city=p, region=KNOWN_CITIES[p.lower()][0], country=KNOWN_CITIES[p.lower()][1])
            for p in parts
        ], False

    if m := _REGION_NAME.search(seg):
        key = m.group(1).lower()
        if key in _CA_NAMES:
            return [Location(city=_city_before(seg), region=_CA_NAMES[key], country="CA")], False
        return [Location(city=_city_before(seg), region=_US_NAMES[key], country="US")], False

    if m := _KNOWN_CITY.search(seg):
        region, country = KNOWN_CITIES[m.group(1).lower()]
        return [Location(city=_clean_city(m.group(1)), region=region, country=country)], False

    in_ca, in_us = bool(_CANADA.search(seg)), bool(_USA.search(seg))
    if in_ca or in_us:
        return [Location(country=c) for c, hit in (("CA", in_ca), ("US", in_us)) if hit], False
    return [], bool(FOREIGN_RE.search(seg))


def _work_mode(raw: str, hint: str | None, has_city: bool) -> str:
    if hint:
        return hint
    if _HYBRID.search(raw):
        return "hybrid"
    if _REMOTE.search(raw):
        return "remote"
    return "onsite" if has_city else "unknown"


def parse_location(
    raw: str,
    country_hint: str | None = None,
    work_mode_hint: str | None = None,
    default_country: str | None = None,
) -> ParsedLocation:
    segments = [s for s in _SPLIT.split(raw or "") if s.strip()]
    found: dict[str, Location] = {}
    foreign: list[bool] = []
    for seg in segments:
        locs, is_foreign = _parse_segment(seg)
        foreign.append(is_foreign)
        for loc in locs:
            found.setdefault(loc.key(), loc)
    locations = list(found.values())
    mode = _work_mode(raw or "", work_mode_hint, any(loc.city for loc in locations))

    if not locations:
        hint = (country_hint or "").upper()
        if hint in ("CA", "US"):
            locations = [Location(country=hint)]
        elif hint or (foreign and all(foreign)):
            return ParsedLocation(country="UNKNOWN", work_mode=mode, foreign_only=True)
        elif default_country in ("CA", "US"):
            locations = [Location(country=default_country)]
        else:
            return ParsedLocation(country="UNKNOWN", work_mode=mode, location_unclear=True)

    countries = {loc.country for loc in locations}
    country = "BOTH" if countries == {"CA", "US"} else next(iter(countries))
    return ParsedLocation(locations=locations, country=country, work_mode=mode)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_location.py -v`
Expected: all pass. If one fails, read the parse order in `_parse_segment` (code → known-city list → region name → known city → country words → foreign) and fix the parser, not the expectation.

- [ ] **Step 5: Commit**

```bash
git add scraper/normalize scraper/tests/test_location.py
git commit -m "Add Canada/US location parsing with foreign-location detection"
```

---

### Task 6: Term parsing

**Files:**
- Create: `scraper/normalize/term.py`, `scraper/tests/test_term.py`

**Interfaces:**
- Produces: `parse_term(title: str, text: str) -> tuple[str | None, int | None]` → (`term` label, `duration_months`).

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_term.py`

```python
import pytest

from scraper.normalize.term import parse_term


@pytest.mark.parametrize(
    ("title", "text", "expected"),
    [
        ("Software Engineer Intern (Summer 2027)", "", ("Summer 2027", None)),
        ("Software Intern", "This is a Fall 2026 internship.", ("Fall 2026", None)),
        ("Intern - Autumn 2026", "", ("Fall 2026", None)),
        ("Software Engineer Co-op (4 months)", "", ("4-month", 4)),
        ("Co-op, Winter 2027 (8-month)", "", ("Winter 2027 · 8-month", 8)),
        ("Data Intern", "This is a 12-16 month co-op placement.", ("12–16-month", 12)),
        ("PEY Co-op Student", "", ("PEY", 12)),
        ("Software Intern", "Requires 6 months of experience with Python.", (None, None)),
        ("Software Intern", "", (None, None)),
    ],
)
def test_parse_term(title, text, expected):
    assert parse_term(title, text) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_term.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `scraper/normalize/term.py`

```python
import re

_SEASON = re.compile(r"\b(summer|fall|autumn|winter|spring)\s*(?:term\s*)?[,'’]?\s*(20\d\d)\b", re.I)
_MONTHS = r"\b(\d{1,2})(?:\s*(?:-|–|to|/)\s*(\d{1,2}))?[- ]months?\b"
_MONTHS_TITLE = re.compile(_MONTHS, re.I)
# In descriptions, only count durations attached to the role ("6 months of experience" doesn't).
_MONTHS_DESC = re.compile(
    _MONTHS + r"\s+(?:co-?op|intern(?:ship)?|work term|placement|term|contract)", re.I
)
_PEY = re.compile(r"(?-i:\bPEY\b)|professional experience year", re.I)


def parse_term(title: str, text: str) -> tuple[str | None, int | None]:
    term: str | None = None
    if season := (_SEASON.search(title) or _SEASON.search(text)):
        name = season.group(1).lower()
        term = f"{'Fall' if name == 'autumn' else name.title()} {season.group(2)}"

    duration: int | None = None
    label: str | None = None
    months = _MONTHS_TITLE.search(title) or _MONTHS_DESC.search(text)
    if months and 2 <= int(months.group(1)) <= 18:
        lo, hi = int(months.group(1)), months.group(2)
        duration = lo
        label = f"{lo}–{hi}-month" if hi else f"{lo}-month"
    elif _PEY.search(title) or _PEY.search(text):
        duration, label = 12, "PEY"

    if label:
        term = f"{term} · {label}" if term else label
    return term, duration
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_term.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add scraper/normalize/term.py scraper/tests/test_term.py
git commit -m "Add internship term and duration parsing"
```

---

### Task 7: Pay parsing

**Files:**
- Create: `scraper/normalize/pay.py`, `scraper/tests/test_pay.py`

**Interfaces:**
- Consumes: `Pay`, `PayRange` (Task 1).
- Produces: `parse_pay(text: str, structured: PayRange | None, country: str) -> Pay | None`, `hourly(value: float, period: str) -> float`.

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_pay.py`

```python
import pytest

from scraper.models import PayRange
from scraper.normalize.pay import parse_pay


def p(text, country="US", structured=None):
    return parse_pay(text, structured, country)


def test_hourly_range_usd():
    pay = p("The hourly rate for this role is $28 - $35 per hour.")
    assert (pay.min, pay.max, pay.currency, pay.period) == (28, 35, "USD", "hour")
    assert (pay.hourly_min, pay.hourly_max) == (28, 35)
    assert pay.raw == "$28 - $35 per hour"


def test_annual_cad_with_hourly_equivalent():
    pay = p("Compensation: CA$70,000–CA$85,000 annually.", country="CA")
    assert (pay.min, pay.max, pay.currency, pay.period) == (70000, 85000, "CAD", "year")
    assert (pay.hourly_min, pay.hourly_max) == (33.65, 40.87)


def test_k_suffix_with_period_from_preceding_text():
    pay = p("Salary range: $80k-$100k")
    assert (pay.min, pay.max, pay.period) == (80000, 100000, "year")


def test_single_value_per_hr():
    pay = p("Pay: $45/hr")
    assert (pay.min, pay.max, pay.period) == (45, 45, "hour")


def test_canada_job_defaults_to_cad():
    assert p("Pay: $30 – $40 hourly", country="CA").currency == "CAD"


def test_monthly():
    pay = p("The base salary range is $8,000 - $9,000 per month.")
    assert (pay.period, pay.hourly_min, pay.hourly_max) == ("month", 46.16, 51.93)


def test_no_period_small_values_with_pay_word_are_hourly():
    assert p("Pay range: $25 - $30").period == "hour"


def test_decimal_values():
    assert p("$28.50 per hour").min == 28.5


@pytest.mark.parametrize(
    "text",
    [
        "We raised a $50M Series B last year.",
        "You'll receive a $5,000 relocation stipend.",
        "Enjoy a $100 monthly learning budget",
        "No pay listed here.",
    ],
)
def test_non_pay_dollar_amounts_ignored(text):
    assert p(text) is None


def test_structured_pay_preferred():
    s = PayRange(min=32, max=40, currency="CAD", period="hour")
    pay = p("Pay is $99 per hour", country="CA", structured=s)
    assert (pay.min, pay.max, pay.currency, pay.raw) == (32, 40, "CAD", "CAD 32–40 per hour")


def test_structured_missing_currency_uses_country_default():
    s = PayRange(min=80000, max=None, currency=None, period="year")
    pay = p("", country="CA", structured=s)
    assert (pay.min, pay.max, pay.currency) == (80000, 80000, "CAD")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_pay.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `scraper/normalize/pay.py`

```python
import re

from scraper.models import Pay, PayRange

_HOURS = {"hour": 1.0, "week": 40.0, "month": 173.3, "year": 2080.0}
_PLAUSIBLE = {"hour": (10, 500), "week": (300, 10_000), "month": (1_000, 20_000), "year": (10_000, 1_000_000)}

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_CUR = r"CA\$|C\$|US\$|\$"
_PAY_RE = re.compile(
    rf"(?P<cur>{_CUR})\s?(?P<a>{_NUM})\s?(?P<ak>[kK]\b)?(?:\s*(?:USD|CAD))?"
    rf"(?:\s*(?:-|–|—|to)\s*(?:{_CUR})?\s?(?P<b>{_NUM})\s?(?P<bk>[kK]\b)?)?"
)
_NOT_PAY_SUFFIX = re.compile(r"^\s*(?:m|mm|b|bn|million|billion)\b", re.I)
_PERIODS = [
    ("hour", re.compile(r"/\s*h(?:ou)?r\b|per\s+hour|hourly|an\s+hour", re.I)),
    ("year", re.compile(r"/\s*y(?:ea)?r\b|per\s+(?:year|annum)|annual(?:ly)?|a\s+year|salary", re.I)),
    ("month", re.compile(r"/\s*mo(?:nth)?\b|per\s+month|monthly|a\s+month", re.I)),
    ("week", re.compile(r"/\s*w(?:ee)?k\b|per\s+week|weekly|a\s+week", re.I)),
]
_PAY_WORD = re.compile(r"\b(?:pay|salary|compensation|wages?|rate|range)\b", re.I)


def hourly(value: float, period: str) -> float:
    return round(value / _HOURS[period], 2)


def _default_currency(country: str) -> str:
    return "CAD" if country == "CA" else "USD"


def _num(s: str, k: str | None) -> float:
    v = float(s.replace(",", ""))
    return v * 1000 if k else v


def _find_period(s: str) -> tuple[str, re.Match[str]] | None:
    for period, pattern in _PERIODS:
        if m := pattern.search(s):
            return period, m
    return None


def _from_structured(s: PayRange, country: str) -> Pay | None:
    lo, hi = s.min if s.min is not None else s.max, s.max if s.max is not None else s.min
    if lo is None or hi is None or s.period is None:
        return None
    cur = (s.currency or _default_currency(country)).upper()
    return Pay(
        min=lo, max=hi, currency=cur, period=s.period,
        hourly_min=hourly(lo, s.period), hourly_max=hourly(hi, s.period),
        raw=f"{cur} {lo:g}–{hi:g} per {s.period}",
    )  # fmt: skip


def parse_pay(text: str, structured: PayRange | None, country: str) -> Pay | None:
    if structured is not None and (pay := _from_structured(structured, country)):
        return pay
    for m in _PAY_RE.finditer(text):
        tail = text[m.end() : m.end() + 40]
        if _NOT_PAY_SUFFIX.match(tail):
            continue
        lo = _num(m.group("a"), m.group("ak"))
        hi = _num(m.group("b"), m.group("bk") or m.group("ak")) if m.group("b") else lo
        if lo > hi:
            lo, hi = hi, lo

        raw_end = m.end()
        found = _find_period(tail)
        if found:
            period, pm = found
            raw_end = m.end() + pm.end()
        else:
            head = text[max(0, m.start() - 60) : m.start()]
            found = _find_period(head)
            if found:
                period = found[0]
            else:
                line_start = text.rfind("\n", 0, m.start()) + 1
                if not _PAY_WORD.search(text[line_start : m.end() + 40]):
                    continue
                if hi < 200:
                    period = "hour"
                elif lo > 10_000:
                    period = "year"
                else:
                    continue
        if period == "year" and hi < 1000:
            period = "hour"

        low_ok, high_ok = _PLAUSIBLE[period]
        if not (low_ok <= lo and hi <= high_ok):
            continue

        cur_sym = m.group("cur")
        window = text[m.start() : m.end() + 12]
        if cur_sym in ("CA$", "C$") or "CAD" in window:
            currency = "CAD"
        elif cur_sym == "US$" or "USD" in window:
            currency = "USD"
        else:
            currency = _default_currency(country)
        return Pay(
            min=lo, max=hi, currency=currency, period=period,
            hourly_min=hourly(lo, period), hourly_max=hourly(hi, period),
            raw=text[m.start() : raw_end].strip(),
        )  # fmt: skip
    return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_pay.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scraper/normalize/pay.py scraper/tests/test_pay.py
git commit -m "Add pay parsing with hourly normalization"
```

---

### Task 8: Visa signals and status

**Files:**
- Create: `scraper/enrich/visa.py`, `scraper/tests/test_visa.py`

**Interfaces:**
- Consumes: `sentence_at` (Task 2).
- Produces: `detect_visa_signals(text: str) -> dict[str, str]` (signal → evidence sentence), `visa_status(signals: Iterable[str], country: str, profile: Profile = OWNER_PROFILE) -> str`, `Profile(authorized_countries: frozenset[str])`, `OWNER_PROFILE`, `BLOCKING_SIGNALS`.

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_visa.py`

```python
import pytest

from scraper.enrich.visa import detect_visa_signals, visa_status


@pytest.mark.parametrize(
    ("text", "signal"),
    [
        ("We are unable to sponsor visas for this role.", "no_sponsorship"),
        ("We do not sponsor work visas.", "no_sponsorship"),
        ("We don't offer visa sponsorship for interns.", "no_sponsorship"),
        ("Must be authorized to work in the US without current or future sponsorship.", "no_sponsorship"),
        ("Sponsorship is not available for this position.", "no_sponsorship"),
        ("Applicants must be a U.S. citizen.", "us_citizen_only"),
        ("U.S. citizenship is required.", "us_citizen_only"),
        ("Open to US citizens or green card holders only.", "us_citizen_only"),
        ("This role is subject to ITAR.", "us_citizen_only"),
        ("This position requires an active Secret clearance.", "clearance"),
        ("Candidates must obtain a security clearance.", "clearance"),
        ("Must be enrolled at a U.S. university.", "us_school_required"),
        ("F-1 students with CPT authorization are welcome.", "us_school_required"),
        ("Visa sponsorship is available for this role.", "sponsors"),
        ("We will sponsor J-1 visas for interns.", "sponsors"),
        ("International students are welcome to apply.", "sponsors"),
        ("Must be enrolled in a co-op program at a Canadian university.", "canadian_coop_required"),
    ],
)
def test_detects_signal(text, signal):
    assert signal in detect_visa_signals(text)


def test_evidence_is_the_matching_sentence():
    signals = detect_visa_signals("Great team. We will not sponsor visas. Apply now.")
    assert signals == {"no_sponsorship": "We will not sponsor visas."}


def test_no_false_positives_on_neutral_text():
    text = "We offer great opportunities. Secrets management experience is a plus. Apply now."
    assert detect_visa_signals(text) == {}


def test_not_available_is_not_sponsors():
    assert "sponsors" not in detect_visa_signals("Visa sponsorship is not available.")


@pytest.mark.parametrize(
    ("signals", "country", "status"),
    [
        ({"no_sponsorship"}, "US", "blocked"),
        ({"sponsors"}, "US", "open"),
        ({"sponsors", "no_sponsorship"}, "US", "blocked"),
        (set(), "US", "unknown"),
        ({"clearance"}, "UNKNOWN", "blocked"),
        ({"no_sponsorship"}, "CA", "open"),
        ({"canadian_coop_required"}, "CA", "open"),
        ({"us_citizen_only"}, "BOTH", "open"),
    ],
)
def test_visa_status_for_owner(signals, country, status):
    assert visa_status(signals, country) == status
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_visa.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `scraper/enrich/visa.py`

```python
import re
from collections.abc import Iterable
from dataclasses import dataclass

from scraper.text import sentence_at

_US = r"(?:U\.?S\.?|United\s+States)"

VISA_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "no_sponsorship",
        re.compile(
            r"\b(?:will|do|does|can|are|is)\s*(?:not|n['’]t)\s+(?:be\s+)?(?:able\s+to\s+)?"
            r"(?:offer\s+|provide\s+)?(?:visa\s+|immigration\s+)?sponsor"
            r"|\bunable\s+to\s+(?:offer\s+|provide\s+|support\s+)?(?:visa\s+|immigration\s+)?sponsor"
            r"|\bnot\s+(?:able|eligible)\s+to\s+(?:provide|offer|receive)\s+"
            r"(?:visa\s+|immigration\s+)?sponsorship"
            r"|\bwithout\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+|now\s+or\s+in\s+"
            r"the\s+future\s+)?(?:visa\s+|employment\s+|immigration\s+|work\s+)?sponsorship"
            r"|\bno\s+(?:visa\s+|immigration\s+)?sponsorship"
            r"|\bsponsorship\s+(?:is\s+|will\s+)?not\s+(?:be\s+)?(?:available|provided|offered)"
            r"|\bsponsorship[^.]{0,60}\bnot\s+eligible|\bnot\s+eligible[^.]{0,60}\bsponsorship",
            re.I,
        ),
    ),
    (
        "us_citizen_only",
        re.compile(
            rf"\bmust\s+be\s+(?:a\s+)?{_US}\s+citizens?"
            rf"|\b{_US}\s+citizenship\s+(?:is\s+)?required|\brequires?\s+{_US}\s+citizenship"
            rf"|\b{_US}\s+citizens?\s+(?:or\s+green\s+card\s+holders\s+)?only"
            rf"|\b{_US}\s+persons?\b|\bgreen\s+card\b"
            rf"|\b{_US}\s+(?:lawful\s+)?permanent\s+residen"
            r"|(?-i:\bITAR\b)|\bexport\s+control",
            re.I,
        ),
    ),
    (
        "clearance",
        re.compile(
            r"\bsecurity\s+clearance|\btop\s+secret\b|(?-i:\bTS/SCI\b)"
            r"|\bsecret\s+(?:level\s+)?clearance|\breliability\s+status\b",
            re.I,
        ),
    ),
    (
        "us_school_required",
        re.compile(
            rf"\benrolled\s+(?:at|in)\s+(?:an?\s+)?(?:accredited\s+)?{_US}(?:[-\s]based)?\s+"
            r"(?:college|university|institution|school)"
            r"|(?-i:\b(?:CPT|OPT)\b)",
            re.I,
        ),
    ),
    (
        "sponsors",
        re.compile(
            r"\b(?:visa\s+|immigration\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided)\b"
            r"|\bwe\s+(?:will|can|do)\s+sponsor"
            r"|(?-i:\bJ-?1\b)"
            r"|\binternational\s+(?:students|candidates|applicants)\s+(?:are\s+)?"
            r"(?:welcome|encouraged)"
            r"|\bopen\s+to\s+(?:candidates|applicants)\s+(?:who\s+)?(?:require|requiring|need|"
            r"needing)\s+(?:visa\s+)?sponsorship",
            re.I,
        ),
    ),
    (
        "canadian_coop_required",
        re.compile(
            r"\bco-?op\s+(?:program|students?|term)[^.]{0,60}\bcanad"
            r"|\benrolled[^.]{0,60}\bcanadian\s+(?:post-?secondary\s+)?"
            r"(?:university|institution|college|school)"
            r"|\bcanad\w*[^.]{0,40}\bco-?op\s+program",
            re.I,
        ),
    ),
]

BLOCKING_SIGNALS = frozenset({"no_sponsorship", "us_citizen_only", "clearance", "us_school_required"})


@dataclass(frozen=True)
class Profile:
    authorized_countries: frozenset[str]


OWNER_PROFILE = Profile(authorized_countries=frozenset({"CA"}))


def detect_visa_signals(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for signal, pattern in VISA_PATTERNS:
        if m := pattern.search(text):
            found[signal] = sentence_at(text, m.start())
    return found


def visa_status(signals: Iterable[str], country: str, profile: Profile = OWNER_PROFILE) -> str:
    """Status for `profile`. UNKNOWN country is judged like a country the profile needs a visa for."""
    if country in profile.authorized_countries:
        return "open"
    if country == "BOTH" and profile.authorized_countries & {"CA", "US"}:
        return "open"
    s = set(signals)
    if s & BLOCKING_SIGNALS:
        return "blocked"
    if "sponsors" in s:
        return "open"
    return "unknown"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_visa.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scraper/enrich/visa.py scraper/tests/test_visa.py
git commit -m "Add visa signal detection and owner visa status"
```

---

### Task 9: Flags and the enrich() orchestrator

**Files:**
- Create: `scraper/enrich/flags.py`, `scraper/tests/test_flags.py`, `scraper/tests/test_enrich.py`
- Modify: `scraper/enrich/__init__.py` (currently empty)

**Interfaces:**
- Consumes: everything from Tasks 2–8.
- Produces: `detect_flags(title: str, text: str, pay: Pay | None, location: ParsedLocation) -> dict[str, str]`; `enrich(raw: RawJob, company_id: int, default_country: str | None = None) -> EnrichedJob | None` (None = not a tech internship in CA/US).

- [ ] **Step 1: Write the failing tests**

`scraper/tests/test_flags.py`:
```python
from scraper.enrich.flags import detect_flags
from scraper.models import ParsedLocation

ONSITE = ParsedLocation(country="CA", work_mode="onsite")


def flags(title="Software Engineer Intern", text="", location=ONSITE):
    return detect_flags(title, text, None, location)


def test_work_mode_flags():
    assert "remote" in flags(location=ParsedLocation(country="US", work_mode="remote"))
    assert "hybrid" in flags(location=ParsedLocation(country="US", work_mode="hybrid"))
    assert "remote" not in flags()


def test_grad_year():
    f = flags(text="Candidates graduating in May 2028 are preferred.")
    assert f["grad_year:2028"] == "Candidates graduating in May 2028 are preferred."


def test_grad_students_only_from_title_and_text():
    assert "grad_students_only" in flags(title="Research Intern (PhD)")
    assert "grad_students_only" in flags(text="You must be currently pursuing a Master's degree.")
    assert "grad_students_only" not in flags(text="Bachelor's or Master's students welcome.")


def test_early_years_only():
    assert "early_years_only" in flags(title="STEP Intern")
    assert "early_years_only" in flags(text="Open to first-year and second-year students.")
    assert "early_years_only" not in flags(title="Step Functions Intern")


def test_eligibility_restricted_and_relocation():
    f = flags(text="This program is designed for students from underrepresented groups. "
                   "Relocation assistance is provided.")
    assert "eligibility_restricted" in f
    assert f["relocation"] == "Relocation assistance is provided."
```

`scraper/tests/test_enrich.py`:
```python
from scraper.enrich import enrich
from scraper.models import PayRange, RawJob


def raw(**kw):
    base = dict(source="greenhouse", source_job_id="1", title="Software Engineer Intern",
                url="https://x/1", location_raw="Toronto, ON")
    return RawJob(**(base | kw))


def test_canadian_intern_with_pay_and_term():
    job = enrich(
        raw(title="Software Engineer Intern (Summer 2027)",
            description_text="Join our team.\nThe hourly rate is CA$30 - CA$38 per hour."),
        company_id=7,
    )
    assert job is not None
    assert (job.category, job.location.country, job.term) == ("SWE", "CA", "Summer 2027")
    assert (job.pay.min, job.pay.max, job.pay.currency) == (30, 38, "CAD")
    assert job.visa_status == "open"
    assert "pay_listed" in job.flags
    assert job.normalized_title == "software engineer intern"
    assert job.company_id == 7 and len(job.fingerprint) == 40


def test_us_intern_without_sponsorship_is_blocked_with_evidence():
    job = enrich(raw(title="Data Science Intern", location_raw="New York, NY",
                     description_text="We will not sponsor visas for this role."), company_id=1)
    assert job.visa_status == "blocked"
    assert job.visa_signals == ["no_sponsorship"]
    assert job.evidence["no_sponsorship"] == "We will not sponsor visas for this role."


def test_title_counts_for_visa_signals():
    job = enrich(raw(title="Software Intern (US Citizens Only)", location_raw="Austin, TX"), 1)
    assert job.visa_status == "blocked"


def test_non_intern_and_non_tech_dropped():
    assert enrich(raw(title="Senior Account Executive"), 1) is None
    assert enrich(raw(title="Marketing Intern"), 1) is None


def test_foreign_only_dropped():
    assert enrich(raw(location_raw="London", country_hint="OTHER"), 1) is None
    assert enrich(raw(location_raw="Bangalore, India"), 1) is None


def test_structured_pay_and_hints_flow_through():
    job = enrich(raw(location_raw="Remote", country_hint="US", work_mode_hint="remote",
                     pay_structured=PayRange(min=50, max=60, currency="USD", period="hour")), 1)
    assert job.location.country == "US" and "remote" in job.flags
    assert job.pay.hourly_max == 60


def test_default_country_used_for_bare_remote():
    job = enrich(raw(location_raw="Remote"), 1, default_country="CA")
    assert job.location.country == "CA" and not job.location.location_unclear
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest scraper/tests/test_flags.py scraper/tests/test_enrich.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'enrich'`

- [ ] **Step 3: Implement** — `scraper/enrich/flags.py`

```python
import re

from scraper.models import ParsedLocation, Pay
from scraper.text import sentence_at

_TITLE_GRAD = re.compile(r"\b(?:ph\.?\s?d|master['’]?s|msc)\b|\bm\.s\.", re.I)
_TITLE_EARLY = re.compile(r"(?-i:\bSTEP\b)|\b(?:first|second)[- ]year\b|\bfreshman\b|\bsophomore\b", re.I)
_GRAD_YEAR = re.compile(r"\bgraduat\w*[^.\n]{0,40}?\b(20\d\d)\b", re.I)
_YEAR = re.compile(r"\b20\d\d\b")

TEXT_FLAGS: list[tuple[str, re.Pattern[str]]] = [
    (
        "grad_students_only",
        re.compile(
            r"(?:must|required\s+to)\s+be\s+(?:currently\s+)?(?:pursuing|enrolled\s+in)\s+an?\s+"
            r"(?:ph\.?\s?d|master['’]?s|graduate)",
            re.I,
        ),
    ),
    (
        "early_years_only",
        re.compile(
            r"\b(?:first|second|1st|2nd)[- ]year\s+(?:and\s+(?:first|second|1st|2nd)[- ]year\s+)?"
            r"(?:undergraduate\s+)?students?\b|\bfreshm[ae]n\b|\bsophomores?\b",
            re.I,
        ),
    ),
    (
        "eligibility_restricted",
        re.compile(
            r"\b(?:open\s+only\s+to|exclusively\s+for|must\s+(?:self-)?identify\s+as|"
            r"(?:program|internship)\s+(?:is\s+)?(?:designed|intended)\s+(?:specifically\s+)?for)\b",
            re.I,
        ),
    ),
    (
        "relocation",
        re.compile(
            r"\brelocation\s+(?:assistance|support|stipend|package|bonus|benefits?)"
            r"|\bhousing\s+(?:stipend|provided|assistance|support)",
            re.I,
        ),
    ),
]


def detect_flags(title: str, text: str, pay: Pay | None, location: ParsedLocation) -> dict[str, str]:
    """Flag name -> evidence ("" when the flag needs no evidence)."""
    flags: dict[str, str] = {}
    if pay is not None:
        flags["pay_listed"] = pay.raw
    if location.work_mode in ("remote", "hybrid"):
        flags[location.work_mode] = ""
    if _TITLE_GRAD.search(title):
        flags["grad_students_only"] = title
    if _TITLE_EARLY.search(title):
        flags["early_years_only"] = title
    for name, pattern in TEXT_FLAGS:
        if name not in flags and (m := pattern.search(text)):
            flags[name] = sentence_at(text, m.start())
    if m := _GRAD_YEAR.search(text):
        sentence = sentence_at(text, m.start())
        for year in sorted(set(_YEAR.findall(sentence))):
            flags[f"grad_year:{year}"] = sentence
    return flags
```

`scraper/enrich/__init__.py`:
```python
from scraper.dedupe import fingerprint
from scraper.enrich.category import categorize, is_intern_title
from scraper.enrich.flags import detect_flags
from scraper.enrich.visa import detect_visa_signals, visa_status
from scraper.models import EnrichedJob, RawJob
from scraper.normalize.location import parse_location
from scraper.normalize.pay import parse_pay
from scraper.normalize.term import parse_term
from scraper.normalize.title import normalize_title


def enrich(raw: RawJob, company_id: int, default_country: str | None = None) -> EnrichedJob | None:
    """Turn a RawJob into an EnrichedJob, or None if it isn't a CA/US tech internship."""
    if not is_intern_title(raw.title, raw.employment_type_hint):
        return None
    category = categorize(raw.title)
    if category is None:
        return None
    location = parse_location(
        raw.location_raw, raw.country_hint, raw.work_mode_hint, default_country
    )
    if location.foreign_only:
        return None

    text = raw.description_text
    pay = parse_pay(text, raw.pay_structured, location.country)
    term, duration = parse_term(raw.title, text)
    signals = detect_visa_signals(f"{raw.title}\n{text}")
    flags = detect_flags(raw.title, text, pay, location)
    normalized = normalize_title(raw.title)
    return EnrichedJob(
        raw=raw,
        company_id=company_id,
        normalized_title=normalized,
        category=category,
        term=term,
        duration_months=duration,
        location=location,
        pay=pay,
        visa_signals=sorted(signals),
        visa_status=visa_status(signals, location.country),
        flags=sorted(flags),
        evidence={k: v for k, v in (signals | flags).items() if v},
        fingerprint=fingerprint(company_id, normalized, location.locations),
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -v`
Expected: all tests pass (whole suite so far).

- [ ] **Step 5: Commit**

```bash
git add scraper/enrich scraper/tests/test_flags.py scraper/tests/test_enrich.py
git commit -m "Add flag detection and enrich() orchestrator"
```

---

### Task 10: HTTP fetcher with retries

**Files:**
- Create: `scraper/http.py`, `scraper/tests/test_http.py`

**Interfaces:**
- Produces: `FetchError(message, status: int | None)`, `Fetcher(client: httpx.AsyncClient | None = None, base_delay: float = 1.0)` — async context manager with `async json(method: str, url: str, **kwargs) -> Any`.

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_http.py`

```python
import httpx
import pytest

from scraper.http import USER_AGENT, FetchError, Fetcher


def fetcher_for(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT})
    return Fetcher(client=client, base_delay=0)


async def test_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    async with fetcher_for(handler) as f:
        assert await f.json("GET", "https://api.example.com/x") == {"ok": True}
    assert len(calls) == 3
    assert calls[0].headers["User-Agent"] == USER_AGENT


async def test_404_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    async with fetcher_for(handler) as f:
        with pytest.raises(FetchError) as e:
            await f.json("GET", "https://api.example.com/x")
    assert e.value.status == 404 and len(calls) == 1


async def test_gives_up_after_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    async with fetcher_for(handler) as f:
        with pytest.raises(FetchError) as e:
            await f.json("GET", "https://api.example.com/x")
    assert e.value.status == 429 and len(calls) == 4


async def test_network_error_wrapped():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    async with fetcher_for(handler) as f:
        with pytest.raises(FetchError, match="ConnectTimeout"):
            await f.json("GET", "https://api.example.com/x")


async def test_invalid_json():
    async with fetcher_for(lambda r: httpx.Response(200, text="<html>")) as f:
        with pytest.raises(FetchError, match="invalid JSON"):
            await f.json("GET", "https://api.example.com/x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_http.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `scraper/http.py`

```python
import asyncio
import random
from typing import Any
from urllib.parse import urlsplit

import httpx

USER_AGENT = "intern-job-scraper (+https://github.com/baldeep06/jobs-scraping)"
TIMEOUT = httpx.Timeout(15.0)
MAX_RETRIES = 3
PER_HOST_LIMIT = 5
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Fetcher:
    """Shared HTTP client: per-host concurrency cap, retries with exponential backoff + jitter."""

    def __init__(self, client: httpx.AsyncClient | None = None, base_delay: float = 1.0):
        self._client = client or httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._base_delay = base_delay
        self._limits: dict[str, asyncio.Semaphore] = {}

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def json(self, method: str, url: str, **kwargs: Any) -> Any:
        limit = self._limits.setdefault(urlsplit(url).hostname or "", asyncio.Semaphore(PER_HOST_LIMIT))
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
            try:
                return resp.json()
            except ValueError as e:
                raise FetchError(f"invalid JSON: {e}") from e
        assert last is not None
        raise last
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_http.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scraper/http.py scraper/tests/test_http.py
git commit -m "Add HTTP fetcher with retries and per-host limits"
```

---

### Task 11: Greenhouse adapter

**Files:**
- Create: `scraper/adapters/__init__.py`, `scraper/adapters/base.py`, `scraper/adapters/greenhouse.py`, `scraper/tests/fixtures/greenhouse.json`, `scraper/tests/test_adapters.py`

**Interfaces:**
- Consumes: `Fetcher`, `FetchError` (Task 10), `RawJob`, `FetchResult`, `Company` (Task 1), `html_to_text` (Task 2).
- Produces: `Adapter = Callable[[Fetcher, Company], Awaitable[FetchResult]]`; `validate(records: Iterable[dict]) -> FetchResult`; `as_id(value) -> str`; `greenhouse.parse(payload) -> FetchResult`, `greenhouse.fetch(fetcher, company) -> FetchResult`; `ADAPTERS: dict[str, Adapter]` (extended in Tasks 12–13).

- [ ] **Step 1: Create fixture** — `scraper/tests/fixtures/greenhouse.json`

```json
{
  "jobs": [
    {
      "id": 7001,
      "title": "Software Engineer Intern (Summer 2027)",
      "absolute_url": "https://boards.greenhouse.io/acme/jobs/7001",
      "updated_at": "2026-09-30T10:00:00-04:00",
      "first_published": "2026-09-28T09:00:00-04:00",
      "location": {"name": "Toronto, ON"},
      "content": "&lt;p&gt;Join our team.&lt;/p&gt;&lt;p&gt;The hourly rate is CA$30 - CA$38 per hour.&lt;/p&gt;"
    },
    {
      "id": 7002,
      "title": "Data Science Intern",
      "absolute_url": "https://boards.greenhouse.io/acme/jobs/7002",
      "updated_at": "2026-09-30T10:00:00-04:00",
      "location": {"name": "New York, NY"},
      "content": "&lt;p&gt;We will not sponsor visas for this role.&lt;/p&gt;"
    },
    {
      "id": 7003,
      "title": "Senior Account Executive",
      "absolute_url": "https://boards.greenhouse.io/acme/jobs/7003",
      "updated_at": "2026-09-30T10:00:00-04:00",
      "location": {"name": "Remote"},
      "content": ""
    },
    {
      "title": "Broken record with no id",
      "absolute_url": "https://boards.greenhouse.io/acme/jobs/x",
      "location": {"name": "Remote"},
      "content": ""
    }
  ],
  "meta": {"total": 4}
}
```

- [ ] **Step 2: Write the failing test** — `scraper/tests/test_adapters.py`

```python
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from scraper.adapters import ADAPTERS, greenhouse
from scraper.http import FetchError, Fetcher
from scraper.models import Company

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_greenhouse_parse():
    result = greenhouse.parse(load("greenhouse.json"))
    assert result.invalid == 1
    assert [j.source_job_id for j in result.jobs] == ["7001", "7002", "7003"]
    first = result.jobs[0]
    assert first.source == "greenhouse"
    assert first.url == "https://boards.greenhouse.io/acme/jobs/7001"
    assert first.location_raw == "Toronto, ON"
    assert first.source_posted_at == datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
    assert first.description_text == "Join our team.\nThe hourly rate is CA$30 - CA$38 per hour."
    assert result.jobs[1].source_posted_at == datetime(2026, 9, 30, 14, 0, tzinfo=UTC)


def test_greenhouse_unexpected_payload():
    with pytest.raises(FetchError, match="unexpected"):
        greenhouse.parse(["not", "a", "dict"])


async def test_greenhouse_fetch_uses_board_url():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=load("greenhouse.json"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with Fetcher(client=client, base_delay=0) as f:
        result = await ADAPTERS["greenhouse"](f, Company(id=1, name="Acme", ats="greenhouse", slug="acme"))
    assert seen == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"]
    assert len(result.jobs) == 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_adapters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.adapters'`

- [ ] **Step 4: Implement**

`scraper/adapters/base.py`:
```python
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import ValidationError

from scraper.http import Fetcher
from scraper.models import Company, FetchResult, RawJob

Adapter = Callable[[Fetcher, Company], Awaitable[FetchResult]]


def as_id(value: Any) -> str:
    return "" if value is None else str(value)


def validate(records: Iterable[dict[str, Any]]) -> FetchResult:
    """Build RawJobs, dropping (and counting) records that fail validation."""
    jobs: list[RawJob] = []
    invalid = 0
    for record in records:
        try:
            jobs.append(RawJob.model_validate(record))
        except ValidationError:
            invalid += 1
    return FetchResult(jobs=jobs, invalid=invalid)
```

`scraper/adapters/greenhouse.py`:
```python
from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import FetchError, Fetcher
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "greenhouse"


def board_url(slug: str) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FetchError("unexpected Greenhouse payload")
    return validate(
        {
            "source": SOURCE,
            "source_job_id": as_id(item.get("id")),
            "title": item.get("title") or "",
            "url": item.get("absolute_url") or "",
            "location_raw": (item.get("location") or {}).get("name") or "",
            "description_text": html_to_text(item.get("content") or ""),
            "source_posted_at": item.get("first_published") or item.get("updated_at"),
        }
        for item in payload["jobs"]
    )


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))
```

`scraper/adapters/__init__.py`:
```python
from scraper.adapters import greenhouse
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
}
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest scraper/tests/test_adapters.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add scraper/adapters scraper/tests/fixtures/greenhouse.json scraper/tests/test_adapters.py
git commit -m "Add Greenhouse adapter"
```

---

### Task 12: Lever adapter

**Files:**
- Create: `scraper/adapters/lever.py`, `scraper/tests/fixtures/lever.json`
- Modify: `scraper/adapters/__init__.py`, `scraper/tests/test_adapters.py`

**Interfaces:**
- Consumes: `as_id`, `validate` (Task 11).
- Produces: `lever.parse(payload) -> FetchResult`, `lever.fetch`, `ADAPTERS["lever"]`.

- [ ] **Step 1: Create fixture** — `scraper/tests/fixtures/lever.json`

```json
[
  {
    "id": "a1b2c3d4-0000-4000-8000-000000000001",
    "text": "Software Engineer Co-op (4 months)",
    "hostedUrl": "https://jobs.lever.co/acme/a1b2c3d4-0000-4000-8000-000000000001",
    "createdAt": 1790000000000,
    "country": "CA",
    "workplaceType": "hybrid",
    "categories": {
      "commitment": "Internship",
      "location": "Waterloo, ON",
      "allLocations": ["Waterloo, ON", "Toronto, ON"],
      "team": "Engineering"
    },
    "descriptionPlain": "Build things.",
    "lists": [
      {"text": "Requirements", "content": "<li>Enrolled in a co-op program at a Canadian university</li>"}
    ],
    "additionalPlain": "",
    "salaryRange": {"currency": "CAD", "interval": "per-hour-wage", "min": 32, "max": 40}
  },
  {
    "id": "a1b2c3d4-0000-4000-8000-000000000002",
    "text": "Account Manager",
    "hostedUrl": "https://jobs.lever.co/acme/a1b2c3d4-0000-4000-8000-000000000002",
    "createdAt": 1790000000000,
    "country": "US",
    "workplaceType": "unspecified",
    "categories": {"commitment": "Full-time", "location": "Austin, TX"},
    "descriptionPlain": "Sell things."
  }
]
```

- [ ] **Step 2: Add failing tests** to `scraper/tests/test_adapters.py`

Change the top import to `from scraper.adapters import ADAPTERS, greenhouse, lever`, then append:

```python
def test_lever_parse():
    result = lever.parse(load("lever.json"))
    assert result.invalid == 0 and len(result.jobs) == 2
    job = result.jobs[0]
    assert job.source == "lever"
    assert job.title == "Software Engineer Co-op (4 months)"
    assert job.location_raw == "Waterloo, ON | Toronto, ON"
    assert job.source_posted_at == datetime.fromtimestamp(1790000000, UTC)
    assert job.description_text == (
        "Build things.\nRequirements\nEnrolled in a co-op program at a Canadian university"
    )
    assert (job.pay_structured.min, job.pay_structured.max) == (32, 40)
    assert (job.pay_structured.currency, job.pay_structured.period) == ("CAD", "hour")
    assert (job.country_hint, job.work_mode_hint, job.employment_type_hint) == ("CA", "hybrid", "Internship")
    assert result.jobs[1].work_mode_hint is None
    assert result.jobs[1].location_raw == "Austin, TX"


def test_lever_unexpected_payload():
    with pytest.raises(FetchError, match="unexpected"):
        lever.parse({"ok": False})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_adapters.py -v`
Expected: FAIL — `ImportError: cannot import name 'lever'`

- [ ] **Step 4: Implement** — `scraper/adapters/lever.py`

```python
from datetime import UTC, datetime
from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import FetchError, Fetcher
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "lever"
_INTERVALS = {
    "per-hour-wage": "hour",
    "per-week-salary": "week",
    "per-month-salary": "month",
    "per-year-salary": "year",
}
_WORKPLACE = {"onsite": "onsite", "remote": "remote", "hybrid": "hybrid"}


def board_url(slug: str) -> str:
    return f"https://api.lever.co/v0/postings/{slug}?mode=json"


def _description(item: dict[str, Any]) -> str:
    parts = [item.get("descriptionPlain") or ""]
    for section in item.get("lists") or []:
        parts.append(section.get("text") or "")
        parts.append(html_to_text(section.get("content") or ""))
    parts.append(item.get("additionalPlain") or "")
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _pay(item: dict[str, Any]) -> dict[str, Any] | None:
    salary = item.get("salaryRange") or {}
    period = _INTERVALS.get(salary.get("interval"))
    if not period:
        return None
    return {"min": salary.get("min"), "max": salary.get("max"),
            "currency": salary.get("currency"), "period": period}


def _record(item: dict[str, Any]) -> dict[str, Any]:
    cats = item.get("categories") or {}
    all_locations = cats.get("allLocations") or []
    created = item.get("createdAt")
    return {
        "source": SOURCE,
        "source_job_id": as_id(item.get("id")),
        "title": item.get("text") or "",
        "url": item.get("hostedUrl") or "",
        "location_raw": " | ".join(all_locations) if all_locations else (cats.get("location") or ""),
        "description_text": _description(item),
        "source_posted_at": (
            datetime.fromtimestamp(created / 1000, UTC) if isinstance(created, int | float) else None
        ),
        "pay_structured": _pay(item),
        "work_mode_hint": _WORKPLACE.get(item.get("workplaceType") or ""),
        "country_hint": item.get("country"),
        "employment_type_hint": cats.get("commitment"),
    }


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, list):
        raise FetchError("unexpected Lever payload")
    return validate(_record(item) for item in payload)


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))
```

`scraper/adapters/__init__.py`:
```python
from scraper.adapters import greenhouse, lever
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
}
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest scraper/tests/test_adapters.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add scraper/adapters scraper/tests/fixtures/lever.json scraper/tests/test_adapters.py
git commit -m "Add Lever adapter"
```

---

### Task 13: Ashby adapter

**Files:**
- Create: `scraper/adapters/ashby.py`, `scraper/tests/fixtures/ashby.json`
- Modify: `scraper/adapters/__init__.py`, `scraper/tests/test_adapters.py`

**Interfaces:**
- Consumes: `as_id`, `validate` (Task 11).
- Produces: `ashby.parse(payload) -> FetchResult`, `ashby.fetch`, `ADAPTERS["ashby"]`.

- [ ] **Step 1: Create fixture** — `scraper/tests/fixtures/ashby.json`

```json
{
  "apiVersion": "1",
  "jobs": [
    {
      "id": "b0000000-0000-4000-8000-000000000001",
      "title": "Machine Learning Intern",
      "location": "San Francisco, CA",
      "secondaryLocations": [{"location": "New York, NY"}],
      "isListed": true,
      "isRemote": false,
      "workplaceType": "OnSite",
      "employmentType": "Intern",
      "publishedAt": "2026-10-01T15:30:00.000+00:00",
      "jobUrl": "https://jobs.ashbyhq.com/acme/b0000000-0000-4000-8000-000000000001",
      "descriptionPlain": "Visa sponsorship is available for this role.",
      "address": {"postalAddress": {"addressCountry": "United States", "addressRegion": "California"}},
      "compensation": {
        "compensationTierSummary": "$50 – $60 per hour",
        "summaryComponents": [
          {"compensationType": "EquityPercentage", "interval": "NONE", "minValue": 0.1, "maxValue": 0.2},
          {"compensationType": "Salary", "interval": "1 HOUR", "currencyCode": "USD", "minValue": 50, "maxValue": 60}
        ]
      }
    },
    {
      "id": "b0000000-0000-4000-8000-000000000002",
      "title": "Hidden Intern Role",
      "location": "Remote",
      "isListed": false,
      "jobUrl": "https://jobs.ashbyhq.com/acme/b0000000-0000-4000-8000-000000000002",
      "descriptionPlain": ""
    },
    {
      "id": "b0000000-0000-4000-8000-000000000003",
      "title": "Software Engineering Intern",
      "location": "London",
      "isListed": true,
      "isRemote": false,
      "workplaceType": "Hybrid",
      "jobUrl": "https://jobs.ashbyhq.com/acme/b0000000-0000-4000-8000-000000000003",
      "descriptionPlain": "Join us in London.",
      "address": {"postalAddress": {"addressCountry": "United Kingdom"}}
    }
  ]
}
```

- [ ] **Step 2: Append failing tests** to `scraper/tests/test_adapters.py` (add `ashby` to the top import: `from scraper.adapters import ADAPTERS, ashby, greenhouse, lever`)

```python
def test_ashby_parse():
    result = ashby.parse(load("ashby.json"))
    assert [j.source_job_id[-1] for j in result.jobs] == ["1", "3"]  # unlisted job skipped
    job = result.jobs[0]
    assert job.source == "ashby"
    assert job.location_raw == "San Francisco, CA | New York, NY"
    assert job.source_posted_at == datetime(2026, 10, 1, 15, 30, tzinfo=UTC)
    assert job.description_text == "Visa sponsorship is available for this role.\n$50 – $60 per hour"
    assert (job.pay_structured.min, job.pay_structured.max) == (50, 60)
    assert (job.pay_structured.currency, job.pay_structured.period) == ("USD", "hour")
    assert (job.country_hint, job.work_mode_hint, job.employment_type_hint) == ("US", "onsite", "Intern")
    london = result.jobs[1]
    assert (london.country_hint, london.work_mode_hint) == ("OTHER", "hybrid")


def test_ashby_unexpected_payload():
    with pytest.raises(FetchError, match="unexpected"):
        ashby.parse({"apiVersion": "1"})


def test_registry_has_all_phase1_adapters():
    assert set(ADAPTERS) == {"greenhouse", "lever", "ashby"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_adapters.py -v`
Expected: FAIL — `ImportError: cannot import name 'ashby'`

- [ ] **Step 4: Implement** — `scraper/adapters/ashby.py`

```python
from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import FetchError, Fetcher
from scraper.models import Company, FetchResult

SOURCE = "ashby"
_INTERVALS = {"1 HOUR": "hour", "1 WEEK": "week", "1 MONTH": "month", "1 YEAR": "year"}
_WORKPLACE = {"OnSite": "onsite", "Remote": "remote", "Hybrid": "hybrid"}
_COUNTRIES = {"canada": "CA", "united states": "US", "united states of america": "US", "usa": "US"}


def board_url(slug: str) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def _country(item: dict[str, Any]) -> str | None:
    country = (((item.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or "")
    country = country.strip()
    if not country:
        return None
    if len(country) == 2 and country.isalpha():
        return country.upper()
    return _COUNTRIES.get(country.lower(), "OTHER")


def _pay(item: dict[str, Any]) -> dict[str, Any] | None:
    for comp in (item.get("compensation") or {}).get("summaryComponents") or []:
        period = _INTERVALS.get(comp.get("interval"))
        if comp.get("compensationType") == "Salary" and period:
            return {"min": comp.get("minValue"), "max": comp.get("maxValue"),
                    "currency": comp.get("currencyCode"), "period": period}
    return None


def _work_mode(item: dict[str, Any]) -> str | None:
    mode = _WORKPLACE.get(item.get("workplaceType") or "")
    return mode or ("remote" if item.get("isRemote") else None)


def _record(item: dict[str, Any]) -> dict[str, Any]:
    locations = [item.get("location") or ""] + [
        (s or {}).get("location") or "" for s in item.get("secondaryLocations") or []
    ]
    summary = (item.get("compensation") or {}).get("compensationTierSummary") or ""
    description = "\n".join(p for p in (item.get("descriptionPlain") or "", summary) if p)
    return {
        "source": SOURCE,
        "source_job_id": as_id(item.get("id")),
        "title": item.get("title") or "",
        "url": item.get("jobUrl") or "",
        "location_raw": " | ".join(loc for loc in locations if loc),
        "description_text": description,
        "source_posted_at": item.get("publishedAt"),
        "pay_structured": _pay(item),
        "work_mode_hint": _work_mode(item),
        "country_hint": _country(item),
        "employment_type_hint": item.get("employmentType"),
    }


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FetchError("unexpected Ashby payload")
    return validate(_record(item) for item in payload["jobs"] if item.get("isListed", True))


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))
```

`scraper/adapters/__init__.py`:
```python
from scraper.adapters import ashby, greenhouse, lever
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -v`
Expected: whole suite passes.

- [ ] **Step 6: Commit**

```bash
git add scraper/adapters scraper/tests/fixtures/ashby.json scraper/tests/test_adapters.py
git commit -m "Add Ashby adapter"
```

---

### Task 14: Database schema, migration runner, and test Postgres

**Files:**
- Create: `supabase/migrations/20261007000000_init.sql`, `scraper/db.py` (connect + migrate only), `scraper/tests/sql/supabase_shim.sql`, `scraper/tests/conftest.py`, `scraper/tests/test_db_schema.py`

**Interfaces:**
- Produces: `db.connect(dsn: str) -> psycopg.Connection` (autocommit, dict rows, no prepared statements); `db.migrate(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]`; pytest fixture `conn` (fresh migrated schema per test).

- [ ] **Step 1: Start a local throwaway Postgres**

```bash
docker run -d --name jobs-pg -e POSTGRES_PASSWORD=postgres -p 54329:5432 postgres:17
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres
```
(If the container already exists: `docker start jobs-pg`.)

- [ ] **Step 2: Write the migration** — `supabase/migrations/20261007000000_init.sql`

```sql
-- Phase 1 schema. Spec §4.

create table companies (
  id bigint generated always as identity primary key,
  name text not null,
  ats text not null check (ats in ('greenhouse','lever','ashby','workday','smartrecruiters','workable')),
  slug text not null,
  workday_host text,
  workday_site text,
  domain text,
  tier text not null default 'warm' check (tier in ('hot','warm','cold','inactive')),
  curated_hot boolean not null default false,
  last_polled_at timestamptz,
  last_success_at timestamptz,
  fail_count int not null default 0,
  consecutive_404s int not null default 0,
  job_ids_hash text,
  last_intern_seen_at timestamptz,
  discovered_from text,
  h1b_count int,
  h1b_fiscal_year int,
  created_at timestamptz not null default now(),
  unique (ats, slug)
);

create table jobs (
  id uuid primary key default gen_random_uuid(),
  company_id bigint not null references companies(id) on delete cascade,
  title text not null,
  normalized_title text not null,
  category text not null,
  term text,
  duration_months int,
  location_raw text not null default '',
  locations jsonb not null default '[]',
  country text not null check (country in ('CA','US','BOTH','UNKNOWN')),
  work_mode text not null default 'unknown' check (work_mode in ('onsite','hybrid','remote','unknown')),
  location_unclear boolean not null default false,
  pay_min numeric,
  pay_max numeric,
  pay_currency text,
  pay_period text check (pay_period in ('hour','year','month','week')),
  pay_hourly_min numeric,
  pay_hourly_max numeric,
  pay_raw text,
  visa_signals text[] not null default '{}',
  visa_status text not null check (visa_status in ('open','blocked','unknown')),
  flags text[] not null default '{}',
  evidence jsonb not null default '{}',
  fingerprint text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  source_posted_at timestamptz,
  status text not null default 'open' check (status in ('open','closed')),
  closed_at timestamptz,
  miss_count int not null default 0,
  freshness text not null default 'fresh'
    check (freshness in ('fresh','repost','reopened','refreshed','recurring')),
  repost_of uuid references jobs(id) on delete set null,
  repost_count int not null default 0,
  best_url text not null,
  updated_at timestamptz not null default now()
);
create index jobs_fingerprint_idx on jobs (fingerprint);
create index jobs_feed_idx on jobs (status, country, first_seen_at desc);
create index jobs_company_idx on jobs (company_id);

create table job_sources (
  id bigint generated always as identity primary key,
  job_id uuid not null references jobs(id) on delete cascade,
  company_id bigint not null references companies(id) on delete cascade,
  source text not null,
  source_job_id text not null,
  url text not null,
  source_posted_at timestamptz,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (source, source_job_id)
);
create index job_sources_company_idx on job_sources (company_id, source);
create index job_sources_job_idx on job_sources (job_id);

create table scrape_runs (
  id bigint generated always as identity primary key,
  workflow text not null,
  source text not null,
  started_at timestamptz not null,
  finished_at timestamptz not null,
  companies_polled int not null default 0,
  jobs_seen int not null default 0,
  jobs_new int not null default 0,
  jobs_closed int not null default 0,
  errors int not null default 0,
  error_samples jsonb not null default '[]'
);

create table source_state (
  source text primary key,
  cooldown_until timestamptz,
  backoff_seconds int not null default 0,
  last_commit_sha text,
  notes text
);

create view jobs_feed with (security_invoker = true) as
select j.*, c.name as company_name, c.domain as company_domain,
       c.h1b_count, c.h1b_fiscal_year
from jobs j
join companies c on c.id = j.company_id
where j.status = 'open';

-- Row-level security: the website's anon key may only read; the scraper connects as the
-- table owner (bypasses RLS).
alter table companies enable row level security;
alter table jobs enable row level security;
alter table job_sources enable row level security;
alter table scrape_runs enable row level security;
alter table source_state enable row level security;

create policy read_companies on companies for select to anon, authenticated using (true);
create policy read_open_jobs on jobs for select to anon, authenticated using (status = 'open');
create policy read_job_sources on job_sources for select to anon, authenticated using (true);
create policy read_scrape_runs on scrape_runs for select to anon, authenticated using (true);

grant usage on schema public to anon, authenticated;
grant select on companies, jobs, job_sources, scrape_runs, jobs_feed to anon, authenticated;
```

- [ ] **Step 3: Write test shim, fixture, and failing test**

`scraper/tests/sql/supabase_shim.sql` (creates the roles Supabase provides; **never run against Supabase**):
```sql
do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end $$;
```

`scraper/tests/conftest.py`:
```python
import os
from pathlib import Path

import pytest

from scraper import db

SHIM = Path(__file__).parent / "sql" / "supabase_shim.sql"


@pytest.fixture
def conn():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")
    if "supabase" in dsn:
        pytest.fail("TEST_DATABASE_URL points at Supabase; tests drop the public schema")
    c = db.connect(dsn)
    c.execute("drop schema if exists public cascade")
    c.execute("create schema public")
    c.execute(SHIM.read_text())
    db.migrate(c)
    yield c
    c.close()
```

`scraper/tests/test_db_schema.py`:
```python
import psycopg
import pytest

from scraper import db


def test_migrate_is_idempotent(conn):
    assert db.migrate(conn) == []
    names = [r["name"] for r in conn.execute("select name from schema_migrations")]
    assert names == ["20261007000000_init.sql"]


def test_anon_reads_open_jobs_only_and_cannot_write(conn):
    cid = conn.execute(
        "insert into companies (name, ats, slug) values ('Acme','greenhouse','acme') returning id"
    ).fetchone()["id"]
    for status in ("open", "closed"):
        conn.execute(
            """insert into jobs (company_id, title, normalized_title, category, country,
                                 visa_status, fingerprint, best_url, status)
               values (%s, %s, 'x', 'SWE', 'CA', 'open', %s, 'https://x', %s)""",
            (cid, f"{status} job", status, status),
        )
    conn.execute("set role anon")
    try:
        assert [r["title"] for r in conn.execute("select title from jobs")] == ["open job"]
        assert [r["company_name"] for r in conn.execute("select company_name from jobs_feed")] == ["Acme"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into companies (name, ats, slug) values ('x','lever','x')")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from source_state")
    finally:
        conn.execute("reset role")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_db_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'db'`

- [ ] **Step 5: Implement** — `scraper/db.py`

```python
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def connect(dsn: str) -> psycopg.Connection:
    # autocommit: every write goes through an explicit `with conn.transaction()` block.
    # prepare_threshold=None: Supabase's pooler doesn't support prepared statements.
    return psycopg.connect(dsn, autocommit=True, prepare_threshold=None, row_factory=dict_row)


def migrate(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    conn.execute(
        "create table if not exists schema_migrations "
        "(name text primary key, applied_at timestamptz not null default now())"
    )
    conn.execute("alter table schema_migrations enable row level security")
    applied = {r["name"] for r in conn.execute("select name from schema_migrations")}
    done = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
        done.append(path.name)
    return done
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest scraper/tests/test_db_schema.py -v`
Expected: 2 passed (not skipped — confirm `TEST_DATABASE_URL` is exported).

- [ ] **Step 7: Commit**

```bash
git add supabase scraper/db.py scraper/tests/sql scraper/tests/conftest.py scraper/tests/test_db_schema.py
git commit -m "Add Postgres schema, RLS policies and migration runner"
```

---

### Task 15: Pipeline (poll + process)

**Files:**
- Create: `scraper/pipeline.py`, `scraper/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `ADAPTERS`, `Adapter` (Tasks 11–13), `enrich` (Task 9), `ids_hash` (Task 3), `parse_location` (Task 5), `FetchError` (Task 10).
- Produces: `dominant_country(raws: list[RawJob]) -> str | None`; `process(company: Company, result: FetchResult) -> CompanyOutcome`; `async poll(fetcher: Fetcher, company: Company, adapters: dict[str, Adapter] = ADAPTERS) -> CompanyOutcome` (never raises).

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_pipeline.py`

```python
from scraper.dedupe import ids_hash
from scraper.http import FetchError
from scraper.models import Company, FetchResult, RawJob
from scraper.pipeline import dominant_country, poll, process

ACME = Company(id=1, name="Acme", ats="greenhouse", slug="acme")


def raw(id_, title="Software Engineer Intern", location="Toronto, ON"):
    return RawJob(source="greenhouse", source_job_id=id_, title=title,
                  url=f"https://x/{id_}", location_raw=location)


def test_process_filters_and_tracks_all_seen_ids():
    result = FetchResult(jobs=[raw("1"), raw("2", title="Account Executive")], invalid=1)
    out = process(ACME, result)
    assert out.ok and not out.unchanged
    assert [j.raw.source_job_id for j in out.jobs] == ["1"]
    assert out.seen_ids == {"1", "2"}
    assert out.ids_hash == ids_hash({"1", "2"})
    assert out.invalid == 1


def test_process_skips_enrichment_when_ids_unchanged():
    company = ACME.model_copy(update={"job_ids_hash": ids_hash({"1"})})
    out = process(company, FetchResult(jobs=[raw("1")]))
    assert out.unchanged and out.jobs == [] and out.seen_ids == {"1"}


def test_dominant_country_used_for_bare_remote():
    out = process(ACME, FetchResult(jobs=[
        raw("1", title="Account Executive", location="Toronto, ON"),
        raw("2", title="Sales Lead", location="Vancouver, BC"),
        raw("3", location="Remote"),
    ]))
    assert out.jobs[0].location.country == "CA"
    assert dominant_country([raw("1", location="Seattle")]) == "US"
    assert dominant_country([raw("1", location="Remote")]) is None


async def test_poll_wraps_fetch_errors():
    async def boom(fetcher, company):
        raise FetchError("HTTP 404", 404)

    out = await poll(None, ACME, adapters={"greenhouse": boom})
    assert (out.ok, out.status, out.error) == (False, 404, "HTTP 404")


async def test_poll_wraps_unexpected_errors():
    async def bug(fetcher, company):
        raise KeyError("jobs")

    out = await poll(None, ACME, adapters={"greenhouse": bug})
    assert not out.ok and out.error.startswith("KeyError")


async def test_poll_success():
    async def ok(fetcher, company):
        return FetchResult(jobs=[raw("1")])

    out = await poll(None, ACME, adapters={"greenhouse": ok})
    assert out.ok and len(out.jobs) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.pipeline'`

- [ ] **Step 3: Implement** — `scraper/pipeline.py`

```python
from collections import Counter

from scraper.adapters import ADAPTERS
from scraper.adapters.base import Adapter
from scraper.dedupe import ids_hash
from scraper.enrich import enrich
from scraper.http import FetchError, Fetcher
from scraper.models import Company, CompanyOutcome, FetchResult, RawJob
from scraper.normalize.location import parse_location


def dominant_country(raws: list[RawJob]) -> str | None:
    """Most common of CA/US across a company's whole board (used for bare "Remote" roles)."""
    counts: Counter[str] = Counter()
    for r in raws:
        country = parse_location(r.location_raw, r.country_hint, r.work_mode_hint).country
        if country in ("CA", "US"):
            counts[country] += 1
    return counts.most_common(1)[0][0] if counts else None


def process(company: Company, result: FetchResult) -> CompanyOutcome:
    seen = {r.source_job_id for r in result.jobs}
    outcome = CompanyOutcome(
        company=company, ok=True, seen_ids=seen, ids_hash=ids_hash(seen), invalid=result.invalid
    )
    if outcome.ids_hash == company.job_ids_hash:
        outcome.unchanged = True
        return outcome
    default = dominant_country(result.jobs)
    outcome.jobs = [e for r in result.jobs if (e := enrich(r, company.id, default)) is not None]
    return outcome


async def poll(
    fetcher: Fetcher, company: Company, adapters: dict[str, Adapter] = ADAPTERS
) -> CompanyOutcome:
    """Fetch + process one company. Never raises: failures become ok=False outcomes."""
    try:
        return process(company, await adapters[company.ats](fetcher, company))
    except FetchError as e:
        return CompanyOutcome(company=company, ok=False, error=str(e), status=e.status)
    except Exception as e:  # adapter bug or surprise payload shape — isolate to this company
        return CompanyOutcome(company=company, ok=False, error=f"{type(e).__name__}: {e}")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_pipeline.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scraper/pipeline.py scraper/tests/test_pipeline.py
git commit -m "Add company poll/process pipeline with failure isolation"
```

---

### Task 16: Database ingest

**Files:**
- Modify: `scraper/db.py` (append)
- Create: `scraper/tests/test_db_ingest.py`

**Interfaces:**
- Consumes: `classify`, `plan_closures`, `ExistingSource`, `FingerprintMatch`, `OpenJob`, `Decision` (Task 3); `CompanyOutcome`, `EnrichedJob`, `Company` (Task 1).
- Produces:
  - `upsert_companies(conn, seeds: list[dict]) -> int` — dict keys `name, ats, slug, domain` (optional), `hot` (bool, optional).
  - `get_companies(conn, *, ats: list[str], tier: str | None = None, slug: str | None = None, limit: int = 1000) -> list[Company]`
  - `IngestStats(new: int = 0, closed: int = 0, seen: int = 0)`
  - `ingest(conn, outcome: CompanyOutcome, now: datetime) -> IngestStats`
  - `record_run(conn, *, workflow: str, source: str, started_at, finished_at, companies_polled, jobs_seen, jobs_new, jobs_closed, errors, error_samples: list[dict]) -> None`

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_db_ingest.py`

```python
from datetime import UTC, datetime, timedelta

from scraper import db
from scraper.dedupe import ids_hash
from scraper.enrich import enrich
from scraper.models import CompanyOutcome, RawJob

T0 = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def company(conn, slug="acme", ats="greenhouse"):
    db.upsert_companies(conn, [{"name": slug.title(), "ats": ats, "slug": slug, "hot": True}])
    return db.get_companies(conn, ats=[ats], slug=slug)[0]


def raw(id_, title="Software Engineer Intern", location="Toronto, ON", posted=None):
    return RawJob(source="greenhouse", source_job_id=id_, title=title,
                  url=f"https://x/{id_}", location_raw=location, source_posted_at=posted)


def outcome(c, raws, unchanged=False):
    seen = {r.source_job_id for r in raws}
    jobs = [] if unchanged else [e for r in raws if (e := enrich(r, c.id))]
    return CompanyOutcome(company=c, ok=True, jobs=jobs, seen_ids=seen,
                          ids_hash=ids_hash(seen), unchanged=unchanged)


def jobs(conn):
    return conn.execute("select * from jobs order by first_seen_at, title").fetchall()


def test_upsert_and_get_companies(conn):
    c = company(conn)
    assert (c.name, c.ats, c.slug, c.job_ids_hash) == ("Acme", "greenhouse", "acme", None)
    tier = conn.execute("select tier from companies").fetchone()["tier"]
    assert tier == "hot"
    assert db.get_companies(conn, ats=["greenhouse"], tier="warm") == []


def test_new_job_inserted_as_fresh_with_source(conn):
    c = company(conn)
    stats = db.ingest(conn, outcome(c, [raw("1")]), T0)
    assert (stats.new, stats.seen, stats.closed) == (1, 1, 0)
    [j] = jobs(conn)
    assert (j["freshness"], j["status"], j["country"], j["first_seen_at"]) == ("fresh", "open", "CA", T0)
    src = conn.execute("select * from job_sources").fetchone()
    assert (src["source_job_id"], src["job_id"]) == ("1", j["id"])
    row = conn.execute("select * from companies").fetchone()
    assert row["job_ids_hash"] == ids_hash({"1"}) and row["last_success_at"] == T0


def test_second_poll_touches_existing(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    stats = db.ingest(conn, outcome(c, [raw("1")]), T0 + timedelta(minutes=5))
    [j] = jobs(conn)
    assert stats.new == 0
    assert (j["first_seen_at"], j["last_seen_at"]) == (T0, T0 + timedelta(minutes=5))


def test_missing_twice_closes_then_reopens(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=5))
    assert jobs(conn)[0]["status"] == "open" and jobs(conn)[0]["miss_count"] == 1
    stats = db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=10))
    assert stats.closed == 1 and jobs(conn)[0]["status"] == "closed"
    db.ingest(conn, outcome(c, [raw("1")]), T0 + timedelta(days=1))
    [j] = jobs(conn)
    assert (j["status"], j["freshness"], j["closed_at"], j["miss_count"]) == ("open", "reopened", None, 0)


def test_same_role_twice_is_one_job_open_while_any_id_listed(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1"), raw("2")]), T0)
    assert len(jobs(conn)) == 1
    assert conn.execute("select count(*) as n from job_sources").fetchone()["n"] == 2
    for minutes in (5, 10, 15):
        db.ingest(conn, outcome(c, [raw("2")]), T0 + timedelta(minutes=minutes))
    [j] = jobs(conn)
    assert (j["status"], j["miss_count"]) == ("open", 0)


def test_repost_after_close_links_to_original(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=5))
    db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=10))
    db.ingest(conn, outcome(c, [raw("9")]), T0 + timedelta(days=30))
    old, new = jobs(conn)
    assert (new["freshness"], new["repost_of"], new["repost_count"]) == ("repost", old["id"], 1)


def test_posted_date_bump_marks_refreshed(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1", posted=T0)]), T0)
    later = T0 + timedelta(days=20)
    db.ingest(conn, outcome(c, [raw("1", posted=later)]), later)
    [j] = jobs(conn)
    assert (j["freshness"], j["source_posted_at"]) == ("refreshed", later)


def test_unchanged_hash_touches_only_seen_jobs(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1"), raw("2", title="Data Science Intern")]), T0)
    db.ingest(conn, outcome(c, [raw("1")]), T0 + timedelta(minutes=5))
    db.ingest(conn, outcome(c, [raw("1")], unchanged=True), T0 + timedelta(minutes=10))
    by_title = {j["title"]: j for j in jobs(conn)}
    assert by_title["Software Engineer Intern"]["last_seen_at"] == T0 + timedelta(minutes=10)
    assert by_title["Data Science Intern"]["status"] == "closed"


def test_failed_poll_closes_nothing_and_404s_deactivate(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    failed = CompanyOutcome(company=c, ok=False, error="HTTP 404", status=404)
    for i in range(5):
        db.ingest(conn, failed, T0 + timedelta(minutes=5 * (i + 1)))
    [j] = jobs(conn)
    assert (j["status"], j["miss_count"]) == ("open", 0)
    row = conn.execute("select * from companies").fetchone()
    assert (row["fail_count"], row["consecutive_404s"], row["tier"]) == (5, 5, "inactive")
    assert db.get_companies(conn, ats=["greenhouse"]) == []


def test_timeout_does_not_count_as_404(conn):
    c = company(conn)
    db.ingest(conn, CompanyOutcome(company=c, ok=False, error="ConnectTimeout"), T0)
    row = conn.execute("select * from companies").fetchone()
    assert (row["fail_count"], row["consecutive_404s"], row["tier"]) == (1, 0, "hot")


def test_record_run(conn):
    db.record_run(conn, workflow="scrape-hot", source="ats", started_at=T0, finished_at=T0,
                  companies_polled=2, jobs_seen=3, jobs_new=1, jobs_closed=0, errors=1,
                  error_samples=[{"company": "acme", "error": "HTTP 500"}])
    row = conn.execute("select * from scrape_runs").fetchone()
    assert (row["companies_polled"], row["error_samples"][0]["error"]) == (2, "HTTP 500")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_db_ingest.py -v`
Expected: FAIL — `AttributeError: module 'scraper.db' has no attribute 'upsert_companies'`

- [ ] **Step 3: Implement** — append to `scraper/db.py` (merge the imports into the top of the file)

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from scraper.dedupe import (
    ClosurePlan,
    Decision,
    ExistingSource,
    FingerprintMatch,
    OpenJob,
    classify,
    plan_closures,
)
from scraper.models import Company, CompanyOutcome, EnrichedJob

INACTIVE_AFTER_404S = 5


def upsert_companies(conn: psycopg.Connection, seeds: list[dict[str, Any]]) -> int:
    with conn.transaction():
        for s in seeds:
            hot = bool(s.get("hot", False))
            conn.execute(
                """insert into companies (name, ats, slug, domain, curated_hot, tier)
                   values (%(name)s, %(ats)s, %(slug)s, %(domain)s, %(hot)s,
                           case when %(hot)s then 'hot' else 'warm' end)
                   on conflict (ats, slug) do update set
                     name = excluded.name, domain = excluded.domain,
                     curated_hot = excluded.curated_hot,
                     tier = case when companies.tier = 'inactive' then 'inactive'
                                 when excluded.curated_hot then 'hot'
                                 else companies.tier end""",
                {"name": s["name"], "ats": s["ats"], "slug": s["slug"],
                 "domain": s.get("domain"), "hot": hot},
            )
    return len(seeds)


def get_companies(
    conn: psycopg.Connection,
    *,
    ats: list[str],
    tier: str | None = None,
    slug: str | None = None,
    limit: int = 1000,
) -> list[Company]:
    rows = conn.execute(
        """select id, name, ats, slug, job_ids_hash from companies
           where ats = any(%(ats)s) and tier <> 'inactive'
             and (%(tier)s::text is null or tier = %(tier)s)
             and (%(slug)s::text is null or slug = %(slug)s)
           order by last_polled_at nulls first, id
           limit %(limit)s""",
        {"ats": ats, "tier": tier, "slug": slug, "limit": limit},
    ).fetchall()
    return [Company(**r) for r in rows]


@dataclass
class IngestStats:
    new: int = 0
    closed: int = 0
    seen: int = 0


def _job_fields(job: EnrichedJob) -> dict[str, Any]:
    pay, loc = job.pay, job.location
    return {
        "title": job.raw.title,
        "normalized_title": job.normalized_title,
        "category": job.category,
        "term": job.term,
        "duration_months": job.duration_months,
        "location_raw": job.raw.location_raw,
        "locations": Jsonb([x.model_dump() for x in loc.locations]),
        "country": loc.country,
        "work_mode": loc.work_mode,
        "location_unclear": loc.location_unclear,
        "pay_min": pay.min if pay else None,
        "pay_max": pay.max if pay else None,
        "pay_currency": pay.currency if pay else None,
        "pay_period": pay.period if pay else None,
        "pay_hourly_min": pay.hourly_min if pay else None,
        "pay_hourly_max": pay.hourly_max if pay else None,
        "pay_raw": pay.raw if pay else None,
        "visa_signals": job.visa_signals,
        "visa_status": job.visa_status,
        "flags": job.flags,
        "evidence": Jsonb(job.evidence),
        "fingerprint": job.fingerprint,
        "best_url": job.raw.url,
    }


# Must match the keys returned by _job_fields().
_FIELD_NAMES = [
    "title", "normalized_title", "category", "term", "duration_months", "location_raw",
    "locations", "country", "work_mode", "location_unclear", "pay_min", "pay_max",
    "pay_currency", "pay_period", "pay_hourly_min", "pay_hourly_max", "pay_raw",
    "visa_signals", "visa_status", "flags", "evidence", "fingerprint", "best_url",
]  # fmt: skip


def _insert_job(conn: psycopg.Connection, job: EnrichedJob, d: Decision, now: datetime) -> str:
    params = _job_fields(job) | {
        "company_id": job.company_id, "now": now, "posted": job.raw.source_posted_at,
        "freshness": d.freshness, "repost_of": d.repost_of, "repost_count": d.repost_count,
    }  # fmt: skip
    cols = ", ".join(_FIELD_NAMES)
    vals = ", ".join(f"%({c})s" for c in _FIELD_NAMES)
    row = conn.execute(
        f"""insert into jobs ({cols}, company_id, first_seen_at, last_seen_at, updated_at,
                              source_posted_at, freshness, repost_of, repost_count)
            values ({vals}, %(company_id)s, %(now)s, %(now)s, %(now)s,
                    %(posted)s, %(freshness)s, %(repost_of)s, %(repost_count)s)
            returning id""",
        params,
    ).fetchone()
    return str(row["id"])


def _update_job(
    conn: psycopg.Connection, job_id: str, job: EnrichedJob, d: Decision, now: datetime
) -> None:
    sets = ", ".join(f"{c} = %({c})s" for c in _FIELD_NAMES)
    conn.execute(
        f"""update jobs set {sets},
               last_seen_at = %(now)s, updated_at = %(now)s, miss_count = 0,
               source_posted_at = coalesce(%(posted)s, source_posted_at),
               freshness = coalesce(%(freshness)s, freshness),
               status = case when %(reopen)s then 'open' else status end,
               closed_at = case when %(reopen)s then null else closed_at end
            where id = %(id)s""",
        _job_fields(job) | {"now": now, "posted": job.raw.source_posted_at, "id": job_id,
                            "freshness": d.freshness, "reopen": d.action == "reopen"},
    )


def _upsert_source(
    conn: psycopg.Connection, job_id: str, company_id: int, job: EnrichedJob, now: datetime
) -> None:
    raw = job.raw
    conn.execute(
        """insert into job_sources (job_id, company_id, source, source_job_id, url,
                                    source_posted_at, first_seen_at, last_seen_at)
           values (%(job)s, %(cid)s, %(src)s, %(sid)s, %(url)s, %(posted)s, %(now)s, %(now)s)
           on conflict (source, source_job_id) do update set
             last_seen_at = excluded.last_seen_at, url = excluded.url,
             source_posted_at = coalesce(excluded.source_posted_at, job_sources.source_posted_at)""",
        {"job": job_id, "cid": company_id, "src": raw.source, "sid": raw.source_job_id,
         "url": raw.url, "posted": raw.source_posted_at, "now": now},
    )


def _ingest_job(conn: psycopg.Connection, company: Company, job: EnrichedJob, now: datetime) -> bool:
    """Returns True if a new jobs row was created."""
    raw = job.raw
    row = conn.execute(
        """select js.job_id, j.status, j.first_seen_at, js.source_posted_at
           from job_sources js join jobs j on j.id = js.job_id
           where js.source = %s and js.source_job_id = %s""",
        (raw.source, raw.source_job_id),
    ).fetchone()
    existing = (
        ExistingSource(str(row["job_id"]), row["status"], row["first_seen_at"], row["source_posted_at"])
        if row else None
    )  # fmt: skip
    match = None
    if existing is None:
        fp = conn.execute(
            """select id, status, last_seen_at, repost_count from jobs
               where fingerprint = %s order by last_seen_at desc limit 1""",
            (job.fingerprint,),
        ).fetchone()
        if fp:
            match = FingerprintMatch(str(fp["id"]), fp["status"], fp["last_seen_at"], fp["repost_count"])

    d = classify(existing, raw.source_posted_at, match, now)
    if d.action == "insert":
        job_id = _insert_job(conn, job, d, now)
        _upsert_source(conn, job_id, company.id, job, now)
        return True
    if d.action == "attach":
        conn.execute(
            "update jobs set last_seen_at = %s, miss_count = 0 where id = %s", (now, d.job_id)
        )
        _upsert_source(conn, d.job_id, company.id, job, now)
        return False
    _update_job(conn, d.job_id, job, d, now)
    _upsert_source(conn, d.job_id, company.id, job, now)
    return False


def _open_jobs(conn: psycopg.Connection, company_id: int, source: str) -> list[OpenJob]:
    rows = conn.execute(
        """select j.id, j.miss_count, array_agg(js.source_job_id) as ids
           from jobs j join job_sources js on js.job_id = j.id
           where j.status = 'open' and js.company_id = %s and js.source = %s
           group by j.id, j.miss_count""",
        (company_id, source),
    ).fetchall()
    return [OpenJob(str(r["id"]), r["miss_count"], frozenset(r["ids"])) for r in rows]


def _apply_closures(conn: psycopg.Connection, plan: ClosurePlan, now: datetime) -> None:
    if plan.reset:
        conn.execute("update jobs set miss_count = 0 where id = any(%s::uuid[])", (plan.reset,))
    if plan.increment:
        conn.execute(
            "update jobs set miss_count = miss_count + 1 where id = any(%s::uuid[])",
            (plan.increment,),
        )
    if plan.close:
        conn.execute(
            """update jobs set status = 'closed', closed_at = %s, miss_count = miss_count + 1,
                               updated_at = %s
               where id = any(%s::uuid[])""",
            (now, now, plan.close),
        )


def _touch_seen(conn: psycopg.Connection, company_id: int, source: str, seen: list[str], now: datetime) -> None:
    conn.execute(
        """update jobs set last_seen_at = %(now)s, miss_count = 0
           where status = 'open' and id in (
             select job_id from job_sources
             where company_id = %(cid)s and source = %(src)s and source_job_id = any(%(seen)s))""",
        {"now": now, "cid": company_id, "src": source, "seen": seen},
    )
    conn.execute(
        """update job_sources set last_seen_at = %(now)s
           where company_id = %(cid)s and source = %(src)s and source_job_id = any(%(seen)s)""",
        {"now": now, "cid": company_id, "src": source, "seen": seen},
    )


def ingest(conn: psycopg.Connection, outcome: CompanyOutcome, now: datetime) -> IngestStats:
    """Write one company's poll result in a single transaction."""
    company = outcome.company
    with conn.transaction():
        if not outcome.ok:
            is_404 = outcome.status == 404
            conn.execute(
                """update companies set last_polled_at = %(now)s, fail_count = fail_count + 1,
                     consecutive_404s = case when %(is_404)s then consecutive_404s + 1 else 0 end,
                     tier = case when %(is_404)s and consecutive_404s + 1 >= %(limit)s
                                 then 'inactive' else tier end
                   where id = %(id)s""",
                {"now": now, "is_404": is_404, "limit": INACTIVE_AFTER_404S, "id": company.id},
            )
            return IngestStats()

        source = company.ats
        stats = IngestStats(seen=len(outcome.seen_ids))
        if outcome.unchanged:
            _touch_seen(conn, company.id, source, sorted(outcome.seen_ids), now)
        else:
            stats.new = sum(_ingest_job(conn, company, job, now) for job in outcome.jobs)

        plan = plan_closures(_open_jobs(conn, company.id, source), outcome.seen_ids)
        _apply_closures(conn, plan, now)
        stats.closed = len(plan.close)

        conn.execute(
            """update companies set last_polled_at = %(now)s, last_success_at = %(now)s,
                 fail_count = 0, consecutive_404s = 0, job_ids_hash = %(hash)s,
                 last_intern_seen_at = case when %(interns)s then %(now)s
                                            else last_intern_seen_at end
               where id = %(id)s""",
            {"now": now, "hash": outcome.ids_hash, "interns": bool(outcome.jobs), "id": company.id},
        )
    return stats


def record_run(
    conn: psycopg.Connection,
    *,
    workflow: str,
    source: str,
    started_at: datetime,
    finished_at: datetime,
    companies_polled: int,
    jobs_seen: int,
    jobs_new: int,
    jobs_closed: int,
    errors: int,
    error_samples: list[dict[str, Any]],
) -> None:
    conn.execute(
        """insert into scrape_runs (workflow, source, started_at, finished_at, companies_polled,
                                    jobs_seen, jobs_new, jobs_closed, errors, error_samples)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (workflow, source, started_at, finished_at, companies_polled, jobs_seen, jobs_new,
         jobs_closed, errors, Jsonb(error_samples[:20])),
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest scraper/tests/test_db_ingest.py scraper/tests/test_db_schema.py -v`
Expected: all pass (none skipped).

- [ ] **Step 5: Lint and full suite**

Run: `uv run ruff check . && uv run ruff format . && uv run pytest -q`
Expected: clean; all pass.

- [ ] **Step 6: Commit**

```bash
git add scraper/db.py scraper/tests/test_db_ingest.py
git commit -m "Add database ingest with dedupe, closing and failure tracking"
```

---

### Task 17: CLI, seed list, and live smoke test

**Files:**
- Create: `scraper/__main__.py`, `data/companies.seed.yml`, `scraper/tests/test_cli.py`

**Interfaces:**
- Consumes: `db.*` (Tasks 14, 16), `poll` (Task 15), `Fetcher` (Task 10), `ADAPTERS`.
- Produces: `python -m scraper migrate | seed [PATH] [--verify] | run [--tier T] [--company SLUG] [--ats ATS] [--limit N] [--dry-run]`; `main(argv: list[str] | None = None) -> int`; `load_seeds(path: Path) -> list[dict]`.

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_cli.py`

```python
from pathlib import Path

import pytest

from scraper.__main__ import load_seeds, main

ROOT = Path(__file__).resolve().parents[2]


def test_seed_file_is_valid():
    seeds = load_seeds(ROOT / "data" / "companies.seed.yml")
    assert len(seeds) >= 20
    assert {s["ats"] for s in seeds} <= {"greenhouse", "lever", "ashby"}
    keys = [(s["ats"], s["slug"]) for s in seeds]
    assert len(keys) == len(set(keys))


def test_load_seeds_rejects_bad_entries(tmp_path):
    bad = tmp_path / "seed.yml"
    bad.write_text("- name: X\n  ats: taleo\n  slug: x\n")
    with pytest.raises(ValueError, match="taleo"):
        load_seeds(bad)


def test_run_requires_database_url_unless_offline_dry_run(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        main(["run", "--tier", "hot"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scraper/tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.__main__'`

- [ ] **Step 3: Write the seed list** — `data/companies.seed.yml`

Slugs are best-known values; Step 6 verifies them live and you remove any that fail.

```yaml
# Curated tech companies polled every 5 minutes (tier: hot).
# ats: greenhouse | lever | ashby. slug: the board token in the ATS URL.
- {name: Stripe, ats: greenhouse, slug: stripe, domain: stripe.com, hot: true}
- {name: Airbnb, ats: greenhouse, slug: airbnb, domain: airbnb.com, hot: true}
- {name: Databricks, ats: greenhouse, slug: databricks, domain: databricks.com, hot: true}
- {name: Robinhood, ats: greenhouse, slug: robinhood, domain: robinhood.com, hot: true}
- {name: Coinbase, ats: greenhouse, slug: coinbase, domain: coinbase.com, hot: true}
- {name: Figma, ats: greenhouse, slug: figma, domain: figma.com, hot: true}
- {name: Discord, ats: greenhouse, slug: discord, domain: discord.com, hot: true}
- {name: Reddit, ats: greenhouse, slug: reddit, domain: reddit.com, hot: true}
- {name: Pinterest, ats: greenhouse, slug: pinterest, domain: pinterest.com, hot: true}
- {name: Lyft, ats: greenhouse, slug: lyft, domain: lyft.com, hot: true}
- {name: Instacart, ats: greenhouse, slug: instacart, domain: instacart.com, hot: true}
- {name: Dropbox, ats: greenhouse, slug: dropbox, domain: dropbox.com, hot: true}
- {name: Cloudflare, ats: greenhouse, slug: cloudflare, domain: cloudflare.com, hot: true}
- {name: Datadog, ats: greenhouse, slug: datadog, domain: datadoghq.com, hot: true}
- {name: MongoDB, ats: greenhouse, slug: mongodb, domain: mongodb.com, hot: true}
- {name: GitLab, ats: greenhouse, slug: gitlab, domain: gitlab.com, hot: true}
- {name: Affirm, ats: greenhouse, slug: affirm, domain: affirm.com, hot: true}
- {name: Brex, ats: greenhouse, slug: brex, domain: brex.com, hot: true}
- {name: Samsara, ats: greenhouse, slug: samsara, domain: samsara.com, hot: true}
- {name: Scale AI, ats: greenhouse, slug: scaleai, domain: scale.com, hot: true}
- {name: Anthropic, ats: greenhouse, slug: anthropic, domain: anthropic.com, hot: true}
- {name: Faire, ats: greenhouse, slug: faire, domain: faire.com, hot: true}
- {name: Roblox, ats: greenhouse, slug: roblox, domain: roblox.com, hot: true}
- {name: Twitch, ats: greenhouse, slug: twitch, domain: twitch.tv, hot: true}
- {name: Duolingo, ats: greenhouse, slug: duolingo, domain: duolingo.com, hot: true}
- {name: Asana, ats: greenhouse, slug: asana, domain: asana.com, hot: true}
- {name: Okta, ats: greenhouse, slug: okta, domain: okta.com, hot: true}
- {name: Elastic, ats: greenhouse, slug: elastic, domain: elastic.co, hot: true}
- {name: Vercel, ats: greenhouse, slug: vercel, domain: vercel.com, hot: true}
- {name: Wealthsimple, ats: greenhouse, slug: wealthsimple, domain: wealthsimple.com, hot: true}
- {name: Palantir, ats: lever, slug: palantir, domain: palantir.com, hot: true}
- {name: Plaid, ats: lever, slug: plaid, domain: plaid.com, hot: true}
- {name: Spotify, ats: lever, slug: spotify, domain: spotify.com, hot: true}
- {name: OpenAI, ats: ashby, slug: openai, domain: openai.com, hot: true}
- {name: Ramp, ats: ashby, slug: ramp, domain: ramp.com, hot: true}
- {name: Notion, ats: ashby, slug: notion, domain: notion.so, hot: true}
- {name: Linear, ats: ashby, slug: linear, domain: linear.app, hot: true}
- {name: Cohere, ats: ashby, slug: cohere, domain: cohere.com, hot: true}
- {name: Supabase, ats: ashby, slug: supabase, domain: supabase.com, hot: true}
```

- [ ] **Step 4: Implement** — `scraper/__main__.py`

```python
import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from scraper import db
from scraper.adapters import ADAPTERS
from scraper.http import Fetcher
from scraper.models import Company, CompanyOutcome
from scraper.pipeline import poll

DEFAULT_SEED = Path("data/companies.seed.yml")


def load_seeds(path: Path) -> list[dict[str, Any]]:
    seeds = yaml.safe_load(path.read_text()) or []
    for s in seeds:
        if s.get("ats") not in ADAPTERS or not s.get("slug") or not s.get("name"):
            raise ValueError(f"bad seed entry: {s}")
    return seeds


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")
    return dsn


async def _poll_all(companies: list[Company]) -> list[CompanyOutcome]:
    async with Fetcher() as fetcher:
        return await asyncio.gather(*(poll(fetcher, c) for c in companies))


def _print_outcomes(outcomes: list[CompanyOutcome]) -> None:
    for o in outcomes:
        c = o.company
        if not o.ok:
            print(f"✗ {c.ats}/{c.slug}: {o.error}")
            continue
        print(f"✓ {c.ats}/{c.slug}: {len(o.seen_ids)} postings, {len(o.jobs)} CA/US tech internships")
        for j in o.jobs:
            pay = f"{j.pay.currency} {j.pay.hourly_min:g}-{j.pay.hourly_max:g}/h" if j.pay else "-"
            print(
                f"    [{j.location.country}] {j.raw.title} | {j.raw.location_raw} | {j.term or '-'}"
                f" | {pay} | visa={j.visa_status} {j.visa_signals} | {j.flags}"
            )


def cmd_migrate(_: argparse.Namespace) -> int:
    applied = db.migrate(db.connect(_dsn()))
    print(f"applied: {applied or 'nothing (up to date)'}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    seeds = load_seeds(args.path)
    if args.verify:
        companies = [Company(id=0, name=s["name"], ats=s["ats"], slug=s["slug"]) for s in seeds]
        outcomes = asyncio.run(_poll_all(companies))
        _print_outcomes(outcomes)
        failed = [o.company.slug for o in outcomes if not o.ok]
        print(f"\n{len(seeds) - len(failed)}/{len(seeds)} boards OK. Failed: {failed or 'none'}")
        return 1 if failed else 0
    print(f"upserted {db.upsert_companies(db.connect(_dsn()), seeds)} companies")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    started = datetime.now(UTC)
    if args.dry_run and args.company and args.ats:
        company = Company(id=0, name=args.company, ats=args.ats, slug=args.company)
        _print_outcomes(asyncio.run(_poll_all([company])))
        return 0

    conn = db.connect(_dsn())
    companies = db.get_companies(
        conn, ats=[args.ats] if args.ats else list(ADAPTERS), tier=args.tier,
        slug=args.company, limit=args.limit,
    )  # fmt: skip
    outcomes = asyncio.run(_poll_all(companies))
    if args.dry_run:
        _print_outcomes(outcomes)
        return 0

    new = closed = seen = 0
    errors: list[dict[str, Any]] = []
    for o in outcomes:
        try:
            stats = db.ingest(conn, o, datetime.now(UTC))
        except Exception as e:  # one bad company must not stop the run
            errors.append({"company": o.company.slug, "error": f"ingest {type(e).__name__}: {e}"})
            continue
        new, closed, seen = new + stats.new, closed + stats.closed, seen + stats.seen
        if not o.ok:
            errors.append({"company": o.company.slug, "error": o.error})

    db.record_run(
        conn, workflow=f"scrape-{args.tier or 'manual'}", source="ats", started_at=started,
        finished_at=datetime.now(UTC), companies_polled=len(outcomes), jobs_seen=seen,
        jobs_new=new, jobs_closed=closed, errors=len(errors), error_samples=errors,
    )  # fmt: skip
    print(f"polled={len(outcomes)} seen={seen} new={new} closed={closed} errors={len(errors)}")
    for e in errors[:10]:
        print(f"  ✗ {e['company']}: {e['error']}")
    # Fail the workflow only when everything failed (systemic problem, e.g. DB or network down).
    return 1 if outcomes and len(errors) == len(outcomes) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="apply supabase/migrations to DATABASE_URL")

    seed = sub.add_parser("seed", help="upsert companies from a seed file")
    seed.add_argument("path", nargs="?", type=Path, default=DEFAULT_SEED)
    seed.add_argument("--verify", action="store_true", help="only check each board responds")

    run = sub.add_parser("run", help="poll companies and write jobs")
    run.add_argument("--tier", choices=["hot", "warm", "cold"])
    run.add_argument("--company", help="only this slug")
    run.add_argument("--ats", choices=sorted(ADAPTERS))
    run.add_argument("--limit", type=int, default=1000)
    run.add_argument("--dry-run", action="store_true",
                     help="print instead of writing; with --company and --ats needs no database")

    args = parser.parse_args(argv)
    handlers = {"migrate": cmd_migrate, "seed": cmd_seed, "run": cmd_run}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest scraper/tests/test_cli.py -v`
Expected: 3 passed.

- [ ] **Step 6: Live smoke test against real boards (network, no database)**

Run: `uv run python -m scraper run --dry-run --company stripe --ats greenhouse`
Expected: `✓ greenhouse/stripe: N postings, M CA/US tech internships` followed by job lines. Read a few: country, pay, visa and flags should look right. If something is clearly misparsed, add that phrase as a new test case in the relevant test file (Tasks 4–9), fix, and re-run.

Run: `uv run python -m scraper seed --verify`
Expected: a ✓/✗ line per company and a summary. **Delete every ✗ entry from `data/companies.seed.yml`** (wrong slug or wrong ATS), then re-run until it exits 0.

- [ ] **Step 7: Commit**

```bash
git add scraper/__main__.py scraper/tests/test_cli.py data/companies.seed.yml
git commit -m "Add scraper CLI and verified seed company list"
```

---

### Task 18: GitHub Actions (CI + scrape-hot)

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/scrape-hot.yml`
- Modify: `README.md`

- [ ] **Step 1: Write** `.github/workflows/ci.yml`

```yaml
name: ci
on:
  push:
  pull_request:

jobs:
  scraper:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest -q
```

- [ ] **Step 2: Write** `.github/workflows/scrape-hot.yml`

```yaml
name: scrape-hot
on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:

concurrency:
  group: scrape-hot
  cancel-in-progress: false

jobs:
  scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen --no-dev
      - name: Scrape hot companies
        run: uv run python -m scraper run --tier hot
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

- [ ] **Step 3: Update** `README.md` — replace the `**Status:** planning.` line and below with:

```markdown
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
```

- [ ] **Step 4: Validate locally and push**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: clean; all pass.

```bash
git add .github README.md
git commit -m "Add CI and 5-minute scrape workflow"
git push
```

Run: `gh run watch $(gh run list --workflow ci.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status`
Expected: CI succeeds. (`scrape-hot` will fail until Task 19 adds the secret — that's expected.)

---

### Task 19: Provision Supabase and go live (needs the owner)

**Files:** none (configuration). `.env` stays untracked.

- [ ] **Step 1 (owner): Create the Supabase project**

At supabase.com → New project (Free plan). Region: closest to you (e.g. Canada Central or US East). Save the database password.

- [ ] **Step 2 (owner): Get the session pooler URI**

Project → **Connect** → *Connection string* → **Session pooler** (not "Direct" — GitHub runners have no IPv6). It looks like:
`postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`
Put it in `.env` as `DATABASE_URL=...`.

- [ ] **Step 3: Apply schema and seed**

```bash
uv run --env-file .env python -m scraper migrate
uv run --env-file .env python -m scraper seed
```
Expected: `applied: ['20261007000000_init.sql']`, then `upserted N companies`.

- [ ] **Step 4: First real run locally**

Run: `uv run --env-file .env python -m scraper run --tier hot`
Expected: `polled=N seen=… new=… closed=0 errors=…` with `new > 0`.

- [ ] **Step 5 (owner): Add the GitHub secret**

In the Claude Code prompt, run: `! gh secret set DATABASE_URL` and paste the URI when prompted (keeps it out of the transcript and shell history).

- [ ] **Step 6: Trigger the workflow and confirm**

```bash
gh workflow run scrape-hot.yml
gh run list --workflow scrape-hot.yml --limit 3   # repeat until the new workflow_dispatch run appears
gh run watch <run-id> --exit-status
```
Expected: success; log ends with `polled=N … new=0 …` (jobs already inserted by Step 4).

- [ ] **Step 7: Verify data in Supabase** (SQL editor)

```sql
select country, visa_status, count(*) from jobs where status = 'open' group by 1, 2 order by 1, 2;
select workflow, finished_at, companies_polled, jobs_new, errors from scrape_runs order by id desc limit 5;
```
Expected: rows for CA/US/BOTH; `scrape_runs` gains a row roughly every 5–20 minutes once the schedule kicks in.

---

## Self-Review Notes

- Spec coverage (phase 1): §3 tier-1 adapters (Tasks 11–13), intern/tech filter (Task 4), §4 tables + fingerprint + freshness + closing (Tasks 3, 14, 16), §5 visa/pay/location/term/flags (Tasks 5–9), §6 `scrape-hot`, concurrency, change detection, politeness, secrets (Tasks 10, 15, 18, 19), §7 error handling (Tasks 10, 11, 15, 16, 17), §10 adapter/enrichment/dedupe/DB/CI tests.
- Deferred to later phase plans, per spec §11: Workday/SmartRecruiters/Workable, Simplify + discovery, tiering + `scrape-sweep` + `maintenance`/`STATS.md`, LinkedIn, H-1B import, digest, website, Simplify/LinkedIn closing rules, Greenhouse structured pay (needs a per-job request).
