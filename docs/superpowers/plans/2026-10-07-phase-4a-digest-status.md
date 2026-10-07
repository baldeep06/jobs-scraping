# Phase 4a — Daily Digest and /status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Email the owner a daily digest of new CA/US tech internships (with a health line), and show scraper health on a `/status` page.

**Architecture:** A shared `db.health()` decides whether each scrape workflow is `degraded` (no successful run within its window). The digest selects jobs first seen in the last 24 h from the database using `digest.config.yml`, groups them US / Canada into "top picks" and "all other", renders HTML + text with Jinja, and sends via Resend (stdlib SMTP fallback). `/status` is a server component that reads `scrape_runs`, `companies` and `jobs` with the anon key and applies the same degraded rule (mirrored in TypeScript, unit-tested).

**Tech Stack:** Python 3.12, jinja2 (new), httpx, smtplib (stdlib), pytest; Next.js 16 / React 19 / Vitest.

**Spec:** `docs/superpowers/specs/2026-10-07-intern-job-scraper-design.md` (§6 Health, §8 `/status`, §9 Daily Digest)

## Global Constraints

- Same lint/test rules as Phase 3: `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` with `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/postgres`; web: `pnpm typecheck && pnpm exec vitest run && pnpm build`.
- Digest content (spec §9): jobs with `first_seen_at` in the last 24 h matching `digest.config.yml` (`categories`, `hide_blocked`, `fresh_only`, `min_hourly_pay`), grouped US / Canada; (1) Top picks = visa open (or Canada) + pay listed + fresh; (2) all other new matches (company · role · location · pay · visa · link); (3) health line. **Sent even when empty.** Recipient from `DIGEST_TO`.
- A source is `degraded` if no successful run in 60 min (spec §6). `scrape-hot` window 60 min; `scrape-sweep` window 120 min (it runs every 30 min and is slower).
- `RESEND_API_KEY`, `DIGEST_TO`, `DIGEST_FROM`, SMTP creds are read from the environment only; never printed, logged, or committed. Errors from sending must not echo the key or the recipient address.
- Authorship: every commit is baldeep06 `<92562237+baldeep06@users.noreply.github.com>`; **no** `Co-Authored-By`, no "Generated with" line (user rule). Work on branch `phase-4a-digest-status`.
- Public repo + public Actions logs: the digest workflow must not print the email body or recipient.

## Rulings made while planning

- **"Saved jobs that closed" section is deferred** to the owner-login phase (needs `user_job_state`); the digest has sections 1, 2 and the health line only.
- **Jinja2 as the spec says**, added with `uv add jinja2` (CI uses `--frozen`, so `uv.lock` is committed).
- **Sender:** `DIGEST_FROM` defaults to `Intern Radar <onboarding@resend.dev>`; Resend's sandbox sender only delivers to the Resend account owner's address, which is the intended recipient.
- `fresh_only` defaults to **true** in `digest.config.yml`: backlog (`existing`) and `repost` jobs never appear in the digest.

## Review Focus

- **Empty day:** zero matches still sends a mail that says so and still carries the health line. (Task 3)
- **Degraded source:** a stale or never-run workflow shows as degraded in both the digest and `/status`. (Tasks 1, 3, 6)
- **HTML injection:** job titles/company names come from third-party ATSes; the template must escape them. (Task 3)
- **Send failure:** a rejected send (HTTP 4xx/5xx) exits non-zero with a message that contains neither the API key nor the recipient. (Task 4)
- **A job in both regions:** `BOTH`/`UNKNOWN` country jobs appear under US and Canada, not silently in one. (Task 2)

## File Structure

- Modify `scraper/db.py` — `health()`; create `scraper/digest/{__init__,select,build,send}.py`, `scraper/digest/templates/digest.html.j2`, `digest.config.yml`, `.github/workflows/digest.yml`.
- Modify `scraper/__main__.py` — `digest` command; `pyproject.toml`/`uv.lock` — jinja2.
- Create `web/lib/health.ts`, `web/app/status/page.tsx`; modify `web/components/Header.tsx`.
- Tests: `scraper/tests/test_health.py`, `test_digest.py`, `web/tests/health.test.ts`, `web/tests/status.test.tsx`.

---

### Task 1: `db.health()`

**Files:** Modify `scraper/db.py`; Test `scraper/tests/test_health.py` (create)

