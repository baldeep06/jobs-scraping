import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from scraper.adapters.base import read_pages, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Phenom career sites (BCG, Trane, MITRE, Battelle, Bell, ...). `workday_host` holds the site
# base: host plus locale path, e.g. "careers.bcg.com/global/en". The keyword search matches
# descriptions too ("intern" finds every MITRE posting), but every site publishes
# <base>/sitemap.xml (a urlset, or an index of urlsets) with one URL per open posting, the title
# spelled out: ".../job/R117698/TECH-Futures-Intern". So: the sitemap, then only the internship
# pages, each of which embeds its posting (description included) as `phApp.ddo = {...}`.
SOURCE = "phenom"
MAX_SITEMAPS = 20
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_JOB = re.compile(r"/job/([^/?#]+)/([^/?#]*)/?$")
_DDO = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.", re.S)
_HOME = {"united states", "united states of america", "usa", "us", "canada"}


def _base(company: Company) -> str:
    if not company.workday_host:
        raise FetchError("phenom company is missing its site base (host/locale)")
    return company.workday_host.strip("/")


def slug_title(slug: str) -> str:
    text = " ".join(unquote(slug).replace("-", " ").split())
    return re.sub(r"(?i)\b(co) (op)\b", r"\1-\2", text)  # the dash went with the others


def parse_sitemap(xml: str) -> tuple[list[dict[str, str]], list[str]]:
    """(postings, child sitemaps): a urlset lists postings, a sitemapindex lists urlsets."""
    if "<urlset" not in xml and "<sitemapindex" not in xml:
        raise FetchError("unexpected Phenom sitemap")
    locs = [u.replace("&amp;", "&") for u in _LOC.findall(xml)]
    if "<sitemapindex" in xml:
        return [], locs
    rows: dict[str, dict[str, str]] = {}
    for url in locs:
        m = _JOB.search(url)
        if m:
            rows.setdefault(m.group(1), {"id": m.group(1), "url": url, "slug": m.group(2)})
    return list(rows.values()), []


def parse_posting(html: str) -> dict[str, Any]:
    m = _DDO.search(html)
    try:
        data = json.loads(m.group(1)) if m else None
    except ValueError:
        data = None
    job = data.get("jobDetail", {}).get("data", {}).get("job") if isinstance(data, dict) else None
    return job if isinstance(job, dict) else {}


def _posted(value: Any) -> datetime | None:
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value or ""))
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _location(job: dict[str, Any]) -> str:
    places = [p for p in job.get("multi_location") or [] if isinstance(p, str) and p.strip()]
    return " | ".join(dict.fromkeys(places)) or str(job.get("location") or "")


def country_hint(job: dict[str, Any]) -> str | None:
    """Returns "OTHER" for a posting placed only outside CA/US: Phenom names the country, which the
    place names alone often don't ("Casablanca, Morocco")."""
    country = str(job.get("country") or "").strip().lower()
    if not country or country in _HOME:
        return None
    if any(home in _location(job).lower() for home in ("united states", "canada", "usa")):
        return None
    return "OTHER"


async def _postings(fetcher: Fetcher, base: str) -> list[dict[str, str]]:
    rows, children = parse_sitemap(await fetcher.text("GET", f"https://{base}/sitemap.xml"))
    for child in [c for c in children if c.startswith(f"https://{base}/")][:MAX_SITEMAPS]:
        rows.extend(parse_sitemap(await fetcher.text("GET", child))[0])
    return list({r["id"]: r for r in rows}.values())


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    base = _base(company)
    host = base.split("/")[0]

    def key(row: dict[str, str]) -> str:
        return f"{host}:{row['id']}"

    # Only internships are listed (as Jibe does): the ids handed to read_pages are exactly the
    # ids returned, so the unchanged-board check matches the pipeline's hash.
    rows = [r for r in await _postings(fetcher, base) if wanted(slug_title(r["slug"]))]
    want = {key(r): r["url"] for r in rows}
    pages, pending = await read_pages(fetcher, company, set(want), want)
    records = []
    for r in rows:
        if key(r) in pending:
            continue
        job = parse_posting(pages[key(r)]) if key(r) in pages else {}
        records.append(
            {
                "source": SOURCE,
                "source_job_id": key(r),
                "title": job.get("title") or slug_title(r["slug"]),
                "url": r["url"],
                "location_raw": _location(job),
                "country_hint": country_hint(job),
                "description_text": html_to_text(str(job.get("description") or "")),
                "source_posted_at": _posted(job.get("postedDate")),
                "employment_type_hint": job.get("type"),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    return result
