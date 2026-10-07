import re
from typing import Any

from scraper.adapters.base import dedupe_by, fetch_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "workday"
PAGE = 20  # Workday rejects a larger limit with HTTP 400
MAX_PAGES = 15
QUERIES = ("intern", "co-op")  # a title search for "intern" never returns Canadian co-ops

# Workday writes "US, CA, Santa Clara" = country, region, city (CA is California here).
_COUNTRY_REGION_CITY = re.compile(r"^([A-Z]{2}), ([A-Z]{2,3}), (.+)$")


def clean_location(text: str) -> str:
    text = text.strip()
    m = _COUNTRY_REGION_CITY.match(text)
    if not m:
        return text
    country, region, city = m.groups()
    return f"{city}, {region}, {country}"


def _key(item: dict[str, Any], scope: str) -> str:
    """Requisition ids repeat across tenants (and sites), so scope them."""
    bullets = item.get("bulletFields") or []
    return f"{scope}:{bullets[0] if bullets else item.get('externalPath') or ''}"


def _record(host: str, scope: str, item: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    path = item.get("externalPath") or ""
    locations = [info.get("location") or item.get("locationsText") or ""]
    locations += info.get("additionalLocations") or []
    return {
        "source": SOURCE,
        "source_job_id": _key(item, scope),
        "title": item.get("title") or "",
        "url": info.get("externalUrl") or f"https://{host}{path}",
        "location_raw": " | ".join(clean_location(x) for x in locations if x),
        "description_text": html_to_text(info.get("jobDescription") or ""),
        # Workday only says "Posted 21 Days Ago"; a date derived from now would drift daily.
        "source_posted_at": None,
    }


async def _search(fetcher: Fetcher, api: str, query: str) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    total = 0
    for page_no in range(MAX_PAGES):
        body = {"appliedFacets": {}, "limit": PAGE, "offset": page_no * PAGE, "searchText": query}
        data = await fetcher.json("POST", f"{api}/jobs", json=body)
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            raise FetchError("unexpected Workday payload")
        if page_no == 0:
            total = int(data.get("total") or 0)  # later pages report 0
        items.extend(data["jobPostings"])
        if not data["jobPostings"] or len(items) >= total:
            break
    return items, total


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host, site = company.workday_host, company.workday_site
    if not host or not site:
        raise FetchError("workday company is missing workday_host/workday_site")
    tenant = host.split(".")[0]
    api, scope = f"https://{host}/wday/cxs/{tenant}/{site}", f"{tenant}/{site}"
    found: list[dict[str, Any]] = []
    totals: list[int] = []
    for query in QUERIES:
        items, total = await _search(fetcher, api, query)
        found.extend(items)
        totals.append(total)
    items = dedupe_by(found, lambda i: _key(i, scope))

    want = {
        _key(i, scope): f"{api}{i['externalPath']}"
        for i in items
        if i.get("externalPath") and wanted(i.get("title") or "")
    }
    details, pending = await fetch_details(fetcher, company, {_key(i, scope) for i in items}, want)
    records = [
        _record(host, scope, i, (details.get(_key(i, scope)) or {}).get("jobPostingInfo") or {})
        for i in items
        if _key(i, scope) not in pending
    ]
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items and not any(totals)
    return result