**Interfaces:**
- Produces: `db.health(conn, now) -> list[dict]` with keys `workflow: str`, `last_finished_at: datetime | None`, `window_minutes: int`, `degraded: bool`, `errors: int` (errors in the most recent run); constant `db.HEALTH_WINDOWS = {"scrape-hot": 60, "scrape-sweep": 120}`.

- [ ] **Step 1: Write the failing test** — `scraper/tests/test_health.py`:

```python
from datetime import UTC, datetime, timedelta

from scraper import db

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def run(conn, workflow, minutes_ago, errors=0):
    t = NOW - timedelta(minutes=minutes_ago)
    db.record_run(
        conn, workflow=workflow, source="ats", started_at=t, finished_at=t, companies_polled=1,
        jobs_seen=0, jobs_new=0, jobs_closed=0, errors=errors, error_samples=[],
    )  # fmt: skip


def test_health_flags_stale_and_missing_workflows(conn):
    run(conn, "scrape-hot", 10, errors=2)
    run(conn, "scrape-hot", 200)  # an older run must not hide the latest one
    h = {r["workflow"]: r for r in db.health(conn, NOW)}
    assert h["scrape-hot"]["degraded"] is False and h["scrape-hot"]["errors"] == 2
    assert h["scrape-sweep"]["degraded"] is True and h["scrape-sweep"]["last_finished_at"] is None


def test_health_degrades_after_the_window(conn):
    run(conn, "scrape-hot", 61)
    run(conn, "scrape-sweep", 119)
    h = {r["workflow"]: r["degraded"] for r in db.health(conn, NOW)}
    assert h == {"scrape-hot": True, "scrape-sweep": False}
```

- [ ] **Step 2: Run to verify it fails** — `TEST_DATABASE_URL=… uv run pytest scraper/tests/test_health.py -q` → FAIL (`module 'scraper.db' has no attribute 'health'`).

- [ ] **Step 3: Implement** — append to `scraper/db.py`:

```python
HEALTH_WINDOWS = {"scrape-hot": 60, "scrape-sweep": 120}  # minutes without a run => degraded


def health(conn: psycopg.Connection, now: datetime) -> list[dict[str, Any]]:
    rows = {
        r["workflow"]: r
        for r in conn.execute(
            """select distinct on (workflow) workflow, finished_at, errors from scrape_runs
               where workflow = any(%s) order by workflow, finished_at desc""",
            (list(HEALTH_WINDOWS),),
        )
    }
    out = []
    for workflow, window in HEALTH_WINDOWS.items():
        row = rows.get(workflow)
        last = row["finished_at"] if row else None
        stale = last is None or (now - last).total_seconds() > window * 60
        out.append(
            {
                "workflow": workflow,
                "last_finished_at": last,
                "window_minutes": window,
                "degraded": stale,
                "errors": row["errors"] if row else 0,
            }
        )
    return out
```

- [ ] **Step 4: Run to verify it passes** — same command → 2 passed. Then the full suite + ruff.
- [ ] **Step 5: Commit** — `git add scraper && git commit -m "feat: scraper health from recent runs"`

---

### Task 2: Digest selection and config

**Files:** Create `digest.config.yml`, `scraper/digest/__init__.py`, `scraper/digest/select.py`; Test `scraper/tests/test_digest.py` (create)

**Interfaces:**
- Produces: `DigestConfig` (dataclass: `categories: list[str]`, `hide_blocked: bool`, `fresh_only: bool`, `min_hourly_pay: float | None`); `load_config(path: Path) -> DigestConfig`; `select_jobs(conn, since: datetime, cfg: DigestConfig) -> dict[str, Region]` where `Region` is a dataclass `top: list[dict]`, `rest: list[dict]` and the dict keys are `"US"` and `"CA"`. Job dicts carry: `company, title, category, location, term, pay, visa_status, freshness, url`.

- [ ] **Step 1: Config file** — `digest.config.yml`:

```yaml
# Which new internships go into the daily email.
categories: [SWE, Data/ML, Hardware/Embedded, PM, Design, Quant, IT/Security, Other-tech]
hide_blocked: true      # drop jobs the visa rules say you cannot take
fresh_only: true        # only genuinely new postings (no reposts / already-open backlog)
min_hourly_pay: null    # e.g. 25 to drop low or unlisted pay; null keeps everything
```

- [ ] **Step 2: Write the failing tests** — `scraper/tests/test_digest.py`:

