from typing import Any

from scraper.adapters.base import get_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "smartrecruiters"
PAGE = 100
MAX_PAGES = 5
_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def list_url(slug: str, offset: int) -> str:
    return (
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        f"?q=intern&limit={PAGE}&offset={offset}"
    )


def detail_url(slug: str, posting_id: str) -> str:
    return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"


def _description(detail: dict[str, Any]) -> str:
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    parts = (html_to_text((sections.get(k) or {}).get("text") or "") for k in _SECTIONS)
    return "\n".join(p for p in parts if p)


def _work_mode(loc: dict[str, Any]) -> str | None:
    if loc.get("remote"):
        return "remote"
    return "hybrid" if loc.get("hybrid") else None


def _hint(item: dict[str, Any]) -> str | None:
    return (item.get("typeOfEmployment") or {}).get("label")


def _record(slug: str, item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    loc = item.get("location") or {}
    country = (loc.get("country") or "").upper() or None
    raw_loc = loc.get("fullLocation") or ", ".join(
        p for p in (loc.get("city"), loc.get("region"), country) if p
    )
    pid = str(item.get("id") or "")
    return {
        "source": SOURCE,
        "source_job_id": pid,
        "title": item.get("name") or "",
        "url": detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{slug}/{pid}",
        "location_raw": raw_loc,
        "description_text": _description(detail),
        "source_posted_at": item.get("releasedDate"),
        "work_mode_hint": _work_mode(loc),
        "country_hint": country,
        "employment_type_hint": _hint(item),
    }


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    items: list[dict[str, Any]] = []
    total = 0
    for page_no in range(MAX_PAGES):
        page = await fetcher.json("GET", list_url(company.slug, page_no * PAGE))
        if not isinstance(page, dict) or not isinstance(page.get("content"), list):
            raise FetchError("unexpected SmartRecruiters payload")
        if page_no == 0:
            total = int(page.get("totalFound") or 0)
        items.extend(page["content"])
        if not page["content"] or len(items) >= total:
            break

    want = {
        str(i["id"]): detail_url(company.slug, str(i["id"]))
        for i in items
        if i.get("id") and wanted(i.get("name") or "", _hint(i))
    }
    details = await get_details(fetcher, want)
    records = [
        _record(company.slug, i, details.get(str(i.get("id")), {}))
        for i in items
        if str(i.get("id")) not in want or str(i["id"]) in details
    ]
    result = validate(records)
    result.confirmed_empty = not items and total == 0
    return result
