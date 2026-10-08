from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import yaml

REGION_COUNTRIES = {"US": ["US", "BOTH", "UNKNOWN"], "CA": ["CA", "BOTH", "UNKNOWN"]}
FRESH = ("fresh", "recurring")


@dataclass(frozen=True)
class DigestConfig:
    categories: list[str]
    hide_blocked: bool
    fresh_only: bool
    min_hourly_pay: float | None


@dataclass
class Region:
    top: list[dict[str, Any]] = field(default_factory=list)
    rest: list[dict[str, Any]] = field(default_factory=list)


def load_config(path: Path) -> DigestConfig:
    raw = yaml.safe_load(path.read_text()) or {}
    pay = raw.get("min_hourly_pay")
    return DigestConfig(
        categories=list(raw.get("categories") or []),
        hide_blocked=bool(raw.get("hide_blocked", True)),
        fresh_only=bool(raw.get("fresh_only", True)),
        min_hourly_pay=float(pay) if pay is not None else None,
    )


def _pay_text(row: dict[str, Any]) -> str:
    if row["pay_hourly_max"] is None:
        return ""
    lo, hi, cur = row["pay_hourly_min"], row["pay_hourly_max"], row["pay_currency"] or ""
    span = f"{lo:g}-{hi:g}" if lo is not None and lo != hi else f"{hi:g}"
    return f"{cur} {span}/h".strip()


def select_jobs(conn: psycopg.Connection, since: datetime, cfg: DigestConfig) -> dict[str, Region]:
    rows = conn.execute(
        """select j.title, j.category, j.country, j.location_raw, j.term, j.visa_status,
                  j.freshness, j.best_url, j.pay_hourly_min, j.pay_hourly_max, j.pay_currency,
                  c.name as company
           from jobs j join companies c on c.id = j.company_id
           where j.status = 'open' and j.first_seen_at >= %(since)s
             and j.category = any(%(cats)s)
             and (not %(hide)s or j.visa_status <> 'blocked')
             and (not %(fresh)s or j.freshness = any(%(fresh_values)s))
             and (%(min_pay)s::numeric is null or j.pay_hourly_max >= %(min_pay)s)
           order by j.first_seen_at desc""",
        {
            "since": since,
            "cats": cfg.categories,
            "hide": cfg.hide_blocked,
            "fresh": cfg.fresh_only,
            "fresh_values": list(FRESH),
            "min_pay": cfg.min_hourly_pay,
        },
    ).fetchall()
    out = {code: Region() for code in REGION_COUNTRIES}
    for r in rows:
        job = {
            "company": r["company"], "title": r["title"], "category": r["category"],
            "location": r["location_raw"], "term": r["term"], "pay": _pay_text(r),
            "visa_status": r["visa_status"], "freshness": r["freshness"], "url": r["best_url"],
        }  # fmt: skip
        for code, countries in REGION_COUNTRIES.items():
            if r["country"] in countries:
                pick = (
                    (r["visa_status"] == "open" or code == "CA")
                    and r["pay_hourly_max"] is not None
                    and r["freshness"] in FRESH
                )
                (out[code].top if pick else out[code].rest).append(job)
    return out
