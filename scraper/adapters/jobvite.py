import re
from typing import Any

from scraper.adapters.base import dedupe_by, read_pages, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Jobvite career sites (jobs.jobvite.com/<slug>). Everything is HTML: the search list has a title
# and a location per row, the posting page has the description. Jobvite shows no posting dates.
BASE = "https://jobs.jobvite.com"
MAX_PAGES = 20
QUERIES = ("intern", "co-op")
_ROW = re.compile(
    r'class="jv-job-list-name">\s*<a href="(/[^"]+/job/([^"/?]+))[^"]*"[^>]*>(.*?)</a>'
    r'.*?class="jv-job-list-location">(.*?)</td>',
    re.S,
)
_TOTAL = re.compile(r"\d+\s*-\s*\d+\s+of\s+(\d+)")
_META = re.compile(r'class="jv-job-detail-meta"[^>]*>(.*?)</p>', re.S)
_DESCRIPTION = re.compile(r'class="jv-job-detail-description"[^>]*>(.*)', re.S)


def _squash(html: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(html)).strip()


def parse_list(html: str) -> tuple[list[dict[str, str]], int]:
    rows = [
        {"path": path, "id": job_id, "title": _squash(title), "location": _squash(loc)}
        for path, job_id, title, loc in _ROW.findall(html)
    ]
    if not rows and "No results found" not in html:
        raise FetchError("unexpected Jobvite page (not a search result)")
    m = _TOTAL.search(html)
    return rows, int(m.group(1)) if m else len(rows)


def _detail(html: str) -> tuple[str, str]:
    meta = _META.search(html)
    body = _DESCRIPTION.search(html)
    text = _squash(body.group(1)) if body else ""
    return _squash(meta.group(1)) if meta else "", text


async def _search(fetcher: Fetcher, slug: str, query: str) -> tuple[list[dict[str, str]], bool]:
    rows: list[dict[str, str]] = []
    total = 0
    for page_no in range(1, MAX_PAGES + 1):
        paging = f"&p={page_no}" if page_no > 1 else ""  # an explicit p=1 returns no results
        found, total = parse_list(
            await fetcher.text("GET", f"{BASE}/{slug}/search?q={query}{paging}")
        )
        rows.extend(found)
        if not found or len(rows) >= total:
            break
    return rows, len(rows) < total


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    slug = company.slug
    found: list[dict[str, str]] = []
    truncated = False
    for query in QUERIES:
        rows, capped = await _search(fetcher, slug, query)
        found.extend(rows)
        truncated = truncated or capped
    items = dedupe_by(found, lambda i: i["id"])

    def key(item: dict[str, Any]) -> str:
        return f"{slug}:{item['id']}"

    want = {key(i): f"{BASE}{i['path']}" for i in items if wanted(i["title"])}
    pages, pending = await read_pages(fetcher, company, {key(i) for i in items}, want)
    records = []
    for i in items:
        if key(i) in pending or key(i) not in want:
            continue
        meta, description = _detail(pages.get(key(i), ""))
        records.append(
            {
                "source": "jobvite",
                "source_job_id": key(i),
                "title": i["title"],
                "url": f"{BASE}{i['path']}",
                "location_raw": i["location"],
                "description_text": f"{meta}\n{description}".strip(),
                "source_posted_at": None,
            }
        )
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items
    result.truncated = truncated
    return result
