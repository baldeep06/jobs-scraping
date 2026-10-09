from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Gem job boards (jobs.gem.com/<slug>); the public API mirrors Greenhouse's job-board API.
SOURCE = "gem"
_WORK_MODE = {"in_office": "onsite", "hybrid": "hybrid", "remote": "remote"}


def board_url(slug: str) -> str:
    return f"https://api.gem.com/job_board/v0/{slug}/job_posts/"


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, list):
        raise FetchError("unexpected Gem payload")
    return validate(
        {
            "source": SOURCE,
            "source_job_id": as_id(item.get("id")),
            "title": item.get("title") or "",
            "url": item.get("absolute_url") or "",
            "location_raw": (item.get("location") or {}).get("name") or "",
            "description_text": html_to_text(item.get("content") or ""),
            "source_posted_at": item.get("first_published_at") or item.get("updated_at"),
            "work_mode_hint": _WORK_MODE.get(item.get("location_type") or ""),
            "employment_type_hint": item.get("employment_type"),
        }
        for item in payload
        if isinstance(item, dict)
    )


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))
