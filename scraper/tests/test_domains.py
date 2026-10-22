import json

import httpx
import pytest

from scraper import db
from scraper.domains import (
    dominant_domain,
    named_like,
    pick_domain,
    resolve_domains,
    simplify_website,
    site_domain,
)
from scraper.http import Fetcher


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


@pytest.mark.parametrize(
    ("name", "suggestions", "expected"),
    [
        (
            "Zscaler",
            [
                {"name": "Zscaler", "domain": "zscaler.com"},
                {"name": "Zscaler", "domain": "zscaler.fr"},
            ],
            "zscaler.com",
        ),
        ("Zscaler, Inc.", [{"name": "Zscaler", "domain": "zscaler.com"}], "zscaler.com"),
        ("Block", [{"name": "Block Inc", "domain": "block.xyz"}], "block.xyz"),
        ("Via", [{"name": "Viator", "domain": "viator.com"}], None),  # near misses are not matches
        # The same name on a regional/partner site is not the company's own site.
        ("Rackspace", [{"name": "Rackspace", "domain": "latam-eventos-rackspace.com"}], None),
        (
            "Rackspace",
            [
                {"name": "Rackspace", "domain": "x.com"},
                {"name": "Rackspace", "domain": "rackspace.com"},
            ],
            "rackspace.com",
        ),
        (
            "The Walt Disney Company",
            [{"name": "The Walt Disney Company", "domain": "disney.com"}],
            "disney.com",
        ),
        # The top hit of an exact-name match is trusted when its site has a plain one-word name.
        ("Texas Instruments", [{"name": "Texas Instruments", "domain": "ti.com"}], "ti.com"),
        ("Texas Instruments", [{"name": "Texas Instruments", "domain": "texas-japan.com"}], None),
        # A longer registered name ("Marvell Technology") still matches the short one.
        ("Marvell", [{"name": "Marvell Technology", "domain": "marvell.com"}], "marvell.com"),
        ("KLA", [{"name": "Klaviyo", "domain": "klaviyo.com"}], None),
        ("Acme", [], None),
        ("Acme", [{"name": "Acme", "domain": ""}, {"name": "Acme", "domain": None}], None),
    ],
)
def test_pick_domain_needs_the_same_company_name(name, suggestions, expected):
    assert pick_domain(name, suggestions) == expected


async def test_resolve_domains_fills_missing_ones_once(conn):
    db.upsert_companies(
        conn,
        [
            {"name": "Zscaler", "ats": "greenhouse", "slug": "zscaler"},
            {"name": "Nobody Co", "ats": "greenhouse", "slug": "nobody"},
            {"name": "Stripe", "ats": "greenhouse", "slug": "stripe", "domain": "stripe.com"},
        ],
    )
    asked = []

    def handler(request):
        if request.url.host == "www.google.com":  # the logo check
            return httpx.Response(200)
        q = request.url.params["query"]
        asked.append(q)
        found = [{"name": "Zscaler", "domain": "zscaler.com"}] if q == "Zscaler" else []
        return httpx.Response(200, json=found)

    async with make_fetcher(handler) as f:
        assert await resolve_domains(f, conn, pages={}) == 1
    rows = {r["name"]: r["domain"] for r in conn.execute("select name, domain from companies")}
    assert rows == {"Zscaler": "zscaler.com", "Nobody Co": None, "Stripe": "stripe.com"}
    assert sorted(asked) == ["Nobody Co", "Zscaler"]

    asked.clear()
    async with make_fetcher(handler) as f:  # already answered (even "unknown"): not asked again
        assert await resolve_domains(f, conn, pages={}) == 0
    assert asked == []


async def test_resolve_domains_survives_lookup_errors_and_retries_them_later(conn):
    db.upsert_companies(conn, [{"name": "Zscaler", "ats": "greenhouse", "slug": "zscaler"}])

    async with make_fetcher(lambda r: httpx.Response(500)) as f:
        assert await resolve_domains(f, conn, pages={}) == 0

    def ok(request):
        return httpx.Response(200, json=[{"name": "Zscaler", "domain": "zscaler.com"}])

    async with make_fetcher(ok) as f:
        assert await resolve_domains(f, conn, pages={}) == 1


async def test_resolve_domains_respects_the_limit(conn):
    db.upsert_companies(
        conn, [{"name": f"Co{i}", "ats": "greenhouse", "slug": f"co{i}"} for i in range(5)]
    )
    async with make_fetcher(lambda r: httpx.Response(200, json=[])) as f:
        await resolve_domains(f, conn, limit=2, pages={})
    unchecked = conn.execute("select count(*) n from companies where domain_checked_at is null")
    assert unchecked.fetchone()["n"] == 3


