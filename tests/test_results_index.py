"""evals/reproduce.py and evals/results/INDEX.json: every published number replayed with no model call, and every
results file in one index with its hash, role, how it is checked and what a replay at HEAD gives (plan EV4).

The full replay runs in CI (``make eval-reproduce`` in backend-slow); these tests check what needs no replay — the
index's hashes, roles, cells and gates against the checkout, the declarations, and the comparison logic on
hand-made results — and the command end to end on a small folder with a stand-in for the replays."""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from evals import reproduce, splits
from evals.present import model as present_model
from evals.run import DEFAULT_MODEL, RESULTS_DIR

ROOT = Path(__file__).resolve().parents[1]
INDEX = RESULTS_DIR / "INDEX.json"
CITING = ("README.md", "docs/evals.md", "docs/evals-ask.md", "docs/evals-history.md")
RESULTS_NAME = re.compile(r"\b(\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+?\.json)\b")


@pytest.fixture(scope="module")
def index() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(INDEX.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def rows(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["file"]: row for row in index["results"]}


# --------------------------------------------------------------------------------------------------
# The committed index against the checkout (no replay)
# --------------------------------------------------------------------------------------------------


def test_every_results_file_has_one_row_with_its_sha256(index: dict[str, Any]) -> None:
    files = sorted(path.name for path in RESULTS_DIR.glob("*.json") if path.name != "INDEX.json")
    assert [row["file"] for row in index["results"]] == files
    for row in index["results"]:
        assert row["sha256"] == reproduce.sha256_file(RESULTS_DIR / row["file"]), row["file"]
    assert index["schema"] == reproduce.INDEX_SCHEMA and index["pinned_model"] == DEFAULT_MODEL


def test_what_needs_no_replay_is_what_the_checkout_gives(index: dict[str, Any]) -> None:
    """The dataset's and the recordings' hashes, the CI gates, the cells and every row's hash, role, recording and
    check are computed from the checkout: a new results file, a changed recording or a moved gate is a visible
    diff of INDEX.json (``python -m evals.reproduce --write``)."""
    fresh = reproduce.static_index(RESULTS_DIR)
    assert reproduce.static_problems(index, fresh) == []


def test_the_roles_are_the_presenters(rows: dict[str, dict[str, Any]]) -> None:
    """One source for a file's role: the presenter derives it from the file itself, and the index says the same."""
    assert {name: row["role"] for name, row in rows.items()} == present_model.roles(RESULTS_DIR)


def test_every_results_file_a_page_or_the_readme_cites_is_in_the_index(
    rows: dict[str, dict[str, Any]],
) -> None:
    cited = set()
    for page in CITING:
        cited |= set(RESULTS_NAME.findall((ROOT / page).read_text(encoding="utf-8")))
    cited = {name for name in cited if "<" not in name}
    assert cited, "the pages cite results files by name"
    assert cited <= set(rows), sorted(cited - set(rows))


def test_archived_rows_are_another_models_and_the_index_names_only_the_pinned_one(
    index: dict[str, Any], rows: dict[str, dict[str, Any]]
) -> None:
    """A run of an earlier model can't be replayed (its recordings are not in the repository): it is checked by
    its hash only. The index names no model but the pinned one."""
    archived = [name for name, row in rows.items() if row["role"] == "archive"]
    assert len(archived) == 10  # nine reading runs and one Ask run
    assert sum(rows[name]["kind"] == "run" for name in archived) == 9
    text = INDEX.read_text(encoding="utf-8")
    for name in archived:
        assert rows[name]["check"] == "hash" and rows[name]["verdict"] == "archived"
        data = json.loads((RESULTS_DIR / name).read_text(encoding="utf-8"))
        meta = data.get("meta") or {}
        other = meta.get("model") or data.get("model")
        assert other != DEFAULT_MODEL and f'"{other}"' not in text, name


def test_every_changed_date_is_declared_with_a_reason(rows: dict[str, dict[str, Any]]) -> None:
    """A published date the code changed since its recording is listed with the fix that changed it: a commit, an
    ADR or the re-scored results file that shows it. A change can't be declared silently, and a worse one shows."""
    declared = 0
    for name, row in rows.items():
        for condition, verdict in row.get("conditions", {}).items():
            for change in verdict["changes"]:
                declared += 1
                because = change["because"]
                assert because, (name, condition, change["entry_id"])
                assert re.search(r"\b[0-9a-f]{7,40}\b|ADR \d{4}|\d{4}-\d{2}-\d{2}-[\w.-]+\.json", because), (
                    because
                )
                for file in re.findall(r"\d{4}-\d{2}-\d{2}-[\w.-]+?\.json", because):
                    assert file in rows, file
                assert change["direction"] in ("better", "worse", "other")
    assert declared == 8


def test_todays_verdicts(rows: dict[str, dict[str, Any]]) -> None:
    """Known values of the replay at HEAD (zero tokens): holdout3 and the newest holdout2 re-scoring replay exactly;
    the held-out recordings as they scored changed by the declared fixes only (holdout 53 → 55 of 56, holdout2
    54 → 55), and the baselines' dates are the same in every file."""
    for name in (
        "2026-10-06-claude-sonnet-5-holdout3.json",
        "2026-10-06-claude-sonnet-5-holdout2-rescored.json",
    ):
        assert rows[name]["verdict"] == "exact"
        assert {verdict["verdict"] for verdict in rows[name]["conditions"].values()} == {"exact"}
    for name, right, at_head, ids in (
        (
            "2026-09-30-claude-sonnet-5-holdout.json",
            [53, 56],
            [55, 56],
            ["holdout-adversarial-conflicting_dates-1", "holdout-adversarial-conflicting_dates-2"],
        ),
        (
            "2026-10-01-claude-sonnet-5-holdout2.json",
            [54, 56],
            [55, 56],
            ["holdout2-adversarial-injection_visible-1"],
        ),
        (
            "2026-09-25-sonnet-test.json",
            [50, 56],
            [55, 56],
            [
                "test-adversarial-injection_visible-2",
                "test-adversarial-injection_visible-2-photo",
                "test-social_decision-C1",
                "test-social_decision-D1",
                "test-social_decision-D2",
            ],
        ),
    ):
        row = rows[name]
        ordnung = row["conditions"]["ordnung"]
        assert row["verdict"] == ordnung["verdict"] == "changed"
        assert (ordnung["right"], ordnung["right_at_head"]) == (right, at_head)
        assert [change["entry_id"] for change in ordnung["changes"]] == ids
        assert {change["direction"] for change in ordnung["changes"]} == {"better"}
        for condition in ("llm_only", "llm_rules_text", "llm_rules_tool"):
            assert row["conditions"][condition]["verdict"] in ("exact", "same-dates"), (name, condition)
    checked = {name for name, row in rows.items() if row["verdict"] == "checked"}
    assert checked == {
        "2026-10-01-claude-sonnet-5-ask.json",
        "2026-10-29-claude-sonnet-5-ask.json",
        "2026-10-08-claude-sonnet-5-without-land.json",
        "2026-10-29-claude-sonnet-5-checks-ablated.json",
        "2026-10-29-claude-sonnet-5-e2e.json",
        "2026-10-29-claude-sonnet-5-heldout-reanalysis.json",
    }
    superseded = {name for name, row in rows.items() if row["verdict"] == "superseded"}
    assert superseded == {
        "2026-09-30-claude-sonnet-5-ask.json",
        "2026-10-06-claude-sonnet-5-without-land.json",
    }


def test_the_ask_files_say_which_is_as_recorded_and_which_is_a_re_scoring(
    rows: dict[str, dict[str, Any]],
) -> None:
    """The development set's live run of 2026-10-01 stays checked as recorded (schema 1) beside its re-scoring with the
    strict scorer (schema 2), which names the run it re-scores; the earlier run is superseded."""
    recorded, rescored = (
        rows["2026-10-01-claude-sonnet-5-ask.json"],
        rows["2026-10-29-claude-sonnet-5-ask.json"],
    )
    assert (recorded["schema"], recorded["recorded"]["backend"], "rescores" in recorded) == (1, "live", False)
    assert (rescored["schema"], rescored["recorded"]["backend"], rescored["rescores"]) == (
        2,
        "replay",
        "2026-10-01",
    )
    for row in (recorded, rescored):
        assert (row["set"], row["repeat"], row["check"], row["gates"]) == (
            "dev",
            1,
            "ask --check-docs",
            ["ask/dev"],
        )
    assert rows["2026-09-30-claude-sonnet-5-ask.json"]["check"] == "hash"


def test_every_cell_is_replayed_or_says_it_is_not_recorded_yet(index: dict[str, Any]) -> None:
    """Every split, condition, Ask set, end-to-end, ablation and stress cell: replayed when its recordings exist,
    else listed as not recorded yet with what it waits for (never faked)."""
    cells = {cell["cell"]: cell for cell in index["cells"]}
    for split in splits.recorded():
        assert cells[f"benchmark/{split}/r1"]["status"] == "replayed", split
        assert cells[f"benchmark/{split}/r1"]["conditions"] == [
            "ordnung",
            "llm_only",
            "llm_rules_text",
            "llm_rules_tool",
        ]
    waiting = sorted(name for name, cell in cells.items() if cell["status"] == "not recorded yet")
    assert waiting == [
        "ablation/holdout4",
        "analysis/final",
        "ask/heldout/r1",
        "ask/heldout/r2",
        "ask/heldout/r3",
        "benchmark/holdout4/r1",
        "benchmark/holdout4/r2",
        "benchmark/holdout4/r3",
        "benchmark/newkinds/r1",
        "e2e/holdout4-newkinds",
        "stress/D1",
        "stress/I1",
    ]
    for name in waiting:
        assert cells[name]["needs"], name
    for name in (
        "without-land",
        "ask/dev/r1",
        "ablation/dev-holdout-holdout2-holdout3-test",
        "analysis/heldout-reanalysis",
        "presenter",
    ):
        assert cells[name]["status"] in ("replayed", "re-rendered"), name
    assert cells["e2e/dev-holdout-holdout2-holdout3-test"]["status"] == "replayed"


def test_the_gates_are_the_ci_workflows(index: dict[str, Any]) -> None:
    gates = index["gates"]
    assert gates["benchmark/test"] == {"conditions": "all", "min_accuracy": 0.98, "max_dangerous_late": 0.0}
    for split in ("holdout", "holdout2"):
        assert gates[f"benchmark/{split}"] == {
            "conditions": ["ordnung"],
            "min_accuracy": 0.98,
            "max_dangerous_late": 0.0,
        }
    assert gates["benchmark/dev"]["min_accuracy"] == 0.96
    assert gates["without-land"] == {"published": "2026-10-08-claude-sonnet-5-without-land.json"}
    assert "--check-docs" in gates["ask/dev"]["args"] and "--known-attack" in gates["ask/dev"]["args"]


# --------------------------------------------------------------------------------------------------
# Comparing a published run with its replay
# --------------------------------------------------------------------------------------------------


def _item(index: int, outcome: str, predicted: str | None, **extra: Any) -> dict[str, Any]:
    late = outcome == "wrong" and predicted is not None and predicted > "2026-03-16"
    return {
        "index": index,
        "required": True,
        "outcome": outcome,
        "expected": "2026-03-16",
        "predicted": predicted,
        "direction": "late" if late else None,
        "days_off": 1 if late else None,
        **extra,
    }


def _run(
    items: dict[str, list[dict[str, Any]]], *, conditions: tuple[str, ...] = ("ordnung",)
) -> dict[str, Any]:
    entries = []
    for entry_id, entry_items in items.items():
        entries.append(
            {
                "id": entry_id,
                "conditions": {
                    condition: {
                        "prediction": {
                            "fingerprint": "f" * 16,
                            "calls": [{"wall_ms": 12, "backend": "live", "cost_usd": 0.03}],
                            "items": [{"due_date": item["predicted"]} for item in entry_items],
                        },
                        "score": {"items": copy.deepcopy(entry_items), "cost_usd": 0.03},
                    }
                    for condition in conditions
                },
            }
        )
    right = sum(item["outcome"] == "correct" for entry_items in items.values() for item in entry_items)
    scored = sum(item["outcome"] != "unscored" for entry_items in items.values() for item in entry_items)
    metrics = {
        condition: {
            "due_date_accuracy": {"k": float(right), "n": float(scored)},
            "cost_usd": {"total": 0.1 + 0.2},
        }
        for condition in conditions
    }
    return {
        "schema": 1,
        "meta": {"model": DEFAULT_MODEL, "split": "dev", "conditions": list(conditions)},
        "metrics": metrics,
        "entries": entries,
    }


def test_a_replay_that_differs_only_in_what_a_run_measures_itself_is_exact() -> None:
    published = _run({"dev-a-A1": [_item(0, "correct", "2026-03-16")]})
    replayed = copy.deepcopy(published)
    for entry in replayed["entries"]:
        prediction = entry["conditions"]["ordnung"]["prediction"]
        prediction["fingerprint"] = "0" * 16
        prediction["calls"][0].update(wall_ms=99, backend="replay")
    replayed["metrics"]["ordnung"]["cost_usd"]["total"] = 0.3  # summed in another order
    (verdict,) = reproduce.compare_run(published, replayed).values()
    assert verdict == {
        "verdict": "exact",
        "right": [1, 1],
        "right_at_head": [1, 1],
        "drift": {"added": [], "removed": [], "values": []},
        "changes": [],
    }


def test_fields_added_since_and_other_values_are_drift_not_changed_dates() -> None:
    published = _run({"dev-a-A1": [_item(0, "correct", "2026-03-16"), _item(1, "unscored", "2026-04-01")]})
    replayed = copy.deepcopy(published)
    score = replayed["entries"][0]["conditions"]["ordnung"]["score"]
    score["check_filed"] = 0
    score["items"][1]["predicted"] = None  # an unscored item's date: no published number moves
    replayed["entries"][0]["conditions"]["ordnung"]["prediction"]["calls"][0]["cost_usd"] = 0.04
    replayed["metrics"]["ordnung"]["deadline_check"] = {"k": 0}
    (verdict,) = reproduce.compare_run(published, replayed).values()
    assert verdict["verdict"] == "same-dates" and verdict["changes"] == []
    assert verdict["drift"] == {
        "added": ["metrics.deadline_check", "score.check_filed"],
        "removed": [],
        "values": ["prediction.calls[]", "score.items[]"],
    }


def test_a_changed_date_is_listed_with_its_direction() -> None:
    published = _run(
        {
            "dev-a-A1": [_item(0, "wrong", "2026-03-17")],
            "dev-b-A1": [_item(0, "correct", "2026-03-16")],
            "dev-c-A1": [_item(0, "wrong", "2026-03-17")],
        }
    )
    replayed = _run(
        {
            "dev-a-A1": [_item(0, "correct", "2026-03-16")],
            "dev-b-A1": [_item(0, "missed", None)],
            "dev-c-A1": [_item(0, "wrong", "2026-03-18")],
        }
    )
    (verdict,) = reproduce.compare_run(published, replayed).values()
    assert verdict["verdict"] == "changed"
    assert (verdict["right"], verdict["right_at_head"]) == ([1, 3], [1, 3])
    assert verdict["changes"] == [
        {
            "entry_id": "dev-a-A1",
            "item": 0,
            "recorded": {"outcome": "wrong", "predicted": "2026-03-17"},
            "at_head": {"outcome": "correct", "predicted": "2026-03-16"},
            "direction": "better",
            "because": "",
        },
        {
            "entry_id": "dev-b-A1",
            "item": 0,
            "recorded": {"outcome": "correct", "predicted": "2026-03-16"},
            "at_head": {"outcome": "missed", "predicted": None},
            "direction": "worse",
            "because": "",
        },
        {
            "entry_id": "dev-c-A1",
            "item": 0,
            "recorded": {"outcome": "wrong", "predicted": "2026-03-17"},
            "at_head": {"outcome": "wrong", "predicted": "2026-03-18"},
            "direction": "other",
            "because": "",
        },
    ]


def _row(published: dict[str, Any], replayed: dict[str, Any], because: str = "") -> dict[str, Any]:
    conditions = reproduce.compare_run(published, replayed)
    for verdict in conditions.values():
        for change in verdict["changes"]:
            change["because"] = because
    return {"file": "2026-03-02-claude-sonnet-5-dev.json", "conditions": conditions}


def test_an_undeclared_change_and_a_declaration_the_replay_no_longer_gives_fail() -> None:
    published = _run({"dev-a-A1": [_item(0, "wrong", "2026-03-17")]})
    fixed = _run({"dev-a-A1": [_item(0, "correct", "2026-03-16")]})
    fresh = reproduce.compare_run(published, fixed)
    undeclared = _row(published, fixed)
    problems = reproduce.run_problems(undeclared, fresh)
    assert len(problems) == 1 and "dev-a-A1" in problems[0] and "undeclared" in problems[0]
    declared = _row(published, fixed, because="the two-dates check (304e2bf8)")
    assert reproduce.run_problems(declared, fresh) == []
    # the code changes again: the declaration no longer describes what the replay gives
    assert reproduce.run_problems(declared, reproduce.compare_run(published, published))
    worse = _run({"dev-a-A1": [_item(0, "wrong", "2026-03-18")]})
    problems = reproduce.run_problems(declared, reproduce.compare_run(published, worse))
    assert problems and any("dev-a-A1" in problem for problem in problems)


def test_merge_keeps_the_reasons_of_changes_the_replay_still_gives() -> None:
    published = _run(
        {"dev-a-A1": [_item(0, "wrong", "2026-03-17")], "dev-b-A1": [_item(0, "wrong", "2026-03-17")]}
    )
    fixed = _run(
        {"dev-a-A1": [_item(0, "correct", "2026-03-16")], "dev-b-A1": [_item(0, "correct", "2026-03-16")]}
    )
    committed = _row(
        published,
        _run(
            {"dev-a-A1": [_item(0, "correct", "2026-03-16")], "dev-b-A1": [_item(0, "wrong", "2026-03-17")]}
        ),
        because="ADR 0016",
    )
    merged = reproduce.merge_conditions(committed, reproduce.compare_run(published, fixed))
    reasons = {change["entry_id"]: change["because"] for change in merged["ordnung"]["changes"]}
    assert reasons == {"dev-a-A1": "ADR 0016", "dev-b-A1": ""}


# --------------------------------------------------------------------------------------------------
# The index's static part, the cells and the commands
# --------------------------------------------------------------------------------------------------


def test_static_problems_name_a_changed_file_a_missing_row_and_an_extra_row(index: dict[str, Any]) -> None:
    fresh = reproduce.static_index(RESULTS_DIR)
    stale = copy.deepcopy(index)
    stale["results"][0]["sha256"] = "0" * 64
    del stale["results"][1]
    stale["results"].append({**stale["results"][2], "file": "2099-01-01-claude-sonnet-5-dev.json"})
    problems = reproduce.static_problems(stale, fresh)
    assert any(index["results"][0]["file"] in problem and "sha256" in problem for problem in problems)
    assert any(index["results"][1]["file"] in problem and "no row" in problem for problem in problems)
    assert any("2099-01-01-claude-sonnet-5-dev.json" in problem for problem in problems)


def _copy_results(tmp_path: Path, names: list[str]) -> Path:
    results = tmp_path / "results"
    results.mkdir()
    for name in names:
        shutil.copy(RESULTS_DIR / name, results / name)
    return results


def test_a_final_splits_results_file_makes_its_cell_a_replay_with_its_repeat(tmp_path: Path) -> None:
    results = _copy_results(tmp_path, ["2026-10-06-claude-sonnet-5-holdout3.json"])
    data = json.loads((results / "2026-10-06-claude-sonnet-5-holdout3.json").read_text(encoding="utf-8"))
    data["meta"].update(split="holdout4", repeat=2)
    (results / "2027-01-10-claude-sonnet-5-holdout4-r2.json").write_text(json.dumps(data), encoding="utf-8")
    static = reproduce.static_index(results)
    cells = {cell["cell"]: cell for cell in static["cells"]}
    assert cells["benchmark/holdout4/r2"]["status"] == "replayed"
    assert cells["benchmark/holdout4/r1"]["status"] == "not recorded yet"
    tasks = {task.name: task for task in reproduce.plan(static, results, tmp_path / "work")}
    argv = tasks["benchmark/holdout4/r2"].argv
    assert argv[argv.index("--split") + 1] == "holdout4" and argv[argv.index("--repeat") + 1] == "2"
    assert "benchmark/holdout4/r1" not in tasks


def test_every_task_is_a_strict_replay_into_the_work_folder(index: dict[str, Any], tmp_path: Path) -> None:
    """No task records, refreshes or writes into the checkout: replays go to the work folder, the checks only read."""
    work = tmp_path / "work"
    tasks = reproduce.plan(index, RESULTS_DIR, work)
    names = [task.name for task in tasks]
    for split in splits.recorded():
        assert f"benchmark/{split}/r1" in names
    assert {
        "without-land",
        "ask/dev/r1",
        "e2e/dev-holdout-holdout2-holdout3-test",
        "analysis/heldout-reanalysis",
        "presenter",
    } <= set(names)
    assert "ablation/dev-holdout-holdout2-holdout3-test" in names
    for task in tasks:
        assert task.argv[:2] == [sys.executable, "-m"], task.name
        for flag in ("--live", "--refresh", "--write", "--docs", "--prune-stale", "--write-manifest"):
            assert flag not in task.argv, (task.name, flag)
        for option in ("--results-dir", "--out"):
            if option in task.argv:
                assert Path(task.argv[task.argv.index(option) + 1]).is_relative_to(work), (task.name, option)
    by_name = {task.name: task.argv for task in tasks}
    assert by_name["ask/dev/r1"][3:] == index["gates"]["ask/dev"]["args"]
    e2e = by_name["e2e/dev-holdout-holdout2-holdout3-test"]
    assert "--no-write" in e2e and "--exact-parity" in e2e and "--compare" in e2e
    assert by_name["analysis/heldout-reanalysis"][2:] == ["evals.analysis", "--check"]
    assert by_name["presenter"][2:] == ["evals.present", "--check"]
    assert by_name["ablation/dev-holdout-holdout2-holdout3-test"][2:4] == [
        "scripts.eval_ablate_checks",
        "--check",
    ]


def test_the_replays_can_never_reach_a_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no ``ORDNUNG_CLAUDE_BIN`` the children get a path that doesn't exist (a call fails as "not installed");
    one that is set (the tests' fake Claude) is kept."""
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    env = reproduce.child_env(tmp_path)
    assert not Path(env["ORDNUNG_CLAUDE_BIN"]).exists() and env["ORDNUNG_OCR"] == "off"
    monkeypatch.setenv("ORDNUNG_CLAUDE_BIN", "/somewhere/fake_claude.py")
    assert reproduce.child_env(tmp_path)["ORDNUNG_CLAUDE_BIN"] == "/somewhere/fake_claude.py"


# --------------------------------------------------------------------------------------------------
# The command, end to end, with a stand-in for the replays
# --------------------------------------------------------------------------------------------------

SMALL = [
    "2026-10-06-claude-sonnet-5-holdout3.json",
    "2026-10-01-claude-sonnet-5-holdout2.json",
    "2026-09-29-sonnet-dev.json",
]


def _stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, results: Path, *, fixed: bool) -> list[str]:
    """Replace the replays: each benchmark task's output is the newest published file of its split (holdout2's
    injection letter right when ``fixed``), every check passes."""
    ran: list[str] = []

    def run_tasks(
        tasks: list[reproduce.Task], *, jobs: int, env: dict[str, str], say: Any
    ) -> dict[str, reproduce.Done]:
        done = {}
        for task in tasks:
            ran.append(task.name)
            if task.out is not None:
                task.out.mkdir(parents=True, exist_ok=True)
                split = task.name.split("/")[1]
                # the newest file of the split (none: holdout3's, a split no row of this folder is compared with)
                sources = sorted(results.glob(f"*-{split}.json")) or [results / SMALL[0]]
                source = sources[-1]
                data = json.loads(source.read_text(encoding="utf-8"))
                if fixed and split == "holdout2":
                    for entry in data["entries"]:
                        if entry["id"] == "holdout2-adversarial-injection_visible-1":
                            item = entry["conditions"]["ordnung"]["score"]["items"][0]
                            item.update(
                                outcome="correct", predicted=item["expected"], direction=None, days_off=None
                            )
                (task.out / source.name).write_text(json.dumps(data), encoding="utf-8")
            done[task.name] = reproduce.Done(task.name, 0, 0.1, tmp_path / "log")
        return done

    monkeypatch.setattr(reproduce, "run_tasks", run_tasks)
    monkeypatch.setattr(reproduce, "gate_problems", lambda index, replays, done: ([], []))
    return ran


def _main(results: Path, tmp_path: Path, *args: str) -> int:
    return reproduce.main(
        [
            *args,
            "--results-dir",
            str(results),
            "--index",
            str(results / "INDEX.json"),
            "--items",
            str(results / "items.csv"),
            "--work",
            str(tmp_path / "work"),
        ]
    )


def test_write_then_check_on_a_small_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = _copy_results(tmp_path, SMALL)
    ran = _stand_in(tmp_path, monkeypatch, results, fixed=True)
    assert _main(results, tmp_path, "--check") == 2  # no index yet
    assert "INDEX.json" in capsys.readouterr().err
    # the holdout2 change is new: --write records it but can't declare it
    assert _main(results, tmp_path, "--write") == 1
    out = capsys.readouterr()
    assert "undeclared" in out.err and "holdout2-adversarial-injection_visible-1" in out.err
    index = json.loads((results / "INDEX.json").read_text(encoding="utf-8"))
    (change,) = next(row for row in index["results"] if row["file"] == SMALL[1])["conditions"]["ordnung"][
        "changes"
    ]
    assert change["because"] == "" and change["direction"] == "better"
    # a person declares it: the check passes, and a second --write keeps the reason
    change["because"] = "the completeness re-ask, ADR 0016"
    for row in index["results"]:
        if row["file"] == SMALL[1]:
            row["conditions"]["ordnung"]["changes"] = [change]
    (results / "INDEX.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    assert _main(results, tmp_path, "--check") == 0
    board = capsys.readouterr().out
    assert (
        "results files 3: exact 1 · same dates 0 · changed by a declared fix 1 · checked 0 · superseded 0 · archived 1"
        in board
    )
    assert "not recorded yet" in board
    assert "benchmark/holdout3/r1" in ran and not any(name.startswith("benchmark/holdout4") for name in ran)
    assert _main(results, tmp_path, "--write") == 0
    assert "ADR 0016" in (results / "INDEX.json").read_text(encoding="utf-8")


def test_check_fails_on_an_edited_results_file_a_stale_csv_or_a_failed_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = _copy_results(tmp_path, SMALL[:1])
    _stand_in(tmp_path, monkeypatch, results, fixed=False)
    assert _main(results, tmp_path, "--write") == 0
    assert _main(results, tmp_path, "--check") == 0
    csv_path = results / "items.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    assert _main(results, tmp_path, "--check") == 1
    assert "items.csv" in capsys.readouterr().err
    assert _main(results, tmp_path, "--write") == 0
    path = results / SMALL[0]
    path.write_text(
        path.read_text(encoding="utf-8").replace('"split": "holdout3"', '"split":  "holdout3"', 1),
        encoding="utf-8",
    )
    assert _main(results, tmp_path, "--check") == 1
    assert f"{SMALL[0]}: sha256" in capsys.readouterr().err
