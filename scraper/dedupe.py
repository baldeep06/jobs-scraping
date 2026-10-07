import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from scraper.models import Location

REPOST_WINDOW = timedelta(days=120)
REFRESH_MIN_AGE = timedelta(days=7)
CLOSE_AFTER_MISSES = 2

Action = Literal["touch", "reopen", "refresh", "attach", "insert"]
Freshness = Literal["fresh", "repost", "reopened", "refreshed", "recurring"]


def fingerprint(company_id: int, normalized_title: str, locations: list[Location]) -> str:
    keys = ",".join(sorted({loc.key() for loc in locations}))
    return hashlib.sha1(f"{company_id}|{normalized_title}|{keys}".encode()).hexdigest()


def ids_hash(ids: Iterable[str]) -> str:
    return hashlib.sha1("\n".join(sorted(ids)).encode()).hexdigest()


@dataclass(frozen=True)
class ExistingSource:
    """A job_sources row already stored for the incoming (source, source_job_id)."""

    job_id: str
    job_status: str
    job_first_seen_at: datetime
    source_posted_at: datetime | None


@dataclass(frozen=True)
class FingerprintMatch:
    """Most recently seen job with the incoming job's fingerprint."""

    job_id: str
    status: str
    last_seen_at: datetime
    repost_count: int
    term: str | None = None


@dataclass(frozen=True)
class Decision:
    action: Action
    job_id: str | None = None
    freshness: Freshness | None = None
    repost_of: str | None = None
    repost_count: int = 0


def classify(
    existing: ExistingSource | None,
    incoming_posted_at: datetime | None,
    fp_match: FingerprintMatch | None,
    now: datetime,
    incoming_term: str | None = None,
) -> Decision:
    """Spec §4 freshness rules, evaluated in order.

    The fingerprint ignores term, so "Intern (Fall 2026)" and "Intern (Winter 2027)" match.
    An open match only absorbs the incoming posting when the terms agree (or one is
    unknown); two terms posted at the same time are separate opportunities.
    """
    if existing is not None:
        if existing.job_status == "closed":
            return Decision("reopen", job_id=existing.job_id, freshness="reopened")
        bumped = (
            incoming_posted_at is not None
            and existing.source_posted_at is not None
            and incoming_posted_at > existing.source_posted_at
        )
        if bumped and now - existing.job_first_seen_at > REFRESH_MIN_AGE:
            return Decision("refresh", job_id=existing.job_id, freshness="refreshed")
        return Decision("touch", job_id=existing.job_id)
    if fp_match is not None:
        if fp_match.status == "open":
            if fp_match.term and incoming_term and fp_match.term != incoming_term:
                return Decision("insert", freshness="fresh")
            return Decision("attach", job_id=fp_match.job_id)
        if now - fp_match.last_seen_at <= REPOST_WINDOW:
            return Decision(
                "insert",
                freshness="repost",
                repost_of=fp_match.job_id,
                repost_count=fp_match.repost_count + 1,
            )
        return Decision("insert", freshness="recurring")
    return Decision("insert", freshness="fresh")


@dataclass(frozen=True)
class OpenJob:
    job_id: str
    miss_count: int
    source_job_ids: frozenset[str]


@dataclass
class ClosurePlan:
    reset: list[str] = field(default_factory=list)
    increment: list[str] = field(default_factory=list)
    close: list[str] = field(default_factory=list)


def plan_closures(
    open_jobs: list[OpenJob], seen_ids: set[str], enriched_ids: set[str] | None = None
) -> ClosurePlan:
    """A job is missing only if none of its source IDs (for this company+source) were seen.

    With `enriched_ids` (a full re-enrichment happened), a job whose IDs are still listed but
    none passed the filter any more (retitled, moved abroad) is closed right away.
    """
    plan = ClosurePlan()
    for job in open_jobs:
        if enriched_ids is not None and job.source_job_ids & seen_ids:
            if not job.source_job_ids & enriched_ids:
                plan.close.append(job.job_id)
                continue
        if job.source_job_ids & seen_ids:
            if job.miss_count:
                plan.reset.append(job.job_id)
        elif job.miss_count + 1 >= CLOSE_AFTER_MISSES:
            plan.close.append(job.job_id)
        else:
            plan.increment.append(job.job_id)
    return plan