async def test_overrides_win_over_the_lookup_and_are_matched_case_insensitively(conn):
    db.upsert_companies(
        conn,
        [
            {"name": "Booz Allen", "ats": "greenhouse", "slug": "booz"},
            {"name": "Zscaler", "ats": "greenhouse", "slug": "zscaler"},
        ],
    )
    asked = []

    def handler(request):
        if request.url.host == "www.google.com":  # the logo check
            return httpx.Response(200)
        asked.append(request.url.params["query"])
        return httpx.Response(200, json=[{"name": "Zscaler", "domain": "zscaler.com"}])

    async with make_fetcher(handler) as f:
        await resolve_domains(f, conn, overrides={"booz allen": "boozallen.com"}, pages={})
    rows = {r["name"]: r["domain"] for r in conn.execute("select name, domain from companies")}
    assert rows == {"Booz Allen": "boozallen.com", "Zscaler": "zscaler.com"}
    assert asked == ["Zscaler"]


def test_the_shipped_override_file_is_well_formed():
    from scraper.domains import load_overrides

    overrides = load_overrides()
    assert overrides and all("." in d and d == d.lower() for d in overrides.values())
    assert all(k == k.lower() for k in overrides)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://careers.celestica.com/job/x/1/", "celestica.com"),
        ("emplois.bnc.ca", "bnc.ca"),
        ("https://www.example.co.uk/jobs", "example.co.uk"),
        ("https://boards.greenhouse.io/stripe/jobs/1", None),
        ("https://acme.wd5.myworkdayjobs.com/en-US/External", None),
        ("bloomberg.avature.net/careers", None),
        ("not a url", None),
    ],
)
def test_site_domain_skips_hosts_shared_by_many_companies(url, expected):
    assert site_domain(url) == expected


def test_dominant_domain_needs_most_postings_on_one_site():
    own = ["https://www.tesla.com/careers/1", "https://www.tesla.com/careers/2"]
    assert dominant_domain(own + ["https://boards.greenhouse.io/x/1"]) == "tesla.com"
    assert dominant_domain(own + ["https://a.test/1", "https://b.test/2"]) is None
    assert dominant_domain([]) is None


@pytest.mark.parametrize(
    ("domain", "name", "expected"),
    [
        ("lifeattiktok.com", "TikTok", True),
        ("gs.com", "Goldman Sachs", True),
        ("itw.com", "Illinois Tool Works", True),
        ("ulalaunch.com", "United Launch Alliance", True),
        ("yello.co", "Ernst & Young", False),
        ("mhicareers.com", "Primetals Technologies", False),
    ],
)
def test_named_like_accepts_the_name_or_its_initials(domain, name, expected):
    assert named_like(domain, name) is expected


def simplify_page(same_as):
    org = {"@type": "Organization", "name": "TikTok", "url": "https://simplify.jobs/c/TikTok",
           "sameAs": same_as}  # fmt: skip
    return f'<script type="application/ld+json">{json.dumps(org)}</script>'


def test_simplify_website_reads_the_organization_and_skips_social_links():
    assert simplify_website(simplify_page(["https://www.tiktok.com/"])) == "tiktok.com"
    assert simplify_website(simplify_page(["https://linkedin.com/company/x"])) is None
    assert simplify_website("<html></html>") is None


async def test_own_sites_fill_websites_without_any_lookup(conn):
    db.upsert_companies(
        conn,
        [
            {"name": "Qualcomm", "ats": "eightfold", "slug": "qualcomm",
             "workday_host": "qualcomm.eightfold.ai", "workday_site": "qualcomm.com"},
            {"name": "Celestica", "ats": "successfactors", "slug": "celestica",
             "workday_host": "careers.celestica.com", "workday_site": "-"},
            {"name": "Tesla", "ats": "simplify", "slug": "Tesla"},
            {"name": "Ernst & Young", "ats": "simplify", "slug": "Ernst & Young"},
        ],
    )  # fmt: skip
    ids = {r["name"]: r["id"] for r in conn.execute("select id, name from companies")}
    for name, url in [("Tesla", "https://www.tesla.com/careers/1"),
                      ("Ernst & Young", "https://eygr.yello.co/jobs/1")]:  # fmt: skip
        conn.execute(
            """insert into jobs (company_id, title, normalized_title, category, country,
                                 visa_status, fingerprint, best_url)
               values (%s, 't', 'x', 'SWE', 'US', 'open', %s, %s)""",
            (ids[name], name, url),
        )

    def nothing(request):
        return httpx.Response(200, json=[])

    async with make_fetcher(nothing) as f:
        assert await resolve_domains(f, conn, pages={}) == 3
    rows = {r["name"]: r["domain"] for r in conn.execute("select name, domain from companies")}
    assert rows == {"Qualcomm": "qualcomm.com", "Celestica": "celestica.com",
                    "Tesla": "tesla.com", "Ernst & Young": None}  # fmt: skip


