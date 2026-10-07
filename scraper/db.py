from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scraper.dedupe import (
    ClosurePlan,
    Decision,
    ExistingSource,
    FingerprintMatch,
    OpenJob,
    classify,
    plan_closures,
)
from scraper.models import Company, CompanyOutcome, EnrichedJob

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
INACTIVE_AFTER_404S = 5
INACTIVE_AFTER = "24 hours"  # and the 404 streak must span at least this long


def connect(dsn: str) -> psycopg.Connection:
    # autocommit: every write goes through an explicit `with conn.transaction()` block.
    # prepare_threshold=None: Supabase's pooler doesn't support prepared statements.
    return psycopg.connect(dsn, autocommit=True, prepare_threshold=None, row_factory=dict_row)


def migrate(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    conn.execute(
        "create table if not exists schema_migrations "
        "(name text primary key, applied_at timestamptz not null default now())"
    )
    conn.execute("alter table schema_migrations enable row level security")
    applied = {r["name"] for r in conn.execute("select name from schema_migrations")}
    done = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
        done.append(path.name)
    return done


def upsert_companies(conn: psycopg.Connection, seeds: list[dict[str, Any]]) -> int:
    with conn.transaction():
        for s in seeds:
            conn.execute(
                """insert into companies (name, ats, slug, domain, workday_host, workday_site,
                                          curated_hot, tier)
                   values (%(name)s, %(ats)s, %(slug)s, %(domain)s, %(workday_host)s,
                           %(workday_site)s, %(hot)s,
                           case when %(hot)s then 'hot' else 'warm' end)
                   on conflict (ats, slug) do update set
                     name = excluded.name, domain = excluded.domain,
                     workday_host = excluded.workday_host,
                     workday_site = excluded.workday_site,
                     curated_hot = excluded.curated_hot,
                     -- re-seeding a curated company reactivates it
                     tier = case when excluded.curated_hot then 'hot' else companies.tier end,
                     consecutive_404s = case when excluded.curated_hot then 0
                                             else companies.consecutive_404s end,
                     first_404_at = case when excluded.curated_hot then null
                                         else companies.first_404_at end""",
                {
                    "name": s["name"],
                    "ats": s["ats"],
                    "slug": s["slug"],
                    "domain": s.get("domain"),
                    "workday_host": s.get("workday_host"),
                    "workday_site": s.get("workday_site"),
                    "hot": bool(s.get("hot", False)),
                },
            )
    return len(seeds)


def get_companies(
    conn: psycopg.Connection,
    *,
    ats: list[str],
    tier: str | None = None,
    slug: str | None = None,
    limit: int = 1000,
) -> list[Company]:
    rows = conn.execute(
        """select id, name, ats, slug, job_ids_hash, workday_host, workday_site from companies
           where ats = any(%(ats)s) and tier <> 'inactive'
             and (%(tier)s::text is null or tier = %(tier)s)
             and (%(slug)s::text is null or slug = %(slug)s)
           order by last_polled_at nulls first, id
           limit %(limit)s""",
        {"ats": ats, "tier": tier, "slug": slug, "limit": limit},
    ).fetchall()
    return [Company(**r) for r in rows]


@dataclass
class IngestStats:
    new: int = 0
    closed: int = 0
    seen: int = 0


def _job_fields(job: EnrichedJob) -> dict[str, Any]:
    pay, loc = job.pay, job.location
    return {
        "title": job.raw.title,
        "normalized_title": job.normalized_title,
        "category": job.category,
        "term": job.term,
        "duration_months": job.duration_months,
        "location_raw": job.raw.location_raw,
        "locations": Jsonb([x.model_dump() for x in loc.locations]),
        "country": loc.country,
        "work_mode": loc.work_mode,
        "location_unclear": loc.location_unclear,
        "pay_min": pay.min if pay else None,
        "pay_max": pay.max if pay else None,
        "pay_currency": pay.currency if pay else None,
        "pay_period": pay.period if pay else None,
        "pay_hourly_min": pay.hourly_min if pay else None,
        "pay_hourly_max": pay.hourly_max if pay else None,
        "pay_raw": pay.raw if pay else None,
        "visa_signals": job.visa_signals,
        "visa_status": job.visa_status,
        "flags": job.flags,
        "evidence": Jsonb(job.evidence),
        "fingerprint": job.fingerprint,
        "best_url": job.raw.url,
    }


# Must match the keys returned by _job_fields().
_FIELD_NAMES = [
    "title", "normalized_title", "category", "term", "duration_months", "location_raw",
    "locations", "country", "work_mode", "location_unclear", "pay_min", "pay_max",
    "pay_currency", "pay_period", "pay_hourly_min", "pay_hourly_max", "pay_raw",
    "visa_signals", "visa_status", "flags", "evidence", "fingerprint", "best_url",
]  # fmt: skip


def _insert_job(conn: psycopg.Connection, job: EnrichedJob, d: Decision, now: datetime) -> str:
    params = _job_fields(job) | {
        "company_id": job.company_id,
        "now": now,
        "posted": job.raw.source_posted_at,
        "freshness": d.freshness,
        "repost_of": d.repost_of,
        "repost_count": d.repost_count,
    }
    cols = ", ".join(_FIELD_NAMES)
    vals = ", ".join(f"%({c})s" for c in _FIELD_NAMES)
    row = conn.execute(
        f"""insert into jobs ({cols}, company_id, first_seen_at, last_seen_at, updated_at,
                              source_posted_at, freshness, repost_of, repost_count)
            values ({vals}, %(company_id)s, %(now)s, %(now)s, %(now)s,
                    %(posted)s, %(freshness)s, %(repost_of)s, %(repost_count)s)
            returning id""",
        params,
    ).fetchone()
    return str(row["id"])


def _update_job(
    conn: psycopg.Connection, job_id: str, job: EnrichedJob, d: Decision, now: datetime
) -> None:
    sets = ", ".join(f"{c} = %({c})s" for c in _FIELD_NAMES)
    conn.execute(
        f"""update jobs set {sets},
               last_seen_at = %(now)s, updated_at = %(now)s, miss_count = 0,
               source_posted_at = coalesce(%(posted)s, source_posted_at),
               freshness = coalesce(%(freshness)s, freshness),
               status = case when %(reopen)s then 'open' else status end,
               closed_at = case when %(reopen)s then null else closed_at end
            where id = %(id)s""",
        _job_fields(job)
        | {
            "now": now,
            "posted": job.raw.source_posted_at,
            "id": job_id,
            "freshness": d.freshness,
            "reopen": d.action == "reopen",
        },
    )


def _upsert_source(
    conn: psycopg.Connection, job_id: str, company_id: int, job: EnrichedJob, now: datetime
) -> None:
    raw = job.raw
    conn.execute(
        """insert into job_sources (job_id, company_id, source, source_job_id, url,
                                    source_posted_at, first_seen_at, last_seen_at)
           values (%(job)s, %(cid)s, %(src)s, %(sid)s, %(url)s, %(posted)s, %(now)s, %(now)s)
           on conflict (source, source_job_id) do update set
             last_seen_at = excluded.last_seen_at, url = excluded.url,
             source_posted_at = coalesce(excluded.source_posted_at, job_sources.source_posted_at)""",
        {
            "job": job_id,
            "cid": company_id,
            "src": raw.source,
            "sid": raw.source_job_id,
            "url": raw.url,
            "posted": raw.source_posted_at,
            "now": now,
        },
    )


def _ingest_job(
    conn: psycopg.Connection, company: Company, job: EnrichedJob, now: datetime
) -> bool:
    """Returns True if a new jobs row was created."""
    raw = job.raw
    row = conn.execute(
        """select js.job_id, j.status, j.first_seen_at, js.source_posted_at
           from job_sources js join jobs j on j.id = js.job_id
           where js.source = %s and js.source_job_id = %s""",
        (raw.source, raw.source_job_id),
    ).fetchone()
    existing = None
    if row:
        existing = ExistingSource(
            str(row["job_id"]), row["status"], row["first_seen_at"], row["source_posted_at"]
        )
    match = None
    if existing is None:
        fp = conn.execute(
            """select id, status, last_seen_at, repost_count, term from jobs
               where fingerprint = %s
               order by (term is not distinct from %s) desc, last_seen_at desc limit 1""",
            (job.fingerprint, job.term),
        ).fetchone()
        if fp:
            match = FingerprintMatch(
                str(fp["id"]), fp["status"], fp["last_seen_at"], fp["repost_count"], fp["term"]
            )

    d = classify(existing, raw.source_posted_at, match, now, incoming_term=job.term)
    if d.action == "insert":
        job_id = _insert_job(conn, job, d, now)
        _upsert_source(conn, job_id, company.id, job, now)
        return True
    if d.action == "attach":
        conn.execute(
            "update jobs set last_seen_at = %s, miss_count = 0 where id = %s", (now, d.job_id)
        )
        _upsert_source(conn, d.job_id, company.id, job, now)
        return False
    _update_job(conn, d.job_id, job, d, now)
    _upsert_source(conn, d.job_id, company.id, job, now)
    return False


def _open_jobs(conn: psycopg.Connection, company_id: int, source: str) -> list[OpenJob]:
    rows = conn.execute(
        """select j.id, j.miss_count, array_agg(js.source_job_id) as ids
           from jobs j join job_sources js on js.job_id = j.id
           where j.status = 'open' and js.company_id = %s and js.source = %s
           group by j.id, j.miss_count""",
        (company_id, source),
    ).fetchall()
    return [OpenJob(str(r["id"]), r["miss_count"], frozenset(r["ids"])) for r in rows]


def _apply_closures(conn: psycopg.Connection, plan: ClosurePlan, now: datetime) -> None:
    if plan.reset:
        conn.execute("update jobs set miss_count = 0 where id = any(%s::uuid[])", (plan.reset,))
    if plan.increment:
        conn.execute(
            "update jobs set miss_count = miss_count + 1 where id = any(%s::uuid[])",
            (plan.increment,),
        )
    if plan.close:
        conn.execute(
            """update jobs set status = 'closed', closed_at = %s, miss_count = miss_count + 1,
                               updated_at = %s
               where id = any(%s::uuid[])""",
            (now, now, plan.close),
        )


def _touch_seen(
    conn: psycopg.Connection, company_id: int, source: str, seen: list[str], now: datetime
) -> None:
    params = {"now": now, "cid": company_id, "src": source, "seen": seen}
    conn.execute(
        """update jobs set last_seen_at = %(now)s, miss_count = 0
           where status = 'open' and id in (
             select job_id from job_sources
             where company_id = %(cid)s and source = %(src)s and source_job_id = any(%(seen)s))""",
        params,
    )
    conn.execute(
        """update job_sources set last_seen_at = %(now)s
           where company_id = %(cid)s and source = %(src)s and source_job_id = any(%(seen)s)""",
        params,
    )


def ingest(conn: psycopg.Connection, outcome: CompanyOutcome, now: datetime) -> IngestStats:
    """Write one company's poll result in a single transaction."""
    company = outcome.company
    with conn.transaction():
        if not outcome.ok:
            is_404 = outcome.status == 404
            row = conn.execute(
                """update companies set last_polled_at = %(now)s, fail_count = fail_count + 1,
                     consecutive_404s = case when %(is_404)s then consecutive_404s + 1 else 0 end,
                     first_404_at = case when %(is_404)s then coalesce(first_404_at, %(now)s)
                                         end,
                     tier = case when %(is_404)s and consecutive_404s + 1 >= %(limit)s
                                      and %(now)s - coalesce(first_404_at, %(now)s)
                                          >= %(window)s::interval
                                 then 'inactive' else tier end
                   where id = %(id)s
                   returning tier""",
                {
                    "now": now,
                    "is_404": is_404,
                    "limit": INACTIVE_AFTER_404S,
                    "window": INACTIVE_AFTER,
                    "id": company.id,
                },
            ).fetchone()
            stats = IngestStats()
            if row and row["tier"] == "inactive":
                # The board is gone: its jobs will never be polled again, so close them.
                closed = conn.execute(
                    """update jobs set status = 'closed', closed_at = %s, updated_at = %s
                       where company_id = %s and status = 'open'""",
                    (now, now, company.id),
                )
                stats.closed = closed.rowcount
            return stats

        source = company.ats
        stats = IngestStats(seen=len(outcome.seen_ids))
        if outcome.unchanged:
            _touch_seen(conn, company.id, source, sorted(outcome.seen_ids), now)
        else:
            stats.new = sum(_ingest_job(conn, company, job, now) for job in outcome.jobs)

        # An empty board or records that failed validation look like an upstream glitch or an
        # API change, not like every job being taken down: count no misses for this poll.
        if (outcome.seen_ids or outcome.confirmed_empty) and not outcome.invalid:
            enriched = None if outcome.unchanged else {j.raw.source_job_id for j in outcome.jobs}
            plan = plan_closures(_open_jobs(conn, company.id, source), outcome.seen_ids, enriched)
            _apply_closures(conn, plan, now)
            stats.closed = len(plan.close)

        conn.execute(
            """update companies set last_polled_at = %(now)s, last_success_at = %(now)s,
                 fail_count = 0, consecutive_404s = 0, first_404_at = null,
                 job_ids_hash = %(hash)s,
                 last_intern_seen_at = case when %(interns)s then %(now)s
                                            else last_intern_seen_at end,
                 tier = case when %(interns)s and tier in ('warm', 'cold') then 'hot'
                             else tier end
               where id = %(id)s""",
            {"now": now, "hash": outcome.ids_hash, "interns": bool(outcome.jobs), "id": company.id},
        )
    return stats


def record_run(
    conn: psycopg.Connection,
    *,
    workflow: str,
    source: str,
    started_at: datetime,
    finished_at: datetime,
    companies_polled: int,
    jobs_seen: int,
    jobs_new: int,
    jobs_closed: int,
    errors: int,
    error_samples: list[dict[str, Any]],
) -> None:
    conn.execute(
        """insert into scrape_runs (workflow, source, started_at, finished_at, companies_polled,
                                    jobs_seen, jobs_new, jobs_closed, errors, error_samples)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            workflow,
            source,
            started_at,
            finished_at,
            companies_polled,
            jobs_seen,
            jobs_new,
            jobs_closed,
            errors,
            Jsonb(error_samples[:20]),
        ),  # fmt: skip
    )


def discover_companies(conn: psycopg.Connection, seeds: list[dict[str, Any]]) -> int:
    """Insert boards we don't know yet as warm companies. Never touches existing rows."""
    added = 0
    with conn.transaction():
        for s in seeds:
            cur = conn.execute(
                """insert into companies (name, ats, slug, workday_host, workday_site,
                                          tier, discovered_from)
                   values (%(name)s, %(ats)s, %(slug)s, %(workday_host)s, %(workday_site)s,
                           'warm', 'simplify')
                   on conflict (ats, slug) do nothing""",
                {
                    "name": s["name"],
                    "ats": s["ats"],
                    "slug": s["slug"],
                    "workday_host": s.get("workday_host"),
                    "workday_site": s.get("workday_site"),
                },
            )
            added += cur.rowcount
    return added


def get_state_sha(conn: psycopg.Connection, source: str) -> str | None:
    row = conn.execute(
        "select last_commit_sha from source_state where source = %s", (source,)
    ).fetchone()
    return row["last_commit_sha"] if row else None


def set_state_sha(conn: psycopg.Connection, source: str, sha: str) -> None:
    conn.execute(
        """insert into source_state (source, last_commit_sha) values (%s, %s)
           on conflict (source) do update set last_commit_sha = excluded.last_commit_sha""",
        (source, sha),
    )


HOT_WINDOW = "30 days"
COLD_AFTER = "90 days"
COLD_REPOLL = "6 hours"


def retier(conn: psycopg.Connection, now: datetime) -> None:
    """hot = curated or an intern posting in the last 30 days; cold = none in 90; else warm."""
    conn.execute(
        """update companies set tier = case
             when curated_hot or last_intern_seen_at >= %(now)s - %(hot)s::interval then 'hot'
             when coalesce(last_intern_seen_at, created_at) < %(now)s - %(cold)s::interval
               then 'cold'
             else 'warm' end
           where tier <> 'inactive'""",
        {"now": now, "hot": HOT_WINDOW, "cold": COLD_AFTER},
    )


def get_sweep_companies(
    conn: psycopg.Connection, *, ats: list[str], now: datetime, limit: int = 500
) -> list[Company]:
    rows = conn.execute(
        """select id, name, ats, slug, job_ids_hash, workday_host, workday_site from companies
           where ats = any(%(ats)s) and tier in ('warm', 'cold')
             and (tier = 'warm' or last_polled_at is null
                  or last_polled_at < %(now)s - %(repoll)s::interval)
           order by last_polled_at nulls first, id
           limit %(limit)s""",
        {"ats": ats, "now": now, "repoll": COLD_REPOLL, "limit": limit},
    ).fetchall()
    return [Company(**r) for r in rows]
