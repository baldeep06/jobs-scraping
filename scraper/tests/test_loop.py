from pathlib import Path

import pytest
import yaml

from scraper import __main__ as cli

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    """Fake time: sleeping advances it, and a cycle can cost time too."""

    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def run_loop(once, minutes=14, every=300, clock=None):
    clock = clock or Clock()
    code = cli.run_loop(once, minutes * 60, every, clock=clock.now, sleep=clock.sleep)
    return code, clock


def test_cycles_start_on_the_interval_until_the_deadline():
    starts = []
    clock = Clock()

    def once():
        starts.append(clock.now())
        return 0

    code, _ = run_loop(once, clock=clock)
    assert code == 0 and starts == [0, 300, 600]  # a cycle at 900 would start past 840
    assert clock.sleeps == [300, 300]


def test_a_slow_cycle_does_not_pile_up_sleep():
    clock = Clock()
    starts = []

    def once():
        starts.append(clock.now())
        clock.t += 400  # longer than the interval
        return 0

    run_loop(once, clock=clock)
    assert starts[:2] == [0, 400] and clock.sleeps[0] == 0


def test_a_crashing_cycle_does_not_end_the_loop(capsys):
    calls = []

    def once():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 0

    code, _ = run_loop(once)
    assert code == 0 and len(calls) == 3
    assert "RuntimeError" in capsys.readouterr().out


def test_a_cycle_exiting_with_a_message_is_survived_and_printed(capsys):
    calls = []

    def once():
        calls.append(1)
        if len(calls) == 1:
            raise SystemExit("could not connect to the database (OperationalError)")
        return 0

    code, _ = run_loop(once)
    assert code == 0 and len(calls) == 3
    assert "could not connect" in capsys.readouterr().out


def test_exit_code_is_failure_only_if_every_cycle_failed():
    code, _ = run_loop(lambda: 1)
    assert code == 1


def test_missing_database_url_fails_fast_without_looping(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        cli.main(["run", "--tier", "hot", "--loop-minutes", "5"])


@pytest.mark.parametrize(
    ("name", "args", "every"),
    [("scrape-hot", "--tier hot", 300), ("scrape-sweep", "--sweep", 1800)],
)
def test_workflows_loop_and_start_their_successor(name, args, every):
    wf = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())
    assert wf["permissions"]["actions"] == "write"
    steps = wf["jobs"][next(iter(wf["jobs"]))]["steps"]
    run_step = next(s for s in steps if args in s.get("run", ""))
    assert f"--every-seconds {every}" in run_step["run"] and "--loop-minutes" in run_step["run"]
    nxt = steps[-1]
    assert f"gh workflow run {name}.yml" in nxt["run"] and nxt["if"] == "success()"
    assert nxt["env"]["GH_TOKEN"] == "${{ github.token }}"
