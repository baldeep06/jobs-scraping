import httpx
import pytest

from scraper.adapters import ADAPTERS
from scraper.http import Fetcher, FetchError
from scraper.models import Company


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def co(ats, host="jobs.example.com", site="example.com"):
    return Company(id=1, name="Ex", ats=ats, slug="ex", workday_host=host, workday_site=site)


# --- Eightfold (pcsx) -------------------------------------------------------------------------


def pcsx_item(i, name="Software Engineer Intern", **kw):
    return {
        "id": 1000 + i, "displayJobId": f"R{i}", "name": name,
        "standardizedLocations": ["San Jose, CA, US"], "postedTs": 1790726400,
        "workLocationOption": "hybrid", "positionUrl": f"/careers/job/{1000 + i}",
    } | kw  # fmt: skip


async def test_eightfold_reads_each_country_and_scopes_ids_to_the_tenant():
    searched = []

    def handler(request):
        if request.url.path == "/api/pcsx/search":
            p = request.url.params
            searched.append((p["query"], p["location"], p["domain"]))
            items = [pcsx_item(1), pcsx_item(2, "Sales Manager")] if p["query"] == "intern" else []
            return httpx.Response(200, json={"data": {"count": len(items), "positions": items}})
        assert request.url.params["position_id"] == "1001"
        detail = {
            "jobDescription": "<p>Build things. Pay $50 per hour.</p>",
            "publicUrl": "https://x/1",
        }
        return httpx.Response(200, json={"data": detail})

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["eightfold"](f, co("eightfold"))
    assert {s[1] for s in searched} == {"United States", "Canada"}
    assert {s[2] for s in searched} == {"example.com"}
    ids = [j.source_job_id for j in result.jobs]
    assert "jobs.example.com:R1" in ids
    job = next(j for j in result.jobs if j.source_job_id.endswith("R1"))
    assert job.url == "https://x/1" and "Pay $50 per hour." in job.description_text
    assert job.location_raw == "San Jose, CA, US" and job.work_mode_hint == "hybrid"
    assert not result.confirmed_empty


async def test_eightfold_failed_detail_is_pending_and_zero_count_is_confirmed_empty():
    def failing(request):
        if request.url.path == "/api/pcsx/search":
            return httpx.Response(200, json={"data": {"count": 1, "positions": [pcsx_item(1)]}})
        return httpx.Response(500)

    async with make_fetcher(failing) as f:
        result = await ADAPTERS["eightfold"](f, co("eightfold"))
    assert result.pending_ids == {"jobs.example.com:R1"} and result.jobs == []

    def empty(request):
        return httpx.Response(200, json={"data": {"count": 0, "positions": []}})

    async with make_fetcher(empty) as f:
        assert (await ADAPTERS["eightfold"](f, co("eightfold"))).confirmed_empty


async def test_eightfold_bad_payload_and_missing_tenant_raise():
    def bad(request):
        return httpx.Response(200, json={"data": {"positions": []}})

    async with make_fetcher(bad) as f:
        with pytest.raises(FetchError):
            await ADAPTERS["eightfold"](f, co("eightfold"))
        with pytest.raises(FetchError, match="host"):
            await ADAPTERS["eightfold"](f, Company(id=1, name="x", ats="eightfold", slug="x"))


# --- Eightfold (v2) ---------------------------------------------------------------------------


def v2_item(i, name="Machine Learning Intern", **kw):
    return {
        "id": 2000 + i, "name": name, "display_job_id": f"JR{i}",
        "locations": ["Los Gatos,California,United States of America"],
        "t_create": 1787097600, "canonicalPositionUrl": f"https://jobs.example.com/careers/job/{2000 + i}",
    } | kw  # fmt: skip


