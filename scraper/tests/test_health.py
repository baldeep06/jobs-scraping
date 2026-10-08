from datetime import UTC, datetime, timedelta

from scraper import db

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def run(conn, workflow, minutes_ago, errors=0):
    t = NOW - timedelta(minutes=minutes_ago)
    db.record_run(
        conn, workflow=workflow, source="ats", started_at=t, finished_at=t, companies_polled=1,
        jobs_seen=0, jobs_new=0, jobs_closed=0, errors=errors, error_samples=[],
    )  # fmt: skip


def test_health_flags_stale_and_missing_workflows(conn):
    run(conn, "scrape-hot", 10, errors=2)
    run(conn, "scrape-hot", 200)  # an older run must not hide the latest one
    h = {r["workflow"]: r for r in db.health(conn, NOW)}
    assert h["scrape-hot"]["degraded"] is False and h["scrape-hot"]["errors"] == 2
    assert h["scrape-sweep"]["degraded"] is True and h["scrape-sweep"]["last_finished_at"] is None


def test_health_degrades_after_the_window(conn):
    run(conn, "scrape-hot", 61)
    run(conn, "scrape-sweep", 119)
    h = {r["workflow"]: r["degraded"] for r in db.health(conn, NOW)}
    assert h == {"scrape-hot": True, "scrape-sweep": False}
