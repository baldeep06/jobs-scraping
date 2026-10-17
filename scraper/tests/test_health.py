from datetime import UTC, datetime, timedelta

from scraper import db

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def run(conn, workflow, minutes_ago, errors=0):
    t = NOW - timedelta(minutes=minutes_ago)
    db.record_run(
        conn, workflow=workflow, source="ats", started_at=t, finished_at=t, companies_polled=5,
        jobs_seen=0, jobs_new=0, jobs_closed=0, errors=errors, error_samples=[],
    )  # fmt: skip


def test_health_flags_stale_and_missing_workflows(conn):
    run(conn, "scrape-heavy", 10, errors=2)
    run(conn, "scrape-heavy", 200)  # an older run must not hide the latest one
    h = {r["workflow"]: r for r in db.health(conn, NOW)}
    assert h["scrape-heavy"]["degraded"] is False and h["scrape-heavy"]["errors"] == 2
    assert h["scrape-sweep"]["degraded"] is True and h["scrape-sweep"]["last_finished_at"] is None


def test_health_degrades_after_the_window(conn):
    run(conn, "scrape-express", 11)
    run(conn, "scrape-fast", 14)
    run(conn, "scrape-heavy", 31)
    run(conn, "scrape-sweep", 119)
    h = {r["workflow"]: r["degraded"] for r in db.health(conn, NOW)}
    assert h == {
        "scrape-express": True, "scrape-fast": False, "scrape-heavy": True, "scrape-sweep": False
    }  # fmt: skip


def test_every_lane_has_a_health_window():
    assert set(db.HEALTH_WINDOWS) == {f"scrape-{lane}" for lane in db.LANES} | {"scrape-sweep"}


def test_a_run_where_every_company_failed_is_not_a_successful_run(conn):
    run(conn, "scrape-heavy", 20)
    t = NOW - timedelta(minutes=5)
    db.record_run(
        conn, workflow="scrape-heavy", source="ats", started_at=t, finished_at=t,
        companies_polled=40, jobs_seen=0, jobs_new=0, jobs_closed=0, errors=40, error_samples=[],
    )  # fmt: skip
    hot = {r["workflow"]: r for r in db.health(conn, NOW)}["scrape-heavy"]
    assert hot["degraded"] is False and hot["last_finished_at"] == NOW - timedelta(minutes=20)
    t = NOW - timedelta(minutes=90)
    conn.execute("update scrape_runs set finished_at = %s where errors = 0", (t,))
    assert {r["workflow"]: r for r in db.health(conn, NOW)}["scrape-heavy"]["degraded"] is True
