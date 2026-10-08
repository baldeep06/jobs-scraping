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


# --- rendering ------------------------------------------------------------------------------

from scraper.digest.build import render  # noqa: E402
from scraper.digest.select import Region  # noqa: E402

HEALTHY = [
    {
        "workflow": "scrape-hot",
        "degraded": False,
        "last_finished_at": NOW,
        "errors": 0,
        "window_minutes": 60,
    }  # fmt: skip
]


def job(**kw):
    base = dict(company="Acme", title="SWE Intern", category="SWE", location="Toronto, ON",
                term="Summer 2027", pay="CAD 30/h", visa_status="open", freshness="fresh",
                url="https://x/1")  # fmt: skip
    return base | kw


def test_render_lists_jobs_by_region_with_links():
    regions = {
        "US": Region(),
        "CA": Region(top=[job()], rest=[job(title="Data Intern", url="https://x/2", pay="")]),
    }
    subject, html, text = render(regions, HEALTHY, NOW)
    assert subject == "Intern Radar — 2 new internships (0 US · 2 CA)"
    assert "https://x/1" in html and "Acme" in html and "Top picks" in html
    assert "Data Intern" in text and "https://x/2" in text


def test_render_empty_day_still_sends_with_health():
    subject, html, text = render({"US": Region(), "CA": Region()}, HEALTHY, NOW)
    assert subject == "Intern Radar — no new internships today"
    assert "No new internships" in html and "All sources healthy" in html


def test_render_shows_degraded_sources():
    bad = [{**HEALTHY[0], "degraded": True}]
    _, html, text = render({"US": Region(), "CA": Region()}, bad, NOW)
    assert "scrape-hot" in html and "degraded" in html.lower() and "degraded" in text.lower()


def test_render_escapes_third_party_text():
    evil = job(title="<script>alert(1)</script>", company="A&B")
    _, html, _ = render({"US": Region(rest=[evil]), "CA": Region()}, HEALTHY, NOW)
    assert "<script>" not in html and "&lt;script&gt;" in html and "A&amp;B" in html


# --- sending --------------------------------------------------------------------------------

import httpx  # noqa: E402
import pytest  # noqa: E402

from scraper.digest.send import SendError, send_email  # noqa: E402

ENV = {"RESEND_API_KEY": "re_secretkey123", "DIGEST_TO": "me@example.com"}


def test_resend_request_shape():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"id": "1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    send_email("Subj", "<b>hi</b>", "hi", ENV, client=client)
    assert seen["auth"] == "Bearer re_secretkey123"
    assert "me@example.com" in seen["body"] and "Subj" in seen["body"]


def test_send_failure_never_leaks_key_or_recipient():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="bad")))
    with pytest.raises(SendError) as exc:
        send_email("S", "h", "t", ENV, client=client)
    assert "re_secretkey123" not in str(exc.value) and "example.com" not in str(exc.value)
    assert "403" in str(exc.value)


def test_missing_credentials_is_a_clear_error():
    with pytest.raises(SendError, match="RESEND_API_KEY"):
        send_email("S", "h", "t", {"DIGEST_TO": "me@example.com"})
    with pytest.raises(SendError, match="DIGEST_TO"):
        send_email("S", "h", "t", {"RESEND_API_KEY": "k"})


