from typing import Any

from scraper.adapters.base import dedupe_by, fetch_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

SOURCE = "workable"
MAX_PAGES = 5
QUERIES = ("intern", "co-op")
_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on_site": "onsite"}


def list_url(slug: str) -> str:
    return f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"


def detail_url(slug: str, shortcode: str) -> str:
    return f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}"


def _location(item: dict[str, Any]) -> str:
    loc = item.get("location") or {}
    return ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)


def _description(detail: dict[str, Any]) -> str:
    parts = (html_to_text(detail.get(k) or "") for k in ("description", "requirements", "benefits"))
    return "\n".join(p for p in parts if p)


def _record(slug: str, item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    code = item.get("shortcode") or ""
    return {
        "source": SOURCE,
        "source_job_id": code,
        "title": item.get("title") or "",
        "url": f"https://apply.workable.com/{slug}/j/{code}/",
        "location_raw": _location(item),
        "description_text": _description(detail),
        "source_posted_at": item.get("published"),
        "work_mode_hint": _WORKPLACE.get(item.get("workplace") or ""),
        "country_hint": (item.get("location") or {}).get("countryCode"),
        "employment_type_hint": item.get("type"),
    }


async def _search(
    fetcher: Fetcher, slug: str, query: str
) -> tuple[list[dict[str, Any]], int | None]:
    items: list[dict[str, Any]] = []
    total: int | None = None
    token = None
    for page_no in range(MAX_PAGES):
        body: dict[str, Any] = {
            "query": query, "location": [], "department": [], "worktype": [], "remote": []
        }  # fmt: skip
        if token:
            body["token"] = token
        page = await fetcher.json("POST", list_url(slug), json=body)
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            raise FetchError("unexpected Workable payload")
        items.extend(page["results"])
        if page_no == 0:
            total = page.get("total")
        token = page.get("nextPage")
        if not token:
            break
    return items, total


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    found: list[dict[str, Any]] = []
    totals: list[int | None] = []
    for query in QUERIES:
        items, total = await _search(fetcher, company.slug, query)
        found.extend(items)
        totals.append(total)
    items = dedupe_by(found, lambda i: i.get("shortcode") or "")

    want = {
        i["shortcode"]: detail_url(company.slug, i["shortcode"])
        for i in items
        if i.get("shortcode") and wanted(i.get("title") or "", i.get("type"))
    }
    details, pending = await fetch_details(
        fetcher, company, {i["shortcode"] for i in items if i.get("shortcode")}, want
    )
    records = [
        _record(company.slug, i, details.get(i.get("shortcode") or "", {}))
        for i in items
        if i.get("shortcode") not in pending
    ]
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items and all(t == 0 for t in totals)
    return result