```python
from datetime import UTC, datetime, timedelta

from scraper import db
from scraper.digest.select import DigestConfig, load_config, select_jobs
from scraper.tests.test_db_ingest import company

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
CFG = DigestConfig(categories=["SWE", "Data/ML"], hide_blocked=True, fresh_only=True, min_hourly_pay=None)


def add(conn, cid, title, *, country="US", visa="open", freshness="fresh", category="SWE",
        pay=None, hours_ago=2, status="open"):  # fmt: skip
    conn.execute(
        """insert into jobs (company_id, title, normalized_title, category, country, location_raw,
             visa_status, fingerprint, best_url, freshness, pay_hourly_max, pay_currency,
             first_seen_at, status)
           values (%s,%s,%s,%s,%s,'Somewhere',%s,%s,'https://x/'||%s,%s,%s,'USD',%s,%s)""",
        (cid, title, title.lower(), category, country, visa, title, title, freshness, pay,
         NOW - timedelta(hours=hours_ago), status),
    )  # fmt: skip


def titles(rows):
    return [r["title"] for r in rows]


def test_load_config(tmp_path):
    p = tmp_path / "c.yml"
    p.write_text("categories: [SWE]\nhide_blocked: false\nfresh_only: true\nmin_hourly_pay: 25\n")
    assert load_config(p) == DigestConfig(["SWE"], False, True, 25.0)


def test_selection_filters(conn):
    c = company(conn)
    add(conn, c.id, "keep")
    add(conn, c.id, "too old", hours_ago=30)
    add(conn, c.id, "closed", status="closed")
    add(conn, c.id, "blocked", visa="blocked")
    add(conn, c.id, "repost", freshness="repost")
    add(conn, c.id, "backlog", freshness="existing")
    add(conn, c.id, "wrong category", category="PM")
    got = select_jobs(conn, NOW - timedelta(hours=24), CFG)
    assert titles(got["US"].top + got["US"].rest) == ["keep"]


def test_top_picks_need_visa_open_pay_and_fresh(conn):
    c = company(conn)
    add(conn, c.id, "pick", pay=40)
    add(conn, c.id, "no pay")
    add(conn, c.id, "unknown visa", visa="unknown", pay=40)
    got = select_jobs(conn, NOW - timedelta(hours=24), CFG)
    assert titles(got["US"].top) == ["pick"]
    assert sorted(titles(got["US"].rest)) == ["no pay", "unknown visa"]


def test_both_country_jobs_appear_in_both_regions(conn):
    c = company(conn)
    add(conn, c.id, "everywhere", country="BOTH", pay=30)
    add(conn, c.id, "canada only", country="CA")
    got = select_jobs(conn, NOW - timedelta(hours=24), CFG)
    assert "everywhere" in titles(got["US"].top + got["US"].rest)
    assert sorted(titles(got["CA"].top + got["CA"].rest)) == ["canada only", "everywhere"]


def test_min_pay_drops_unlisted_and_low_pay(conn):
    c = company(conn)
    add(conn, c.id, "high", pay=50)
    add(conn, c.id, "low", pay=10)
    add(conn, c.id, "none")
    cfg = DigestConfig(["SWE"], True, True, 25.0)
    got = select_jobs(conn, NOW - timedelta(hours=24), cfg)
    assert titles(got["US"].top + got["US"].rest) == ["high"]
```

- [ ] **Step 3: Run to verify they fail** — `uv run pytest scraper/tests/test_digest.py -q` → FAIL (import error).

