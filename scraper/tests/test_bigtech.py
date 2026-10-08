import json
from datetime import UTC, datetime

import httpx
import pytest

from scraper.adapters import ADAPTERS, amazon, apple, google, meta, microsoft
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


# --- Microsoft ------------------------------------------------------------------------------


def ms_pos(i, name="Software Engineer Intern", locs=("Redmond, WA, US",), **kw):
    base = {
        "id": 1000 + i, "displayJobId": f"2000{i}", "name": name,
        "standardizedLocations": list(locs), "postedTs": 1791482125,
        "workLocationOption": "hybrid", "positionUrl": f"/careers/job/{1000 + i}",
    }  # fmt: skip
    return base | kw


def ms_handler(positions_by_search, details=None):
    seen = []

    def handler(request):
        if request.url.path.endswith("/search"):
            q = request.url.params
            seen.append((q["query"], q["location"], q["start"]))
            items = positions_by_search.get((q["query"], q["location"]), [])
            start = int(q["start"])
            body = {"positions": items[start : start + 10], "count": len(items)}
            return httpx.Response(200, json={"data": body})
        pid = request.url.params["position_id"]
        if details is None or pid not in details:
            return httpx.Response(404)
        return httpx.Response(200, json={"data": details[pid]})

    handler.seen = seen
    return handler


async def test_microsoft_fetch_searches_each_country_and_reads_details():
    detail = {
        "jobDescription": "<p>Build.</p><p>Pay: $50 per hour.</p>",
        "publicUrl": "https://apply.careers.microsoft.com/careers/job/1001",
        "efcustomTextEmploymentType": ["Internship"],
    }
    h = ms_handler(
        {
            ("intern", "United States"): [ms_pos(1), ms_pos(2, "Account Executive")],
            ("co-op", "Canada"): [ms_pos(3, "Software Engineer Co-op", locs=("Toronto, ON, CA",))],
        },
        details={"1001": detail, "1003": {"jobDescription": "<p>Co-op.</p>"}},
    )
    async with make_fetcher(h) as f:
        result = await ADAPTERS["microsoft"](f, co("microsoft"))
    assert {(q, loc) for q, loc, _ in h.seen} == {
        (q, loc) for q in ("intern", "co-op") for loc in ("United States", "Canada")
    }
    assert [j.source_job_id for j in result.jobs] == ["20001", "20002", "20003"]
    job = result.jobs[0]
    assert job.url == "https://apply.careers.microsoft.com/careers/job/1001"
    assert job.location_raw == "Redmond, WA, US" and job.work_mode_hint == "hybrid"
    assert job.employment_type_hint == "Internship"
    assert "Pay: $50 per hour." in job.description_text
    assert job.source_posted_at == datetime.fromtimestamp(1791482125, UTC)


async def test_microsoft_failed_detail_is_pending_not_gone():
    h = ms_handler({("intern", "United States"): [ms_pos(1)]}, details={})
    async with make_fetcher(h) as f:
        result = await microsoft.fetch(f, co("microsoft"))
    assert result.jobs == [] and result.pending_ids == {"20001"}


async def test_microsoft_pages_by_ten():
    h = ms_handler({("intern", "United States"): [ms_pos(i, "Sales Rep") for i in range(25)]})
    async with make_fetcher(h) as f:
        result = await microsoft.fetch(f, co("microsoft"))
    starts = [s for q, loc, s in h.seen if (q, loc) == ("intern", "United States")]
    assert starts == ["0", "10", "20"] and len(result.jobs) == 25


async def test_microsoft_zero_count_confirmed_empty_and_bad_payload_raises():
    async with make_fetcher(ms_handler({})) as f:
        assert (await microsoft.fetch(f, co("microsoft"))).confirmed_empty
    async with make_fetcher(lambda r: httpx.Response(200, json={"status": 200})) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await microsoft.fetch(f, co("microsoft"))


# --- Apple ----------------------------------------------------------------------------------

US_LOC = {"city": "Cupertino", "stateProvince": "California", "countryName": "United States"}
CA_LOC = {"city": "Toronto", "stateProvince": "Ontario", "countryName": "Canada"}


