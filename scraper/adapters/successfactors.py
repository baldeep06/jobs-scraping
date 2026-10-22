import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from selectolax.lexbor import LexborHTMLParser

from scraper.adapters.base import read_pages, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# SAP SuccessFactors career sites ("RMK": careers.celestica.com, jobs.bombardier.com). The site
# host is kept in `workday_host`. The keyword search is full text and some sites render results
# with JavaScript, but every site publishes /sitemap.xml with one URL per open posting, and the
# URL spells out the title ("/job/Toronto-Student-Intern%2C-Test-Development-ON/1439151233/").
# So: one sitemap request, then only the internship pages are opened.
SOURCE = "successfactors"
_JOB = re.compile(r"<loc>\s*(https?://[^<\s]+/job/([^<\s/]+)/(\d+)/?)\s*</loc>")
# Some sites print the place as "Mississauga, ON, CAN, L5S 1W1" (or "Colon, QUE, MEX, 76270")
# instead of tagging it.
_PLACE = re.compile(r"^[A-Z][\w .'-]+, [A-Z]{2,3}, ([A-Z]{2,3})\b")
_ISO3 = {"CAN": "CA", "USA": "US"}


def _host(company: Company) -> str:
    if not company.workday_host:
        raise FetchError("successfactors company is missing its site host")
    return company.workday_host


def slug_title(slug: str) -> str:
    return " ".join(unquote(slug).replace("&amp;", "&").replace("-", " ").split())


def parse_sitemap(xml: str) -> list[dict[str, str]]:
    if "<urlset" not in xml:
        raise FetchError("unexpected SuccessFactors sitemap")
    rows = {}
    for url, slug, job_id in _JOB.findall(xml):
        rows.setdefault(job_id, {"id": job_id, "url": url.replace("&amp;", "&"), "slug": slug})
    return list(rows.values())


def _meta(tree: LexborHTMLParser, prop: str) -> str:
    node = tree.css_first(f'meta[itemprop="{prop}"]')
    return ((node.attributes.get("content") or "") if node is not None else "").strip()


def _posted(value: str) -> datetime | None:
    try:  # "Tue Sep 29 00:00:00 UTC 2026"
        return datetime.strptime(value.replace("UTC ", ""), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None


def slug_location(slug: str, title: str) -> str:
    """URLs are "<city>-<title>-<region>-<postcode>": what is left around the title."""
    text, words = slug_title(slug), re.sub(r"[^\w]+", " ", title).split()
    flat = re.sub(r"[^\w]+", " ", text)
    at = flat.find(" ".join(words)) if words else -1
    if at <= 0:
        return ""
    city, after = flat[:at].strip(), flat[at + len(" ".join(words)) :].split()
    return ", ".join(x for x in (city, after[0] if after else "") if x)


def parse_page(html: str, slug: str) -> dict[str, Any]:
    tree = LexborHTMLParser(html)
    node = tree.css_first('[itemprop="title"]')
    title = " ".join(node.text().split()) if node is not None else ""
    place = ", ".join(
        x
        for x in (_meta(tree, p) for p in ("addressLocality", "addressRegion", "addressCountry"))
        if x
    )
    country = _meta(tree, "addressCountry").upper()
    if not place:
        place = next(
            (t for n in tree.css("span") if _PLACE.match(t := " ".join(n.text().split()))), ""
        )
        if m := _PLACE.match(place):
            code = m.group(1)
            country = _ISO3.get(code, code if len(code) == 2 else "OTHER")
    body = tree.css_first('[itemprop="description"]')
    return {
        "title": title,
        "location": place or slug_location(slug, title),
        "country": country or None,
        "posted": _posted(_meta(tree, "datePosted")),
        "description": html_to_text(body.html or "") if body is not None else "",
    }


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host = _host(company)
    rows = parse_sitemap(await fetcher.text("GET", f"https://{host}/sitemap.xml"))

    def key(row: dict[str, str]) -> str:
        return f"{host}:{row['id']}"

    # Only internships are listed (as Jibe does): the ids handed to read_pages are exactly the
    # ids returned, so the unchanged-board check matches the pipeline's hash.
    rows = [r for r in rows if wanted(slug_title(r["slug"]))]
    want = {key(r): r["url"] for r in rows}
    pages, pending = await read_pages(fetcher, company, set(want), want)
    records = []
    for r in rows:
        if key(r) in pending:
            continue
        page = parse_page(pages[key(r)], r["slug"]) if key(r) in pages else {}
        records.append(
            {
                "source": SOURCE,
                "source_job_id": key(r),
                "title": page.get("title") or slug_title(r["slug"]),
                "url": r["url"],
                "location_raw": page.get("location") or "",
                "country_hint": page.get("country"),
                "description_text": page.get("description") or "",
                "source_posted_at": page.get("posted"),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    return result
