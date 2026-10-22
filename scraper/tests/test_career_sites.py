import json

import httpx
import pytest

from scraper.adapters import ADAPTERS, avature, deshaw, pinpoint, shopify, successfactors
from scraper.http import Fetcher, FetchError
from scraper.models import Company


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def co(ats, slug="ex", host=None):
    return Company(id=1, name="Ex", ats=ats, slug=slug, workday_host=host, workday_site="-")


# --- Pinpoint ---------------------------------------------------------------------------------


def pinpoint_item(i, title="Software Engineering Intern (Summer 2027)", **kw):
    return {
        "id": str(i), "title": title, "url": f"https://acme.pinpointhq.com/en/postings/{i}",
        "description": "<p>Build rockets.</p>", "key_responsibilities": "<ul><li>Code</li></ul>",
        "skills_knowledge_expertise": "", "employment_type_text": "Internship",
        "workplace_type": "onsite",
        "location": {"name": "Redondo Beach ", "city": "Redondo Beach", "province": "California"},
        "compensation_visible": True, "compensation_minimum": 30, "compensation_maximum": 40,
        "compensation_currency": "USD", "compensation_frequency": "hour",
    } | kw  # fmt: skip


async def test_pinpoint_maps_fields_pay_and_location():
    def handler(request):
        assert str(request.url) == "https://acme.pinpointhq.com/postings.json"
        return httpx.Response(200, json={"data": [pinpoint_item(1)]})

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["pinpoint"](f, co("pinpoint", "acme"))
    job = result.jobs[0]
    assert job.source_job_id == "1" and job.location_raw == "Redondo Beach, California"
    assert "Build rockets." in job.description_text and "Code" in job.description_text
    assert job.pay_structured.period == "hour" and job.pay_structured.max == 40
    assert job.work_mode_hint == "onsite" and job.employment_type_hint == "Internship"


def test_pinpoint_keeps_a_located_name_and_hides_unshown_pay():
    item = pinpoint_item(2, compensation_visible=False)
    item["location"] = {"name": "Chicago, IL", "city": "Chicago", "province": "Illinois"}
    job = pinpoint.parse({"data": [item]}).jobs[0]
    assert job.location_raw == "Chicago, IL" and job.pay_structured is None


def test_pinpoint_bad_payload_raises():
    with pytest.raises(FetchError):
        pinpoint.parse({"postings": []})


# --- Avature ----------------------------------------------------------------------------------

BASE = "jobs.example.com/careers"


def bloomberg_page(rows, next_offset=None):
    items = "".join(
        f'<article class="article article--result"><h3><a class="link" '
        f'href="https://jobs.example.com/careers/JobDetail/{t.replace(" ", "-")}/{i}">{t}</a>'
        f'</h3><span class="list-item-location">{loc}</span></article>'
        for i, t, loc in rows
    )
    nxt = (
        f'<a class="paginationNextLink" href="https://jobs.example.com/careers/SearchJobs/'
        f'?jobRecordsPerPage=12&amp;jobOffset={next_offset}">Next</a>'
        if next_offset is not None
        else ""
    )
    return f"<html><body>{nxt}{items}</body></html>"


def detail_page(location="", posted="", body="Write code. Pay $45/hour."):
    fields = "".join(
        f'<div class="article__content__view__field"><div class="article__content__view__field__label">'
        f'{k}</div><div class="article__content__view__field__value">{v}</div></div>'
        for k, v in (("Location", location), ("Posting date", posted))
        if v
    )
    return f"<html><body><main>{fields}<p>{body}</p></main></body></html>"


async def test_avature_pages_reads_only_wanted_postings_and_takes_the_row_location():
    opened = []

    def handler(request):
        url = str(request.url)
        if "/SearchJobs/" in url:
            if request.url.params["search"] != "intern":
                return httpx.Response(200, text="<html><body>No results found</body></html>")
            if request.url.params["jobOffset"] == "0":
                rows = [(1, "Software Engineer Intern", "New York, NY, United States"),
                        (2, "Internal Auditor", "London, United Kingdom")]  # fmt: skip
                return httpx.Response(200, text=bloomberg_page(rows, next_offset=12))
            rows = [(3, "Data Science Intern", "")]
            return httpx.Response(200, text=bloomberg_page(rows))
        opened.append(url)
        if url.endswith("/3"):
            return httpx.Response(200, text=detail_page("Toronto, ON", "21-Sep-2026"))
        return httpx.Response(200, text=detail_page("New York"))

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["avature"](f, co("avature", host=BASE))
    jobs = {j.source_job_id: j for j in result.jobs}
    assert set(jobs) == {"jobs.example.com:1", "jobs.example.com:2", "jobs.example.com:3"}
    assert len(opened) == 2 and not any(u.endswith("/2") for u in opened)
    assert jobs["jobs.example.com:1"].location_raw == "New York, NY, United States"
    assert jobs["jobs.example.com:3"].location_raw == "Toronto, ON"
    assert jobs["jobs.example.com:3"].source_posted_at.date().isoformat() == "2026-09-21"
    assert "Pay $45/hour." in jobs["jobs.example.com:1"].description_text
    assert not result.truncated and not result.confirmed_empty


