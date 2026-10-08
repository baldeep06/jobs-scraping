from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scraper.digest.select import Region

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def health_line(health: list[dict[str, Any]]) -> str:
    bad = [h["workflow"] for h in health if h["degraded"]]
    return f"Degraded sources: {', '.join(bad)}" if bad else "All sources healthy."


def render(
    regions: dict[str, Region], health: list[dict[str, Any]], now: datetime
) -> tuple[str, str, str]:
    counts = {code: len(r.top) + len(r.rest) for code, r in regions.items()}
    total = len({j["url"] for r in regions.values() for j in r.top + r.rest})
    subject = (
        f"Intern Radar — {total} new internships ({counts['US']} US · {counts['CA']} CA)"
        if total
        else "Intern Radar — no new internships today"
    )
    line = health_line(health)
    html = _env.get_template("digest.html.j2").render(
        regions=regions, total=total, date=f"{now:%A %B %d}", health_line=line
    )
    lines = [subject, ""]
    for code, label in (("US", "United States"), ("CA", "Canada")):
        jobs = regions[code].top + regions[code].rest
        if jobs:
            lines.append(label.upper())
            lines += [
                f"- {j['company']} · {j['title']} · {j['location']} · {j['pay'] or 'pay n/a'}"
                f" · visa {j['visa_status']}\n  {j['url']}"
                for j in jobs
            ]
            lines.append("")
    if not total:
        lines.append("No new internships matched today.")
    lines.append(line)
    return subject, html, "\n".join(lines) + "\n"
