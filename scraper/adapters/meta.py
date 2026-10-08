import asyncio
import json
import re
from typing import Any

from scraper.adapters.base import validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "meta"
SITEMAP = "https://www.metacareers.com/jobs/sitemap.xml"
JOB_URL = "https://www.metacareers.com/profile/job_details/{}/"
# Meta's GraphQL needs rotating tokens, but it publishes a sitemap of every job and each job page
# carries schema.org JobPosting data. Pages are opened only once, and at most this many per poll
# (the first run backfills gradually). Meta's robots.txt discourages automated collection, so
# this stays small; remove the `meta` seed row to stop all requests.
MAX_NEW_PAGES = 120
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


async def _load_pages(fetcher: Fetcher, ids: list[str]) -> dict[str, str]:
    async def one(job_id: str) -> tuple[str, str | None]:
        try:
            return job_id, await fetcher.text("GET", JOB_URL.format(job_id))
        except FetchError:
            return job_id, None  # retried on the next poll (not remembered)

    pages = await asyncio.gather(*(one(i) for i in ids))
    return {i: html for i, html in pages if html is not None}


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    ids = parse_sitemap(await fetcher.text("GET", SITEMAP))
    listed = set(ids)
    known = company.known_ids | company.checked_ids
    new = [i for i in ids if i not in known][:MAX_NEW_PAGES]

    records: list[dict[str, Any]] = []
    rejected: set[str] = set()
    for job_id, html in (await _load_pages(fetcher, new)).items():
        posting = parse_job_page(html)
        places = _places(posting) if posting else []
        title = (posting or {}).get("title") or ""
        if (
            posting
            and wanted(title, posting.get("employmentType"))
            and any(country in _WANTED_COUNTRIES for _, country in places)
        ):
            records.append(_record(job_id, posting, places))
        elif posting:
            rejected.add(job_id)

    result = validate(records)
    result.pending_ids = company.known_ids & listed
    result.rejected_ids = rejected
    result.forgotten_ids = company.checked_ids - listed
    return result
