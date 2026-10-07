import psycopg
import pytest

from scraper import db


def test_migrate_is_idempotent(conn):
    assert db.migrate(conn) == []
    names = [r["name"] for r in conn.execute("select name from schema_migrations")]
    assert names == ["20261007000000_init.sql", "20261007120000_repost_signals.sql"]


def test_anon_reads_open_jobs_only_and_cannot_write(conn):
    cid = conn.execute(
        "insert into companies (name, ats, slug) values ('Acme','greenhouse','acme') returning id"
    ).fetchone()["id"]
    for status in ("open", "closed"):
        conn.execute(
            """insert into jobs (company_id, title, normalized_title, category, country,
                                 visa_status, fingerprint, best_url, status)
               values (%s, %s, 'x', 'SWE', 'CA', 'open', %s, 'https://x', %s)""",
            (cid, f"{status} job", status, status),
        )
    conn.execute("set role anon")
    try:
        assert [r["title"] for r in conn.execute("select title from jobs")] == ["open job"]
        feed = conn.execute("select company_name from jobs_feed")
        assert [r["company_name"] for r in feed] == ["Acme"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into companies (name, ats, slug) values ('x','lever','x')")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from source_state")
    finally:
        conn.execute("reset role")


def test_freshness_allows_existing_and_signal_columns_exist(conn):
    cid = conn.execute(
        "insert into companies (name, ats, slug) values ('Acme','greenhouse','acme') returning id"
    ).fetchone()["id"]
    conn.execute(
        """insert into jobs (company_id, title, normalized_title, category, country, visa_status,
                             fingerprint, best_url, freshness, title_key, desc_hash)
           values (%s, 't', 'x', 'SWE', 'CA', 'open', 'f', 'https://x', 'existing', 'k', 'h')""",
        (cid,),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """insert into jobs (company_id, title, normalized_title, category, country,
                                 visa_status, fingerprint, best_url, freshness)
               values (%s, 't', 'x', 'SWE', 'CA', 'open', 'f', 'https://x', 'bogus')""",
            (cid,),
        )
