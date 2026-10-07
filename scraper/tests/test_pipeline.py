from scraper import pipeline
from scraper.http import FetchError
from scraper.models import Company, FetchResult, RawJob
from scraper.pipeline import board_hash, dominant_country, poll, process

ACME = Company(id=1, name="Acme", ats="greenhouse", slug="acme")


def raw(id_, title="Software Engineer Intern", location="Toronto, ON"):
    return RawJob(
        source="greenhouse", source_job_id=id_, title=title, url=f"https://x/{id_}",
        location_raw=location,
    )  # fmt: skip


def test_process_filters_and_tracks_all_seen_ids():
    jobs = [raw(str(i), title="Account Executive") for i in range(2, 11)]
    result = FetchResult(jobs=[raw("1"), *jobs], invalid=1)
    out = process(ACME, result)
    assert out.ok and not out.unchanged
    assert [j.raw.source_job_id for j in out.jobs] == ["1"]
    assert out.seen_ids == {str(i) for i in range(1, 11)}
    assert out.ids_hash == board_hash(out.seen_ids)
    assert out.invalid == 1


def test_process_skips_enrichment_when_ids_unchanged():
    company = ACME.model_copy(update={"job_ids_hash": board_hash({"1"})})
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


def test_board_hash_changes_with_enrichment_version(monkeypatch):
    before = board_hash({"1"})
    monkeypatch.setattr(pipeline, "ENRICH_VERSION", pipeline.ENRICH_VERSION + 1)
    assert board_hash({"1"}) != before


def test_all_records_invalid_is_a_failed_poll():
    out = process(ACME, FetchResult(jobs=[], invalid=12))
    assert not out.ok and "12 of 12" in out.error


def test_many_invalid_records_is_a_failed_poll():
    out = process(ACME, FetchResult(jobs=[raw("1")], invalid=1))
    assert not out.ok


def test_few_invalid_records_still_ingests():
    jobs = [raw(str(i)) for i in range(10)]
    out = process(ACME, FetchResult(jobs=jobs, invalid=1))
    assert out.ok and out.invalid == 1
