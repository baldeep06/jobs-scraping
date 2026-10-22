import re
from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from scraper.adapters.base import dedupe_by, read_pages, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Avature career portals (Bloomberg, Epic, National Bank of Canada). `workday_host` holds the
# portal base: host plus portal path, e.g. "bloomberg.avature.net/careers"; `workday_site` names
# the search page where a portal renames it (Two Sigma's "OpenRoles"; "-" = SearchJobs). There
# is no API: the search page is HTML (12-20 rows a page, paged by jobOffset or folderOffset) and
# the RSS feed only ever shows the 20 newest postings. The search is full text, so "intern" also
# matches "internal"; titles are filtered before any posting page is opened.
SOURCE = "avature"
QUERIES = ("intern", "co-op")
MAX_PAGES = 25
_DETAIL = re.compile(r"/(?:JobDetail|FolderDetail)/(?:[^/?#]*/)?(\d+)/?(?:[?#].*)?$")
_OFFSET = re.compile(r"\b((?:job|folder)Offset)=(\d+)")
_EMPTY = re.compile(r"(?i)no (?:results|jobs) found|0 matching positions")
_GENERIC = {"learn more", "apply", "apply now", "view job", "more info", "read more"}
_LOCATION_LABELS = {"location", "location(s)", "locations", "job location", "city"}
_DATE_LABELS = {"posting date", "date posted", "posted"}


def _base(company: Company) -> str:
    if not company.workday_host:
        raise FetchError("avature company is missing its portal base (host/path)")
    return company.workday_host.strip("/")


def _row_location(link: LexborNode) -> str:
    """The location printed next to a result (Bloomberg's span, a table's first cell)."""
    row = link.parent
    while row is not None and row.tag not in ("article", "li", "tr"):
        row = row.parent
    if row is None:
        return ""
    for sel in (".list-item-location", "td"):
        cell = row.css_first(sel)
        if cell is not None and cell.text(strip=True):
            return " ".join(cell.text().split())
    return ""


def parse_list(html: str, offset: int) -> tuple[list[dict[str, str]], tuple[str, int] | None]:
    """Rows (id, url, title, location) on one search page, and the next page as (parameter,
    offset): portals page by jobOffset or folderOffset (Epic), as their own links show."""
    tree = LexborHTMLParser(html)
    rows: dict[str, dict[str, str]] = {}
    for link in tree.css("a[href]"):
        href = link.attributes.get("href") or ""
        m = _DETAIL.search(urlsplit(href).path)
        if not m:
            continue
        title = " ".join(link.text().split()) or (link.attributes.get("title") or "").strip()
        row = rows.setdefault(m.group(1), {"id": m.group(1), "url": href, "title": ""})
        if not row["title"] and title.lower() not in _GENERIC:
            row["title"], row["location"] = title, _row_location(link)
    found = [r for r in rows.values() if r["title"]]
    if not found and not _EMPTY.search(tree.body.text() if tree.body else ""):
        raise FetchError("unexpected Avature page (no results and no empty-result message)")
    later = sorted((int(n), p) for p, n in _OFFSET.findall(html) if int(n) > offset)
    return found, ((later[0][1], later[0][0]) if later else None)


def _fields(tree: LexborHTMLParser) -> dict[str, str]:
    out = {}
    for field in tree.css(".article__content__view__field"):
        label = field.css_first(".article__content__view__field__label")
        value = field.css_first(".article__content__view__field__value")
        if label is not None and value is not None:
            out[label.text(strip=True).rstrip(":").lower()] = " ".join(value.text().split())
    return out


def _posted(value: str) -> datetime | None:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_detail(html: str) -> dict[str, Any]:
    tree = LexborHTMLParser(html)
    fields = _fields(tree)
    body = next((n for s in ("main", ".jobDetail", "article") if (n := tree.css_first(s))), None)
    return {
        "location": next((fields[k] for k in _LOCATION_LABELS if fields.get(k)), ""),
        "posted": next((_posted(fields[k]) for k in _DATE_LABELS if fields.get(k)), None),
        "description": html_to_text(body.html or "") if body is not None else "",
    }


def slug_location(url: str, title: str) -> str:
    """Epic's posting URLs lead with the place ("Verona-Wisconsin-United-States-<title>")."""
    parts = unquote(urlsplit(url).path).rstrip("/").split("/")
    slug = parts[-2] if len(parts) >= 2 else ""
    words = re.sub(r"[^A-Za-z0-9]+", " ", title).split()
    tail = "-".join(words)
    if words and slug.lower().endswith(tail.lower()):
        return slug[: -len(tail)].strip("-").replace("-", " ")
    return ""


def _search_page(company: Company) -> str:
    site = (company.workday_site or "").strip("/ ")
    return site if site and site != "-" else "SearchJobs"


async def _search(
    fetcher: Fetcher, base: str, page: str, query: str
) -> tuple[list[dict[str, str]], bool]:
    rows: list[dict[str, str]] = []
    param, offset = "jobOffset", 0
    for _ in range(MAX_PAGES):
        url = f"https://{base}/{page}/?search={quote(query)}&{param}={offset}"
        found, following = parse_list(await fetcher.text("GET", url), offset)
        rows.extend(found)
        if not found or following is None:
            return rows, False
        param, offset = following
    return rows, True


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    base = _base(company)
    host = base.split("/")[0]
    found: list[dict[str, str]] = []
    truncated = False
    for query in QUERIES:
        rows, capped = await _search(fetcher, base, _search_page(company), query)
        found.extend(rows)
        truncated = truncated or capped
    items = dedupe_by(found, lambda r: r["id"])

    def key(row: dict[str, str]) -> str:
        return f"{host}:{row['id']}"

    want = {key(r): r["url"] for r in items if wanted(r["title"])}
    pages, pending = await read_pages(fetcher, company, {key(r) for r in items}, want)
    records = []
    for r in items:
        if key(r) in pending:
            continue
        detail = parse_detail(pages[key(r)]) if key(r) in pages else {}
        records.append(
            {
                "source": SOURCE,
                "source_job_id": key(r),
                "title": r["title"],
                "url": r["url"],
                "location_raw": r.get("location")
                or detail.get("location")
                or slug_location(r["url"], r["title"]),
                "description_text": detail.get("description") or "",
                "source_posted_at": detail.get("posted"),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items
    result.truncated = truncated
    return result