def test_avature_list_reads_table_rows_and_epic_folders():
    table = (
        '<table><tr><th><a href="https://b.test/en_CA/careers/JobDetail/59935-STAGE/35506" '
        'title="Corporate Finance Internships"> Corporate Finance Internships </a></th>'
        "<td> Montreal, Quebec </td><td> Hybrid </td></tr></table>"
    )
    rows, following = avature.parse_list(table, 0)
    assert rows[0]["title"] == "Corporate Finance Internships"
    assert rows[0]["location"] == "Montreal, Quebec" and following is None

    epic = (
        '<ul><li class="jobResultItem"><h3><a href="https://e.test/Careers/FolderDetail/'
        'Verona-Wisconsin-United-States-Software-Developer-Intern-Summer-2027/30318">'
        'Software Developer Intern - Summer 2027</a></h3><p><a href="https://e.test/Careers/'
        'FolderDetail/Verona-Wisconsin-United-States-Software-Developer-Intern-Summer-2027/30318">'
        'Learn More</a></p></li></ul><a href="https://e.test/Careers/SearchJobs/intern?'
        'folderOffset=10">Next</a>'
    )
    rows, following = avature.parse_list(epic, 0)
    assert [r["title"] for r in rows] == ["Software Developer Intern - Summer 2027"]
    assert following == ("folderOffset", 10)
    assert (
        avature.slug_location(rows[0]["url"], rows[0]["title"]) == "Verona Wisconsin United States"
    )


def test_avature_page_without_rows_or_empty_message_raises():
    with pytest.raises(FetchError):
        avature.parse_list("<html><body>Something else entirely</body></html>", 0)


async def test_avature_failed_page_is_pending_and_missing_base_raises():
    def handler(request):
        if "/SearchJobs/" in str(request.url):
            if request.url.params["search"] != "intern":
                return httpx.Response(200, text="<html><body>No jobs found</body></html>")
            return httpx.Response(200, text=bloomberg_page([(1, "Software Engineer Intern", "")]))
        return httpx.Response(500)

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["avature"](f, co("avature", host=BASE))
        assert result.pending_ids == {"jobs.example.com:1"} and result.jobs == []
        with pytest.raises(FetchError, match="portal"):
            await ADAPTERS["avature"](f, co("avature"))


# --- SuccessFactors ---------------------------------------------------------------------------

SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://jobs.example.com/job/Austin-Student-Intern%2C-Software-Testing-TX-73301/111/</loc></url>
<url><loc>https://jobs.example.com/job/Toronto-Buyer-ON/222/</loc></url>
<url><loc>https://jobs.example.com/job/Mississauga-Intern%2C-Systems-Engineering-%28Winter-2027%29-ON-L5S-1W1/333/</loc></url>
<url><loc>https://jobs.example.com/job/Dorval-Intern%2C-Software-Developer-Qu%C3%A9b-H4S-1Y9/444/</loc></url>
</urlset>"""


def rmk_page(title, meta=True, span=""):
    tags = (
        '<meta itemprop="addressLocality" content="Austin"><meta itemprop="addressRegion" '
        'content="TX"><meta itemprop="addressCountry" content="US">'
        '<meta itemprop="datePosted" content="Tue Sep 29 00:00:00 UTC 2026">'
        if meta
        else ""
    )
    return (
        f'<html><head>{tags}</head><body><span itemprop="title">{title}</span>'
        f"<div><span>{span}</span></div>"
        '<span itemprop="description"><p>Test firmware. $30 per hour.</p></span></body></html>'
    )


async def test_successfactors_opens_only_internship_pages_and_finds_the_place():
    opened = []

    def handler(request):
        url = str(request.url)
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=SITEMAP)
        opened.append(request.url.path)
        if "/111/" in url:
            return httpx.Response(200, text=rmk_page("Student Intern, Software Testing"))
        if "/333/" in url:
            page = rmk_page("Intern, Systems Engineering (Winter 2027)", False,
                            "Mississauga, ON, CAN, L5S 1W1")  # fmt: skip
            return httpx.Response(200, text=page)
        return httpx.Response(200, text=rmk_page("Intern, Software Developer", False))

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["successfactors"](f, co("successfactors", host="jobs.example.com"))
    jobs = {j.source_job_id.split(":")[1]: j for j in result.jobs}
    assert set(jobs) == {"111", "333", "444"} and not any("/222/" in p for p in opened)
    assert jobs["111"].location_raw == "Austin, TX, US"
    assert jobs["111"].source_posted_at.date().isoformat() == "2026-09-29"
    assert "$30 per hour." in jobs["111"].description_text
    assert jobs["333"].location_raw == "Mississauga, ON, CAN, L5S 1W1"
    assert jobs["444"].location_raw == "Dorval, Québ"  # from the URL: city, then region
    assert jobs["111"].country_hint == "US" and jobs["333"].country_hint == "CA"


def test_successfactors_reads_a_printed_place_outside_ca_us_as_foreign():
    page = successfactors.parse_page(
        rmk_page("Intern, Engineering", False, "Colon, QUE, MEX, 76270"), "Colon-Intern-MEX"
    )
    assert page["location"] == "Colon, QUE, MEX, 76270" and page["country"] == "OTHER"


def test_successfactors_bad_sitemap_raises():
    with pytest.raises(FetchError):
        successfactors.parse_sitemap("<html>not a sitemap</html>")


# --- D. E. Shaw -------------------------------------------------------------------------------


def deshaw_page(internships, regular=()):
    props = {"props": {"pageProps": {"internships": internships, "regularJobs": list(regular)}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(props)}</script>'


def deshaw_job(i, title, active=True):
    return {
        "id": i, "displayName": title, "office": [{"name": "New York", "abbreviation": "NYC"}],
        "data": {
            "id": i, "displayName": title, "jobUrl": f"Some-Title-{i}", "activeOnJobsListing": active,
            "jobDescription": {"websiteDescription": "<p>Write C++.</p>",
                               "peopleWeAreLookingFor": ["Strong CS"]},
            "jobMetadata": {"workStatus": "Intern"},
        },
    }  # fmt: skip


def test_deshaw_reads_both_lists_and_skips_inactive_postings():
    page = deshaw_page(
        [deshaw_job(1, "Software Developer Intern (New York) – Summer 2027")],
        [deshaw_job(2, "Quant Analyst"), deshaw_job(3, "Old Job", active=False)],
    )
    jobs = {j.source_job_id: j for j in deshaw.parse(page).jobs}
    assert set(jobs) == {"1", "2"}
    job = jobs["1"]
    assert job.url == "https://www.deshaw.com/careers/some-title-1"
    assert job.location_raw == "New York" and job.employment_type_hint == "Intern"
    assert "Write C++." in job.description_text and "Strong CS" in job.description_text


def test_deshaw_page_without_job_lists_raises():
    with pytest.raises(FetchError):
        deshaw.parse("<html>maintenance</html>")


# --- Shopify ----------------------------------------------------------------------------------


def turbo(flat):
    """A page carrying `flat` the way React Router streams it."""
    chunk = json.dumps(json.dumps(flat) + "\n")
    return f"<script>window.__reactRouterContext.streamController.enqueue({chunk});</script>"


def search_flat(postings):
    """Encode {"loaderData": {"jobPostingsWithJobs": [{"jobPosting": p}, ...]}} as turbo-stream."""
    flat = [None]

    def add(v):
        flat.append(v)
        return len(flat) - 1

    def enc(v):
        if isinstance(v, dict):
            at = add(None)
            flat[at] = {f"_{add(k)}": enc(x) for k, x in v.items()}
            return at
        if isinstance(v, list):
            at = add(None)
            flat[at] = [enc(x) for x in v]
            return at
        return -5 if v is None else add(v)

    root = {"loaderData": {"jobPostingsWithJobs": [{"jobPosting": p} for p in postings]}}
    flat[0] = flat[enc(root)]
    return flat  # fmt: skip


def test_shopify_decodes_turbo_stream_with_shared_values():
    flat = [{"_1": 2, "_3": 2, "_4": -5}, "a", [5, 5], "b", "c", "shared"]
    assert shopify.decode_stream(turbo(flat)) == {
        "a": ["shared", "shared"],
        "b": ["shared", "shared"],
        "c": None,
    }


async def test_shopify_lists_postings_and_reads_only_internship_pages():
    postings = [
        {"id": "u1", "title": "Software Engineering Intern", "locationName": "Canada",
         "employmentType": "Intern", "workplaceType": "Remote", "publishedDate": "2026-10-20",
         "isListed": True},
        {"id": "u2", "title": "Account Executive, SMB", "locationName": "Americas",
         "employmentType": "FullTime", "isListed": True},
    ]  # fmt: skip
    opened = []

    def handler(request):
        if request.url.path == "/careers/search":
            assert not request.url.query  # robots.txt disallows /careers/search?*
            return httpx.Response(200, text=turbo(search_flat(postings)))
        opened.append(request.url.path)
        detail = search_flat([])
        detail.append({"_" + str(len(detail) + 1): len(detail) + 2})
        detail += ["descriptionPlain", "Ship code. Paid $40/hour."]
        detail[0] = detail[len(detail) - 3]
        return httpx.Response(200, text=turbo(detail))

    async with make_fetcher(handler) as f:
        result = await ADAPTERS["shopify"](f, co("shopify", "shopify"))
    assert opened == ["/careers/software-engineering-intern_u1"]
    [job] = result.jobs
    assert job.location_raw == "Canada" and job.work_mode_hint == "remote"
    assert job.description_text == "Ship code. Paid $40/hour."
    assert job.source_posted_at.date().isoformat() == "2026-10-20"


def test_shopify_page_without_route_data_raises():
    with pytest.raises(FetchError):
        shopify.parse_search("<html></html>")
