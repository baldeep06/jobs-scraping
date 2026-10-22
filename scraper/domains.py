import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import psycopg
import yaml

from scraper.http import Fetcher, FetchError

SUGGEST = "https://autocomplete.clearbit.com/v1/companies/suggest?query="
# Hosts that serve many companies' jobs (or profiles), so they say nothing about whose site it is.
_SHARED_HOSTS = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "myworkdaysite.com",
    "smartrecruiters.com", "workable.com", "icims.com", "eightfold.ai", "oraclecloud.com",
    "jobvite.com", "gem.com", "rippling.com", "avature.net", "successfactors.com",
    "successfactors.eu", "sapsf.com", "pinpointhq.com", "simplify.jobs", "intern-list.com",
    "linkedin.com", "indeed.com", "glassdoor.com", "taleo.net", "applytojob.com", "bamboohr.com",
    "breezy.hr", "recruitee.com", "teamtailor.com", "jibeapply.com", "phenompeople.com",
    "paylocity.com", "ultipro.com", "ukg.com", "adp.com", "dayforcehcm.com", "brassring.com",
    "jazzhr.com", "workforcenow.com", "csod.com", "github.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "youtube.com", "crunchbase.com", "wellfound.com",
    "yello.co", "careerpuck.com", "applicantpro.com", "gusto.com", "dover.com", "recsolu.com",
    "hireology.com", "ycombinator.com", "workatastartup.com", "notion.site", "notion.so",
    "google.com", "typeform.com", "careerplug.com", "paycomonline.net", "paycor.com",
    "trinethire.com", "freshteam.com", "zohorecruit.com", "comeet.com", "personio.com",
    "personio.de", "join.com", "homerun.co", "keka.com", "hrmdirect.com", "isolvedhire.com",
}  # fmt: skip
# Second-level labels under a country code: example.co.uk, example.com.au (but bnc.ca).
_SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu", "ne", "or", "go"}
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


def site_domain(url_or_host: str) -> str | None:
    """The registrable domain of a URL or host ("careers.celestica.com" -> "celestica.com"), or
    None for hosts shared by many companies (ATS vendors, job boards, social sites)."""
    host = urlsplit(url_or_host if "//" in url_or_host else f"//{url_or_host}").hostname or ""
    parts = [p for p in host.lower().split(".") if p]
    if len(parts) < 2:
        return None
    keep = 3 if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL else 2
    domain = ".".join(parts[-keep:])
    return None if domain in _SHARED_HOSTS else domain


def named_like(domain: str, name: str) -> bool:
    """The site is named after the company, or after its initials (gs.com, ea.com, ulalaunch)."""
    wanted = _norm(name)
    if not wanted:
        return False
    if _looks_like(domain, wanted):
        return True
    words = [w for w in _SUFFIX.sub(" ", re.sub(r"[^a-z0-9 ]", " ", name.lower())).split()]
    initials = "".join(w[0] for w in words if w not in {"and", "of", "&"})
    label = _label(domain).replace("-", "")
    return len(initials) >= 2 and label.startswith(initials)


def dominant_domain(urls: list[str]) -> str | None:
    """The company's own site, if most of its postings live there."""
    found = Counter(d for u in urls if (d := site_domain(u)))
    if not found:
        return None
    domain, n = found.most_common(1)[0]
    return domain if n * 2 > len(urls) else None


def domains_from_sites(conn: psycopg.Connection) -> int:
    """Fill websites from career sites we configured ourselves, for free: Eightfold tenants store
    the company's domain, and self-hosted sites (jobs.intuit.com) are on it. Unlike the lookups
    below, this runs for every company without a website, every time."""
    rows = conn.execute(
        "select id, ats, workday_host, workday_site from companies where domain is null"
    ).fetchall()
    filled = 0
    for r in rows:
        if r["ats"] in ("eightfold", "eightfold_v2") and r["workday_site"]:
            domain = site_domain(r["workday_site"])
        else:
            domain = site_domain(r["workday_host"]) if r["workday_host"] else None
        if domain:
            conn.execute(
                "update companies set domain = %s, has_logo = null, logo_host = null, domain_checked_at = now() where id = %s",
                (domain, r["id"]),
            )
            filled += 1
    return filled


_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def simplify_website(html: str) -> str | None:
    """The website on a Simplify company page (its schema.org Organization's sameAs)."""
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Organization":
            links = data.get("sameAs") or []
            for link in [links] if isinstance(links, str) else links:
                if isinstance(link, str) and (domain := site_domain(link)):
                    return domain
    return None


FAVICON = "https://www.google.com/s2/favicons?domain={}&sz=64"


