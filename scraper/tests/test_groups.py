from pathlib import Path

import pytest

from scraper.groups import GROUPS, apply_groups, load_groups

ROOT = Path(__file__).resolve().parents[2]


def test_group_file_only_uses_known_groups():
    mapping = load_groups(ROOT / "data" / "company_groups.yml")
    assert mapping
    assert {g for gs in mapping.values() for g in gs} <= set(GROUPS)


def test_load_groups_rejects_unknown_group(tmp_path):
    f = tmp_path / "g.yml"
    f.write_text("faang: [Google]\nmegacorp: [Acme]\n")
    with pytest.raises(ValueError, match="megacorp"):
        load_groups(f)


def test_load_groups_inverts_to_company_lists_case_insensitively(tmp_path):
    f = tmp_path / "g.yml"
    f.write_text("faang: [Google, Meta]\nai_labs: [google]\n")
    assert load_groups(f) == {"google": ["faang", "ai_labs"], "meta": ["faang"]}


def _add(conn, name, slug):
    conn.execute(
        "insert into companies (name, ats, slug) values (%s, 'greenhouse', %s)", (name, slug)
    )


def test_apply_groups_sets_by_name_and_replaces_old_values(conn):
    _add(conn, "Jane Street", "js")
    _add(conn, "Acme", "acme")
    conn.execute("update companies set groups = '{unicorn}' where slug = 'acme'")
    n = apply_groups(conn, {"jane street": ["quant"]})
    rows = {r["slug"]: r["groups"] for r in conn.execute("select slug, groups from companies")}
    assert rows == {"js": ["quant"], "acme": []}
    assert n == 1


def test_feed_exposes_company_groups(conn):
    _add(conn, "Jane Street", "js")
    apply_groups(conn, {"jane street": ["quant"]})
    conn.execute(
        """insert into jobs (company_id, title, normalized_title, category, country,
                             visa_status, fingerprint, best_url)
           select id, 'Intern', 'intern', 'SWE', 'US', 'open', 'fp', 'https://x' from companies"""
    )
    assert conn.execute("select company_groups from jobs_feed").fetchone()["company_groups"] == [
        "quant"
    ]


def test_groups_command_applies_the_file(conn, monkeypatch, tmp_path, capsys):
    from scraper import __main__ as cli

    _add(conn, "Jane Street", "js")
    f = tmp_path / "g.yml"
    f.write_text("quant: [Jane Street]\n")
    monkeypatch.setattr(cli, "_connect", lambda: conn)
    assert cli.main(["groups", "--file", str(f)]) == 0
    assert conn.execute("select groups from companies").fetchone()["groups"] == ["quant"]
    assert "1 companies" in capsys.readouterr().out