async def test_eightfold_v2_lists_then_reads_detail_for_internships_only():
    def handler(request):
        if request.url.path == "/api/apply/v2/jobs":
            items = (
                [v2_item(1), v2_item(2, "Accountant")]
                if request.url.params["query"] == "intern"
                else []
            )
            return httpx.Response(200, json={"count": len(items), "positions": items})
        assert request.url.path == "/api/apply/v2/jobs/2001"
        return httpx.Response(200, json={"job_description": "<p>Train models.</p>"})

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["eightfold_v2"](f, co("eightfold_v2"))
    job = result.jobs[0]
    assert job.source_job_id == "jobs.example.com:JR1" and "Train models." in job.description_text
    assert job.location_raw == "Los Gatos,California,United States of America"
    assert job.source_posted_at is not None


async def test_eightfold_v2_rejects_unexpected_payloads():
    def bad(request):
        return httpx.Response(200, json={"positions": []})

    async with make_fetcher(bad) as f:
        with pytest.raises(FetchError):
            await ADAPTERS["eightfold_v2"](f, co("eightfold_v2"))


# --- Oracle HCM -------------------------------------------------------------------------------


def oracle_req(i, title="Design Verification Engineering Intern", **kw):
    return {
        "Id": str(3000 + i), "Title": title, "PostedDate": "2026-09-02",
        "PrimaryLocation": "Dallas, TX, United States", "PrimaryLocationCountry": "US",
        "secondaryLocations": [{"Name": "Austin, TX, United States"}],
    } | kw  # fmt: skip


async def test_oracle_hcm_lists_by_keyword_and_reads_detail():
    queries = []

    def handler(request):
        path = request.url.path
        if path.endswith("recruitingCEJobRequisitions"):
            finder = request.url.params["finder"]
            queries.append(finder)
            if "keyword=intern" in finder:
                rows = [oracle_req(1), oracle_req(2, "Recruiter")]
                return httpx.Response(
                    200, json={"items": [{"TotalJobsCount": 2, "requisitionList": rows}]}
                )
            return httpx.Response(
                200, json={"items": [{"TotalJobsCount": 0, "requisitionList": []}]}
            )
        assert 'Id="3001"' in request.url.params["finder"]
        d = {
            "ExternalDescriptionStr": "<p>Verify chips.</p>",
            "ExternalQualificationsStr": "<p>Pursuing MS</p>",
        }
        return httpx.Response(200, json={"items": [d]})

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["oraclehcm"](f, co("oraclehcm", "h.fa.us2.oraclecloud.com", "CX_1"))
    assert any("siteNumber=CX_1" in q and "keyword=co-op" in q for q in queries)
    job = next(j for j in result.jobs if j.source_job_id.endswith(":3001"))
    assert job.source_job_id == "h.fa.us2.oraclecloud.com:3001"
    assert (
        job.url
        == "https://h.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/3001"
    )
    assert "Verify chips." in job.description_text and "Pursuing MS" in job.description_text
    assert job.location_raw == "Dallas, TX, United States | Austin, TX, United States"
    assert job.country_hint == "US" and job.source_posted_at.year == 2026


async def test_oracle_hcm_failed_detail_pending_truncation_and_bad_payload():
    def failing(request):
        if request.url.path.endswith("recruitingCEJobRequisitions"):
            row = {"TotalJobsCount": 5, "requisitionList": [oracle_req(1)]}
            return (
                httpx.Response(200, json={"items": [row]})
                if request.url.params["finder"].count("offset=0")
                else httpx.Response(
                    200, json={"items": [{"TotalJobsCount": 5, "requisitionList": []}]}
                )
            )
        return httpx.Response(500)

    async with make_fetcher(failing) as f:
        result = await ADAPTERS["oraclehcm"](f, co("oraclehcm", "h.example.com", "CX"))
    assert result.pending_ids == {"h.example.com:3001"} and result.truncated

    def bad(request):
        return httpx.Response(200, json={"items": [{"requisitionList": []}]})

    async with make_fetcher(bad) as f:
        with pytest.raises(FetchError):
            await ADAPTERS["oraclehcm"](f, co("oraclehcm", "h.example.com", "CX"))


# --- iCIMS ------------------------------------------------------------------------------------

ICIMS_HOST = "careers-ex.icims.com"


