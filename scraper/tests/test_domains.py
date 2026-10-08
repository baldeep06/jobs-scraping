import httpx
import pytest

from scraper import db
from scraper.domains import pick_domain, resolve_domains
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
        q = request.url.params["query"]
        asked.append(q)
        found = [{"name": "Zscaler", "domain": "zscaler.com"}] if q == "Zscaler" else []
        return httpx.Response(200, json=found)

    async with make_fetcher(handler) as f:
        assert await resolve_domains(f, conn) == 1
    rows = {r["name"]: r["domain"] for r in conn.execute("select name, domain from companies")}
    assert rows == {"Zscaler": "zscaler.com", "Nobody Co": None, "Stripe": "stripe.com"}
    assert sorted(asked) == ["Nobody Co", "Zscaler"]

    asked.clear()
    async with make_fetcher(handler) as f:  # already answered (even "unknown"): not asked again
        assert await resolve_domains(f, conn) == 0
    assert asked == []


async def test_resolve_domains_survives_lookup_errors_and_retries_them_later(conn):
    db.upsert_companies(conn, [{"name": "Zscaler", "ats": "greenhouse", "slug": "zscaler"}])

    async with make_fetcher(lambda r: httpx.Response(500)) as f:
        assert await resolve_domains(f, conn) == 0

    def ok(request):
        return httpx.Response(200, json=[{"name": "Zscaler", "domain": "zscaler.com"}])

    async with make_fetcher(ok) as f:
        assert await resolve_domains(f, conn) == 1


async def test_resolve_domains_respects_the_limit(conn):
    db.upsert_companies(
        conn, [{"name": f"Co{i}", "ats": "greenhouse", "slug": f"co{i}"} for i in range(5)]
    )
    async with make_fetcher(lambda r: httpx.Response(200, json=[])) as f:
        await resolve_domains(f, conn, limit=2)
    unchecked = conn.execute("select count(*) n from companies where domain_checked_at is null")
    assert unchecked.fetchone()["n"] == 3
