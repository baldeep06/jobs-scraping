from pathlib import Path

import pytest

from scraper.__main__ import load_seeds, main

ROOT = Path(__file__).resolve().parents[2]


def test_seed_file_is_valid():
    seeds = load_seeds(ROOT / "data" / "companies.seed.yml")
    assert len(seeds) >= 20
    assert {s["ats"] for s in seeds} <= {"greenhouse", "lever", "ashby"}
    keys = [(s["ats"], s["slug"]) for s in seeds]
    assert len(keys) == len(set(keys))


def test_load_seeds_rejects_bad_entries(tmp_path):
    bad = tmp_path / "seed.yml"
    bad.write_text("- name: X\n  ats: taleo\n  slug: x\n")
    with pytest.raises(ValueError, match="taleo"):
        load_seeds(bad)


def test_run_requires_database_url_unless_offline_dry_run(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        main(["run", "--tier", "hot"])
