import asyncio
import json

import httpx
import pytest

from scraper.adapters import ADAPTERS, internlist
from scraper.http import Fetcher, FetchError
from scraper.models import Company


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(internlist, "DELAY", 0)


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def co(slug, id_=1, known=(), checked=()):
    return Company(
        id=id_,
        name=slug,
        ats="internlist",
        slug=slug,
        known_ids=set(known),
        checked_ids=set(checked),
    )


def row(slug, title, company):
    return (
        f'<div role="listitem" class="collection-item-8 w-dyn-item"><a href="/swe-intern-list/{slug}"'
        f' class="flex-block-27 w-inline-block"><div class="w-layout-hflex joblist">'
        f'<p class="jobtitle">{title}</p><p class="blogtag">October 15, 2026</p></div>'
        f'<p class="companyname_list">{company}</p></a></div>'
    )


def list_page(rows, next_page=None):
    nav = f'<a href="?e3be0bc2_page={next_page}" class="w-pagination-next">' if next_page else ""
    return (
        '<div class="collection-list-wrapper-2 w-dyn-list"><div role="list" class="w-dyn-items">'
        + "".join(rows)
        + f"</div>{nav}</div>"
    )


def detail(title="Software Engineering Intern", closed=False, **kw):
    posting = {
        "@type": "JobPosting", "title": title, "description": "<p>Build things.</p>",
        "datePosted": "2026-10-15 04:31:16", "employmentType": ["INTERN"],
        "jobLocation": {"address": {"addressLocality": "Mason", "addressRegion": "OH",
                                    "addressCountry": "US"}},
        "baseSalary": {"currency": "USD", "value": {"minValue": 18.0, "maxValue": 50.0,
                                                    "unitText": "HOUR"}},
    } | kw  # fmt: skip
    hidden = "" if closed else " w-condition-invisible"
    return (
        f'<a href="https://jobright.ai/jobs/info/abc" class="link-2">Apply Now</a>'
        f'<div class="div-block-147{hidden}"><div class="code-embed-22 w-embed"><svg></svg></div>'
        f"<div>This job has closed.</div></div>"
        f"<div class=\"w-richtext\"><script id='job-posting' type='application/ld+json'>"
        f"{json.dumps(posting)}</script></div>"
    )


SWE_P1 = list_page(
    [
        row("swe_intern_at_siemens_101", "Software Engineering Intern", "Siemens"),
        row("sales_intern_at_siemens_102", "Sales Intern", "Siemens"),
        row("swe_intern_at_ibm_103", "Software Developer Intern", "IBM"),
    ],
    next_page=2,
)
SWE_P2 = list_page([row("ml_intern_at_siemens_104", "Machine Learning Intern", "Siemens")])
OTHER = list_page([])


def site(requests, details=None):
    details = details or {}

    def handler(request):
        requests.append(request)
        path, page = request.url.path, request.url.params.get("e3be0bc2_page")
        if path == "/swe-intern-list":
            return httpx.Response(200, text=SWE_P2 if page == "2" else SWE_P1)
        if path in {f"/{name}" for name in internlist.LISTS}:
            return httpx.Response(200, text=OTHER)
        slug = path.rsplit("/", 1)[-1]
        if slug in details:
            return details[slug]
        return httpx.Response(200, text=detail(title=slug))

    return handler


async def test_reads_that_companys_postings_across_pages_with_details():
    requests = []
    async with make_fetcher(site(requests)) as f:
        result = await ADAPTERS["internlist"](f, co("Siemens"))
    jobs = sorted(result.jobs, key=lambda j: j.source_job_id)
    assert [j.source_job_id for j in jobs] == ["101", "104"]  # the sales intern is skipped
    job = jobs[0]
    assert job.source == "internlist"
    assert job.url == "https://www.intern-list.com/swe-intern-list/swe_intern_at_siemens_101"
    assert job.location_raw == "Mason, OH, US"
    assert job.description_text == "Build things."
    assert job.source_posted_at.isoformat() == "2026-10-15T04:31:16+00:00"
    assert job.pay_structured.model_dump() == {
        "min": 18.0, "max": 50.0, "currency": "USD", "period": "hour"
    }  # fmt: skip
    opened = [r.url.path for r in requests if r.url.path.count("/") == 2]
    assert "/swe-intern-list/sales_intern_at_siemens_102" not in opened
    assert result.confirmed_empty  # the lists parsed, so a company with no rows really has none


