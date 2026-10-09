import httpx
import pytest

from scraper import db, discovery
from scraper.http import Fetcher


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://job-boards.greenhouse.io/Stripe/jobs/123", {"ats": "greenhouse", "slug": "stripe"}),
        ("https://boards.greenhouse.io/airbnb/jobs/9?gh_src=x", {"ats": "greenhouse", "slug": "airbnb"}),
        ("https://jobs.lever.co/Palantir/abc-def", {"ats": "lever", "slug": "palantir"}),
        ("https://jobs.eu.lever.co/Cirrus/abc/apply", {"ats": "lever_eu", "slug": "cirrus"}),
        ("https://ats.rippling.com/Rippling/jobs/u1", {"ats": "rippling", "slug": "rippling"}),
        ("https://jobs.ashbyhq.com/openai/uuid", {"ats": "ashby", "slug": "openai"}),
        ("https://jobs.smartrecruiters.com/ServiceNow/744-title", {"ats": "smartrecruiters", "slug": "ServiceNow"}),
        ("https://apply.workable.com/huggingface/j/ABC123/", {"ats": "workable", "slug": "huggingface"}),
        (
            "https://thomsonreuters.wd5.myworkdayjobs.com/en-US/External_Career_Site/job/Toronto/X_JR1",
            {"ats": "workday", "slug": "thomsonreuters/External_Career_Site",
             "workday_host": "thomsonreuters.wd5.myworkdayjobs.com",
             "workday_site": "External_Career_Site"},
        ),
        (
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA/Y_JR2?q=1",
            {"ats": "workday", "slug": "nvidia/NVIDIAExternalCareerSite",
             "workday_host": "nvidia.wd5.myworkdayjobs.com",
             "workday_site": "NVIDIAExternalCareerSite"},
        ),
    ],
)  # fmt: skip
def test_parse_board_url(url, expected):
    assert discovery.parse_board_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tesla.com/careers/search/job/123",
        "https://boards.greenhouse.io/embed/job_app?for=acme&token=1",
        "https://apply.workable.com/",
        "https://acme.wd5.myworkdayjobs.com/",
        "not a url",
        "",
    ],
)
def test_parse_board_url_ignores_junk(url):
    assert discovery.parse_board_url(url) is None


def listing(url, name="Acme", active=True, visible=True):
    return {"company_name": name, "url": url, "active": active, "is_visible": visible}


def test_extract_boards_dedupes_and_skips_inactive():
    boards = discovery.extract_boards([
        listing("https://jobs.lever.co/acme/1"),
        listing("https://jobs.lever.co/acme/2", name="Acme Inc"),
        listing("https://jobs.lever.co/old/3", active=False),
        listing("https://jobs.lever.co/hidden/4", visible=False),
        listing("https://example.com/x"),
    ])  # fmt: skip
    assert boards == [{"name": "Acme", "ats": "lever", "slug": "acme"}]


def test_discover_companies_inserts_only_new_as_warm(conn):
    db.upsert_companies(conn, [{"name": "Acme", "ats": "lever", "slug": "acme", "hot": True}])
    n = db.discover_companies(
        conn,
        [{"name": "Acme", "ats": "lever", "slug": "acme"},
         {"name": "Beta", "ats": "ashby", "slug": "beta"}],
    )  # fmt: skip
    assert n == 1
    rows = {r["slug"]: r for r in conn.execute("select * from companies")}
    assert rows["acme"]["tier"] == "hot" and rows["acme"]["discovered_from"] is None
    assert rows["beta"]["tier"] == "warm" and rows["beta"]["discovered_from"] == "simplify"


def test_state_sha_round_trip(conn):
    assert db.get_state_sha(conn, "simplify:x") is None
    db.set_state_sha(conn, "simplify:x", "abc")
    db.set_state_sha(conn, "simplify:x", "def")
    assert db.get_state_sha(conn, "simplify:x") == "def"


REPO = "SimplifyJobs/Summer2027-Internships"


def routed(sha="s1", listings=None, sha_status=200):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.github.com":
            return httpx.Response(sha_status, json={"sha": sha})
        return httpx.Response(200, json=listings or [])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Fetcher(client=client, base_delay=0), calls


async def test_discover_downloads_only_when_sha_changed(conn):
    boards = [listing("https://jobs.lever.co/acme/1")]
    f, calls = routed(sha="s1", listings=boards)
    async with f:
        assert await discovery.discover(f, conn, [REPO]) == 1
    assert calls == ["api.github.com", "raw.githubusercontent.com"]

    f, calls = routed(sha="s1", listings=boards)
    async with f:
        assert await discovery.discover(f, conn, [REPO]) == 0
    assert calls == ["api.github.com"]  # unchanged: no download
    assert db.get_state_sha(conn, f"simplify:{REPO}") == "s1"


async def test_discover_survives_github_failure_and_keeps_old_sha(conn):
    db.set_state_sha(conn, f"simplify:{REPO}", "old")
    f, calls = routed(sha_status=403)
    async with f:
        assert await discovery.discover(f, conn, [REPO]) == 0
    assert calls == ["api.github.com"]
    assert db.get_state_sha(conn, f"simplify:{REPO}") == "old"
