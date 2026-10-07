from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult

SOURCE = "ashby"
_INTERVALS = {"1 HOUR": "hour", "1 WEEK": "week", "1 MONTH": "month", "1 YEAR": "year"}
_WORKPLACE = {"OnSite": "onsite", "Remote": "remote", "Hybrid": "hybrid"}
_COUNTRIES = {"canada": "CA", "united states": "US", "united states of america": "US", "usa": "US"}


def board_url(slug: str) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def _country(item: dict[str, Any]) -> str | None:
    address = ((item.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
    country = (address or "").strip()
    if not country:
        return None
    if len(country) == 2 and country.isalpha():
        return country.upper()
    return _COUNTRIES.get(country.lower(), "OTHER")


def _pay(item: dict[str, Any]) -> dict[str, Any] | None:
    for comp in (item.get("compensation") or {}).get("summaryComponents") or []:
        period = _INTERVALS.get(comp.get("interval"))
        if comp.get("compensationType") == "Salary" and period:
            return {
                "min": comp.get("minValue"),
                "max": comp.get("maxValue"),
                "currency": comp.get("currencyCode"),
                "period": period,
            }
    return None


def _work_mode(item: dict[str, Any]) -> str | None:
    mode = _WORKPLACE.get(item.get("workplaceType") or "")
    return mode or ("remote" if item.get("isRemote") else None)


def _record(item: dict[str, Any]) -> dict[str, Any]:
    locations = [item.get("location") or ""] + [
        (s or {}).get("location") or "" for s in item.get("secondaryLocations") or []
    ]
    summary = (item.get("compensation") or {}).get("compensationTierSummary") or ""
    description = "\n".join(p for p in (item.get("descriptionPlain") or "", summary) if p)
    return {
        "source": SOURCE,
        "source_job_id": as_id(item.get("id")),
        "title": item.get("title") or "",
        "url": item.get("jobUrl") or "",
        "location_raw": " | ".join(loc for loc in locations if loc),
        "description_text": description,
        "source_posted_at": item.get("publishedAt"),
        "pay_structured": _pay(item),
        "work_mode_hint": _work_mode(item),
        "country_hint": _country(item),
        "employment_type_hint": item.get("employmentType"),
    }


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FetchError("unexpected Ashby payload")
    return validate(_record(item) for item in payload["jobs"] if item.get("isListed", True))


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))
