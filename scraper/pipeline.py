from collections import Counter

from scraper.adapters import ADAPTERS
from scraper.adapters.base import STATEFUL_ATS, Adapter
from scraper.dedupe import ids_hash
from scraper.enrich import enrich
from scraper.http import Fetcher, FetchError
from scraper.models import Company, CompanyOutcome, FetchResult, RawJob
from scraper.normalize.location import parse_location

# Bump when enrichment rules change so existing rows get re-enriched on the next poll.
ENRICH_VERSION = 3
# More invalid records than this share means the ATS changed its format: don't trust the poll.
MAX_INVALID_SHARE = 0.2


def dominant_country(raws: list[RawJob]) -> str | None:
    """Most common of CA/US across a company's whole board (used for bare "Remote" roles)."""
    counts: Counter[str] = Counter()
    for r in raws:
        country = parse_location(r.location_raw, r.country_hint, r.work_mode_hint).country
        if country in ("CA", "US"):
            counts[country] += 1
    return counts.most_common(1)[0][0] if counts else None


def board_hash(seen: set[str]) -> str:
    """Change-detection hash. Includes ENRICH_VERSION so a rules change reprocesses every board."""
    return ids_hash([f"__enrich_v{ENRICH_VERSION}", *seen])


def process(company: Company, result: FetchResult) -> CompanyOutcome:
    total = len(result.jobs) + result.invalid
    if result.invalid and (not result.jobs or result.invalid / total > MAX_INVALID_SHARE):
        return CompanyOutcome(
            company=company,
            ok=False,
            invalid=result.invalid,
            error=f"{result.invalid} of {total} records failed validation (API change?)",
        )
    seen = {r.source_job_id for r in result.jobs} | result.pending_ids
    outcome = CompanyOutcome(
        company=company,
        ok=True,
        seen_ids=seen,
        # A half-fetched board must be re-read next time, never judged "unchanged".
        ids_hash=None if result.pending_ids else board_hash(seen),
        invalid=result.invalid,
        confirmed_empty=result.confirmed_empty,
        pending_ids=set(result.pending_ids),
        rejected_ids=set(result.rejected_ids),
        forgotten_ids=set(result.forgotten_ids),
        truncated=result.truncated,
    )
    if outcome.ids_hash == company.job_ids_hash:
        outcome.unchanged = True
        return outcome
    default = dominant_country(result.jobs)
    outcome.jobs = [e for r in result.jobs if (e := enrich(r, company.id, default)) is not None]
    if company.ats in STATEFUL_ATS:
        # Read but dropped by enrichment: remember it so the page is not opened again.
        kept = {j.raw.source_job_id for j in outcome.jobs}
        outcome.rejected_ids |= {r.source_job_id for r in result.jobs} - kept
    return outcome


async def poll(
    fetcher: Fetcher, company: Company, adapters: dict[str, Adapter] = ADAPTERS
) -> CompanyOutcome:
    """Fetch + process one company. Never raises: failures become ok=False outcomes."""
    try:
        return process(company, await adapters[company.ats](fetcher, company))
    except FetchError as e:
        return CompanyOutcome(company=company, ok=False, error=str(e), status=e.status)
    except Exception as e:  # adapter bug or surprise payload shape — isolate to this company
        return CompanyOutcome(company=company, ok=False, error=f"{type(e).__name__}: {e}")