def icims_list(rows, pages=1):
    body = "".join(
        f'<div class="iCIMS_JobListingRow"><a href="https://{ICIMS_HOST}/jobs/{i}/slug/job?in_iframe=1">'
        f'<span class="sr-only field-label">Job Title</span><h3>{title}</h3></a></div>'
        for i, title in rows
    )
    return f'<html><body><div class="iCIMS_JobsTable">{body}</div><span>Page 1 of {pages}</span></body></html>'


def icims_page(title="Cybersecurity Intern", country="US", **kw):
    import json

    posting = {
        "@type": "JobPosting", "title": title, "description": "<p>Protect things.</p>",
        "datePosted": "2026-10-07T04:00:00.000Z",
        "jobLocation": [{"address": {
            "addressLocality": "Downers Grove", "addressRegion": "IL", "addressCountry": country}}],
    } | kw  # fmt: skip
    return f'<html><script type="application/ld+json">{json.dumps(posting)}</script></html>'


async def test_icims_lists_each_query_and_reads_internship_pages():
    queries = []

    def handler(request):
        if request.url.path == "/jobs/search":
            queries.append((request.url.params["searchKeyword"], request.url.params.get("pr")))
            rows = [(5131, "Cybersecurity Intern"), (5132, "Accountant")]
            return httpx.Response(200, text=icims_list(rows if "intern" in queries[-1][0] else []))
        assert request.url.path == "/jobs/5131/slug/job"
        return httpx.Response(200, text=icims_page())

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["icims"](f, co("icims", ICIMS_HOST, "-"))
    assert {q[0] for q in queries} == {"intern", "co-op"}
    job = next(j for j in result.jobs if j.source_job_id.endswith(":5131"))
    assert job.source_job_id == f"{ICIMS_HOST}:5131" and job.title == "Cybersecurity Intern"
    assert job.url == f"https://{ICIMS_HOST}/jobs/5131/slug/job"
    assert job.location_raw == "Downers Grove, IL, US" and "Protect things." in job.description_text
    assert job.source_posted_at.year == 2026 and not result.confirmed_empty


async def test_icims_follows_pages_failed_detail_is_pending_and_empty_is_confirmed():
    seen_pages = []

    def paged(request):
        if request.url.path == "/jobs/search":
            page = int(request.url.params.get("pr", "0"))
            seen_pages.append(page)
            rows = [(100 + page, "Software Engineer Intern")]
            return httpx.Response(200, text=icims_list(rows, pages=2))
        return httpx.Response(500)

    async with make_fetcher(paged) as f:
        result = await ADAPTERS["icims"](f, co("icims", ICIMS_HOST, "-"))
    assert {0, 1} <= set(seen_pages)
    assert result.pending_ids == {f"{ICIMS_HOST}:100", f"{ICIMS_HOST}:101"} and not result.jobs

    def empty(request):
        return httpx.Response(200, text=icims_list([]))

    async with make_fetcher(empty) as f:
        assert (await ADAPTERS["icims"](f, co("icims", ICIMS_HOST, "-"))).confirmed_empty


async def test_icims_unrecognised_page_raises_instead_of_looking_empty():
    def handler(request):
        return httpx.Response(200, text="<html>Please enable JavaScript</html>")

    async with make_fetcher(handler) as f:
        with pytest.raises(FetchError, match="iCIMS"):
            await ADAPTERS["icims"](f, co("icims", ICIMS_HOST, "-"))


# --- Lever (EU) -------------------------------------------------------------------------------


async def test_lever_eu_reads_the_eu_api():
    def handler(request):
        assert request.url.host == "api.eu.lever.co" and request.url.path == "/v0/postings/cirrus"
        item = {
            "id": "abc",
            "text": "Firmware Intern",
            "hostedUrl": "https://jobs.eu.lever.co/cirrus/abc",
        }
        return httpx.Response(200, json=[item])

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["lever_eu"](
            f, Company(id=1, name="Cirrus", ats="lever_eu", slug="cirrus")
        )
    assert result.jobs[0].source == "lever" and result.jobs[0].source_job_id == "abc"
