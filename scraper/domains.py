import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
import yaml

from scraper.http import Fetcher, FetchError

SUGGEST = "https://autocomplete.clearbit.com/v1/companies/suggest?query="
_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|holdings|holding|group|"
    r"the)\b"
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _SUFFIX.sub(" ", re.sub(r"[^a-z0-9 ]", " ", name.lower())))


def _label(domain: str) -> str:
    parts = domain.split(".")
    if len(parts) > 2 and len(parts[-1]) == 2 and len(parts[-2]) <= 3:  # example.co.uk
        return parts[-3]
    return parts[-2] if len(parts) > 1 else parts[0]


def _looks_like(domain: str, wanted: str) -> bool:
    """The site's own name resembles the company's (not 'latam-eventos-rackspace.com')."""
    label = _label(domain)
    squashed = label.replace("-", "")
    if squashed == wanted:
        return True
    if "-" in label or len(squashed) < 3:
        return False
    return wanted in squashed or squashed in wanted


def pick_domain(name: str, suggestions: list[dict[str, Any]]) -> str | None:
    """A suggestion (the list is ranked by popularity) with the same company name whose site is
    named like the company. The top hit is also trusted if its site has a plain one-word name
    (ti.com for Texas Instruments). No guess is better than another company's logo."""
    wanted = _norm(name)
    if not wanted:
        return None
    exact = [
        str(s.get("domain") or "").lower()
        for s in suggestions
        if s.get("domain") and _norm(str(s.get("name") or "")) == wanted
    ]
    for domain in exact:
        if _looks_like(domain, wanted):
            return domain
    if len(wanted) >= 4:  # "Marvell" for "Marvell Technology": the site must be named exactly so
        for s in suggestions:
            domain = str(s.get("domain") or "").lower()
            if domain and _norm(str(s.get("name") or "")).startswith(wanted):
                if _label(domain).replace("-", "") == wanted:
                    return domain
    top = str(suggestions[0].get("domain") or "").lower() if suggestions else ""
    if top and top in exact and "-" not in _label(top):
        return top
    return None


OVERRIDES = Path(__file__).resolve().parents[1] / "data" / "domain_overrides.yml"


def load_overrides(path: Path = OVERRIDES) -> dict[str, str]:
    """Hand-checked websites for companies the lookup cannot place, keyed by lower-case name."""
    data = yaml.safe_load(path.read_text()) or {}
    return {str(k).strip().lower(): str(v).strip().lower() for k, v in data.items()}


async def resolve_domains(
    fetcher: Fetcher,
    conn: psycopg.Connection,
    limit: int = 200,
    parallel: int = 5,
    overrides: dict[str, str] | None = None,
) -> int:
    """Look up the website of companies that have none, for their logo. A company the lookup
    answered for is not asked again (even when nothing matched); a failed lookup is retried."""
    known = load_overrides() if overrides is None else overrides
    filled = 0
    for name, domain in known.items():
        filled += conn.execute(
            """update companies set domain = %s, domain_checked_at = now()
               where lower(name) = %s and domain is null""",
            (domain, name),
        ).rowcount
    rows = conn.execute(
        """select c.id, c.name from companies c
           where c.domain is null and c.domain_checked_at is null
           order by (select count(*) from jobs j where j.company_id = c.id and j.status = 'open') desc,
                    c.id
           limit %s""",
        (limit,),
    ).fetchall()
    gate = asyncio.Semaphore(parallel)

    async def lookup(row: dict[str, Any]) -> tuple[int, str | None, bool]:
        async with gate:
            try:
                data = await fetcher.json("GET", SUGGEST + quote(row["name"]))
            except FetchError:
                return row["id"], None, False
        found = pick_domain(row["name"], data) if isinstance(data, list) else None
        return row["id"], found, True

    for company_id, domain, answered in await asyncio.gather(*(lookup(r) for r in rows)):
        if not answered:
            continue
        conn.execute(
            "update companies set domain = %s, domain_checked_at = now() where id = %s",
            (domain, company_id),
        )
        filled += domain is not None
    return filled
