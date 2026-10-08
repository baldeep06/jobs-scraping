from datetime import datetime
from typing import Any

from scraper.adapters.base import dedupe_by, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# "Jibe" career sites (iCIMS's newer front end: careers.docusign.com, jobs.booking.com, ...).
# The site host is kept in `workday_host`; /api/jobs returns full postings, descriptions included.
PAGE = 100
MAX_PAGES = 15
QUERIES = ("intern", "co-op")


def _key(host: str, data: dict[str, Any]) -> str:
    return f"{host}:{data.get('req_id') or data.get('slug') or ''}"


def _posted(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def _search(fetcher: Fetcher, host: str, query: str) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    total = 0
    for page_no in range(1, MAX_PAGES + 1):
        url = f"https://{host}/api/jobs?keywords={query}&page={page_no}&limit={PAGE}"
        data = await fetcher.json("GET", url)
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise FetchError("unexpected Jibe payload")
        if page_no == 1:
            if "totalCount" not in data:
                raise FetchError("unexpected Jibe payload (no result count)")
            total = int(data["totalCount"] or 0)
        rows = [r["data"] for r in data["jobs"] if isinstance(r, dict) and r.get("data")]
        items.extend(rows)
        if not data["jobs"] or len(items) >= total:
            break
    return items, total


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host = company.workday_host
    if not host:
        raise FetchError("jibe company is missing its site host")
    found: list[dict[str, Any]] = []
    totals: list[int] = []
    truncated = False
    for query in QUERIES:
        items, total = await _search(fetcher, host, query)
        found.extend(items)
        totals.append(total)
        truncated = truncated or len(items) < total
    items = dedupe_by(found, lambda d: _key(host, d))

    records = []
    for d in items:
        if not wanted(d.get("title") or "", d.get("employment_type")):
            continue
        place = ", ".join(x for x in (d.get("city"), d.get("state"), d.get("country_code")) if x)
        text = "\n".join(
            html_to_text(str(d.get(f) or ""))
            for f in ("description", "responsibilities", "qualifications")
        )
        records.append(
            {
                "source": "jibe",
                "source_job_id": _key(host, d),
                "title": d.get("title") or "",
                "url": f"https://{host}/jobs/{d.get('slug') or d.get('req_id')}",
                "location_raw": place or d.get("full_location") or "",
                "country_hint": d.get("country_code") or None,
                "description_text": text.strip(),
                "source_posted_at": _posted(d.get("posted_date")),
                "employment_type_hint": d.get("employment_type"),
            }
        )
    result = validate(records)
    result.confirmed_empty = not items and not any(totals)
    result.truncated = truncated
    return result
