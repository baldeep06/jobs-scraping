import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from scraper.adapters import ADAPTERS, smartrecruiters, workable, workday
from scraper.adapters.base import get_details, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company
from scraper.normalize.location import parse_location

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def test_wanted_needs_intern_and_tech():
    assert wanted("Software Engineer Intern")
    assert not wanted("International Sales Manager")
    assert not wanted("Marketing Intern")  # intern but no tech category
    assert not wanted("Senior Software Engineer")
    assert wanted("Software Engineer", "Intern")  # employment type counts


async def test_get_details_skips_failures():
    def handler(request):
        if request.url.path.endswith("/bad"):
            return httpx.Response(404)
        if request.url.path.endswith("/list"):
            return httpx.Response(200, json=[1])
        return httpx.Response(200, json={"ok": request.url.path})

    async with make_fetcher(handler) as f:
        got = await get_details(
            f, {"a": "https://x.test/a", "b": "https://x.test/bad", "c": "https://x.test/list"}
        )
    assert got == {"a": {"ok": "/a"}}


async def test_workable_fetch_details_only_for_wanted_titles():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json=load("workable_list.json"))
        if request.url.path.endswith("AAA111"):
            return httpx.Response(200, json=load("workable_detail.json"))
        return httpx.Response(404)  # CCC333's detail vanished

    company = Company(id=1, name="Acme", ats="workable", slug="acme")
    async with make_fetcher(handler) as f:
        result = await ADAPTERS["workable"](f, company)

    assert ("GET", "/api/v2/accounts/acme/jobs/BBB222") not in seen  # not an intern title
    assert ("GET", "/api/v2/accounts/acme/jobs/AAA111") in seen
    # CCC333 wanted a detail that 404'd, so it is dropped from this poll.
    assert [j.source_job_id for j in result.jobs] == ["AAA111", "BBB222"]
    first = result.jobs[0]
    assert first.url == "https://apply.workable.com/acme/j/AAA111/"
    assert first.location_raw == "Toronto, Ontario, Canada"
    assert first.country_hint == "CA"
    assert first.work_mode_hint == "hybrid"
    assert first.employment_type_hint == "intern"
    assert first.source_posted_at == datetime(2026, 9, 30, tzinfo=UTC)
    assert first.description_text == "Build things.\nPython\nPay: CA$30 - CA$35 per hour."
    assert not result.confirmed_empty


async def test_workable_zero_total_is_confirmed_empty():
    def handler(request):
        return httpx.Response(200, json={"total": 0, "results": []})

    async with make_fetcher(handler) as f:
        result = await workable.fetch(f, Company(id=1, name="A", ats="workable", slug="a"))
    assert result.jobs == [] and result.confirmed_empty


async def test_workable_bad_payload_is_an_error():
    def handler(request):
        return httpx.Response(200, json={"oops": 1})

    async with make_fetcher(handler) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await workable.fetch(f, Company(id=1, name="A", ats="workable", slug="a"))


async def test_smartrecruiters_fetch():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.endswith("/postings") and request.method == "GET":
            return httpx.Response(200, json=load("smartrecruiters_list.json"))
        return httpx.Response(200, json=load("smartrecruiters_detail.json"))

    company = Company(id=1, name="Acme", ats="smartrecruiters", slug="Acme")
    async with make_fetcher(handler) as f:
        result = await ADAPTERS["smartrecruiters"](f, company)

    assert "https://api.smartrecruiters.com/v1/companies/Acme/postings/222" not in seen
    assert "https://api.smartrecruiters.com/v1/companies/Acme/postings/111" in seen
    assert [j.source_job_id for j in result.jobs] == ["111", "222"]
    job = result.jobs[0]
    assert job.url == "https://jobs.smartrecruiters.com/Acme/111-software-engineer-intern"
    assert job.location_raw == "Toronto, ON, Canada"
    assert job.country_hint == "CA"
    assert job.work_mode_hint == "hybrid"
    assert job.employment_type_hint == "Intern"
    assert job.source_posted_at == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert job.description_text.splitlines()[-1] == "Pay: US$40 - US$45 per hour."
    assert result.jobs[1].work_mode_hint == "remote"


