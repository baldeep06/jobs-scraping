import asyncio
import json
import re
from datetime import datetime
from typing import Any

from scraper.adapters.base import dedupe_by, unchanged_board, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# iCIMS career portals ("careers-<name>.icims.com"). The portal host is kept in `workday_host`.
# There is no JSON API: the search page is HTML (20 rows per page) and every posting page carries
# a schema.org JobPosting block.
QUERIES = ("intern", "co-op")
MAX_PAGES = 15
_ROW = re.compile(
    r'<a[^>]+href="(https?://[^"]*?/jobs/(\d+)/[^"/]*/job)[^"]*"[^>]*>(.*?)</a>', re.S | re.I
)
_PAGES = re.compile(r"Page\s+\d+\s+of\s+(\d+)")
_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def _host(company: Company) -> str:
    if not company.workday_host:
        raise FetchError("icims company is missing its portal host")
    return company.workday_host


def parse_list(html: str) -> tuple[list[dict[str, str]], int]:
    """Rows (id, url, title) on one search page and the number of pages."""
    if "iCIMS" not in html:
        raise FetchError("unexpected iCIMS page (not a portal search result)")
    rows = []
    for url, job_id, inner in _ROW.findall(html):
        title = html_to_text(inner).replace("Job Title", "").strip()
        rows.append({"id": job_id, "url": url, "title": title})
    m = _PAGES.search(html)
    return rows, int(m.group(1)) if m else 1


def _posting(html: str) -> dict[str, Any]:
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _location(posting: dict[str, Any]) -> str:
    places = posting.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    out = []
    for place in places:
        a = (place.get("address") or {}) if isinstance(place, dict) else {}
        text = ", ".join(
            x
            for x in (a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry"))
            if x
        )
        if text:
            out.append(text)
    return " | ".join(out)


def _posted(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _search(fetcher: Fetcher, host: str, query: str) -> tuple[list[dict[str, str]], bool]:
    rows: list[dict[str, str]] = []
    pages = 1
    for page_no in range(MAX_PAGES):
        url = f"https://{host}/jobs/search?ss=1&searchKeyword={query}&in_iframe=1&pr={page_no}"
        found, pages = parse_list(await fetcher.text("GET", url))
        rows.extend(found)
        if not found or page_no + 1 >= pages:
            break
    return rows, pages > MAX_PAGES


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host = _host(company)
    found: list[dict[str, str]] = []
    truncated = False
    for query in QUERIES:
        rows, capped = await _search(fetcher, host, query)
        found.extend(rows)
        truncated = truncated or capped
    items = dedupe_by(found, lambda i: f"{host}:{i['id']}")

    def key(item: dict[str, str]) -> str:
        return f"{host}:{item['id']}"

    want = {key(i): i["url"] for i in items if wanted(i["title"])}
    pages: dict[str, str] = {}
    pending: set[str] = set()
    if want:
        details, pending = await _read_pages(fetcher, company, {key(i) for i in items}, want)
        pages = details
    records = []
    for i in items:
        if key(i) in pending:
            continue
        posting = _posting(pages.get(key(i), ""))
        records.append(
            {
                "source": "icims",
                "source_job_id": key(i),
                "title": posting.get("title") or i["title"],
                "url": i["url"],
                "location_raw": _location(posting),
                "description_text": html_to_text(str(posting.get("description") or "")),
                "source_posted_at": _posted(posting.get("datePosted")),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items
    result.truncated = truncated
    return result


async def _read_pages(
    fetcher: Fetcher, company: Company, all_ids: set[str], want: dict[str, str]
) -> tuple[dict[str, str], set[str]]:
    """Like fetch_details, for HTML pages."""
    if unchanged_board(company, all_ids):
        return {}, set()

    async def one(k: str, url: str) -> tuple[str, str | None]:
        try:
            return k, await fetcher.text("GET", url)
        except FetchError:
            return k, None

    pairs = await asyncio.gather(*(one(k, u) for k, u in want.items()))
    pages = {k: v for k, v in pairs if v}
    return pages, set(want) - set(pages)