- [ ] **Step 4: Implement** — `scraper/digest/__init__.py` (empty) and `scraper/digest/select.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import yaml

REGION_COUNTRIES = {"US": ["US", "BOTH", "UNKNOWN"], "CA": ["CA", "BOTH", "UNKNOWN"]}
FRESH = ("fresh", "recurring")


@dataclass(frozen=True)
class DigestConfig:
    categories: list[str]
    hide_blocked: bool
    fresh_only: bool
    min_hourly_pay: float | None


@dataclass
class Region:
    top: list[dict[str, Any]] = field(default_factory=list)
    rest: list[dict[str, Any]] = field(default_factory=list)


def load_config(path: Path) -> DigestConfig:
    raw = yaml.safe_load(path.read_text()) or {}
    pay = raw.get("min_hourly_pay")
    return DigestConfig(
        categories=list(raw.get("categories") or []),
        hide_blocked=bool(raw.get("hide_blocked", True)),
        fresh_only=bool(raw.get("fresh_only", True)),
        min_hourly_pay=float(pay) if pay is not None else None,
    )


def _pay_text(row: dict[str, Any]) -> str:
    if row["pay_hourly_max"] is None:
        return ""
    lo, hi, cur = row["pay_hourly_min"], row["pay_hourly_max"], row["pay_currency"] or ""
    span = f"{lo:g}-{hi:g}" if lo is not None and lo != hi else f"{hi:g}"
    return f"{cur} {span}/h".strip()


def select_jobs(
    conn: psycopg.Connection, since: datetime, cfg: DigestConfig
) -> dict[str, Region]:
    rows = conn.execute(
        """select j.title, j.category, j.country, j.location_raw, j.term, j.visa_status,
                  j.freshness, j.best_url, j.pay_hourly_min, j.pay_hourly_max, j.pay_currency,
                  c.name as company
           from jobs j join companies c on c.id = j.company_id
           where j.status = 'open' and j.first_seen_at >= %(since)s
             and j.category = any(%(cats)s)
             and (not %(hide)s or j.visa_status <> 'blocked')
             and (not %(fresh)s or j.freshness = any(%(fresh_values)s))
             and (%(min_pay)s::numeric is null or j.pay_hourly_max >= %(min_pay)s)
           order by j.first_seen_at desc""",
        {
            "since": since,
            "cats": cfg.categories,
            "hide": cfg.hide_blocked,
            "fresh": cfg.fresh_only,
            "fresh_values": list(FRESH),
            "min_pay": cfg.min_hourly_pay,
        },
    ).fetchall()
    out = {code: Region() for code in REGION_COUNTRIES}
    for r in rows:
        job = {
            "company": r["company"], "title": r["title"], "category": r["category"],
            "location": r["location_raw"], "term": r["term"], "pay": _pay_text(r),
            "visa_status": r["visa_status"], "freshness": r["freshness"], "url": r["best_url"],
        }  # fmt: skip
        for code, countries in REGION_COUNTRIES.items():
            if r["country"] in countries:
                pick = (
                    (r["visa_status"] == "open" or code == "CA")
                    and r["pay_hourly_max"] is not None
                    and r["freshness"] in FRESH
                )
                (out[code].top if pick else out[code].rest).append(job)
    return out
```

- [ ] **Step 5: Run to verify they pass** — `uv run pytest scraper/tests/test_digest.py -q` → 5 passed; full suite + ruff.
- [ ] **Step 6: Commit** — `git add scraper digest.config.yml && git commit -m "feat: digest job selection and config"`

---

### Task 3: Render the email

**Files:** `uv add jinja2`; Create `scraper/digest/build.py`, `scraper/digest/templates/digest.html.j2`; Test `scraper/tests/test_digest.py`

**Interfaces:**
- Consumes: `select_jobs` output, `db.health` output.
- Produces: `render(regions: dict[str, Region], health: list[dict], now: datetime) -> tuple[str, str, str]` returning `(subject, html, text)`. Subject: `Intern Radar — {n} new internships ({us} US · {ca} CA)` where `n` counts distinct jobs by URL; with none: `Intern Radar — no new internships today`.

- [ ] **Step 1: Add the dependency** — `uv add jinja2` (commit `pyproject.toml` and `uv.lock`).

- [ ] **Step 2: Write the failing tests** — append to `scraper/tests/test_digest.py`:

```python
from scraper.digest.build import render
from scraper.digest.select import Region

HEALTHY = [{"workflow": "scrape-hot", "degraded": False, "last_finished_at": NOW, "errors": 0,
            "window_minutes": 60}]  # fmt: skip


def job(**kw):
    base = dict(company="Acme", title="SWE Intern", category="SWE", location="Toronto, ON",
                term="Summer 2027", pay="CAD 30/h", visa_status="open", freshness="fresh",
                url="https://x/1")  # fmt: skip
    return base | kw


def test_render_lists_jobs_by_region_with_links():
    regions = {"US": Region(), "CA": Region(top=[job()], rest=[job(title="Data Intern", url="https://x/2", pay="")])}
    subject, html, text = render(regions, HEALTHY, NOW)
    assert subject == "Intern Radar — 2 new internships (0 US · 2 CA)"
    assert "https://x/1" in html and "Acme" in html and "Top picks" in html
    assert "Data Intern" in text and "https://x/2" in text


def test_render_empty_day_still_sends_with_health():
    subject, html, text = render({"US": Region(), "CA": Region()}, HEALTHY, NOW)
    assert subject == "Intern Radar — no new internships today"
    assert "No new internships" in html and "All sources healthy" in html


def test_render_shows_degraded_sources():
    bad = [{**HEALTHY[0], "degraded": True}]
    _, html, text = render({"US": Region(), "CA": Region()}, bad, NOW)
    assert "scrape-hot" in html and "degraded" in html.lower() and "degraded" in text.lower()


def test_render_escapes_third_party_text():
    evil = job(title="<script>alert(1)</script>", company="A&B")
    _, html, _ = render({"US": Region(rest=[evil]), "CA": Region()}, HEALTHY, NOW)
    assert "<script>" not in html and "&lt;script&gt;" in html and "A&amp;B" in html
```

