""".github/workflows/ci.yml: lint and types run once, coverage on one backend leg, the slow tests (in two jobs that
share their files) and the replays each in a job of their own, the end-to-end groups beside the backend's legs, a
push to main never cuts off a running run, macOS and Windows must pass, every published benchmark number is
replayed with a gate at that number, coverage has floors, the weekly run checks the rules' age and the real Claude
Code's flags, a real Tesseract is installed only where a test needs it (ADR 0024), and each job that runs the
pre-registration's tests checks out the whole history."""

from __future__ import annotations

import ast
import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
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
    of them, and ``make eval-reproduce`` took 6 of the replays' 12 to 13. So the slow tests (in two jobs, see
    below), the gates' replays (with ``demo --check``), ``make eval-reproduce`` and lint with the type check (the
    same on every Python: pyproject.toml gives ruff and mypy 3.11 as their target) each have a job, all on pull
    requests, and every check still runs. The gates' replays keep the job id ``backend-slow`` (tests/test_present.py
    looks for the presenter's check there); evals/reproduce.py reads the gates of every job."""
    jobs = _jobs()
    lint, backend, tests, replays = jobs["lint"], jobs["backend"], jobs["slow-tests"], jobs["backend-slow"]
    reproduce, longest = jobs["reproduce"], jobs["slow-long"]
    assert all(_on_pull_requests(job) for job in (lint, backend, tests, longest, replays, reproduce))
    assert {job["runs-on"] for job in (backend, tests, longest, replays, reproduce)} == {"ubuntu-24.04"}
    for job in (lint, tests, longest, replays, reproduce):
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
    unless ``ORDNUNG_REQUIRE_SAMPLES=1``: then it fails. The one job whose slow tests include it (of the two that
    share the slow tests) installs the manifest's libraries (``-c constraints.txt`` on Ubuntu 24.04's Python 3.12)
    and sets it, so drifted libraries fail CI instead of passing it with the check skipped. No other job sets it."""
    check = "tests/test_samples.py::test_committed_samples_match_regeneration"
    samples = (ROOT / "tests" / "test_samples.py").read_text(encoding="utf-8")
    assert (
        "@pytest.mark.slow  # regenerates the samples\ndef test_committed_samples_match_regeneration("
        in samples
    )
    assert 'os.environ.get("ORDNUNG_REQUIRE_SAMPLES") == "1"' in samples
    jobs = _jobs()
    (runner,) = [
        name
        for name, job in jobs.items()
        if any(_can_run(args, "tests/test_samples.py") for args in _slow_runs(job))
    ]
    assert runner in SLOW_JOBS
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


def _e2e_legs(e2e: dict[str, Any]) -> list[tuple[str, int, int]]:
    """The end-to-end job's legs: each one's group, its part and how many parts its group runs in."""
    return [(leg["group"], leg["shard"], leg["shards"]) for leg in e2e["strategy"]["matrix"]["include"]]


def _legs_cover_their_groups(legs: list[tuple[str, int, int]], groups: list[str]) -> list[str]:
    """What is wrong with ``legs`` as the legs of ``groups`` (nothing: every test runs once): each group runs in
    parts 1 to N of N, each part once, and every leg is of a group. Playwright's ``--shard=k/N`` gives every file of
    the group to exactly one of the N parts, so parts 1 to N of one N are the whole group, each test once."""
    problems = []
    for group in groups:
        parts = sorted((shard, shards) for name, shard, shards in legs if name == group)
        totals = {shards for _, shards in parts}
        if len(totals) != 1 or parts != [(k, max(totals)) for k in range(1, max(totals) + 1)]:
            problems.append(f"{group}: parts {parts}")
    problems += [f"{name}: no such group" for name, _, _ in legs if name not in groups]
    return problems


#: legs that leave tests out or run them twice, and what the check above says of each
BROKEN_LEGS = [
    ([("demo", 1, 1), ("layout", 1, 2)], ["layout: parts [(1, 2)]"]),  # a part missing
    # a part twice
    (
        [("demo", 1, 1), ("layout", 1, 2), ("layout", 2, 2), ("layout", 2, 2)],
        ["layout: parts [(1, 2), (2, 2), (2, 2)]"],
    ),
    # two ways to cut one group
    ([("demo", 1, 1), ("layout", 1, 2), ("layout", 2, 3)], ["layout: parts [(1, 2), (2, 3)]"]),
    ([("layout", 1, 1)], ["demo: parts []"]),  # a group with no leg
    ([("demo", 1, 1), ("layout", 1, 1), ("lay-out", 1, 1)], ["lay-out: no such group"]),
]


def test_a_group_whose_legs_leave_out_or_repeat_a_part_is_caught() -> None:
    whole = [("demo", 1, 1), ("layout", 1, 2), ("layout", 2, 2)]
    assert _legs_cover_their_groups(whole, ["demo", "layout"]) == []
    for legs, problems in BROKEN_LEGS:
        assert _legs_cover_their_groups(legs, ["demo", "layout"]) == problems, legs


def test_the_end_to_end_groups_start_at_once_and_together_run_every_project() -> None:
    """Each end-to-end leg installs its own Python, Node and Chromium and checks that the committed web build
    matches its sources: it uses nothing another job makes, so it waits for none (waiting for the frontend job put 8
    minutes before a 39-minute Playwright run, 18 Nov 2026; a stale build fails the leg's own check, and the
    frontend job's build proves the sources still build). Playwright drives the committed build, the one the wheel
    ships, never one the leg builds. Chromium comes as its headless shell, with no system packages (an apt mirror
    once hung the install and failed a run), cached under a key of its own. Its legs are the groups of
    web/e2e/env.ts: a group left out here would never run in CI. A group runs whole, or in parts (Playwright's
    ``--shard``) whose legs together are the whole group, each part once: the layout guards, the longest, in four.
    The checks that need both toolchains run on one leg, not on each; among them the next test, which lists every
    leg's tests with Playwright and holds them to the whole run's, each once."""
    jobs = _jobs()
    e2e = jobs["e2e"]
    assert "needs" not in e2e and "download-artifact" not in json.dumps(e2e)
    assert _on_pull_requests(e2e) and _on_pull_requests(jobs["frontend"])
    assert set(e2e["strategy"]["matrix"]) == {"include"}
    legs = _e2e_legs(e2e)
    assert len(legs) == len(set(legs)), (
        "a leg is listed twice in e2e's matrix: each (group, shard, shards) once"
    )
    assert _legs_cover_their_groups(legs, _e2e_groups()) == [], (
        "each group in web/e2e/env.ts needs legs for parts 1..N of one N in the e2e job's matrix"
    )
    assert ("layout", 4, 4) in legs
    _, playwright = _step(e2e, "npm run e2e")
    assert playwright["env"]["E2E_GROUP"] == "${{ matrix.group }}"
    # a leg runs its part of its group: 1/1 is the whole group
    assert playwright["run"] == "cd web && npm run e2e -- --shard=${{ matrix.shard }}/${{ matrix.shards }}"
    assert "format(' {0}/{1}', matrix.shard, matrix.shards)" in e2e["name"]
    (upload,) = [step for step in e2e["steps"] if "upload-artifact" in step.get("uses", "")]
    assert upload["with"]["name"] == "playwright-report-${{ matrix.group }}-${{ matrix.shard }}"
    (checks,) = [step for step in e2e["steps"] if "ORDNUNG_REQUIRE_MOCK_CHECK" in step.get("env", {})]
    assert checks["if"] == "matrix.group == 'real'"
    assert (
        "tests/test_ci_workflow.py::test_every_end_to_end_test_runs_in_exactly_one_leg"
        in checks["run"].split()
    ), "the end-to-end job's real leg must run the listing test: it skips everywhere else"
    assert [leg for leg in legs if leg[0] == "real"] == [("real", 1, 1)]
    fresh_at, fresh = _step(e2e, "cd web && node scripts/source-hash.mjs --check")
    assert fresh["run"].endswith(" ../src/ordnung/web/dist/build-info.json")
    assert "npm run build" not in _script(e2e) and "npm run build" in _script(jobs["frontend"])
    assert fresh_at < _step(e2e, "npm run e2e")[0]
    _, browser = _step(e2e, "npx playwright install")
    assert browser["run"] == "cd web && npx playwright install --only-shell chromium"
    (cache,) = [step for step in e2e["steps"] if "ms-playwright" in step.get("with", {}).get("path", "")]
    assert cache["with"]["key"].startswith("playwright-shell-")


_WEB = ROOT / "web"
#: Playwright's ``--list`` line of a test: ``[project] › file:line:column › title``
_LISTED_TEST = re.compile(r"^\s+\[[\w-]+\] › \S+:\d+:\d+ › ", re.M)


def _listed(group: str | None, *args: str) -> list[str]:
    """The tests Playwright lists for a run of ``group`` (``E2E_GROUP``; ``None``: the whole run) with ``args``."""
    env = {key: value for key, value in os.environ.items() if key not in ("E2E_GROUP", "CI")}
    if group:
        env["E2E_GROUP"] = group
    listing = subprocess.run(
        [str(_WEB / "node_modules" / ".bin" / "playwright"), "test", "--list", *args],
        cwd=_WEB,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if listing.returncode != 0:
        # Playwright's own reason (such as a project that E2E_GROUPS doesn't hold) is what the next person needs
        pytest.fail(f"playwright test --list (E2E_GROUP={group}) failed:\n{listing.stderr or listing.stdout}")
    return [line.strip() for line in listing.stdout.splitlines() if _LISTED_TEST.match(line)]


#: Skipped without Node and the web app's packages, except where ``ORDNUNG_REQUIRE_MOCK_CHECK=1`` (CI's end-to-end
#: job, which has both toolchains): there a missing toolchain fails, so CI always checks its own legs.
_needs_web = pytest.mark.skipif(
    os.environ.get("ORDNUNG_REQUIRE_MOCK_CHECK") != "1"
    and (shutil.which("node") is None or not (_WEB / "node_modules" / ".bin").exists()),
    reason="needs node and web/node_modules (npm ci in web/)",
)


@_needs_web
def test_every_end_to_end_test_runs_in_exactly_one_leg() -> None:
    """What Playwright itself lists for each leg of the end-to-end job (its group and its ``--shard``) is, all legs
    together, what it lists for the whole run, and no test is in two legs: a spec file that no group's project
    takes, or a part left out, fails here, not by never running: such a file is missing from the whole run's
    listing too, so the spec files on disk are held to that listing."""
    whole = _listed(None)
    listed_files = {line.split(" › ")[1].rsplit(":", 2)[0] for line in whole}
    on_disk = {path.relative_to(_WEB / "e2e").as_posix() for path in (_WEB / "e2e").rglob("*.spec.ts")}
    assert sorted(on_disk - listed_files) == [], (
        "a spec file no project of playwright.config.ts takes never runs: add it to a project's testMatch"
    )
    seen: Counter[str] = Counter()
    for group, shard, shards in _e2e_legs(_jobs()["e2e"]):
        tests = _listed(group, f"--shard={shard}/{shards}")
        assert tests, (group, shard, shards)
        seen.update(tests)
    assert [test for test, count in seen.items() if count > 1] == []
    assert sorted(seen) == sorted(whole), "a test runs in no leg or in two: compare the two lists"


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
    is required now, Windows on every pull request as well; only the weekly check of Claude Code's flags, which installs
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
    assert "(Windows on every pull request, both on main and weekly, required to pass)" in guide
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


def test_the_only_third_party_action_runs_a_fixed_commit() -> None:
    """GitHub's own actions are named by major version; astral-sh/setup-uv, the one from elsewhere, runs a fixed
    commit with its version beside it (Dependabot updates both), the one release.yml pins, so a moved tag can't
    make a run pass that should fail."""
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    refs = set(re.findall(r"uses: astral-sh/setup-uv@(\S+.*)$", text, re.M))
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    (pinned,) = re.findall(r"uses: astral-sh/setup-uv@([0-9a-f]{40} # v\d+\.\d+\.\d+)$", release, re.M)
    assert refs == {pinned}
    others = {ref.split("@")[0] for ref in re.findall(r"uses: (\S+)", text)} - {"astral-sh/setup-uv"}
    assert all(name.startswith("actions/") for name in others), others


def test_the_frontend_job_fails_on_any_difference_from_the_committed_build() -> None:
    """The sources' hash alone passes a committed bundle changed by hand: the build is reproducible, so the step
    right after ``npm run build`` (which writes into the committed folder) fails on any changed, added or removed
    file there."""
    steps = _jobs()["frontend"]["steps"]
    (built,) = [i for i, step in enumerate(steps) if step.get("run") == "npm run build"]
    check = steps[built + 1]["run"]
    assert "git diff --exit-code --stat -- ../src/ordnung/web/dist" in check
    assert 'test -z "$(git status --porcelain -- ../src/ordnung/web/dist)"' in check


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
    # a bash array the script fills (``tests=(...)``) and passes as ``"${part[@]}"``: read as every item of every
    # array the script writes out, a superset of what the run can take
    listed = [
        item for items in re.findall(r"^\s*\w+=\(([^)]*)\)", script, re.M | re.S) for item in items.split()
    ]
    for line in script.replace("\\\n", " ").splitlines():
        found = re.search(r"(?:^|[\s/])pytest(?=\s|$)", line)
        if found:
            args = shlex.split(line[found.end() :])
            runs.append(
                [item for arg in args for item in (listed if re.fullmatch(r"\$\{\w+\[@\]\}", arg) else [arg])]
            )
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


def _paths(args: list[str]) -> tuple[list[str], list[str]]:
    """The test paths a pytest run with ``args`` names (a node id read as its file), and the ones it ``--ignore``s,
    each in the order given. An argument that names no test (an option's value, as in ``--durations 20``) is
    neither."""
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
    return paths, ignored


def _can_run(args: list[str], test_file: str) -> bool:
    """Whether a pytest run with ``args`` can include ``test_file``: one that names no test path runs the whole
    suite, whatever its ``-m`` (the pre-registration's file has slow and not-slow tests); one that names paths runs
    what they match; an ``--ignore`` that matches leaves it out. An argument that names no test (an option's value,
    as in ``--durations 20``) is not read as a path."""
    paths, ignored = _paths(args)
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
    any job that comes to run it). The macOS and Windows job, the end-to-end job and the job of the longest slow
    tests name their tests, and it is not among them today; the parser's cases above hold that reading."""
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


#: the two jobs that share the slow tests: ``slow-tests`` runs every slow test file but those ``slow-long`` names
SLOW_JOBS = ("slow-tests", "slow-long")
#: the slow test that bounds the longest slow tests' job (232 s on a fast runner, 19 Nov 2026)
KILL_TEST_FILE = "tests/test_sync_pull_process.py"
_SLOW_MARK = "pytest.mark.slow"


def _slow_runs(job: dict[str, Any]) -> list[list[str]]:
    """The arguments of each pytest run of ``job`` that selects the slow tests (``-m slow``)."""
    return [
        args for args in _pytest_runs(job) if "-m" in args and args[args.index("-m") + 1 :][:1] == ["slow"]
    ]


def _slow_tests(path: Path) -> list[str]:
    """The tests of ``path`` marked slow: a test function or class with the mark as its decorator, a test class
    made with it (``TestX = pytest.mark.slow(...)``), or every test of a file whose ``pytestmark`` holds it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def marked(node: ast.AST) -> bool:
        return any(ast.unparse(part) == _SLOW_MARK for part in ast.walk(node))

    def names(node: ast.Assign) -> list[str]:
        return [target.id for target in node.targets if isinstance(target, ast.Name)]

    tests = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name.lower().startswith("test")
    ]
    assigned = [node for node in tree.body if isinstance(node, ast.Assign) and marked(node.value)]
    if any("pytestmark" in names(node) for node in assigned):
        return [node.name for node in tests]
    return [node.name for node in tests if any(marked(mark) for mark in node.decorator_list)] + [
        name for node in assigned for name in names(node) if name.startswith("Test")
    ]


def test_the_slow_tests_run_in_two_jobs_that_share_their_files() -> None:
    """As one job the slow tests were about 2,000 s of work on a runner's 4 processes: 565 s on one runner, 908 on
    another where every test was about 1.6 times slower (19 Nov 2026), and that job was the last of a run whose
    other jobs were done in 10 to 11 minutes. So two jobs share them, each on a runner of its own: ``slow-long``
    names the files of the longest slow tests, and ``slow-tests`` runs every other slow test, the files the first
    names left out with an ``--ignore`` each. The two lists are the same files: no slow test is dropped, none runs
    twice, and a new slow test file runs in ``slow-tests`` without an edit to the workflow (it names no path). So
    ``slow-long`` names whole files (a node id would leave the file's other slow tests in neither job), and neither
    job narrows its selection further (``-k``, ``--deselect``, ``--ignore-glob``, ``--lf``, a second ``-m``, which
    pytest reads instead of the first, or any of them in ``PYTEST_ADDOPTS``) or only collects (``--co``). The
    pre-registration's file stays in ``slow-tests``, where the whole history is checked out. ``slow-long`` keeps its files in the order
    given (pytest-xdist would sort them by their number of tests), with the kill test's file fourth: of the 4
    processes, each takes one file and then a second while it has at most 2 tests waiting, in turn, so with at
    most 2 slow tests in each of the first three files and at most 7 files the kill test's process, the fourth,
    gets no file after it."""
    jobs = _jobs()
    assert [name for name, job in jobs.items() if _slow_runs(job)] == list(SLOW_JOBS)
    (rest,), (longest,) = (_slow_runs(jobs[name]) for name in SLOW_JOBS)
    rest_paths, left_out = _paths(rest)
    named, ignored = _paths(longest)
    assert rest_paths == [] and ignored == []
    values = {index + 1 for index, arg in enumerate(longest) if arg in _PYTEST_OPTION_VALUES}
    arguments = [arg for index, arg in enumerate(longest) if index not in values and not arg.startswith("-")]
    assert arguments == named, "slow-long names whole files"
    for args in (rest, longest):
        options = {arg.split("=", 1)[0] for arg in args if arg.startswith("-")}
        narrowing = {"--deselect", "--ignore-glob", "--co", "--collect-only", "--lf", "--last-failed"}
        assert not options & narrowing, options
        assert not any(arg.startswith("-k") for arg in args), args
        assert args.count("-m") == 1 and not any(a.startswith("-m") and a != "-m" for a in args), args
    for name in SLOW_JOBS:
        job = jobs[name]
        assert "PYTEST_ADDOPTS" not in json.dumps(job.get("env", {})) + json.dumps(job["steps"]), name
    assert "PYTEST_ADDOPTS" not in json.dumps(_workflow().get("env", {}))
    assert len(named) == len(set(named)) and len(left_out) == len(set(left_out))
    assert sorted(named) == sorted(left_out), "the files slow-long names are the files slow-tests leaves out"
    assert all(re.fullmatch(r"tests/test_\w+\.py", name) for name in named), named
    assert _can_run(rest, PREREGISTRATION_TESTS) and not _can_run(longest, PREREGISTRATION_TESTS)
    assert "--no-loadscope-reorder" in longest and named.index(KILL_TEST_FILE) == 3
    assert len(named) <= 7 and all(len(_slow_tests(ROOT / name)) <= 2 for name in named[:3]), named
    assert (
        ["--dist", "loadfile"] == longest[longest.index("--dist") :][:2] == rest[rest.index("--dist") :][:2]
    )


def test_each_file_of_the_longest_slow_tests_holds_a_slow_test() -> None:
    """A file ``slow-long`` names runs only its slow tests (``-m slow``): one without any (renamed, or its tests no
    longer slow) would leave the job running nothing of it, and ``slow-tests`` leaving it out as well."""
    (longest,) = _slow_runs(_jobs()["slow-long"])
    for name in _paths(longest)[0]:
        path = ROOT / name
        assert path.is_file(), f"{name} is no test file"
        assert _slow_tests(path), f"{name} has no slow test"


def test_both_jobs_of_slow_tests_run_on_the_same_events_and_name_their_slowest_tests() -> None:
    """The two halves of the slow tests run where the one job ran (pull requests, main and by hand, not the weekly
    run) on the same system, Python and pinned libraries, and each names its 15 slowest tests at the end, so a
    slow runner or a test that grew shows in its log. ``slow-tests`` keeps the name it had as the one job: a
    required check may be registered under that name."""
    jobs = _jobs()
    assert jobs["slow-tests"]["name"] == "Backend, slow tests (Python 3.12)"
    rest, longest = (jobs[name] for name in SLOW_JOBS)
    assert longest.get("if") == rest.get("if") == "github.event_name != 'schedule'"
    assert longest["runs-on"] == rest["runs-on"] == "ubuntu-24.04"
    for name in SLOW_JOBS:
        job = jobs[name]
        assert [
            step["with"]["python-version"]
            for step in job["steps"]
            if "python-version" in step.get("with", {})
        ] == ["3.12"], name
        assert 'uv pip install -e ".[dev]" -c constraints.txt' in _script(job), name
        (args,) = _slow_runs(job)
        assert "--durations=15" in args, name


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


def _without_land_step() -> dict[str, Any]:
    """The step that replays the benchmark without the sender's Land and compares it with the published file: in the
    second part of the job ``reproduce`` (it took the benchmarks' job, whose steps run one after another, to 7.5 to
    8.5 minutes), once."""
    found = [
        (name, step)
        for name, job in _jobs().items()
        for step in job["steps"]
        if "eval_without_land" in step.get("run", "")
    ]
    assert [name for name, _ in found] == ["reproduce"], found
    ((_, step),) = found
    assert step["if"] == "matrix.part == 2"
    return dict(step)


def test_the_without_land_replay_goes_to_a_temporary_folder_and_must_match_the_published_file(
    tmp_path: Path,
) -> None:
    step = _without_land_step()
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
    doesn't exist). The job runs in two parts (the next test says how they share the commands)."""
    jobs = _jobs()
    slow, reproduce = jobs["backend-slow"], jobs["reproduce"]
    assert reproduce["if"] == "github.event_name != 'schedule'"  # on pull requests and main, not weekly
    _, step = _step(reproduce, "make eval-reproduce")
    assert step["run"].strip() == "make eval-reproduce" and set(step["env"]) == {"REPRODUCE_ARGS"}
    assert "if" not in step, "both parts replay: a condition on the step loses its part's commands"
    # the without-Land gate runs in one part only (the gate's own test); every other step runs in both
    assert [
        s.get("name") for s in reproduce["steps"] if "if" in s and "eval_without_land" not in s.get("run", "")
    ] == [], "only the without-Land gate runs in one part: a condition on another step loses that part's work"
    assert [name for name, job in jobs.items() if "make eval-reproduce" in _script(job)] == ["reproduce"]
    assert set(_gates(_script(slow))) == set(GATED_SPLITS)  # the gates stay
    workflow = json.dumps([slow, reproduce])
    assert "secrets." not in workflow and "ANTHROPIC_API_KEY" not in workflow and "install.sh" not in workflow
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "eval-reproduce" in makefile.split(".PHONY:", 1)[1].splitlines()[0]
    recipe = makefile.split("\neval-reproduce:", 1)[1].split("\n\n", 1)[0]
    assert "$(PY) -m evals.reproduce --check $(REPRODUCE_ARGS)" in recipe and "--live" not in recipe
    assert re.search(r"^REPRODUCE_ARGS \?=$", makefile, re.M), (
        "make takes REPRODUCE_ARGS from the environment"
    )


def _reproduce_parts() -> list[list[str]]:
    """The arguments each leg of the job ``reproduce`` gives ``python -m evals.reproduce --check`` (its step's
    ``REPRODUCE_ARGS``, with the leg's ``select``), part 1 first."""
    job = _jobs()["reproduce"]
    _, step = _step(job, "make eval-reproduce")
    legs = sorted(job["strategy"]["matrix"]["include"], key=lambda leg: leg["part"])
    return [
        shlex.split(step["env"]["REPRODUCE_ARGS"].replace("${{ matrix.select }}", leg["select"]))
        for leg in legs
    ]


def test_the_two_parts_of_the_published_numbers_replay_every_command_once(tmp_path: Path) -> None:
    """As one job the replay of every published number took 8.2 to 9.2 minutes (25 Nov 2026), its 4 processes busy
    throughout: it runs in two parts side by side. Both legs name the same cells, one with ``--only`` and the other
    with ``--skip``, so every command of the plan runs in exactly one of them, and a cell added later runs in the
    second without an edit here; each part checks the rows of its own commands and keeps what the index says of the
    others. Neither part is empty, and the job's name says which part a leg is."""
    from evals import reproduce

    job = _jobs()["reproduce"]
    assert [leg["part"] for leg in job["strategy"]["matrix"]["include"]] == [1, 2]
    # a failure in one part must not cancel the other: its gates' and comparisons' failures would go unreported
    assert job["strategy"]["fail-fast"] is False
    assert "${{ matrix.part }}/2" in job["name"]
    first, second = _reproduce_parts()
    assert first[0] == "--only" and second[0] == "--skip" and first[1:] == second[1:] and first[1:]
    cells = first[1:]
    tasks = [task.name for task in reproduce.plan(reproduce.static_index(), reproduce.RESULTS_DIR, tmp_path)]
    assert len(tasks) == len(set(tasks))
    parts = [
        [name for name in tasks if reproduce.named(name, cells)],
        [n for n in tasks if not reproduce.named(n, cells)],
    ]
    assert all(parts), parts
    assert sorted(parts[0] + parts[1]) == sorted(tasks) and not set(parts[0]) & set(parts[1])
    # each cell names a kind of command the plan has: a misspelt one would leave its commands in the second part
    assert all(any(reproduce.named(name, [cell]) for name in tasks) for cell in cells), cells


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
    without_land = _without_land_step()
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


#: the tests whose subject differs per system, which the "Other systems" job runs on macOS and Windows: its test
#: step's list (``tests=(...)``), entry for entry and in its order. A file dropped from that list would stop running
#: there with nothing else failing, so a change to it is a change here, with its reason
PER_SYSTEM_TESTS = (
    "tests/test_platform_smoke.py",  # the real lookups, the disk-encryption probe among them
    # the data folder's lock, held across processes
    "tests/test_cli.py::test_the_lock_keeps_a_second_writer_out",
    "tests/test_cli.py::test_the_lock_waits_up_to_its_timeout",
    "tests/test_cli.py::test_a_lock_held_by_another_process_blocks_until_it_exits",
    "tests/test_sync_*.py",  # sync's computer id among them
    "tests/test_phone_net.py",  # phone access's network lookups
    "tests/test_phone_tls.py",
    "tests/test_phone_listener.py",
    "tests/test_autostart.py",  # the autostart entry, one per operating system
    "tests/test_shortcut.py",  # the Mac bundle opened; the Windows link read back by the shell and opened
    "tests/test_backup.py",
    "tests/test_backup_container.py",
    "tests/test_rules_postcodes.py",
    "tests/test_make_postcode_table.py",
    "tests/test_encryption.py",  # no answer and no process on Windows; nothing in it depends on the system
    "tests/test_store_ledger_token.py",  # SQLite's data_version and TEMP triggers, in each system's own SQLite
    "tests/test_ocr.py",  # Tesseract's places, priority, private temp folder and kill per system; missing there
    "tests/test_doctor_pictures.py",  # "Not installed (optional)" with that system's install line
)


def _other_systems_legs(job: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The legs (``os``, ``part``, ``parts``) of the macOS and Windows job: on a pull request, and on every other
    event."""
    legs = re.fullmatch(
        r"\$\{\{ fromJSON\(github\.event_name == 'pull_request' && '(\{[^']*\})' \|\| '(\{[^']*\})'\) \}\}",
        job["strategy"]["matrix"],
    )
    assert legs, job["strategy"]["matrix"]
    on_a_pull_request, on_every_other_event = (json.loads(listed) for listed in legs.groups())
    assert set(on_a_pull_request) == set(on_every_other_event) == {"include"}
    return on_a_pull_request["include"], on_every_other_event["include"]


#: what the macOS and Windows job's test step does with its list: the tests whose file matches FIRST_PART are part
#: 1, every other test part 2, and a leg of one part runs them all
_PART_SELECTION = """
part=()
for test in "${tests[@]}"; do
  if [[ $test == $FIRST_PART ]]; then first=1; else first=2; fi
  if [ "${{ matrix.parts }}" = 1 ] || [ "$first" = "${{ matrix.part }}" ]; then part+=("$test"); fi
done
# with no file named, the run would take every test of the repository
test ${#part[@]} -gt 0 || { echo "::error::part ${{ matrix.part }} has no test: see FIRST_PART"; exit 1; }
"$venv/python" -m pytest -m "not slow" --durations=20 "${part[@]}"
"""


def _per_system_parts(step: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """The tests of the macOS and Windows job's test step, as bash expands its list (``tests=(...)``, a glob read as
    the files it matches, in their order): those of part 1, of part 2, and all of them."""
    script = step["run"].replace("\\\n", " ")
    assert _PART_SELECTION in "\n" + script, "the test step picks its part of the list by FIRST_PART alone"
    (listed,) = re.findall(r"^tests=\(([^)]*)\)$", script, re.M | re.S)
    assert tuple(listed.split()) == PER_SYSTEM_TESTS, (
        "the per-system list changed: update PER_SYSTEM_TESTS and say why"
    )
    tests = []
    for name in listed.split():
        path, _, test = name.partition("::")
        files = sorted(str(file.relative_to(ROOT)) for file in ROOT.glob(path)) if "*" in path else [path]
        assert files and (ROOT / files[0]).is_file(), f"{name} names no test file"
        assert not test or f"def {test}(" in (ROOT / path).read_text(encoding="utf-8"), (
            f"{name} names no test"
        )
        tests += [f"{file}::{test}" if test else file for file in files]
    first = step["env"]["FIRST_PART"]
    return [t for t in tests if fnmatch(t, first)], [t for t in tests if not fnmatch(t, first)], tests


def test_the_other_systems_job_runs_the_tests_whose_subject_differs_per_system() -> None:
    """Every job ran on Ubuntu, so the data-folder lock's, the durable writes', sync's
    computer id and phone access's macOS and Windows code never ran. One job runs their tests there, and a failure
    there fails the run; every test it names exists. Windows runs on every event, pull requests and the weekly run
    among them (the job has no ``if``). macOS runs on every event but a pull request: on one pull request of three
    its runner was 10 minutes in coming, longer than any job takes, and on another none came, so the job was
    cancelled after 15 minutes in the queue and failed a run whose other jobs had all passed."""
    job = _jobs()["other-systems"]
    (step,) = [step for step in job["steps"] if "pytest" in step.get("run", "")]
    *_, tests = _per_system_parts(step)  # the list is PER_SYSTEM_TESTS, entry for entry
    assert "--durations=20" in step["run"].split()  # each leg's long poles, on record in its log
    on_a_pull_request, on_every_other_event = _other_systems_legs(job)
    assert {leg["os"] for leg in on_a_pull_request} == {"windows-latest"}
    assert {leg["os"] for leg in on_every_other_event} == {"macos-latest", "windows-latest"}
    assert [leg for leg in on_every_other_event if leg["os"] == "windows-latest"] == on_a_pull_request
    assert job["runs-on"] == "${{ matrix.os }}"
    assert "if" not in job
    assert "continue-on-error" not in job and all("continue-on-error" not in step for step in job["steps"])
    assert "tests/test_platform_smoke.py" in tests
    # the run is read as its list, not as the whole suite (which would need the whole history checked out)
    (args,) = _pytest_runs(job)
    assert _can_run(args, "tests/test_sync_crash.py") and not _can_run(args, PREREGISTRATION_TESTS)


def test_each_per_system_test_runs_in_exactly_one_part_on_each_system() -> None:
    """On Windows the tests run in one process (locks across processes, real ports, kills mid-write), and as one
    job they took 6.6 to 9.9 minutes, twice the longest of a run (three runs, 25 Nov 2026). So Windows runs them in two legs side
    by side: one list in the step, and one pattern (``FIRST_PART``) that sends a test to part 1 when its file
    matches and to part 2 when it does not, so no test is in neither part or in both, and a file added to the list
    lands in one of them without an edit. A system with one leg (macOS) runs the whole list. Each system's legs
    together are the parts 1 to N once each; the wheel's steps run in the last part only."""
    job = _jobs()["other-systems"]
    (step,) = [step for step in job["steps"] if "pytest" in step.get("run", "")]
    first, second, tests = _per_system_parts(step)
    assert len(tests) == len(set(tests))
    assert first and second and sorted(first + second) == sorted(tests) and not set(first) & set(second)
    assert "tests/test_sync_crash.py" in first  # the longest file, about a third of the step on Windows
    on_a_pull_request, on_every_other_event = _other_systems_legs(job)
    for legs in (on_a_pull_request, on_every_other_event):
        for system in {leg["os"] for leg in legs}:
            parts = sorted((leg["part"], leg["parts"]) for leg in legs if leg["os"] == system)
            count = parts[0][1]
            assert parts == [(part, count) for part in range(1, count + 1)], (system, parts)
            assert count in (1, 2), (system, parts)
    assert ("macos-latest", 1, 1) in [(leg["os"], leg["part"], leg["parts"]) for leg in on_every_other_event]
    assert "matrix.parts > 1" in job["name"] and "matrix.part" in step["name"]
    assert step["if"] == "${{ !cancelled() && steps.install.outcome == 'success' }}", (
        "the test step runs in every leg: a condition on matrix.part drops that part's tests"
    )
    wheel_steps = ("Build the wheel and install it into a clean venv", "The wheel reports this version")
    for name in wheel_steps:
        (wheel,) = [step for step in job["steps"] if step.get("name", "").startswith(name)]
        assert wheel["if"] == "matrix.part == matrix.parts", name
    # a leg's failure must not cancel the other legs: each part's failures are its own to report
    assert job["strategy"]["fail-fast"] is False
    assert [
        step.get("name")
        for step in job["steps"]
        if "matrix.part" in step.get("if", "") and not step.get("name", "").startswith(wheel_steps)
    ] == [], "only the wheel's steps depend on the part: a condition on matrix.part drops that part's work"


def test_a_per_system_selection_that_loses_or_repeats_a_test_is_caught() -> None:
    """The reading above fails a step whose list or pattern would drop or double a test: a pattern that matches
    every file or none leaves a part empty, and a step that picks its part some other way is not read at all."""
    (step,) = [step for step in _jobs()["other-systems"]["steps"] if "pytest" in step.get("run", "")]
    for pattern in ("tests/*", "tests/nothing_*"):
        first, second, _ = _per_system_parts({**step, "env": {"FIRST_PART": pattern}})
        assert not (first and second), pattern
    for old, new in (
        ('[ "$first" = "${{ matrix.part }}" ]', '[ "$first" -le "${{ matrix.part }}" ]'),
        ('"${part[@]}"', '"${tests[@]}"'),
    ):
        with pytest.raises(AssertionError, match="picks its part"):
            _per_system_parts({**step, "run": step["run"].replace(old, new)})


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
    assert ("real", 1, 1) in _e2e_legs(e2e)
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


def _coverage_halves(backend: dict[str, Any]) -> list[tuple[dict[str, Any], list[str]]]:
    """The steps of the backend's coverage leg that measure it, with each one's pytest arguments: one a half."""
    measured = [step for step in backend["steps"] if "--cov=ordnung" in step.get("run", "")]
    return [(step, shlex.split(step["run"].split("pytest", 1)[1])) for step in measured]


def test_coverage_counts_branches_and_has_floors_for_the_whole_package_sync_and_phone() -> None:
    """Only the rules engine had a coverage gate: the main test step reported coverage but never failed on
    it. The floors read the coverage the test steps measured, so they cost no second run. Coverage is measured
    on one leg, the one with Tesseract (the most code runs there), in two halves on two runners: each test file runs
    in exactly one of them (the files one pattern names, and every other file with that pattern left out), and the
    job ``coverage`` adds up what both measured and reads the floors from the sum, so they are read on the whole
    fast suite, as when one leg ran it. It runs once both halves are done, and fails when either kept no coverage
    (a half whose tests failed); it keeps the name the one leg had."""
    coverage = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]
    assert coverage["run"]["branch"] is True
    assert 90 <= coverage["report"]["fail_under"] < 100
    jobs = _jobs()
    backend, total = jobs["backend"], jobs["coverage"]
    assert _coverage_legs(backend) == ["3.12"]
    matrix = backend["strategy"]["matrix"]
    assert matrix["half"] == [1, 2]
    excluded = [(leg["python"], leg["half"]) for leg in matrix["exclude"]]
    assert sorted(excluded) == [(python, 2) for python in matrix["python"] if python != "3.12"]
    measured = _coverage_halves(backend)
    assert [step["if"] for step, _ in measured] == [
        "${{ matrix.coverage && matrix.half == 1 }}",
        "${{ matrix.coverage && matrix.half == 2 }}",
    ]
    (_, named), (_, second) = measured
    assert len(_paths(named)[0]) == 1, f"half 1 must name exactly one pattern of test files: {_paths(named)}"
    (pattern,) = _paths(named)[0]
    assert _paths(named) == ([pattern], []) and _paths(second) == ([], [pattern]), (
        "half 2 must leave out exactly the pattern half 1 names, so every test file runs in one half",
        _paths(named),
        _paths(second),
    )
    for args in (named, second):
        # the floors are the sum's: a half alone measures half the package
        assert "--cov-report=" in args and "--cov-fail-under=0" in args and "--durations=15" in args, args
        options = args[: args.index("--cov=ordnung")]
        assert options == shlex.split('-m "not slow" -n auto --dist loadfile'), args
    files = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob("test_*.py"))
    in_no_half_or_both = [name for name in files if _can_run(named, name) == _can_run(second, name)]
    assert in_no_half_or_both == []
    assert _can_run(named, "tests/test_cli.py") and _can_run(second, "tests/test_sync_lineage.py")
    # each half keeps its data for the job that adds them up
    _, keep = _step(backend, 'mv .coverage ".coverage.${{ matrix.half }}"')
    assert keep["if"] == "${{ matrix.coverage }}"
    (upload,) = [step for step in backend["steps"] if "upload-artifact" in step.get("uses", "")]
    assert upload["with"]["path"] == ".coverage.${{ matrix.half }}" and upload["with"]["include-hidden-files"]
    assert upload["with"]["if-no-files-found"] == "error" and upload["if"] == "${{ matrix.coverage }}"
    assert total.get("needs") == "backend", "the job that adds up the coverage must wait for the backend legs"
    assert total["name"] == "Backend (Python 3.12)"
    assert total["if"] == "${{ !cancelled() && github.event_name != 'schedule' }}"
    script = _script(total)
    # a missing half says which one, not only that the step failed
    assert "for h in 1 2; do\n  test -f .coverage.$h || {" in script
    assert '"::error::no coverage from half $h: its tests failed or did not finish' in script
    assert ".venv/bin/coverage combine .coverage.1 .coverage.2\n.venv/bin/coverage report " in script
    # the whole package's floor is pyproject.toml's
    assert "--fail-under" not in script.split("coverage report", 2)[1]
    for package in ("sync", "phone"):
        lines = [line for line in script.splitlines() if f"--include='*/ordnung/{package}/*'" in line]
        assert len(lines) == 1, (
            f"the coverage job must read the {package} floor once, with --fail-under: {lines}"
        )
        (line,) = lines
        floor = float(line.split("--fail-under=", 1)[1].split()[0])
        assert 80 <= floor < 100, package
    assert "coverage report" not in _script(backend)
