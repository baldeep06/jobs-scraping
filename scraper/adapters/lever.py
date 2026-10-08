from datetime import UTC, datetime
from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "lever"
_INTERVALS = {
    "per-hour-wage": "hour",
    "per-week-salary": "week",
    "per-month-salary": "month",
    "per-year-salary": "year",
}
_WORKPLACE = {"onsite": "onsite", "remote": "remote", "hybrid": "hybrid"}


def board_url(slug: str, api: str = "api.lever.co") -> str:
    return f"https://{api}/v0/postings/{slug}?mode=json"


def _description(item: dict[str, Any]) -> str:
    parts = [item.get("descriptionPlain") or ""]
    for section in item.get("lists") or []:
        parts.append(section.get("text") or "")
        parts.append(html_to_text(section.get("content") or ""))
    parts.append(item.get("additionalPlain") or "")
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _pay(item: dict[str, Any]) -> dict[str, Any] | None:
    salary = item.get("salaryRange") or {}
    period = _INTERVALS.get(salary.get("interval"))
    if not period:
        return None
    return {
        "min": salary.get("min"),
        "max": salary.get("max"),
        "currency": salary.get("currency"),
        "period": period,
    }


def _record(item: dict[str, Any]) -> dict[str, Any]:
    cats = item.get("categories") or {}
    all_locations = cats.get("allLocations") or []
    created = item.get("createdAt")
    return {
        "source": SOURCE,
        "source_job_id": as_id(item.get("id")),
        "title": item.get("text") or "",
        "url": item.get("hostedUrl") or "",
        "location_raw": " | ".join(all_locations)
        if all_locations
        else (cats.get("location") or ""),
        "description_text": _description(item),
        "source_posted_at": (
            datetime.fromtimestamp(created / 1000, UTC)
            if isinstance(created, int | float)
            else None
        ),
        "pay_structured": _pay(item),
        "work_mode_hint": _WORKPLACE.get(item.get("workplaceType") or ""),
        "country_hint": item.get("country"),
        "employment_type_hint": cats.get("commitment"),
    }


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, list):
        raise FetchError("unexpected Lever payload")
    return validate(_record(item) for item in payload)


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))


async def fetch_eu(fetcher: Fetcher, company: Company) -> FetchResult:
    """Boards on Lever's EU instance (jobs.eu.lever.co) live behind a different API host."""
    return parse(await fetcher.json("GET", board_url(company.slug, "api.eu.lever.co")))