- [ ] **Step 3: Run to verify they fail** — import error for `scraper.digest.build`.

- [ ] **Step 4: Implement** — `scraper/digest/templates/digest.html.j2`:

```jinja
<!doctype html>
<html><body style="margin:0;background:#f6f7fb;font-family:Inter,Arial,sans-serif;color:#111827">
<div style="max-width:640px;margin:0 auto;padding:24px 16px">
  <h1 style="font-family:Poppins,Arial,sans-serif;font-size:22px;margin:0 0 4px">Intern Radar</h1>
  <p style="margin:0 0 20px;color:#6b7280">{{ date }} · new tech internships from the last 24 hours</p>
  {% if total == 0 %}
  <p style="background:#fff;border-radius:16px;padding:16px">No new internships matched today.</p>
  {% endif %}
  {% for code, label in [("US", "United States"), ("CA", "Canada")] %}
    {% set region = regions[code] %}
    {% if region.top or region.rest %}
    <h2 style="font-family:Poppins,Arial,sans-serif;font-size:17px;margin:24px 0 8px">{{ label }}</h2>
    {% if region.top %}
      <h3 style="font-size:13px;color:#1b55f5;margin:12px 0 6px">Top picks</h3>
      {% for j in region.top %}{{ row(j) }}{% endfor %}
    {% endif %}
    {% if region.rest %}
      <h3 style="font-size:13px;color:#6b7280;margin:12px 0 6px">All other new matches</h3>
      {% for j in region.rest %}{{ row(j) }}{% endfor %}
    {% endif %}
    {% endif %}
  {% endfor %}
  <p style="margin:28px 0 0;font-size:12px;color:#6b7280">{{ health_line }}</p>
</div></body></html>
```
with the `row` macro defined at the top of the file:

```jinja
{% macro row(j) -%}
<div style="background:#fff;border-radius:16px;padding:12px 16px;margin:0 0 8px">
  <a href="{{ j.url }}" style="color:#111827;font-weight:600;text-decoration:none">{{ j.title }}</a>
  <div style="font-size:13px;color:#6b7280">{{ j.company }} · {{ j.location }}{% if j.term %} · {{ j.term }}{% endif %}{% if j.pay %} · {{ j.pay }}{% endif %} · visa {{ j.visa_status }}</div>
</div>
{%- endmacro %}
```

`scraper/digest/build.py`:

```python
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scraper.digest.select import Region

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def health_line(health: list[dict[str, Any]]) -> str:
    bad = [h["workflow"] for h in health if h["degraded"]]
    return f"Degraded sources: {', '.join(bad)}" if bad else "All sources healthy."


def render(
    regions: dict[str, Region], health: list[dict[str, Any]], now: datetime
) -> tuple[str, str, str]:
    counts = {c: len(r.top) + len(r.rest) for c, r in regions.items()}
    urls = {j["url"] for r in regions.values() for j in r.top + r.rest}
    total = len(urls)
    subject = (
        f"Intern Radar — {total} new internships ({counts['US']} US · {counts['CA']} CA)"
        if total
        else "Intern Radar — no new internships today"
    )
    line = health_line(health)
    html = _env.get_template("digest.html.j2").render(
        regions=regions, total=total, date=f"{now:%A %B %d}", health_line=line
    )
    lines = [subject, ""]
    for code, label in (("US", "United States"), ("CA", "Canada")):
        jobs = regions[code].top + regions[code].rest
        if jobs:
            lines += [label.upper()]
            lines += [
                f"- {j['company']} · {j['title']} · {j['location']} · {j['pay'] or 'pay n/a'}"
                f" · visa {j['visa_status']}\n  {j['url']}"
                for j in jobs
            ]
            lines.append("")
    if not total:
        lines.append("No new internships matched today.")
    lines.append(line)
    return subject, html, "\n".join(lines) + "\n"
```
The template needs `{% set %}` of `health_line`, `regions`, `date`, `total` — the macro `row` must be defined before use; Jinja macros are defined at the top of the file. (The empty-day test expects the exact strings "No new internships" and "All sources healthy"; the template/text above contain them.) Adjust the HTML sentence to read `No new internships matched today.`