def test_smtp_fallback(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, **kw):
            sent["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            sent["user"] = user

        def send_message(self, msg):
            sent["to"] = msg["To"]

    monkeypatch.setattr("scraper.digest.send.smtplib.SMTP_SSL", FakeSMTP)
    env = {"DIGEST_TRANSPORT": "smtp", "DIGEST_TO": "me@example.com", "SMTP_HOST": "smtp.x.test",
           "SMTP_USER": "u", "SMTP_PASSWORD": "p"}  # fmt: skip
    send_email("S", "<b>h</b>", "t", env)
    assert sent == {"host": "smtp.x.test", "user": "u", "to": "me@example.com"}


# --- CLI ------------------------------------------------------------------------------------


def test_digest_dry_run_prints_subject_and_writes_html(conn, monkeypatch, capsys, tmp_path):
    from scraper import __main__ as cli

    monkeypatch.setattr(cli, "_connect", lambda: conn)
    out = tmp_path / "d.html"
    assert cli.main(["digest", "--dry-run", "--out", str(out)]) == 0
    assert capsys.readouterr().out.startswith("Intern Radar —")
    assert "<html" in out.read_text()


def test_digest_send_failure_exits_nonzero_without_secrets(conn, monkeypatch, capsys):
    from scraper import __main__ as cli

    monkeypatch.setattr(cli, "_connect", lambda: conn)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("DIGEST_TO", "me@example.com")
    assert cli.main(["digest"]) == 1
    shown = capsys.readouterr().out
    assert "RESEND_API_KEY" in shown and "me@example.com" not in shown


# --- review fixes ---------------------------------------------------------------------------


def test_non_http_links_are_not_rendered_as_links():
    evil = job(url="javascript:alert(1)")
    ok = job(title="Fine", url="https://x/ok")
    _, html, text = render({"US": Region(rest=[evil, ok]), "CA": Region()}, HEALTHY, NOW)
    assert "javascript:" not in html and "javascript:" not in text
    assert 'href="https://x/ok"' in html and "SWE Intern" in html


def test_select_blanks_unsafe_urls(conn):
    c = company(conn)
    add(conn, c.id, "hostile")
    conn.execute("update jobs set best_url = 'javascript:alert(1)'")
    got = select_jobs(conn, NOW - timedelta(hours=24), CFG)
    assert got["US"].rest[0]["url"] == ""


def test_empty_categories_means_all_categories(conn):
    c = company(conn)
    add(conn, c.id, "any category", category="Quant")
    cfg = DigestConfig(categories=[], hide_blocked=True, fresh_only=True, min_hourly_pay=None)
    got = select_jobs(conn, NOW - timedelta(hours=24), cfg)
    assert titles(got["US"].rest) == ["any category"]


def test_window_starts_at_the_last_digest_not_a_fixed_24h(conn, monkeypatch, capsys):
    from scraper import __main__ as cli
    from scraper import db

    c = company(conn)
    now = datetime.now(UTC)

    def at(hours_ago):
        return now - timedelta(hours=hours_ago)

    def seen(title, hours_ago):
        add(conn, c.id, title, hours_ago=0)
        conn.execute("update jobs set first_seen_at = %s where title = %s", (at(hours_ago), title))

    seen("after last digest", 28)  # a late cron stretched the gap to 30 h
    seen("before last digest", 31)
    db.record_run(
        conn, workflow="digest", source="digest", started_at=at(30), finished_at=at(30),
        companies_polled=0, jobs_seen=0, jobs_new=0, jobs_closed=0, errors=0, error_samples=[],
    )  # fmt: skip
    sent = {}
    monkeypatch.setattr(cli, "_connect", lambda: conn)
    monkeypatch.setattr(
        "scraper.digest.send.send_email", lambda subject, html, text, env: sent.update(t=text)
    )
    assert cli.main(["digest"]) == 0
    assert "after last digest" in sent["t"] and "before last digest" not in sent["t"]
    # sending recorded a new digest run, so the next window starts there
    last = conn.execute(
        "select max(finished_at) as t from scrape_runs where workflow = 'digest'"
    ).fetchone()["t"]
    assert last > at(1)


def test_dry_run_does_not_move_the_window(conn, monkeypatch):
    from scraper import __main__ as cli

    monkeypatch.setattr(cli, "_connect", lambda: conn)
    cli.main(["digest", "--dry-run"])
    assert conn.execute("select count(*) as n from scrape_runs").fetchone()["n"] == 0


def test_digest_workflow_passes_every_env_var_the_readme_documents():
    from pathlib import Path

    import yaml

    wf = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/digest.yml").read_text()
    )
    env = wf["jobs"]["digest"]["steps"][-1]["env"]
    assert {
        "DATABASE_URL", "RESEND_API_KEY", "DIGEST_TO", "DIGEST_FROM", "DIGEST_TRANSPORT",
        "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
    } <= set(env)  # fmt: skip


def test_rejection_reports_resend_error_name_but_never_its_message():
    body = {
        "name": "validation_error",
        "message": "You can only send testing emails to your own email address (owner@example.org).",
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=body)))
    with pytest.raises(SendError) as exc:
        send_email("S", "h", "t", ENV, client=client)
    shown = str(exc.value)
    assert "403" in shown and "validation_error" in shown
    assert "owner@example.org" not in shown and "testing emails" not in shown
