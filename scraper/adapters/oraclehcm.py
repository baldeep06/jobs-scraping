from datetime import UTC, date, datetime
from typing import Any

from scraper.adapters.base import dedupe_by, fetch_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Oracle Recruiting Cloud career sites (Oracle, Dell, TI, ON, Vertiv, ...). The tenant host is in
# `workday_host` and the career-site number (CX, CX_1001, "careers", ...) in `workday_site`.
PAGE = 25
MAX_PAGES = 30
QUERIES = ("intern", "co-op")


def _finder(site: str, query: str, offset: int) -> str:
    return f"findReqs;siteNumber={site},limit={PAGE},keyword={query},offset={offset}"


async def _search(
    fetcher: Fetcher, host: str, site: str, query: str
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    total = 0
    for page_no in range(MAX_PAGES):
        url = (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder={_finder(site, query, page_no * PAGE)}"
        )
        data = await fetcher.json("GET", url)
        rows = data.get("items") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise FetchError("unexpected Oracle HCM payload")
        head = rows[0]
        if not isinstance(head.get("requisitionList"), list) or "TotalJobsCount" not in head:
            raise FetchError("unexpected Oracle HCM payload (no requisition list)")
        if page_no == 0:
            total = int(head["TotalJobsCount"] or 0)
        items.extend(head["requisitionList"])
        if not head["requisitionList"] or len(items) >= total:
            break
    return items, total


def _posted(value: Any) -> datetime | None:
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _key(host: str, item: dict[str, Any]) -> str:
    return f"{host}:{item.get('Id') or ''}"


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host, site = company.workday_host, company.workday_site
    if not host or not site:
        raise FetchError("oraclehcm company is missing its host/site number")
    found: list[dict[str, Any]] = []
    totals: list[int] = []
    truncated = False
    for query in QUERIES:
        items, total = await _search(fetcher, host, site, query)
        found.extend(items)
        totals.append(total)
        truncated = truncated or len(items) < total
    items = dedupe_by(found, lambda i: _key(host, i))

    base = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
    want = {
        _key(
            host, i
        ): f'{base}?expand=all&onlyData=true&finder=ById;Id="{i["Id"]}",siteNumber={site}'
        for i in items
        if i.get("Id") and wanted(i.get("Title") or "")
    }
    details, pending = await fetch_details(fetcher, company, {_key(host, i) for i in items}, want)
    records = []
    for i in items:
        key = _key(host, i)
        if key in pending:
            continue
        rows = (details.get(key) or {}).get("items")
        d = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        secondary = [
            s.get("Name") for s in i.get("secondaryLocations") or [] if isinstance(s, dict)
        ]
        locations = [i.get("PrimaryLocation") or d.get("PrimaryLocation") or ""]
        locations += [s for s in secondary if s]
        text = " ".join(
            html_to_text(d.get(f) or "")
            for f in ("ExternalDescriptionStr", "ExternalQualificationsStr")
        ).strip()
        records.append(
            {
                "source": "oraclehcm",
                "source_job_id": key,
                "title": i.get("Title") or "",
                "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{i['Id']}",
                "location_raw": " | ".join(x for x in locations if x),
                "country_hint": i.get("PrimaryLocationCountry") or None,
                "description_text": text,
                "source_posted_at": _posted(i.get("PostedDate")),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items and not any(totals)
    result.truncated = truncated
    return result