async def test_smartrecruiters_paginates_until_total():
    offsets = []

    def handler(request):
        offsets.append(request.url.params["offset"])
        n = int(request.url.params["offset"])
        content = [
            {"id": str(n + i), "name": "Account Executive", "location": {}} for i in range(100)
        ]
        return httpx.Response(200, json={"totalFound": 250, "content": content})

    async with make_fetcher(handler) as f:
        result = await smartrecruiters.fetch(
            f, Company(id=1, name="A", ats="smartrecruiters", slug="A")
        )
    assert offsets == ["0", "100", "200"]
    assert len(result.jobs) == 300


async def test_smartrecruiters_zero_total_is_confirmed_empty():
    def handler(request):
        return httpx.Response(200, json={"totalFound": 0, "content": []})

    async with make_fetcher(handler) as f:
        result = await smartrecruiters.fetch(
            f, Company(id=1, name="A", ats="smartrecruiters", slug="A")
        )
    assert result.confirmed_empty


def wd_company(**kw):
    base = dict(
        id=1, name="Acme", ats="workday", slug="acme/Site",
        workday_host="acme.wd5.myworkdayjobs.com", workday_site="Site",
    )  # fmt: skip
    return Company(**(base | kw))


@pytest.mark.parametrize(
    ("raw", "expected_country", "expected_region"),
    [
        ("US, CA, Santa Clara", "US", "CA"),  # CA here is California
        ("CA, ON, Toronto", "CA", "ON"),
        ("CA, BC, Vancouver", "CA", "BC"),
    ],
)
def test_workday_locations_parse_to_the_right_country(raw, expected_country, expected_region):
    parsed = parse_location(workday.clean_location(raw))
    assert parsed.country == expected_country
    assert parsed.locations[0].region == expected_region


def test_clean_location_leaves_other_shapes_alone():
    assert workday.clean_location("Toronto, ON, Canada") == "Toronto, ON, Canada"
    assert workday.clean_location("Remote") == "Remote"


async def test_workday_fetch():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["searchText"] == "intern" and body["limit"] == 20
            return httpx.Response(200, json=load("workday_list.json"))
        if request.url.path.endswith("JR1"):
            return httpx.Response(200, json=load("workday_detail.json"))
        return httpx.Response(404)  # JR3's detail vanished

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["workday"](f, wd_company())

    assert ("POST", "/wday/cxs/acme/Site/jobs") in seen
    assert ("GET", "/wday/cxs/acme/Site/job/US-CA-Santa-Clara/Director_JR2") not in seen
    assert [j.source_job_id for j in result.jobs] == ["JR1", "JR2"]  # JR3 dropped this poll
    job = result.jobs[0]
    assert job.url.endswith("Software-Engineer-Intern_JR1")
    assert job.location_raw == "Santa Clara, CA, US | Toronto, ON, CA"  # not "2 Locations"
    assert job.description_text == "Build GPUs.\nThe hourly rate is US$45 per hour."
    assert job.source_posted_at is None
    assert not result.confirmed_empty


async def test_workday_pages_by_20_up_to_total():
    offsets = []

    def handler(request):
        body = json.loads(request.content)
        offsets.append(body["offset"])
        n = body["offset"]
        posts = [
            {"title": "Account Executive", "externalPath": f"/job/x/y_{n + i}",
             "bulletFields": [f"R{n + i}"], "locationsText": "US"}
            for i in range(20)
        ]  # fmt: skip
        return httpx.Response(200, json={"total": 45 if n == 0 else 0, "jobPostings": posts})

    async with make_fetcher(handler) as f:
        result = await workday.fetch(f, wd_company())
    assert offsets == [0, 20, 40]
    assert len(result.jobs) == 60


async def test_workday_zero_total_is_confirmed_empty():
    def handler(request):
        return httpx.Response(200, json={"total": 0, "jobPostings": []})

    async with make_fetcher(handler) as f:
        result = await workday.fetch(f, wd_company())
    assert result.confirmed_empty


async def test_workday_needs_host_and_site():
    async with make_fetcher(lambda r: httpx.Response(200, json={})) as f:
        with pytest.raises(FetchError, match="workday_host"):
            await workday.fetch(f, wd_company(workday_host=None))
