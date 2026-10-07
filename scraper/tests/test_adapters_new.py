import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from scraper.adapters import ADAPTERS, workable
from scraper.adapters.base import get_details, wanted
from scraper.http import Fetcher, FetchError
from scraper.models import Company

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
