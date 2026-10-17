from datetime import UTC, datetime

import pytest

from scraper import db
from scraper.adapters import ADAPTERS

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
ALL = list(ADAPTERS)


def add(conn, slug, ats="greenhouse", tier="hot", curated=False, fails=0):
    conn.execute(
        """insert into companies (name, ats, slug, tier, curated_hot, fail_count)
           values (%s, %s, %s, %s, %s, %s)""",
        (slug, ats, slug, tier, curated, fails),
    )


@pytest.fixture
def companies(conn):
    add(conn, "stripe", curated=True)
    add(conn, "nvidia", ats="workday", curated=True)
    add(conn, "google", ats="google", curated=True)  # big-tech sites: never every minute
    add(conn, "figma")
    add(conn, "acme-wd", ats="workday")
    add(conn, "Tesla", ats="simplify")  # aggregators: never in a fast lane
    add(conn, "IBM", ats="internlist")
    add(conn, "broken", fails=3)
    add(conn, "broken-curated", curated=True, fails=5)
    add(conn, "quiet", tier="warm")
    add(conn, "gone", tier="inactive")
    return conn


def slugs(rows):
    return sorted(c.slug for c in rows)


@pytest.mark.parametrize(
    ("lane", "expected"),
    [
        ("express", ["nvidia", "stripe"]),
        ("fast", ["figma"]),
        ("heavy", ["acme-wd", "google"]),
    ],
)
def test_each_hot_company_is_in_exactly_one_lane(companies, lane, expected):
    assert slugs(db.get_lane_companies(companies, lane=lane, ats=ALL, now=NOW)) == expected


def test_the_sweep_takes_warm_aggregators_and_failing_companies(companies):
    got = slugs(db.get_sweep_companies(companies, ats=ALL, now=NOW))
    assert got == ["IBM", "Tesla", "broken", "broken-curated", "quiet"]


def test_lanes_and_sweep_never_overlap(companies):
    lanes = [
        c.slug
        for lane in db.LANES
        for c in db.get_lane_companies(companies, lane=lane, ats=ALL, now=NOW)
    ]
    sweep = [c.slug for c in db.get_sweep_companies(companies, ats=ALL, now=NOW)]
    assert len(lanes) == len(set(lanes))
    assert not set(lanes) & set(sweep)
    every = {
        r["slug"] for r in companies.execute("select slug from companies where tier <> 'inactive'")
    }
    assert set(lanes) | set(sweep) == every


def _fake_run(monkeypatch, conn):
    from scraper import __main__ as cli
    from scraper.models import CompanyOutcome

    polled, runs = [], []

    async def fake_poll_all(cs):
        polled.extend(c.slug for c in cs)
        return [CompanyOutcome(company=c, ok=True, seconds=float(i)) for i, c in enumerate(cs)]

    monkeypatch.setattr(cli, "_connect", lambda: conn)
    monkeypatch.setattr(cli, "_poll_all", fake_poll_all)
    monkeypatch.setattr(cli.db, "ingest", lambda *a, **k: db.IngestStats())
    monkeypatch.setattr(cli.db, "record_run", lambda conn, **kw: runs.append(kw))
    return cli, polled, runs


def test_run_lane_polls_that_lane_and_names_the_run(companies, monkeypatch, capsys):
    cli, polled, runs = _fake_run(monkeypatch, companies)
    assert cli.main(["run", "--lane", "express"]) == 0
    assert sorted(polled) == ["nvidia", "stripe"]
    assert runs[0]["workflow"] == "scrape-express"
    assert "slowest:" in capsys.readouterr().out


def test_sweep_is_not_capped_at_500(companies, monkeypatch):
    for i in range(600):
        add(companies, f"warm-{i}", tier="warm")
    cli, polled, _ = _fake_run(monkeypatch, companies)
    cli.main(["run", "--sweep"])
    assert len(polled) > 600


async def test_poll_records_how_long_a_company_took():
    from scraper.models import Company, FetchResult
    from scraper.pipeline import poll

    async def adapter(fetcher, company):
        return FetchResult(jobs=[])

    c = Company(id=1, name="x", ats="greenhouse", slug="x")
    outcome = await poll(None, c, adapters={"greenhouse": adapter})
    assert outcome.ok and outcome.seconds >= 0