async def test_simplify_page_comes_before_the_lookup_and_recheck_retries_misses(conn):
    db.upsert_companies(conn, [{"name": "TikTok", "ats": "simplify", "slug": "TikTok"}])
    conn.execute("update companies set domain_checked_at = now()")  # an earlier miss
    asked = []

    def handler(request):
        asked.append(request.url.host)
        if request.url.host == "simplify.jobs":
            return httpx.Response(200, text=simplify_page(["https://www.tiktok.com/"]))
        return httpx.Response(200, json=[])

    pages = {"tiktok": "https://simplify.jobs/c/TikTok"}
    async with make_fetcher(handler) as f:
        assert await resolve_domains(f, conn, pages=pages) == 0  # misses are not retried
        assert await resolve_domains(f, conn, pages=pages, recheck=True) == 1
    assert asked == ["simplify.jobs", "www.google.com"]  # the page, then tiktok.com's logo
    assert conn.execute("select domain from companies").fetchone()["domain"] == "tiktok.com"


async def test_a_postings_site_without_a_logo_is_not_used(conn):
    db.upsert_companies(conn, [{"name": "TikTok", "ats": "simplify", "slug": "TikTok"}])
    cid = conn.execute("select id from companies").fetchone()["id"]
    conn.execute(
        """insert into jobs (company_id, title, normalized_title, category, country,
                             visa_status, fingerprint, best_url)
           values (%s, 't', 'x', 'SWE', 'US', 'open', 'f', 'https://lifeattiktok.com/job/1')""",
        (cid,),
    )

    def handler(request):
        if request.url.host == "www.google.com":  # no favicon for the careers microsite
            return httpx.Response(404)
        return httpx.Response(200, json=[{"name": "TikTok", "domain": "tiktok.com"}])

    async with make_fetcher(handler) as f:
        assert await resolve_domains(f, conn, pages={}) == 1
    assert conn.execute("select domain from companies").fetchone()["domain"] == "tiktok.com"


async def test_reseeding_without_a_domain_keeps_the_one_we_found(conn):
    seed = [{"name": "Rippling", "ats": "rippling", "slug": "rippling"}]
    db.upsert_companies(conn, seed)
    conn.execute("update companies set domain = 'rippling.com', has_logo = true")
    db.upsert_companies(conn, seed)
    row = conn.execute("select domain, has_logo from companies").fetchone()
    assert (row["domain"], row["has_logo"]) == ("rippling.com", True)
    db.upsert_companies(conn, [seed[0] | {"domain": "rippling.io"}])  # a new site: check again
    row = conn.execute("select domain, has_logo from companies").fetchone()
    assert (row["domain"], row["has_logo"]) == ("rippling.io", None)


async def test_logos_are_checked_and_the_feed_hides_sites_without_one(conn):
    db.upsert_companies(
        conn,
        [
            {"name": "Stripe", "ats": "greenhouse", "slug": "stripe", "domain": "stripe.com"},
            {"name": "TikTok", "ats": "simplify", "slug": "TikTok", "domain": "lifeattiktok.com"},
            {"name": "Flaky", "ats": "greenhouse", "slug": "flaky", "domain": "flaky.com"},
        ],
    )

    def handler(request):
        domain = request.url.params.get("domain")
        if domain in ("lifeattiktok.com", "www.lifeattiktok.com", "stripe.com"):
            return httpx.Response(404)  # stripe.com has its icon on www.stripe.com only
        if domain == "flaky.com":
            return httpx.Response(500)  # unknown: asked again next time
        return httpx.Response(200, json=[])

    async with make_fetcher(handler) as f:
        await resolve_domains(f, conn, pages={})
    logos = {r["name"]: r["has_logo"] for r in conn.execute("select name, has_logo from companies")}
    assert logos == {"Stripe": True, "TikTok": False, "Flaky": None}

    ids = {r["name"]: r["id"] for r in conn.execute("select id, name from companies")}
    for name in ids:
        conn.execute(
            """insert into jobs (company_id, title, normalized_title, category, country,
                                 visa_status, fingerprint, best_url)
               values (%s, 't', 'x', 'SWE', 'US', 'open', %s, 'https://x')""",
            (ids[name], name),
        )
    feed = {r["company_name"]: r["company_domain"] for r in conn.execute("select * from jobs_feed")}
    assert feed == {"Stripe": "www.stripe.com", "TikTok": None, "Flaky": "flaky.com"}


async def test_a_hand_checked_website_replaces_an_earlier_wrong_pick(conn):
    db.upsert_companies(conn, [{"name": "Anduril", "ats": "greenhouse", "slug": "anduril"}])
    conn.execute("update companies set domain = 'andurilgroup.co.za', has_logo = false")

    def handler(request):
        return httpx.Response(200, json=[])

    async with make_fetcher(handler) as f:
        await resolve_domains(f, conn, overrides={"anduril": "anduril.com"}, pages={})
    row = conn.execute("select domain, has_logo, logo_host from companies").fetchone()
    assert (row["domain"], row["has_logo"], row["logo_host"]) == (
        "anduril.com",
        True,
        "anduril.com",
    )
