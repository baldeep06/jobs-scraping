from datetime import datetime
from typing import Any


def _table(title: str, rows: dict[str, int]) -> str:
    lines = [f"## {title}", "", "| | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows.items()]
    return "\n".join(lines)


def render(data: dict[str, Any], now: datetime) -> str:
    last = data["last_run"]
    last_line = (
        f"Last scrape: {last['workflow']} at {last['finished_at']:%Y-%m-%d %H:%M} UTC"
        if last
        else "Last scrape: none yet"
    )
    parts = [
        "# Intern Radar stats",
        f"Updated {now:%Y-%m-%d} (weekly by the maintenance workflow, which also keeps "
        f"GitHub from disabling the schedules). {last_line}",
        _table("Companies by tier", data["companies_by_tier"]),
        _table("Companies by ATS", data["companies_by_ats"]),
        _table("Open internships by country", data["open_jobs_by_country"]),
    ]
    return "\n\n".join(parts) + "\n"
