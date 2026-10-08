from datetime import datetime
from typing import Any

from scraper.adapters.base import dedupe_by, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult

SOURCE = "apple"
BASE = "https://jobs.apple.com"
MAX_PAGES = 10
# Apple's search is loose full-text ("intern" matches "internal"/"international" in 1,400 jobs);
# its student roles are titled "... Internships", so that is the query that surfaces them.
QUERIES = ("internships", "co-op")
_COUNTRY = {"United States": "US", "United States of America": "US", "Canada": "CA"}


async def _csrf(fetcher: Fetcher) -> str:
    headers = await fetcher.response_headers("GET", f"{BASE}/api/v1/CSRFToken")
    token = headers.get("x-apple-csrf-token")
    if not token:
        raise FetchError("Apple did not issue a CSRF token")
    return token


def _body(query: str, page: int) -> dict[str, Any]:
    return {
        "query": query,
        "filters": {"locations": ["postLocation-USA", "postLocation-CAN"]},
        "page": page,
        "locale": "en-us",
        "sort": "newest",
        "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
    }


def _location(loc: dict[str, Any]) -> str:
    parts = (loc.get("city"), loc.get("stateProvince"), loc.get("countryName"))
    return ", ".join(p for p in parts if p)


def _posted(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _record(item: dict[str, Any]) -> dict[str, Any]:
    locs = item.get("locations") or []
    country = _COUNTRY.get((locs[0].get("countryName") if locs else "") or "", "OTHER")
    pid = str(item.get("positionId") or "")
    return {
        "source": SOURCE,
        "source_job_id": pid,
        "title": item.get("postingTitle") or "",
        "url": f"{BASE}/en-us/details/{pid}/{item.get('transformedPostingTitle') or ''}",
        "location_raw": " | ".join(_location(x) for x in locs if _location(x)),
        "description_text": item.get("jobSummary") or "",
        "source_posted_at": _posted(item.get("postDateInGMT")),
        "country_hint": country,
    }


async def _search(fetcher: Fetcher, token: str, query: str) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    total = 0
    headers = {"x-apple-csrf-token": token, "Origin": BASE}
    for page_no in range(1, MAX_PAGES + 1):
        data = await fetcher.json(
            "POST", f"{BASE}/api/v1/search", json=_body(query, page_no), headers=headers
        )
        res = data.get("res") if isinstance(data, dict) else None
        if not isinstance(res, dict) or not isinstance(res.get("searchResults"), list):
            raise FetchError("unexpected Apple payload")
        if page_no == 1:
            if "totalRecords" not in res:
                raise FetchError("unexpected Apple payload (no result count)")
            total = int(res["totalRecords"] or 0)
        items.extend(res["searchResults"])
        if not res["searchResults"] or len(items) >= total:
            break
    return items, total


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    token = await _csrf(fetcher)
    found: list[dict[str, Any]] = []
    totals: list[int] = []
    truncated = False
    for query in QUERIES:
        items, total = await _search(fetcher, token, query)
        found.extend(items)
        totals.append(total)
        truncated = truncated or len(items) < total
    items = dedupe_by(found, lambda i: str(i.get("positionId") or ""))
    result = validate(_record(i) for i in items)
    result.confirmed_empty = not items and not any(totals)
    result.truncated = truncated
    return result
