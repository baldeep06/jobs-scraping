import re
from typing import Any

from scraper.adapters.base import get_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "workday"
PAGE = 20  # Workday rejects a larger limit with HTTP 400
MAX_PAGES = 15

# Workday writes "US, CA, Santa Clara" = country, region, city (CA is California here).
_COUNTRY_REGION_CITY = re.compile(r"^([A-Z]{2}), ([A-Z]{2,3}), (.+)$")


def clean_location(text: str) -> str:
    text = text.strip()
    m = _COUNTRY_REGION_CITY.match(text)
    if not m:
        return text
    country, region, city = m.groups()
    return f"{city}, {region}, {country}"


def _key(item: dict[str, Any]) -> str:
    bullets = item.get("bulletFields") or []
    return str(bullets[0]) if bullets else (item.get("externalPath") or "")


def _record(host: str, item: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    path = item.get("externalPath") or ""
    locations = [info.get("location") or item.get("locationsText") or ""]
    locations += info.get("additionalLocations") or []
    return {
        "source": SOURCE,
        "source_job_id": _key(item),
        "title": item.get("title") or "",
        "url": info.get("externalUrl") or f"https://{host}{path}",
        "location_raw": " | ".join(clean_location(x) for x in locations if x),
        "description_text": html_to_text(info.get("jobDescription") or ""),
        # Workday only says "Posted 21 Days Ago"; a date derived from now would drift daily.
        "source_posted_at": None,
    }


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host, site = company.workday_host, company.workday_site
    if not host or not site:
        raise FetchError("workday company is missing workday_host/workday_site")
    api = f"https://{host}/wday/cxs/{host.split('.')[0]}/{site}"
    items: list[dict[str, Any]] = []
    total = 0
    for page_no in range(MAX_PAGES):
        body = {
            "appliedFacets": {},
            "limit": PAGE,
            "offset": page_no * PAGE,
            "searchText": "intern",
        }
        data = await fetcher.json("POST", f"{api}/jobs", json=body)
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            raise FetchError("unexpected Workday payload")
        if page_no == 0:
            total = int(data.get("total") or 0)  # later pages report 0
        items.extend(data["jobPostings"])
        if not data["jobPostings"] or len(items) >= total:
            break

    want = {
        _key(i): f"{api}{i['externalPath']}"
        for i in items
        if i.get("externalPath") and wanted(i.get("title") or "")
    }
    details = await get_details(fetcher, want)
    records = [
        _record(host, i, (details.get(_key(i)) or {}).get("jobPostingInfo") or {})
        for i in items
        if _key(i) not in want or _key(i) in details
    ]
    result = validate(records)
    result.confirmed_empty = not items and total == 0
    return result
