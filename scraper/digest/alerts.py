"""Priority alerts: an email minutes after a new SWE internship appears at a big name.

Each scrape pass calls send_due() after writing its jobs. Jobs are claimed with one atomic
UPDATE (so two lanes finishing together never email the same job), then sent; a failed send
releases them for the next pass.
"""

import html as htmllib
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import psycopg

from scraper.digest.select import FRESH, safe_url
from scraper.digest.send import SendError, send_email

PRIORITY_GROUPS = ("faang", "big_tech", "big_tech_adjacent", "unicorn", "ai_labs")
CATEGORIES = ("SWE",)
WINDOW = "6 hours"  # only jobs first seen this recently: never the backlog
MAX_PER_HOUR = 20  # a company posting 50 roles at once still means a few emails, not 50


def claim(conn: psycopg.Connection, now: datetime) -> list[dict[str, Any]]:
    """Mark and return the jobs due an alert. Visa-blocked jobs are skipped unless the job can
    be in Canada (blocked there usually means "no US sponsorship")."""
    return conn.execute(
        """with sent as (
             select count(*) as n from jobs where alerted_at > %(now)s - interval '1 hour'
           ), due as (
             select j.id from jobs j join companies c on c.id = j.company_id
             where j.status = 'open' and j.alerted_at is null
               and j.first_seen_at >= %(now)s - %(window)s::interval
               and j.category = any(%(cats)s) and j.freshness = any(%(fresh)s)
               and c.groups && %(groups)s::text[]
               and (j.visa_status <> 'blocked' or j.country in ('CA', 'BOTH'))
             order by j.first_seen_at
             limit greatest(%(cap)s - (select n from sent), 0)
             for update of j skip locked
           )
           update jobs j set alerted_at = %(now)s
           from due, companies c
           where j.id = due.id and c.id = j.company_id
           returning j.id, j.title, j.location_raw, j.term, j.country, j.best_url,
                     j.pay_hourly_min, j.pay_hourly_max, j.pay_currency, c.name as company""",
        {
            "now": now,
            "window": WINDOW,
            "cats": list(CATEGORIES),
            "fresh": list(FRESH),
            "groups": list(PRIORITY_GROUPS),
            "cap": MAX_PER_HOUR,
        },
    ).fetchall()


def release(conn: psycopg.Connection, ids: list[Any]) -> None:
    conn.execute("update jobs set alerted_at = null where id = any(%s)", (ids,))


def _pay(row: Mapping[str, Any]) -> str:
    if row.get("pay") is not None:
        return str(row["pay"])
    hi = row.get("pay_hourly_max")
    if hi is None:
        return ""
    lo, cur = row.get("pay_hourly_min"), row.get("pay_currency") or ""
    span = f"{lo:g}-{hi:g}" if lo is not None and lo != hi else f"{hi:g}"
    return f"{cur} {span}/h".strip()


def render(rows: list[Mapping[str, Any]]) -> tuple[str, str, str]:
    if len(rows) == 1:
        subject = f"🔔 {rows[0]['company']}: {rows[0]['title']}"
    else:
        names = list(dict.fromkeys(r["company"] for r in rows))
        shown = ", ".join(names[:4]) + (", …" if len(names) > 4 else "")
        subject = f"🔔 {len(rows)} new priority SWE internships: {shown}"
    items, lines = [], []
    for r in rows:
        url = safe_url(r.get("url") or r.get("best_url"))
        details = " · ".join(x for x in (r.get("location_raw"), r.get("term"), _pay(r)) if x)
        title = htmllib.escape(f"{r['company']} — {r['title']}")
        link = f'<a href="{htmllib.escape(url)}">{title}</a>' if url else title
        items.append(
            f"<li style='margin:0 0 12px'>{link}<br><small>{htmllib.escape(details)}</small></li>"
        )
        lines.append(f"{r['company']} — {r['title']}\n  {details}\n  {url}".rstrip())
    html = (
        "<div style='font-family:system-ui,sans-serif;font-size:14px'>"
        "<p>New priority SWE internship" + ("s" if len(rows) > 1 else "") + ":</p>"
        f"<ul style='padding-left:18px'>{''.join(items)}</ul>"
        "<p style='color:#666'>Intern Radar priority alert</p></div>"
    )
    return subject, html, "\n\n".join(lines)


def send_due(
    conn: psycopg.Connection,
    env: Mapping[str, str],
    now: datetime,
    send: Callable[..., None] = send_email,
) -> int:
    """Email the due alerts; returns how many jobs it covered. Without email settings it does
    nothing (so a fork or a local run never claims jobs it cannot send)."""
    if not env.get("DIGEST_TO") or not (
        env.get("RESEND_API_KEY") or env.get("DIGEST_TRANSPORT") == "smtp"
    ):
        return 0
    rows = claim(conn, now)
    if not rows:
        return 0
    subject, html, text = render(rows)
    try:
        send(subject, html, text, env)
    except SendError as e:
        release(conn, [r["id"] for r in rows])
        print(f"priority alert not sent: {e}")
        return 0
    return len(rows)
