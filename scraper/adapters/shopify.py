import json
import re
from datetime import datetime
from typing import Any

from scraper.adapters.base import read_pages, validate, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult

# Shopify's careers site (React Router; postings come from a private Ashby board). The page data
# is not JSON but React Router's "turbo-stream": one flat array where objects are written as
# {"_<key index>": <value index>}. /careers/search lists every posting (title, location, type,
# date); a posting's own page adds the description. robots.txt only disallows /careers/search?*,
# so the list is read without a query string.
SOURCE = "shopify"
SEARCH = "https://www.shopify.com/careers/search"
_STREAM = re.compile(r"streamController\.enqueue\((\".*?\")\);", re.S)
_WORK_MODE = {"Remote": "remote", "Hybrid": "hybrid", "OnSite": "onsite", "Onsite": "onsite"}


def decode_stream(html: str) -> Any:
    """The page's React Router data (the first turbo-stream line, deferred parts left out)."""
    chunks = _STREAM.findall(html)
    if not chunks:
        raise FetchError("unexpected Shopify page (no route data)")
    try:
        flat = json.loads("".join(json.loads(c) for c in chunks).split("\n")[0])
    except ValueError as e:
        raise FetchError("unexpected Shopify page (unreadable route data)") from e
    if not isinstance(flat, list):
        raise FetchError("unexpected Shopify page (route data is not a list)")
    done: dict[int, Any] = {}

    def value(i: Any) -> Any:
        if not isinstance(i, int) or i >= len(flat):
            return None
        if i < 0:  # turbo-stream's null, undefined, NaN, infinities, holes
            return 0 if i == -4 else None
        if i in done:
            return done[i]
        raw = flat[i]
        if isinstance(raw, dict):
            obj: dict[str, Any] = {}
            done[i] = obj
            for k, v in raw.items():
                key = flat[int(k[1:])] if k[1:].isdigit() and int(k[1:]) < len(flat) else k
                obj[str(key)] = value(v)
            return obj
        if isinstance(raw, list):
            if raw and isinstance(raw[0], str):  # typed value: ["D", date], ["P", promise], ...
                done[i] = raw
                return raw
            arr: list[Any] = []
            done[i] = arr
            arr.extend(value(x) for x in raw)
            return arr
        return raw

    return value(0)


def find_all(node: Any, key: str) -> list[dict[str, Any]]:
    """Every object holding `key`, depth first."""
    out, stack, seen = [], [node], set()
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, dict):
            if key in n:
                out.append(n)
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)
    return out


def job_url(posting: dict[str, Any]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(posting.get("title") or "").lower()).strip("-")
    return f"https://www.shopify.com/careers/{slug}_{posting['id']}"


def parse_search(html: str) -> list[dict[str, Any]]:
    lists = find_all(decode_stream(html), "jobPostingsWithJobs")
    rows = lists[0].get("jobPostingsWithJobs") if lists else None
    if not isinstance(rows, list):
        raise FetchError("unexpected Shopify search page (no postings)")
    postings = [r.get("jobPosting") for r in rows if isinstance(r, dict)]
    return [p for p in postings if isinstance(p, dict) and p.get("id") and p.get("title")]


def parse_posting(html: str) -> dict[str, Any]:
    found = find_all(decode_stream(html), "descriptionPlain")
    return found[0] if found else {}


def _posted(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    postings = [
        p
        for p in parse_search(await fetcher.text("GET", SEARCH))
        if p.get("isListed") is not False and wanted(p["title"], p.get("employmentType"))
    ]
    want = {str(p["id"]): job_url(p) for p in postings}
    pages, pending = await read_pages(fetcher, company, set(want), want)
    records = []
    for p in postings:
        pid = str(p["id"])
        if pid in pending:
            continue
        detail = parse_posting(pages[pid]) if pid in pages else {}
        records.append(
            {
                "source": SOURCE,
                "source_job_id": pid,
                "title": p["title"],
                "url": want[pid],
                "location_raw": p.get("locationName") or "",
                "description_text": detail.get("descriptionPlain") or "",
                "source_posted_at": _posted(p.get("publishedDate")),
                "work_mode_hint": _WORK_MODE.get(str(p.get("workplaceType") or "")),
                "employment_type_hint": p.get("employmentType"),
            }
        )
    result = validate(records)
    result.pending_ids = pending
    return result
