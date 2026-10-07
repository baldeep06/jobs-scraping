from pathlib import Path

import pytest

from scraper.__main__ import load_seeds, main

ROOT = Path(__file__).resolve().parents[2]


def test_seed_file_is_valid():
    seeds = load_seeds(ROOT / "data" / "companies.seed.yml")
    assert len(seeds) >= 20
    assert {s["ats"] for s in seeds} <= {
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "smartrecruiters",
        "workable",
    }
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


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user:Sup3r%Secret@localhost:1/db",  # bad percent-encoding
        "postgresql://user:Sup3rSecret@127.0.0.1:1/db",  # unreachable
    ],
)
def test_connection_errors_never_print_the_password(monkeypatch, capsys, dsn):
    monkeypatch.setenv("DATABASE_URL", dsn)
    with pytest.raises(SystemExit) as exc:
        main(["run", "--tier", "hot"])
    out = capsys.readouterr()
    shown = f"{exc.value} {out.out} {out.err}"
    assert "Sup3r" not in shown and "Secret" not in shown
    assert "DATABASE_URL" in str(exc.value)


def test_workday_seed_needs_host_and_site(tmp_path):
    bad = tmp_path / "seed.yml"
    bad.write_text("- {name: X, ats: workday, slug: x/y}\n")
    with pytest.raises(ValueError, match="workday"):
        load_seeds(bad)


def test_seed_verify_passes_workday_host_and_site(monkeypatch, tmp_path):
    from scraper import __main__ as cli

    seed = tmp_path / "seed.yml"
    seed.write_text(
        "- {name: A, ats: workday, slug: a/S, workday_host: a.wd5.myworkdayjobs.com, workday_site: S}\n"
    )
    seen = []

    async def fake_poll_all(companies):
        seen.extend(companies)
        return []

    monkeypatch.setattr(cli, "_poll_all", fake_poll_all)
    cli.main(["seed", str(seed), "--verify"])
    assert (seen[0].workday_host, seen[0].workday_site) == ("a.wd5.myworkdayjobs.com", "S")
