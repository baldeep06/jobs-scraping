import json
import re
from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# D. E. Shaw's careers site (Next.js). The /careers page embeds every open posting, with its
# description, in __NEXT_DATA__ ("internships" and "regularJobs"), so one request per poll.
SOURCE = "deshaw"
URL = "https://www.deshaw.com/careers"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LISTS = ("internships", "regularJobs")


def _description(data: dict[str, Any]) -> str:
    d = data.get("jobDescription") or {}
    parts = [
        html_to_text(str(d.get("websiteDescription") or "")),
        html_to_text(str(d.get("responsibilitiesHtml") or d.get("responsibilities") or "")),
        html_to_text(str(d.get("peopleWeAreLookingForHtml") or ""))
        or "\n".join(str(x) for x in d.get("peopleWeAreLookingFor") or []),
    ]
    return "\n".join(p for p in parts if p)


def parse(html: str) -> FetchResult:
    m = _NEXT_DATA.search(html)
    try:
        props = json.loads(m.group(1))["props"]["pageProps"] if m else None
    except (ValueError, KeyError, TypeError):
        props = None
    if not isinstance(props, dict) or not all(isinstance(props.get(k), list) for k in _LISTS):
        raise FetchError("unexpected D. E. Shaw careers page (no job lists)")
    records = []
    for item in (i for k in _LISTS for i in props[k]):
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict) or data.get("activeOnJobsListing") is False:
            continue
        offices = item.get("office") or (data.get("jobMetadata") or {}).get("jobLocations") or []
        meta = data.get("jobMetadata") or {}
        records.append(
            {
                "source": SOURCE,
                "source_job_id": as_id(data.get("id") or item.get("id")),
                "title": data.get("displayName") or item.get("displayName") or "",
                "url": f"{URL}/{str(data.get('jobUrl') or '').lower()}",
                "location_raw": " | ".join(o.get("name") or "" for o in offices if o.get("name")),
                "description_text": _description(data),
                "employment_type_hint": meta.get("workStatus") or data.get("status"),
            }
        )
    return validate(records)


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.text("GET", URL))
