import json
import re
from typing import Any

from scraper.adapters.base import validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "google"
BASE = "https://www.google.com/about/careers/applications/jobs/results/"
MAX_PAGES = 10
QUERIES = ("intern", "co-op")
LOCATIONS = ("United States", "Canada")
_BLOB = re.compile(
    r"AF_initDataCallback\(\{key: 'ds:1', hash: '\d+', data:(.*?), sideChannel", re.S
)
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
    if not (
        isinstance(data, list)
        and len(data) >= 3
        and isinstance(data[0], list)
        and isinstance(data[2], int)
    ):
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
        html = await fetcher.text("GET", page_url(query, location, page_no))
        page_jobs, page_total = parse_page(html)
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
