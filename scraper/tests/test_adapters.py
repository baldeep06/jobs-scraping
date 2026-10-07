import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from scraper.adapters import ADAPTERS, ashby, greenhouse, lever
from scraper.http import Fetcher, FetchError
from scraper.models import Company

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_greenhouse_parse():
    result = greenhouse.parse(load("greenhouse.json"))
    assert result.invalid == 1
    assert [j.source_job_id for j in result.jobs] == ["7001", "7002", "7003"]
    first = result.jobs[0]
    assert first.source == "greenhouse"
    assert first.url == "https://boards.greenhouse.io/acme/jobs/7001"
    assert first.location_raw == "Toronto, ON"
    assert first.source_posted_at == datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
    assert first.description_text == "Join our team.\nThe hourly rate is CA$30 - CA$38 per hour."
    assert result.jobs[1].source_posted_at == datetime(2026, 9, 30, 14, 0, tzinfo=UTC)


def test_greenhouse_unexpected_payload():
    with pytest.raises(FetchError, match="unexpected"):
        greenhouse.parse(["not", "a", "dict"])


async def test_greenhouse_fetch_uses_board_url():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=load("greenhouse.json"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with Fetcher(client=client, base_delay=0) as f:
        company = Company(id=1, name="Acme", ats="greenhouse", slug="acme")
        result = await ADAPTERS["greenhouse"](f, company)
    assert seen == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"]
    assert len(result.jobs) == 3


def test_lever_parse():
    result = lever.parse(load("lever.json"))
    assert result.invalid == 0 and len(result.jobs) == 2
    job = result.jobs[0]
    assert job.source == "lever"
    assert job.title == "Software Engineer Co-op (4 months)"
    assert job.location_raw == "Waterloo, ON | Toronto, ON"
    assert job.source_posted_at == datetime.fromtimestamp(1790000000, UTC)
    assert job.description_text == (
        "Build things.\nRequirements\nEnrolled in a co-op program at a Canadian university"
    )
    assert (job.pay_structured.min, job.pay_structured.max) == (32, 40)
    assert (job.pay_structured.currency, job.pay_structured.period) == ("CAD", "hour")
    hints = (job.country_hint, job.work_mode_hint, job.employment_type_hint)
    assert hints == ("CA", "hybrid", "Internship")
    assert result.jobs[1].work_mode_hint is None
    assert result.jobs[1].location_raw == "Austin, TX"


def test_lever_unexpected_payload():
    with pytest.raises(FetchError, match="unexpected"):
        lever.parse({"ok": False})


def test_ashby_parse():
    result = ashby.parse(load("ashby.json"))
    assert [j.source_job_id[-1] for j in result.jobs] == ["1", "3"]  # unlisted job skipped
    job = result.jobs[0]
    assert job.source == "ashby"
    assert job.location_raw == "San Francisco, CA | New York, NY"
    assert job.source_posted_at == datetime(2026, 10, 1, 15, 30, tzinfo=UTC)
    assert (
        job.description_text == "Visa sponsorship is available for this role.\n$50 – $60 per hour"
    )
    assert (job.pay_structured.min, job.pay_structured.max) == (50, 60)
    assert (job.pay_structured.currency, job.pay_structured.period) == ("USD", "hour")
    hints = (job.country_hint, job.work_mode_hint, job.employment_type_hint)
    assert hints == ("US", "onsite", "Intern")
    london = result.jobs[1]
    assert (london.country_hint, london.work_mode_hint) == ("OTHER", "hybrid")


def test_ashby_unexpected_payload():
    with pytest.raises(FetchError, match="unexpected"):
        ashby.parse({"apiVersion": "1"})


def test_registry_has_all_phase1_adapters():
    assert {"greenhouse", "lever", "ashby"} <= set(ADAPTERS)
