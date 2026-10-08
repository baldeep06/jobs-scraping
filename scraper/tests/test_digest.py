from datetime import UTC, datetime, timedelta

from scraper.digest.select import DigestConfig, load_config, select_jobs
from scraper.tests.test_db_ingest import company

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
CFG = DigestConfig(
    categories=["SWE", "Data/ML"], hide_blocked=True, fresh_only=True, min_hourly_pay=None
)


def add(conn, cid, title, *, country="US", visa="open", freshness="fresh", category="SWE",
        pay=None, hours_ago=2, status="open"):  # fmt: skip
    conn.execute(
        """insert into jobs (company_id, title, normalized_title, category, country, location_raw,
             visa_status, fingerprint, best_url, freshness, pay_hourly_max, pay_currency,
             first_seen_at, status)
           values (%s,%s,%s,%s,%s,'Somewhere',%s,%s,'https://x/'||%s,%s,%s,'USD',%s,%s)""",
        (cid, title, title.lower(), category, country, visa, title, title, freshness, pay,
         NOW - timedelta(hours=hours_ago), status),
    )  # fmt: skip


def titles(rows):
    return [r["title"] for r in rows]


def test_load_config(tmp_path):
    p = tmp_path / "c.yml"
    p.write_text("categories: [SWE]\nhide_blocked: false\nfresh_only: true\nmin_hourly_pay: 25\n")
    assert load_config(p) == DigestConfig(["SWE"], False, True, 25.0)


def test_selection_filters(conn):
    c = company(conn)
    add(conn, c.id, "keep")
    add(conn, c.id, "too old", hours_ago=30)
    add(conn, c.id, "closed", status="closed")
    add(conn, c.id, "blocked", visa="blocked")
    add(conn, c.id, "repost", freshness="repost")
    add(conn, c.id, "backlog", freshness="existing")
    add(conn, c.id, "wrong category", category="PM")
    got = select_jobs(conn, NOW - timedelta(hours=24), CFG)
    assert titles(got["US"].top + got["US"].rest) == ["keep"]


def test_top_picks_need_visa_open_pay_and_fresh(conn):
    c = company(conn)
    add(conn, c.id, "pick", pay=40)
    add(conn, c.id, "no pay")
    add(conn, c.id, "unknown visa", visa="unknown", pay=40)
    got = select_jobs(conn, NOW - timedelta(hours=24), CFG)
    assert titles(got["US"].top) == ["pick"]
    assert sorted(titles(got["US"].rest)) == ["no pay", "unknown visa"]


def test_both_country_jobs_appear_in_both_regions(conn):
    c = company(conn)
    add(conn, c.id, "everywhere", country="BOTH", pay=30)
    add(conn, c.id, "canada only", country="CA")
    got = select_jobs(conn, NOW - timedelta(hours=24), CFG)
    assert "everywhere" in titles(got["US"].top + got["US"].rest)
    assert sorted(titles(got["CA"].top + got["CA"].rest)) == ["canada only", "everywhere"]


def test_min_pay_drops_unlisted_and_low_pay(conn):
    c = company(conn)
    add(conn, c.id, "high", pay=50)
    add(conn, c.id, "low", pay=10)
    add(conn, c.id, "none")
    cfg = DigestConfig(["SWE"], True, True, 25.0)
    got = select_jobs(conn, NOW - timedelta(hours=24), cfg)
    assert titles(got["US"].top + got["US"].rest) == ["high"]