def test_a_dry_run_also_lists_the_slowest_companies(companies, monkeypatch, capsys):
    cli, _, _ = _fake_run(monkeypatch, companies)
    cli.main(["run", "--lane", "fast", "--dry-run"])
    assert "slowest: greenhouse/figma 0.0s" in capsys.readouterr().out


# --- vendor cooldown and per-ATS pacing ---------------------------------------------------------

from datetime import timedelta  # noqa: E402


def test_a_blocked_ats_cools_down_longer_each_time_and_recovers(conn):
    db.record_ats_health(conn, blocked={"workday"}, healthy=set(), now=NOW)
    assert db.ats_cooldowns(conn, NOW + timedelta(minutes=29)) == {"workday"}
    assert db.ats_cooldowns(conn, NOW + timedelta(minutes=31)) == set()
    later = NOW + timedelta(minutes=31)
    db.record_ats_health(conn, blocked={"workday"}, healthy=set(), now=later)
    assert db.ats_cooldowns(conn, later + timedelta(minutes=59)) == {"workday"}
    for _ in range(10):
        db.record_ats_health(conn, blocked={"workday"}, healthy=set(), now=later)
    assert db.ats_cooldowns(conn, later + timedelta(hours=6, minutes=1)) == set()  # capped at 6 h
    db.record_ats_health(conn, blocked=set(), healthy={"workday"}, now=later)
    db.record_ats_health(conn, blocked={"workday"}, healthy=set(), now=later)
    assert db.ats_cooldowns(conn, later + timedelta(minutes=31)) == set()  # back to 30 min


def test_cooling_ats_are_skipped_by_lanes_and_sweep(companies):
    db.record_ats_health(companies, blocked={"workday"}, healthy=set(), now=NOW)
    for lane in db.LANES:
        cs = db.get_lane_companies(companies, lane=lane, ats=ALL, now=NOW)
        assert all(c.ats != "workday" for c in cs)
    add(companies, "wd-warm", ats="workday", tier="warm")
    assert "wd-warm" not in slugs(db.get_sweep_companies(companies, ats=ALL, now=NOW))


def test_workday_tenants_are_polled_at_most_every_15_minutes(companies):
    companies.execute(
        "update companies set last_polled_at = %s where slug = 'acme-wd'",
        (NOW - timedelta(minutes=10),),
    )
    assert "acme-wd" not in slugs(db.get_lane_companies(companies, lane="heavy", ats=ALL, now=NOW))
    later = NOW + timedelta(minutes=6)
    assert "acme-wd" in slugs(db.get_lane_companies(companies, lane="heavy", ats=ALL, now=later))


def test_workable_is_in_the_heavy_lane_not_the_fast_one(companies):
    add(companies, "wk", ats="workable")
    assert "wk" in slugs(db.get_lane_companies(companies, lane="heavy", ats=ALL, now=NOW))
    assert "wk" not in slugs(db.get_lane_companies(companies, lane="fast", ats=ALL, now=NOW))


def test_a_pass_where_an_ats_is_mostly_blocked_puts_it_on_cooldown(companies, monkeypatch):
    from scraper import __main__ as cli
    from scraper.models import CompanyOutcome

    for i in range(6):
        add(companies, f"wd{i}", ats="workday")

    async def fake_poll_all(cs):
        return [
            CompanyOutcome(company=c, ok=False, error="invalid JSON: x (starts '<html>')")
            if c.ats == "workday"
            else CompanyOutcome(company=c, ok=True)
            for c in cs
        ]

    health = []
    monkeypatch.setattr(cli, "_connect", lambda: companies)
    monkeypatch.setattr(cli, "_poll_all", fake_poll_all)
    monkeypatch.setattr(cli.db, "ingest", lambda *a, **k: db.IngestStats())
    monkeypatch.setattr(cli.db, "record_ats_health", lambda conn, **kw: health.append(kw))
    cli.main(["run", "--lane", "heavy"])
    assert health[0]["blocked"] == {"workday"}
    assert health[0]["healthy"] == {"google"}
