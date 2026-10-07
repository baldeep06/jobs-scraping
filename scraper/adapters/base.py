import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import ValidationError

from scraper.enrich.category import categorize, is_intern_title
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult, RawJob

Adapter = Callable[[Fetcher, Company], Awaitable[FetchResult]]


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
