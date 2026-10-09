from typing import Any

from scraper.adapters.base import fetch_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Rippling's applicant-tracking boards (ats.rippling.com/<slug>): the list has titles only, so
# internship-looking postings are opened one by one for their description and date.
API = "https://api.rippling.com/platform/api/ats/v1/board"


def _key(slug: str, item: dict[str, Any]) -> str:
    return f"{slug}:{item.get('uuid') or ''}"


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    slug = company.slug
    items = await fetcher.json("GET", f"{API}/{slug}/jobs")
    if not isinstance(items, list):
        raise FetchError("unexpected Rippling payload")
    items = [i for i in items if isinstance(i, dict) and i.get("uuid")]
    want = {
        _key(slug, i): f"{API}/{slug}/jobs/{i['uuid']}"
        for i in items
        if wanted((i.get("name") or "").strip())
    }
    details, pending = await fetch_details(fetcher, company, {_key(slug, i) for i in items}, want)
    records = []
    for i in items:
        key = _key(slug, i)
        if key in pending or key not in want:
            continue
        d = details.get(key) or {}
        description = d.get("description") or {}
        locations = d.get("workLocations") or [(i.get("workLocation") or {}).get("label") or ""]
        employment = d.get("employmentType") or {}
        records.append(
            {
                "source": "rippling",
                "source_job_id": key,
                "title": (i.get("name") or "").strip(),
                "url": i.get("url") or f"https://ats.rippling.com/{slug}/jobs/{i['uuid']}",
                "location_raw": " | ".join(x for x in locations if x),
                "description_text": "\n".join(
                    html_to_text(str(description.get(k) or "")) for k in ("role", "company")
                ).strip(),
                "source_posted_at": d.get("createdOn"),
                "employment_type_hint": employment.get("id") or employment.get("label"),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    return result
