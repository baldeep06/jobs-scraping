from datetime import UTC, datetime

import httpx
import pytest

from scraper.adapters import ADAPTERS, amazon
from scraper.http import Fetcher, FetchError
from scraper.models import Company


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def co(ats):
    return Company(id=1, name=ats.title(), ats=ats, slug=ats)


# --- Amazon ---------------------------------------------------------------------------------


def amazon_job(i, title="Software Development Engineer Intern - 2027 (US)", **kw):
    base = {
        "id_icims": str(i), "title": title, "job_path": f"/en/jobs/{i}/sde-intern",
        "location": "US, WA, Seattle", "normalized_location": "Seattle, Washington, USA",
        "country_code": "USA", "posted_date": "October  8, 2026",
        "job_schedule_type": "full-time",
        "description": "Build services.<br/>Pay: $45 per hour.",
        "basic_qualifications": "- Currently enrolled in a BS",
        "preferred_qualifications": "- Python",
    }  # fmt: skip
    return base | kw


async def test_amazon_fetch_maps_fields_and_searches_both_queries():
    seen = []

    def handler(request):
        seen.append((request.url.params["base_query"], request.url.params["offset"]))
        assert request.url.params.get_list("country[]") == ["USA", "CAN"]
        if request.url.params["base_query"] == "intern":
            return httpx.Response(
                200, json={"hits": 2, "jobs": [amazon_job(1), amazon_job(2, "Account Executive")]}
            )
        co_op = amazon_job(3, "Software Engineer Co-op", country_code="CAN")
        return httpx.Response(200, json={"hits": 1, "jobs": [co_op]})

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["amazon"](f, co("amazon"))
    assert seen == [("intern", "0"), ("co-op", "0")]
    assert [j.source_job_id for j in result.jobs] == ["1", "2", "3"]
    job = result.jobs[0]
    assert job.source == "amazon" and job.url == "https://www.amazon.jobs/en/jobs/1/sde-intern"
    assert job.location_raw == "Seattle, Washington, USA" and job.country_hint == "US"
    assert job.source_posted_at == datetime(2026, 10, 8, tzinfo=UTC)
    assert "Pay: $45 per hour." in job.description_text and "Python" in job.description_text
    assert result.jobs[2].country_hint == "CA" and not result.confirmed_empty


async def test_amazon_pages_until_hits():
    offsets = []

    def handler(request):
        n = int(request.url.params["offset"])
        if request.url.params["base_query"] != "intern":
            return httpx.Response(200, json={"hits": 0, "jobs": []})
        offsets.append(n)
        jobs = [amazon_job(n + i, "Sales Rep") for i in range(100)]
        return httpx.Response(200, json={"hits": 230, "jobs": jobs})

    async with make_fetcher(handler) as f:
        result = await amazon.fetch(f, co("amazon"))
    assert offsets == [0, 100, 200] and len(result.jobs) == 300


async def test_amazon_zero_hits_is_confirmed_empty_and_bad_payload_raises():
    async with make_fetcher(lambda r: httpx.Response(200, json={"hits": 0, "jobs": []})) as f:
        assert (await amazon.fetch(f, co("amazon"))).confirmed_empty
    async with make_fetcher(lambda r: httpx.Response(200, json={"error": "x"})) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await amazon.fetch(f, co("amazon"))
    async with make_fetcher(lambda r: httpx.Response(200, text="<html>blocked</html>")) as f:
        with pytest.raises(FetchError):
            await amazon.fetch(f, co("amazon"))