async def has_logo(fetcher: Fetcher, domain: str) -> bool | None:
    """Whether the site shows a logo: Google's favicon service answers 404 (with a generic
    globe) for sites it has none for, which careers microsites often are. None: no answer."""
    try:
        await fetcher.response_headers("GET", FAVICON.format(quote(domain)))
    except FetchError as e:
        return False if e.status == 404 else None
    return True


async def logo_host(fetcher: Fetcher, domain: str) -> str | None | bool:
    """The host Google has a logo for: the domain, else its www. host (www.bny.com has an icon
    where bny.com has none). False when neither has one, None when Google did not answer."""
    hosts = [domain] if domain.startswith("www.") else [domain, f"www.{domain}"]
    for host in hosts:
        found = await has_logo(fetcher, host)
        if found is None:
            return None
        if found:
            return host
    return False


async def check_logos(
    fetcher: Fetcher, conn: psycopg.Connection, limit: int = 2000, parallel: int = 5
) -> int:
    """Record which websites have a logo, and on which host (the site shows a letter tile for
    the rest). Returns how many were found to have none."""
    rows = conn.execute(
        """select c.id, c.domain from companies c
           where c.domain is not null and c.has_logo is null
           order by (select count(*) from jobs j where j.company_id = c.id and j.status = 'open') desc,
                    c.id
           limit %s""",
        (limit,),
    ).fetchall()
    gate = asyncio.Semaphore(parallel)

    async def check(row: dict[str, Any]) -> tuple[int, str | None | bool]:
        async with gate:
            return row["id"], await logo_host(fetcher, row["domain"])

    missing = 0
    for company_id, host in await asyncio.gather(*(check(r) for r in rows)):
        if host is None:
            continue  # no answer: asked again next time
        conn.execute(
            "update companies set has_logo = %s, logo_host = %s where id = %s",
            (bool(host), host or None, company_id),
        )
        missing += not host
    return missing


async def simplify_pages(fetcher: Fetcher) -> dict[str, str]:
    """Lower-case company name -> its Simplify company page, from the Simplify listings."""
    from scraper.adapters.simplify import _listings  # local: adapters import scraper.http

    try:
        listings = await _listings(fetcher)
    except FetchError:
        return {}
    pages: dict[str, str] = {}
    for item in listings:
        url = str(item.get("company_url") or "")
        if url.startswith("https://simplify.jobs/c/"):
            pages.setdefault(str(item.get("company_name") or "").strip().lower(), url)
    return pages


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
    recheck: bool = False,
    pages: dict[str, str] | None = None,
) -> int:
    """Find the website of companies that have none, for their logo: hand-checked overrides,
    our configured career sites, the company's Simplify page, the site most of its postings are
    on (if named like the company and showing a logo), then Clearbit's lookup. A company the
    lookups answered for is not asked again (even when nothing matched) unless `recheck`; a
    failed lookup is retried. `pages` (name -> Simplify page) defaults to the Simplify lists."""
    # Hand-checked websites win, also over an earlier lookup's pick.
    known = load_overrides() if overrides is None else overrides
    filled = 0
    for name, domain in known.items():
        filled += conn.execute(
            """update companies set domain = %s, has_logo = null, logo_host = null, domain_checked_at = now()
               where lower(name) = %s and domain is distinct from %s""",
            (domain, name, domain),
        ).rowcount
    filled += domains_from_sites(conn)
    rows = conn.execute(
        """select c.id, c.name,
                  array(select j.best_url from jobs j
                        where j.company_id = c.id and j.best_url is not null) as urls
           from companies c
           where c.domain is null and (c.domain_checked_at is null or %s)
           order by (select count(*) from jobs j where j.company_id = c.id and j.status = 'open') desc,
                    c.id
           limit %s""",
        (recheck, limit),
    ).fetchall()
    if rows and pages is None:
        pages = await simplify_pages(fetcher)
    gate = asyncio.Semaphore(parallel)

    async def lookup(row: dict[str, Any]) -> tuple[int, str | None, bool]:
        async with gate:
            page = (pages or {}).get(row["name"].strip().lower())
            if page:
                try:
                    if found := simplify_website(await fetcher.text("GET", page)):
                        return row["id"], found, True
                except FetchError:
                    pass  # fall back to the lookup
            # Job links also lead to recruiting platforms and parent companies: the site must be
            # named like the company.
            own = dominant_domain(row["urls"])
            if own and named_like(own, row["name"]) and await has_logo(fetcher, own) is True:
                return row["id"], own, True
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
            "update companies set domain = %s, has_logo = null, logo_host = null, domain_checked_at = now() where id = %s",
            (domain, company_id),
        )
        filled += domain is not None
    await check_logos(fetcher, conn, limit=limit)
    return filled