- [ ] **Step 5: Run to verify they pass** — `uv run pytest scraper/tests/test_digest.py -q`; fix template syntax errors until green. Full suite + ruff.
- [ ] **Step 6: Commit** — `git add scraper pyproject.toml uv.lock && git commit -m "feat: render the daily digest email"`

---

### Task 4: Send, CLI command, workflow

**Files:** Create `scraper/digest/send.py`, `.github/workflows/digest.yml`; Modify `scraper/__main__.py`; Test `scraper/tests/test_digest.py`

**Interfaces:**
- Produces: `send_email(subject, html, text, env: Mapping[str, str], client: httpx.Client | None = None) -> None` (raises `SendError(message)` with a message that never contains the key or recipient); CLI `python -m scraper digest [--hours 24] [--dry-run] [--out FILE]`.

- [ ] **Step 1: Write the failing tests** — append to `test_digest.py`:

```python
import httpx
import pytest

from scraper.digest.send import SendError, send_email

ENV = {"RESEND_API_KEY": "re_secretkey123", "DIGEST_TO": "me@example.com"}


def test_resend_request_shape():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"id": "1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    send_email("Subj", "<b>hi</b>", "hi", ENV, client=client)
    assert seen["auth"] == "Bearer re_secretkey123"
    assert "me@example.com" in seen["body"] and "Subj" in seen["body"]


def test_send_failure_never_leaks_key_or_recipient():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="bad")))
    with pytest.raises(SendError) as exc:
        send_email("S", "h", "t", ENV, client=client)
    assert "re_secretkey123" not in str(exc.value) and "example.com" not in str(exc.value)
    assert "403" in str(exc.value)


def test_missing_credentials_is_a_clear_error():
    with pytest.raises(SendError, match="RESEND_API_KEY"):
        send_email("S", "h", "t", {"DIGEST_TO": "me@example.com"})
    with pytest.raises(SendError, match="DIGEST_TO"):
        send_email("S", "h", "t", {"RESEND_API_KEY": "k"})


def test_smtp_fallback(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, **kw): sent["host"] = host
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, user, password): sent["user"] = user
        def send_message(self, msg): sent["to"] = msg["To"]

    monkeypatch.setattr("scraper.digest.send.smtplib.SMTP_SSL", FakeSMTP)
    env = {"DIGEST_TRANSPORT": "smtp", "DIGEST_TO": "me@example.com", "SMTP_HOST": "smtp.x.test",
           "SMTP_USER": "u", "SMTP_PASSWORD": "p"}  # fmt: skip
    send_email("S", "<b>h</b>", "t", env)
    assert sent == {"host": "smtp.x.test", "user": "u", "to": "me@example.com"}
```

and a CLI test appended to `scraper/tests/test_cli.py`:

```python
def test_digest_dry_run_prints_subject_and_never_needs_email_secrets(conn, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DATABASE_URL", conn.info.dsn.replace("password=", "password="))  # see Step 3
```
(The CLI test is written in Step 3 once `cmd_digest` exists, using monkeypatching of `_connect` to return the test `conn`; it asserts the output contains `Intern Radar —` and that `--out` writes an HTML file.)

- [ ] **Step 2: Run to verify they fail** — import error for `scraper.digest.send`.

- [ ] **Step 3: Implement** — `scraper/digest/send.py`:

```python
import smtplib
from collections.abc import Mapping
from email.message import EmailMessage

import httpx

DEFAULT_FROM = "Intern Radar <onboarding@resend.dev>"


class SendError(Exception):
    """Raised with a message that is safe to print in a public log."""


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise SendError(f"{name} is not set")
    return value


def send_email(
    subject: str,
    html: str,
    text: str,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
) -> None:
    to = _require(env, "DIGEST_TO")
    sender = env.get("DIGEST_FROM") or DEFAULT_FROM
    if env.get("DIGEST_TRANSPORT") == "smtp":
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, sender, to
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP_SSL(_require(env, "SMTP_HOST"), 465) as smtp:
                smtp.login(_require(env, "SMTP_USER"), _require(env, "SMTP_PASSWORD"))
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            raise SendError(f"SMTP send failed ({type(e).__name__})") from None
        return
    key = _require(env, "RESEND_API_KEY")
    own = client or httpx.Client(timeout=20)
    try:
        resp = own.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={"from": sender, "to": [to], "subject": subject, "html": html, "text": text},
        )
    except httpx.HTTPError as e:
        raise SendError(f"Resend request failed ({type(e).__name__})") from None
    if resp.status_code >= 400:
        raise SendError(f"Resend rejected the email (HTTP {resp.status_code})")
```

