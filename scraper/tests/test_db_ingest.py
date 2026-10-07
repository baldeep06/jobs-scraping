from datetime import UTC, datetime, timedelta

from scraper import db
from scraper.dedupe import ids_hash
from scraper.enrich import enrich
from scraper.models import CompanyOutcome, RawJob

T0 = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def company(conn, slug="acme", ats="greenhouse"):
    db.upsert_companies(conn, [{"name": slug.title(), "ats": ats, "slug": slug, "hot": True}])
    return db.get_companies(conn, ats=[ats], slug=slug)[0]


def raw(id_, title="Software Engineer Intern", location="Toronto, ON", posted=None):
    return RawJob(
        source="greenhouse", source_job_id=id_, title=title, url=f"https://x/{id_}",
        location_raw=location, source_posted_at=posted,
    )  # fmt: skip


def outcome(c, raws, unchanged=False):
    seen = {r.source_job_id for r in raws}
    jobs = [] if unchanged else [e for r in raws if (e := enrich(r, c.id))]
    return CompanyOutcome(
        company=c, ok=True, jobs=jobs, seen_ids=seen, ids_hash=ids_hash(seen), unchanged=unchanged
    )


def jobs(conn):
    return conn.execute("select * from jobs order by first_seen_at, title").fetchall()


def test_upsert_and_get_companies(conn):
    c = company(conn)
    assert (c.name, c.ats, c.slug, c.job_ids_hash) == ("Acme", "greenhouse", "acme", None)
    tier = conn.execute("select tier from companies").fetchone()["tier"]
    assert tier == "hot"
    assert db.get_companies(conn, ats=["greenhouse"], tier="warm") == []


def test_new_job_inserted_as_fresh_with_source(conn):
    c = company(conn)
    stats = db.ingest(conn, outcome(c, [raw("1")]), T0)
    assert (stats.new, stats.seen, stats.closed) == (1, 1, 0)
    [j] = jobs(conn)
    assert (j["freshness"], j["status"], j["country"], j["first_seen_at"]) == (
        "fresh", "open", "CA", T0,
    )  # fmt: skip
    src = conn.execute("select * from job_sources").fetchone()
    assert (src["source_job_id"], src["job_id"]) == ("1", j["id"])
    row = conn.execute("select * from companies").fetchone()
    assert row["job_ids_hash"] == ids_hash({"1"}) and row["last_success_at"] == T0


def test_second_poll_touches_existing(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    stats = db.ingest(conn, outcome(c, [raw("1")]), T0 + timedelta(minutes=5))
    [j] = jobs(conn)
    assert stats.new == 0
    assert (j["first_seen_at"], j["last_seen_at"]) == (T0, T0 + timedelta(minutes=5))


def test_missing_twice_closes_then_reopens(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=5))
    assert jobs(conn)[0]["status"] == "open" and jobs(conn)[0]["miss_count"] == 1
    stats = db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=10))
    assert stats.closed == 1 and jobs(conn)[0]["status"] == "closed"
    db.ingest(conn, outcome(c, [raw("1")]), T0 + timedelta(days=1))
    [j] = jobs(conn)
    assert (j["status"], j["freshness"], j["closed_at"], j["miss_count"]) == (
        "open", "reopened", None, 0,
    )  # fmt: skip


def test_same_role_twice_is_one_job_open_while_any_id_listed(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1"), raw("2")]), T0)
    assert len(jobs(conn)) == 1
    assert conn.execute("select count(*) as n from job_sources").fetchone()["n"] == 2
    for minutes in (5, 10, 15):
        db.ingest(conn, outcome(c, [raw("2")]), T0 + timedelta(minutes=minutes))
    [j] = jobs(conn)
    assert (j["status"], j["miss_count"]) == ("open", 0)


def test_repost_after_close_links_to_original(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=5))
    db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=10))
    db.ingest(conn, outcome(c, [raw("9")]), T0 + timedelta(days=30))
    old, new = jobs(conn)
    assert (new["freshness"], new["repost_of"], new["repost_count"]) == ("repost", old["id"], 1)


def test_posted_date_bump_marks_refreshed(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1", posted=T0)]), T0)
    later = T0 + timedelta(days=20)
    db.ingest(conn, outcome(c, [raw("1", posted=later)]), later)
    [j] = jobs(conn)
    assert (j["freshness"], j["source_posted_at"]) == ("refreshed", later)


def test_unchanged_hash_touches_only_seen_jobs(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1"), raw("2", title="Data Science Intern")]), T0)
    db.ingest(conn, outcome(c, [raw("1")]), T0 + timedelta(minutes=5))
    db.ingest(conn, outcome(c, [raw("1")], unchanged=True), T0 + timedelta(minutes=10))
    by_title = {j["title"]: j for j in jobs(conn)}
    assert by_title["Software Engineer Intern"]["last_seen_at"] == T0 + timedelta(minutes=10)
    assert by_title["Data Science Intern"]["status"] == "closed"


def test_failed_poll_closes_nothing_and_404s_deactivate(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    failed = CompanyOutcome(company=c, ok=False, error="HTTP 404", status=404)
    for i in range(5):
        db.ingest(conn, failed, T0 + timedelta(minutes=5 * (i + 1)))
    [j] = jobs(conn)
    assert (j["status"], j["miss_count"]) == ("open", 0)
    row = conn.execute("select * from companies").fetchone()
    assert (row["fail_count"], row["consecutive_404s"], row["tier"]) == (5, 5, "inactive")
    assert db.get_companies(conn, ats=["greenhouse"]) == []


def test_timeout_does_not_count_as_404(conn):
    c = company(conn)
    db.ingest(conn, CompanyOutcome(company=c, ok=False, error="ConnectTimeout"), T0)
    row = conn.execute("select * from companies").fetchone()
    assert (row["fail_count"], row["consecutive_404s"], row["tier"]) == (1, 0, "hot")


def test_record_run(conn):
    db.record_run(
        conn, workflow="scrape-hot", source="ats", started_at=T0, finished_at=T0,
        companies_polled=2, jobs_seen=3, jobs_new=1, jobs_closed=0, errors=1,
        error_samples=[{"company": "acme", "error": "HTTP 500"}],
    )  # fmt: skip
    row = conn.execute("select * from scrape_runs").fetchone()
    assert (row["companies_polled"], row["error_samples"][0]["error"]) == (2, "HTTP 500")
