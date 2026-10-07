import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import yaml

from scraper import db
from scraper.adapters import ADAPTERS
from scraper.discovery import discover
from scraper.http import Fetcher
from scraper.models import Company, CompanyOutcome
from scraper.pipeline import poll

DEFAULT_SEED = Path("data/companies.seed.yml")


def load_seeds(path: Path) -> list[dict[str, Any]]:
    seeds = yaml.safe_load(path.read_text()) or []
    for s in seeds:
        if s.get("ats") not in ADAPTERS or not s.get("slug") or not s.get("name"):
            raise ValueError(f"bad seed entry (ats={s.get('ats')}): {s}")
        if s["ats"] == "workday" and not (s.get("workday_host") and s.get("workday_site")):
            raise ValueError(f"workday seed needs workday_host and workday_site: {s}")
    return seeds


def _connect() -> psycopg.Connection:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")
    try:
        return db.connect(dsn)
    except (psycopg.Error, ValueError) as e:
        # Never echo the message: psycopg can quote parts of the URL, including the password,
        # and Actions logs are public. GitHub only masks the exact secret, not fragments.
        raise SystemExit(
            f"could not connect to the database ({type(e).__name__}); check DATABASE_URL"
        ) from None


async def _poll_all(companies: list[Company]) -> list[CompanyOutcome]:
    async with Fetcher() as fetcher:
        return await asyncio.gather(*(poll(fetcher, c) for c in companies))


def _print_outcomes(outcomes: list[CompanyOutcome]) -> None:
    for o in outcomes:
        c = o.company
        if not o.ok:
            print(f"✗ {c.ats}/{c.slug}: {o.error}")
            continue
        print(
            f"✓ {c.ats}/{c.slug}: {len(o.seen_ids)} postings, {len(o.jobs)} CA/US tech internships"
        )
        for j in o.jobs:
            pay = f"{j.pay.currency} {j.pay.hourly_min:g}-{j.pay.hourly_max:g}/h" if j.pay else "-"
            print(
                f"    [{j.location.country}] {j.raw.title} | {j.raw.location_raw} | {j.term or '-'}"
                f" | {pay} | visa={j.visa_status} {j.visa_signals} | {j.flags}"
            )


def cmd_migrate(_: argparse.Namespace) -> int:
    applied = db.migrate(_connect())
    print(f"applied: {applied or 'nothing (up to date)'}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    seeds = load_seeds(args.path)
    if args.verify:
        companies = [Company(id=0, name=s["name"], ats=s["ats"], slug=s["slug"]) for s in seeds]
        outcomes = asyncio.run(_poll_all(companies))
        _print_outcomes(outcomes)
        failed = [o.company.slug for o in outcomes if not o.ok]
        print(f"\n{len(seeds) - len(failed)}/{len(seeds)} boards OK. Failed: {failed or 'none'}")
        return 1 if failed else 0
    print(f"upserted {db.upsert_companies(_connect(), seeds)} companies")
    return 0


def cmd_discover(_: argparse.Namespace) -> int:
    async def go(conn: psycopg.Connection) -> int:
        async with Fetcher() as fetcher:
            return await discover(fetcher, conn)

    print(f"discovered {asyncio.run(go(_connect()))} new companies")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    started = datetime.now(UTC)
    if args.dry_run and args.company and args.ats:
        company = Company(id=0, name=args.company, ats=args.ats, slug=args.company)
        _print_outcomes(asyncio.run(_poll_all([company])))
        return 0

    conn = _connect()
    companies = db.get_companies(
        conn,
        ats=[args.ats] if args.ats else list(ADAPTERS),
        tier=args.tier,
        slug=args.company,
        limit=args.limit,
    )
    outcomes = asyncio.run(_poll_all(companies))
    if args.dry_run:
        _print_outcomes(outcomes)
        return 0

    new = closed = seen = 0
    errors: list[dict[str, Any]] = []
    for o in outcomes:
        try:
            stats = db.ingest(conn, o, datetime.now(UTC))
        except Exception as e:  # one bad company must not stop the run
            errors.append({"company": o.company.slug, "error": f"ingest {type(e).__name__}: {e}"})
            continue
        new, closed, seen = new + stats.new, closed + stats.closed, seen + stats.seen
        if not o.ok:
            errors.append({"company": o.company.slug, "error": o.error})

    db.record_run(
        conn,
        workflow=f"scrape-{args.tier or 'manual'}",
        source="ats",
        started_at=started,
        finished_at=datetime.now(UTC),
        companies_polled=len(outcomes),
        jobs_seen=seen,
        jobs_new=new,
        jobs_closed=closed,
        errors=len(errors),
        error_samples=errors,
    )
    print(f"polled={len(outcomes)} seen={seen} new={new} closed={closed} errors={len(errors)}")
    for e in errors[:10]:
        print(f"  ✗ {e['company']}: {e['error']}")
    # Fail the workflow only when everything failed (systemic problem, e.g. DB or network down).
    return 1 if outcomes and len(errors) == len(outcomes) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="apply supabase/migrations to DATABASE_URL")

    seed = sub.add_parser("seed", help="upsert companies from a seed file")
    seed.add_argument("path", nargs="?", type=Path, default=DEFAULT_SEED)
    seed.add_argument("--verify", action="store_true", help="only check each board responds")

    sub.add_parser("discover", help="add companies found in the Simplify lists")

    run = sub.add_parser("run", help="poll companies and write jobs")
    run.add_argument("--tier", choices=["hot", "warm", "cold"])
    run.add_argument("--company", help="only this slug")
    run.add_argument("--ats", choices=sorted(ADAPTERS))
    run.add_argument("--limit", type=int, default=1000)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="print instead of writing; with --company and --ats needs no database",
    )

    args = parser.parse_args(argv)
    handlers = {"migrate": cmd_migrate, "seed": cmd_seed, "run": cmd_run, "discover": cmd_discover}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