def apple_res(i, title="Software Engineering Intern", **kw):
    base = {
        "positionId": f"1000{i}", "postingTitle": title,
        "transformedPostingTitle": title.lower().replace(" ", "-"),
        "jobSummary": "Build things. Pay: $48 per hour.", "locations": [US_LOC],
        "postDateInGMT": "2026-10-08T19:37:18.420Z",
    }  # fmt: skip
    return base | kw


def apple_handler(results_by_query, token="tok123"):
    seen = {"tokens": [], "bodies": []}

    def handler(request):
        if request.url.path.endswith("/CSRFToken"):
            headers = {"x-apple-csrf-token": token} if token else {}
            return httpx.Response(200, content=b"", headers=headers)
        seen["tokens"].append(request.headers.get("x-apple-csrf-token"))
        body = json.loads(request.content)
        seen["bodies"].append(body)
        rows = results_by_query.get(body["query"], [])
        page = body["page"]
        res = {"searchResults": rows[(page - 1) * 20 : page * 20], "totalRecords": len(rows)}
        return httpx.Response(200, json={"res": res})

    handler.seen = seen
    return handler


async def test_apple_fetch_sends_csrf_and_maps_fields():
    h = apple_handler(
        {
            "internships": [apple_res(1)],
            "co-op": [apple_res(2, "Hardware Co-op", locations=[CA_LOC])],
        }
    )
    async with make_fetcher(h) as f:
        result = await ADAPTERS["apple"](f, co("apple"))
    assert set(h.seen["tokens"]) == {"tok123"}
    assert h.seen["bodies"][0]["filters"]["locations"] == ["postLocation-USA", "postLocation-CAN"]
    assert [j.source_job_id for j in result.jobs] == ["10001", "10002"]
    job = result.jobs[0]
    assert job.url == "https://jobs.apple.com/en-us/details/10001/software-engineering-intern"
    assert job.location_raw == "Cupertino, California, United States"
    assert job.country_hint == "US"
    assert job.source_posted_at == datetime(2026, 10, 8, 19, 37, 18, 420000, tzinfo=UTC)
    assert "Pay: $48 per hour." in job.description_text
    assert result.jobs[1].country_hint == "CA"


async def test_apple_pages_by_twenty():
    h = apple_handler({"internships": [apple_res(i, "Sales Rep") for i in range(45)]})
    async with make_fetcher(h) as f:
        result = await apple.fetch(f, co("apple"))
    pages = [b["page"] for b in h.seen["bodies"] if b["query"] == "internships"]
    assert pages == [1, 2, 3] and len(result.jobs) == 45


async def test_apple_missing_token_or_bad_payload_raises_and_zero_is_confirmed_empty():
    async with make_fetcher(apple_handler({}, token=None)) as f:
        with pytest.raises(FetchError, match="CSRF"):
            await apple.fetch(f, co("apple"))
    async with make_fetcher(apple_handler({})) as f:
        assert (await apple.fetch(f, co("apple"))).confirmed_empty

    def bad(request):
        if request.url.path.endswith("/CSRFToken"):
            return httpx.Response(200, content=b"", headers={"x-apple-csrf-token": "t"})
        return httpx.Response(200, json={"res": {}})

    async with make_fetcher(bad) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await apple.fetch(f, co("apple"))


# --- Google ---------------------------------------------------------------------------------


def g_job(i, title="Software Engineering Intern, Summer 2027", loc="Mountain View, CA, USA"):
    row = [None] * 21
    row[0], row[1] = f"9100{i}", title
    row[2] = f"https://www.google.com/about/careers/applications/signin?jobId=abc{i}&loc=US"
    row[3] = [None, "<ul><li>Write code.</li></ul>"]
    row[4] = [None, "<p>Pay: $52 per hour.</p>"]
    row[7] = "Google"
    row[9] = [[loc, ["addr"], "Mountain View", "94043", "CA", "US"]]
    row[10] = [None, "<p>About the team.</p>"]
    row[19] = [None, "<p>Python</p>"]
    return row


