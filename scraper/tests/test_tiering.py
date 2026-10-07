from datetime import UTC, datetime, timedelta

from scraper import db
from scraper.tests.test_db_ingest import company, outcome, raw

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def add(conn, slug, *, hot=False, intern_days=None, created_days=0, polled_hours=None, tier=None):
    db.upsert_companies(conn, [{"name": slug, "ats": "lever", "slug": slug, "hot": hot}])
    conn.execute(
        """update companies set created_at = %s, last_intern_seen_at = %s, last_polled_at = %s,
             tier = coalesce(%s, tier) where slug = %s""",
        (
            NOW - timedelta(days=created_days),
            None if intern_days is None else NOW - timedelta(days=intern_days),
            None if polled_hours is None else NOW - timedelta(hours=polled_hours),
            tier,
            slug,
        ),
    )  # fmt: skip


def tiers(conn):
    return {r["slug"]: r["tier"] for r in conn.execute("select slug, tier from companies")}


def test_retier_rules(conn):
    add(conn, "curated", hot=True, intern_days=200)
    add(conn, "recent", intern_days=10)
    add(conn, "middling", intern_days=60, tier="hot")
    add(conn, "stale", intern_days=120)
    add(conn, "never-old", created_days=100)
    add(conn, "never-new", created_days=5, tier="cold")
    add(conn, "dead", intern_days=1, tier="inactive")
    db.retier(conn, NOW)
    assert tiers(conn) == {
        "curated": "hot", "recent": "hot", "middling": "warm", "stale": "cold",
        "never-old": "cold", "never-new": "warm", "dead": "inactive",
    }  # fmt: skip


def test_ingest_promotes_to_hot_when_interns_found(conn):
    c = company(conn, "promo")
    conn.execute("update companies set tier = 'cold' where id = %s", (c.id,))
    db.ingest(conn, outcome(c, [raw("1")]), NOW)
    assert tiers(conn)["promo"] == "hot"


def test_ingest_without_interns_keeps_tier(conn):
    c = company(conn, "quiet")
    conn.execute("update companies set tier = 'cold' where id = %s", (c.id,))
    db.ingest(conn, outcome(c, [raw("1", title="Account Executive")]), NOW)
    assert tiers(conn)["quiet"] == "cold"


def test_sweep_selection(conn):
    add(conn, "hot-one", hot=True)
    add(conn, "warm-never", tier="warm")
    add(conn, "warm-recent", tier="warm", polled_hours=1)
    add(conn, "cold-recent", tier="cold", polled_hours=2)
    add(conn, "cold-due", tier="cold", polled_hours=7)
    add(conn, "dead", tier="inactive")
    got = [c.slug for c in db.get_sweep_companies(conn, ats=["lever"], now=NOW)]
    # least recently polled first (never polled first); hot/inactive/not-due-cold excluded
    assert got == ["warm-never", "cold-due", "warm-recent"]
    assert [c.slug for c in db.get_sweep_companies(conn, ats=["lever"], now=NOW, limit=1)] == [
        "warm-never"
    ]
