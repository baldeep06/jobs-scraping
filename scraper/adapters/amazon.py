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
    keys = ("description", "basic_qualifications", "preferred_qualifications")
    parts = (html_to_text(item.get(k) or "") for k in keys)
    return {
        "source": SOURCE,
        "source_job_id": str(item.get("id_icims") or ""),
        "title": item.get("title") or "",
        "url": f"https://www.amazon.jobs{item.get('job_path') or ''}",
        "location_raw": item.get("normalized_location") or item.get("location") or "",
        "description_text": "\n".join(p for p in parts if p),
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
            if "hits" not in data:
                raise FetchError("unexpected Amazon payload (no hit count)")
            hits = int(data["hits"] or 0)
        items.extend(data["jobs"])
        if not data["jobs"] or len(items) >= hits:
            break
    return items, hits


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    found: list[dict[str, Any]] = []
    totals: list[int] = []
    truncated = False
    for query in QUERIES:
        items, hits = await _search(fetcher, query)
        found.extend(items)
        totals.append(hits)
        truncated = truncated or len(items) < hits
    items = dedupe_by(found, lambda i: str(i.get("id_icims") or ""))
    result = validate(_record(i) for i in items)
    result.confirmed_empty = not items and not any(totals)
    result.truncated = truncated
    return result
