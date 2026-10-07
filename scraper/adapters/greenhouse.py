from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "greenhouse"


def board_url(slug: str) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def parse(payload: Any) -> FetchResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FetchError("unexpected Greenhouse payload")
    return validate(
        {
            "source": SOURCE,
            "source_job_id": as_id(item.get("id")),
            "title": item.get("title") or "",
            "url": item.get("absolute_url") or "",
            "location_raw": (item.get("location") or {}).get("name") or "",
            "description_text": html_to_text(item.get("content") or ""),
            "source_posted_at": item.get("first_published") or item.get("updated_at"),
        }
        for item in payload["jobs"]
    )


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await fetcher.json("GET", board_url(company.slug)))
