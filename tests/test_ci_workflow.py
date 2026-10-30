""".github/workflows/ci.yml: the slow checks have a job of their own, every published benchmark number is
replayed with a gate at that number, coverage has floors, the weekly run checks the rules' age and the
real Claude Code's flags, and a real Tesseract is installed only where a test needs it (ADR 0024)."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from ordnung.doctor import native_install, tesseract_install
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


def test_the_ask_benchmark_gates_the_household_group_at_its_recorded_number() -> None:
    """The Ask benchmark's household group (whose a number is) is gated at the share its newest recording
    measured, as each reading split is: a change that loses one of its answers fails the build. The headline
    thresholds hold for that recording too (its notes say why each is where it is)."""
    (line,) = [line for line in _script(_jobs()["backend-slow"]).splitlines() if "-m evals.ask" in line]
    args = shlex.split(line.split("-m evals.ask", 1)[1])
    option = {name: args[args.index(name) + 1] for name in args if name.startswith(("--min-", "--max-"))}
    latest = sorted((ROOT / "evals" / "results").glob("*-ask.json"))[-1]
    summary = json.loads(latest.read_text(encoding="utf-8"))["summary"]
    right, asked = summary["household"]["attribution"]["k"], summary["household"]["attribution"]["n"]
    assert (right - 1) / asked < float(option["--min-household"]) <= right / asked
    assert float(option["--min-accuracy"]) <= summary["accuracy"]["value"]
    assert float(option["--min-abstention"]) <= summary["abstention"]["value"]
    assert int(option["--max-unsupported"]) == 0 == summary["guard"]["unsupported_in_final"]


def test_the_ask_benchmark_gates_strict_correctness_and_harm_at_their_recorded_numbers() -> None:
    """The strict scores of the newest Ask file (schema 2, the re-scoring of E2's recording) are gated at the values
    it measured, as the household group is: one more strictly wrong answer, or one more harmful answer (a date still
    open called passed, a later date or a wrong amount given as Ordnung's), fails the build. Never a gate the
    published numbers fail."""
    (line,) = [line for line in _script(_jobs()["backend-slow"]).splitlines() if "-m evals.ask" in line]
    args = shlex.split(line.split("-m evals.ask", 1)[1])
    option = {name: args[args.index(name) + 1] for name in args if name.startswith(("--min-", "--max-"))}
    latest = sorted((ROOT / "evals" / "results").glob("*-ask.json"))[-1]
    data = json.loads(latest.read_text(encoding="utf-8"))
    assert data["schema"] == 2
    summary = data["summary"]
    right, asked = summary["strict_accuracy"]["k"], summary["strict_accuracy"]["n"]
    assert (right - 1) / asked < float(option["--min-strict-accuracy"]) <= right / asked
    assert int(option["--max-harmful"]) == len(summary["harmful_answers"]) == summary["harmful"]["k"]


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


def test_make_eval_reproduce_replays_every_published_number_in_the_slow_job() -> None:
    """One command reproduces every published number (plan EV4): every split, condition, Ask set, end-to-end,
    ablation and stress cell that exists replayed with no model call, the analysis and the presenter checked, all
    compared with ``evals/results/INDEX.json``. It runs in backend-slow beside the gates, which stay; like them it
    gets no ``claude`` and no secret (``evals/reproduce.py`` points any stray call at a path that doesn't exist)."""
    slow = _jobs()["backend-slow"]
    at, step = _step(slow, "make eval-reproduce")
    assert step["run"].strip() == "make eval-reproduce" and "env" not in step
    gates_at, _ = _step(slow, "--split holdout2")
    assert gates_at < at  # the gates say first what failed, then reproduce says everything that differs
    assert set(_gates(_script(slow))) == set(GATED_SPLITS)  # the gates stay
    workflow = json.dumps(slow)
    assert "secrets." not in workflow and "ANTHROPIC_API_KEY" not in workflow and "install.sh" not in workflow
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "eval-reproduce" in makefile.split(".PHONY:", 1)[1].splitlines()[0]
    recipe = makefile.split("\neval-reproduce:", 1)[1].split("\n\n", 1)[0]
    assert "$(PY) -m evals.reproduce --check" in recipe and "--live" not in recipe


def test_reproduce_holds_the_replays_to_the_gates_this_workflow_runs() -> None:
    """evals/reproduce.py reads the gates from this file (it shows them on its scoreboard and in INDEX.json), so the
    two can't disagree."""
    from evals import reproduce

    gates = reproduce.ci_gates(ROOT / ".github/workflows/ci.yml")
    parsed = _gates(_script(_jobs()["backend-slow"]))
    assert {
        name.split("/", 1)[1]: (gate["min_accuracy"], gate["max_dangerous_late"])
        for name, gate in gates.items()
        if name.startswith("benchmark/")
    } == parsed
    (ask,) = [
        step["run"] for step in _jobs()["backend-slow"]["steps"] if "-m evals.ask" in step.get("run", "")
    ]
    assert gates["ask/dev"]["args"] == shlex.split(ask.split("-m evals.ask", 1)[1])
    (without_land,) = [
        step for step in _jobs()["backend-slow"]["steps"] if "eval_without_land" in step.get("run", "")
    ]
    assert gates["without-land"] == {"published": Path(without_land["env"]["PUBLISHED"]).name}


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


#: test files whose subject differs per system and that the "Other systems" job runs on macOS and Windows
PER_SYSTEM_TESTS = (
    "tests/test_platform_smoke.py",  # the real lookups, the disk-encryption probe among them
    "tests/test_shortcut.py",  # the Mac bundle opened; the Windows link read back by the shell and opened
    "tests/test_encryption.py",  # no answer and no process on Windows; nothing in it depends on the system
    "tests/test_store_ledger_token.py",  # SQLite's data_version and TEMP triggers, in each system's own SQLite
    "tests/test_ocr.py",  # Tesseract's places, priority, private temp folder and kill per system; missing there
    "tests/test_doctor_pictures.py",  # "Not installed (optional)" with that system's install line
)


def test_the_other_systems_job_runs_the_tests_whose_subject_differs_per_system() -> None:
    (step,) = [step for step in _jobs()["other-systems"]["steps"] if "pytest" in step.get("run", "")]
    named = step["run"].replace("\\\n", " ").split()
    for name in PER_SYSTEM_TESTS:
        assert name in named, name


#: what installs Tesseract with its German language data (Ubuntu's ``tesseract-ocr`` brings English with it)
APT_TESSERACT = (
    "sudo apt-get update -q && sudo apt-get install -y -q --no-install-recommends "
    "tesseract-ocr tesseract-ocr-deu"
)


def _step(job: dict[str, Any], text: str) -> tuple[int, dict[str, Any]]:
    """The one step of ``job`` whose script holds ``text``, and where it is."""
    (found,) = [(index, step) for index, step in enumerate(job["steps"]) if text in step.get("run", "")]
    return found


def test_tesseract_is_installed_only_where_a_real_binary_test_needs_it() -> None:
    """Text in pictures (ADR 0024): Tesseract is an optional program, never a dependency. A real one, with German,
    is installed only in the backend's 3.12 leg (the real-binary tests, which must run there instead of skipping)
    and the end-to-end job (the real app reads a photo with OCR on). Every other job, the macOS and Windows runners
    among them, tests the missing-binary path."""
    jobs = _jobs()
    # the packages the doctor's Linux line names
    assert "sudo apt install tesseract-ocr tesseract-ocr-deu" in tesseract_install("linux")

    backend = jobs["backend"]
    at, install = _step(backend, "tesseract")
    assert install["run"].strip() == APT_TESSERACT and install["if"] == "matrix.python == '3.12'"
    tests_at, tests = _step(backend, 'pytest -m "not slow"')
    assert at < tests_at
    assert tests["env"]["ORDNUNG_REQUIRE_TESSERACT"] == "${{ matrix.python == '3.12' && '1' || '' }}"
    assert tests["env"]["ORDNUNG_REQUIRE_TESSERACT"] == tests["env"]["ORDNUNG_REQUIRE_SAMPLES"]

    e2e = jobs["e2e"]
    at, install = _step(e2e, "tesseract")
    assert install["run"].strip() == APT_TESSERACT and "if" not in install
    playwright_at, playwright = _step(e2e, "npm run e2e")
    assert at < playwright_at
    assert playwright["env"] == {"ORDNUNG_E2E_OCR": "on", "ORDNUNG_REQUIRE_TESSERACT": "1"}

    for name, job in jobs.items():
        if name not in ("backend", "e2e"):
            lines = _script(job).lower().splitlines()
            assert not [line for line in lines if "install" in line and "tesseract" in line], name
            assert "ORDNUNG_REQUIRE_TESSERACT" not in json.dumps(job), name
    for test in ("tests/test_ocr.py", "tests/test_doctor_pictures.py"):
        assert test in PER_SYSTEM_TESTS
    doctor_tests = (ROOT / "tests" / "test_doctor_pictures.py").read_text(encoding="utf-8")
    assert "ORDNUNG_REQUIRE_TESSERACT" in doctor_tests


def test_the_installed_wheels_doctor_finds_text_in_pictures_optional_on_other_systems() -> None:
    """Where Tesseract is missing (the macOS and Windows runners) the wheel's doctor shows *Text in pictures* as
    info: *Not installed (optional)*, never a warning that would say something is wrong. On Windows the *Disk
    encryption* row is info too (Ordnung can't check BitLocker there; the row says where to look). An info row
    never fails the doctor: only Claude's checks may, as before."""
    (step,) = [step for step in _jobs()["other-systems"]["steps"] if "run_doctor_sync" in step.get("run", "")]
    script = step["run"]
    assert 'check.id == "ocr"' in script and 'ocr.status == "info"' in script
    assert 'ocr.detail == "Not installed (optional)"' in script
    assert 'sys.platform == "win32"' in script and 'check.id == "disk_encryption"' in script
    assert 'disk.status == "info"' in script
    assert 'check.status == "fail"' in script and 'name.startswith("claude")' in script


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