`scraper/__main__.py` — add:

```python
def cmd_digest(args: argparse.Namespace) -> int:
    from datetime import timedelta

    from scraper.digest.build import render
    from scraper.digest.select import load_config, select_jobs
    from scraper.digest.send import SendError, send_email

    conn = _connect()
    now = datetime.now(UTC)
    regions = select_jobs(conn, now - timedelta(hours=args.hours), load_config(args.config))
    subject, html, text = render(regions, db.health(conn, now), now)
    if args.out:
        args.out.write_text(html)
    if args.dry_run:
        print(subject)
        return 0
    try:
        send_email(subject, html, text, os.environ)
    except SendError as e:
        print(f"digest not sent: {e}")
        return 1
    print(f"digest sent: {subject}")
    return 0
```
Register `digest` with `--hours` (int, default 24), `--config` (Path, default `digest.config.yml`), `--dry-run`, `--out` (Path). The CLI test monkeypatches `scraper.__main__._connect` to return the fixture `conn` and asserts `main(["digest", "--dry-run", "--out", str(tmp_path / "d.html")])` returns 0, prints a subject starting `Intern Radar —`, and writes HTML.

`.github/workflows/digest.yml`:

```yaml
name: digest
on:
  schedule:
    - cron: "17 12 * * *"
  workflow_dispatch:

concurrency:
  group: digest
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  digest:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen --no-dev
      - name: Send the daily digest
        run: uv run python -m scraper digest
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
          DIGEST_TO: ${{ secrets.DIGEST_TO }}
```

- [ ] **Step 4: Run to verify they pass** — `uv run pytest -q` (full) and ruff. Validate the workflow YAML parses.
- [ ] **Step 5: Commit** — `git add scraper .github && git commit -m "feat: send the daily digest by Resend or SMTP"`

---

### Task 5: `/status` page

**Files:** Create `web/lib/health.ts`, `web/app/status/page.tsx`; Modify `web/components/Header.tsx`; Test `web/tests/health.test.ts`, `web/tests/status.test.tsx`

**Interfaces:**
- Produces: `HEALTH_WINDOWS: Record<string, number>` (`scrape-hot` 60, `scrape-sweep` 120); `workflowHealth(runs: {workflow: string; finished_at: string; errors: number}[], now: Date): {workflow: string; lastFinishedAt: string | null; minutesAgo: number | null; windowMinutes: number; degraded: boolean; errors: number}[]` (uses the most recent run per workflow).

- [ ] **Step 1: Write the failing tests** — `web/tests/health.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { workflowHealth } from "@/lib/health";

const NOW = new Date("2026-10-07T12:00:00Z");
const ago = (m: number) => new Date(NOW.getTime() - m * 60_000).toISOString();

describe("workflowHealth", () => {
  it("uses the latest run per workflow and flags stale or missing ones", () => {
    const h = workflowHealth(
      [
        { workflow: "scrape-hot", finished_at: ago(200), errors: 0 },
        { workflow: "scrape-hot", finished_at: ago(10), errors: 3 },
      ],
      NOW,
    );
    const hot = h.find((x) => x.workflow === "scrape-hot")!;
    const sweep = h.find((x) => x.workflow === "scrape-sweep")!;
    expect(hot).toMatchObject({ degraded: false, minutesAgo: 10, errors: 3 });
    expect(sweep).toMatchObject({ degraded: true, lastFinishedAt: null, minutesAgo: null });
  });

  it("degrades once the window has passed", () => {
    const h = workflowHealth([{ workflow: "scrape-hot", finished_at: ago(61), errors: 0 }], NOW);
    expect(h.find((x) => x.workflow === "scrape-hot")!.degraded).toBe(true);
  });
});
```

