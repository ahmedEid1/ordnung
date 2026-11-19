""".github/workflows/ci.yml: lint and types run once, coverage on one backend leg, the slow tests and the replays
each in a job of their own, the end-to-end groups beside the backend's legs, a push to main never cuts off a
running run, macOS and Windows must pass, every published benchmark number is replayed with a gate at that
number, coverage has floors, the weekly run checks the rules' age and the real Claude Code's flags, a real
Tesseract is installed only where a test needs it (ADR 0024), and each job that runs the pre-registration's tests
checks out the whole history."""

from __future__ import annotations

import ast
import functools
import json
import re
import shlex
import subprocess
import sys
import tomllib
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import pytest
from evals.present.build import HISTORY_INPUTS

from helpers_tables import check_rows
from ordnung.doctor import native_install, tesseract_install
from ordnung.llm.claude_cli import MIN_CLAUDE_VERSION, version_text
from test_final_gates import FINAL, workflow_gates

ROOT = Path(__file__).resolve().parents[1]
#: The splits whose numbers the README and docs/evals.md publish as replayed on the current code (holdout3 is
#: replayed letter by letter in tests/test_holdout3_replay.py).
GATED_SPLITS = ("test", "holdout", "holdout2", "dev")
#: The published without-Land results file: the report's input, which tests/test_docs_claims.py holds to be the
#: file the docs cite.
WITHOUT_LAND = HISTORY_INPUTS["without_land"]
assert isinstance(WITHOUT_LAND, str)


