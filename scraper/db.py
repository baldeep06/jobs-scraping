from pathlib import Path

import psycopg
from psycopg.rows import dict_row

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


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
