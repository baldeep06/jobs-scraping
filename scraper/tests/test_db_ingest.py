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


def other():
    """A non-intern posting, so the board isn't empty (empty boards never count as misses)."""
    return [raw("other", title="Account Executive")]


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
    stats = db.ingest(conn, outcome(c, [raw("1", posted=T0 - timedelta(hours=2))]), T0)
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
    db.ingest(conn, outcome(c, other()), T0 + timedelta(minutes=5))
    assert jobs(conn)[0]["status"] == "open" and jobs(conn)[0]["miss_count"] == 1
    stats = db.ingest(conn, outcome(c, other()), T0 + timedelta(minutes=10))
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
    db.ingest(conn, outcome(c, other()), T0 + timedelta(minutes=5))
    db.ingest(conn, outcome(c, other()), T0 + timedelta(minutes=10))
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


def test_failed_poll_closes_nothing_and_brief_404s_dont_deactivate(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    failed = CompanyOutcome(company=c, ok=False, error="HTTP 404", status=404)
    for i in range(5):
        db.ingest(conn, failed, T0 + timedelta(minutes=5 * (i + 1)))
    [j] = jobs(conn)
    assert (j["status"], j["miss_count"]) == ("open", 0)
    row = conn.execute("select * from companies").fetchone()
    assert (row["fail_count"], row["consecutive_404s"], row["tier"]) == (5, 5, "hot")


def test_404s_for_a_day_deactivate_and_close_jobs_until_reseeded(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    failed = CompanyOutcome(company=c, ok=False, error="HTTP 404", status=404)
    for hours in (1, 2, 3, 4, 26):
        db.ingest(conn, failed, T0 + timedelta(hours=hours))
    assert conn.execute("select tier from companies").fetchone()["tier"] == "inactive"
    assert jobs(conn)[0]["status"] == "closed"
    assert db.get_companies(conn, ats=["greenhouse"]) == []
    company(conn)  # re-seeding a hot company reactivates it
    row = conn.execute("select tier, consecutive_404s from companies").fetchone()
    assert (row["tier"], row["consecutive_404s"]) == ("hot", 0)


def test_success_resets_404_streak(conn):
    c = company(conn)
    failed = CompanyOutcome(company=c, ok=False, error="HTTP 404", status=404)
    for hours in (1, 2, 3, 4):
        db.ingest(conn, failed, T0 + timedelta(hours=hours))
    db.ingest(conn, outcome(c, [raw("1")]), T0 + timedelta(hours=5))
    db.ingest(conn, failed, T0 + timedelta(hours=30))
    row = conn.execute("select tier, consecutive_404s from companies").fetchone()
    assert (row["tier"], row["consecutive_404s"]) == ("hot", 1)


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


def test_empty_board_never_closes_jobs(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    for minutes in (5, 10, 15):
        db.ingest(conn, outcome(c, []), T0 + timedelta(minutes=minutes))
    [j] = jobs(conn)
    assert (j["status"], j["miss_count"]) == ("open", 0)


def test_poll_with_invalid_records_never_closes_jobs(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    for minutes in (5, 10):
        o = outcome(c, other())
        o.invalid = 1
        db.ingest(conn, o, T0 + timedelta(minutes=minutes))
    assert jobs(conn)[0]["status"] == "open"


def test_two_terms_posted_at_once_are_two_jobs(conn):
    c = company(conn)
    fall = raw("1", title="Software Engineer Intern (Fall 2026)")
    winter = raw("2", title="Software Engineer Intern (Winter 2027)")
    db.ingest(conn, outcome(c, [fall, winter]), T0)
    db.ingest(conn, outcome(c, [winter, fall]), T0 + timedelta(minutes=5))
    rows = jobs(conn)
    assert sorted(j["term"] for j in rows) == ["Fall 2026", "Winter 2027"]
    assert all(j["status"] == "open" for j in rows)
    terms_by_url = {j["best_url"]: j["term"] for j in rows}
    assert terms_by_url == {"https://x/1": "Fall 2026", "https://x/2": "Winter 2027"}


def test_job_that_stops_passing_the_filter_is_closed(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    db.ingest(conn, outcome(c, [raw("1", location="London, UK")]), T0 + timedelta(minutes=5))
    assert jobs(conn)[0]["status"] == "closed"


def test_workday_fields_round_trip(conn):
    db.upsert_companies(
        conn,
        [{"name": "Nvidia", "ats": "workday", "slug": "nvidia/Site", "hot": True,
          "workday_host": "nvidia.wd5.myworkdayjobs.com", "workday_site": "Site"}],
    )  # fmt: skip
    c = db.get_companies(conn, ats=["workday"])[0]
    assert (c.workday_host, c.workday_site) == ("nvidia.wd5.myworkdayjobs.com", "Site")


def _empty_outcome(c, confirmed):
    return CompanyOutcome(
        company=c, ok=True, seen_ids=set(), ids_hash=ids_hash(set()), confirmed_empty=confirmed
    )


def test_confirmed_empty_board_closes_after_two_polls(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")] + other()), T0)
    for i in (1, 2):
        c = db.get_companies(conn, ats=["greenhouse"], slug="acme")[0]
        db.ingest(conn, _empty_outcome(c, True), T0 + timedelta(minutes=5 * i))
    assert jobs(conn)[0]["status"] == "closed"


def test_unconfirmed_empty_board_never_closes(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")] + other()), T0)
    for i in (1, 2, 3):
        c = db.get_companies(conn, ats=["greenhouse"], slug="acme")[0]
        db.ingest(conn, _empty_outcome(c, False), T0 + timedelta(minutes=5 * i))
    assert jobs(conn)[0]["status"] == "open"


# --- reposts vs fresh vs already-open ----------------------------------------------------------

BODY = "Join the platform team and build reliable payment services in Python. " * 6


def rjob(id_, title, location="Toronto, ON", body="", posted=None):
    return RawJob(
        source="greenhouse", source_job_id=id_, title=title, url=f"https://x/{id_}",
        location_raw=location, description_text=body, source_posted_at=posted,
    )  # fmt: skip


def settle(conn, c, *raws, at=T0):
    """Ingest after the company's first poll, so nothing counts as baseline backlog."""
    conn.execute("update companies set last_success_at = %s where id = %s", (at, c.id))
    db.ingest(conn, outcome(c, list(raws) + other()), at)


def close_all(conn):
    conn.execute("update jobs set status = 'closed', closed_at = %s", (T0,))


def by_title(conn):
    return {r["title"]: r for r in jobs(conn)}


def test_first_poll_backlog_is_existing_not_fresh(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [rjob("1", "Software Engineer Intern")] + other()), T0)
    assert jobs(conn)[0]["freshness"] == "existing"


def test_first_poll_job_with_a_recent_date_is_still_fresh(conn):
    c = company(conn)
    posted = T0 - timedelta(hours=3)
    db.ingest(conn, outcome(c, [rjob("1", "Software Engineer Intern", posted=posted)]), T0)
    assert jobs(conn)[0]["freshness"] == "fresh"


def test_later_undated_job_is_fresh(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, other()), T0)
    c = db.get_companies(conn, ats=["greenhouse"], slug="acme")[0]
    db.ingest(conn, outcome(c, [rjob("2", "Software Engineer Intern")] + other()), T0)
    assert by_title(conn)["Software Engineer Intern"]["freshness"] == "fresh"


def test_old_dated_job_is_existing_even_after_the_first_poll(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern", posted=T0 - timedelta(days=60)))
    assert by_title(conn)["Software Engineer Intern"]["freshness"] == "existing"


def test_reworded_title_is_a_repost_of_the_closed_job(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern, Backend"))
    close_all(conn)
    settle(conn, c, rjob("2", "Backend Software Engineer Intern"), at=T0 + timedelta(days=10))
    new = by_title(conn)["Backend Software Engineer Intern"]
    old = by_title(conn)["Software Engineer Intern, Backend"]
    assert new["freshness"] == "repost" and new["repost_of"] == old["id"]


def test_same_title_in_another_city_is_a_new_opening_not_a_repost(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern", location="Santa Clara, CA"))
    close_all(conn)
    settle(conn, c, rjob("2", "Software Engineer Intern", location="Austin, TX"),
           at=T0 + timedelta(days=5))  # fmt: skip
    austin = [r for r in jobs(conn) if r["location_raw"] == "Austin, TX"][0]
    assert austin["freshness"] != "repost"


def test_same_title_and_description_in_another_city_is_a_repost(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern", location="Toronto, ON", body=BODY))
    close_all(conn)
    settle(conn, c, rjob("2", "Software Engineer Intern", location="Waterloo, ON", body=BODY),
           at=T0 + timedelta(days=5))  # fmt: skip
    waterloo = [r for r in jobs(conn) if r["location_raw"] == "Waterloo, ON"][0]
    assert waterloo["freshness"] == "repost"


def test_closed_job_in_another_country_is_not_a_repost(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern", location="New York, NY"))
    close_all(conn)
    settle(conn, c, rjob("2", "Software Engineer Intern", location="Toronto, ON"),
           at=T0 + timedelta(days=5))  # fmt: skip
    toronto = [r for r in jobs(conn) if r["location_raw"] == "Toronto, ON"][0]
    assert toronto["freshness"] != "repost"


def test_retitled_posting_sharing_only_a_template_description_is_not_a_repost(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Platform Engineering Intern", body=BODY + " Summer 2027."))
    close_all(conn)
    settle(conn, c, rjob("2", "Software Developer Intern", body=BODY + " Summer 2027."),
           at=T0 + timedelta(days=9))  # fmt: skip
    assert by_title(conn)["Software Developer Intern"]["freshness"] != "repost"


def test_reworded_repost_in_the_same_poll_the_old_one_vanishes_attaches_to_it(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern, Backend"))
    # next poll: the old id is gone (still open: closing takes two misses), a reworded one is up
    settle(conn, c, rjob("2", "Backend Software Engineer Intern"), at=T0 + timedelta(hours=1))
    sources = conn.execute(
        "select source_job_id, job_id from job_sources where source_job_id in ('1', '2')"
    ).fetchall()
    assert len(sources) == 2 and len({r["job_id"] for r in sources}) == 1  # one continuing job
    assert len(jobs(conn)) == 1


def test_open_exact_match_wins_over_a_closed_fuzzy_match_with_the_same_term(conn):
    c = company(conn)
    settle(
        conn,
        c,
        rjob("9", "Software Engineer Intern Summer 2027", location="Toronto, ON | Waterloo, ON"),
    )
    close_all(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern", location="Toronto, ON"),
           at=T0 + timedelta(days=1))  # fmt: skip
    settle(conn, c, rjob("1", "Software Engineer Intern", location="Toronto, ON"),
           rjob("2", "Software Engineer Intern (Summer 2027)", location="Toronto, ON"),
           at=T0 + timedelta(days=2))  # fmt: skip
    open_rows = [r for r in jobs(conn) if r["status"] == "open" and r["title"].startswith("Soft")]
    assert len(open_rows) == 1  # id 2 attached to the open exact match, not inserted as a repost


def test_same_title_in_another_city_while_the_first_is_open_is_a_separate_job(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern", location="Toronto, ON"))
    settle(conn, c, rjob("1", "Software Engineer Intern", location="Toronto, ON"),
           rjob("2", "Software Engineer Intern", location="Waterloo, ON"),
           at=T0 + timedelta(hours=1))  # fmt: skip
    rows = jobs(conn)
    assert len([r for r in rows if r["title"] == "Software Engineer Intern"]) == 2
    assert all(r["freshness"] != "repost" for r in rows)


def test_a_new_term_of_the_same_role_is_fresh_not_a_repost(conn):
    c = company(conn)
    settle(conn, c, rjob("1", "Software Engineer Intern (Summer 2026)"))
    close_all(conn)
    settle(conn, c, rjob("2", "Software Engineer Intern (Summer 2027)"), at=T0 + timedelta(days=30))
    assert by_title(conn)["Software Engineer Intern (Summer 2027)"]["freshness"] == "fresh"


def test_unchanged_board_with_open_internships_keeps_the_company_hot(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")]), T0)
    c = db.get_companies(conn, ats=["greenhouse"], slug="acme")[0]
    later = T0 + timedelta(days=40)
    db.ingest(conn, outcome(c, [raw("1")], unchanged=True), later)
    seen = conn.execute("select last_intern_seen_at from companies").fetchone()
    assert seen["last_intern_seen_at"] == later


# --- listed-but-unreadable postings (pending) ----------------------------------------------


def pending_outcome(c, raws, pending):
    out = outcome(c, raws)
    out.seen_ids = out.seen_ids | set(pending)
    out.pending_ids = set(pending)
    out.ids_hash = None
    return out


def test_pending_posting_stays_open_and_is_touched(conn):
    c = company(conn)
    db.ingest(conn, outcome(c, [raw("1")] + other()), T0)
    later = T0 + timedelta(minutes=30)
    for i in range(3):  # its detail fetch keeps failing, but the board still lists it
        c = db.get_companies(conn, ats=["greenhouse"], slug="acme")[0]
        db.ingest(
            conn,
            pending_outcome(c, [raw("2", title="Data Analyst Intern")], {"1"}),
            later + timedelta(minutes=i),
        )
    job = by_title(conn)["Software Engineer Intern"]
    assert job["status"] == "open" and job["miss_count"] == 0
    assert job["last_seen_at"] == later + timedelta(minutes=2)


# --- remembered postings (Meta) --------------------------------------------------------------


def meta_raw(id_, title="Software Engineer Intern"):
    return RawJob(
        source="meta", source_job_id=id_, title=title, url=f"https://m/{id_}",
        location_raw="Menlo Park, CA, US", source_posted_at=T0,
    )  # fmt: skip


def meta_outcome(c, raws, pending=(), rejected=(), forgotten=()):
    out = outcome(c, raws)
    out.pending_ids = set(pending)
    out.seen_ids = out.seen_ids | set(pending)
    out.ids_hash = None
    out.rejected_ids = set(rejected)
    out.forgotten_ids = set(forgotten)
    return out


def test_load_known_separates_open_jobs_from_rejected_pages(conn):
    c = company(conn, "meta", ats="greenhouse")
    conn.execute("update companies set ats = 'meta' where id = %s", (c.id,))
    c = db.get_companies(conn, ats=["meta"])[0]
    db.ingest(conn, meta_outcome(c, [], rejected={"7", "8"}), T0)
    conn.execute("insert into checked_postings (source, source_job_id) values ('other', '9')")
    open_ids, checked = db.load_known(conn, c)
    assert (open_ids, checked) == (set(), {"7", "8"})


def test_rejected_ids_are_stored_once_and_forgotten_ids_deleted(conn):
    c = company(conn, "meta2")
    conn.execute("update companies set ats = 'meta' where id = %s", (c.id,))
    c = db.get_companies(conn, ats=["meta"])[0]
    db.ingest(conn, meta_outcome(c, [], rejected={"1", "2"}), T0)
    db.ingest(conn, meta_outcome(c, [], rejected={"2", "3"}, forgotten={"1"}), T0)
    rows = conn.execute("select source_job_id from checked_postings order by 1").fetchall()
    assert [r["source_job_id"] for r in rows] == ["2", "3"]


def test_known_open_job_survives_polls_while_listed_and_closes_after_it_leaves(conn):
    c = company(conn, "meta3")
    conn.execute("update companies set ats = 'meta' where id = %s", (c.id,))
    c = db.get_companies(conn, ats=["meta"])[0]
    db.ingest(conn, meta_outcome(c, [meta_raw("1")]), T0)
    open_ids, _ = db.load_known(conn, c)
    assert open_ids == {"1"}
    for i in range(1, 4):  # listed but not re-read (pending), plus another posting each time
        db.ingest(
            conn,
            meta_outcome(c, [meta_raw(f"x{i}", "Data Analyst Intern")], pending={"1"}),
            T0 + timedelta(minutes=5 * i),
        )
    job = by_title(conn)["Software Engineer Intern"]
    assert job["status"] == "open" and job["miss_count"] == 0
    for i in (4, 5):  # now it has left the sitemap
        db.ingest(
            conn,
            meta_outcome(c, [meta_raw("y", "Data Analyst Intern")]),
            T0 + timedelta(minutes=5 * i),
        )
    assert by_title(conn)["Software Engineer Intern"]["status"] == "closed"


def test_two_reworded_postings_that_are_both_still_listed_stay_separate(conn):
    c = company(conn)
    settle(
        conn, c,
        rjob("1", "Software Engineer Intern, Backend"),
        rjob("2", "Backend Software Engineer Intern"),
    )  # fmt: skip
    rows = [r for r in jobs(conn)]
    assert len(rows) == 2  # both are listed right now, so neither is a continuation of the other