and `web/tests/status.test.tsx`: render `<StatusView health={…} counts={…} />` (an exported presentational component from `app/status/page.tsx`'s sibling `components/StatusView.tsx`) and assert it shows "Degraded" for a degraded workflow, "Healthy" otherwise, and the company/job counts.

- [ ] **Step 2: Run to verify they fail** — `pnpm exec vitest run` → module not found.

- [ ] **Step 3: Implement** — `web/lib/health.ts`:

```ts
export const HEALTH_WINDOWS: Record<string, number> = { "scrape-hot": 60, "scrape-sweep": 120 };

export interface RunRow {
  workflow: string;
  finished_at: string;
  errors: number;
}

export interface WorkflowHealth {
  workflow: string;
  lastFinishedAt: string | null;
  minutesAgo: number | null;
  windowMinutes: number;
  degraded: boolean;
  errors: number;
}

export function workflowHealth(runs: RunRow[], now: Date): WorkflowHealth[] {
  return Object.entries(HEALTH_WINDOWS).map(([workflow, windowMinutes]) => {
    const latest = runs
      .filter((r) => r.workflow === workflow)
      .sort((a, b) => b.finished_at.localeCompare(a.finished_at))[0];
    const minutesAgo = latest
      ? Math.round((now.getTime() - new Date(latest.finished_at).getTime()) / 60_000)
      : null;
    return {
      workflow,
      lastFinishedAt: latest?.finished_at ?? null,
      minutesAgo,
      windowMinutes,
      degraded: minutesAgo === null || minutesAgo > windowMinutes,
      errors: latest?.errors ?? 0,
    };
  });
}
```

`web/components/StatusView.tsx` — a presentational component using the existing `Badge` (tone `signal` for Healthy, `tangerine` for Degraded) listing each workflow with "last run N min ago · errors N", plus a counts card (companies by tier, open jobs by region). `web/app/status/page.tsx` — `export const dynamic = "force-dynamic"`; server component using `supabase()` to select `workflow,finished_at,errors` from `scrape_runs` (last 3 hours, ordered desc), `tier` counts from `companies`, and open-job counts (`jobs_feed`, head count per `country` group of US/CA); wrap in try/catch and render an error card like `error.tsx` does. `Header.tsx`: add `<Link href="/status">Status</Link>` next to Jobs.

- [ ] **Step 4: Run to verify they pass** — `pnpm typecheck && pnpm exec vitest run && pnpm build` (build must list `/status` as dynamic).
- [ ] **Step 5: Commit** — `git add web && git commit -m "feat(web): /status page with scraper health"`

---

### Task 6: Live verification, docs, deploy

- [ ] **Step 1: Dry-run against the real database** (no email secrets needed): `set -a && . ./.env && set +a && uv run python -m scraper digest --dry-run --out /tmp/digest.html` → prints a subject; open the HTML and check it visually (screenshot with the existing chromium tooling if available).
- [ ] **Step 2: README** — add `digest` to the commands line and a short "Daily digest" paragraph: needs GitHub secrets `RESEND_API_KEY` and `DIGEST_TO` (and optionally `DIGEST_FROM`); `digest.config.yml` controls what is included.
- [ ] **Step 3: Full verification** — Python suite + ruff; web typecheck/tests/build; `git log --format='%an <%ae>%n%b' main..HEAD | sort | uniq -c` shows only baldeep06 and no `Co-Authored-By`.
- [ ] **Step 4: Commit** — `git add README.md && git commit -m "docs: daily digest"`
- [ ] **Step 5 (after merge, needs the owner):** the owner adds `RESEND_API_KEY` and `DIGEST_TO` as GitHub secrets (`gh secret set`, typed by the owner or piped from their terminal — never pasted into chat), then runs the `digest` workflow once manually (`gh workflow run digest`) and confirms the email arrives; deploy `web/` to Vercel (`vercel deploy --prod --scope bp-c01d`) so `/status` is live.

---

## Self-Review

- **Spec coverage:** §9 digest content (selection, top picks, grouping, empty-day send, health line, Jinja, Resend + SMTP, `DIGEST_TO`) → Tasks 2–4; §6 degraded rule + §8 `/status` → Tasks 1 and 5; the "saved jobs that closed" part of §9 is deferred by ruling.
- **Placeholders:** none (the Task 4 CLI test body is specified by its assertions and written against `cmd_digest` in Step 3).
- **Type consistency:** `Region.top/rest` and job dict keys (Task 2) are exactly what `render` (Task 3) and the template read; `db.health` keys (Task 1) match `health_line`; the TypeScript `WorkflowHealth` mirrors the Python rule and windows.
