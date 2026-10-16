import asyncio
import html as htmllib
import json
import re
import weakref
from datetime import datetime
from typing import Any

from scraper.adapters.base import posting_location, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# intern-list.com (run by Jobright): daily-updated internship lists rendered as plain HTML.
# A backup source for companies we have no other way to read; the slug is the company name as
# intern-list writes it. The lists are read once per run (per Fetcher), and posting pages are
# opened one at a time, DELAY seconds apart, and only for postings not seen before.
SOURCE = "internlist"
SITE = "https://www.intern-list.com"
LISTS = ("swe-intern-list", "da-intern-list", "pm-intern-list")
MAX_PAGES = 10
DELAY = 2.0

_ROW = re.compile(
    r'<a href="(/[a-z0-9-]+/([^"/]+))"[^>]*>\s*<div class="w-layout-hflex joblist">\s*'
    r'<p class="jobtitle">(.*?)</p>.*?<p class="companyname_list">(.*?)</p>',
    re.S,
)
_LD_JSON = re.compile(r"<script[^>]*type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", re.S)
_CLOSED_TEXT = "This job has closed."
_DIV_TAG = re.compile(r'<div(?:\s+class="([^"]*)")?[^>]*>|</div>')
_PERIODS = {"HOUR": "hour", "WEEK": "week", "MONTH": "month", "YEAR": "year"}

_lists: "weakref.WeakKeyDictionary[Fetcher, asyncio.Task[list[dict[str, str]]]]" = (
    weakref.WeakKeyDictionary()
)
_turns: "weakref.WeakKeyDictionary[Fetcher, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_list(page: str) -> tuple[list[dict[str, str]], bool]:
    """(rows, whether there is a next page)."""
    if "w-dyn-items" not in page and "w-dyn-empty" not in page:
        raise FetchError("unexpected intern-list page (not a job list)")
    rows = [
        {
            "path": path,
            "id": m.group(1) if (m := re.search(r"_(\d+)$", slug)) else slug,
            "title": htmllib.unescape(title).strip(),
            "company": htmllib.unescape(company).strip(),
        }
        for path, slug, title, company in _ROW.findall(page)
    ]
    return rows, "w-pagination-next" in page


async def _polite(fetcher: Fetcher, url: str) -> str:
    """One intern-list request at a time across the whole run, DELAY seconds apart."""
    async with _turns.setdefault(fetcher, asyncio.Lock()):
        try:
            return await fetcher.text("GET", url)
        finally:
            await asyncio.sleep(DELAY)


async def _read_lists(fetcher: Fetcher) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in LISTS:
        page_param = ""
        for page_no in range(1, MAX_PAGES + 1):
            page = await _polite(fetcher, f"{SITE}/{name}{page_param}")
            found, more = parse_list(page)
            rows.extend(found)
            m = re.search(rf'href="\?([a-z0-9]+_page)={page_no + 1}"', page)
            if not found or not more or not m:
                break
            page_param = f"?{m.group(1)}={page_no + 1}"
    return rows


async def _all_rows(fetcher: Fetcher) -> list[dict[str, str]]:
    task = _lists.get(fetcher)
    if task is None:
        task = _lists[fetcher] = asyncio.ensure_future(_read_lists(fetcher))
    try:
        return await asyncio.shield(task)
    except FetchError as e:
        _lists.pop(fetcher, None)  # let the next company retry
        # Drop the status: a moved list page is not these companies' boards 404ing.
        raise FetchError(f"intern-list unavailable: {e}") from e


def _posting(page: str) -> dict[str, Any]:
    for block in _LD_JSON.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _closed(page: str) -> bool:
    """Every page carries the "closed" banner; Webflow hides it (w-condition-invisible on an
    enclosing div) while the job is open."""
    at = page.find(_CLOSED_TEXT)
    if at < 0:
        return False
    enclosing: list[str] = []
    for tag in _DIV_TAG.finditer(page, 0, at):
        if tag.group(0) == "</div>":
            if enclosing:
                enclosing.pop()
        else:
            enclosing.append(tag.group(1) or "")
    return not any("w-condition-invisible" in c for c in enclosing)


def _pay(posting: dict[str, Any]) -> dict[str, Any] | None:
    salary = posting.get("baseSalary") or {}
    value = salary.get("value") or {} if isinstance(salary, dict) else {}
    period = _PERIODS.get(str(value.get("unitText") or "").upper())
    if not period:
        return None
    return {
        "min": value.get("minValue"),
        "max": value.get("maxValue"),
        "currency": salary.get("currency"),
        "period": period,
    }


def _posted(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    every = await _all_rows(fetcher)
    if not every:
        raise FetchError("intern-list lists have no rows (layout changed?)")
    name = _norm(company.slug)
    rows = {r["id"]: r for r in every if _norm(r["company"]) == name}
    listed = set(rows)
    known = company.known_ids | company.checked_ids
    records = []
    rejected: set[str] = set()
    for job_id, r in rows.items():
        if job_id in known or not wanted(r["title"]):
            continue
        try:
            page = await _polite(fetcher, SITE + r["path"])
        except FetchError:
            continue  # not remembered, so it is tried again next run
        if _closed(page):
            rejected.add(job_id)  # never open it again
            continue
        posting = _posting(page)
        records.append(
            {
                "source": SOURCE,
                "source_job_id": job_id,
                "title": posting.get("title") or r["title"],
                "url": SITE + r["path"],
                "location_raw": posting_location(posting),
                "description_text": html_to_text(str(posting.get("description") or "")),
                "source_posted_at": _posted(posting.get("datePosted")),
                "pay_structured": _pay(posting),
                "employment_type_hint": ", ".join(posting.get("employmentType") or []),
            }
        )
    result = validate(records)
    # The lists parsed, so a company's missing rows are real; held postings stay open while
    # they are still listed.
    result.confirmed_empty = True
    result.pending_ids = company.known_ids & listed
    result.rejected_ids = rejected
    result.forgotten_ids = company.checked_ids - listed
    return result
