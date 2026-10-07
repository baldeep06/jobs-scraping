from scraper.dedupe import ids_hash
from scraper.http import FetchError
from scraper.models import Company, FetchResult, RawJob
from scraper.pipeline import dominant_country, poll, process

ACME = Company(id=1, name="Acme", ats="greenhouse", slug="acme")


def raw(id_, title="Software Engineer Intern", location="Toronto, ON"):
    return RawJob(
        source="greenhouse", source_job_id=id_, title=title, url=f"https://x/{id_}",
        location_raw=location,
    )  # fmt: skip


def test_process_filters_and_tracks_all_seen_ids():
    result = FetchResult(jobs=[raw("1"), raw("2", title="Account Executive")], invalid=1)
    out = process(ACME, result)
    assert out.ok and not out.unchanged
    assert [j.raw.source_job_id for j in out.jobs] == ["1"]
    assert out.seen_ids == {"1", "2"}
    assert out.ids_hash == ids_hash({"1", "2"})
    assert out.invalid == 1


def test_process_skips_enrichment_when_ids_unchanged():
    company = ACME.model_copy(update={"job_ids_hash": ids_hash({"1"})})
    out = process(company, FetchResult(jobs=[raw("1")]))
    assert out.unchanged and out.jobs == [] and out.seen_ids == {"1"}


def test_dominant_country_used_for_bare_remote():
    out = process(
        ACME,
        FetchResult(
            jobs=[
                raw("1", title="Account Executive", location="Toronto, ON"),
                raw("2", title="Sales Lead", location="Vancouver, BC"),
                raw("3", location="Remote"),
            ]
        ),
    )
    assert out.jobs[0].location.country == "CA"
    assert dominant_country([raw("1", location="Seattle")]) == "US"
    assert dominant_country([raw("1", location="Remote")]) is None


async def test_poll_wraps_fetch_errors():
    async def boom(fetcher, company):
        raise FetchError("HTTP 404", 404)

    out = await poll(None, ACME, adapters={"greenhouse": boom})
    assert (out.ok, out.status, out.error) == (False, 404, "HTTP 404")


async def test_poll_wraps_unexpected_errors():
    async def bug(fetcher, company):
        raise KeyError("jobs")

    out = await poll(None, ACME, adapters={"greenhouse": bug})
    assert not out.ok and out.error.startswith("KeyError")


async def test_poll_success():
    async def ok(fetcher, company):
        return FetchResult(jobs=[raw("1")])

    out = await poll(None, ACME, adapters={"greenhouse": ok})
    assert out.ok and len(out.jobs) == 1