@functools.cache
def _parsed_workflow() -> dict[Any, Any]:
    """ci.yml parsed once for the module: every test only reads it."""
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    return dict(yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")))


def _workflow() -> dict[Any, Any]:
    return dict(_parsed_workflow())


def _jobs() -> dict[str, Any]:
    return dict(_workflow()["jobs"])


def _script(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def _on_pull_requests(job: dict[str, Any]) -> bool:
    return job.get("if", "github.event_name != 'schedule'") == "github.event_name != 'schedule'"


def _weekly(job: dict[str, Any]) -> bool:
    return job.get("if") == "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"


def test_each_check_runs_on_pull_requests_in_a_job_of_its_own() -> None:
    """A run's time is its longest job's. The slow tests and the replays took a backend leg to 36 of its 45
    minutes; in a job of their own (``backend-slow``) they took 27 to 41 (November 2026), the slow tests alone 21
    of them, and ``make eval-reproduce`` took 6 of the replays' 12 to 13. So the slow tests, the gates' replays
    (with ``demo --check``), ``make eval-reproduce`` and lint with the type check (the same on every Python:
    pyproject.toml gives ruff and mypy 3.11 as their target) each have a job, all on pull requests, and every check
    still runs. The gates' replays keep the job id ``backend-slow``: evals/reproduce.py reads the gates from it."""
    jobs = _jobs()
    lint, backend, tests, replays = jobs["lint"], jobs["backend"], jobs["slow-tests"], jobs["backend-slow"]
    reproduce = jobs["reproduce"]
    assert all(_on_pull_requests(job) for job in (lint, backend, tests, replays, reproduce))
    assert {job["runs-on"] for job in (backend, tests, replays, reproduce)} == {"ubuntu-24.04"}
    for job in (lint, tests, replays, reproduce):
        assert any(step.get("with", {}).get("python-version") == "3.12" for step in job["steps"])
    where = {
        "ruff check": lint,
        "ruff format --check": lint,
        "mypy": lint,
        'pytest -m "not slow" -n auto --dist loadfile --cov=ordnung': backend,
        "pytest -m slow -n auto --dist loadfile": tests,
        "--cov=ordnung.rules": tests,
        "--cov-fail-under=100": tests,  # the rules engine's gate
        "ordnung eval": replays,
        "evals.ask": replays,
        "evals.present --check": replays,
        "make eval-reproduce": reproduce,
        "ordnung demo --check": replays,
    }
    for check, job in where.items():
        assert check in _script(job), check
        assert job is backend or check not in _script(backend), check  # once, not in each leg
    assert "pytest" not in _script(replays) and "pytest" not in _script(reproduce)


def test_the_samples_must_regenerate_byte_for_byte_in_the_job_that_runs_their_check() -> None:
    """The samples' byte-for-byte check (a slow test) skips where the libraries differ from the manifest's,
    unless ``ORDNUNG_REQUIRE_SAMPLES=1``: then it fails. The job that runs the slow tests installs the
    manifest's libraries (``-c constraints.txt`` on Ubuntu 24.04's Python 3.12) and sets it, so drifted
    libraries fail CI instead of passing it with the check skipped. No other job sets it."""
    check = "tests/test_samples.py::test_committed_samples_match_regeneration"
    samples = (ROOT / "tests" / "test_samples.py").read_text(encoding="utf-8")
    assert (
        "@pytest.mark.slow  # regenerates the samples\ndef test_committed_samples_match_regeneration("
        in samples
    )
    assert 'os.environ.get("ORDNUNG_REQUIRE_SAMPLES") == "1"' in samples
    jobs = _jobs()
    (runner,) = [name for name, job in jobs.items() if "pytest -m slow " in _script(job)]
    job = jobs[runner]
    assert job["env"]["ORDNUNG_REQUIRE_SAMPLES"] == "1", check
    assert job["runs-on"] == "ubuntu-24.04"
    assert any(step.get("with", {}).get("python-version") == "3.12" for step in job["steps"])
    assert "-c constraints.txt" in _script(job)
    for name, other in jobs.items():
        assert name == runner or "ORDNUNG_REQUIRE_SAMPLES" not in json.dumps(other), name
    # the samples regenerate byte for byte only with their manifest's libraries: CI installs with
    # ``-c constraints.txt``, which pins them
    manifest = json.loads((ROOT / "src/ordnung/demo/samples/manifest.json").read_text(encoding="utf-8"))
    constraints = (ROOT / "constraints.txt").read_text(encoding="utf-8")
    pins = dict(re.findall(r"^([\w.-]+)==([^\s;]+)", constraints, re.M))
    for name in ("fpdf2", "fonttools", "pillow", "pypdfium2"):
        assert pins[name] == manifest["generator"]["environment"][name], name
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert workflow.count('uv pip install -e ".[dev]" -c constraints.txt') >= 2


def _e2e_groups() -> list[str]:
    """The groups of Playwright's projects one end-to-end run can take (``E2E_GROUPS`` in web/e2e/env.ts)."""
    env_ts = (ROOT / "web" / "e2e" / "env.ts").read_text(encoding="utf-8")
    groups = env_ts.split("export const E2E_GROUPS", 1)[1].split("\n};", 1)[0]
    return re.findall(r'^  "?([\w-]+)"?: \[', groups, re.M)


def test_the_end_to_end_groups_start_at_once_and_together_run_every_project() -> None:
    """Each end-to-end leg installs its own Python, Node and Chromium and checks that the committed web build
    matches its sources: it uses nothing another job makes, so it waits for none (waiting for the frontend job put 8
    minutes before a 39-minute Playwright run, 18 Nov 2026; a stale build fails the leg's own check, and the
    frontend job's build proves the sources still build). Playwright drives the committed build, the one the wheel
    ships, never one the leg builds. Chromium comes as its headless shell, with no system packages (an apt mirror
    once hung the install and failed a run), cached under a key of its own. Its legs are the groups of
    web/e2e/env.ts, each once: a group left out here would never run in CI. Only the layout group, the longest, runs
    as two halves (Playwright's ``--shard``), and the two halves together are the whole group: every other group has
    one leg that runs all of it. The checks that need both toolchains run on one leg, not on each."""
    jobs = _jobs()
    e2e = jobs["e2e"]
    assert "needs" not in e2e and "download-artifact" not in json.dumps(e2e)
    assert _on_pull_requests(e2e) and _on_pull_requests(jobs["frontend"])
    matrix = e2e["strategy"]["matrix"]
    groups = matrix["group"]
    assert sorted(groups) == sorted(set(groups)) == sorted(_e2e_groups())
    assert set(matrix) == {"group", "shard", "exclude"} and matrix["shard"] == [1, 2]
    legs = [
        (group, shard)
        for group in groups
        for shard in matrix["shard"]
        if {"group": group, "shard": shard} not in matrix["exclude"]
    ]
    assert sorted(legs) == sorted([(group, 1) for group in groups] + [("layout", 2)])
    _, playwright = _step(e2e, "npm run e2e")
    assert playwright["env"]["E2E_GROUP"] == "${{ matrix.group }}"
    # a leg runs its shard of as many as its group has legs: 1/1 is the whole group, 1/2 and 2/2 the layout's
    assert playwright["run"] == (
        "cd web && npm run e2e -- --shard=${{ matrix.shard }}/${{ matrix.group == 'layout' && 2 || 1 }}"
    )
    assert "format(' {0}/2', matrix.shard)" in e2e["name"]
    (upload,) = [step for step in e2e["steps"] if "upload-artifact" in step.get("uses", "")]
    assert upload["with"]["name"] == "playwright-report-${{ matrix.group }}-${{ matrix.shard }}"
    (checks,) = [step for step in e2e["steps"] if "ORDNUNG_REQUIRE_MOCK_CHECK" in step.get("env", {})]
    assert checks["if"] == "matrix.group == 'real'"
    fresh_at, fresh = _step(e2e, "cd web && node scripts/source-hash.mjs --check")
    assert fresh["run"].endswith(" ../src/ordnung/web/dist/build-info.json")
    assert "npm run build" not in _script(e2e) and "npm run build" in _script(jobs["frontend"])
    assert fresh_at < _step(e2e, "npm run e2e")[0]
    _, browser = _step(e2e, "npx playwright install")
    assert browser["run"] == "cd web && npx playwright install --only-shell chromium"
    (cache,) = [step for step in e2e["steps"] if "ms-playwright" in step.get("with", {}).get("path", "")]
    assert cache["with"]["key"].startswith("playwright-shell-")


def test_only_a_pull_request_s_older_run_is_cancelled() -> None:
    """A newer push to a pull request cancels that pull request's older run. A push to main never cancels a run
    that is going on: release.yml releases a tag only when CI's push run on its commit passed, and a cancelled run
    never has (demo.yml follows the same rule). GitHub still keeps only one run waiting in the group, so a third
    merge replaces the second one's waiting run; docs/releasing.md says to re-run it before tagging, and the
    workflow's comment says so."""
    concurrency = _workflow()["concurrency"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    assert "github.ref" in concurrency["group"] and "github.event_name" in concurrency["group"]
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "ci.yml/runs?head_sha=$GITHUB_SHA&event=push&status=success" in release
    comment = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8").split("concurrency:", 1)[1]
    comment = " ".join(comment.split("cancel-in-progress:", 1)[0].replace("#", " ").split())
    assert (
        "replaces the second one's waiting run" in comment
        and "re-run a replaced run before tagging" in comment
    )
    releasing = " ".join((ROOT / "docs/releasing.md").read_text(encoding="utf-8").split())
    assert "cancelled because another merge followed, run it again" in releasing


def test_a_failure_on_macos_or_windows_fails_the_run() -> None:
    """The release gate counts a run as passed when its macOS or Windows job failed while that job may fail. It
    is required now, on every pull request as well; only the weekly check of Claude Code's flags, which installs
    whatever Anthropic released last, still shows a failure without failing the run. The guide says so, and neither
    it nor README says otherwise."""
    jobs = _jobs()
    assert "continue-on-error" not in jobs["other-systems"]
    assert [name for name, job in jobs.items() if "continue-on-error" in job] == ["claude-code"]
    # nor may a step of any other job: a step that may fail lets its job pass all the same
    steps = [
        (name, step) for name, job in jobs.items() if name != "claude-code" for step in job.get("steps", [])
    ]
    assert [f"{name}: {step.get('name')}" for name, step in steps if "continue-on-error" in step] == []
    comment = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8").split("  other-systems:", 1)[1]
    assert "without failing the run" not in comment.split("    steps:", 1)[0]
    guide = " ".join((ROOT / "docs/guide.md").read_text(encoding="utf-8").split())
    assert "(on every pull request, on main and weekly, required to pass)" in guide
    for name in ("README.md", "docs/guide.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "not yet required to pass" not in text and "Not yet a gate: weekly and on main" not in text, (
            name
        )


def test_a_hung_test_is_named_and_no_unread_coverage_report_is_written() -> None:
    """A test still running after 10 minutes gets every thread's stack printed (pytest's faulthandler), so a hang
    names its test long before a job's time limit ends the run without a word. No step writes coverage.xml,
    which nothing reads; the terminal report and the floors read the coverage data itself."""
    pytest_ini = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]
    timeout = pytest_ini["ini_options"]["faulthandler_timeout"]
    jobs = _jobs()
    assert (
        timeout == 600 < 60 * min(job["timeout-minutes"] for job in jobs.values() if "pytest" in _script(job))
    )
    for name, job in jobs.items():
        assert "--cov-report=xml" not in _script(job) and "coverage xml" not in _script(job), name
    assert "--cov-report=xml" not in (ROOT / "Makefile").read_text(encoding="utf-8")


def test_the_type_check_covers_the_scripts_each_under_one_name() -> None:
    """CI's type check (``mypy`` with pyproject.toml's list) covers scripts/ too: they write data the tests and the
    static demo pin (the sample life, the postcode table, the mock data). evals/ never imports scripts/, so every
    script is checked under its file name but scripts/prereg_hashes.py, which is checked as
    ``scripts.prereg_hashes``, the name scripts/prereg_published.py imports it by: listed as a file as well, mypy
    would find it under two names and stop before checking anything."""
    mypy = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]
    assert mypy["files"] == ["src/ordnung", "evals", "scripts"]
    assert mypy["exclude"] == [r"^scripts/prereg_hashes\.py$"]
    evals = ROOT / "evals"
    data = {"dataset", "recorded", "prompts", "results", "retakes"}
    from_scripts = []
    for path in sorted(evals.rglob("*.py")):
        parts = path.relative_to(evals).parts
        if data & set(parts[:-1]) or parts[:2] == ("ask", "heldout"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            from_scripts += [
                f"{path.relative_to(ROOT)}: {name}" for name in names if name.split(".")[0] == "scripts"
            ]
    assert from_scripts == [], "evals/ imports scripts/"
    published = (ROOT / "scripts" / "prereg_published.py").read_text(encoding="utf-8")
    assert re.search(r"^from scripts\.prereg_hashes import ", published, re.M)
    assert [step["run"] for step in _jobs()["lint"]["steps"] if "mypy" in step.get("run", "")] == [
        ".venv/bin/mypy"
    ]


def test_the_frontend_job_has_room_for_a_slow_runner() -> None:
    """The web job (npm ci, lint, typecheck, the full vitest run, the build check and the build) took 4.5 to 17
    minutes on hosted runners, and one slow runner was cancelled at 20 with vitest still passing tests: its limit
    must leave room for that, as the backend jobs' limits do."""
    frontend = _jobs()["frontend"]
    assert frontend["timeout-minutes"] >= 30
    assert "npm test" in _script(frontend)


def test_the_backend_legs_have_room_for_a_slow_runner() -> None:
    """The backend's legs on Python 3.11 to 3.14 run the tests in parallel processes, a file to each. Serial, the
    slowest leg's tests took 39 minutes with coverage (3.12, run 44310555051 of 18 November 2026), 26 without
    (3.11, the lowest versions' job); only 3.12 measures coverage now. A leg a slow runner cancels fails the push
    run on main, which release.yml needs passed before it tags: the limit leaves half as much again as the slowest
    leg, 39 minutes over 4 processes (what a hosted Linux runner has, at 3 times the speed: 4 processes ran the
    suite 4.1 times as fast as one on a 4-core computer) plus install and Tesseract. A hung test is still named
    after 10 minutes (faulthandler_timeout), long before it."""
    backend = _jobs()["backend"]
    slowest_leg = 39 / 3 + 3
    assert backend["timeout-minutes"] >= 1.5 * slowest_leg
    assert backend["strategy"]["matrix"]["python"] == ["3.11", "3.12", "3.13", "3.14"]
    assert "pytest" in _script(backend)


#: the tests that read the git history from the pre-registration's freeze commit on
PREREGISTRATION_TESTS = "tests/test_preregistration.py"
#: pytest's options whose value is the next argument (``-m "not slow"``, ``--deselect tests/x.py::y``,
#: ``--durations 20``)
_PYTEST_OPTION_VALUES = (
    "-m",
    "-k",
    "-p",
    "-c",
    "-n",
    "--dist",
    "-o",
    "-W",
    "--deselect",
    "--ignore",
    "--ignore-glob",
    "--rootdir",
    "--confcutdir",
    "--basetemp",
    "--durations",
    "--maxfail",
    "--tb",
    "--junitxml",
)


def _make_rules() -> dict[str, tuple[list[str], list[str]]]:
    """The Makefile's rules: each target's prerequisites and recipe lines."""
    rules: dict[str, tuple[list[str], list[str]]] = {}
    target = None
    for line in (ROOT / "Makefile").read_text(encoding="utf-8").splitlines():
        rule = re.match(r"([a-z][a-z0-9-]*):(?!=)([^#]*)", line)
        if rule:
            target = rule.group(1)
            rules[target] = (rule.group(2).split(), [])
        elif line.startswith("\t") and target is not None:
            rules[target][1].append(line[1:])
        elif line.strip():
            target = None
    return rules


def _script_runs(
    script: str, rules: dict[str, tuple[list[str], list[str]]], seen: set[str]
) -> list[list[str]]:
    runs = []
    for line in script.replace("\\\n", " ").splitlines():
        found = re.search(r"(?:^|[\s/])pytest(?=\s|$)", line)
        if found:
            runs.append(shlex.split(line[found.end() :]))
            continue
        make = re.search(r"(?:^|[\s;&|(])make\s+(.*)", line)
        for target in shlex.split(make.group(1)) if make else []:
            if target.startswith("-") or "=" in target or target in seen or target not in rules:
                continue
            seen.add(target)
            prerequisites, recipe = rules[target]
            runs += _script_runs("\n".join(f"make {name}" for name in prerequisites), rules, seen)
            runs += _script_runs("\n".join(recipe), rules, seen)
    return runs


def _pytest_runs(job: dict[str, Any]) -> list[list[str]]:
    """The arguments of each pytest run in ``job``'s steps (a line continued with a backslash read as one; a
    ``make <target>`` read as that target's recipe, its prerequisites' first)."""
    return _script_runs(_script(job), _make_rules(), set())


def _is_test_path(arg: str) -> bool:
    """Whether a pytest argument names tests (a file, a folder, a node id or a glob of them), not an option's value."""
    return arg in (".", "tests") or arg.startswith(("tests/", "./")) or "::" in arg or arg.endswith(".py")


def _can_run(args: list[str], test_file: str) -> bool:
    """Whether a pytest run with ``args`` can include ``test_file``: one that names no test path runs the whole
    suite, whatever its ``-m`` (the pre-registration's file has slow and not-slow tests); one that names paths runs
    what they match; an ``--ignore`` that matches leaves it out. An argument that names no test (an option's value,
    as in ``--durations 20``) is not read as a path."""
    paths, ignored = [], []
    rest = iter(args)
    for arg in rest:
        if arg in _PYTEST_OPTION_VALUES:
            value = next(rest, "")
            if arg.startswith("--ignore"):
                ignored.append(value)
        elif arg.startswith(("--ignore=", "--ignore-glob=")):
            ignored.append(arg.split("=", 1)[1])
        elif not arg.startswith("-") and _is_test_path(arg):
            paths.append(arg.split("::", 1)[0].removeprefix("./").rstrip("/"))
    if any(fnmatch(test_file, pattern) for pattern in ignored):
        return False
    return not paths or any(path in (".", "", "tests") or fnmatch(test_file, path) for path in paths)


PYTEST_RUNS = [
    ('-m "not slow" --cov=ordnung --cov-report=term-missing:skip-covered', True),
    ("-m slow", True),
    ('-m "not slow" --deselect tests/test_openapi_contract.py::test_web_openapi_json_is_current', True),
    ("-q tests", True),
    ("tests/test_pre*.py", True),
    ("tests/test_preregistration.py::test_every_required_field_is_there", True),
    ("tests/test_rules_*.py --cov=ordnung.rules --cov-branch", False),
    ("-q tests/test_mock_numbers.py tests/test_docs_claims.py::test_x", False),
    ('-m "not slow" --ignore=tests/test_preregistration.py', False),
    # an option's value is no test path, whether or not the option is known to take one
    ('-m "not slow" --durations 20', True),
    ("-m slow -n auto --dist loadfile --durations=15", True),
    ("-n 4 -q", True),
    ('-m "not slow" -n auto --dist loadfile', True),
    ("-W error -m slow", True),
    ("-m slow --junitxml reports/junit.xml", True),
    ("-o addopts= -q", True),
    ("--durations 20 tests/test_rules_dates.py", False),
    ("--durations=15 tests/test_rules_dates.py", False),
    ('-m "not slow" tests/test_platform_smoke.py tests/test_cli.py::test_x tests/test_sync_*.py', False),
]


def test_a_pytest_run_is_read_as_running_the_pre_registration_s_tests_or_not() -> None:
    def check(command: str, runs_it: bool) -> None:
        assert _can_run(shlex.split(command), PREREGISTRATION_TESTS) is runs_it

    check_rows(PYTEST_RUNS, check)


def test_a_make_target_s_pytest_runs_are_read_as_the_job_s() -> None:
    """A step that runs a Makefile target runs that target's recipe (and its prerequisites'): `make test` runs the
    whole suite twice (not slow, then slow), each in parallel processes that take whole files (a module's shared
    fixtures are built once), `make eval-reproduce` runs no pytest."""
    assert _pytest_runs({"steps": [{"run": "make test"}]}) == [
        shlex.split(
            '-m "not slow" -n auto --dist loadfile --cov=ordnung --cov-report=term-missing:skip-covered'
        ),
        shlex.split("-m slow -n auto --dist loadfile"),
    ]
    assert _pytest_runs({"steps": [{"run": "make eval-reproduce"}]}) == []
    assert any(
        _can_run(args, PREREGISTRATION_TESTS) for args in _pytest_runs({"steps": [{"run": "make test"}]})
    )


def test_every_job_that_runs_the_pre_registration_s_tests_checks_out_the_whole_history() -> None:
    """tests/test_preregistration.py reads the git history from the freeze commit on (the paths changed since, the
    files written once, each deviation recorded at the time). A clone without that commit skips those checks only
    until a final result is published, and fails them from then on: CI's clone must hold the history.
    actions/checkout fetches one commit unless ``fetch-depth: 0`` asks for all of them, so each job whose pytest run
    can include that file asks for all: the backend's legs, the slow checks and the lowest and newest versions (and
    any job that comes to run it). The macOS and Windows job and the end-to-end job name their tests, and it is not
    among them today; the parser's cases above hold that reading."""
    jobs = _jobs()
    history = {
        name
        for name, job in jobs.items()
        if any(_can_run(args, PREREGISTRATION_TESTS) for args in _pytest_runs(job))
    }
    assert {"backend", "slow-tests", "lowest", "latest"} <= history
    for name in sorted(history):
        (checkout,) = [
            step for step in jobs[name]["steps"] if step.get("uses", "").startswith("actions/checkout@")
        ]
        assert checkout.get("with", {}).get("fetch-depth") == 0, name


def _final_gate(line: str) -> bool:
    """Whether ``line`` is a gate of the final run (a replay of one of its reads: a final split's, or a held-out Ask
    run's), found as tests/test_final_gates.py finds them. That test, frozen with the pre-registration, holds each
    to its own read's replay and INDEX.json; the checks here are of every other gate."""
    return bool(workflow_gates({"jobs": {"backend-slow": {"steps": [{"run": line}]}}}))


def _gates(script: str) -> dict[str, tuple[float, float]]:
    """Each ``ordnung eval`` gate in ``script`` but the final run's: its split's minimum accuracy and maximum
    dangerous-late rate."""
    gates = {}
    for line in script.splitlines():
        if "ordnung eval" not in line or _final_gate(line):
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


def _ask_line() -> str:
    """The development set's Ask gate: the one ``-m evals.ask`` line of backend-slow that is not the final run's."""
    (line,) = [
        line
        for line in _script(_jobs()["backend-slow"]).splitlines()
        if "-m evals.ask" in line and not _final_gate(line)
    ]
    return line


def _newest_ask() -> Path:
    """The development set's newest Ask results file: a day's re-scoring (``-rescored``) after that day's live run."""
    from evals.ask.report import latest_results

    latest = latest_results(ROOT / "evals" / "results", "claude-sonnet-5")
    assert latest is not None
    return latest


def test_the_ask_benchmark_gates_each_score_at_its_recorded_number() -> None:
    """The Ask benchmark's household group (whose a number is) is gated at the share its newest recording
    measured, as each reading split is: a change that loses one of its answers fails the build. The headline
    thresholds hold for that recording too (its notes say why each is where it is). The strict scores of the newest
    Ask file (schema 2, the re-scoring of E2's recording) are gated at the values it measured too: one more strictly
    wrong answer, or one more harmful answer (a date still open called passed, a later date or a wrong amount given
    as Ordnung's), fails the build. Never a gate the published numbers fail."""
    args = shlex.split(_ask_line().split("-m evals.ask", 1)[1])
    option = {name: args[args.index(name) + 1] for name in args if name.startswith(("--min-", "--max-"))}
    latest = _newest_ask()
    data = json.loads(latest.read_text(encoding="utf-8"))
    summary = data["summary"]
    right, asked = summary["household"]["attribution"]["k"], summary["household"]["attribution"]["n"]
    assert (right - 1) / asked < float(option["--min-household"]) <= right / asked
    assert float(option["--min-accuracy"]) <= summary["accuracy"]["value"]
    assert float(option["--min-abstention"]) <= summary["abstention"]["value"]
    assert int(option["--max-unsupported"]) == 0 == summary["guard"]["unsupported_in_final"]
    assert data["schema"] == 2
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


def test_make_eval_reproduce_replays_every_published_number_in_a_job_of_its_own() -> None:
    """One command reproduces every published number: every split, condition, Ask set, end-to-end,
    ablation and stress cell that exists replayed with no model call, the analysis and the presenter checked, all
    compared with ``evals/results/INDEX.json``. It runs in a job of its own, beside backend-slow's gates, which
    stay; like them it gets no ``claude`` and no secret (``evals/reproduce.py`` points any stray call at a path that
    doesn't exist)."""
    jobs = _jobs()
    slow, reproduce = jobs["backend-slow"], jobs["reproduce"]
    assert reproduce["if"] == "github.event_name != 'schedule'"  # on pull requests and main, not weekly
    _, step = _step(reproduce, "make eval-reproduce")
    assert step["run"].strip() == "make eval-reproduce" and "env" not in step
    assert [name for name, job in jobs.items() if "make eval-reproduce" in _script(job)] == ["reproduce"]
    assert set(_gates(_script(slow))) == set(GATED_SPLITS)  # the gates stay
    workflow = json.dumps([slow, reproduce])
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
    # the final splits' gates are tests/test_final_gates.py's
    assert {
        name.split("/", 1)[1]: (gate["min_accuracy"], gate["max_dangerous_late"])
        for name, gate in gates.items()
        if name.startswith("benchmark/") and name.split("/")[1] not in FINAL
    } == parsed
    assert gates["ask/dev"]["args"] == shlex.split(_ask_line().split("-m evals.ask", 1)[1])
    (without_land,) = [
        step for step in _jobs()["backend-slow"]["steps"] if "eval_without_land" in step.get("run", "")
    ]
    assert gates["without-land"] == {"published": Path(without_land["env"]["PUBLISHED"]).name}


def test_the_weekly_run_fails_once_the_rules_were_last_checked_more_than_ninety_days_ago() -> None:
    job = _jobs()["rules-age"]
    assert _weekly(job) and not job.get("continue-on-error")
    assert "python -m scripts.check_rules_age" in _script(job)


def test_the_weekly_run_installs_claude_code_as_the_guide_says_and_checks_its_flags() -> None:
    """Every call passes over a dozen Claude Code flags, and CI only ever ran a fake ``claude``. The weekly
    run installs the real one with Anthropic's installer (the newest, and the oldest Ordnung takes) and checks
    them without signing in; while the job is new a failure shows without failing the run."""
    job = _jobs()["claude-code"]
    assert _weekly(job) and job["continue-on-error"] is True
    assert job["strategy"]["matrix"]["claude"] == ["latest", version_text(MIN_CLAUDE_VERSION)]
    install = native_install("linux")
    assert f"`{install}`" in (ROOT / "docs/guide.md").read_text(encoding="utf-8")
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
    """Every job ran on Ubuntu, so the data-folder lock's, the durable writes', sync's
    computer id and phone access's macOS and Windows code never ran. One job runs their tests there on every
    event, pull requests and the weekly run among them (it has no ``if``), and a failure there fails the run; every
    test it names exists."""
    job = _jobs()["other-systems"]
    (step,) = [step for step in job["steps"] if "pytest" in step.get("run", "")]
    named = step["run"].replace("\\\n", " ").split()
    for name in PER_SYSTEM_TESTS:
        assert name in named, name
    assert job["strategy"]["matrix"]["os"] == ["macos-latest", "windows-latest"]
    assert job["runs-on"] == "${{ matrix.os }}"
    assert "if" not in job
    assert "continue-on-error" not in job and all("continue-on-error" not in step for step in job["steps"])
    tests = "\n".join(step.get("run", "") for step in job["steps"] if "pytest" in step.get("run", ""))
    named = re.findall(r"tests/[\w*]+\.py(?:::\w+)?", tests)
    assert "tests/test_platform_smoke.py" in named
    for name in named:
        pattern, _, test = name.partition("::")
        files = list(ROOT.glob(pattern))
        assert files, f"{name} names no test file"
        assert not test or f"def {test}(" in files[0].read_text(encoding="utf-8"), f"{name} names no test"


def test_the_installed_wheel_reports_the_package_version_in_ci() -> None:
    for name in ("wheel", "other-systems"):
        script = "\n".join(step.get("run", "") for step in _jobs()[name]["steps"])
        assert "src/ordnung/__init__.py" in script and 'ordnung" --version' in script, name
        assert 'test "$reported" = "ordnung $version"' in script, name


#: what installs Tesseract with its German language data (Ubuntu's ``tesseract-ocr`` brings English with it)
APT_TESSERACT = (
    "sudo apt-get update -q && sudo apt-get install -y -q --no-install-recommends "
    "tesseract-ocr tesseract-ocr-deu"
)


def _step(job: dict[str, Any], text: str) -> tuple[int, dict[str, Any]]:
    """The one step of ``job`` whose script holds ``text``, and where it is."""
    (found,) = [(index, step) for index, step in enumerate(job["steps"]) if text in step.get("run", "")]
    return found


def _coverage_legs(backend: dict[str, Any]) -> list[str]:
    """The backend legs that measure coverage (``coverage: true`` in the matrix)."""
    return [leg["python"] for leg in backend["strategy"]["matrix"].get("include", []) if leg.get("coverage")]


def test_tesseract_is_installed_only_where_a_real_binary_test_needs_it() -> None:
    """Text in pictures (ADR 0024): Tesseract is an optional program, never a dependency. A real one, with German,
    is installed only in the backend's 3.12 leg (the real-binary tests, which must run there instead of skipping)
    and the end-to-end leg of the real app (it reads a photo with OCR on). Every other job, the macOS and Windows
    runners among them, tests the missing-binary path."""
    jobs = _jobs()
    # the packages the doctor's Linux line names
    assert "sudo apt install tesseract-ocr tesseract-ocr-deu" in tesseract_install("linux")

    backend = jobs["backend"]
    at, install = _step(backend, "tesseract")
    assert install["run"].strip() == APT_TESSERACT and install["if"] == "matrix.python == '3.12'"
    runs = [
        index for index, step in enumerate(backend["steps"]) if 'pytest -m "not slow"' in step.get("run", "")
    ]
    assert runs and at < min(runs)
    # on every step of the job: whichever of its test steps runs on 3.12
    assert backend["env"]["ORDNUNG_REQUIRE_TESSERACT"] == "${{ matrix.python == '3.12' && '1' || '' }}"

    e2e = jobs["e2e"]
    at, install = _step(e2e, "tesseract")
    assert install["run"].strip() == APT_TESSERACT and install["if"] == "matrix.group == 'real'"
    playwright_at, playwright = _step(e2e, "npm run e2e")
    assert at < playwright_at
    assert "real" in e2e["strategy"]["matrix"]["group"]
    assert playwright["env"] == {
        "E2E_GROUP": "${{ matrix.group }}",
        "ORDNUNG_E2E_OCR": "on",
        "ORDNUNG_REQUIRE_TESSERACT": "1",
    }

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
    it. The floors read the coverage the test step measured, so they cost no second run. Coverage is measured
    on one leg, the one with Tesseract (the most code runs there), and that leg runs
    the whole fast suite with it: the floors are read where the coverage was measured."""
    coverage = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]
    assert coverage["run"]["branch"] is True
    assert 90 <= coverage["report"]["fail_under"] < 100
    backend = _jobs()["backend"]
    assert _coverage_legs(backend) == ["3.12"]
    (measured,) = [step for step in backend["steps"] if "--cov=ordnung" in step.get("run", "")]
    assert _can_run(shlex.split(measured["run"].split("pytest", 1)[1]), "tests/test_sync_lineage.py")
    script = ""
    for step in backend["steps"]:
        if "coverage report" in step.get("run", ""):
            assert step["if"] == measured["if"] == "${{ matrix.coverage }}"
            script += step["run"]
    for package in ("sync", "phone"):
        (line,) = [line for line in script.splitlines() if f"--include='*/ordnung/{package}/*'" in line]
        floor = float(line.split("--fail-under=", 1)[1].split()[0])
        assert 80 <= floor < 100, package