def g_page(jobs, total=None):
    blob = json.dumps([jobs, None, len(jobs) if total is None else total, 20])
    return (
        "<html><script>AF_initDataCallback({key: 'ds:1', hash: '2', data:"
        f"{blob}, sideChannel: {{}}}});</script></html>"
    )


def test_google_parse_page():
    jobs, total = google.parse_page(g_page([g_job(1)], total=25))
    assert total == 25 and jobs[0][1].startswith("Software Engineering Intern")


def test_google_parse_page_raises_when_the_page_shape_changes():
    empty = (
        "<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:{}, sideChannel: {}});</script>"
    )
    for html in ("<html>no data</html>", empty):
        with pytest.raises(FetchError, match="unexpected"):
            google.parse_page(html)


async def test_google_fetch_maps_fields_for_both_countries():
    def handler(request):
        p = request.url.params
        if (p["q"], p["location"]) == ("intern", "United States"):
            return httpx.Response(200, text=g_page([g_job(1), g_job(2, "Sales Manager")]))
        if (p["q"], p["location"]) == ("co-op", "Canada"):
            job = g_job(3, "Software Engineer Co-op", "Waterloo, ON, Canada")
            return httpx.Response(200, text=g_page([job]))
        return httpx.Response(200, text=g_page([], total=0))

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["google"](f, co("google"))
    assert [j.source_job_id for j in result.jobs] == ["91001", "91002", "91003"]
    job = result.jobs[0]
    assert job.url.startswith("https://www.google.com/about/careers/applications/signin?jobId=")
    assert job.location_raw == "Mountain View, CA, USA" and job.country_hint == "US"
    assert job.source_posted_at is None
    assert "Pay: $52 per hour." in job.description_text
    assert "Write code." in job.description_text
    assert result.jobs[2].country_hint == "CA" and not result.confirmed_empty


async def test_google_pages_until_total_and_zero_is_confirmed_empty():
    pages = []

    def handler(request):
        p = request.url.params
        if (p["q"], p["location"]) != ("intern", "United States"):
            return httpx.Response(200, text=g_page([], total=0))
        n = int(p["page"])
        pages.append(n)
        jobs = [g_job(n * 100 + i, "Sales Rep") for i in range(20)]
        return httpx.Response(200, text=g_page(jobs, total=45))

    async with make_fetcher(handler) as f:
        result = await google.fetch(f, co("google"))
    assert pages == [1, 2, 3] and len(result.jobs) == 60

    async with make_fetcher(lambda r: httpx.Response(200, text=g_page([], total=0))) as f:
        assert (await google.fetch(f, co("google"))).confirmed_empty


# --- Meta (sitemap + one JSON-LD page per posting) -------------------------------------------


def meta_sitemap(ids):
    urls = "".join(
        f"<url><loc>https://www.metacareers.com/profile/job_details/{i}/</loc></url>" for i in ids
    )
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'


def meta_page(title, countries=("US",), employment="INTERN", posted="2026-10-01T10:00:00-07:00"):
    places = [
        {
            "@type": "Place",
            "name": f"City{n}, ST",
            "address": {"@type": "PostalAddress", "addressCountry": c},
        }
        for n, c in enumerate(countries)
    ]
    ld = {
        "@context": "https://schema.org", "@type": "JobPosting", "title": title,
        "description": "Build <b>things</b>.", "responsibilities": "Ship it.",
        "qualifications": "Pay: $60 per hour.", "datePosted": posted,
        "employmentType": employment, "jobLocation": places,
    }  # fmt: skip
    return f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head></html>'


def meta_handler(ids, pages, fail=()):
    fetched = []

    def handler(request):
        if request.url.path.endswith("sitemap.xml"):
            return httpx.Response(200, text=meta_sitemap(ids))
        job_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        fetched.append(job_id)
        if job_id in fail:
            return httpx.Response(500)
        return httpx.Response(200, text=pages[job_id])

    handler.fetched = fetched
    return handler


def meta_company(known=(), checked=()):
    return Company(
        id=1, name="Meta", ats="meta", slug="meta", known_ids=set(known), checked_ids=set(checked)
    )


