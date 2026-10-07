import os
from pathlib import Path

import pytest

from scraper import db

SHIM = Path(__file__).parent / "sql" / "supabase_shim.sql"


@pytest.fixture
def conn():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")
    if "supabase" in dsn:
        pytest.fail("TEST_DATABASE_URL points at Supabase; tests drop the public schema")
    c = db.connect(dsn)
    c.execute("drop schema if exists public cascade")
    c.execute("create schema public")
    c.execute(SHIM.read_text())
    db.migrate(c)
    yield c
    c.close()
