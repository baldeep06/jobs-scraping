from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Pinpoint boards (<slug>.pinpointhq.com). postings.json lists every open posting with its
# full description, so one request per company.
SOURCE = "pinpoint"
_WORK_MODE = {"onsite": "onsite", "hybrid": "hybrid", "remote": "remote"}
_PERIOD = {"hour": "hour", "year": "year", "month": "month", "week": "week"}
_SECTIONS = ("description", "key_responsibilities", "skills_knowledge_expertise")


def board_url(slug: str) -> str:
    return f"https://{slug}.pinpointhq.com/postings.json"


def _location(place: dict[str, Any]) -> str:
    name = (place.get("name") or "").strip()
    region = (place.get("province") or "").strip()
    # "Redondo Beach " alone loses the state; add it when the name does not already carry one.
    if region and "," not in name:
        return ", ".join(x for x in (name or place.get("city"), region) if x)
    return name or (place.get("city") or "")


def _pay(item: dict[str, Any]) -> dict[str, Any] | None:
    period = _PERIOD.get(str(item.get("compensation_frequency") or "").lower())
    low, high = item.get("compensation_minimum"), item.get("compensation_maximum")
    if not item.get("compensation_visible") or not period or (low is None and high is None):
        return None
    return {
        "min": low,
        "max": high,
        "currency": item.get("compensation_currency"),
        "period": period,
    }


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise FetchError("unexpected Pinpoint payload")
    records = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        text = "\n".join(html_to_text(str(item.get(s) or "")) for s in _SECTIONS)
        records.append(
            {
                "source": SOURCE,
                "source_job_id": as_id(item.get("id")),
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "location_raw": _location(item.get("location") or {}),
                "description_text": text.strip(),
                "pay_structured": _pay(item),
                "work_mode_hint": _WORK_MODE.get(item.get("workplace_type") or ""),
                "employment_type_hint": item.get("employment_type_text")
                or item.get("employment_type"),
            }
        )
    return validate(records)


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))
