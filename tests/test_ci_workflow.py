""".github/workflows/ci.yml: the slow checks have a job of their own, every published benchmark number is
replayed with a gate at that number, coverage has floors, and the weekly run checks the rules' age and the
real Claude Code's flags."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from ordnung.doctor import native_install
from ordnung.llm.claude_cli import MIN_CLAUDE_VERSION, version_text
from test_docs_claims import WITHOUT_LAND

ROOT = Path(__file__).resolve().parents[1]
#: The splits whose numbers the README and docs/evals.md publish as replayed on the current code (holdout3 is
#: replayed letter by letter in tests/test_holdout3_replay.py).
GATED_SPLITS = ("test", "holdout", "holdout2", "dev")


def _jobs() -> dict[str, Any]:
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    return dict(workflow["jobs"])


def _script(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def _on_pull_requests(job: dict[str, Any]) -> bool:
    return job.get("if", "github.event_name != 'schedule'") == "github.event_name != 'schedule'"


def _weekly(job: dict[str, Any]) -> bool:
    return job.get("if") == "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"


def test_the_slow_checks_run_in_a_job_of_their_own_and_every_check_still_runs() -> None:
    """The 3.12 leg ran the suite with coverage, then the slow tests, the replays and ``demo --check``, in 36 of
    its 45 minutes: a slow runner could time it out. Each check that ran there still runs on pull requests."""
    jobs = _jobs()
    backend, slow = jobs["backend"], jobs["backend-slow"]
    assert _on_pull_requests(slow) and slow["runs-on"] == backend["runs-on"] == "ubuntu-24.04"
    assert slow["timeout-minutes"] <= 45 and backend["timeout-minutes"] == 45
    assert any(step.get("with", {}).get("python-version") == "3.12" for step in slow["steps"])
    for moved in (
        "pytest -m slow",
        "--cov=ordnung.rules",
        "ordnung eval",
        "evals.ask",
        "ordnung demo --check",
    ):
        assert moved in _script(slow) and moved not in _script(backend), moved
    for kept in ("ruff check", "ruff format --check", "mypy", 'pytest -m "not slow" --cov=ordnung'):
        assert kept in _script(backend), kept
    assert "--cov-fail-under=100" in _script(slow)  # the rules engine's gate
    assert set(jobs["e2e"]["needs"]) >= {"backend", "frontend"}


def _gates(script: str) -> dict[str, tuple[float, float]]:
    """Each ``ordnung eval`` gate in ``script``: its split's minimum accuracy and maximum dangerous-late rate."""
    gates = {}
    for line in script.splitlines():
        if "ordnung eval" not in line:
            continue
        args = shlex.split(line.split("ordnung eval", 1)[1])
        option = {
            name: args[args.index(name) + 1] for name in args if name.startswith("--") and name != "--quiet"
        }
        if "--split" in option:  # a held-out split: Ordnung alone, the cheap replay
            assert option["--conditions"] == "ordnung", line
        gates[option.get("--split", "test")] = (
            float(option["--min-accuracy"]),
            float(option["--max-dangerous-late"]),
        )
    return gates


def _published() -> dict[str, Any]:
    return json.loads((ROOT / "evals" / "results" / WITHOUT_LAND).read_text(encoding="utf-8"))


def test_every_published_split_is_replayed_with_a_gate_at_its_published_number() -> None:
    """A code change could quietly lower a held-out number: CI replays the recordings of each split whose
    number is published (no model call) and fails when Ordnung gets fewer dates right than the published
    replay, or any date dangerously late."""
    gates = _gates(_script(_jobs()["backend-slow"]))
    assert set(gates) == set(GATED_SPLITS)
    for split in GATED_SPLITS:
        published = _published()["splits"][split]["with_land"]
        right, letters = published["due_date_accuracy"]["k"], published["due_date_accuracy"]["n"]
        minimum, late = gates[split]
        assert (right - 1) / letters < minimum <= right / letters, (split, minimum, right, letters)
        assert late == 0 == published["dangerous_late_rate"]["k"], split


def _comparison(script: str) -> str:
    """The Python the without-Land step runs to compare its replay with the published file."""
    return script.split("<<'EOF'\n", 1)[1].split("\nEOF", 1)[0]


def test_the_without_land_replay_goes_to_a_temporary_folder_and_must_match_the_published_file(
    tmp_path: Path,
) -> None:
    (step,) = [
        step for step in _jobs()["backend-slow"]["steps"] if "eval_without_land" in step.get("run", "")
    ]
    assert step["env"]["PUBLISHED"] == f"evals/results/{WITHOUT_LAND}"
    run = step["run"]
    assert '--out "$RUNNER_TEMP/without-land"' in run and "--date" in run
    compare = _comparison(run)
    published = ROOT / step["env"]["PUBLISHED"]
    changed = _published()
    changed["splits"]["dev"]["without_land"]["due_date_accuracy"]["k"] -= 1
    other = tmp_path / WITHOUT_LAND
    other.write_text(json.dumps(changed), encoding="utf-8")
    for replayed, code in ((published, 0), (other, 1)):
        done = subprocess.run(
            [sys.executable, "-c", compare, str(published), str(replayed)], capture_output=True, text=True
        )
        assert done.returncode == code, done.stderr
    assert "dev" in done.stderr


def test_the_weekly_run_fails_once_the_rules_were_last_checked_more_than_ninety_days_ago() -> None:
    job = _jobs()["rules-age"]
    assert _weekly(job) and not job.get("continue-on-error")
    assert "python -m scripts.check_rules_age" in _script(job)


def test_the_weekly_run_installs_claude_code_as_the_readme_says_and_checks_its_flags() -> None:
    """Every call passes over a dozen Claude Code flags, and CI only ever ran a fake ``claude``. The weekly
    run installs the real one with Anthropic's installer (the newest, and the oldest Ordnung takes) and checks
    them without signing in; while the job is new a failure shows without failing the run."""
    job = _jobs()["claude-code"]
    assert _weekly(job) and job["continue-on-error"] is True
    assert job["strategy"]["matrix"]["claude"] == ["latest", version_text(MIN_CLAUDE_VERSION)]
    install = native_install("linux")
    assert f"`{install}`" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{install} -s ${{{{ matrix.claude }}}}" in _script(job)
    assert "python -m scripts.check_claude_flags" in _script(job)
    assert "ANTHROPIC_API_KEY" not in json.dumps(job) and "secrets." not in json.dumps(job)


def test_coverage_counts_branches_and_has_floors_for_the_whole_package_sync_and_phone() -> None:
    """Only the rules engine had a coverage gate: the main test step reported coverage but never failed on
    it. The floors read the coverage the test step measured, so they cost no second run."""
    coverage = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]
    assert coverage["run"]["branch"] is True
    assert 90 <= coverage["report"]["fail_under"] < 100
    script = _script(_jobs()["backend"])
    for package in ("sync", "phone"):
        (line,) = [line for line in script.splitlines() if f"--include='*/ordnung/{package}/*'" in line]
        floor = float(line.split("--fail-under=", 1)[1].split()[0])
        assert 80 <= floor < 100, package