async def test_meta_classifies_pages_and_maps_fields():
    h = meta_handler(
        ["1", "2", "3", "4"],
        {
            "1": meta_page("Software Engineer Intern, ML", ("US", "CA")),
            "2": meta_page("Staff Software Engineer", ("US",), employment="FULL_TIME"),
            "3": meta_page("Software Engineer Intern", ("GB",)),
            "4": meta_page("Research Scientist Intern", ("CA",)),
        },
    )
    async with make_fetcher(h) as f:
        result = await ADAPTERS["meta"](f, meta_company())
    assert sorted(j.source_job_id for j in result.jobs) == ["1", "4"]
    assert result.rejected_ids == {"2", "3"}  # senior role; interns outside US/CA
    job = next(j for j in result.jobs if j.source_job_id == "1")
    assert job.url == "https://www.metacareers.com/profile/job_details/1/"
    assert job.location_raw == "City0, ST, US | City1, ST, CA"
    assert job.source_posted_at == datetime(2026, 10, 1, 17, 0, tzinfo=UTC)
    assert "Pay: $60 per hour." in job.description_text and "Build things." in job.description_text


async def test_meta_only_opens_unknown_ids_and_caps_each_poll(monkeypatch):
    monkeypatch.setattr(meta, "MAX_NEW_PAGES", 2)
    pages = {str(i): meta_page("Account Executive", employment="FULL_TIME") for i in range(1, 8)}
    h = meta_handler(list(pages), pages)
    async with make_fetcher(h) as f:
        result = await meta.fetch(f, meta_company(known={"1"}, checked={"2", "3"}))
    assert h.fetched == ["4", "5"]  # 1-3 already known; at most 2 new pages per poll
    assert result.rejected_ids == {"4", "5"}


async def test_meta_known_interns_still_listed_are_pending_and_gone_ones_are_not():
    h = meta_handler(["1", "2"], {})
    async with make_fetcher(h) as f:
        result = await meta.fetch(f, meta_company(known={"1", "9"}, checked={"2", "8"}))
    assert h.fetched == []
    assert result.pending_ids == {"1"}  # 9 left the sitemap: it must count as missing
    assert result.forgotten_ids == {"8"}  # a rejected id that left the sitemap is forgotten
    assert result.jobs == []
    # the sitemap parsed, so an empty read really means "nothing new"; known interns that left
    # the sitemap must be allowed to close
    assert result.confirmed_empty


async def test_meta_failed_page_is_retried_next_poll_not_remembered():
    pages = {i: meta_page("Software Engineer Intern") for i in ("1", "2", "3")}
    h = meta_handler(["1", "2", "3"], pages, fail={"1"})
    async with make_fetcher(h) as f:
        result = await meta.fetch(f, meta_company())
    assert sorted(j.source_job_id for j in result.jobs) == ["2", "3"]
    assert "1" not in result.rejected_ids and "1" not in result.pending_ids  # retried later


async def test_meta_empty_or_garbled_sitemap_raises():
    for body in (meta_sitemap([]), "<html>blocked</html>"):
        async with make_fetcher(lambda r, b=body: httpx.Response(200, text=b)) as f:
            with pytest.raises(FetchError, match="unexpected"):
                await meta.fetch(f, meta_company())


async def test_meta_remembers_gone_pages_and_pages_without_job_data():
    h = meta_handler(
        ["1", "2", "3"], {"1": meta_page("Software Engineer Intern"), "3": "<html>gone</html>"}
    )
    orig = h

    def handler(request):
        if request.url.path.rstrip("/").endswith("/2"):
            orig.fetched.append("2")
            return httpx.Response(404)
        return orig(request)

    async with make_fetcher(handler) as f:
        result = await meta.fetch(f, meta_company())
    assert [j.source_job_id for j in result.jobs] == ["1"]
    assert result.rejected_ids == {"2", "3"}  # a 404 and an isolated page with no JSON-LD


async def test_meta_pages_without_job_data_en_masse_mean_we_are_blocked():
    ids = [str(i) for i in range(1, 9)]
    h = meta_handler(ids, {i: "<html>please log in</html>" for i in ids})
    async with make_fetcher(h) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await meta.fetch(f, meta_company())


