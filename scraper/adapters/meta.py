import asyncio
import json
import re
from typing import Any

from scraper.adapters.base import validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult, RawJob
from scraper.text import html_to_text

SOURCE = "meta"
SITEMAP = "https://www.metacareers.com/jobs/sitemap.xml"
JOB_URL = "https://www.metacareers.com/profile/job_details/{}/"
# Meta's GraphQL needs rotating tokens, but it publishes a sitemap of every job and each job page
# carries schema.org JobPosting data. Pages are opened only once, and at most this many per poll
# (the first run backfills gradually). Meta's robots.txt discourages automated collection, so
# this stays small; remove the `meta` seed row to stop all requests.
MAX_NEW_PAGES = 120
BATCH = 10  # pages opened at once; a failing batch ends the poll
MIN_PAGES_FOR_CHECK = 5  # below this, a page without data is just one odd page
_JOB_ID = re.compile(r"<loc>\s*https://www\.metacareers\.com/profile/job_details/(\d+)/?\s*</loc>")
_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_WANTED_COUNTRIES = {"US", "CA"}


def parse_sitemap(xml: str) -> list[str]:
    ids = list(dict.fromkeys(_JOB_ID.findall(xml)))
    if not ids:
        raise FetchError("unexpected Meta sitemap (no job pages)")
    return ids


def parse_job_page(html: str) -> dict[str, Any] | None:
    """The page's schema.org JobPosting, or None if it is missing."""
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def _places(posting: dict[str, Any]) -> list[tuple[str, str]]:
    places = posting.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    out = []
    for place in places:
        if not isinstance(place, dict):
            continue
        country = ((place.get("address") or {}).get("addressCountry") or "").upper()
        out.append((place.get("name") or "", country))
    return out


def _record(job_id: str, posting: dict[str, Any], places: list[tuple[str, str]]) -> dict[str, Any]:
    parts = (
        html_to_text(str(posting.get(k) or ""))
        for k in ("description", "responsibilities", "qualifications")
    )
    return {
        "source": SOURCE,
        "source_job_id": job_id,
        "title": posting.get("title") or "",
        "url": JOB_URL.format(job_id),
        "location_raw": " | ".join(f"{name}, {country}".strip(", ") for name, country in places),
        "description_text": "\n".join(p for p in parts if p),
        "source_posted_at": posting.get("datePosted"),
        "employment_type_hint": posting.get("employmentType"),
    }


async def _read_pages(fetcher: Fetcher, ids: list[str]) -> tuple[dict[str, str], set[str]]:
    """Open pages in small batches. Returns (pages, ids that are gone: HTTP 404/410).

    A batch where half the requests fail for any other reason means Meta is blocking or rate
    limiting us: stop for this poll (keeping what was read) instead of hammering the site. If
    not a single page could be read, raise so the failure is visible.
    """

    async def one(job_id: str) -> tuple[str, str | None, int | None]:
        try:
            return job_id, await fetcher.text("GET", JOB_URL.format(job_id)), None
        except FetchError as e:
            return job_id, None, e.status

    pages: dict[str, str] = {}
    gone: set[str] = set()
    for start in range(0, len(ids), BATCH):
        batch = ids[start : start + BATCH]
        failures = 0
        for job_id, html, status in await asyncio.gather(*(one(i) for i in batch)):
            if html is not None:
                pages[job_id] = html
            elif status in (404, 410):
                gone.add(job_id)
            else:
                failures += 1
        if failures * 2 >= len(batch):
            if not pages and not gone:
                raise FetchError("Meta is not serving job pages (blocked or rate limited)")
            break
    return pages, gone


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    ids = parse_sitemap(await fetcher.text("GET", SITEMAP))
    listed = set(ids)
    known = company.known_ids | company.checked_ids
    new = [i for i in ids if i not in known][:MAX_NEW_PAGES]

    pages, gone = await _read_pages(fetcher, new)
    postings = {job_id: parse_job_page(html) for job_id, html in pages.items()}
    if len(pages) >= MIN_PAGES_FOR_CHECK:
        if sum(p is None for p in postings.values()) * 2 > len(pages):
            raise FetchError("unexpected Meta pages (no job data: blocked or changed)")
        readable = [p for p in postings.values() if p]
        if readable and not any(c in _WANTED_COUNTRIES for p in readable for _, c in _places(p)):
            # Every page has job data but none says US/CA: more likely a format change than reality.
            raise FetchError("unexpected Meta pages (no US/CA location found: format changed?)")

    jobs: list[RawJob] = []
    rejected: set[str] = set(gone)
    for job_id, posting in postings.items():
        places = _places(posting) if posting else []
        title = (posting or {}).get("title") or ""
        if (
            posting
            and wanted(title, posting.get("employmentType"))
            and any(country in _WANTED_COUNTRIES for _, country in places)
        ):
            checked = validate([_record(job_id, posting, places)])
            if checked.jobs:
                jobs.extend(checked.jobs)
                continue
        rejected.add(job_id)  # not an internship / not US-CA / unreadable: never open it again

    return FetchResult(
        jobs=jobs,
        # The sitemap parsed (an empty one raises), so "nothing new" is real and known interns
        # that left it may be closed.
        confirmed_empty=True,
        pending_ids=company.known_ids & listed,
        rejected_ids=rejected,
        forgotten_ids=company.checked_ids - listed,
    )
