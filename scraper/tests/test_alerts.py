from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from scraper.digest import alerts
from scraper.digest.send import SendError

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
ENV = {"DIGEST_TO": "me@example.com", "RESEND_API_KEY": "re_test"}
ROOT = Path(__file__).resolve().parents[2]


def company(conn, name, groups=("unicorn",)):
    return conn.execute(
        "insert into companies (name, ats, slug, groups) values (%s, 'greenhouse', %s, %s) returning id",
        (name, name.lower(), list(groups)),
    ).fetchone()["id"]


def job(conn, cid, title="Software Engineer Intern", category="SWE", country="US", visa="open",
        freshness="fresh", age=timedelta(minutes=5), url="https://jobs.example.com/1"):  # fmt: skip
    return conn.execute(
        """insert into jobs (company_id, title, normalized_title, category, country, visa_status,
                             fingerprint, best_url, freshness, first_seen_at, location_raw)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'New York, NY') returning id""",
        (cid, title, title.lower(), category, country, visa, f"fp-{title}-{cid}", url, freshness,
         NOW - age),
    ).fetchone()["id"]  # fmt: skip


def test_only_new_priority_swe_internships_are_claimed(conn):
    stripe = company(conn, "Stripe", ("big_tech_adjacent",))
    shop = company(conn, "Corner Shop", ())
    want = job(conn, stripe)
    ca_blocked = job(conn, stripe, title="SWE Intern Toronto", country="CA", visa="blocked")
    job(conn, shop)  # not a priority company
    job(conn, stripe, title="Data Science Intern", category="Data/ML")
    job(conn, stripe, title="Backlog Intern", freshness="existing")  # was open before we watched
    job(conn, stripe, title="Old Intern", age=timedelta(hours=7))
    job(conn, stripe, title="Citizens Only Intern", visa="blocked")  # US role you cannot take
    got = {r["id"] for r in alerts.claim(conn, NOW)}
    assert got == {want, ca_blocked}


def test_a_job_is_claimed_once(conn):
    job(conn, company(conn, "Stripe"))
    assert len(alerts.claim(conn, NOW)) == 1
    assert alerts.claim(conn, NOW) == []


def test_at_most_max_per_hour_are_sent(conn, monkeypatch):
    monkeypatch.setattr(alerts, "MAX_PER_HOUR", 3)
    cid = company(conn, "Stripe")
    for i in range(5):
        job(conn, cid, title=f"SWE Intern {i}")
    assert len(alerts.claim(conn, NOW)) == 3
    assert alerts.claim(conn, NOW) == []
    assert len(alerts.claim(conn, NOW + timedelta(minutes=61))) == 2


def test_send_due_emails_once_and_marks_the_jobs(conn):
    job(conn, company(conn, "Stripe"))
    sent = []
    n = alerts.send_due(conn, ENV, NOW, send=lambda *a, **k: sent.append(a))
    assert n == 1 and len(sent) == 1
    assert alerts.send_due(conn, ENV, NOW, send=lambda *a, **k: sent.append(a)) == 0
    assert len(sent) == 1


def test_a_failed_send_releases_the_jobs_for_the_next_pass(conn):
    job(conn, company(conn, "Stripe"))

    def fail(*a, **k):
        raise SendError("Resend rejected the email (HTTP 403, validation_error)")

    assert alerts.send_due(conn, ENV, NOW, send=fail) == 0
    sent = []
    assert alerts.send_due(conn, ENV, NOW, send=lambda *a, **k: sent.append(a)) == 1


def test_without_email_settings_nothing_is_claimed_or_sent(conn):
    job(conn, company(conn, "Stripe"))
    sent = []
    assert alerts.send_due(conn, {}, NOW, send=lambda *a, **k: sent.append(a)) == 0
    assert sent == [] and len(alerts.claim(conn, NOW)) == 1


def test_render_one_and_many():
    row = {"company": "Stripe", "title": "SWE <Intern>", "location_raw": "New York, NY",
           "term": "Summer 2027", "url": "https://jobs.example.com/1", "pay": "USD 50/h",
           "country": "US"}  # fmt: skip
    subject, html, text = alerts.render([row])
    assert subject == "🔔 Stripe: SWE <Intern>"
    assert "SWE &lt;Intern&gt;" in html and 'href="https://jobs.example.com/1"' in html
    assert "https://jobs.example.com/1" in text
    bad = row | {"url": "javascript:alert(1)", "company": "Ramp"}
    subject, html, _ = alerts.render([row, bad])
    assert subject == "🔔 2 new priority SWE internships: Stripe, Ramp"
    assert "javascript:" not in html


@pytest.mark.parametrize("name", ["scrape-express", "scrape-fast", "scrape-heavy", "scrape-sweep"])
def test_scrape_workflows_can_send_alerts(name):
    wf = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())
    steps = wf["jobs"][next(iter(wf["jobs"]))]["steps"]
    env = next(s for s in steps if "scraper run" in s.get("run", ""))["env"]
    for key in ("RESEND_API_KEY", "DIGEST_TO", "DIGEST_FROM"):
        assert env[key] == f"${{{{ secrets.{key} }}}}"


def test_each_scrape_pass_sends_due_alerts(conn, monkeypatch):
    from scraper import __main__ as cli

    called = []
    monkeypatch.setattr(cli, "_connect", lambda: conn)

    async def no_companies(cs):
        return []

    monkeypatch.setattr(cli, "_poll_all", no_companies)
    monkeypatch.setattr(cli, "send_alerts", lambda c, env, now: called.append(now) or 0)
    cli.main(["run", "--lane", "express"])
    assert len(called) == 1
