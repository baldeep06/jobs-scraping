from typing import Any

from scraper.adapters.base import as_id, validate
from scraper.http import Fetcher, FetchError
from scraper.models import Company, FetchResult

# TikTok's careers site (lifeattiktok.com) reads its postings from a public search API. Filtering
# on the internship recruit type ("202") gives every internship worldwide, description included,
# 100 a page: about 13 requests a poll. The API's location filter wants city codes, so the
# country is read from each posting's place (city -> state -> country) and only CA/US postings
# are kept.
SOURCE = "tiktok"
API = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
SITE = "https://lifeattiktok.com"
INTERN_TYPE = "202"
PAGE = 100
MAX_PAGES = 30
_HEADERS = {"website-path": "tiktok", "Origin": SITE, "Referer": f"{SITE}/"}
_HOME = {"united states of america": "US", "united states": "US", "canada": "CA"}


def _body(offset: int) -> dict[str, Any]:
    return {
        "recruitment_id_list": [INTERN_TYPE], "job_category_id_list": [], "subject_id_list": [],
        "location_code_list": [], "keyword": "", "limit": PAGE, "offset": offset,
    }  # fmt: skip


def places(post: dict[str, Any]) -> list[str]:
    """The posting's place from city up: ["Los Angeles", "California", "United States of America"]."""
    out, node = [], post.get("city_info")
    while isinstance(node, dict):
        if node.get("en_name"):
            out.append(str(node["en_name"]))
        node = node.get("parent")
    return out


def _record(post: dict[str, Any]) -> dict[str, Any]:
    where = places(post)
    country = _HOME.get(where[-1].lower(), "OTHER") if where else None
    text = "\n\n".join(str(post.get(k) or "") for k in ("description", "requirement")).strip()
    return {
        "source": SOURCE,
        "source_job_id": as_id(post.get("id")),
        "title": post.get("title") or "",
        "url": f"{SITE}/search/{post.get('id')}",
        "location_raw": ", ".join(where),
        "country_hint": country,
        "description_text": text,
        "employment_type_hint": ((post.get("recruit_type") or {}).get("en_name")),
    }


def parse(data: Any) -> tuple[list[dict[str, Any]], int]:
    page = data.get("data") if isinstance(data, dict) else None
    posts = page.get("job_post_list") if isinstance(page, dict) else None
    if not isinstance(posts, list) or "count" not in page:
        raise FetchError("unexpected TikTok payload")
    return [p for p in posts if isinstance(p, dict) and p.get("id")], int(page["count"] or 0)


async def fetch(fetcher: Fetcher, company: Company) -> FetchResult:
    posts: dict[str, dict[str, Any]] = {}
    total = 0
    for page_no in range(MAX_PAGES):
        data = await fetcher.json("POST", API, json=_body(page_no * PAGE), headers=_HEADERS)
        found, total = parse(data)
        posts.update((str(p["id"]), p) for p in found)
        if not found or (page_no + 1) * PAGE >= total:
            break
    records = [_record(p) for p in posts.values()]
    result = validate(r for r in records if r["country_hint"] in ("CA", "US"))
    result.confirmed_empty = not posts and total == 0
    result.truncated = len(posts) < total and (page_no + 1) == MAX_PAGES
    return result
