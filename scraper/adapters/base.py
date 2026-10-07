from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import ValidationError

from scraper.http import Fetcher
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
