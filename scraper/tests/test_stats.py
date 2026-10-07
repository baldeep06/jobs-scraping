from datetime import UTC, datetime, timedelta

from scraper import db, stats
from scraper.tests.test_db_ingest import company, outcome, raw

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_prune_drops_old_runs_only(conn):
    for age in (45, 5):
        db.record_run(
            conn, workflow="w", source="ats", started_at=NOW - timedelta(days=age),
            finished_at=NOW - timedelta(days=age), companies_polled=1, jobs_seen=0,
            jobs_new=0, jobs_closed=0, errors=0, error_samples=[],
        )  # fmt: skip
    assert db.prune(conn, NOW) == 1
    assert conn.execute("select count(*) as n from scrape_runs").fetchone()["n"] == 1


def test_stats_and_render(conn):
    c = company(conn, "acme")
    db.ingest(conn, outcome(c, [raw("1")]), NOW)
    data = db.stats(conn, NOW)
    assert data["companies_by_tier"]["hot"] == 1
    assert data["companies_by_ats"]["greenhouse"] == 1
    assert data["open_jobs_by_country"]["CA"] == 1
    text = stats.render(data, NOW)
    assert text.startswith("# Intern Radar stats")
    assert "2026-10-07" in text and "| hot | 1 |" in text and "| CA | 1 |" in text
    assert "\n\n\n" not in text and text.endswith("\n")
