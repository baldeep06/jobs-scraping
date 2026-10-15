"""Company groups (FAANG+, quant, unicorn, ...) shown as toggles on the site."""

from pathlib import Path
from typing import Any

import psycopg
import yaml

ROOT = Path(__file__).resolve().parents[1]
GROUPS_FILE = ROOT / "data" / "company_groups.yml"

GROUPS = (
    "faang",
    "big_tech",
    "big_tech_adjacent",
    "quant",
    "unicorn",
    "ai_labs",
    "fintech",
    "defense_hardware",
    "canadian",
)


def load_groups(path: Path = GROUPS_FILE) -> dict[str, list[str]]:
    """Read `group: [company names]` and invert it to `lower-cased name -> [groups]`."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    out: dict[str, list[str]] = {}
    for group, names in raw.items():
        if group not in GROUPS:
            raise ValueError(f"unknown company group {group!r} (known: {', '.join(GROUPS)})")
        for name in names or []:
            out.setdefault(str(name).lower(), []).append(group)
    return out


def apply_groups(conn: psycopg.Connection, mapping: dict[str, list[str]]) -> int:
    """Replace every company's groups from `mapping` (name match is case-insensitive).
    Returns how many companies ended up with at least one group."""
    with conn.transaction():
        conn.execute("update companies set groups = '{}' where groups <> '{}'")
        for name, groups in mapping.items():
            conn.execute("update companies set groups = %s where lower(name) = %s", (groups, name))
        row = conn.execute("select count(*) as n from companies where groups <> '{}'").fetchone()
    return row["n"]