async def test_lists_are_read_once_per_run():
    requests = []
    async with make_fetcher(site(requests)) as f:
        await ADAPTERS["internlist"](f, co("Siemens"))
        ibm = await ADAPTERS["internlist"](f, co("IBM", 2))
    list_reads = [r for r in requests if r.url.path.count("/") == 1]
    assert len(list_reads) == len(internlist.LISTS) + 1  # the SWE list has a second page
    assert [j.source_job_id for j in ibm.jobs] == ["103"]


async def test_company_names_match_loosely():
    async with make_fetcher(site([])) as f:
        result = await ADAPTERS["internlist"](f, co("siemens"))
    assert len(result.jobs) == 2


async def test_closed_postings_are_left_out_and_remembered():
    details = {"swe_intern_at_siemens_101": httpx.Response(200, text=detail(closed=True))}
    async with make_fetcher(site([], details)) as f:
        result = await ADAPTERS["internlist"](f, co("Siemens"))
    assert [j.source_job_id for j in result.jobs] == ["104"]
    assert result.rejected_ids == {"101"}


async def test_known_and_checked_postings_are_not_reopened():
    requests = []
    async with make_fetcher(site(requests)) as f:
        result = await ADAPTERS["internlist"](
            f, co("Siemens", known={"101"}, checked={"104", "999"})
        )
    assert not [r for r in requests if r.url.path.count("/") == 2]
    assert result.jobs == []
    assert result.pending_ids == {"101"}  # still listed, so it stays open
    assert result.forgotten_ids == {"999"}  # left the list: no need to remember it


async def test_a_failed_detail_page_is_retried_next_time():
    details = {"swe_intern_at_siemens_101": httpx.Response(404)}
    async with make_fetcher(site([], details)) as f:
        result = await ADAPTERS["internlist"](f, co("Siemens"))
    assert [j.source_job_id for j in result.jobs] == ["104"]
    assert "101" not in result.rejected_ids


async def test_detail_pages_are_fetched_one_at_a_time():
    active = 0
    peak = 0

    async def handler(request):
        nonlocal active, peak
        if request.url.path.count("/") == 2:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
        return site([])(request)

    async with make_fetcher(handler) as f:
        await asyncio.gather(
            ADAPTERS["internlist"](f, co("Siemens")), ADAPTERS["internlist"](f, co("IBM", 2))
        )
    assert peak == 1


async def test_an_unrecognized_list_page_is_an_error_not_an_empty_board():
    async with make_fetcher(lambda r: httpx.Response(200, text="<html>maintenance</html>")) as f:
        with pytest.raises(FetchError):
            await ADAPTERS["internlist"](f, co("Siemens"))


async def test_a_missing_list_never_counts_as_the_company_404ing():
    async with make_fetcher(lambda r: httpx.Response(404)) as f:
        with pytest.raises(FetchError) as exc:
            await ADAPTERS["internlist"](f, co("Siemens"))
    assert exc.value.status is None


async def test_lists_with_no_rows_at_all_are_an_error():
    # A layout change could keep the markers but lose the rows; that must not close every job.
    async with make_fetcher(lambda r: httpx.Response(200, text=list_page([]))) as f:
        with pytest.raises(FetchError):
            await ADAPTERS["internlist"](f, co("Siemens"))


def test_internlist_remembers_opened_pages():
    from scraper.adapters.base import STATEFUL_ATS

    assert "internlist" in STATEFUL_ATS
