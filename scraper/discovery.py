import os
import re
from typing import Any

import psycopg

from scraper import db
from scraper.http import Fetcher, FetchError

SIMPLIFY_REPOS = ["SimplifyJobs/Summer2027-Internships"]
BRANCH = "dev"

_SEG = r"([^/?#]+)"
_WORKDAY = re.compile(
    r"^https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?" + _SEG, re.I
)
# (ats, pattern, slug is case-insensitive)
_SIMPLE = [
    ("greenhouse", re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/" + _SEG, re.I), True),
    ("lever", re.compile(r"^https?://jobs\.lever\.co/" + _SEG, re.I), True),
    ("ashby", re.compile(r"^https?://jobs\.ashbyhq\.com/" + _SEG, re.I), True),
    ("smartrecruiters", re.compile(r"^https?://jobs\.smartrecruiters\.com/" + _SEG, re.I), False),
    ("workable", re.compile(r"^https?://apply\.workable\.com/" + _SEG, re.I), True),
]
_NOT_A_BOARD = {"embed", "oneclick-ui", "j", "login", "api"}


def parse_board_url(url: str) -> dict[str, str] | None:
    """A job/board URL on a supported ATS -> the board we can poll directly, else None."""
    for ats, pattern, lower in _SIMPLE:
        m = pattern.match(url or "")
        if m and m.group(1).lower() not in _NOT_A_BOARD:
            slug = m.group(1)
            return {"ats": ats, "slug": slug.lower() if lower else slug}
    m = _WORKDAY.match(url or "")
    if m and m.group(3).lower() not in _NOT_A_BOARD:
        tenant, wd, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
        return {
            "ats": "workday",
            "slug": f"{tenant}/{site}",
            "workday_host": f"{tenant}.{wd}.myworkdayjobs.com",
            "workday_site": site,
        }
    return None


def extract_boards(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boards: dict[tuple[str, str], dict[str, Any]] = {}
    for item in listings:
        if not (item.get("active") and item.get("is_visible", True)):
            continue
        board = parse_board_url(item.get("url") or "")
        name = (item.get("company_name") or "").strip()
        if board and name:
            boards.setdefault((board["ats"], board["slug"]), {"name": name, **board})
    return list(boards.values())


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def discover(
    fetcher: Fetcher, conn: psycopg.Connection, repos: list[str] = SIMPLIFY_REPOS
) -> int:
    """Add boards found in the Simplify lists; a list is downloaded only if its repo has a new commit."""
    added = 0
    for repo in repos:
        state = f"simplify:{repo}"
        try:
            head = await fetcher.json(
                "GET", f"https://api.github.com/repos/{repo}/commits/{BRANCH}", headers=_headers()
            )
            sha = head["sha"]
            if sha == db.get_state_sha(conn, state):
                continue
            listings = await fetcher.json(
                "GET",
                f"https://raw.githubusercontent.com/{repo}/{BRANCH}/.github/scripts/listings.json",
            )
        except (FetchError, KeyError, TypeError) as e:
            print(f"discovery skipped for {repo}: {type(e).__name__}: {e}")
            continue
        if not isinstance(listings, list):
            print(f"discovery skipped for {repo}: unexpected listings payload")
            continue
        added += db.discover_companies(conn, extract_boards(listings))
        db.set_state_sha(conn, state, sha)  # only after a fully successful import
    return added
