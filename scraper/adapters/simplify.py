import asyncio
import weakref
from datetime import UTC, datetime
from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult

# Postings from SimplifyJobs' public internship list on GitHub, for companies whose own career
# sites block automated requests (Tesla, Citadel, ...). No request reaches the company: the
# slug is the company name exactly as Simplify writes it, and each posting links to the
# company's own page. The list is ~13 MB, so it is downloaded once per run (per Fetcher).
SOURCE = "simplify"
LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/"
    ".github/scripts/listings.json"
)
# Simplify's sponsorship field, phrased so the usual visa rules read it.
_SPONSORSHIP = {
    "Does Not Offer Sponsorship": "Simplify: this role does not offer visa sponsorship.",
    "U.S. Citizenship is Required": "Simplify: U.S. citizenship is required.",
    "Offers Sponsorship": "Simplify: visa sponsorship is offered.",
}

_lists: "weakref.WeakKeyDictionary[Fetcher, asyncio.Task[Any]]" = weakref.WeakKeyDictionary()


async def _listings(fetcher: Fetcher) -> list[dict[str, Any]]:
    task = _lists.get(fetcher)
    if task is None:
        task = _lists[fetcher] = asyncio.ensure_future(fetcher.json("GET", LISTINGS_URL))
    try:
        payload = await asyncio.shield(task)
    except FetchError as e:
        _lists.pop(fetcher, None)  # let the next company retry
        # Drop the status: a moved list is not these companies' boards 404ing.
        raise FetchError(f"Simplify listings unavailable: {e}") from e
    if not isinstance(payload, list):
        raise FetchError("unexpected Simplify listings payload")
    return payload


def _posted(epoch: Any) -> datetime | None:
    return datetime.fromtimestamp(epoch, UTC) if isinstance(epoch, int | float) else None


def parse(listings: list[dict[str, Any]], company_name: str) -> FetchResult:
    name = company_name.lower()
    return validate(
        {
            "source": SOURCE,
            "source_job_id": as_id(item.get("id")),
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "location_raw": " | ".join(x for x in item.get("locations") or [] if x),
            "description_text": " ".join(
                filter(
                    None,
                    [
                        f"Terms: {', '.join(item.get('terms') or [])}."
                        if item.get("terms")
                        else "",
                        _SPONSORSHIP.get(item.get("sponsorship") or "", ""),
                    ],
                )
            ),
            "source_posted_at": _posted(item.get("date_posted")),
        }
        for item in listings
        if isinstance(item, dict)
        and str(item.get("company_name") or "").lower() == name
        and item.get("active")
        and item.get("is_visible", True)
    )


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    return parse(await _listings(fetcher), company.slug)
