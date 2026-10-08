import html as htmllib
import re
from datetime import datetime
from typing import Any

from scraper.adapters.base import (
    dedupe_by,
    json_ld_posting,
    posting_location,
    read_pages,
    validate,
    wanted,
)
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# TalentBrew (Radancy) career sites: jobs.intuit.com, careers.synopsys.com, jobs.comcast.com.
# The site host is kept in `workday_host`. Search results are HTML (/search-jobs?k=<query>&p=N) and
# each posting page carries a schema.org JobPosting block.
MAX_PAGES = 15
QUERIES = ("intern", "co-op")
_ROW = re.compile(r'<a href="(/job/[^"]+)"[^>]*data-job-id="(\d+)"[^>]*data-title="([^"]*)"', re.I)
_PAGES = re.compile(r'data-total-pages="(\d+)"')


def parse_list(html: str) -> tuple[list[dict[str, str]], int]:
    if "data-total-results" not in html:
        raise FetchError("unexpected TalentBrew page (not a search result)")
    rows = [
        {"path": path, "id": job_id, "title": htmllib.unescape(title)}
        for path, job_id, title in _ROW.findall(html)
    ]
    m = _PAGES.search(html)
    return rows, int(m.group(1)) if m else 1


def _posted(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def _search(fetcher: Fetcher, host: str, query: str) -> tuple[list[dict[str, str]], bool]:
    rows: list[dict[str, str]] = []
    pages = 1
    for page_no in range(1, MAX_PAGES + 1):
        found, pages = parse_list(
            await fetcher.text("GET", f"https://{host}/search-jobs?k={query}&p={page_no}")
        )
        rows.extend(found)
        if not found or page_no >= pages:
            break
    return rows, pages > MAX_PAGES


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host = company.workday_host
    if not host:
        raise FetchError("talentbrew company is missing its site host")
    found: list[dict[str, str]] = []
    truncated = False
    for query in QUERIES:
        rows, capped = await _search(fetcher, host, query)
        found.extend(rows)
        truncated = truncated or capped
    items = dedupe_by(found, lambda i: i["id"])

    def key(item: dict[str, str]) -> str:
        return f"{host}:{item['id']}"

    want = {key(i): f"https://{host}{i['path']}" for i in items if wanted(i["title"])}
    pages, pending = await read_pages(fetcher, company, {key(i) for i in items}, want)
    records = []
    for i in items:
        if key(i) in pending or key(i) not in want:
            continue
        posting = json_ld_posting(pages.get(key(i), ""))
        records.append(
            {
                "source": "talentbrew",
                "source_job_id": key(i),
                "title": posting.get("title") or i["title"],
                "url": f"https://{host}{i['path']}",
                "location_raw": posting_location(posting),
                "description_text": html_to_text(str(posting.get("description") or "")),
                "source_posted_at": _posted(posting.get("datePosted")),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items
    result.truncated = truncated
    return result
