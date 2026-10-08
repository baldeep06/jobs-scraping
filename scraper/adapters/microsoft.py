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
    locations = item.get("standardizedLocations") or item.get("locations") or []
    return {
        "source": SOURCE,
        "source_job_id": _key(item),
        "title": item.get("name") or "",
        "url": detail.get("publicUrl") or f"{BASE}{item.get('positionUrl') or ''}",
        "location_raw": " | ".join(locations),
        "description_text": html_to_text(detail.get("jobDescription") or ""),
        "source_posted_at": (
            datetime.fromtimestamp(posted, UTC) if isinstance(posted, int | float) else None
        ),
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
            if "count" not in body:
                raise FetchError("unexpected Microsoft payload (no result count)")
            count = int(body["count"] or 0)
        items.extend(body["positions"])
        if not body["positions"] or len(items) >= count:
            break
    return items, count


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    found: list[dict[str, Any]] = []
    counts: list[int] = []
    truncated = False
    for query in QUERIES:
        for location in LOCATIONS:
            items, count = await _search(fetcher, query, location)
            found.extend(items)
            counts.append(count)
            truncated = truncated or len(items) < count
    items = dedupe_by(found, _key)

    want = {
        _key(i): detail_url(i["id"]) for i in items if i.get("id") and wanted(i.get("name") or "")
    }
    details, pending = await fetch_details(fetcher, company, {_key(i) for i in items}, want)
    records = [
        _record(i, (details.get(_key(i)) or {}).get("data") or {})
        for i in items
        if _key(i) not in pending
    ]
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items and not any(counts)
    result.truncated = truncated
    return result