async def test_meta_does_not_remember_pages_when_the_country_format_changes():
    ids = [str(i) for i in range(1, 9)]
    pages = {i: meta_page("Software Engineer Intern", ("United States",)) for i in ids}
    async with make_fetcher(meta_handler(ids, pages)) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await meta.fetch(f, meta_company())


async def test_meta_invalid_record_is_remembered_not_counted_as_invalid():
    page = meta_page("Software Engineer Intern").replace(
        '"title": "Software Engineer Intern"', '"title": "  "'
    )
    h = meta_handler(["1"], {"1": page})
    async with make_fetcher(h) as f:
        result = await meta.fetch(f, meta_company())
    assert result.jobs == [] and result.invalid == 0 and result.rejected_ids == {"1"}


async def test_meta_stops_after_a_failing_batch_instead_of_hammering_the_site(monkeypatch):
    monkeypatch.setattr(meta, "BATCH", 4)
    ids = [str(i) for i in range(1, 21)]
    pages = {i: meta_page("Software Engineer Intern") for i in ids[:4]}
    ok = meta_handler(ids, pages, fail=set(ids[4:]))
    async with make_fetcher(ok) as f:
        result = await meta.fetch(f, meta_company())
    assert len(result.jobs) == 4  # progress from the good batch is kept
    assert set(ok.fetched) <= set(ids[:8])  # the failing batch ended the poll; no later batches
    assert result.rejected_ids == set()


async def test_meta_raises_when_nothing_loads_at_all():
    ids = ["1", "2", "3"]
    h = meta_handler(ids, {}, fail=set(ids))
    async with make_fetcher(h) as f:
        with pytest.raises(FetchError, match="not serving"):
            await meta.fetch(f, meta_company())


# --- caps and missing totals never close live jobs -------------------------------------------


async def test_amazon_missing_total_raises_and_a_capped_search_is_truncated(monkeypatch):
    async with make_fetcher(lambda r: httpx.Response(200, json={"jobs": []})) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await amazon.fetch(f, co("amazon"))
    monkeypatch.setattr(amazon, "MAX_PAGES", 1)

    def handler(request):
        if request.url.params["base_query"] != "intern":
            return httpx.Response(200, json={"hits": 0, "jobs": []})
        return httpx.Response(
            200, json={"hits": 500, "jobs": [amazon_job(i, "Sales") for i in range(100)]}
        )

    async with make_fetcher(handler) as f:
        result = await amazon.fetch(f, co("amazon"))
    assert result.truncated


async def test_microsoft_apple_google_flag_truncation_and_missing_totals(monkeypatch):
    # Microsoft
    monkeypatch.setattr(microsoft, "MAX_PAGES", 1)
    h = ms_handler({("intern", "United States"): [ms_pos(i, "Sales Rep") for i in range(25)]})
    async with make_fetcher(h) as f:
        assert (await microsoft.fetch(f, co("microsoft"))).truncated
    async with make_fetcher(lambda r: httpx.Response(200, json={"data": {"positions": []}})) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await microsoft.fetch(f, co("microsoft"))
    # Apple
    monkeypatch.setattr(apple, "MAX_PAGES", 1)
    h = apple_handler({"internships": [apple_res(i, "Sales Rep") for i in range(45)]})
    async with make_fetcher(h) as f:
        assert (await apple.fetch(f, co("apple"))).truncated

    def no_total(request):
        if request.url.path.endswith("/CSRFToken"):
            return httpx.Response(200, content=b"", headers={"x-apple-csrf-token": "t"})
        return httpx.Response(200, json={"res": {"searchResults": []}})

    async with make_fetcher(no_total) as f:
        with pytest.raises(FetchError, match="unexpected"):
            await apple.fetch(f, co("apple"))
    # Google
    monkeypatch.setattr(google, "MAX_PAGES", 1)

    def g(request):
        p = request.url.params
        if (p["q"], p["location"]) != ("intern", "United States"):
            return httpx.Response(200, text=g_page([], total=0))
        return httpx.Response(
            200, text=g_page([g_job(i, "Sales Rep") for i in range(20)], total=45)
        )

    async with make_fetcher(g) as f:
        assert (await google.fetch(f, co("google"))).truncated
