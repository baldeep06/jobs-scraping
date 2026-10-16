import httpx
import pytest

from scraper.adapters import ADAPTERS
from scraper.enrich import enrich
from scraper.http import Fetcher, FetchError
from scraper.models import Company


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def co(slug, id_=1):
    return Company(id=id_, name=slug, ats="simplify", slug=slug)


def listing(i, company="Tesla", **kw):
    return {
        "id": f"uuid-{i}", "company_name": company, "active": True, "is_visible": True,
        "title": "Software Engineering Intern", "url": f"https://www.tesla.com/careers/job/{i}",
        "locations": ["Palo Alto, CA", "Austin, TX"], "terms": ["Summer 2027"],
        "date_posted": 1790726400, "sponsorship": "Other",
    } | kw  # fmt: skip


LISTINGS = [
    listing(1),
    listing(2, active=False),
    listing(3, is_visible=False),
    listing(4, company="Two Sigma", url="https://twosigma.avature.net/careers/JobDetail/4"),
    listing(5, company="tesla"),
]


async def test_reads_only_active_visible_postings_of_that_company():
    async with make_fetcher(lambda r: httpx.Response(200, json=LISTINGS)) as f:
        result = await ADAPTERS["simplify"](f, co("Tesla"))
    assert sorted(j.source_job_id for j in result.jobs) == ["uuid-1", "uuid-5"]
    job = result.jobs[0]
    assert job.source == "simplify"
    assert job.url == "https://www.tesla.com/careers/job/1"
    assert job.location_raw == "Palo Alto, CA | Austin, TX"
    assert job.source_posted_at.year == 2026
    assert "Summer 2027" in job.description_text
    assert not result.confirmed_empty


async def test_downloads_the_list_once_per_run():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=LISTINGS)

    async with make_fetcher(handler) as f:
        a = await ADAPTERS["simplify"](f, co("Tesla"))
        b = await ADAPTERS["simplify"](f, co("Two Sigma", 2))
    assert len(calls) == 1
    assert "SimplifyJobs/Summer2027-Internships" in calls[0]
    assert [j.source_job_id for j in b.jobs] == ["uuid-4"] and len(a.jobs) == 2


async def test_unexpected_payload_is_an_error_not_an_empty_board():
    async with make_fetcher(lambda r: httpx.Response(200, json={"oops": 1})) as f:
        with pytest.raises(FetchError):
            await ADAPTERS["simplify"](f, co("Tesla"))


@pytest.mark.parametrize(
    ("sponsorship", "visa"),
    [
        ("Does Not Offer Sponsorship", "blocked"),
        ("U.S. Citizenship is Required", "blocked"),
        ("Offers Sponsorship", "open"),
        ("Other", "unknown"),
    ],
)
async def test_sponsorship_field_feeds_the_visa_status(sponsorship, visa):
    data = [listing(1, sponsorship=sponsorship)]
    async with make_fetcher(lambda r: httpx.Response(200, json=data)) as f:
        result = await ADAPTERS["simplify"](f, co("Tesla"))
    assert enrich(result.jobs[0], 1).visa_status == visa


async def test_a_missing_list_never_counts_as_the_company_404ing():
    # The repo is renamed every season; that must not deactivate every Simplify company.
    async with make_fetcher(lambda r: httpx.Response(404)) as f:
        with pytest.raises(FetchError) as exc:
            await ADAPTERS["simplify"](f, co("Tesla"))
    assert exc.value.status is None
