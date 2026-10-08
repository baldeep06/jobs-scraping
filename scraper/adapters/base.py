import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import ValidationError

from scraper.enrich.category import categorize, is_intern_title
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult, RawJob

Adapter = Callable[[Fetcher, Company], Awaitable[FetchResult]]

# Sites that need one request per posting remember what they have already opened.
STATEFUL_ATS = {"meta"}


def as_id(value: Any) -> str:
    return "" if value is None else str(value)


def validate(records: Iterable[dict[str, Any]]) -> FetchResult:
    """Build RawJobs, dropping (and counting) records that fail validation."""
    jobs: list[RawJob] = []
    invalid = 0
    for record in records:
        try:
            jobs.append(RawJob.model_validate(record))
        except ValidationError:
            invalid += 1
    return FetchResult(jobs=jobs, invalid=invalid)


def wanted(title: str, employment_type: str | None = None) -> bool:
    """Cheap pre-check so search-based adapters only fetch details for plausible postings."""
    return is_intern_title(title, employment_type) and categorize(title) is not None


async def get_details(fetcher: Fetcher, urls: dict[str, str]) -> dict[str, dict[str, Any]]:
    """GET every url concurrently. A failed or non-object response just omits that key, so one
    removed posting can never fail (or 404-deactivate) the whole company."""

    async def one(key: str, url: str) -> tuple[str, Any]:
        try:
            return key, await fetcher.json("GET", url)
        except FetchError:
            return key, None

    pairs = await asyncio.gather(*(one(k, u) for k, u in urls.items()))
    return {k: v for k, v in pairs if isinstance(v, dict)}


def dedupe_by(
    items: Iterable[dict[str, Any]], key: Callable[[dict[str, Any]], str]
) -> list[dict[str, Any]]:
    """Merge the hits of several searches, keeping the first occurrence of each posting."""
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        merged.setdefault(key(item), item)
    return list(merged.values())


def unchanged_board(company: Company, ids: Iterable[str]) -> bool:
    """True if the listed ids are exactly what we stored last time (so nothing needs re-reading)."""
    from scraper.pipeline import board_hash  # local: pipeline imports the adapters

    return company.job_ids_hash is not None and company.job_ids_hash == board_hash(set(ids))


async def fetch_details(
    fetcher: Fetcher, company: Company, all_ids: set[str], want: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Details for the postings worth reading, plus the ids whose fetch failed.

    Skipped entirely when the id list is unchanged since the last successful poll: nothing
    would be re-enriched, so the requests would be wasted.
    """
    if not want or unchanged_board(company, all_ids):
        return {}, set()
    details = await get_details(fetcher, want)
    return details, set(want) - set(details)


_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def json_ld_posting(html: str) -> dict[str, Any]:
    """The schema.org JobPosting embedded in a posting page ({} if there is none)."""
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def posting_location(posting: dict[str, Any]) -> str:
    places = posting.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    out = []
    for place in places:
        a = (place.get("address") or {}) if isinstance(place, dict) else {}
        text = ", ".join(
            x
            for x in (a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry"))
            if x
        )
        if text:
            out.append(text)
    return " | ".join(out)


async def read_pages(
    fetcher: Fetcher, company: Company, all_ids: set[str], want: dict[str, str]
) -> tuple[dict[str, str], set[str]]:
    """fetch_details for HTML pages: (html by id, ids whose page failed to load)."""
    if not want or unchanged_board(company, all_ids):
        return {}, set()

    async def one(key: str, url: str) -> tuple[str, str | None]:
        try:
            return key, await fetcher.text("GET", url)
        except FetchError:
            return key, None

    pairs = await asyncio.gather(*(one(k, u) for k, u in want.items()))
    pages = {k: v for k, v in pairs if v}
    return pages, set(want) - set(pages)
