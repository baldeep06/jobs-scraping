from datetime import UTC, datetime
from typing import Any

from scraper.adapters.base import dedupe_by, fetch_details, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult
from scraper.text import html_to_text

# Eightfold career sites. The host lives in `workday_host` and the site's domain in
# `workday_site` (those two columns are simply "tenant host" and "tenant name" for every
# multi-tenant ATS). Two API flavours exist: "pcsx" (Microsoft, PayPal, Qualcomm, Lam) and
# the older "v2" (Netflix, NetApp); which one a site speaks is part of its seed entry.
PAGE = 10
MAX_PAGES = 20
QUERIES = ("intern", "co-op")
LOCATIONS = ("United States", "Canada")
_WORK_MODE = {"onsite": "onsite", "hybrid": "hybrid", "remote": "remote"}


def _tenant(company: Company, ats: str) -> tuple[str, str]:
    if not company.workday_host or not company.workday_site:
        raise FetchError(f"{ats} company is missing its host/domain")
    return company.workday_host, company.workday_site


def _when(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int | float) else None


# --- pcsx -----------------------------------------------------------------------------------


def _pcsx_key(host: str, item: dict[str, Any]) -> str:
    return f"{host}:{item.get('displayJobId') or item.get('id') or ''}"


async def _pcsx_search(
    fetcher: Fetcher, host: str, domain: str, query: str, location: str
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    count = 0
    for page_no in range(MAX_PAGES):
        url = (
            f"https://{host}/api/pcsx/search?domain={domain}&query={query}"
            f"&location={location.replace(' ', '%20')}&start={page_no * PAGE}&sort_by=timestamp"
        )
        data = await fetcher.json("GET", url)
        body = data.get("data") if isinstance(data, dict) else None
        if not isinstance(body, dict) or not isinstance(body.get("positions"), list):
            raise FetchError("unexpected Eightfold payload")
        if page_no == 0:
            if "count" not in body:
                raise FetchError("unexpected Eightfold payload (no result count)")
            count = int(body["count"] or 0)
        items.extend(body["positions"])
        if not body["positions"] or len(items) >= count:
            break
    return items, count


def _pcsx_record(
    host: str, item: dict[str, Any], detail: dict[str, Any], source: str
) -> dict[str, Any]:
    types = detail.get("efcustomTextEmploymentType") or []
    locations = item.get("standardizedLocations") or item.get("locations") or []
    return {
        "source": source,
        "source_job_id": _pcsx_key(host, item),
        "title": item.get("name") or "",
        "url": detail.get("publicUrl") or f"https://{host}{item.get('positionUrl') or ''}",
        "location_raw": " | ".join(locations),
        "description_text": html_to_text(detail.get("jobDescription") or ""),
        "source_posted_at": _when(item.get("postedTs")),
        "work_mode_hint": _WORK_MODE.get(item.get("workLocationOption") or ""),
        "employment_type_hint": types[0] if types else None,
    }


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    host, domain = _tenant(company, "eightfold")
    found: list[dict[str, Any]] = []
    counts: list[int] = []
    truncated = False
    for query in QUERIES:
        for location in LOCATIONS:
            items, count = await _pcsx_search(fetcher, host, domain, query, location)
            found.extend(items)
            counts.append(count)
            truncated = truncated or len(items) < count
    items = dedupe_by(found, lambda i: _pcsx_key(host, i))

    want = {
        _pcsx_key(host, i): (
            f"https://{host}/api/pcsx/position_details?position_id={i['id']}&domain={domain}&hl=en"
        )
        for i in items
        if i.get("id") and wanted(i.get("name") or "")
    }
    details, pending = await fetch_details(
        fetcher, company, {_pcsx_key(host, i) for i in items}, want
    )
    records = [
        _pcsx_record(
            host, i, (details.get(_pcsx_key(host, i)) or {}).get("data") or {}, "eightfold"
        )
        for i in items
        if _pcsx_key(host, i) not in pending
    ]
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items and not any(counts)
    result.truncated = truncated
    return result


# --- v2 -------------------------------------------------------------------------------------


async def _v2_search(
    fetcher: Fetcher, host: str, domain: str, query: str
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    count = 0
    for page_no in range(MAX_PAGES):
        url = (
            f"https://{host}/api/apply/v2/jobs?domain={domain}&query={query}"
            f"&start={page_no * PAGE}&num={PAGE}"
        )
        data = await fetcher.json("GET", url)
        if not isinstance(data, dict) or not isinstance(data.get("positions"), list):
            raise FetchError("unexpected Eightfold payload")
        if page_no == 0:
            if "count" not in data:
                raise FetchError("unexpected Eightfold payload (no result count)")
            count = int(data["count"] or 0)
        items.extend(data["positions"])
        if not data["positions"] or len(items) >= count:
            break
    return items, count


def _v2_key(host: str, item: dict[str, Any]) -> str:
    return f"{host}:{item.get('display_job_id') or item.get('ats_job_id') or item.get('id') or ''}"


async def fetch_v2(fetcher: Fetcher, company: Company) -> FetchResult:
    host, domain = _tenant(company, "eightfold_v2")
    found: list[dict[str, Any]] = []
    counts: list[int] = []
    truncated = False
    for query in QUERIES:
        items, count = await _v2_search(fetcher, host, domain, query)
        found.extend(items)
        counts.append(count)
        truncated = truncated or len(items) < count
    items = dedupe_by(found, lambda i: _v2_key(host, i))

    want = {
        _v2_key(host, i): f"https://{host}/api/apply/v2/jobs/{i['id']}?domain={domain}"
        for i in items
        if i.get("id") and wanted(i.get("name") or "")
    }
    details, pending = await fetch_details(
        fetcher, company, {_v2_key(host, i) for i in items}, want
    )
    records = []
    for i in items:
        key = _v2_key(host, i)
        if key in pending:
            continue
        d = details.get(key) or {}
        locations = i.get("locations") or [i.get("location") or ""]
        records.append(
            {
                "source": "eightfold",
                "source_job_id": key,
                "title": i.get("name") or "",
                "url": i.get("canonicalPositionUrl") or f"https://{host}/careers/job/{i['id']}",
                "location_raw": " | ".join(x for x in locations if x),
                "description_text": html_to_text(d.get("job_description") or ""),
                "source_posted_at": _when(i.get("t_create")),
                "work_mode_hint": _WORK_MODE.get(i.get("work_location_option") or ""),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    result.confirmed_empty = not items and not any(counts)
    result.truncated = truncated
    return result
