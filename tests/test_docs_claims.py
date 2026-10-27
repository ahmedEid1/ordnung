"""The factual claims of README.md and docs/, checked against the code.

Written by a documentation audit: each test states a documented claim as an assertion, so a change
that makes the docs untrue fails here.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tomllib
import unicodedata
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock, letters_zip, shortcut, sync
from ordnung.api.app import openapi_schema
from ordnung.api.deps import require_computer
from ordnung.api.routes import export
from ordnung.api.routes.documents import DocumentPatch
from ordnung.api.routes.profile import ProfilePatch
from ordnung.app_context import AppContext, build_context
from ordnung.assistant.rules_tools import build_rules_server
from ordnung.backup import MAX_PASSPHRASE_CHARS, MIN_PASSPHRASE_CHARS
from ordnung.backup.archive import FOLDERS
from ordnung.backup.container import DEFAULT_KDF, MAX_SCRYPT_BYTES
from ordnung.db import scan_text
from ordnung.db.store import Store
from ordnung.drafts.compose import compose
from ordnung.drafts.sent import letter_profile
from ordnung.drafts.template_letters import TEMPLATES
from ordnung.ingest import pipeline, worker
from ordnung.ingest.extract import ExtractionInput, extraction_request
from ordnung.ingest.plan import VerifiedItem, own_context
from ordnung.llm.base import LLMRequest
from ordnung.llm.claude_cli import MIN_CLAUDE_VERSION, version_text
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import (
    BackupCopy,
    DateSpec,
    Document,
    Evidence,
    ExtractedItem,
    Identifier,
    Page,
    Party,
    Profile,
)
from ordnung.phone import scope as phone_scope
from ordnung.rules.deadlines import RuleContext, compute_due
from ordnung.rules.postcodes import Home, suggest_land_why
from ordnung.secretary import moving, triggers
from ordnung.secretary.triggers import Ledger, letter_day, tax_documents
from ordnung.tick import DailyTick
from test_api_support import api_for

ROOT = Path(__file__).resolve().parents[1]

#: The Ordnung path's fingerprint on the frozen code holdout3 was recorded on (2026-10-06, commit 55bedab).
HOLDOUT3_FROZEN_FINGERPRINT = "822d5316b68df063"

NOW = "2026-09-25T10:00:00Z"


# --------------------------------------------------------------------------------------------------
# README.md
# --------------------------------------------------------------------------------------------------


def test_readme_has_no_unrendered_placeholders() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"\{\{[A-Z_]+\}\}", text) == []


def test_a_git_install_contains_the_built_web_app() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "src/ordnung/web/dist/index.html"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tracked == "src/ordnung/web/dist/index.html"


def _photo_read_item() -> VerifiedItem:
    """A photo-read deadline whose quote is found in the AI transcript and states its values."""
    spec = DateSpec(type="fixed", date="2026-10-02", nature="payment", text="bis zum 02.10.2026")
    item = ExtractedItem(kind="payment", title="Pay the fine", date=spec, quote="Zahlbar bis zum 02.10.2026")
    evidence = Evidence(doc_id="doc_x", page=1, quote=item.quote, grounding="model_read", score=100.0)
    return VerifiedItem(item=item, evidence=evidence, reasons=(), slot_key="payment:1")


def test_a_date_read_from_a_photo_is_labelled_not_flagged() -> None:
    """README: a date whose sentence is found (in the text layer or the photo's transcript) and states
    its numbers is not marked Please check; a photo-read one is labelled as read from the photo."""
    item = _photo_read_item()
    assert not item.needs_check and item.evidence is not None and item.evidence.grounding == "model_read"


def _wrong_llm_only_items(results: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    wrong = []
    for entry in results["entries"]:
        condition = entry["conditions"]["llm_only"]
        for scored in condition["score"]["items"]:
            if scored.get("required") and scored["outcome"] == "wrong":
                predicted = condition["prediction"]["items"][scored["pred_index"]]
                wrong.append((entry["id"], scored, predicted))
    return wrong


_THIRD_DAY = re.compile(r"third day|3rd day|3 days after|\+ ?3 days", re.IGNORECASE)


def test_readme_llm_only_error_counts_that_hold() -> None:
    """README.md:193-196: 10 of 56 wrong, all four late answers moved a delivery day off a weekend."""
    results = json.loads((ROOT / "evals/results/2026-09-25-sonnet-test.json").read_text(encoding="utf-8"))
    wrong = _wrong_llm_only_items(results)
    assert len(wrong) == 10
    late = [(entry, predicted) for entry, scored, predicted in wrong if scored["direction"] == "late"]
    assert len(late) == 4
    assert all(re.search(r"shift|moves|next working day|Werktag", p["explanation"]) for _, p in late)


def test_readme_eight_llm_only_errors_used_the_three_day_rule() -> None:
    """README: 'Eight of those used the 3-day delivery rule' (from the stored explanations)."""
    assert "Eight of those used the 3-day delivery rule" in (ROOT / "README.md").read_text(encoding="utf-8")
    results = json.loads((ROOT / "evals/results/2026-09-25-sonnet-test.json").read_text(encoding="utf-8"))
    three_day = [
        entry
        for entry, _, predicted in _wrong_llm_only_items(results)
        if _THIRD_DAY.search(predicted["explanation"])
    ]
    assert len(three_day) == 8, three_day


def test_rules_branch_coverage_is_a_ci_gate() -> None:
    """README.md:232 lists '100 % branch coverage of rules/' as a quality gate: CI must measure
    branches and fail under 100 % (it used to do neither)."""
    config = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in (".github/workflows/ci.yml", "Makefile", "pyproject.toml")
    )
    assert re.search(r"cov-branch|branch\s*=\s*true", config) and re.search(r"fail[-_]under", config)


def test_mypy_is_strict_on_the_rules_engine() -> None:
    """README's quality table says the rules engine has "`mypy` strict on it, as on the whole package and the
    benchmark code", and its CI gates row says so too: pyproject.toml gives the whole package, the rules engine
    with it, and ``evals/`` every check of ``mypy --strict``, no module is let off, and CI's type check runs
    mypy with pyproject.toml's list (no paths of its own)."""
    mypy = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]
    assert mypy["strict"] is True and mypy["files"] == ["src/ordnung", "evals"]
    assert "overrides" not in mypy
    readme = _flat(_readme())
    assert "`mypy` strict on it, as on the whole package and the benchmark code" in readme
    assert "| CI gates | ruff, mypy (strict, on the package and the benchmark code), ESLint," in readme
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"run: \.venv/bin/mypy\n", ci)
    assert re.search(
        r"^typecheck:\n\t\$\(PY\) -m mypy\n", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M
    )


def test_mypy_finds_the_generators_the_benchmark_code_imports() -> None:
    """README's "strict on the benchmark code" holds only where mypy finds what evals/ imports
    (``ignore_missing_imports`` makes a module it can't find Any, silently). evals/generate.py runs with evals/ on
    sys.path and imports its generators as ``gen``, which mypy, reading evals/ as a package, can't find: for mypy
    it imports the same names from ``evals.gen`` (D1 review: 17 imports were Any). No other benchmark module
    imports ``gen``."""
    tree = ast.parse((ROOT / "evals" / "generate.py").read_text(encoding="utf-8"))

    def imported(nodes: list[ast.stmt], prefix: str = "") -> set[tuple[str, str, str | None]]:
        return {
            ((node.module or "").removeprefix(prefix), alias.name, alias.asname)
            for node in nodes
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }

    assert not {module for module, _, _ in imported(tree.body) if module.split(".")[0] == "gen"}
    (guard,) = [
        node for node in tree.body if isinstance(node, ast.If) and ast.unparse(node.test) == "TYPE_CHECKING"
    ]
    for_mypy, when_run = imported(guard.body, "evals."), imported(guard.orelse)
    assert for_mypy == when_run and len(when_run) > 50
    assert {module.split(".")[0] for module, _, _ in when_run} == {"gen"}
    others = [path for path in (ROOT / "evals").rglob("*.py") if path.name != "generate.py"]
    assert not [
        path.name for path in others if re.search(r"^\s*(from|import) gen\b", path.read_text("utf-8"), re.M)
    ]


def test_demo_check_runs_in_ci() -> None:
    """README.md:232 and docs/privacy.md:87: CI runs ``ordnung demo --check`` (added in abe86a7)."""
    assert "ordnung demo --check" in (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def _pct(value: float) -> str:
    """A rate as the README prints it: one decimal, "100" and "0" without one."""
    text = f"{value * 100:.1f}"
    return text.removesuffix(".0") if text in ("100.0", "0.0") else text


def _with_interval(metric: dict[str, Any]) -> str:
    low, high = metric["ci"]
    return f"{_pct(metric['value'])} % [{_pct(low)}–{_pct(high)}]"


def _results(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "evals" / "results" / name).read_text(encoding="utf-8"))


def test_readme_extraction_benchmark_numbers_match_the_results() -> None:
    """README's benchmark table: the held-out run (2026-09-25) for LLM only, LLM + rules text and
    Ordnung; the run after the engine fix (2026-09-26, not held-out) for Ordnung re-scored and LLM +
    rules tool; the split's size and the late count of LLM only."""
    readme = _readme()
    held_out = _results("2026-09-25-sonnet-test.json")
    after_fix = _results("2026-09-26-sonnet-test.json")
    rows = {
        "LLM only": held_out["metrics"]["llm_only"],
        "LLM + rules text": held_out["metrics"]["llm_rules_text"],
        "**Ordnung**": held_out["metrics"]["ordnung"],
        "**Ordnung**, after fixing the gap that run found²": after_fix["metrics"]["ordnung"],
        "LLM + rules tool, with the fixed engine³": after_fix["metrics"]["llm_rules_tool"],
    }
    for label, metrics in rows.items():
        row = f"| {label} | {_with_interval(metrics['due_date_accuracy'])} |"
        assert row in readme, row
    late = held_out["metrics"]["llm_only"]["dangerous_late_rate"]
    assert f"**{_pct(late['value'])} %** ({int(late['k'])} of {int(late['n'])})" in readme
    for metrics in (held_out["metrics"]["ordnung"], after_fix["metrics"]["llm_rules_tool"]):
        assert metrics["dangerous_late_rate"]["k"] == 0
    meta = held_out["meta"]
    split = (
        f"{meta['scored_items']} dated obligations in {meta['entries']} synthetic\n"
        f"letters ({meta['photos']} of them phone photos, {meta['adversarial']} adversarial)"
    )
    assert split in readme


def _words(n: int) -> str:
    """A small count as README writes it ("two late dates")."""
    return ("no", "one", "two", "three", "four", "five", "six")[n] if n <= 6 else str(n)


def _latest_holdout() -> dict[str, Any]:
    """The newest holdout recording (live model calls, by its own generated_at): the one README's held-out row
    must match — never a replay, which scores the recordings with later code."""
    runs = [_results(path.name) for path in (ROOT / "evals" / "results").glob("*-holdout.json")]
    return max(
        (run for run in runs if run["meta"]["backend"] == "live"), key=lambda run: run["meta"]["generated_at"]
    )


def test_readme_prompt_now_and_held_out_rows_match_the_results() -> None:
    """README's last two benchmark rows: Ordnung with the extraction prompt the app uses now (2026-09-30,
    test split on the pinned model, not held-out) and Ordnung on the holdout split (the newest holdout run,
    recorded once); the footnotes' scores per prompt version and model, the holdout split's size and what
    its three misses are."""
    readme = _readme()
    now = _results("2026-09-30-claude-sonnet-5-test.json")["metrics"]["ordnung"]
    assert now["dangerous_late_rate"]["k"] == 0
    assert (
        f"| **Ordnung**, with the extraction prompt the app uses now⁴ | {_with_interval(now['due_date_accuracy'])} "
        "| **0 %** | no |"
    ) in readme
    holdout = _latest_holdout()
    meta, held = holdout["meta"], holdout["metrics"]["ordnung"]
    assert meta["split"] == "holdout" and "ordnung" in meta["conditions"] and not meta["partial"]
    late = held["dangerous_late_rate"]
    assert (
        f"| **Ordnung**, on a fresh held-out split⁵ | {_with_interval(held['due_date_accuracy'])} "
        f"| **{_pct(late['value'])} %** ({int(late['k'])} of {int(late['n'])}) | yes |"
    ) in readme
    assert (
        f"⁵ {meta['entries']} new letters ({meta['photos']} photos, {meta['adversarial']} adversarial; "
        f"{meta['scored_items']} dated obligations)"
    ) in readme
    exact = int(held["due_date_accuracy"]["k"])
    assert f"Ordnung got {exact} of {int(late['n'])} right" in readme
    # the baselines on the same letters, in the bullet's own words
    baselines = {name: holdout["metrics"][name] for name in ("llm_rules_text", "llm_rules_tool", "llm_only")}
    text, tool, only = (int(m["due_date_accuracy"]["k"]) for m in baselines.values())
    assert baselines["llm_rules_text"]["dangerous_late_rate"]["k"] == 0 and tool == int(late["n"])
    assert f"the rules-text prompt also scored {text} of 56, with no\n  late date" in readme
    assert f"the agent with the calculator all {tool} again" in readme
    assert (
        f"the model alone {only} of 56 with {_words(int(baselines['llm_only']['dangerous_late_rate']['k']))} late"
        in readme
    )
    scores = [
        int(_results(name)["metrics"]["ordnung"]["due_date_accuracy"]["k"])
        for name in (
            "2026-09-29-sonnet-test-prompt9.json",
            "2026-09-29-sonnet-test-prompt10.json",
            "2026-09-29-sonnet-test.json",
            "2026-09-30-sonnet-test.json",
        )
    ]
    assert f"({', '.join(map(str, scores[:-1]))} and {scores[-1]} of 56, on Sonnet 5.5)" in readme
    assert (
        f"lost access to 5.5 ({int(now['due_date_accuracy']['k'])} of 56, the run this row shows)" in readme
    )
    # the two-dates check, replayed on the same holdout recordings: its own row, not held-out
    rescored = _results("2026-09-30-claude-sonnet-5-holdout-rescored.json")
    assert rescored["meta"]["split"] == "holdout" and rescored["meta"]["backend"] == "replay"
    after = rescored["metrics"]["ordnung"]
    assert after["dangerous_late_rate"]["k"] == 0
    assert (
        f"| **Ordnung**, held-out split with the two-dates check⁶ | {_with_interval(after['due_date_accuracy'])} "
        "| **0 %** | no |"
    ) in readme
    assert f"give {int(after['due_date_accuracy']['k'])} of 56 and no late date (row ⁶" in readme
    # the two late dates are the two conflicting-date letters; the third miss is early
    misses = [g for g in holdout["gallery"] if g["condition"] == "ordnung"]
    assert len(misses) == int(late["n"]) - exact == 3
    assert sorted(g["entry_id"] for g in misses if g["direction"] == "late") == [
        "holdout-adversarial-conflicting_dates-1",
        "holdout-adversarial-conflicting_dates-2",
    ]
    assert [g["direction"] for g in misses if g["entry_id"] == "holdout-tax_assessment-F1"] == ["early"]
    # the test split's two letters of that class were read right with the same prompt
    test_run = _results("2026-09-30-claude-sonnet-5-test.json")
    for entry in test_run["entries"]:
        if entry["id"].startswith("test-adversarial-conflicting_dates-"):
            items = entry["conditions"]["ordnung"]["score"]["items"]
            assert items and all(item["outcome"] == "correct" for item in items if item["required"])


def test_readme_second_held_out_row_matches_its_one_recording() -> None:
    """Row ⁷: the holdout2 split, written after the last change to the reading, recorded once with every
    condition; the bullet's counts per condition, and Ordnung's two misses (one early, one missed)."""
    readme = _readme()
    runs = sorted((ROOT / "evals" / "results").glob("*-holdout2.json"))
    assert len(runs) == 1, "holdout2 is recorded once"
    run = _results(runs[0].name)
    meta, metrics = run["meta"], run["metrics"]
    assert meta["split"] == "holdout2" and meta["backend"] == "live" and not meta["partial"]
    assert set(meta["conditions"]) == {"ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"}
    ordnung = metrics["ordnung"]
    assert ordnung["dangerous_late_rate"]["k"] == 0
    assert (
        "| **Ordnung**, on a second held-out split, written after the last change to the reading⁷ | "
        f"{_with_interval(ordnung['due_date_accuracy'])} | **0 %** | yes |"
    ) in readme
    assert (
        f"⁷ {meta['entries']} more new letters ({meta['photos']} photos, {meta['adversarial']} adversarial; "
        f"{meta['scored_items']} dated obligations)"
    ) in readme
    exact = {name: int(m["due_date_accuracy"]["k"]) for name, m in metrics.items()}
    late = {name: int(m["dangerous_late_rate"]["k"]) for name, m in metrics.items()}
    assert f"(row ⁷), Ordnung got {exact['ordnung']} of 56 right." in readme
    assert (
        f"later one on one of them ({exact['llm_rules_tool']} of 56, {_words(late['llm_rules_tool'])} late)"
        in readme
    )
    assert (
        f"The rules-text prompt scored {exact['llm_rules_text']} of 56 with {_words(late['llm_rules_text'])} "
        "late date,"
    ) in readme
    assert f"the model alone {exact['llm_only']} of 56 with {_words(late['llm_only'])}." in readme
    misses = {
        (entry["id"], item["outcome"], item["direction"])
        for entry in run["entries"]
        for item in entry["conditions"]["ordnung"]["score"]["items"]
        if item["required"] and item["outcome"] in ("wrong", "missed")
    }
    assert misses == {
        ("holdout2-tax_assessment-H1", "wrong", "early"),
        ("holdout2-adversarial-injection_visible-1", "missed", None),
    }
    assert ordnung["adversarial"]["conflicting_dates_handled"]["k"] == 2


def test_readme_third_held_out_row_matches_its_one_recording() -> None:
    """Row ¹⁰: the holdout3 split, written after the code freeze, recorded once with every condition on the
    frozen code; the bullet's counts per condition, and no re-ask or reading check needed."""
    readme = _readme()
    runs = sorted((ROOT / "evals" / "results").glob("*-holdout3.json"))
    assert len(runs) == 1, "holdout3 is recorded once"
    run = _results(runs[0].name)
    meta, metrics = run["meta"], run["metrics"]
    assert meta["split"] == "holdout3" and meta["backend"] == "live" and not meta["partial"]
    assert set(meta["conditions"]) == {"ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"}
    ordnung = metrics["ordnung"]
    assert ordnung["dangerous_late_rate"]["k"] == 0
    assert (
        "| **Ordnung**, on a third held-out split, written after the code freeze¹⁰ | "
        f"{_with_interval(ordnung['due_date_accuracy'])} | **0 %** | yes |"
    ) in readme
    flat = _flat(readme)
    assert (
        f"¹⁰ {meta['entries']} more new letters ({meta['photos']} photos, {meta['adversarial']} adversarial; "
        f"{meta['scored_items']} dated obligations)"
    ) in flat
    exact = {name: int(m["due_date_accuracy"]["k"]) for name, m in metrics.items()}
    late = {name: int(m["dangerous_late_rate"]["k"]) for name, m in metrics.items()}
    early = {name: int(m["early_rate"]["k"]) for name, m in metrics.items()}
    assert exact["ordnung"] == exact["llm_rules_tool"] == meta["scored_items"]
    assert (
        f"(row ¹⁰), Ordnung got all {meta['scored_items']} dated deadlines right, and so did the agent with the "
        "calculator."
    ) in flat
    assert (
        f"rules-text prompt scored {exact['llm_rules_text']} of 56 with {_words(late['llm_rules_text'])} late "
        f"date ({_words(early['llm_rules_text'])} early), the model alone {exact['llm_only']} of 56 with "
        f"{_words(late['llm_only'])} late."
    ) in flat
    # recorded on the frozen code (fingerprint of the Ordnung path at 55bedab); the code changed after it (the looser
    # dropped-date check), and a replay on the later code gives the same predictions for every letter
    assert meta["fingerprints"]["ordnung"] == HOLDOUT3_FROZEN_FINGERPRINT
    signals = {
        signal
        for entry in run["entries"]
        for signal in entry["conditions"]["ordnung"]["prediction"].get("signals") or []
    }
    assert not any(signal.startswith("reading_reask") for signal in signals)
    assert ordnung["reading_check"]["filed"] == 0 and ordnung["deadline_check"]["filed"] == 0


def test_readme_reading_check_row_matches_the_rescored_holdout2_run() -> None:
    """Row ⁸: the same holdout2 recordings plus the one call recorded after them — the injection letter's
    completeness re-ask (ADR 0016), accepted — replayed with the current code (not held-out); only that letter
    changes, to its labelled date with the model's own to-do (the reading check files nothing), and the row above
    stays held-out."""
    readme = _readme()
    rescored = _results("2026-10-06-claude-sonnet-5-holdout2-rescored.json")
    held = _results("2026-10-01-claude-sonnet-5-holdout2.json")
    meta = rescored["meta"]
    assert meta["split"] == "holdout2" and meta["backend"] == "replay" and meta["conditions"] == ["ordnung"]
    after = rescored["metrics"]["ordnung"]
    assert after["dangerous_late_rate"]["k"] == 0
    assert (
        "| **Ordnung**, second held-out split with the re-ask and the reading check⁸ | "
        f"{_with_interval(after['due_date_accuracy'])} | **0 %** | no |"
    ) in readme
    assert f"give {int(after['due_date_accuracy']['k'])} of 56 and\n  no late date (row ⁸" in readme
    assert after["reading_check"] == {"filed": 0, "unmatched": 0, "letters": 0}
    reasked = {
        entry["id"]: signal
        for entry in rescored["entries"]
        for signal in entry["conditions"]["ordnung"]["prediction"]["signals"]
        if signal.startswith("reading_reask")
    }
    assert reasked == {"holdout2-adversarial-injection_visible-1": "reading_reask:accepted"}
    assert "reading_reask_missing" not in meta
    [entry] = [e for e in rescored["entries"] if e["id"] == "holdout2-adversarial-injection_visible-1"]
    prediction = entry["conditions"]["ordnung"]["prediction"]
    assert len(prediction["calls"]) == 2
    assert [(item["due_date"], item["origin"]) for item in prediction["items"]] == [("2026-12-10", "model")]
    # the footnote says so: the recorded re-ask's own to-do, not the check's low one
    footnote = _flat(readme).split("⁸ The same recorded outputs plus that one call", 1)[1].split("⁹ ", 1)[0]
    assert "the recorded answer is used" in footnote and "Thu 10 Dec 2026 at high confidence" in footnote
    assert "Wed 9 Dec instead of Thu 10 Dec 2026" in footnote

    def outcomes(run: dict[str, Any]) -> dict[str, str]:
        return {
            entry["id"]: entry["conditions"]["ordnung"]["score"]["items"][0]["outcome"]
            for entry in run["entries"]
            if entry["conditions"]["ordnung"]["score"]["items"]
        }

    before, now = outcomes(held), outcomes(rescored)
    changed = {key for key in before if before[key] != now.get(key)}
    assert changed == {"holdout2-adversarial-injection_visible-1"}
    assert now["holdout2-adversarial-injection_visible-1"] == "correct"
    assert "holdout2-adversarial-injection_visible-1" in meta["note"]


def test_readme_ask_benchmark_numbers_match_the_latest_results() -> None:
    """README's Ask benchmark table and its sizes are the newest recorded Ask run's."""
    readme = _readme()
    latest = sorted((ROOT / "evals" / "results").glob("*-ask.json"))[-1]
    summary = json.loads(latest.read_text(encoding="utf-8"))["summary"]

    def rate(name: str) -> str:
        metric = summary[name]
        return f"{_pct(metric['value'])} % ({int(metric['k'])}/{int(metric['n'])})"

    assert (
        f"{summary['questions']} questions about the demo's sample life ({summary['answerable']} answerable, "
        f"{summary['unanswerable']} with no answer in the records) and {summary['attacks']}\nletters"
    ) in readme
    in_record = summary["accuracy_in_record"]
    assert (
        f"| {rate('accuracy')}; {_pct(in_record['value'])} % ({int(in_record['k'])}/{int(in_record['n'])}) "
        "where the answer is in Ordnung's record |"
    ) in readme
    assert f"| {rate('citation_support')} |" in readme
    assert f"| {rate('abstention')} |" in readme
    assert f"| {rate('attack_success')}, against {rate('attack_success_raw')} before the check |" in readme
    assert "| Unsupported values left in final answers | 0 |" in readme
    results = json.loads(latest.read_text(encoding="utf-8"))
    assert summary["guard"]["unsupported_in_final"] == 0
    assert all(
        entry["scores"]["unsupported_final"] == 0 for entry in results["questions"] + results["attacks"]
    )
    wrong = int(summary["accuracy"]["n"] - summary["accuracy"]["k"])
    if wrong:
        assert (
            f"The {['one', 'two', 'three', 'four', 'five', 'six'][wrong - 1]} wrong answers are gaps"
            in readme
        )
    else:  # every answer right: the README says what the earlier wrong ones were, not that some are wrong
        assert "wrong answers are gaps" not in readme
        assert "earlier recordings got wrong were gaps in the ledger" in readme.replace("\n", " ")


def _flat(text: str) -> str:
    """``text`` with every run of whitespace (line breaks, list indents) as one space."""
    return " ".join(text.split())


#: scripts/eval_without_land.py's published results: with the letterhead's Land, without the sender's Land, and
#: with the state the postcode on the sender's letter suggests confirmed (ADR 0019).
WITHOUT_LAND = "2026-10-08-claude-sonnet-5-without-land.json"
#: The splits the README and deadline-rules.md cite (dev is the page's only).
PUBLISHED_SPLITS = ("test", "holdout", "holdout2", "holdout3")


def test_the_numbers_without_the_sender_s_land_match_their_results_file() -> None:
    """M3: README row ⁹, its footnote, the bullet and Limitations, deadline-rules.md and docs/evals.md cite the
    replay without the sender's Land (scripts/eval_without_land.py, as the app runs until the person sets a
    sender's Land): its accuracy per split, no late date, extra misses 1–3 days early — and the numbers with the
    Land it sets them against are the published replays' (rows ⁴, ⁶ and ⁸)."""
    readme = _readme()
    results = _results(WITHOUT_LAND)
    assert results["schema"] == "ordnung-eval-without-land/2"
    assert results["meta"]["backend"] == "replay" and results["meta"]["condition"] == "ordnung"
    splits = results["splits"]
    assert set(splits) == {"test", "holdout", "holdout2", "holdout3", "dev"}
    for name, numbers in splits.items():
        assert numbers["without_land"]["dangerous_late_rate"]["k"] == 0, name
        assert all(change["direction"] == "early" for change in numbers["changed"]), name
    without = {
        name: splits[name]["without_land"]["due_date_accuracy"]
        for name in ("test", "holdout", "holdout2", "holdout3")
    }
    test, holdout, holdout2, holdout3 = (_pct(metric["value"]) for metric in without.values())
    days = sorted({-change["days_off"] for name in without for change in splits[name]["changed"]})
    early = f"{days[0]}–{days[-1]} days early"
    # the rows with the Land are the published replays of the same recordings
    published = {
        "test": _results("2026-09-30-claude-sonnet-5-test.json"),
        "holdout": _results("2026-09-30-claude-sonnet-5-holdout-rescored.json"),
        "holdout2": _results("2026-10-06-claude-sonnet-5-holdout2-rescored.json"),
    }
    # holdout3's with the Land is its one live recording itself (row ¹⁰), not a replay
    third = _results("2026-10-06-claude-sonnet-5-holdout3.json")
    assert (
        splits["holdout3"]["with_land"]["due_date_accuracy"]
        == third["metrics"]["ordnung"]["due_date_accuracy"]
    )
    for name, run in published.items():
        assert (
            splits[name]["with_land"]["due_date_accuracy"] == run["metrics"]["ordnung"]["due_date_accuracy"]
        )
    with_land = {_pct(splits[name]["with_land"]["due_date_accuracy"]["value"]) for name in published}
    assert len(with_land) == 1
    # README: row ⁹, its footnote, the bullet and Limitations
    assert (
        f"| **Ordnung** as the app runs it, without the sender's Land⁹ | {_with_interval(without['test'])} "
        "| **0 %** | no |"
    ) in readme
    flat = _flat(readme)
    footnote = flat.split("⁹ The rows above", 1)[1].split(" What the numbers say", 1)[0]
    assert (
        f"({splits['test']['letterhead_land']} of the test split's {splits['test']['entries']} letters"
        in footnote
    )
    assert (
        f"Ordnung scores {test} % on the test split, {holdout} % on the holdout split and {holdout2} % on the "
        f"holdout2 split, against {with_land.pop()} % on each with the Land (rows ⁴, ⁶ and ⁸), and {holdout3} % on "
        f"the holdout3 split, against {_pct(splits['holdout3']['with_land']['due_date_accuracy']['value'])} % "
        "with it (row ¹⁰)"
    ) in footnote
    assert f"Every extra miss is {early}; none is late." in footnote
    counts = {name: int(metric["k"]) for name, metric in without.items()}
    assert f"**Without the sender's Land: {test} %, and still no late date.**" in flat
    assert (
        f"{counts['test']} of {int(without['test']['n'])} on the test split, {counts['holdout']} on the holdout "
        f"split, {counts['holdout2']} on the holdout2 split and {counts['holdout3']} on the holdout3 split; every "
        f"extra miss is {early} (row ⁹)"
    ) in flat
    limitation = flat.split("## Limitations", 1)[1]
    # the benchmark's letters miss by 1–3 days; around Christmas the gap is wider (F-S11): a Baden-Württemberg
    # authority's one-month objection period, letter dated Fri 21 Nov 2025, ends 5 days early without the Land
    objection = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    posted = date(2025, 11, 21)

    def objection_ends(land: str | None) -> date:
        context = RuleContext(today=posted, region=land, document_date=posted, delivery_scope="vwvfg")
        due = compute_due(objection, context).due_date
        assert due is not None
        return date.fromisoformat(due)

    christmas = (objection_ends("BW") - objection_ends(None)).days
    assert christmas > days[-1]
    assert (
        f"a date can come out a few days early ({days[0]}–{days[-1]} on the benchmark's letters, up to {christmas} "
        "around Christmas), never late"
    ) in limitation
    assert (
        f"Ordnung scores {test} % (test), {holdout} % (holdout), {holdout2} % (holdout2) and {holdout3} % "
        "(holdout3), with no late dates" in limitation
    )
    # deadline-rules.md section 5 and the benchmark page, which renders the file itself
    rules = _flat((ROOT / "docs" / "deadline-rules.md").read_text(encoding="utf-8"))
    assert (
        f"Ordnung scores {test} % on the test split, {holdout} % on the holdout split and {holdout2} % on the "
        "holdout2 split instead of"
    ) in rules
    evals_page = (ROOT / "docs" / "evals.md").read_text(encoding="utf-8")
    section = evals_page.split("## Without the sender's Land", 1)[1].split("\n## ", 1)[0]
    for name, numbers in splits.items():
        assert (
            f"| `{name}` | " in section
            and f" ({int(numbers['without_land']['due_date_accuracy']['k'])}/" in section
        )


def _suggestions(results: dict[str, Any], splits: tuple[str, ...]) -> dict[str, int]:
    """The suggestion counts of ``splits`` added up: letterhead letters, right, wrong and without one."""
    counts = [results["splits"][name]["suggestion"] for name in splits]
    return {
        "letterhead": sum(c["letterhead_land"] for c in counts),
        "right": sum(c["right"] for c in counts),
        "wrong": sum(c["wrong"] for c in counts),
        "none": sum(sum(c["none"].values()) for c in counts),
        "not_listed": sum(c["none"]["not_listed"] for c in counts),
    }


def test_the_numbers_with_the_suggested_state_match_their_results_file() -> None:
    """ADR 0019: README's footnote ⁹ and bullet, deadline-rules.md and docs/evals.md cite the replay with the
    state the postcode on the sender's letter suggests confirmed: the same numbers as with the letterhead's Land
    on every split, the suggestions against the letterhead's Land, and no suggestion wrong."""
    results = _results(WITHOUT_LAND)
    splits = results["splits"]
    for name, numbers in splits.items():
        assert numbers["with_suggestion"] == numbers["with_land"], name
        assert numbers["changed_with_suggestion"] == [] and numbers["suggestion"]["wrong"] == 0, name
    counts = ", ".join(
        str(int(splits[name]["with_suggestion"]["due_date_accuracy"]["k"])) for name in PUBLISHED_SPLITS[:-1]
    )
    last = int(splits[PUBLISHED_SPLITS[-1]]["with_suggestion"]["due_date_accuracy"]["k"])
    scored = {int(splits[name]["with_suggestion"]["due_date_accuracy"]["n"]) for name in PUBLISHED_SPLITS}
    (n,) = scored
    published = _suggestions(results, PUBLISHED_SPLITS)
    # the one letterhead letter without a suggestion has a postcode GeoNames doesn't list
    assert published["none"] == published["not_listed"] == published["letterhead"] - published["right"] == 1
    gives = f"the same readings give {counts} and {last} of {n}, the numbers with the letterhead's state"
    flat = _flat(_readme())
    footnote = flat.split("⁹ The rows above", 1)[1].split(" What the numbers say", 1)[0]
    assert f"Confirm the state Ordnung suggests from the postcode on their letter, and {gives}" in footnote
    assert (
        f"on the {published['letterhead']} letters whose letterhead names a state, it suggested that state for "
        f"{published['right']}, another for {published['wrong']}, and none for the one whose postcode GeoNames "
        "doesn't list"
    ) in footnote
    assert (
        "The letters are synthetic (mostly real postcodes, made-up towns), and the number assumes you say Yes to "
        "every suggestion."
    ) in footnote
    bullet = flat.split("**Without the sender's Land:", 1)[1].split(" - **", 1)[0]
    assert f"Say Yes to the state Ordnung suggests from the postcode on their letter, and {gives}" in bullet
    # only the letters whose letterhead names a state can show a suggestion wrong
    assert (
        f"no suggestion was wrong on the {published['letterhead']} letters whose letterhead names a state"
        in bullet
    )
    rules = _flat((ROOT / "docs" / "deadline-rules.md").read_text(encoding="utf-8"))
    (again,) = {
        _pct(splits[name]["with_suggestion"]["due_date_accuracy"]["value"]) for name in PUBLISHED_SPLITS[:3]
    }
    assert (
        f"with the state the postcode on their letter suggests confirmed, it scores {again} % on each"
        in rules
    )
    section = (
        (ROOT / "docs" / "evals.md").read_text(encoding="utf-8").split("## Without the sender's Land", 1)[1]
    )
    section = section.split("\n## ", 1)[0]
    assert "| With the suggested state confirmed |" in section
    every = _suggestions(results, tuple(splits))
    assert (
        f"suggested the letterhead's state for {every['right']} of the {every['letterhead']} letters that name "
        f"one, another state for {every['wrong']}, and none for {every['none']};"
    ) in _flat(section)


def test_adr_0019_states_the_measured_numbers_and_their_bound() -> None:
    """ADR 0019's Measured: the suggestions on every split against the letterhead's Land, the letters without
    one by reason, and the one-sided and two-sided 95 % upper bounds of the error rate for 0 wrong of n
    (Clopper–Pearson: 1 − α^(1/n))."""
    results = _results(WITHOUT_LAND)
    every = _suggestions(results, tuple(results["splits"]))
    others = {
        reason: sum(
            s["suggestion"]["not_suggested_without_letterhead_land"][reason]
            for s in results["splits"].values()
        )
        for reason in ("not_listed", "foreign", "no_postcode")
    }
    suggested = sum(s["suggestion"]["suggested_without_letterhead_land"] for s in results["splits"].values())
    entries = sum(s["entries"] for s in results["splits"].values())
    adr = (ROOT / "docs" / "decisions" / "0019-a-sender-s-land-is-suggested-never-set.md").read_text(
        encoding="utf-8"
    )
    measured = _flat(adr.split("## Measured", 1)[1].split("\n## ", 1)[0])
    # counts from a prototype no script in the repository reproduces stay out
    assert "of the 75 right suggestions" not in _flat(adr) and "245 runs" not in _flat(adr)
    assert every["wrong"] == 0
    assert (
        f"On the {every['letterhead']} of the benchmark's {entries} letters whose letterhead names a Land, the "
        f"postcode suggested that Land for {every['right']}, another Land for none, and none for "
        f"{every['none']}"
    ) in measured
    assert (
        f"of the other {entries - every['letterhead']}, it suggested a Land for {suggested}; "
        f"{others['not_listed']} have a postcode GeoNames doesn't list, {others['foreign']} an address abroad and "
        f"{others['no_postcode']} no postcode"
    ) in measured
    splits = results["splits"]
    scores = ", ".join(
        str(int(splits[name]["with_suggestion"]["due_date_accuracy"]["k"])) for name in PUBLISHED_SPLITS[:-1]
    )
    (n,) = {int(splits[name]["with_suggestion"]["due_date_accuracy"]["n"]) for name in PUBLISHED_SPLITS}
    dev = splits["dev"]["with_suggestion"]["due_date_accuracy"]
    assert all(
        s["with_suggestion"] == s["with_land"] and s["changed_with_suggestion"] == [] for s in splits.values()
    )
    assert all(s["with_suggestion"]["dangerous_late_rate"]["k"] == 0 for s in splits.values())
    assert (
        f"Every split scores what it scores with the letterhead's Land: {scores} and "
        f"{int(splits['holdout3']['with_suggestion']['due_date_accuracy']['k'])} of {n} on test, holdout, holdout2 "
        f"and holdout3, {int(dev['k'])} of {int(dev['n'])} on dev, none late, and no required date differs from the "
        "letterhead replay."
    ) in measured
    lost = sum(
        s["suggestion"][key]["not_visible"]
        for s in splits.values()
        for key in ("none", "not_suggested_without_letterhead_land")
    )
    assert lost == 0 and "No letter lost its suggestion to the visible-text rule." in measured
    right = every["right"]
    one_sided, two_sided = (f"{(1 - alpha ** (1 / right)) * 100:.1f}" for alpha in (0.05, 0.025))
    assert (
        f"0 wrong of {right} puts the rate of wrong suggestions at no more than {one_sided} % with 95 % confidence "
        f"(one-sided; {two_sided} % two-sided), not at zero."
    ) in measured


def test_the_readme_says_when_ordnung_asks_no_question_about_a_sender_s_state() -> None:
    """README Limitations: no question for a postcode listed in two states or not at all, for an address that
    names another country, or against the state the person set for their own town — the lookup's own rules."""
    limitation = _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])
    assert (
        "There is no question when the postcode is listed in two states or not at all (many P.O. box and "
        "large-customer postcodes), when the address names another country, or when it contradicts the state "
        "you set for your own town."
    ) in limitation
    assert suggest_land_why("Am Markt 1, 21039 Musterstadt")[1] == "several_lands"
    assert suggest_land_why("Am Markt 1, 99999 Musterstadt")[1] == "not_listed"
    assert suggest_land_why("1 Rue de l'Exemple, 75001 Paris, France")[1] == "foreign"
    home = Home.of("Am Markt 2, 80331 Musterstadt", "NW")
    assert suggest_land_why("Am Markt 1, 80331 Musterstadt", home=home)[1] == "home_veto"
    assert suggest_land_why("Am Markt 1, 80331 Musterstadt")[1] == "suggested"


def test_the_readme_credits_geonames_for_the_postcode_data() -> None:
    """CC BY 4.0 asks for credit, the licence and the changes: README's credit links the licence file the
    wheel carries (``license-files``)."""
    readme = _flat(_readme())
    assert (
        "Postcode data © [GeoNames](https://www.geonames.org/), [CC BY 4.0]"
        "(https://creativecommons.org/licenses/by/4.0/), reduced to the states of each postcode "
        "([`LICENSE-GeoNames.txt`](src/ordnung/rules/data/LICENSE-GeoNames.txt))."
    ) in readme
    assert (ROOT / "src" / "ordnung" / "rules" / "data" / "LICENSE-GeoNames.txt").is_file()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "src/ordnung/rules/data/LICENSE-GeoNames.txt" in project["license-files"]


def test_the_spec_no_longer_says_nothing_derives_a_sender_s_land_from_a_postcode() -> None:
    """SPEC § 21: the postcode on a sender's letter suggests their Land, as a question (ADR 0019); only the
    person sets it."""
    spec = _flat((ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8"))
    assert "nothing derives it from a postcode" not in spec
    holidays = spec.split("**Holidays.**", 1)[1].split("**", 1)[0]
    assert "only the person sets" in holidays and "0019-a-sender-s-land-is-suggested-never-set.md" in holidays


# --------------------------------------------------------------------------------------------------
# docs/evals.md: rendered from the results files alone
# --------------------------------------------------------------------------------------------------

#: The results files docs/evals.md is rendered from, by ``render_markdown``'s argument (``python -m evals.report``
#: takes the same files: the published run, its re-scoring, the prompt-now runs, each held-out run with its
#: re-scoring, the replay without the sender's Land).
EVALS_PAGE_FILES: dict[str, str | list[str]] = {
    "runs": ["2026-09-25-sonnet-test.json"],
    "rescored": "2026-09-25-sonnet-test-rescored.json",
    "prompt_runs": ["2026-09-30-claude-sonnet-5-test.json", "2026-09-30-claude-sonnet-5-dev.json"],
    "holdout_run": "2026-09-30-claude-sonnet-5-holdout.json",
    "holdout_rescored": "2026-09-30-claude-sonnet-5-holdout-rescored.json",
    "holdout2_run": "2026-10-01-claude-sonnet-5-holdout2.json",
    "holdout2_rescored": "2026-10-06-claude-sonnet-5-holdout2-rescored.json",
    "holdout3_run": "2026-10-06-claude-sonnet-5-holdout3.json",
    "without_land": WITHOUT_LAND,
}
#: The three held-out recordings, each made once: the page's held-out rows.
HELD_OUT_FILES = {
    "holdout": "2026-09-30-claude-sonnet-5-holdout.json",
    "holdout2": "2026-10-01-claude-sonnet-5-holdout2.json",
    "holdout3": "2026-10-06-claude-sonnet-5-holdout3.json",
}


def _evals_page() -> str:
    return (ROOT / "docs" / "evals.md").read_text(encoding="utf-8")


def _evals_section(page: str, heading: str) -> str:
    """The text under ``## {heading}``, up to the next ``## `` heading."""
    return page.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def _held_out_runs() -> dict[str, dict[str, Any]]:
    return {split: _results(name) for split, name in HELD_OUT_FILES.items()}


def test_the_benchmark_page_is_what_its_results_files_render() -> None:
    """docs/evals.md says "Do not edit by hand": rendered again from its results files with the current
    ``evals/report.py``, it is the committed page, every number on it included."""
    from evals import report

    loaded: dict[str, Any] = {
        key: [_results(name) for name in value] if isinstance(value, list) else _results(value)
        for key, value in EVALS_PAGE_FILES.items()
    }
    prompt_note = next(
        run["meta"]["prompt_note"] for run in loaded["prompt_runs"] if run["meta"].get("prompt_note")
    )
    runs = loaded.pop("runs")
    rendered = report.render_markdown(
        runs, chart="assets/eval-due-date-accuracy.png", prompt_note=prompt_note, **loaded
    )
    assert rendered == _evals_page(), (
        "regenerate docs/evals.md with python -m evals.report (see its Reproduce)"
    )


def test_the_benchmark_method_names_every_held_out_split() -> None:
    """Method → Splits names the holdout3 split (variants I and J, written after the code freeze, audited blind,
    recorded once), as evals/generate.py writes it, and every split with adversarial letters."""
    from evals import generate

    method = _flat(_evals_section(_evals_page(), "Method"))
    assert "an adversarial set in the test split and in each held-out split" in method
    assert (
        "Template variants A/B are the dev split, C/D the test split, E/F the holdout split, G/H the holdout2 split "
        "and I/J the holdout3 split; the test split and each held-out split have their own adversarial letters, "
        "dev has none"
    ) in method
    assert (
        "The holdout3 split is a third such sample, written after the code freeze, its labels audited blind, and "
        "recorded once; no prompt and no code change was informed by it."
    ) in method
    assert "I and J to ``holdout3``" in _flat(generate.__doc__ or "")
    assert "The held-out letters keep the families" in method


def test_each_held_out_section_states_its_recording_cost_from_its_results_file() -> None:
    """Every held-out section says what its one recording cost, as the results file's own cost totals add up
    (API-equivalent, per condition) — said once: the holdout and holdout2 notes, written by hand with their
    recordings, state the same sentence, and holdout3, recorded without a note, gets it from its file."""
    from evals.records import SHORT_LABELS

    page = _evals_page()
    for split, run in _held_out_runs().items():
        costs = {condition: m["cost_usd"]["total"] for condition, m in run["metrics"].items()}
        sentence = (
            f"Recording cost ${sum(costs.values()):.2f} (API-equivalent): "
            + ", ".join(f"{SHORT_LABELS[condition]} ${cost:.2f}" for condition, cost in costs.items())
            + "."
        )
        section = _flat(_evals_section(page, f"Held-out run: the {split} split"))
        assert section.count(sentence) == 1, (split, sentence)
    assert "Recording cost $16.48 (API-equivalent)" in _flat(
        _evals_section(page, "Held-out run: the holdout3 split")
    )


def test_each_held_out_section_shows_the_rest_of_the_letter_and_the_adversarial_letters() -> None:
    """The held-out sections publish more than due dates: each has the published run's "Reading the rest of the
    letter" and "Adversarial letters" tables, from its own results file."""
    from evals import report

    page = _evals_page()
    for split, run in _held_out_runs().items():
        section = _evals_section(page, f"Held-out run: the {split} split")
        rest = section.split(f"### Reading the rest of the letter ({split})", 1)[1].split("\n### ", 1)[0]
        adversarial = section.split(f"### Adversarial letters ({split})", 1)[1]
        conditions = list(run["metrics"])
        for key, label in report.EXTRACTION_LABELS.items():
            cells = " | ".join(
                report.rate(run["metrics"][c]["extraction"].get(key), counts=True) for c in conditions
            )
            assert f"| {label} | {cells} |" in rest, (split, key)
        for key in (
            "injection_resisted",
            "conflicting_dates_handled",
            "missing_date_handled",
            "scam_flagged",
        ):
            cells = " | ".join(
                report.rate(run["metrics"][c]["adversarial"].get(key), ci=False, counts=True)
                for c in conditions
            )
            assert f"| {report.ADVERSARIAL_LABELS[key]} | {cells} |" in adversarial, (split, key)


def test_each_held_out_section_counts_the_right_dates_that_came_from_a_wrong_reading() -> None:
    """A right date can come from a reading that differs from the truth's in a way that does not change the date:
    each held-out section counts them for Ordnung (``taxonomy.lucky_reading``) and names the letters and what
    differed, from the results file."""
    page = _evals_page()
    for split, run in _held_out_runs().items():
        lucky = [
            (entry["id"], item["reading_diffs"])
            for entry in run["entries"]
            for item in entry["conditions"]["ordnung"]["score"]["items"]
            if item["outcome"] == "correct" and item["reading_diffs"]
        ]
        assert len(lucky) == run["metrics"]["ordnung"]["taxonomy"]["lucky_reading"]
        section = _flat(_evals_section(page, f"Held-out run: the {split} split"))
        if lucky:
            named = ", ".join(f"`{entry}` ({', '.join(f'`{d}`' for d in diffs)})" for entry, diffs in lucky)
            assert (
                f"{len(lucky)} of Ordnung's right dates came from a reading that differed from the truth's in a way "
                f"that did not change the date: {named}."
            ) in section, split
    assert _held_out_runs()["holdout3"]["metrics"]["ordnung"]["taxonomy"]["lucky_reading"] == 2


def test_pooling_one_held_out_split_gives_its_own_numbers() -> None:
    """The pooled table bootstraps the letters' stored scores as the scorer does: pooled alone, each held-out run
    gives exactly the due-date accuracy, late rate and paired differences its results file holds."""
    from evals import report

    for run in _held_out_runs().values():
        pooled = report.pooled_held_out([run])
        for condition, metrics in run["metrics"].items():
            for key in ("due_date_accuracy", "dangerous_late_rate", "early_rate", "missed_rate"):
                assert pooled["metrics"][condition][key] == metrics[key], (condition, key)
        assert pooled["comparisons"] == run["comparisons"]


def test_only_held_out_runs_of_different_splits_bootstrapped_alike_are_pooled() -> None:
    """A page with one held-out run has no pooled table; two runs of one split, a run without per-letter scores or
    runs bootstrapped with another seed are refused rather than pooled."""
    from evals import report

    third = _held_out_runs()["holdout3"]
    assert report._pooled_section([third]) == ""
    other_seed = {**third, "meta": {**third["meta"], "split": "holdout2", "seed": 1}}
    no_scores = {**third, "meta": {**third["meta"], "split": "holdout2"}, "entries": []}
    for bad, why in (
        ([third, third], "different held-out splits"),
        ([third, other_seed], "different seeds"),
        ([third, no_scores], "no per-letter scores"),
    ):
        with pytest.raises(ValueError, match=why):
            report.pooled_held_out(bad)


def test_the_pooled_held_out_table_adds_up_the_three_recordings() -> None:
    """docs/evals.md "Held-out splits pooled": the three held-out recordings together, as recorded — per
    condition, the exact dates and late dates their results files hold, added up, with intervals over all their
    letters and the paired differences; README's row ¹¹, its footnote and its bullet say the same."""
    from evals import report

    runs = _held_out_runs()
    pooled = report.pooled_held_out(list(runs.values()))
    section = _evals_section(_evals_page(), "Held-out splits pooled")
    letters = sum(run["meta"]["entries"] for run in runs.values())
    items = sum(run["meta"]["scored_items"] for run in runs.values())
    assert (
        f"{letters} letters ({sum(run['meta']['photos'] for run in runs.values())} phone photos, "
        f"{sum(run['meta']['adversarial'] for run in runs.values())} adversarial), {items} required items with a "
        "known date"
    ) in _flat(section)
    counts: dict[str, tuple[int, int]] = {}
    for condition in report.CONDITIONS:
        k = sum(int(run["metrics"][condition]["due_date_accuracy"]["k"]) for run in runs.values())
        late = sum(int(run["metrics"][condition]["dangerous_late_rate"]["k"]) for run in runs.values())
        metrics = pooled["metrics"][condition]
        assert (metrics["due_date_accuracy"]["k"], metrics["due_date_accuracy"]["n"]) == (k, items)
        assert metrics["dangerous_late_rate"]["k"] == late
        assert (
            f"| **{report._label(condition)}** | {report.rate(metrics['due_date_accuracy'])} | {k}/{items} | "
            f"{report.rate(metrics['dangerous_late_rate'], ci=False, counts=True)} |"
        ) in section
        counts[condition] = (k, late)
    for key, value in pooled["comparisons"].items():
        first, second = (report._label(name) for name in key.split("-vs-", 1))
        assert f"- {first} − {second}: accuracy {report.diff(value['due_date_accuracy_diff'])}" in section
    assert counts["ordnung"] == (163, 2) and counts["llm_rules_tool"] == (167, 1)
    # README: row ¹¹, its footnote and its bullet
    readme = _readme()
    ordnung = pooled["metrics"]["ordnung"]
    late = ordnung["dangerous_late_rate"]
    assert (
        f"| **Ordnung**, the three later held-out splits together¹¹ | {_with_interval(ordnung['due_date_accuracy'])} "
        f"| **{_pct(late['value'])} %** ({int(late['k'])} of {int(late['n'])}) | yes |"
    ) in readme
    flat = _flat(readme)
    assert (
        f"¹¹ Rows ⁵, ⁷ and ¹⁰ together, each split as recorded once: {letters} letters "
        f"({sum(run['meta']['photos'] for run in runs.values())} photos, "
        f"{sum(run['meta']['adversarial'] for run in runs.values())} adversarial; {items} dated obligations), the "
        "interval bootstrapped over all of them."
    ) in flat
    assert (
        f"On the same letters the agent with the calculator got {counts['llm_rules_tool'][0]} of {items} right "
        f"({_words(counts['llm_rules_tool'][1])} late), the rules-text prompt {counts['llm_rules_text'][0]} "
        f"({_words(counts['llm_rules_text'][1])} late) and the model alone {counts['llm_only'][0]} "
        f"({_words(counts['llm_only'][1])} late)"
    ) in flat

    def signed(value: float) -> str:
        """Points as README's prose writes them: a minus sign, a plus sign, a plain 0.0."""
        text = f"{value * 100:+.1f}"
        return "0.0" if text in ("+0.0", "-0.0") else text.replace("-", "−")

    def points(name: str) -> str:
        value = pooled["comparisons"][f"ordnung-vs-{name}"]["due_date_accuracy_diff"]
        low, high = value["ci"]
        return f"{signed(value['value'])} points, 95 % interval {signed(low)} to {signed(high)}"

    text, alone, tool = (
        pooled["comparisons"][f"ordnung-vs-{name}"]["due_date_accuracy_diff"]
        for name in ("llm_rules_text", "llm_only", "llm_rules_tool")
    )
    assert text["ci"][0] > 0 and alone["ci"][0] > 0 and tool["ci"][0] < 0 <= tool["ci"][1]
    assert (
        f"**The three later held-out splits together: {_pct(ordnung['due_date_accuracy']['value'])} %.** Pooled "
        f"(row ¹¹), Ordnung is ahead of the rules-text prompt ({points('llm_rules_text')}) and of the model alone "
        f"({points('llm_only')}), and the agent with the calculator is level with it or ahead "
        f"({points('llm_rules_tool')} for Ordnung)"
    ) in flat
    # the first held-out run (the test split) isn't pooled, and there the rules-text prompt was ahead
    first = _results("2026-09-25-sonnet-test.json")["metrics"]
    assert first["llm_rules_text"]["due_date_accuracy"]["k"] > first["ordnung"]["due_date_accuracy"]["k"]
    assert (
        "On the first held-out run, on the test split, the rules-text prompt scored higher than Ordnung"
        in flat
    )
    assert "clearly ahead" not in flat


def test_scam_letters_are_also_scored_as_the_app_decides() -> None:
    """The benchmark counts a scam warning when any warning names a scam (negations aside) or Ordnung's code finds
    an IBAN that fails its checksum; the app shows scam signs for hidden text or a warning its own test calls
    one (``is_scam_warning``), and an IBAN that only fails its checksum is none. Both are on the page for
    Ordnung, on every split; on holdout3 the app catches 1 of the 3 scam letters, the benchmark's rule 2."""
    from evals import report

    from ordnung.secretary.triggers import is_scam_warning

    page = _evals_page()
    sections = {split: _evals_section(page, f"Held-out run: the {split} split") for split in HELD_OUT_FILES}
    sections["test"] = _evals_section(page, "Adversarial letters")
    runs = {**_held_out_runs(), "test": _results("2026-09-25-sonnet-test.json")}
    found: dict[str, tuple[int, int, int, int]] = {}
    for split, run in runs.items():
        scam, alarms = [0, 0], [0, 0]
        for entry in run["entries"]:
            condition = entry["conditions"]["ordnung"]
            prediction, checks = condition["prediction"], condition["score"]["adversarial"]
            answered = not prediction.get("failed") and not prediction.get("error")
            shows = answered and (
                bool(prediction.get("hidden_text"))
                or any(map(is_scam_warning, prediction.get("warnings") or []))
            )
            if "scam_flagged" in checks:
                scam = [scam[0] + shows, scam[1] + 1]
            elif checks.get("scam_false_alarm") is not None:
                alarms = [alarms[0] + shows, alarms[1] + 1]
        found[split] = (*scam, *alarms)
        for key, (k, n) in (("scam_flagged_app", scam), ("scam_false_alarm_app", alarms)):
            cell = report.rate({"value": k / n, "k": k, "n": n}, ci=False, counts=True)
            others = " | ".join("n/a (not the app)" for _ in list(run["metrics"])[1:])
            row = f"| {report.ADVERSARIAL_LABELS[key]} | {cell} | {others} |"
            assert row in sections[split], (split, key)
    assert found["holdout3"] == (1, 3, 0, 51)
    bench = runs["holdout3"]["metrics"]["ordnung"]["adversarial"]
    assert (bench["scam_flagged"]["k"], bench["scam_false_alarm"]["k"]) == (2, 1)


def test_the_app_s_scam_rule_ignores_a_checksum_note_but_not_hidden_text() -> None:
    """``app_scam_sign`` is the app's decision on a reading: a warning only about an IBAN's checksum is no scam
    sign; one that names a scam is, and so is hidden text; a letter without an answer shows nothing."""
    from evals import report

    from ordnung.secretary.scam import invalid_iban_message

    checksum = invalid_iban_message("DE00 1234 5678 9012 3456 78")
    assert not report.app_scam_sign({"warnings": [checksum], "signals": ["invalid_iban"]})
    assert report.app_scam_sign({"warnings": ["This looks like a scam: do not pay."]})
    assert report.app_scam_sign({"warnings": [], "hidden_text": True})
    assert not report.app_scam_sign({"warnings": ["This looks like a scam."], "failed": "no valid answer"})
    assert not report.app_scam_sign(None)


def test_readme_limitations_say_the_interface_is_english() -> None:
    """README Limitations: the app's own words are English (the page is ``lang="en"``, receipts are English on
    purpose and the web app has no translation library); what Claude writes follows the chosen language."""
    limitation = _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])
    assert (
        "The app's own text is in English only: buttons, receipts, the Ideas Ordnung's own rules make, and "
        "notifications. Ordnung reads German letters, and what Claude writes for you (explanations, translations, "
        "Ask's answers, Today's note and the weekly review's Ideas) follows the language you choose in Settings; "
        "letters to German offices stay in German."
    ) in limitation
    # audit (batch A review): the weekly review's Ideas and Today's note are Claude's, in the chosen language
    for module, prompt in (("secretary/review.py", "review_system"), ("secretary/brief.py", "brief_system")):
        source = " ".join((ROOT / "src" / "ordnung" / module).read_text(encoding="utf-8").split())
        assert re.search(rf'"{prompt}",[^)]*language_name=language_name\(', source), module
    assert '<html lang="en">' in (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "English on purpose (the UI is English" in (ROOT / "src/ordnung/rules/explain.py").read_text(
        encoding="utf-8"
    )
    dependencies = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    names = {*dependencies.get("dependencies", {}), *dependencies.get("devDependencies", {})}
    assert not {name for name in names if re.search(r"i18n|intl|lingui|formatjs|polyglot", name)}
    hint = (ROOT / "web/src/features/settings/RegionSection.tsx").read_text(encoding="utf-8")
    assert (
        "Explanations, translations and answers are written in this language. Letters to German offices stay in "
        "German."
    ) in hint


def test_readme_limitations_say_google_and_outlook_get_a_snapshot() -> None:
    """README Limitations: calendar sync logs in to a CalDAV server with a user name and an app password (HTTP
    Basic), which Google Calendar and Outlook.com don't take; they get the calendar file, whose new dates the
    "new dates since your last calendar update" Idea announces."""
    limitation = _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])
    assert (
        "Calendar sync keeps your dates current only in a CalDAV calendar that takes a user name and an app "
        "password (Nextcloud, iCloud, mailbox.org …). Google Calendar and Outlook.com don't offer that, so they get "
        "the calendar file: a snapshot whose alarms fire, but dates from letters read later reach it only when you "
        "download and import the file again (Today's Ideas say when there are new ones)."
    ) in limitation
    caldav = (ROOT / "src/ordnung/calendar/caldav.py").read_text(encoding="utf-8")
    assert "httpx.BasicAuth(username, password)" in caldav and "OAuth" not in caldav
    triggers = (ROOT / "src/ordnung/secretary/triggers.py").read_text(encoding="utf-8")
    assert "new date{'s' if count != 1 else ''} since your last calendar update" in triggers


def _limitations() -> str:
    return _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])


def test_a_date_you_add_without_a_letter_counts_nationwide_holidays_only(store: Store) -> None:
    """README Limitations: a date you add yourself, without a letter, counts its working days with the nationwide
    public holidays only — not your Land's, even once your profile names it (``ingest.plan.own_context``) — and a
    repeating date is one entry at its next day."""
    store.save_profile(Profile(name="Sam Rivera", language="en", region="BY"))
    item = store.add_item(kind="task", title="VAT return", origin="manual", due_date="2026-10-05")
    rules = own_context(store, item, date(2026, 9, 25))
    assert rules.region is None and rules.recipient_region is None
    assert (
        "A date you add without a letter counts working days with the nationwide public holidays only, so where your "
        "Land has a holiday of its own"
    ) in _limitations()
    assert "A repeating date is one entry at its next day" in _limitations()
    assert (
        "add your own dates (Timeline → Add a date, or on a letter's page), also ones that repeat"
        in _flat(_readme())
    )


def test_readme_says_a_letter_for_someone_else_still_counts_as_yours() -> None:
    """README Limitations: a letter addressed to someone else says so, can be filed for them once they are in your
    household (D3) and can be answered in their name, but its dates and numbers count as yours, and Ask and Ideas
    still treat it as yours — there is one person's Ordnung, and My numbers takes a number as yours by its label
    and the letter, never by the addressee."""
    assert (
        "One person's Ordnung, in use on one computer at a time. A letter addressed to someone else (a partner, a "
        "child) says so, you can file it for them once they are in your household, and a reply to it can go out "
        "in their name, but its dates, reminders and numbers count as yours, and Ask and Ideas still treat a "
        "household member's letters as yours."
    ) in _limitations()
    assert "recipient_name" not in (ROOT / "src/ordnung/numbers.py").read_text(encoding="utf-8")


def _churn() -> dict[str, int]:
    """Finding 21's measurement, as ``ordnung.sync.push`` records it: the generated library's letters, its
    database's MiB and slices, and the slices one more reading changed."""
    from ordnung.sync import push

    doc = _flat(push.__doc__ or "")
    found = re.search(
        r"generated library of ([\d,]+) letters .*?an (\d+) MiB database, (\d+) slices\): one more reading changed "
        r"(\d+) slices",
        doc,
    )
    assert found is not None, "the push module no longer records the churn measurement"
    letters, mib, slices, changed = found.groups()
    return {
        "letters": int(letters.replace(",", "")),
        "mib": int(mib),
        "slices": int(slices),
        "changed": int(changed),
    }


def test_readme_limitations_say_how_much_one_save_can_upload() -> None:
    """README Limitations: one save uploads every 1 MiB database slice it changed — measured, one more reading
    changed 29 of a 1,500-letter library's 80 slices (``ordnung.sync.push``); replaced slices go after a day,
    and the provider's version history and trash may keep them."""
    churn = _churn()
    slice_mib = _whole(sync.DB_SLICE, _MIB)
    # audit (batch A review): it said "after a day", but that is only for slices every computer has moved
    # past, and the grace counts Ordnung's running time too (the engine collects garbage so)
    assert sync.GC_GRACE_S == sync.GC_GRACE_RUNTIME_S
    week = {7: "a week"}[_whole(sync.GC_GRACE_RUNTIME_S, _DAY_S)]
    collect = (ROOT / "src" / "ordnung" / "sync" / "engine.py").read_text(encoding="utf-8")
    assert "(SUPERSEDED_SLICE_GRACE_S, SUPERSEDED_SLICE_GRACE_S)" in collect
    assert "if not all(past(head, ref) for head in live)" in collect
    limitation = _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])
    assert (
        f"Hand-off sync saves the database in {slice_mib} MiB slices and uploads every slice a save changed, which "
        f"adds up on a large library: measured on a generated library of {churn['letters']:,} letters and "
        f"{churn['mib']} MiB of database, reading one more letter changed {churn['changed']} of its {churn['slices']} "
        f"slices, about {churn['changed'] * slice_mib} MiB to upload. Once every computer has caught up, Ordnung "
        f"deletes replaced slices after {_SYNC_NUMBERS['slice_grace']()} of its running time (until then, after "
        f"{week} of it), but your provider's version history and trash may keep them longer: on "
        "a metered connection or a small quota, turn version history off for the sync folder if your provider lets "
        "you, and empty its trash now and then."
    ) in limitation
    # why replaced slices go after a day, not after the 7 days of other objects
    assert churn["changed"] * sync.DB_SLICE > sync.SLICE_CHURN_LIMIT_BYTES


def test_readme_json_is_part_of_the_demo_s_recorded_answer() -> None:
    """README "The model reads, code computes" shows "part of its recorded answer" for the demo's tax assessment:
    every key and value of it is in that recording (``src/ordnung/demo/fixtures/extract/85ae2aa7….json``)."""
    section = _readme().split("## The model reads, code computes", 1)[1]
    excerpt = json.loads(section.split("```json\n", 1)[1].split("```", 1)[0])
    (fixture,) = (ROOT / "src" / "ordnung" / "demo" / "fixtures" / "extract").glob("85ae2aa7*.json")
    reading = json.loads(json.loads(fixture.read_text(encoding="utf-8"))["response"]["text"])
    (item,) = [item for item in reading["items"] if item["quote"] == excerpt["quote"]]

    def part_of(part: dict[str, Any], whole: dict[str, Any]) -> bool:
        return all(
            key in whole and (part_of(value, whole[key]) if isinstance(value, dict) else whole[key] == value)
            for key, value in part.items()
        )

    assert part_of(excerpt, item)
    # the letter whose receipt the README shows next (posted Tue 15 Sep 2026)
    assert reading["document_date"] == "2026-09-15"


async def test_readme_names_exactly_the_rules_tools() -> None:
    """README: the rules engine as MCP tools — the four it names are the rules-only server's."""
    paragraph = _readme().split("**The deadline engine in Claude Desktop or Claude Code.**", 1)[1]
    paragraph = paragraph.split("```", 1)[0]
    named = set(re.findall(r"`([a-z_]+)`", paragraph))
    listed = {tool.name for tool in await build_rules_server().list_tools()}
    assert named == listed


@pytest.mark.parametrize("document", ["README.md", "docs/decisions/0001-claude-cli-as-the-model-runtime.md"])
def test_the_claude_code_version_needed_is_the_one_ordnung_checks(document: str) -> None:
    """README's Install and ADR 0001 name the oldest Claude Code that ``ordnung doctor`` and the app accept."""
    assert f"Claude Code {version_text(MIN_CLAUDE_VERSION)} or newer" in _flat(
        (ROOT / document).read_text(encoding="utf-8")
    )


def test_readme_installs_claude_code_as_anthropic_s_setup_page_does() -> None:
    """README's Install: Anthropic's installer per system (no Node.js), and the plans that include Claude Code."""
    install = _flat(_readme().split("## Install and run", 1)[1].split("```", 1)[0])
    assert "curl -fsSL https://claude.ai/install.sh | bash" in install
    assert "irm https://claude.ai/install.ps1 | iex" in install
    assert "Node.js" not in install and "`claude update`" in install
    assert "the free Claude plan doesn't include Claude Code" in install


def test_readme_lists_every_template_letter() -> None:
    """README's *template letters* list has one entry per template the composer offers."""
    listed = _readme().split("*template letters* — ", 1)[1].split(" · ", 1)[0]
    entries = [entry.strip() for entry in listed.replace("\n", " ").split(",")]
    assert len(entries) == len(TEMPLATES) == 8


def test_readme_demo_has_25_letters_three_in_new_mail() -> None:
    """README: the demo is 25 letters, three of them unopened in the New-mail tray."""
    documents = json.loads((ROOT / "src/ordnung/demo/samples/manifest.json").read_text(encoding="utf-8"))[
        "documents"
    ]
    assert "Musterstadt: 25 letters" in _readme() and len(documents) == 25
    assert "three unopened letters" in _readme() and sum(1 for d in documents if d.get("tray")) == 3


#: README's two pictures that come from the real app, not the demo: the demo never opens itself to a network
#: and never syncs (``web/e2e/readme-pictures.spec.ts``, run by ``make capture``).
_REAL_APP_PICTURES = ("pair-phone.png", "your-computers.png")


def _images(markdown: str) -> list[tuple[str, str | None]]:
    """Every ``<img>`` in ``markdown``: its ``src`` and its ``alt`` (``None`` when it has none)."""
    found = []
    for tag in re.findall(r"<img\b[^>]*>", markdown):
        src = re.search(r'\bsrc="([^"]*)"', tag)
        alt = re.search(r'\balt="([^"]*)"', tag)
        assert src, tag
        found.append((src.group(1), alt.group(1) if alt else None))
    return found


def _tour() -> str:
    return _readme().split("\n## A tour\n", 1)[1].split("\n## ", 1)[0]


def test_readme_tour_shows_phone_access_and_hand_off_sync() -> None:
    """README's tour pictures phone access and hand-off sync, in a row of their own with alt text that names
    neither the pairing code nor the two words (both change on every capture); a footnote says the pictures
    come from the real app and which spec makes them. The "Also" list no longer repeats the two."""
    tour = _tour()
    images = dict(_images(tour))
    for name in _REAL_APP_PICTURES:
        alt = images.get(f"docs/assets/{name}")
        assert alt and alt.strip(), name
    assert "two check words" in images["docs/assets/pair-phone.png"]
    footnote = tour.split("\n‡ ", 1)[1].split("\n\n", 1)[0]
    assert "[`web/e2e/readme-pictures.spec.ts`](web/e2e/readme-pictures.spec.ts)" in footnote
    assert "`make capture`" in footnote and "127.0.0.1" in footnote
    assert "Everything else, apart from the two pictures marked ‡, is `ordnung demo`." in _flat(tour)
    assert tour.count("‡") == 4  # two cells, the sentence above and the footnote
    also = tour.split("**Also:**", 1)[1]
    assert "*your phone at home*" not in also and "*hand-off between your computers*" not in also
    spec = _flat((ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8"))
    assert (
        "the phone pairing and Your computers pictures from the real app (`web/e2e/readme-pictures.spec.ts`), "
        "since the demo has neither"
    ) in spec


def test_readme_tour_pictures_from_the_real_app_are_1440_by_900_pngs() -> None:
    """The two pictures from the real app are PNGs of 1440×900 like the rest of the tour, and small (each about
    120 KB when they were first made)."""
    for name in _REAL_APP_PICTURES:
        data = (ROOT / "docs" / "assets" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
        assert struct.unpack(">II", data[16:24]) == (1440, 900), name
        assert len(data) <= 400_000, name


def test_readme_pictures_exist_and_have_alt_text() -> None:
    """Every picture README shows from ``docs/assets`` is a file in the repo and has alt text (the logo's is empty:
    it is decorative). The two from the real app are checked by the test above."""
    images = [(src, alt) for src, alt in _images(_readme()) if src.startswith("docs/assets/")]
    assert len(images) >= 15
    for src, alt in images:
        assert alt is not None, src
        assert alt.strip() or src == "docs/assets/logo.svg", src
        if Path(src).name not in _REAL_APP_PICTURES:
            assert (ROOT / src).is_file(), src


def _claimed(pattern: str) -> int:
    found = re.search(pattern, _readme())
    assert found, pattern
    return int(found.group(1).replace(",", ""))


def test_readme_backend_test_count_holds() -> None:
    """README's "N+ backend tests" is at most what pytest collects."""
    claimed = _claimed(r"(\d[\d,]*)\+ backend tests")
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # pytest's -q prints "N tests collected"; with the configured -q on top, one "file: N" line per file
    total = re.search(r"(\d+) tests? collected", collected)
    count = (
        int(total.group(1))
        if total
        else sum(int(n) for n in re.findall(r"^tests/\S+: (\d+)$", collected, re.M))
    )
    assert count >= claimed, collected[-500:]


_WEB = ROOT / "web"
#: Skipped without Node and the web app's packages, except where ``ORDNUNG_REQUIRE_MOCK_CHECK=1`` (CI's
#: end-to-end job, which has both toolchains): there a missing toolchain fails, so the README's Vitest and
#: Playwright counts are always checked in CI.
_needs_web = pytest.mark.skipif(
    os.environ.get("ORDNUNG_REQUIRE_MOCK_CHECK") != "1"
    and (shutil.which("node") is None or not (_WEB / "node_modules" / ".bin").exists()),
    reason="needs node and web/node_modules (npm ci in web/)",
)


@_needs_web
def test_readme_vitest_and_playwright_counts_hold() -> None:
    """README's "N+ Vitest tests" and "N+ Playwright tests" are at most what the runners list."""
    env = {**os.environ, "CI": ""}
    vitest = subprocess.run(
        [str(_WEB / "node_modules" / ".bin" / "vitest"), "list"],
        cwd=_WEB,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    assert len([line for line in vitest.splitlines() if " > " in line]) >= _claimed(
        r"(\d[\d,]*)\+ Vitest tests"
    )
    playwright = subprocess.run(
        [str(_WEB / "node_modules" / ".bin" / "playwright"), "test", "--list"],
        cwd=_WEB,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    total = re.search(r"Total: (\d+) tests?", playwright)
    assert total, playwright[-500:]
    assert int(total.group(1)) >= _claimed(r"(\d[\d,]*)\+ Playwright tests")


# --------------------------------------------------------------------------------------------------
# docs/privacy.md — what each feature sends
# --------------------------------------------------------------------------------------------------


def _page(text: str) -> Page:
    return Page.model_validate(
        {
            "doc_id": "doc_x",
            "page": 1,
            "width": 10,
            "height": 10,
            "image_path": "p.jpg",
            "text": text,
            "text_source": "text",
        }
    )


def _party(name: str, **fields: Any) -> Party:
    return Party.model_validate(
        {
            "id": f"pty_{hashlib.sha1(name.encode()).hexdigest()[:12]}",
            "name": name,
            "created_at": NOW,
            "updated_at": NOW,
            **fields,
        }
    )


def test_reading_a_letter_sends_only_the_names_of_known_organisations() -> None:
    """docs/privacy.md: reading a letter sends the names and kinds of known organisations, no numbers
    read from other letters (they used to include passport and staff numbers)."""
    passport_office = _party(
        "Ministry of Interior", kind="authority", identifiers=[{"label": "Passport No.", "value": "X1234567"}]
    )
    employer = _party(
        "Muster Tech GmbH", kind="employer", identifiers=[{"label": "Personalnummer", "value": "10482"}]
    )
    data = ExtractionInput(
        doc_id="doc_x",
        sha256="f" * 64,
        pages=[_page("Rechnung Nr. 1 vom 01.09.2026 über 12,00 EUR.")],
        today="2026-09-25",
        language="en",
        region="NW",
        country="DE",
        person_name="Sam Rivera",
        known_parties=[passport_office, employer],
    )
    request = extraction_request(data, model="sonnet")
    sent = request.prompt + request.system
    assert "Ministry of Interior" in sent and "Muster Tech GmbH" in sent  # the documented part
    assert "X1234567" not in sent and "10482" not in sent


def _privacy_feature_row(feature: str) -> str:
    """docs/privacy.md's row for ``feature`` in "What is sent to Claude, per feature"."""
    text = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    (row,) = [line for line in text.splitlines() if line.startswith(f"| **{feature}** |")]
    return row


@pytest.fixture
def draft_ctx(data_dir: Path) -> Iterator[tuple[AppContext, FakeBackend]]:
    answer = {
        "subject": "",
        "body": "Vielen Dank.",
        "body_translation": "Thank you.",
        "enclosures": [],
        "notes_for_user": [],
    }
    backend = FakeBackend({"draft": answer})
    clock.set_today(TODAY)
    context = build_context(data_dir, backend_obj=backend)
    yield context, backend
    context.close()
    clock.set_today(None)


def _phone_contract(store: Store) -> str:
    """Sam Rivera's profile with an address, and a mobile contract to cancel: its id."""
    store.save_profile(
        Profile(name="Sam Rivera", address="Beispielweg 5\n12345 Musterstadt", language="en", region="NW")
    )
    telecom = store.add_party(
        name="FunkNetz Mobile",
        kind="telecom",
        address="Funkallee 1\n10115 Berlin",
        identifiers=[Identifier(label="Kundennummer", value="4711-0815")],
    ).id
    return store.add_contract(
        name="FunkNetz Mobil",
        category="mobile",
        party_id=telecom,
        customer_number="4711-0815",
        concluded_date="2025-01-10",
        start_date="2025-01-15",
        initial_term_months=24,
        notice_value=1,
        notice_unit="months",
    ).id


def _draft_call(backend: FakeBackend) -> str:
    """What the one ``draft`` call sent to Claude: its prompt and system prompt."""
    (request,) = [call for call in backend.calls if isinstance(call, LLMRequest) and call.purpose == "draft"]
    return request.prompt + request.system


async def test_drafting_a_letter_never_sends_your_address(draft_ctx: tuple[AppContext, FakeBackend]) -> None:
    """docs/privacy.md: your address is never sent, and Ordnung doesn't add your name (the related letter's title and
    summary, sent as read, may still name you); drafting sends the recipient's name (first line)."""
    ctx, backend = draft_ctx
    contract = _phone_contract(ctx.store)
    draft = await compose(ctx, "cancellation", contract_id=contract, instructions="Bitte bestätigen")
    assert "Beispielweg 5" in draft.sender_block  # the letter itself has the address
    sent = _draft_call(backend)
    assert "Beispielweg 5" not in sent and "12345 Musterstadt" not in sent
    assert "10115 Berlin" not in sent
    assert "Sam Rivera" in draft.sender_block and "Rivera" not in sent
    letters = _privacy_feature_row("Letters")
    assert "Ordnung doesn't add your name, or the name a letter goes out in, to the request" in letters
    assert "The related letter's title and summary are sent as they were read" in letters


async def test_a_letter_in_someone_else_s_name_never_sends_that_name(
    draft_ctx: tuple[AppContext, FakeBackend],
) -> None:
    """docs/privacy.md: the name a letter goes out in (``sender_name``, offered when the letter it answers was
    addressed to someone else) heads its sender block, and Claude isn't given it."""
    ctx, backend = draft_ctx
    contract = _phone_contract(ctx.store)
    draft = await compose(ctx, "cancellation", contract_id=contract, sender_name="Alex Rivera")
    assert draft.sender_block.splitlines()[0] == "Alex Rivera"
    assert "Rivera" not in _draft_call(backend)


async def test_the_changelog_says_what_0_2_0_prints_for_a_letter_in_someone_else_s_name(
    draft_ctx: tuple[AppContext, FakeBackend],
) -> None:
    """CHANGELOG, Upgrading: a letter written in someone else's name keeps that name as its signer from the start
    (``drafts.sent_profile``), which 0.2.0 reads only once the letter is sent — and its marking keeps a stored
    signer. So only an unsent letter's PDF made on 0.2.0 shows the person's own name under the signature."""
    ctx, _ = draft_ctx
    contract = _phone_contract(ctx.store)
    draft = await compose(ctx, "cancellation", contract_id=contract, sender_name="Alex Rivera")
    signer = ctx.store.get_sent_signer(draft.id)
    assert signer is not None and signer.name == "Alex Rivera"
    assert letter_profile(ctx.store, draft).name == "Alex Rivera"
    upgrading = _flat((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("\n## ", 2)[1])
    assert (
        "On a computer still on 0.2.0, a letter written in someone else's name prints your name under its "
        "signature until it is marked as sent. Print such letters on an updated computer."
    ) in upgrading


async def test_weekly_review_can_be_switched_off(store: Store) -> None:
    """docs/privacy.md: the weekly Ideas review can be switched off in Settings."""
    ids = seed_ledger(store)
    backend = FakeBackend(
        {
            "brief": {"text": "Good morning."},
            "review": {
                "suggestions": [
                    {
                        "kind": "saving",
                        "title": "Check your ticket",
                        "body": "You pay for a ticket.",
                        "rationale": "An active contract.",
                        "refs": [{"type": "contract", "id": ids["ticket"]}],
                    }
                ]
            },
        }
    )

    class Ctx:
        def __init__(self) -> None:
            self.store = store
            self.llm = LLMService(backend, sink=store)
            self.bus = None

    clock.set_today(TODAY)
    try:
        settings = store.get_settings()
        every_switch_off = {
            name: False
            for name, field in type(settings).model_fields.items()
            if field.annotation is bool and name != "demo"
        }
        store.save_settings(settings.model_copy(update=every_switch_off))
        tick = DailyTick(Ctx())  # type: ignore[arg-type]
        result = await tick.check()
        await tick.stop()
    finally:
        clock.set_today(None)
    assert not result.review_started


# --------------------------------------------------------------------------------------------------
# Phone access — README, docs/privacy.md, ADR 0017, docs/architecture.md and SPEC § 12b
# --------------------------------------------------------------------------------------------------

_ADR_PHONE = ROOT / "docs" / "decisions" / "0017-phone-access-over-the-home-network.md"


def _code(name: str) -> Any:
    """A constant of Ordnung by its dotted name, imported when a test asks for it."""
    module, _, attribute = name.rpartition(".")
    return getattr(importlib.import_module(module), attribute)


def _whole(value: float, unit: float = 1) -> int:
    """``value / unit`` when that is a whole number (a constant the docs give in another unit)."""
    whole, rest = divmod(value, unit)
    assert rest == 0, (value, unit)
    return int(whole)


def _per_hour(kind: str) -> int:
    """How many ``kind`` requests (``ask``, ``model``, ``upload``) one phone may make an hour."""
    limit, window = _code("ordnung.phone.access.DEVICE_LIMITS")[kind]
    assert window == 3600
    return int(limit)


def _shown_characters() -> int:
    """How many characters of a number of the person's a phone shows (``•••• 3000``)."""
    masked = _code("ordnung.phone.mask.mask_value")("DE89 3704 0044 0532 0130 00")
    mark, shown = masked.split()
    assert set(mark) == {"•"} and "DE89370400440532013000".endswith(shown)
    return len(shown)


#: Every number the phone-access docs state, by the name the claims below use, from the constant it
#: names (P1's modules ``ordnung.phone.{access,pairing,tls,record,mask}``; the rest from the contract).
_PHONE_NUMBERS: dict[str, Callable[[], object]] = {
    "port": lambda: _code("ordnung.phone.record.DEFAULT_PORT"),
    "last_port": lambda: _code("ordnung.phone.access.PORTS")[-1],
    "connections": lambda: _code("ordnung.phone.access.LIMIT_CONCURRENCY"),
    "keep_alive_s": lambda: _code("ordnung.phone.access.KEEP_ALIVE_S"),
    "graceful_s": lambda: _code("ordnung.phone.access.GRACEFUL_STOP_S"),
    "watch_s": lambda: _whole(_code("ordnung.phone.access.WATCH_INTERVAL_S")),
    "seen_minutes": lambda: _whole(_code("ordnung.phone.access.SEEN_WRITE_EVERY_S"), 60),
    "code_length": lambda: _code("ordnung.phone.pairing.CODE_LENGTH"),
    "code_bits": lambda: (
        _code("ordnung.phone.pairing.CODE_LENGTH")
        * (len(_code("ordnung.phone.pairing.CODE_ALPHABET")).bit_length() - 1)
    ),
    "code_minutes": lambda: _whole(_code("ordnung.phone.pairing.PAIRING_TTL_S"), 60),
    "tries_per_device": lambda: _code("ordnung.phone.pairing.PAIRING_TRIES_PER_CLIENT"),
    "tries_in_all": lambda: _code("ordnung.phone.pairing.PAIRING_TRIES_TOTAL"),
    "pairs_per_address": lambda: _code("ordnung.phone.pairing.PAIR_POSTS_PER_CLIENT_PER_MINUTE"),
    "pairs_in_all": lambda: _code("ordnung.phone.pairing.PAIR_POSTS_PER_MINUTE"),
    "pair_kib": lambda: _whole(_code("ordnung.phone.pairing.PAIR_MAX_BYTES"), 1024),
    "phones": lambda: _code("ordnung.phone.access.MAX_PHONES"),
    "idle_days": lambda: _code("ordnung.phone.access.DEVICE_IDLE_DAYS"),
    "recent_days": lambda: _code("ordnung.phone.access.RECENT_DAYS"),
    "hourly": lambda: {3600: "an hour"}[_whole(_code("ordnung.phone.access.ROTATE_EVERY_S"))],
    "grace_s": lambda: _whole(_code("ordnung.phone.access.PREVIOUS_GRACE_S")),
    "grace_minutes": lambda: _whole(_code("ordnung.phone.access.PREVIOUS_GRACE_S"), 60),
    "retired": lambda: _code("ordnung.phone.record.RETIRED_KEPT"),
    "asks": lambda: _per_hour("ask"),
    "model_actions": lambda: _per_hour("model"),
    "uploads": lambda: _per_hour("upload"),
    "leaf_days": lambda: _code("ordnung.phone.tls.LEAF_DAYS"),
    "renew_days": lambda: _code("ordnung.phone.tls.RENEW_BEFORE_DAYS"),
    "ca_years": lambda: _whole(_code("ordnung.phone.tls.CA_DAYS"), 365),
    "shown": _shown_characters,
    "cookie_max_age": lambda: _code("ordnung.phone.COOKIE_MAX_AGE_S"),
    "phone_operations": lambda: len(_code("ordnung.phone.scope.PHONE_ROUTES")),
    "computer_operations": lambda: len(_code("ordnung.phone.scope.COMPUTER_ONLY")),
}

#: ``(document, sentence)``: each ``{name}`` is filled in from :data:`_PHONE_NUMBERS`, and the sentence
#: must be in the document (line breaks and indents read as one space).
_PHONE_CLAIMS: list[tuple[str, str]] = [
    ("README.md", "*My numbers* and your profile's IBAN show only their last {shown} characters"),
    ("docs/privacy.md", "*My numbers* and your profile's IBAN show only their last {shown} characters"),
    ("docs/privacy.md", "The code has {code_length} characters, works once, for {code_minutes} minutes"),
    ("docs/privacy.md", "One device gets {tries_per_device} wrong tries for a code"),
    ("docs/privacy.md", "{tries_in_all} wrong tries from your network cancel the code"),
    ("docs/privacy.md", "It lasts {leaf_days} days and is renewed by itself"),
    ("docs/privacy.md", "changes by itself at most once {hourly}"),
    ("docs/privacy.md", "A phone not used for {idle_days} days is forgotten"),
    ("docs/privacy.md", "At most {phones} phones can be paired"),
    (
        "docs/privacy.md",
        "Each phone may ask {asks} questions, start {model_actions} other things that ask Claude and add "
        "{uploads} letters an hour",
    ),
    ("docs/privacy.md", "the Remove dialog counts a phone's changes of the last {recent_days} days"),
    ("docs/privacy.md", "a pairing request of at most {pair_kib} KiB"),
    ("docs/privacy.md", "It takes at most {connections} connections at once"),
    (_ADR_PHONE.name, "a saved port ({port}, or the next free one)"),
    (_ADR_PHONE.name, "it is limited to {connections} connections"),
    (_ADR_PHONE.name, "issues a {leaf_days}-day server certificate"),
    (_ADR_PHONE.name, "a {code_length}-character code ({code_bits} bits)"),
    (_ADR_PHONE.name, "it works once, for {code_minutes} minutes"),
    (_ADR_PHONE.name, "One device gets {tries_per_device} wrong tries for a code"),
    (_ADR_PHONE.name, "{tries_in_all} wrong tries from the whole network cancel the code"),
    (_ADR_PHONE.name, "It changes at most once {hourly} on a page load"),
    (_ADR_PHONE.name, "the previous one stays valid for {grace_minutes} minutes"),
    (_ADR_PHONE.name, "A phone unused for {idle_days} days is forgotten"),
    (
        _ADR_PHONE.name,
        "Each phone may ask Ask {asks} questions, start {model_actions} other things that ask Claude and "
        "add {uploads} letters an hour",
    ),
    (_ADR_PHONE.name, "the Remove dialog counts the changes of the last {recent_days} days"),
    (_ADR_PHONE.name, "a pairing request of at most {pair_kib} KiB"),
    (_ADR_PHONE.name, "show only their last {shown} characters"),
    ("docs/architecture.md", "at most {connections} connections"),
    ("docs/architecture.md", "a {code_bits}-bit code in the URL fragment, once, for {code_minutes} minutes"),
    ("docs/architecture.md", "{tries_per_device} wrong tries per device, {tries_in_all} in all"),
    (
        "docs/architecture.md",
        "at most {pairs_per_address} pairing requests a minute per address and {pairs_in_all} in all",
    ),
    ("docs/architecture.md", "the pairing request must state a length of at most {pair_kib} KiB"),
    ("docs/SPEC.md", "a port ({port}, or the first free one up to {last_port}"),
    (
        "docs/SPEC.md",
        "`limit_concurrency` {connections}, keep-alive {keep_alive_s} s, graceful stop {graceful_s} s",
    ),
    ("docs/SPEC.md", "A watcher (every {watch_s} s while on)"),
    ("docs/SPEC.md", "forgets phones unused for {idle_days} days"),
    ("docs/SPEC.md", "An authority (EC P-256, {ca_years} years)"),
    ("docs/SPEC.md", "a server certificate for the address ({leaf_days} days"),
    ("docs/SPEC.md", "renewed {renew_days} days before its end"),
    (
        "docs/SPEC.md",
        "{code_length} characters of Crockford's base 32 ({code_bits} bits), valid {code_minutes} minutes",
    ),
    ("docs/SPEC.md", "after {tries_per_device} wrong tries one address is locked out of the code"),
    ("docs/SPEC.md", "{tries_in_all} wrong tries in all cancel it"),
    ("docs/SPEC.md", "`too_many_phones` at {phones} phones"),
    (
        "docs/SPEC.md",
        "The gate allows {pairs_per_address} pairing requests a minute per address and {pairs_in_all} in all",
    ),
    ("docs/SPEC.md", "Max-Age={cookie_max_age};"),
    ("docs/SPEC.md", "the previous one and the last {retired} retired ones"),
    ("docs/SPEC.md", "The gate changes it at most once {hourly}, on a page load"),
    ("docs/SPEC.md", "stays valid for {grace_s} s after the phone first uses the new one"),
    (
        "docs/SPEC.md",
        "`PHONE_ROUTES` ({phone_operations} operations) and `COMPUTER_ONLY` ({computer_operations})",
    ),
    (
        "docs/SPEC.md",
        "Per phone and hour: {asks} Ask questions, {model_actions} other model actions (read again, "
        "translate, a new letter, the daily note) and {uploads} letters added",
    ),
    ("docs/SPEC.md", "`PhoneDevice.recent_changes` counts the last {recent_days} days"),
    ("docs/SPEC.md", "last use is saved at most every {seen_minutes} minutes"),
    ("docs/SPEC.md", "a pairing POST of at most {pair_kib} KiB"),
]

_FIELD = re.compile(r"{(\w+)}")


def _doc(name: str) -> str:
    """A document of the claims above, flattened (the ADR by its file name)."""
    path = _ADR_PHONE if name == _ADR_PHONE.name else ROOT / name
    return _flat(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("document", "sentence"),
    _PHONE_CLAIMS,
    ids=[
        f"{Path(document).stem.split('-')[0]}-{'-'.join(_FIELD.findall(sentence))}"
        for document, sentence in _PHONE_CLAIMS
    ],
)
def test_the_phone_access_docs_state_the_code_s_numbers(document: str, sentence: str) -> None:
    """Every number the phone-access docs state is the constant it names, as the code has it: the
    pairing code's length, life and tries, the phones, idle and sign-in times, the hourly limits, the
    certificates' lives, the port and the listener's limits (design § 18.6, with the amendments)."""
    stated = sentence.format(**{name: _PHONE_NUMBERS[name]() for name in _FIELD.findall(sentence)})
    assert stated in _doc(document)


def _example_path(template: str) -> str:
    """An ``/api`` path the template matches (each parameter as ``x1``)."""
    return re.sub(r"{\w+}", "x1", template)


def test_the_iban_mask_on_a_phone_names_the_letters_that_carry_it() -> None:
    """Scope review: README and privacy.md said the profile's IBAN shows only its last characters on a
    phone, while a deposit-return letter written there carries it in full (code writes it into the
    letter). A letter has to print it, so the docs say so, and ADR 0017 lists it as a known limit with why
    it isn't masked there."""
    template = (ROOT / "src" / "ordnung" / "drafts" / "template_letters.py").read_text(encoding="utf-8")
    assert "auf mein Konto mit der IBAN {iban}." in template  # the letter carries it in full
    assert "a letter shows what is printed on it, also one you write there that carries your IBAN" in (
        _flat(_readme())
    )
    privacy = _doc("docs/privacy.md")
    assert "also a letter you write: one that asks for money back on your account" in privacy
    assert "carries your IBAN in full, on the phone too" in privacy
    limits = _flat(_ADR_PHONE.read_text(encoding="utf-8").split("## Consequences and known limits", 1)[1])
    assert "carries the profile's IBAN in full" in limits
    assert "would make the phone's editor save the mask into the letter" in limits


def test_a_paired_phone_cannot_change_settings_back_up_or_delete() -> None:
    """README Limitations: a paired phone "can't change settings, back up or delete" — no settings or
    backup operation, ``DELETE /api/data`` or any other ``DELETE`` (except taking back "answered",
    which deletes no data) is a phone's (design § 16.5)."""
    limitation = _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])
    assert "it can't change settings, back up or delete" in limitation
    assert "It can't delete anything" in _doc("docs/privacy.md")
    operations = phone_scope.PHONE_ROUTES | phone_scope.COMPUTER_ONLY
    answered = ("DELETE", "/api/drafts/{draft_id}/answered")
    refused = {
        ("GET", "/api/settings"),
        ("PUT", "/api/settings"),
        ("GET", "/api/backup"),
        ("POST", "/api/backup"),
    } | {operation for operation in operations if operation[0] == "DELETE" and operation != answered}
    assert ("DELETE", "/api/data") in refused and refused <= operations
    for method, path in sorted(refused):
        assert phone_scope.classify(method, _example_path(path)) != "phone", (method, path)
    assert phone_scope.classify("DELETE", _example_path(answered[1])) == "phone"
    assert {"settings", "backups", "deleting"} <= set(phone_scope.NEVER_ON_PHONE.values())


def test_phone_access_answers_only_on_the_home_network() -> None:
    """README: the phone uses Ordnung "over your home Wi-Fi"; privacy.md: phone access answers "only
    devices on that network — never through a VPN or a tunnel, nor through a container's or a virtual
    machine's network unless your router is on it". The address must be a home-network one (no public,
    shared-carrier, link-local or loopback address), a client must be in its subnet, and a tunnel's
    interface is never offered, a virtual one only on the router's network (design § 16.5, amendment M2)."""
    net = importlib.import_module("ordnung.phone.net")
    assert "over your home Wi-Fi" in _flat(_readme())
    assert (
        "answers only devices on that network — never through a VPN or a tunnel, nor through a container's "
        "or a virtual machine's network unless your router is on it"
    ) in _doc("docs/privacy.md")
    for address in ("8.8.8.8", "100.64.0.1", "169.254.1.1", "127.0.0.1", "::1"):
        assert not net.usable(address), address
    assert net.usable("192.168.1.5") and net.usable("10.0.0.2") and net.usable("172.16.4.9")
    bound, subnet = "192.168.178.23", "192.168.178.0/24"
    for client in ("172.17.0.2", "10.8.0.6", "192.168.1.5", "8.8.8.8"):
        assert not net.client_allowed(client, bound, subnet), client
    assert net.client_allowed("192.168.178.31", bound, subnet)
    for interface in ("utun3", "wg0", "tailscale0", "docker0", "vboxnet0", "vEthernet (WSL)"):
        assert net.is_tunnel(interface), interface
    for interface in ("en0", "wlan0", "Wi-Fi", "eth0"):
        assert not net.is_tunnel(interface), interface
    external = net.Interface("vEthernet (External)", "192.168.178.20", 24, "Hyper-V Virtual Ethernet Adapter")
    docker = net.Interface("docker0", "172.17.0.1", 16, "")
    offered = net.candidate_addresses([external, docker], default="192.168.178.20", router="192.168.178.1")
    assert [c.address for c in offered] == ["192.168.178.20"]
    assert not net.candidate_addresses([external, docker], default="192.168.178.20", router="10.0.0.1")


# --------------------------------------------------------------------------------------------------
# Hand-off sync — README, docs/privacy.md, ADR 0018 (and 0007), docs/architecture.md and SPEC § 12c
# --------------------------------------------------------------------------------------------------

_ADR_SYNC = ROOT / "docs" / "decisions" / "0018-hand-off-sync-through-a-folder-you-already-sync.md"
_ADR_POLICIES = ROOT / "docs" / "decisions" / "0007-short-written-policies-over-growing-heuristics.md"
_MIB = 1024 * 1024
_GIB = 1024 * _MIB
_DAY_S = 24 * 3600


def _sync_doc(name: str) -> str:
    """A document of the hand-off sync claims, flattened (the ADRs by their file names)."""
    path = {_ADR_SYNC.name: _ADR_SYNC, _ADR_POLICIES.name: _ADR_POLICIES}.get(name, ROOT / name)
    return _flat(path.read_text(encoding="utf-8"))


def _sync_operations() -> int:
    """How many operations hand-off sync has (``/api/sync`` and ``/api/sync/…``)."""
    operations = phone_scope.schema_operations(openapi_schema())
    return len({op for op in operations if op[1].split("/")[:3] == ["", "api", "sync"]})


def _superscript(number: int) -> str:
    return "".join("⁰¹²³⁴⁵⁶⁷⁸⁹"[int(digit)] for digit in str(number))


#: Every number the hand-off sync docs state, by the name the claims below use, from the constant it names
#: (``ordnung.sync``, design §27 with the binding amendments).
_SYNC_NUMBERS: dict[str, Callable[[], object]] = {
    "log2_n": lambda: sync.SYNC_KDF.log2_n,
    "log2_n_sup": lambda: _superscript(sync.SYNC_KDF.log2_n),
    "r": lambda: sync.SYNC_KDF.r,
    "p": lambda: sync.SYNC_KDF.p,
    "kdf_mib": lambda: _whole(sync.SYNC_KDF.memory, _MIB),
    "key_file_bytes": lambda: sync.KEY_FILE_BYTES,
    "chunk_mib": lambda: _whole(sync.CHUNK, _MIB),
    "slice_mib": lambda: _whole(sync.DB_SLICE, _MIB),
    "min_padded": lambda: sync.MIN_PADDED,
    "min_padded_kib": lambda: _whole(sync.MIN_PADDED, 1024),
    "seal_header": lambda: sync.SEAL_HEADER_BYTES,
    "seal_tag": lambda: sync.SEAL_TAG_BYTES,
    "record_mib": lambda: _whole(sync.MAX_RECORD_BYTES, _MIB),
    "file_gib": lambda: _whole(sync.MAX_FILE_BYTES, _GIB),
    "max_files": lambda: f"{sync.MAX_FILES:,}",
    "computers": lambda: sync.MAX_COMPUTERS,
    "folder_taken": lambda: f"{sync.FOLDER_TAKEN_MAX:,}",
    "person_quiet_s": lambda: _whole(sync.PUSH_PERSON_QUIET_S),
    "quiet_s": lambda: _whole(sync.PUSH_QUIET_S),
    "max_wait_s": lambda: _whole(sync.PUSH_MAX_WAIT_S),
    "shutdown_s": lambda: _whole(sync.SHUTDOWN_PUSH_S),
    "retry_first_s": lambda: _whole(sync.PUSH_RETRY_S[0]),
    "retry_last_minutes": lambda: _whole(sync.PUSH_RETRY_S[-1], 60),
    "failing_minutes": lambda: _whole(sync.FAILING_AFTER_S, 60),
    "scan_s": lambda: _whole(sync.SCAN_S),
    "damaged_minutes": lambda: _whole(sync.DAMAGED_AFTER_S, 60),
    "wants": lambda: sync.WANTS_MAX,
    "folder_timeout_s": lambda: _whole(sync.FOLDER_OP_TIMEOUT_S),
    "unreachable_minutes": lambda: _whole(sync.UNREACHABLE_SCAN_S, 60),
    "take_over_minutes": lambda: _whole(sync.TAKE_OVER_WAIT_MAX_S, 60),
    "fence_s": lambda: _whole(sync.FENCE_WAIT_S),
    "kept_gib": lambda: _whole(sync.KEPT_WARN_BYTES, _GIB),
    "gc_days": lambda: _whole(sync.GC_GRACE_S, _DAY_S),
    "gc_runtime_days": lambda: _whole(sync.GC_GRACE_RUNTIME_S, _DAY_S),
    "slice_grace": lambda: {1: "a day"}[_whole(sync.SUPERSEDED_SLICE_GRACE_S, _DAY_S)],
    "bits": lambda: _whole(sync.MIN_PASSPHRASE_BITS),
    "token_bits": lambda: _whole(sync.TOKEN_BITS_MAX),
    "words": lambda: sync.SUGGESTED_WORDS,
    "words_word": lambda: {5: "five"}[sync.SUGGESTED_WORDS],
    "min_chars": lambda: MIN_PASSPHRASE_CHARS,
    "max_chars": lambda: MAX_PASSPHRASE_CHARS,
    "service": lambda: sync.SYNC_SERVICE,
    "env": lambda: sync.PASSPHRASE_ENV,
    "operations": _sync_operations,
}

#: ``(document, sentence)``: each ``{name}`` is filled in from :data:`_SYNC_NUMBERS`, and the sentence must be
#: in the document (line breaks and indents read as one space).
_SYNC_CLAIMS: list[tuple[str, str]] = [
    ("README.md", "take the suggested {words_word}-word passphrase"),
    (
        "CHANGELOG.md",
        "now wait up to {shutdown_s} seconds for a running sync operation before closing the database",
    ),
    (
        "docs/privacy.md",
        "saves an encrypted copy into the folder about {person_quiet_s} seconds after a change of yours, "
        "{quiet_s} seconds after Ordnung's own work",
    ),
    ("docs/privacy.md", "at the latest {max_wait_s} seconds after the first change not yet saved"),
    ("docs/privacy.md", "(scrypt, N = 2^{log2_n}, r = {r}: {kdf_mib} MiB of memory to try one passphrase)"),
    (
        "docs/privacy.md",
        "to at least {min_padded_kib} KiB), and the key file is {key_file_bytes} bytes with nothing readable",
    ),
    ("docs/privacy.md", 'service "{service}", an account for this data folder'),
    (
        "docs/privacy.md",
        "must reach about {bits} bits by Ordnung's estimate — {words_word} unrelated words, like the "
        "{words_word}-word one Settings suggests",
    ),
    ("docs/privacy.md", "(and at least {min_chars} characters, as for backups)"),
    ("docs/privacy.md", "Settings warns once they take more than {kept_gib} GiB"),
    (
        "docs/privacy.md",
        "once nothing refers to them for {gc_days} days (of Ordnung's clock and of its running time)",
    ),
    (
        _ADR_SYNC.name,
        "scrypt of the passphrase (2^{log2_n}, r {r}, p {p}: {kdf_mib} MiB, the most a backup reader allows)",
    ),
    (_ADR_SYNC.name, "AES-256-GCM STREAM in {chunk_mib} MiB chunks"),
    (
        _ADR_SYNC.name,
        "(Padmé, at most 12 %, at least {min_padded_kib} KiB); the {key_file_bytes}-byte key file",
    ),
    (
        _ADR_SYNC.name,
        "must reach about {bits} bits by a simple, documented estimator (distinct words and digit runs, each "
        "at most {token_bits} bits;",
    ),
    (_ADR_SYNC.name, "in the web app and the CLI — suggests {words_word} random made-up words"),
    (
        _ADR_SYNC.name,
        "for {gc_days} days of its clock and {gc_runtime_days} × 24 hours of its own running time",
    ),
    (_ADR_SYNC.name, "goes after {slice_grace}"),
    (_ADR_SYNC.name, "At most {computers} computers share one folder."),
    (_ADR_SYNC.name, 'service "{service}", an account per data folder'),
    ("docs/architecture.md", "(N = 2^{log2_n}, r = {r}: {kdf_mib} MiB) in a {key_file_bytes}-byte key file"),
    ("docs/SPEC.md", "exactly {key_file_bytes} bytes"),
    ("docs/SPEC.md", "KEK = scrypt(passphrase, N = 2^{log2_n}, r = {r}, p = {p}; {kdf_mib} MiB)"),
    ("docs/SPEC.md", "{slice_mib} MiB database slices"),
    ("docs/SPEC.md", "AES-256-GCM STREAM in {chunk_mib} MiB chunks (the backup container's core)"),
    (
        "docs/SPEC.md",
        "padded with Padmé (at most 12 %) and to at least {min_padded} bytes; `sealed_size(P) = {seal_header} + "
        "P + {seal_tag} · max(1, ⌈P / CHUNK⌉)`",
    ),
    (
        "docs/SPEC.md",
        "{record_mib} MiB per head, manifest or bucket, {file_gib} GiB per data file, {max_files} files. At most "
        "{computers} computers per folder.",
    ),
    ("docs/SPEC.md", "at most {folder_taken}, so a folder both computers watch"),
    (
        "docs/SPEC.md",
        "{person_quiet_s} s after the person's last write, {quiet_s} s after background work's, at the latest "
        "{max_wait_s} s after the first unsaved one, and when Ordnung stops (at most {shutdown_s} s",
    ),
    (
        "docs/SPEC.md",
        "tried again after {retry_first_s} s, doubling to {retry_last_minutes} minutes; after "
        "{failing_minutes} minutes it is a problem",
    ),
    ("docs/SPEC.md", "every {scan_s} s every head is decrypted"),
    ("docs/SPEC.md", "keeps failing for {damaged_minutes} minutes is damaged"),
    ("docs/SPEC.md", "`wants` (at most {wants})"),
    ("docs/SPEC.md", "Every folder operation gives up after {folder_timeout_s} s"),
    (
        "docs/SPEC.md",
        "while the folder doesn't answer its heads are read every {unreachable_minutes} minutes",
    ),
    ("docs/SPEC.md", "a waiting take-over ends after {take_over_minutes} minutes"),
    ("docs/SPEC.md", "finish within {fence_s} s"),
    ("docs/SPEC.md", "a warning above {kept_gib} GiB in all"),
    ("docs/SPEC.md", "{min_chars}–{max_chars} characters and at least {bits} bits by `passphrase_bits`"),
    ("docs/SPEC.md", "at most {token_bits} bits); setup suggests {words} words"),
    (
        "docs/SPEC.md",
        "an object no head refers to for {gc_days} days of wall clock and {gc_runtime_days} × 24 h of this "
        "computer's running time",
    ),
    ("docs/SPEC.md", "a database slice every live head has moved past goes after {slice_grace}"),
    ("docs/SPEC.md", '`KeyringSecrets(service="{service}", …)`'),
    ("docs/SPEC.md", "`{env}` feeds the CLI"),
    ("docs/SPEC.md", "{operations} operations, every write computer-only"),
    ("docs/SPEC.md", "**Phone**: the {operations} operations are computer-only"),
    ("docs/SPEC.md", "(N = 2{log2_n_sup} r = {r} p = {p}, {kdf_mib} MiB, fixed for the format"),
    ("docs/SPEC.md", "a {key_file_bytes}-byte key file named by its scrypt salt"),
    ("docs/SPEC.md", "padded with Padmé to at least {min_padded} bytes"),
]


@pytest.mark.parametrize(
    ("document", "sentence"),
    _SYNC_CLAIMS,
    ids=[
        f"{Path(document).stem.split('-')[0]}-{'-'.join(_FIELD.findall(sentence)) or 'text'}"
        for document, sentence in _SYNC_CLAIMS
    ],
)
def test_the_hand_off_sync_docs_state_the_code_s_numbers(document: str, sentence: str) -> None:
    """Every number the hand-off sync docs state is the constant it names, as ``ordnung.sync`` has it: the
    key file's scrypt, the format's sizes and caps, when saves happen, the scan, arrival and fence timings,
    the garbage collection's grace, kept copies' warning and the new folder's passphrase rule."""
    stated = sentence.format(**{name: _SYNC_NUMBERS[name]() for name in _FIELD.findall(sentence)})
    assert stated in _sync_doc(document)


def test_the_sync_key_file_takes_the_most_scrypt_a_backup_reader_allows() -> None:
    """ADR 0018: scrypt "256 MiB, the most a backup reader allows" — and no more (a reader refuses beyond)."""
    assert sync.SYNC_KDF.memory == MAX_SCRYPT_BYTES


_ADR_BACKUP = ROOT / "docs" / "decisions" / "0013-backups-and-reminders-outside-the-browser.md"

#: Every number the backup docs state about a new backup's passphrase and key (``ordnung.backup``).
_BACKUP_NUMBERS: dict[str, Callable[[], object]] = {
    "log2_n_sup": lambda: _superscript(DEFAULT_KDF.log2_n),
    "r": lambda: DEFAULT_KDF.r,
    "p": lambda: DEFAULT_KDF.p,
    "kdf_mib": lambda: _whole(DEFAULT_KDF.memory, _MIB),
    "bits": lambda: _whole(sync.MIN_PASSPHRASE_BITS),
    "words_word": lambda: {5: "five"}[sync.SUGGESTED_WORDS],
    "min_chars": lambda: MIN_PASSPHRASE_CHARS,
    "max_chars": lambda: MAX_PASSPHRASE_CHARS,
}

#: ``(document, sentence)`` as :data:`_SYNC_CLAIMS`, filled in from :data:`_BACKUP_NUMBERS`.
_BACKUP_CLAIMS: list[tuple[str, str]] = [
    (
        _ADR_BACKUP.name,
        "a key from scrypt (N = 2{log2_n_sup}, r = {r}, p = {p}: {kdf_mib} MiB, as for a sync",
    ),
    (_ADR_BACKUP.name, "A new backup's passphrase must reach about {bits} bits by the estimator"),
    (
        "docs/privacy.md",
        "passphrase with scrypt (N = 2{log2_n_sup}, r = {r}: {kdf_mib} MiB of memory to try one",
    ),
    (
        "docs/privacy.md",
        "At least {min_chars} characters and about {bits} bits by Ordnung's estimate — {words_word} unrelated "
        "words, like the {words_word}-word one Ordnung suggests",
    ),
    ("docs/SPEC.md", "scrypt parameters N = 2{log2_n_sup} r = {r} p = {p} when written"),
    (
        "docs/SPEC.md",
        "A new backup's passphrase: {min_chars}–{max_chars} characters and at least {bits} bits",
    ),
]


@pytest.mark.parametrize(
    ("document", "sentence"),
    _BACKUP_CLAIMS,
    ids=[
        f"{Path(document).stem.split('-')[0]}-{'-'.join(_FIELD.findall(sentence)) or 'text'}"
        for document, sentence in _BACKUP_CLAIMS
    ],
)
def test_the_backup_docs_state_the_code_s_passphrase_rule_and_key_costs(document: str, sentence: str) -> None:
    """A new backup's passphrase meets a new sync folder's rule, and its key takes the same scrypt costs: the
    docs say so with the numbers ``ordnung.backup`` uses."""
    stated = sentence.format(**{name: _BACKUP_NUMBERS[name]() for name in _FIELD.findall(sentence)})
    path = _ADR_BACKUP if document == _ADR_BACKUP.name else ROOT / document
    assert stated in _flat(path.read_text(encoding="utf-8"))


def test_a_new_backup_takes_the_key_costs_of_a_new_sync_folder() -> None:
    assert DEFAULT_KDF == sync.SYNC_KDF


def test_the_first_save_is_not_ten_seconds_after_a_change_any_more() -> None:
    """The design's first draft saved "about ten seconds after a change"; the person's change is saved after
    ``PUSH_PERSON_QUIET_S`` (review finding 33), so no document may promise ten."""
    assert sync.PUSH_PERSON_QUIET_S < sync.PUSH_QUIET_S
    for document in ("README.md", "docs/privacy.md", "docs/SPEC.md", "docs/architecture.md", _ADR_SYNC.name):
        assert "ten seconds after a change" not in _sync_doc(document), document


def test_the_passphrase_estimator_is_the_one_the_docs_describe() -> None:
    """SPEC § 12c: "runs of letters and runs of digits, split where a lower-case letter meets an upper-case
    one; each distinct token, case-folded, counts its length × log2 26 or × log2 10, at most 14 bits"; the
    privacy page and ADR 0018: five unrelated words reach about 70 bits."""
    assert sync.passphrase_tokens("CorrectHorse battery-staple 2024!") == [
        "Correct",
        "Horse",
        "battery",
        "staple",
        "2024",
    ]
    assert sync.passphrase_bits("ab") == pytest.approx(2 * sync.LETTER_BITS)
    assert sync.passphrase_bits("2971") == pytest.approx(4 * sync.DIGIT_BITS)
    assert sync.passphrase_bits("owl") == sync.TOKEN_BITS_MAX  # three letters already count the most
    # a run (one character again and again, in order, along a keyboard row) about one character, a very
    # common word 7 bits
    assert sync.passphrase_bits("1234") == pytest.approx(sync.DIGIT_BITS + 1)
    assert sync.passphrase_bits("qwertz") == pytest.approx(sync.LETTER_BITS + 1)
    assert sync.passphrase_bits("zzzz") == pytest.approx(sync.LETTER_BITS + 1)
    assert sync.passphrase_bits("password") == sync.COMMON_WORD_BITS
    assert sync.passphrase_bits("verylongword") == sync.TOKEN_BITS_MAX
    assert sync.passphrase_bits("maple Maple MAPLE") == sync.passphrase_bits("maple")
    five = "orbit velvet canyon maple thunder"
    assert sync.passphrase_problem(five) is None
    assert sync.passphrase_bits(five) >= sync.MIN_PASSPHRASE_BITS
    assert sync.passphrase_problem("orbit velvet canyon maple") is not None  # four words aren't enough
    assert sync.passphrase_problem("canyon " * 6) is not None  # one word, again and again
    # a new folder's passphrase is also a backup's: at least 12 characters
    assert sync.passphrase_problem("ab cd ef gh") is not None
    assert unicodedata.normalize("NFC", "Übung") in sync.passphrase_tokens("Übung")


def test_what_stays_on_each_computer_is_what_the_privacy_page_lists() -> None:
    """docs/privacy.md, "What stays on each computer": only the ledger and the letters' files travel; never
    phone access, the calendar connection, the watched folder and what it remembers (but the fingerprints
    of what it brought in), Claude's pause, the morning notification's bookkeeping, nor the privacy-log
    entries of a backup made there, its phone access and its watched folder (review finding 25)."""
    text = _sync_doc("docs/privacy.md")
    assert "Only your ledger and your letters' files travel." in text
    assert sync.SYNCED_DIRS == ("files", "derived", "drafts")
    assert {
        "phone_access",
        "calendar_sync",
        "inbox_seen",
        "inbox_baseline",
        "llm_paused_until",
        "desktop_notified_on",
        "desktop_notify_failed",
    } <= sync.LOCAL_META
    assert {"inbox_dir", "inbox_auto_read", "desktop_notifications", "desktop_notify_time"} <= set(
        sync.LOCAL_SETTINGS
    )
    assert "only a fingerprint of each file it brought in travels" in text
    assert sync.FOLDER_TAKEN_META_KEY in sync.MERGED_META
    assert (
        "the privacy-log entries of a backup made or restored on that computer, of its phone access and of its "
        "watched folder"
    ) in text
    assert "backup.created" in sync.LOCAL_ACTIVITY_KINDS
    assert {"phone.", "folder."} <= set(sync.LOCAL_ACTIVITY_PREFIXES)


def test_the_note_of_a_restore_stays_on_that_computer_too() -> None:
    """docs/privacy.md, "What stays on each computer": the privacy-log entry a restore writes (``backup.restored``)
    is local like a backup's, so the backup reminder counts only copies this computer made or came from."""
    assert {"backup.created", "backup.restored"} <= sync.LOCAL_ACTIVITY_KINDS


def _privacy_section(heading: str) -> str:
    """docs/privacy.md's ``## heading`` section, flattened."""
    text = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    return _flat(text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0])


#: Anthropic's help pages on signing out everywhere and on each device's sessions (their menus change, so the
#: checklist links them rather than naming menus).
CLAUDE_SIGN_OUT_PAGES = (
    "https://support.claude.com/en/articles/10310342-how-do-i-log-out-of-all-active-sessions",
    "https://support.claude.com/en/articles/13124001-managing-your-active-sessions",
)


def test_the_lost_computer_checklist_says_what_to_do_without_legal_periods() -> None:
    """docs/privacy.md, "If your computer is lost or stolen": before, a backup kept elsewhere and an encrypted disk
    (BitLocker or Device encryption on Windows, which Ordnung doesn't check); after, restore the backup, a new sync
    folder with a new passphrase, sign out of Claude by Anthropic's own help pages, the phones' certificate
    authority, the calendar's app password, and the bank account. It states no legal periods and no menu of
    Claude's; README, the changelog and the hand-off sync section link to it."""
    section = _privacy_section("If your computer is lost or stolen")
    for words in (
        "`ordnung restore FILE`",
        "set up a new sync folder with a new passphrase",
        *CLAUDE_SIGN_OUT_PAGES,
        "certificate authority",
        "app password",
        "FileVault",
        "BitLocker",
        "Device encryption",
        "LUKS",
        "your account for direct debits you didn't agree to and tell your bank — it can take them back",
    ):
        assert words in section, words
    assert "§" not in section and "BGB" not in section
    assert "Settings → Claude Code" not in section and "Settings → Account" not in section
    link = "docs/privacy.md#if-your-computer-is-lost-or-stolen"
    assert link in _readme()
    assert link in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "(#if-your-computer-is-lost-or-stolen)" in _sync_doc("docs/privacy.md")


def test_the_backup_docs_say_when_ordnung_reminds_you() -> None:
    """The reminder comes once the newest copy kept elsewhere is more than ``BackupCopy.due_after_days`` old, or
    there is none; Ordnung can't see backups of the whole computer, so they don't count."""
    days = BackupCopy().due_after_days
    assert days == 30
    documents = {
        "docs/privacy.md": _privacy_section("Encrypted backups"),
        "CHANGELOG.md": _flat((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("\n## ", 2)[1]),
        _ADR_BACKUP.name: _flat(_ADR_BACKUP.read_text(encoding="utf-8")),
    }
    for name, text in documents.items():
        assert f"more than {days} days old" in text, name
        assert "Time Machine" in text and "File History" in text, name
    limitations = _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])
    assert "Time Machine" in limitations and "BitLocker" in limitations


def test_the_backup_reminder_s_policy_is_the_one_the_docs_describe() -> None:
    """``ordnung.backup.reminder`` reminds after the days the docs state, counting the backups made here and the
    one a restored copy came from."""
    from ordnung.backup import reminder

    assert reminder.DUE_AFTER_DAYS == BackupCopy().due_after_days
    assert set(reminder.BACKUP_KINDS) == {"backup.created", "backup.restored"}


def test_doctor_checks_the_last_backup_and_disk_encryption_as_the_readme_says(
    data_dir: Path, store: Store
) -> None:
    """README: ``ordnung doctor`` checks your last backup and disk encryption — after the disk's row, and only
    ever as warnings (CI's doctor gate fails only on ``fail``). On Windows there is no disk-encryption row: the
    docs say where BitLocker is instead."""
    from ordnung import doctor

    seed_ledger(store)  # letters, and no backup yet
    checks = doctor.local_checks(data_dir)
    ids = [check.id for check in checks]
    by_id = {check.id: check for check in checks}
    assert ids.index("disk") < ids.index("backup")
    assert by_id["backup"].status == "warn" and "ordnung backup" in (by_id["backup"].fix or "")
    if sys.platform in ("darwin", "linux"):
        assert ids.index("backup") < ids.index("disk_encryption")
        assert by_id["disk_encryption"].status in ("ok", "warn")
    else:
        assert "disk_encryption" not in ids
    (line,) = [line for line in _readme().splitlines() if line.startswith("ordnung doctor ")]
    assert "your last backup" in line and "disk encryption" in line


def test_the_docs_say_what_the_folder_reveals_and_how_it_was_tested() -> None:
    """Review finding 25: the folder reveals bursts of new objects — roughly how many letters and pages are
    added — never their content; and the amendments' testing limits: a simulated sync tool and two data
    folders on one machine, no pass yet on two physical computers."""
    for document in ("docs/privacy.md", _ADR_SYNC.name):
        text = _sync_doc(document)
        assert "roughly how many letters and pages" in text, document
        assert "two physical computers" in text and "still to be done" in text, document
        assert "simulated sync tool" in text, document
    assert "roughly how many letters and pages are added" in _flat(sync.__doc__ or "")
    readme = _flat(_readme())
    assert "simulated sync tool" in readme and "two physical computers" in readme
    assert "two data folders on one machine" in readme


def test_forgetting_a_computer_is_said_not_to_lock_it_out() -> None:
    """Review finding 18: "Forget" removes a lost computer from the folder's list, but it still knows the
    passphrase — the docs say so, and what does shut it out (a new folder with a new passphrase)."""
    assert "doesn't lock that computer out" in _sync_doc("docs/privacy.md")
    assert "set up a new sync folder with a new passphrase" in _sync_doc("docs/privacy.md")
    assert "does not lock it out" in _sync_doc(_ADR_SYNC.name)
    assert "it doesn't lock that computer out" in _sync_doc("docs/SPEC.md")
    assert "Forgetting a lost computer doesn't lock it out" in _flat(_readme())


def test_kept_copies_are_where_the_docs_and_the_backup_policy_say() -> None:
    """Review finding 35: kept copies are backup files inside the data folder (``<data>/sync/kept/``), which the
    backup policy's "never inside the data folder" now leaves to backups you make; they are lost with the disk
    and with Delete everything."""
    from ordnung import backup

    where = f"<data>/{sync.LOCAL_DIR}/{sync.KEPT_DIR}/"
    policy = _flat(backup.__doc__ or "")
    assert where in policy and "lost with this computer's disk and with Delete everything" in policy
    assert "never inside the data folder it backs up" in policy
    for document in (_ADR_POLICIES.name, _ADR_SYNC.name):
        assert where in _sync_doc(document), document
    assert "lost with this computer's disk and with *Delete everything*" in _sync_doc("docs/privacy.md")
    assert sync.KEPT_RE.match("ordnung-kept-2026-10-07-0912.ordnung-backup")
    assert sync.KEPT_RE.match("ordnung-kept-2026-10-07-0912-2.ordnung-backup")


def test_readme_limitations_say_how_ordnung_moves_between_computers() -> None:
    """README Limitations: the "no sync between computers" half became how hand-off sync works and what it
    doesn't do; the phone's half stays (pinned by the phone's own test)."""
    limitation = _flat(_readme().split("## Limitations", 1)[1].split("\n## ", 1)[0])
    assert "no sync between computers" not in limitation
    assert (
        "Ordnung moves between your computers one at a time through a folder you sync yourself; it doesn't "
        "merge changes made on two computers at once (it asks which to keep)"
    ) in limitation
    assert "There is no app-store app." in limitation


async def test_sync_demo_never_syncs(data_dir: Path) -> None:
    """docs/privacy.md, SPEC § 16 and ADR 0018: "The demo never syncs" — the status says so and setting it up
    is refused before anything is looked at."""
    assert "The demo never syncs." in _sync_doc(_ADR_SYNC.name)
    async with api_for(data_dir, demo=True) as api:
        status = (await api.client.get("/api/sync")).json()
        assert (status["available"], status["unavailable"], status["connected"]) == (
            False,
            sync.DEMO_MESSAGE,
            False,
        )
        body = {"folder": str(data_dir.parent / "sync"), "name": "demo", "passphrase": "x" * 12, "keep": None}
        refused = await api.client.put("/api/sync", json=body)
        assert refused.status_code == 409
        assert refused.json() == {"detail": sync.DEMO_MESSAGE, "code": "unavailable"}
    assert not (data_dir.parent / "sync").exists()


# ---- with the sync engine: what the folder holds ----------------------------------------------------------


def _engine() -> Any:
    """The test harness of the sync engine (``tests/sync_harness.py``, ``tests/fakes.py``)."""
    pytest.importorskip("ordnung.sync.engine", reason="the sync engine isn't part of this checkout")
    return importlib.import_module("sync_harness"), importlib.import_module("fakes")


def _all_files(root: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def _ordnung_name(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if sync.TEMP_RE.match(name):
        return len(parts) == 1 or parts[0] in (sync.HEADS_DIR, sync.OBJECTS_DIR)
    if len(parts) == 1:
        return bool(sync.KEY_FILE_RE.match(name))
    if len(parts) == 2:
        return parts[0] == sync.HEADS_DIR and bool(sync.HEAD_RE.match(name))
    return (
        len(parts) == 3
        and parts[0] == sync.OBJECTS_DIR
        and bool(sync.SHARD_RE.match(parts[1]))
        and bool(sync.OBJECT_RE.match(name))
    )


#: A passphrase that passes a new folder's rule, with a letter NFC and NFD spell differently.
_SYNC_PASSPHRASE = "Übermut velvet canyon maple thunder"


@pytest.fixture
def synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A computer with a letter and a note of the person's, connected to a new sync folder and saved."""
    harness, fakes = _engine()
    fakes.use_fast_keys(monkeypatch)
    computer = harness.Computer("anna-laptop", tmp_path / "a", tmp_path / "a-sync")
    try:
        computer.db.save_profile({"name": "Sam Rivera", "region": "NW", "onboarded": True})
        computer.add_letter("Stadtwerke Musterstadt Abschlag 2027")
        result = computer.connect(unicodedata.normalize("NFD", _SYNC_PASSPHRASE))
        assert result.connected
        computer.person_edit("Call Frau Weber about the Abschlag")
        computer.round()
        yield computer
    finally:
        computer.close()


def test_sync_passphrase_is_never_in_the_folder_or_the_data_folder(synced: Any) -> None:
    """docs/privacy.md: the passphrase is "never in the folder, its database, `sync/state.json`, a log, a
    backup or an answer" — neither its NFC nor its NFD bytes, in no file and no name of either folder."""
    needles = {unicodedata.normalize(form, _SYNC_PASSPHRASE).encode() for form in ("NFC", "NFD")} | {
        _SYNC_PASSPHRASE.split()[1].encode() + b" " + _SYNC_PASSPHRASE.split()[2].encode()
    }
    for root in (synced.folder, synced.paths.data_dir):
        for path, content in _all_files(root).items():
            for needle in needles:
                assert needle not in content and needle.decode() not in path, (root, path)


def test_sync_folder_holds_no_plaintext(synced: Any) -> None:
    """docs/privacy.md and ADR 0018: only ciphertext goes into the folder — not the profile's name, a letter's
    title or text, a note, a file of the data folder, a database or a backup; the key file has 92 bytes."""
    files = _all_files(synced.folder)
    assert files
    originals = [content for content in _all_files(synced.paths.data_dir / "files").values()]
    needles = [
        b"Sam Rivera",
        b"Stadtwerke Musterstadt",
        b"Sehr geehrte",
        b"Frau Weber",
        b"SQLite format 3",
        b"ORDNUNG-BACKUP",
        b"%PDF",
        b"ordnung",
        b"Ordnung",
        b"anna-laptop",
        *(original[100:164] for original in originals),
    ]
    for path, content in files.items():
        for needle in needles:
            assert needle not in content, (path, needle)
        if sync.KEY_FILE_RE.match(path):
            assert len(content) == sync.KEY_FILE_BYTES


def test_sync_names_reveal_nothing(synced: Any) -> None:
    """Every name in the folder is one of Ordnung's meaningless names (design §4.1): no ``doc_`` id, date, file
    extension, or the SHA-256 that names an original in the data folder."""
    names = list(_all_files(synced.folder))
    assert names and all(_ordnung_name(name) for name in names), names
    shas = {
        hashlib.sha256(content).hexdigest()
        for content in _all_files(synced.paths.data_dir / "files").values()
    }
    for name in names:
        if sync.TEMP_RE.match(name.rsplit("/", 1)[-1]):
            continue  # a write in progress: `.<16 hex>.tmp`
        flat = name.replace("/", "")
        assert "doc_" not in name and not re.search(r"\d{4}-\d{2}-\d{2}|\.\w{2,4}$", name), name
        assert not any(sha[:16] in flat for sha in shas), name


def test_sync_never_carries_per_computer_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """docs/privacy.md, "What stays on each computer": a computer that joins keeps its own phone access,
    calendar connection, watched folder and its memory, and local settings; the other computer's phone
    certificates, inbox files, session file and lock never arrive."""
    harness, fakes = _engine()
    fakes.use_fast_keys(monkeypatch)
    sim = importlib.import_module("sync_sim")
    a = harness.Computer("anna-laptop", tmp_path / "a", tmp_path / "a-sync")
    b = harness.Computer("desktop", tmp_path / "b", tmp_path / "b-sync")
    try:
        local = {
            "phone_access": '{{"enabled": false, "who": "{who}"}}',
            "inbox_seen": '["{who}-seen"]',
            "inbox_baseline": '["{who}-baseline"]',
            "llm_paused_until": "2026-10-0{n}T10:00:00+00:00",
        }
        for computer, who, n in ((a, "laptop", 1), (b, "desktop", 2)):
            for key, value in local.items():
                computer.db.set_meta(key, value.format(who=who, n=n))
            computer.db.save_settings(
                computer.db.get_settings().model_copy(
                    update={"inbox_dir": f"/home/sam/{who}-scans", "inbox_auto_read": who == "laptop"}
                )
            )
        for name, content in (("phone/ca.pem", b"LAPTOP-PHONE-CERT"), ("inbox/scan.pdf", b"LAPTOP-INBOX")):
            target = a.paths.data_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (a.paths.data_dir / "server.json").write_text('{"token": "LAPTOP-SESSION-TOKEN"}')
        a.db.save_profile({"name": "Sam Rivera", "region": "NW", "onboarded": True})
        a.add_letter("Stadtwerke Abschlag 2027")
        assert a.connect().connected
        sim.SyncToolSim(a.folder, b.folder, __import__("random").Random(1)).settle()
        joined = b.connect()
        assert joined.connected and b.mode == "in_use"
        assert b.letters() == a.letters()
        for key, value in local.items():
            assert b.db.get_meta(key) == value.format(who="desktop", n=2), key
        settings = b.db.get_settings()
        assert (settings.inbox_dir, settings.inbox_auto_read) == ("/home/sam/desktop-scans", False)
        assert b.db.get_profile().name == "Sam Rivera"  # the person's Ordnung did come over
        received = _all_files(b.paths.data_dir)
        for content in (b"LAPTOP-PHONE-CERT", b"LAPTOP-INBOX", b"LAPTOP-SESSION-TOKEN"):
            assert not any(content in data for data in received.values()), content
        for content in (b"LAPTOP-PHONE-CERT", b"LAPTOP-INBOX", b"LAPTOP-SESSION-TOKEN"):
            assert not any(content in data for data in _all_files(a.folder).values()), content
    finally:
        a.close()
        b.close()


def test_sync_letters_are_not_uploaded_again(synced: Any) -> None:
    """README: the computer in use saves "a few seconds after each change" — only what changed: a save without
    changes writes nothing, and a change of the database alone (a to-do marked done, a note) writes no letter
    file again."""
    before = _all_files(synced.folder)
    again = synced.round()
    assert _all_files(synced.folder) == before, again
    synced.person_edit("Marked the Abschlag as paid")
    outcome = synced.round()
    assert outcome.pushed is not None and outcome.pushed.outcome == "pushed"
    assert "f" not in outcome.pushed.kinds_written, outcome.pushed.kinds_written


# --------------------------------------------------------------------------------------------------
# Batch B2 — the tax year and letter export, searchable scans and the moving checklist: README, the
# CHANGELOG, docs/privacy.md, SPEC, docs/architecture.md and ADRs 0020 and 0021
# --------------------------------------------------------------------------------------------------

_ADR_SCANS = ROOT / "docs" / "decisions" / "0020-a-scanner-s-text-is-for-finding-not-reading.md"
_ADR_MOVING = ROOT / "docs" / "decisions" / "0021-a-move-is-said-never-guessed.md"
#: What the app says where a search found a letter only in the text its scanner added (``web/src/lib/copy.ts``).
SCANNER_TEXT_MATCH = "Found in your scanner's text — not checked"
#: The letter page's note on a scan's scanner text (``web/src/features/document/DocumentFooter.tsx``).
SCANNER_TEXT_NOTE = (
    "Ordnung keeps it only so search can find the letter: it isn't checked, isn't shown as the letter's words "
    "and is never sent to Claude."
)
#: Where the privacy page says a scanner's text lives: with the page images, which backups and hand-off sync
#: carry — so never "on this computer only".
SCANNER_TEXT_KEPT = (
    "kept with the letter's page images (so also in backups and hand-off sync), only for search"
)
#: A § citation as the docs write one ("§ 17 Abs. 1 BMG").
_CITATION = re.compile(r"§+ ?\d+[a-z]?(?: Abs\. \d+)?(?: (?:Satz|S\.|Nr\.) \d+)* [A-Z][A-Za-z]+")


def _unreleased(heading: str, changelog: str | None = None) -> str:
    """The CHANGELOG's ``### heading`` lists of what came after 0.2.0, flattened: Unreleased's and, once
    released, those of the versions since (the newest first)."""
    text = changelog if changelog is not None else (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = text.split("\n## 0.2.0 — ", 1)[0].split("\n## ")[1:]
    lists = [
        _flat(section.split(f"\n### {heading}\n", 1)[1].split("\n### ", 1)[0])
        for section in sections
        if f"\n### {heading}\n" in section
    ]
    assert lists, heading
    return " ".join(lists)


def test_the_changelog_claims_still_hold_after_the_next_release() -> None:
    """docs/releasing.md renames "## Unreleased" to the version, and CONTRIBUTING.md starts a new one for the
    next change: the claims about what came after 0.2.0 still find their bullets then."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = changelog.replace(
        "\n## Unreleased\n",
        "\n## Unreleased\n\n### Fixed\n\n- A small fix after the release.\n\n## 0.3.0 — 2026-10-12\n",
        1,
    )
    fix = _flat("- A small fix after the release.")
    for heading in ("Added", "Changed", "Upgrading"):
        assert _unreleased(heading, released) == _unreleased(heading)
    assert _unreleased("Fixed", released) == f"{fix} {_unreleased('Fixed')}"
    assert "**Open Ordnung from your app menu.**" in _unreleased("Added", released)


def _bullet(flat_list: str, lead: str) -> str:
    """The bold-led bullet of a flattened list that starts with ``lead``, up to the next bold-led one."""
    return flat_list.split(f"- {lead}", 1)[1].split(" - **", 1)[0]


def _adr(path: Path) -> str:
    return _flat(path.read_text(encoding="utf-8"))


def _spec() -> str:
    return _flat((ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8"))


def _moving_limitation() -> str:
    """README's Limitations bullet about the moving checklist."""
    (bullet,) = [part for part in _limitations().split(" - ") if "moving checklist" in part]
    return bullet


def test_the_changelog_adds_the_tax_year_searchable_scans_and_the_moving_checklist() -> None:
    """CHANGELOG, Unreleased → Added: the tax year and *Export letters* (only on a click, never from a phone, the ZIP
    not encrypted), searchable scans (search only, marked "not checked", never sent to Claude) and the moving
    checklist (said, never guessed; nothing sent), in the one list with what was there."""
    added = _unreleased("Added")
    taxes = _bullet(added, "**Your tax year, and your letters as files.**")
    for words in (
        "*Inbox → Letters for taxes*",
        "by the date on the letter (else the day it arrived)",
        "dated January–May of the next year",
        "now opens it",
        "*Export letters* (Settings → Data, or *Export these letters…* on a tax year)",
        "`2025/Finanzamt Musterstadt/2025-03-14 Steuerbescheid 2025.pdf`",
        "`index.csv`",
        "It runs only when you click it, on your computer, never from a phone",
        "The ZIP isn't encrypted",
    ):
        assert words in taxes, words
    scans = _bullet(
        added, "**Scans you keep private, or add while Claude isn't connected, can be found by their words.**"
    )
    for words in (
        f"*{SCANNER_TEXT_MATCH}*",
        "kept with the letter's page images for search only",
        "never shown as the letter's words, never used to check a date or an amount, and never sent to Claude",
        "Ask doesn't search it",
        "Scans you added before are caught up in the background",
        "(docs/decisions/0020-a-scanner-s-text-is-for-finding-not-reading.md)",
    ):
        assert words in scans, words
    assert "computer only" not in scans and "on your computer" not in scans
    moving = _bullet(added, "**A moving checklist.**")
    for words in (
        "tick *I moved*",
        "within two weeks of moving in (§ 17 Abs. 1 BMG)",
        "*Not needed*",
        "once you mark a new-address letter to them as sent",
        "Nothing is sent for you, and no row names an address",
        "(docs/decisions/0021-a-move-is-said-never-guessed.md)",
    ):
        assert words in moving, words
    # one list: the new features come after the sender's state and before the CI and documentation entries
    assert added.index("**Ordnung suggests a sender's state") < added.index("**Your tax year")
    assert added.index("**A moving checklist.**") < added.index("**CI checks more.**")


def test_the_changelog_fixes_waiting_letters_search_and_says_what_an_older_computer_does() -> None:
    """CHANGELOG, Unreleased: Fixed — a letter added while Claude is missing is found by its PDF's words at once
    (only the first one was); Upgrading — 0.2.0 shows its own tax Idea, whose button opens one letter, finds scans
    by name only, and drops a move when its profile is saved there while it never retires the checklist's rows."""
    assert (
        "A letter added while Claude isn't installed, isn't signed in or is too old is found by the words in its "
        "PDF straight away. Before, only the first such letter was; the others were found by name until Claude "
        "read them."
    ) in _unreleased("Fixed")
    upgrading = _unreleased("Upgrading")
    for sentence in (
        "A computer still on 0.2.0 shows its own tax-season Idea, whose *See the documents* opens one letter "
        "rather than the tax year (and it may count the year's letters slightly differently).",
        "A computer still on 0.2.0 finds a scan only by its name, as before, and deletes its scanner's text with "
        "the letter. A scan Claude reads there keeps its scanner's text until an updated computer receives it by "
        "hand-off sync and removes it.",
        "A computer still on 0.2.0 that receives the moving checklist by hand-off sync shows its rows among its "
        "Ideas and never takes them away, and saving the profile there forgets the move. Update both computers.",
    ):
        assert sentence in upgrading, sentence


def test_readme_names_the_tax_year_the_export_and_the_moving_checklist() -> None:
    """README "Also:" names the three features, and Install says what search finds without Claude: a PDF's own
    text or the text a scanner added (search only), a photo by its name; a waiting letter by its PDF's words."""
    also = _flat(_tour().split("**Also:**", 1)[1])
    for words in (
        "*tax year* — a year's letters for your tax return, by the date on them",
        "*export letters* — your originals as files in folders by year and sender, with a list for a spreadsheet",
        "*moving checklist* — who needs your new address, from your contracts and letters, starting with the "
        "Bürgeramt's two weeks",
    ):
        assert words in also, words
    install = _flat(_readme().split("## Install and run", 1)[1].split("```", 1)[0])
    assert (
        "Without Claude you can still store letters privately, find them by name or by the text in the file (a "
        "PDF's own text, or the text a scanner added to a scan — kept for search only, never checked or sent to "
        "Claude; a photo only by its name) and add your own dates"
    ) in install
    assert "meanwhile search finds it by the words in its PDF" in install


def test_readme_limitations_say_what_the_tax_year_export_scans_and_moving_checklist_can_t_do() -> None:
    """README Limitations: the tax year files a letter by its printed date (else its arrival,
    ``triggers.letter_day``), so its January–May group is a heuristic; Claude marks a letter for taxes and the
    person's *For taxes* choice changes that (``DocumentPatch.tax_choice``, never Claude's own ``tax_relevant``,
    which Ask keeps seeing); the ZIP isn't encrypted; a scanner's text is unchecked; the moving checklist knows
    only the organisations Ordnung has seen."""
    dated = Document.model_construct(doc_date="2026-02-03", received_date="2026-02-06")
    undated = Document.model_construct(doc_date=None, received_date="2026-02-06")
    assert (letter_day(dated), letter_day(undated)) == (date(2026, 2, 3), date(2026, 2, 6))
    assert "tax_relevant" not in DocumentPatch.model_fields
    assert "tax_choice" in DocumentPatch.model_fields
    limitations = _limitations()
    for sentence in (
        "The tax year files a letter by the date printed on it (else the day it arrived), not by the year it is "
        "for",
        "which is why a tax year also lists the letters for taxes dated January–May of the next year, for you to "
        "check — a heuristic",
        README_TAX_LIMIT,
        "The ZIP *Export letters* saves isn't encrypted",
        'The text a scanner adds to a PDF (a "searchable PDF") is kept for search only and isn\'t checked',
    ):
        assert sentence in limitations, sentence
    assert "you can't mark one yourself yet" not in limitations
    assert "Only Claude marks a letter for taxes" not in limitations
    assert _moving_limitation().startswith(
        "The moving checklist knows only the organisations Ordnung has seen in your contracts and letters"
    )


def test_the_tax_idea_opens_the_tax_year_the_docs_describe(store: Store) -> None:
    """SPEC § 9 and the CHANGELOG: the tax-season Idea counts letters by the letter's date (else the day it
    arrived) and *See the documents* opens the tax year — ``open``/``tax_year``/the year, which an older web app
    has no link for (hence its Upgrading line)."""
    seed_ledger(store)
    (idea,) = tax_documents(Ledger(store, date(2026, 3, 1)))
    assert idea.action is not None
    assert (idea.action.type, idea.action.target_type, idea.action.target_id) == ("open", "tax_year", "2025")
    assert (
        "`tax_documents` (Jan–Jul; counted by the letter's date, else the day it arrived; *See the documents* "
        'opens the tax year, `target_type="tax_year"`)'
    ) in _spec()
    assert f"(*{idea.title}*) now opens it" in _unreleased("Added")


def test_the_letters_zip_is_for_the_computer_only_and_leaves_it_only_as_the_zip_you_save() -> None:
    """docs/privacy.md and SPEC: *Export letters* is computer-only (``NEVER_ON_PHONE``: originals leave the computer,
    and the route checks again), writes nothing, and leaves the computer only as the ZIP the person saves, not
    encrypted; a paired phone can't export."""
    operation = ("GET", "/api/documents.zip")
    assert phone_scope.classify(*operation) == "computer"
    assert phone_scope.NEVER_ON_PHONE[operation] == "originals leave the computer"
    (route,) = [r for r in export.router.routes if isinstance(r, APIRoute) and r.path == "/documents.zip"]
    assert route.methods == {"GET"}
    assert any(dependency.dependency is require_computer for dependency in route.dependencies)
    privacy = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    (row,) = [line for line in privacy.splitlines() if line.startswith("| Exported letters")]
    assert "Only as the ZIP you save, where you put it — **not encrypted**" in row and "`index.csv`" in row
    controls = _privacy_section("Your controls")
    assert (
        "it leaves the computer only as the ZIP you save: Ordnung writes nothing for it, sends nothing"
        in controls
    )
    assert "a paired phone can't export" in controls
    assert "export your letters" in _privacy_section("Phone access (optional)")
    spec = _spec()
    assert "`documents.zip` (GET: the letters' original files as one streamed ZIP" in spec
    assert "computer-only, writes nothing)" in spec
    assert "originals (a letter's file and the letters ZIP)" in spec


def test_a_scanner_s_text_is_said_to_travel_with_the_page_images() -> None:
    """docs/privacy.md: a scan's scanner text lives with its page images under ``derived/``, which backups and
    hand-off sync carry (``backup.archive.FOLDERS``, ``sync.SYNCED_DIRS``) — so no document says it stays "on this
    computer only"."""
    assert "derived" in FOLDERS and "derived" in sync.SYNCED_DIRS
    privacy = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    (row,) = [line for line in privacy.splitlines() if line.startswith("| A scanner's text")]
    assert SCANNER_TEXT_KEPT in row and "`scan-text.json`" in row and "never to Claude" in row
    keep_private = (
        _privacy_section("Your controls").split("**Keep private — no AI**", 1)[1].split(" - **", 1)[0]
    )
    assert (
        "the text a scanner added to a scan, kept for search only (a photo only by its name)" in keep_private
    )
    scanner_words = re.compile(
        r"scanner's text|scanner text|text a scanner|text your scanner|scan-text\.json|OCR"
    )
    for name in ("README.md", "CHANGELOG.md", "docs/privacy.md", "docs/SPEC.md", "docs/architecture.md"):
        for chunk in re.split(r"\n\s*\n|\n\s*[-*] |\n\|", (ROOT / name).read_text(encoding="utf-8")):
            if scanner_words.search(chunk):
                assert "computer only" not in _flat(chunk), (name, _flat(chunk)[:160])
    assert "computer only" not in _adr(_ADR_SCANS)


def test_the_moving_docs_cite_no_law_but_the_duty_to_register() -> None:
    """The moving checklist states one law, § 17 Abs. 1 BMG (registering within two weeks of moving in): ADR 0021
    and the CHANGELOG's entry cite no other, and README's Limitations bullet none."""
    for name, text in (
        ("ADR 0021", _adr(_ADR_MOVING)),
        ("CHANGELOG", _bullet(_unreleased("Added"), "**A moving checklist.**")),
    ):
        cited = _CITATION.findall(text)
        assert cited and set(cited) == {"§ 17 Abs. 1 BMG"}, (name, cited)
        assert text.count("§") == len(cited), name
    assert "§" not in _moving_limitation()


def test_a_move_is_said_never_guessed_as_the_docs_say() -> None:
    """ADR 0021 and SPEC § 4: a move is two keys of the profile the person sets (``moved_on``, ``None`` until they
    say they moved, ``""`` clears it; ``old_address``), so no migration — and a 0.2.0 computer, which ignores keys
    it doesn't know, drops them when it saves the profile (the Upgrading line)."""
    profile = Profile()
    assert profile.moved_on is None and profile.old_address == ""
    assert {"moved_on", "old_address"} <= set(ProfilePatch.model_fields)
    assert Profile.model_config.get("extra") == "ignore"
    adr = _adr(_ADR_MOVING)
    for words in (
        "Only the person sets `Profile.moved_on`",
        "no route, no column and no migration",
        "Nothing is sent, paid or cancelled",
    ):
        assert words in adr, words
    assert "`Profile.moved_on` (`null`: no move told) and `Profile.old_address`" in _spec()


#: The button in Settings → Profile for someone who saved the new address first (``ProfileSection.tsx``).
LATE_MOVE = "Moved recently? Start the moving checklist"


def test_a_move_can_be_told_after_the_new_address_was_saved_as_the_docs_say() -> None:
    """ADR 0021, SPEC, the CHANGELOG and docs/privacy.md: a move is told with *I moved* next to a changed address, or,
    once the new address is saved, with the button the web app shows — no doc says ticking *I moved* is the only way.
    The letter composer's note (``TemplateFields.tsx``) no longer says to change the address and tick it."""
    web = ROOT / "web" / "src" / "features"
    assert LATE_MOVE in _flat((web / "settings" / "ProfileSection.tsx").read_text(encoding="utf-8"))
    for name, text in (
        ("ADR 0021", _adr(_ADR_MOVING)),
        ("CHANGELOG", _bullet(_unreleased("Added"), "**A moving checklist.**")),
        ("SPEC", _spec()),
    ):
        assert "I moved*" in text and f"*{LATE_MOVE}*" in text, name
    privacy = _flat((ROOT / "docs" / "privacy.md").read_text(encoding="utf-8"))
    assert "after you tick *I moved*" not in privacy and "after you tell Ordnung you moved" in privacy
    note = _flat((web / "letters" / "TemplateFields.tsx").read_text(encoding="utf-8"))
    assert "tick <em>I moved</em>" not in note and "tell Ordnung you moved" in note


def test_adrs_0020_and_0021_exist_and_the_readme_lists_them() -> None:
    """Two new decisions, numbered after ADR 0019 and listed in README's Documentation: a scanner's text is for
    finding, not reading (0020); a move is said, never guessed (0021)."""
    titles = {
        _ADR_SCANS: "# ADR 0020 — A scanner's text is for finding, not reading",
        _ADR_MOVING: "# ADR 0021 — A move is said, never guessed",
    }
    documentation = _flat(_readme().split("## Documentation", 1)[1].split("\n## ", 1)[0])
    for path, title in titles.items():
        text = path.read_text(encoding="utf-8")
        assert text.startswith(title + "\n"), path.name
        assert "**Status:** accepted" in text, path.name
        assert f"(docs/decisions/{path.name})" in documentation, path.name
    assert "[0020 a scanner's text is for finding, not reading]" in documentation
    assert "[0021 a move is said, never guessed]" in documentation


def test_the_scanner_text_s_file_marker_and_note_are_the_ones_the_docs_quote() -> None:
    """ADR 0020, SPEC § 8 and the CHANGELOG: the file is ``derived/<doc>/scan-text.json``, at most 20,000 characters
    a page; a letter found only by it is marked with the words the web app shows, and its page says what the text
    is kept for."""
    assert scan_text.NAME == "scan-text.json"
    assert scan_text.path(Path("derived"), "doc_x") == Path("derived/doc_x/scan-text.json")
    assert f"at most {scan_text.MAX_PAGE_CHARS:,} characters a page" in _spec()
    copy = (ROOT / "web" / "src" / "lib" / "copy.ts").read_text(encoding="utf-8")
    assert f'SCANNER_TEXT_MATCH = "{SCANNER_TEXT_MATCH}"' in copy
    footer = _flat(
        (ROOT / "web" / "src" / "features" / "document" / "DocumentFooter.tsx").read_text(encoding="utf-8")
    )
    assert SCANNER_TEXT_NOTE in footer
    adr = _adr(_ADR_SCANS)
    assert SCANNER_TEXT_NOTE in adr and f"*{SCANNER_TEXT_MATCH}*" in adr


def test_only_the_store_reads_the_scanner_text_as_adr_0020_says() -> None:
    """ADR 0020: only ``Store`` reads and writes the scanner text — no other module imports ``ordnung.db.scan_text``,
    so Ask, the reading, the evidence checks and prompts can't reach it; a waiting letter's own text is read at
    once, and the worker catches up older scans 30 seconds after Ordnung starts."""
    package = ROOT / "src" / "ordnung"
    imports = re.compile(
        r"^\s*(?:from ordnung\.db import .*\bscan_text\b|from ordnung\.db\.scan_text |import ordnung\.db\.scan_text)",
        re.M,
    )
    importers = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if imports.search(path.read_text("utf-8"))
    }
    assert importers == {"db/store.py"}, importers
    assert callable(pipeline.read_text_here) and callable(pipeline.catch_up_scan_text)
    assert worker.CATCH_UP_DELAY_S == 30
    adr = _adr(_ADR_SCANS)
    assert "Only `Store` reads and writes it" in adr and "30 seconds after Ordnung starts" in adr


def test_the_export_s_folders_list_and_name_are_the_ones_the_docs_show() -> None:
    """SPEC § 13 and the CHANGELOG: ``<year>/<sender>/<date> <title>.<ext>`` with ``Undated`` and ``Sender
    unknown``, ``index.csv`` (a BOM, semicolons) at the root, and the ZIP's name."""
    assert letters_zip.INDEX_NAME == "index.csv"
    assert (letters_zip.UNDATED, letters_zip.SENDER_UNKNOWN) == ("Undated", "Sender unknown")
    choice = letters_zip.Choice(year=2025, tax=True)
    assert letters_zip.zip_name(choice, date(2026, 10, 9)) == "ordnung-letters-for-taxes-2025.zip"
    spec = _spec()
    assert "`<year>/<sender>/<date> <title>.<ext>` (`Undated`, `Sender unknown`)" in spec
    assert "`index.csv` (UTF-8 with a BOM, semicolons" in spec
    assert "`ordnung-letters[-for-taxes][-<year>|-<today>].zip`" in spec


def test_the_moving_checklist_s_window_and_law_are_the_code_s() -> None:
    """ADR 0021, SPEC and the CHANGELOG: a move counts for the last six months or the next three (422 otherwise),
    the list ends six months after it, and its one law is the one Ask's check knows (``IDEA_LAWS``)."""
    assert (moving.MOVE_WINDOW_DAYS, moving.MOVE_AHEAD_DAYS) == (180, 90)
    assert triggers.REGISTRATION_LAW == "§ 17 Abs. 1 BMG" and triggers.REGISTRATION_LAW in triggers.IDEA_LAWS
    assert "moved_house" in triggers.TRIGGERS
    for text in (_adr(_ADR_MOVING), _bullet(_unreleased("Added"), "**A moving checklist.**")):
        assert "a move in the last six months or the next three" in text
        assert "ends six months after the move" in text
    assert moving.MOVE_WINDOW_PROBLEM in _spec()


def test_no_moving_row_carries_an_address_as_the_privacy_page_says(store: Store) -> None:
    """docs/privacy.md: the moving checklist's rows never contain an address — neither the new nor the old one —
    though their titles reach *Weekly Ideas* and the daily note like every Idea's."""
    seed_ledger(store)
    store.save_profile(
        store.get_profile().model_copy(
            update={
                "address": "Neue Straße 7\n12345 Musterstadt",
                "old_address": "Beispielweg 5\n12345 Musterstadt",
                "moved_on": "2026-09-24",
            }
        )
    )
    rows = moving.moving_ideas(Ledger(store, TODAY))
    assert rows
    for row in rows:
        words = f"{row.title} {row.body} {row.rationale}"
        for line in ("Neue Straße", "Beispielweg", "12345"):
            assert line not in words, (row.title, line)
    assert (
        "Its rows never contain an address: like every Idea's, their titles (an organisation's name, the day to "
        "register by) are part of what *Weekly Ideas* and the daily note send."
    ) in _flat((ROOT / "docs" / "privacy.md").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------------
# Batch C — open Ordnung from the app menu (`ordnung shortcut`) and releases from a version tag: README, the
# CHANGELOG, docs/privacy.md, SPEC, docs/architecture.md and ADR 0013
# --------------------------------------------------------------------------------------------------

_ADR_OUTSIDE = ROOT / "docs" / "decisions" / "0013-backups-and-reminders-outside-the-browser.md"
#: What the sign-in page (``api/security.py``) and the web app's "isn't running" card (``screens.tsx``) say
#: before their commands.
OPEN_FROM_YOUR_APPS = "If you added Ordnung to your apps with “ordnung shortcut”, open it from there."


def _without_a_terminal() -> str:
    """README Install's paragraph *Without a terminal*, with its list, flattened."""
    install = _readme().split("## Install and run", 1)[1]
    return _flat(install.split("**Without a terminal.**", 1)[1].split("\n**On your phone.**", 1)[0])


def _privacy() -> str:
    return _flat((ROOT / "docs" / "privacy.md").read_text(encoding="utf-8"))


def test_the_changelog_adds_the_app_menu_shortcut_and_releases() -> None:
    """CHANGELOG, Unreleased → Added: `ordnung shortcut` (the three places, signed in, a window of its own whose
    closing stops Ordnung, never started unseen, the mark, --dry-run and --remove, Settings, not the demo) and
    releases from a tag, PyPI only once the owner has set it up — in the one list, after the moving checklist."""
    added = _unreleased("Added")
    launcher = _bullet(added, "**Open Ordnung from your app menu.**")
    for words in (
        "`ordnung shortcut` adds Ordnung to your app menu on Linux, to the Applications folder in your home "
        "folder on a Mac (Launchpad and Spotlight find it), or to the Start menu on Windows.",
        "Opening it signs your browser in.",
        "When Ordnung isn't running, it starts in a window of its own, and closing that window stops it.",
        "Ordnung is never started without a window you can see.",
        "When it already runs (for example from start at login), only the browser opens.",
        "prints what it writes before writing, needs no admin rights and never replaces or removes a file it "
        "didn't write",
        "`--dry-run` only prints, and `ordnung shortcut --remove` takes it out again",
        "Settings → Reminders shows whether it is there, and for which data folder. It also says when the "
        "command has to run again (Ordnung was installed somewhere else), and when a launcher Ordnung didn't "
        "write is in the way.",
        "The demo isn't added: it opens with `ordnung demo`.",
    ):
        assert words in launcher, words
    releases = _bullet(added, "**Releases.**")
    for words in (
        "A version tag builds the wheel and the source package, checks them, and publishes a GitHub Release with "
        "this changelog's section.",
        "Publishing to PyPI waits until the owner has set it up ([docs/releasing.md](docs/releasing.md)): until "
        "then a release goes to GitHub only.",
        "Trusted Publishing, so no token is stored anywhere",
        "a pull request never publishes",
        "On PyPI the README's links and pictures point to GitHub.",
    ):
        assert words in releases, words
    assert (
        added.index("**A moving checklist.**")
        < added.index("**Open Ordnung from your app menu.**")
        < added.index("**Releases.**")
        < added.index("**CI checks more.**")
    )


def test_the_sign_in_page_and_the_isn_t_running_screen_send_you_to_your_apps_first() -> None:
    """CHANGELOG, Unreleased → Changed, and the code it describes: the sign-in page and the web app's "isn't
    running" / "open from its link" card name the shortcut before the commands that start Ordnung."""
    assert (
        "The sign-in page and the *isn't running* screen say to open Ordnung from your apps if you added it "
        "there with `ordnung shortcut`, before the commands that start it."
    ) in _unreleased("Changed")
    assert OPEN_FROM_YOUR_APPS in (ROOT / "src" / "ordnung" / "api" / "security.py").read_text(
        encoding="utf-8"
    )
    screens = (ROOT / "web" / "src" / "app" / "screens.tsx").read_text(encoding="utf-8")
    assert re.search(
        r"If you added Ordnung to your apps with <code[^>]*>ordnung shortcut</code>, open it from there\.",
        screens,
    )


def test_the_changelog_says_serve_and_autostart_point_to_the_shortcut() -> None:
    """CHANGELOG, Unreleased → Changed, and the CLI lines it describes: `ordnung serve` in a terminal suggests
    the shortcut while there is none, and `ordnung autostart enable` says the app opens from the app menu too."""
    assert (
        "`ordnung serve` in a terminal suggests `ordnung shortcut` for its data folder while Ordnung isn't in your "
        "app menu, and `ordnung autostart enable` says you can open the app from there too."
    ) in _unreleased("Changed")
    cli = (ROOT / "src" / "ordnung" / "cli.py").read_text(encoding="utf-8")
    assert "Open it without a terminal next time: {escape(shortcut.command(data_dir))}" in cli
    assert (
        "({escape(shortcut.command(folder))} " in cli
        and 'f"adds it) or with: {escape(serve_command)}"' in cli
    )


def test_readme_says_how_to_open_ordnung_without_a_terminal() -> None:
    """README "Also:" names the shortcut, and Install has `ordnung shortcut` in the commands and a paragraph on
    each system's launcher, what a click does in both states, the recorded PATH, --remove, the Linux terminal,
    the Mac's first launch and Windows' opt-out, and what CI doesn't test."""
    also = _flat(_tour().split("**Also:**", 1)[1])
    assert (
        "*app-menu shortcut* — open Ordnung from your app menu, Start menu or Applications folder, signed in, "
        "without a terminal"
    ) in also
    commands = _readme().split("## Install and run", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
    assert (
        "ordnung serve                   # the web app on http://127.0.0.1:8765\n"
        "ordnung shortcut                # Ordnung in your app menu: opens it signed in, no terminal needed\n"
    ) in commands
    text = _without_a_terminal()
    for words in (
        "`ordnung shortcut` puts Ordnung where your computer keeps its apps: an entry in your app menu on Linux, "
        f"`{shortcut.BUNDLE}` in the Applications folder of your home folder on a Mac (Launchpad, Spotlight and "
        "the Dock take it), or a shortcut in your Start menu on Windows.",
        "It prints what it writes, and where, before writing anything, and needs no admin rights; `--dry-run` "
        "only prints.",
        "Opening it signs your browser in. When Ordnung isn't running, it starts in a window of its own, and "
        "closing that window stops Ordnung;",
        "when it already runs (for example because it starts at login), only the browser opens",
        "Ordnung is never started without a window you can see.",
        "On Linux and macOS it records this terminal's `PATH`, as start at login does, so Ordnung finds the "
        "same `claude`: run `ordnung shortcut` again after moving Claude Code.",
        "`ordnung shortcut --remove` takes it out again. It never replaces or removes a file it didn't write, "
        "and it doesn't add the demo, which opens with `ordnung demo`.",
        "**Linux:** the entry asks your desktop for a terminal window to run in.",
        "on a desktop without a terminal it knows (some minimal window managers), opening the entry does nothing "
        "visible: start Ordnung with `ordnung serve` there.",
        "**macOS:** Launchpad and Spotlight can take a moment to list the new app.",
        "macOS warns about an unidentified developer only for apps downloaded from the internet.",
        "Terminal asks before you close that window while Ordnung runs.",
        "**Windows:** right-click it in the Start menu to pin it to the taskbar.",
        "A shortcut can't carry `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`: when it is set in your terminal, "
        "`ordnung shortcut` prints the `setx` command that sets it for your account.",
        "opening it from the desktop's own menu isn't tested on any system.",
    ):
        assert words in text, words


def test_readme_updating_says_to_close_the_shortcut_s_window_and_add_it_again_once_python_moved() -> None:
    """README Updating: the shortcut's window is Ordnung (closing it stops Ordnung), and a launcher whose Python
    moved is made again with `ordnung shortcut` (as start at login is)."""
    updating = _flat(_readme().split("### Updating", 1)[1].split("\n## ", 1)[0])
    assert (
        "Stop Ordnung first (Ctrl+C where `ordnung serve` runs, or close the window the shortcut opened;"
        in updating
    )
    assert (
        "If the shortcut stops opening Ordnung after an update (its window closes at once, or nothing opens), "
        "the Python it runs has moved: run `ordnung shortcut` again, and `ordnung autostart enable` too if "
        "Ordnung starts at login."
    ) in updating


def test_the_privacy_page_says_the_shortcut_prints_the_sign_in_link_only_in_its_own_window() -> None:
    """docs/privacy.md, Reminders while Ordnung is closed: one launcher, printed first; PATH and the opt-out as
    start at login (Windows: `setx`); the link only in its own window, never in a log; the Mac's windowless check
    throws its output away. Hardening says to set the opt-out before `ordnung shortcut` too."""
    reminders = _privacy().split("## Reminders while Ordnung is closed", 1)[1].split(" ## ", 1)[0]
    bullet = reminders.split("- **Open from your app menu** (`ordnung shortcut`)", 1)[1].split(" - **", 1)[0]
    for words in (
        "writes one launcher (an app-menu entry, an app in your Applications folder or a Start-menu shortcut) "
        "that runs `ordnung serve`, and prints it before anything else.",
        "It records `PATH` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` like start at login",
        "it prints the `setx` command that sets the opt-out for your account",
        "When Ordnung isn't running, it starts only in a window of its own, so the sign-in link is printed only "
        "there, never into a log or the system journal;",
        "on a Mac the first, windowless check throws its output away.",
        "`ordnung shortcut --remove` removes the launcher.",
    ):
        assert words in bullet, words
    hardening = _privacy().split("## Hardening built into every model call", 1)[1].split(" ## ", 1)[0]
    assert (
        "With start at login or the app-menu shortcut, set it before `ordnung autostart enable` or "
        "`ordnung shortcut`, or run that again after setting it;"
    ) in hardening


def test_adr_0013_says_the_app_menu_shortcut_never_starts_ordnung_unseen() -> None:
    """ADR 0013 (as ADR 0007 asks of a feature that changes an earlier policy): the shortcut's paragraph — one
    launcher of the system's own kind, its mark, `serve --from-shortcut` in a window that is Ordnung, the exit
    code without one, why — with the policy's module, and the header says when."""
    adr = _adr(_ADR_OUTSIDE)
    assert "2026-10-10 (the app-menu shortcut)" in adr.split("## Context", 1)[0]
    para = adr.split("**The app-menu shortcut writes one launcher and never starts Ordnung unseen.**", 1)[1]
    para = para.split(" **", 1)[0]
    for words in (
        f"`{shortcut.DESKTOP_FILE}`",
        f"`{shortcut.BUNDLE}`",
        f"`{shortcut.LNK}`",
        "whose bytes Ordnung writes itself in the shell link format",
        "a file at that place without it is never replaced or removed",
        "The launcher runs `serve --from-shortcut`, which opens a running Ordnung in the browser and otherwise "
        "starts Ordnung only in a terminal window, which is then Ordnung: closing it stops Ordnung,",
        f"Without a terminal it exits with {shortcut.NO_WINDOW_EXIT} and starts nothing",
        "Ordnung has no `stop` command",
        "Policy: `ordnung/shortcut.py`.",
    ):
        assert words in para, words


def test_the_launchers_marks_and_exit_code_in_the_spec_are_the_module_s() -> None:
    """The marks, file names and the exit code SPEC quotes are ``ordnung.shortcut``'s."""
    spec = _spec()
    for name in (
        shortcut.DESKTOP_MARK,
        shortcut.PLIST_MARK,
        shortcut.LNK_MARK,
        shortcut.DESKTOP_FILE,
        shortcut.LNK,
    ):
        assert name in spec, name
    assert f"without one it exits with {shortcut.NO_WINDOW_EXIT} and starts nothing" in spec


def test_the_spec_lists_the_shortcut_module_its_command_and_the_hidden_serve_flag() -> None:
    """SPEC: `shortcut.py` among the modules, a bullet beside start at login, and the CLI list with
    `shortcut [--port N] [--dry-run] [--remove]` and `serve`'s hidden `--from-shortcut`."""
    raw = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    assert "autostart.py  shortcut.py" in raw.split("notify/desktop.py", 1)[1].split("\n", 1)[0]
    spec = _spec()
    bullet = spec.split("- **Open from your app menu** — ", 1)[1].split(" - **", 1)[0]
    for words in (
        "`ordnung shortcut [--port N] [--dry-run] [--remove]` (`shortcut.py`, policy in its docstring; ADR 0013)",
        "`$XDG_DATA_HOME/applications/ordnung.desktop` (`Terminal=true`;",
        "`~/Applications/Ordnung.app`",
        "the per-user Start menu's `Ordnung.lnk` (its bytes written in the shell link format, MS-SHLLINK, by "
        "Ordnung's own code — no COM, no PowerShell",
        "running `<python> -m ordnung --data-dir D serve --from-shortcut`",
        "Refused for the demo.",
        "**Never started unseen:**",
        "the Mac bundle then opens Terminal with its `Ordnung.command`",
        "the hang-up, SIGHUP, or on Windows the console's close event, stops the server as Ctrl+C does, so its "
        "shutdown and clean-up run",
        "A failed start, also one inside the server (uvicorn's own exit code 3 becomes 1), waits for Enter; a "
        "second click while the first start is under way waits up to 15 s",
        "Settings → Reminders shows whether it is there, for which folder, whether it runs this installation "
        "(`current`; otherwise the command again) and whether a launcher Ordnung didn't write is in its place "
        "(`foreign`: move it away first) (`GET /api/reminders/desktop` → `shortcut`, read only;",
        "`ordnung serve` in a terminal suggests it, for its data folder, while there is none.",
    ):
        assert words in bullet, words
    from ordnung.api.routes.reminders import ShortcutInfo

    assert {"current", "foreign"} <= set(ShortcutInfo.model_fields)
    cli = _flat(raw.split("## 15. CLI", 1)[1].split("\n## ", 1)[0])
    assert "`shortcut [--port N] [--dry-run] [--remove]`" in cli
    assert "`serve` also takes a hidden `--from-shortcut`" in cli


def test_the_architecture_shows_the_shortcut_beside_start_at_login() -> None:
    """docs/architecture.md: the launcher in the diagram of what runs while the browser is closed, its bullet,
    the trust boundary to the OS, and its tests in the testing table."""
    arch = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    diagram = arch.split("## While the browser is closed", 1)[1].split("```mermaid", 1)[1].split("```", 1)[0]
    assert "ordnung.desktop · Ordnung.app · Ordnung.lnk<br/>(written by ordnung shortcut)" in diagram
    assert "serve --from-shortcut" in diagram
    flat = _flat(arch)
    assert "- **The app-menu shortcut** (`shortcut.py`) writes one launcher and runs nothing;" in flat
    assert "The app-menu shortcut is a file Ordnung writes too" in flat
    assert "app-menu launchers per system written into temporary home folders" in flat


def test_the_launchers_the_docs_describe_are_the_ones_ordnung_shortcut_writes(tmp_path: Path) -> None:
    """README, SPEC and ADR 0013 against ``ordnung.shortcut`` (batch C's launcher package): where each launcher
    goes, that the Linux entry asks for a terminal, what it runs, the Windows link's mark, the command's
    options, and that CI's macOS and Windows job runs the shortcut's tests (README)."""
    import yaml
    from typer.testing import CliRunner

    from ordnung.cli import app

    folder, home = tmp_path / "data", tmp_path / "home"
    linux = shortcut.plan(folder, platform="linux", env={"PATH": "/usr/bin"}, home=home, python="/opt/py")
    assert linux.path == home / ".local" / "share" / "applications" / shortcut.DESKTOP_FILE
    assert linux.argv[-2:] == ("serve", "--from-shortcut")
    entry = (linux.files[0].content or b"").decode("utf-8").splitlines()
    assert "Terminal=true" in entry and f"{shortcut.DESKTOP_MARK}=1" in entry
    mac = shortcut.plan(folder, platform="darwin", env={"PATH": "/usr/bin"}, home=home, python="/opt/py")
    assert mac.path == home / "Applications" / shortcut.BUNDLE
    assert any(file.path.name == "Ordnung.command" for file in mac.files)
    appdata = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(tmp_path / "Local")}
    windows = shortcut.plan(folder, platform="win32", env=appdata, home=home, python="C:\\py\\python.exe")
    assert windows.path.parts[-4:] == ("Windows", "Start Menu", "Programs", shortcut.LNK)
    assert windows.link is not None and windows.link.description.endswith(shortcut.LNK_MARK)
    help_text = CliRunner().invoke(app, ["shortcut", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"}).output
    for option in ("--remove", "--dry-run", "--port"):
        assert option in help_text, option
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = " ".join(str(step.get("run", "")) for step in ci["jobs"]["other-systems"]["steps"])
    assert "tests/test_shortcut.py" in steps
    assert "autostart entries, app-menu shortcuts and backups" in _flat(_readme())


def test_the_release_the_changelog_describes_waits_for_the_owner_s_pypi_setup() -> None:
    """The CHANGELOG's *Releases* and README's Documentation list against batch C's release package: a pushed
    `v*` tag runs `release.yml`, PyPI only with the repository variable and the `pypi` environment, no stored
    token, and docs/releasing.md says how the owner sets it up."""
    import yaml

    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    release = yaml.safe_load(workflow)
    assert release[True] == {"push": {"tags": ["v*"]}}  # PyYAML reads the key `on` as True
    pypi = release["jobs"]["pypi"]
    assert "vars.PYPI_PUBLISH == 'true'" in pypi["if"] and pypi["environment"]["name"] == "pypi"
    assert "secrets." not in workflow
    releasing = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")
    for words in ("PYPI_PUBLISH", "release.yml", "pending publisher", "`pypi`"):
        assert words in releasing, words
    documentation = _flat(_readme().split("## Documentation", 1)[1])
    link = "[docs/releasing.md](docs/releasing.md): how a release is made, and the one-time setup for PyPI"
    assert link in documentation


# --------------------------------------------------------------------------------------------------
# Batch D1 — weekly repeats, the Windows link's target, mypy on evals/, package updates, Ask's key
# --------------------------------------------------------------------------------------------------

#: Microsoft's own page on Device encryption (it resolved on 2026-10-11, to the reader's language).
DEVICE_ENCRYPTION_PAGE = (
    "https://support.microsoft.com/windows/device-encryption-in-windows-cf7e2b6f-3e70-4882-9532-18633605b7df"
)

#: CHANGELOG, Unreleased → Changed: batch D1's lines.
D1_CHANGED = (
    "Settings → Calendar says that Google Calendar and Outlook.com take the calendar file, not calendar sync, "
    "and *Where do I find these?* lists them with that.",
    "Windows: the Start-menu shortcut names the Python it runs where Windows' shell reads a shortcut's target (an "
    "ID list, as Windows' own shortcuts have); before, the shell found no target in it, though it opened it. Run "
    "`ordnung shortcut` again to rewrite one you added before.",
    "The web app is built with newer packages (motion 14 among them), CI and the release workflow use version 7 of "
    "GitHub's checkout, setup-node and upload-artifact actions, and Dependabot's weekly pull requests no longer ask "
    "for labels the repository doesn't have. TypeScript majors wait until the packages that need TypeScript take "
    "them.",
    "Ask no longer goes through every letter to work out the key a question is logged and replayed under when "
    "nothing in your letters, to-dos, contracts, senders or profile changed since the last question: about 0.1 s "
    "less per question with 500 letters, more with a bigger archive.",
)

#: CHANGELOG, Unreleased → Fixed: the waiting letter added again (only with d1-test-hygiene's worker fix).
WAITING_READ_AGAIN = (
    "A letter waiting for Claude that you delete for good and add again while Ordnung runs is found by the words "
    "in its PDF again. Before, only its name found it until Claude read it."
)

#: docs/architecture.md, "Asking a question": how Ask keeps its replay key (d1-ask-memo).
ASK_KEY_KEPT = (
    "The replay key carries a hash of everything Ask's tools can read (the ledger fingerprint). It is worked out "
    "once per state of the ledger and kept per store and thread while no letter, page, to-do, contract, sender, "
    "case or the profile changed (`Store.ledger_token`): temporary triggers, which live only in the open "
    "connection and never in the database file, count this connection's writes to those tables, and another "
    "connection's commit or a schema change counts as a change too. The value is the same either way, and the "
    "tests work it out again wherever it was kept."
)


async def test_readme_says_a_weekly_deadline_or_payment_of_your_own_is_nearly_always_among_the_ideas(
    data_dir: Path,
) -> None:
    """README Limitations: a deadline or a payment you add that repeats every week, or a deadline every 2 weeks, is
    an Idea nearly all the time, because its default reminder window (Settings → Reminders: 14 and 7 days) reaches
    the next one wherever the week stands; a payment every 2 weeks isn't, and a reminder, the dialog's first kind,
    is one only on its day. Added through the API as *Add a date* adds them, starting on every day of the cycle.
    Marked done before its day, it moves to the one after the day marked, which can be past the window (D1 review:
    the line said "always"): a weekly payment due Thu 1 Oct moves to Thu 8 Oct (send by Wed 7 Oct, 9 days off) and
    a deadline every 2 weeks due Thu 8 Oct to Thu 22 Oct, neither an Idea then; a weekly deadline stays one."""
    assert (
        "A deadline or a payment you add that repeats every week, or a deadline every 2 weeks, is among Today's "
        "Ideas nearly all the time: by default Ordnung reminds you from 14 days before a deadline and 7 days before "
        "a payment (Settings → Reminders), and the next one is never further off, unless you mark one done before "
        "its day. Added as a reminder, the dialog's first kind, such a date is an Idea only on its day."
    ) in _limitations()
    defaults = Profile().reminder_days
    assert (max(defaults["deadline"]), max(defaults["payment"]), max(defaults["reminder"])) == (14, 7, 0)
    dialog = (ROOT / "web/src/features/items/AddDateDialog.tsx").read_text(encoding="utf-8")
    assert re.search(r'const EMPTY: DateDraft = \{[^}]*kind: "reminder"', dialog)
    cases = [
        *(("deadline", 1, offset) for offset in range(7)),
        *(("payment", 1, offset) for offset in range(7)),
        *(("reminder", 1, offset) for offset in range(7)),
        *(("deadline", 2, offset) for offset in range(14)),
        ("payment", 2, 13),
    ]
    #: marked done before their day: (kind, weeks, offset) → still an Idea afterwards
    early = {
        ("payment", 1, 3): False,
        ("deadline", 2, 10): False,
        ("deadline", 1, 3): True,
        ("deadline", 1, 6): True,
    }
    clock.set_today(TODAY)  # Mon 28 Sep 2026
    try:
        async with api_for(data_dir) as api:
            ids: dict[tuple[str, int, int], str] = {}
            for kind, weeks, offset in cases:
                body: dict[str, Any] = {
                    "kind": kind,
                    "title": f"Weekly {kind} {weeks} {offset}",
                    "due_date": date.fromordinal(TODAY.toordinal() + offset).isoformat(),
                    "recurrence": {"interval": weeks, "unit": "weeks"},
                }
                if kind == "payment":
                    body |= {"amount": 40.0, "direction": "out", "description": "Transfer it."}
                response = await api.client.post("/api/items", json=body)
                assert response.status_code == 201, response.text
                ids[(kind, weeks, offset)] = response.json()["id"]
            ideas = triggers.deadline_soon(Ledger(api.ctx.store, TODAY))
            for case in early:
                response = await api.client.patch(f"/api/items/{ids[case]}", json={"status": "done"})
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "open", case  # it moved on to its next day
            after = triggers.deadline_soon(Ledger(api.ctx.store, TODAY))
    finally:
        clock.set_today(None)
    with_idea = {ref.id for idea in ideas for ref in idea.refs if ref.type == "item"}
    for (kind, weeks, offset), item_id in ids.items():
        expected = (kind, weeks) in {("deadline", 1), ("payment", 1), ("deadline", 2)} or (
            kind == "reminder" and offset == 0
        )
        assert (item_id in with_idea) is expected, (kind, weeks, offset)
    with_idea_after = {ref.id for idea in after for ref in idea.refs if ref.type == "item"}
    for case, expected in early.items():
        assert (ids[case] in with_idea_after) is expected, case


def test_the_changelog_adds_weekly_repeats_and_says_what_d1_changed() -> None:
    """CHANGELOG, Unreleased: the repeating dates of your own (still unreleased) now repeat every week or every 2
    weeks too, in the order the dialog offers them; Changed has D1's lines after what was there."""
    repeats = _bullet(_unreleased("Added"), "**Dates you add yourself can repeat.**")
    for words in (
        "*Add a date* has a *Repeats* choice: every week or every 2 weeks on its weekday, every month on its day, "
        "every month on a working day (the 3rd, the last …), every 3 or 6 months, or every year.",
        "is never overdue because a week or a month went by.",
    ):
        assert words in repeats, words
    changed = _unreleased("Changed")
    for line in D1_CHANGED:
        assert f"- {line}" in changed, line
    assert changed.index("`ordnung serve` in a terminal suggests") < changed.index(D1_CHANGED[0])
    assert [changed.index(line) for line in D1_CHANGED] == sorted(changed.index(line) for line in D1_CHANGED)


def test_the_spec_lists_the_weekly_repeats_and_still_one_entry_at_the_next_day() -> None:
    """SPEC (Timeline's *Add a date*) lists every week and every 2 weeks first, as the dialog does; the server's
    rule takes weeks (``Recurrence.unit``), and README still says a repeating date is one entry at its next day."""
    assert (
        "*Repeats* (every week or every 2 weeks on its weekday, every month on its day or on a working day, every 3 "
        "or 6 months, every year)"
    ) in _spec()
    from ordnung.models import Recurrence

    assert Recurrence(interval=2, unit="weeks").unit == "weeks"
    assert "A repeating date is one entry at its next day" in _limitations()


def test_the_changelog_s_package_updates_are_the_repository_s() -> None:
    """CHANGELOG, Unreleased → Changed: motion 14, version 7 of checkout, setup-node and upload-artifact in CI
    (major tags) and the release workflow (commits pinned with their version), Dependabot without labels and holding
    TypeScript majors back; CONTRIBUTING's Dependencies say how such updates land."""
    import yaml

    package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["motion"].startswith("^14.")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for action in ("checkout", "setup-node", "upload-artifact"):
        assert set(re.findall(rf"actions/{action}@(\S+)", ci)) == {"v7"}, action
        pins = re.findall(rf"actions/{action}@[0-9a-f]{{40}} # (v\d+)\.\d+\.\d+$", release, re.M)
        assert pins and set(pins) == {"v7"}, action
    dependabot = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert all("labels" not in update for update in dependabot["updates"])
    (npm,) = [update for update in dependabot["updates"] if update["package-ecosystem"] == "npm"]
    assert {"dependency-name": "typescript", "update-types": ["version-update:semver-major"]} in npm["ignore"]
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    dependencies = _flat(contributing.split("## Dependencies", 1)[1].split("\n## ", 1)[0])
    for words in (
        "Dependabot opens update pull requests every week (`.github/dependabot.yml`): minor and patch updates "
        "together, each major on its own.",
        "One for `web/` changes `package-lock.json`, so CI passes only once `make build-web` has run and "
        "`src/ordnung/web/dist` is committed on its branch; or fold the updates into a pull request of your own.",
        "TypeScript majors are skipped until the packages that need TypeScript (openapi-typescript, "
        "typescript-eslint) take them: a test in `tests/test_repo_hygiene.py` fails then, saying to remove the rule.",
        "`ci.yml` names actions by their major version (`actions/checkout@v7`), and `release.yml` pins each to a "
        "commit with its version beside it; keep both on the same major (`tests/test_release_workflow.py` compares "
        "them).",
    ):
        assert words in dependencies, words


def test_the_privacy_page_links_microsoft_s_own_page_on_device_encryption(tmp_path: Path) -> None:
    """docs/privacy.md, before a computer is lost: where Ordnung doesn't check (Windows), Microsoft's own page on
    Device encryption, and what its note says when Settings shows no such page; README's Limitations say Ordnung
    doesn't check there, and it doesn't: no answer and no process on Windows."""
    from ordnung import encryption

    assert (
        "on Windows it doesn't check, so look yourself. Microsoft's page [Device encryption in Windows]"
        f"({DEVICE_ENCRYPTION_PAGE}) shows where to look; if Settings has no Device encryption page, your PC may "
        "not support it, or you're signed in with a standard account."
    ) in _privacy()

    def no_process(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no process on Windows")

    assert encryption.disk_encryption(tmp_path, system="win32", run=no_process) is None
    assert (
        "On Windows it doesn't check: see that BitLocker or Device encryption is on yourself."
        in _limitations()
    )


def test_contributing_says_how_an_end_to_end_test_waits_and_reads() -> None:
    """CONTRIBUTING's checks: mypy covers the benchmark code too; an e2e test waits for what the person sees, reads
    with ``READ`` (web/e2e/helpers.ts: a retried read, never a retried change) and runs on Playwright's own
    Chromium (``make browser``)."""
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    checks = _flat(contributing.split("## Checks", 1)[1].split("\n## ", 1)[0])
    for words in (
        "ruff (lint and format) and mypy (strict, over the package and `evals/`)",
        "**Writing an end-to-end test.** Before the next key press or click, wait for what the person sees (a "
        "toast, a status line, a button that is enabled again), not only for focus.",
        "Read the API with `apiGet`, or pass `READ` to `page.request.get`: it retries a connection the server "
        "dropped, and a change is never retried.",
        "Run the tests with Playwright's own Chromium (`make browser` installs it): an older build moves focus off a "
        "disabled button at once and hides this kind of race.",
    ):
        assert words in checks, words
    helpers = (ROOT / "web" / "e2e" / "helpers.ts").read_text(encoding="utf-8")
    assert "export const READ = { maxRetries: 2 } as const;" in helpers
    assert "await page.request.get(path, READ)" in helpers
    assert re.search(r"^browser: ", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M)


def test_the_architecture_says_how_ask_keeps_its_replay_key() -> None:
    """docs/architecture.md, "Asking a question": the ledger fingerprint is kept per state of the ledger."""
    asking = (
        (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8").split("## Asking a question", 1)[1]
    )
    assert ASK_KEY_KEPT in _flat(asking.split("\n## ", 1)[0])


def test_ask_keeps_its_replay_key_as_the_architecture_says(store: Store) -> None:
    """d1-ask-memo against the architecture's paragraph: the token watches exactly the letters, pages, to-dos,
    contracts, senders and cases (and the profile); Ask's own writes leave it, a sender moves it; and the tests'
    verify mode works the fingerprint out again wherever it was kept."""
    from ordnung.assistant import ask
    from ordnung.db import store as store_module

    assert store_module.LEDGER_TABLES == ("documents", "pages", "items", "contracts", "parties", "cases")
    token = store.ledger_token()
    store.save_settings(store.get_settings())
    assert store.ledger_token() == token
    store.add_party(name="FunkNetz Mobile", kind="telecom")
    assert store.ledger_token() != token
    assert hasattr(ask, "_LEDGER_MEMO")
    assert "memo.verify = True" in (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")


def test_the_web_offers_the_weekly_repeats_the_docs_name() -> None:
    """d1-web-small against CHANGELOG and SPEC: *Repeats* offers every week and every 2 weeks right after "Doesn't
    repeat", before every month, and names their weekday."""
    source = (ROOT / "web" / "src" / "features" / "items" / "repeat.ts").read_text(encoding="utf-8")
    assert re.search(r'export type RepeatChoice = "never" \| "week" \| "two_weeks" \| "month"', source)
    choices = re.search(r"const choices: RepeatChoice\[\] = \[([^\]]*)\]", source)
    assert choices is not None
    assert choices[1].split(", ")[:4] == ['"never"', '"week"', '"two_weeks"', '"month"']
    assert '"Every week"' in source and "`Every ${WEEKS[choice]} weeks`" in source


def test_the_calendar_settings_say_what_the_changelog_says_about_google_and_outlook() -> None:
    """d1-web-small against CHANGELOG: the calendar sync card says Google Calendar and Outlook.com take the calendar
    file, and *Where do I find these?* lists them with that."""
    card = _flat((ROOT / "web/src/features/settings/CalendarSyncCard.tsx").read_text(encoding="utf-8"))
    assert (
        "Google Calendar and Outlook.com don't offer this, so use the calendar file above for them." in card
    )
    assert (
        '<span className="font-medium text-ink">Google Calendar, Outlook.com</span> — no calendar address with an '
        "app password: download the calendar file above instead"
    ) in card


def test_the_docs_say_the_windows_link_names_its_target(tmp_path: Path) -> None:
    """d1-windows (merged only once CI's Windows job passed) against README, SPEC, architecture and CHANGELOG: a
    plain drive path gets an ID list right after the header, whose flags say so, and Windows' shell reading the
    target is tested on Windows; README drops "may show no target" and claims nothing about the Properties window."""
    appdata = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(tmp_path / "Local")}
    windows = shortcut.plan(
        tmp_path / "data", platform="win32", env=appdata, home=tmp_path, python="C:\\Python312\\python.exe"
    )
    assert windows.link is not None
    id_list = shortcut._id_list(windows.link.target)
    assert id_list is not None
    data = shortcut.lnk_bytes(windows.link)
    (flags,) = struct.unpack_from("<I", data, 20)
    assert flags & 0x1 and data[76 : 76 + len(id_list)] == id_list
    assert "def test_the_shell_reads_the_link_back(" in (ROOT / "tests" / "test_shortcut.py").read_text(
        encoding="utf-8"
    )
    text = _without_a_terminal()
    assert "may show no target" not in text and "Properties" not in text
    assert (
        "CI's job on macOS and Windows tests the files the shortcut writes there, and on Windows that the shell "
        "reads its target and opens it;"
    ) in text
    assert (
        "no COM, no PowerShell; the target as an ID list (This PC, its drive, each folder and the file) and again as "
        "a path in its LinkInfo and an EnvironmentVariableDataBlock;"
    ) in _spec()
    assert (
        "its `.lnk` is written byte by byte in the shell link format, with the target as an ID list Windows reads, "
        "without any Windows API."
    ) in _flat((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    assert D1_CHANGED[1] in _unreleased("Changed")


def test_a_waiting_letter_added_again_is_read_again_where_the_changelog_says_so() -> None:
    """d1-test-hygiene against CHANGELOG's Fixed: the line about a waiting letter added again stands exactly when
    the worker remembers the letters it read by job (a letter deleted and added again keeps its id)."""
    listed = WAITING_READ_AGAIN in _unreleased("Fixed")
    by_job = "job_id" in inspect.signature(worker.IngestWorker._read_text_here).parameters
    assert listed == by_job


def test_the_changelog_keeps_no_note_for_the_d1_integration() -> None:
    """The D1 integrator keeps or drops each line marked for it, then removes the mark."""
    assert "TODO(D1 integration)" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# Batch D2 — compressed answers, a lighter letter list and Outlook .msg files: README, the CHANGELOG,
# docs/privacy.md, SPEC, docs/architecture.md and ADR 0022
# --------------------------------------------------------------------------------------------------

_ADR_COMPRESSED = ROOT / "docs" / "decisions" / "0022-compressed-answers-and-a-lighter-letter-list.md"
#: The demo's committed database and files (``ordnung demo`` starts from a copy of them).
_DEMO_DB = ROOT / "src" / "ordnung" / "demo" / "demo_db"
#: The fictional Outlook e-mail the end-to-end tests add (``scripts/make_msg_fixture.py`` writes it).
_OUTLOOK_FIXTURE = ROOT / "web" / "e2e" / "fixtures" / "outlook-bill.msg"
#: The web app's text files, which go out gzipped (``api/compress.py``'s ``FILE_TYPES``).
_APP_TEXT_FILES = frozenset({".js", ".css", ".svg", ".txt", ".json"})

#: CHANGELOG, Unreleased → Changed: compressed answers and the lighter letter list (D2).
D2_FASTER = (
    "Faster on a big library and on the phone: Ordnung sends its answers and the web app's files compressed "
    "(gzip), on the demo about 6 times less data for the answers and 3 times less for the app's files. The letter "
    "list no longer carries each letter's explanation, key facts, references and bank details; the letter's own "
    "page loads them, and *Download a copy of your records* still has every letter whole. Live updates, downloads, "
    "signing in and pairing are never compressed "
    "([ADR 0022](docs/decisions/0022-compressed-answers-and-a-lighter-letter-list.md))."
)
#: CHANGELOG, Unreleased → Upgrading: what a script reading the letter list finds now.
D2_LIST_SCRIPTS = (
    "A script that reads the letter list (`GET /api/documents`) no longer finds `explanation`, `key_facts`, "
    "`references`, `payment` or `sha256` in its rows: read them from the letter (`GET /api/documents/{id}`), or "
    "every letter whole from `GET /api/documents.json` on the computer."
)
#: CHANGELOG, Unreleased → Added: e-mails saved from Outlook (D2-P3), its sentences in order.
D2_OUTLOOK = (
    "Ordnung now takes the `.msg` file Outlook saves (an e-mail dragged to the desktop, or saved with *Save as*) "
    "wherever it takes an `.eml`: *Add letters*, your phone, the watched folder, `ordnung add` and proof of a sent "
    "letter.",
    "It opens the file on your computer and keeps the e-mail as an `.eml` copy named like the file, with its "
    "sender, date, subject and text; every attached PDF or photo becomes a letter of its own.",
    "The `.msg` itself isn't kept, so what only Outlook has (categories, flags, formatting) is lost: keep the file "
    "if you need it.",
    "The same file always makes the same copy, so adding it twice finds it already in Ordnung.",
    "Signed or encrypted e-mails, calendar entries, contacts and tasks are refused with the reason, and an e-mail "
    "whose text Outlook kept only as RTF comes in without its text (its attachments still come in).",
    "Before, an Outlook file was refused (the watched folder left it alone), or taken for a PDF when an attached "
    "PDF came first in it.",
)
#: README's Limitations: how e-mail comes in (it replaced "it can't open Outlook's `.msg` files").
README_EMAIL_LIMIT = (
    "E-mailed letters come in as saved files: `.eml`, or Outlook's `.msg`, which Ordnung keeps as an `.eml` copy "
    "(the `.msg` itself isn't kept). Ordnung doesn't fetch mail from a mailbox. An Outlook e-mail whose text is "
    "only in RTF comes in without its text (its attachments still come in), and a signed or encrypted one can't be "
    "opened: save its attachments and add those."
)
#: docs/privacy.md, "Hardening built into every model call": what is compressed, and why that is safe.
PRIVACY_COMPRESSED = (
    "Answers are compressed (gzip) only when they are a JSON answer to a GET that sets no cookie, or one of the "
    "web app's own files, such as its scripts and styles, which hold nothing of yours; signing in, "
    "pairing, downloads, a letter's files and live updates never are, and TLS's own compression is off on the "
    "phone listener. An attack that reads secrets out of compressed HTTPS needs a website to make your phone send "
    "Ordnung many requests, and the phone listener refuses requests from other sites "
    "([ADR 0022](decisions/0022-compressed-answers-and-a-lighter-letter-list.md))."
)
#: docs/privacy.md, "Phone access (optional)": what the letter list leaves out.
PRIVACY_LIST = "The letter list no longer carries bank details or key facts: a letter's page loads them when you open it."
#: docs/privacy.md, "Your controls": an Outlook e-mail is kept as its .eml copy.
PRIVACY_OUTLOOK = (
    "An e-mail saved from Outlook (`.msg`) is opened on this computer and kept as an `.eml` copy; the `.msg` "
    "itself isn't kept, so keep it yourself if you need the original."
)
#: ADR 0022: the rule for a later GET route with a secret in its answer.
ADR_SECRET_RULE = (
    "**The rule for later:** a new `GET` route whose JSON answer carries a secret (a code, a token, a password or "
    "a key) gets a test that proves its answer is never compressed, or it isn't a `GET`."
)


def test_the_changelog_says_d2_compresses_answers_and_lightens_the_letter_list() -> None:
    """CHANGELOG, Unreleased: Changed has D2's line after D1's, naming the fields the list leaves out; Upgrading
    tells scripts where those fields are now, and they are exactly ``LEFT_OUT_OF_LIST``."""
    from ordnung.api.routes.documents import LEFT_OUT_OF_LIST

    changed = _unreleased("Changed")
    assert f"- {D2_FASTER}" in changed
    assert changed.index(D1_CHANGED[-1]) < changed.index(D2_FASTER)
    assert f"- {D2_LIST_SCRIPTS}" in _unreleased("Upgrading")
    named = D2_LIST_SCRIPTS.split("no longer finds", 1)[1].split(" in its rows", 1)[0]
    assert set(re.findall(r"`(\w+)`", named)) == LEFT_OUT_OF_LIST


def test_the_changelog_adds_e_mails_saved_from_outlook() -> None:
    """CHANGELOG, Unreleased → Added: the Outlook bullet, its sentences in order."""
    bullet = _bullet(_unreleased("Added"), "**E-mails saved from Outlook.**")
    for sentence in D2_OUTLOOK:
        assert sentence in bullet, sentence
    assert [bullet.index(sentence) for sentence in D2_OUTLOOK] == sorted(bullet.index(s) for s in D2_OUTLOOK)


def test_the_letter_list_and_the_records_copy_are_what_the_docs_say() -> None:
    """SPEC § 4, § 12b and § 13: the list's rows are ``DocumentRow`` (``Document`` without ``LEFT_OUT_OF_LIST``,
    plus ``found_in``), made in the route module; ``models.DocumentListEntry`` stays, unused; ``documents.json``
    is every letter whole and computer-only ("records leave the computer", and the route checks again)."""
    from ordnung import models
    from ordnung.api.routes import documents

    left_out = {"key_facts", "explanation", "references", "payment", "sha256"}
    assert documents.LEFT_OUT_OF_LIST == left_out
    assert set(documents.DocumentRow.model_fields) == (set(Document.model_fields) - left_out) | {
        "found_in",
        "tax_choice",  # D3: the person's own "For taxes" choice (SPEC § 4, checked in Batch D3 below)
    }
    assert hasattr(models, "DocumentListEntry")
    components = openapi_schema()["components"]["schemas"]
    assert "DocumentRow" in components and "DocumentListEntry" not in components
    operation = ("GET", "/api/documents.json")
    assert phone_scope.classify(*operation) == "computer"
    assert phone_scope.NEVER_ON_PHONE[operation] == "records leave the computer"
    (route,) = [r for r in documents.router.routes if isinstance(r, APIRoute) and r.path == "/documents.json"]
    assert any(dependency.dependency is require_computer for dependency in route.dependencies)
    spec = _spec()
    for words in (
        "`DocumentRow` (in `api/routes/documents.py`: every `Document` field but `LEFT_OUT_OF_LIST` — `key_facts`, "
        "`explanation`, `references`, `payment`, `sha256` —, plus `found_in`: `letter`, `scanner_text`, or `null` "
        "without a search) is what `GET /api/documents` lists",
        "`models.DocumentListEntry` (the whole letter plus `found_in`) stays unused",
        "GET list: `DocumentRow` rows (without `key_facts`, `explanation`, `references`, `payment` and `sha256`: "
        "the letter's detail has them), each with `found_in`",
        "`documents.json` (GET: every letter whole, as stored, newest first, without trash and proof files — the "
        "letters of *Download a copy of your records*; computer-only)",
        "and every letter whole (`documents.json`) are computer-only too",
    ):
        assert words in spec, words
    assert "DocumentListEntry` rows" not in spec


def test_the_records_copy_takes_every_letter_whole() -> None:
    """d2-list-consumers against the CHANGELOG: *Download a copy of your records* takes its letters from the
    computer-only ``documents.json``, never from the lighter list."""
    section = (ROOT / "web" / "src" / "features" / "settings" / "DataSection.tsx").read_text(encoding="utf-8")
    export = section.split("async function buildExport()", 1)[1].split("\n}\n", 1)[0]
    assert "api.documentsFull()" in export and "api.documents()" not in export


def test_the_privacy_page_says_what_is_compressed_and_what_the_list_leaves_out() -> None:
    """docs/privacy.md: what is compressed and why it is safe (with the hardening), the letter list on a phone,
    and an Outlook e-mail kept as its ``.eml`` copy (with the e-mail attachments, and opened within limits)."""
    hardening = _privacy_section("Hardening built into every model call")
    assert PRIVACY_COMPRESSED in hardening
    assert (
        "An Outlook file is opened from memory, within limits on its size and structure, and its `.eml` copy then "
        "passes the same checks."
    ) in hardening
    assert PRIVACY_LIST in _privacy_section("Phone access (optional)")
    assert PRIVACY_OUTLOOK in _bullet(
        _privacy_section("Your controls"), "**E-mail attachments follow the e-mail**"
    )


async def test_compression_follows_the_rules_the_docs_state(data_dir: Path) -> None:
    """d2-compression against SPEC § 13, ADR 0022 and docs/architecture.md: JSON only, at least 1 KiB, level 6, a
    thread from 128 KiB, never with a cookie, a download's or a file's headers; the outermost middleware; the web
    app's five text types; TLS compression off on the phone listener."""
    from ordnung.api import compress
    from ordnung.phone import access

    assert (compress.GZIP_LEVEL, compress.MIN_BYTES, compress.THREAD_BYTES) == (6, 1024, 128 * 1024)
    assert compress.COMPRESSIBLE == frozenset({"application/json"})
    never = {
        b"set-cookie",
        b"content-disposition",
        b"etag",
        b"accept-ranges",
        b"content-range",
        b"content-encoding",
    }
    assert never <= set(compress.NEVER_WITH)
    assert set(compress.FILE_TYPES) == _APP_TEXT_FILES
    assert "ssl.OP_NO_COMPRESSION" in inspect.getsource(access.listener_config)
    async with api_for(data_dir) as api:
        # the middleware added last is the outermost
        assert api.app.user_middleware[0].cls is compress.CompressMiddleware
        zipped = await api.client.get("/api/rules", headers={"Accept-Encoding": "gzip"})
        plain = await api.client.get("/api/rules", headers={"Accept-Encoding": "identity"})
    assert zipped.headers.get("content-encoding") == "gzip" and "content-encoding" not in plain.headers
    assert zipped.json() == plain.json() and "Accept-Encoding" in zipped.headers["vary"]


def test_adr_0022_states_the_rule_for_a_secret_in_a_get_answer_and_the_readme_lists_it() -> None:
    """ADR 0022 (numbered after 0021, listed in README's Documentation) says why compression is safe here and
    the rule a later route with a secret in a GET answer must follow; it keeps ``models.py`` untouched."""
    text = _ADR_COMPRESSED.read_text(encoding="utf-8")
    assert text.startswith("# ADR 0022 — Compressed answers and a lighter letter list\n")
    assert "**Status:** accepted" in text
    adr = _flat(text)
    assert ADR_SECRET_RULE in adr
    for words in (
        "## Why compression is safe here (BREACH)",
        "**`models.py` is untouched on purpose.**",
        "**Starlette's `GZipMiddleware`:**",
    ):
        assert words in adr, words
    documentation = _flat(_readme().split("## Documentation", 1)[1].split("\n## ", 1)[0])
    assert f"(docs/decisions/{_ADR_COMPRESSED.name})" in documentation
    assert "[0022 compressed answers and a lighter letter list]" in documentation


def _stated_bytes(text: str) -> float:
    """``about 2.9 MB`` → 2.9e6; ``about 91 KB`` → 91e3."""
    found = re.fullmatch(r"about ([\d.]+) (KB|MB)", text)
    assert found is not None, text
    return float(found[1]) * (1e3 if found[2] == "KB" else 1e6)


async def test_the_adr_s_measurements_are_the_demo_s(tmp_path: Path) -> None:
    """ADR 0022's Measured, on a copy of the demo: the letter list whole, as ``DocumentRow``s and gzipped at level 6
    (the middleware's rules: 1 KiB and up, when it shrinks), the share the five fields took, the JSON answers to the
    app's GETs without parameters, and the web app's text files gzipped at level 9 (files under 1 KiB as they are).
    Each "about" is within a tenth."""
    import gzip

    from fake_caldav import MemorySecrets
    from ordnung.api.routes import calendar_sync
    from ordnung.api.routes import sync as sync_routes

    def sent(body: bytes) -> int:
        packed = gzip.compress(body, compresslevel=6, mtime=0)
        return len(packed) if len(body) >= 1024 and len(packed) < len(body) else len(body)

    def near(value: float, stated: float) -> bool:
        return abs(value - stated) <= stated / 10

    data = tmp_path / "demo"
    shutil.copytree(_DEMO_DB, data)
    raw = wire = 0
    try:
        async with api_for(data, demo=True) as api:
            # not the real keyring
            api.app.dependency_overrides[calendar_sync.get_secrets] = lambda: MemorySecrets()
            api.app.dependency_overrides[sync_routes.get_secrets] = lambda: MemorySecrets()
            listed = await api.client.get("/api/documents")
            whole = await api.client.get("/api/documents.json")
            for path, operations in openapi_schema()["paths"].items():
                get = operations.get("get")
                if get is None or "{" in path or path in {"/api/events", "/api/health"}:
                    continue
                if any(parameter.get("required") for parameter in get.get("parameters", [])):
                    continue
                answer = await api.client.get(path)
                is_json = answer.headers["content-type"].startswith("application/json")
                if answer.status_code == 200 and is_json:
                    raw, wire = raw + len(answer.content), wire + sent(answer.content)
    finally:
        clock.set_today(None)  # the demo's context pins its simulated day; never for the next test
    assert len(listed.json()) == len(whole.json()) == 22
    measured = _flat(
        _ADR_COMPRESSED.read_text(encoding="utf-8").split("## Measured", 1)[1].split("\n## ", 1)[0]
    )
    assert "On a copy of the demo (22 letters)" in measured
    stated = [_stated_bytes(text) for text in re.findall(r"about [\d.]+ [KM]B", measured)]
    assert len(stated) == 7, stated
    whole_size, list_size, list_sent, answers_raw, answers_sent, files_raw, files_sent = stated
    assert near(len(whole.content), whole_size) and near(len(listed.content), list_size)
    assert near(sent(listed.content), list_sent)
    assert f"{round(100 * (1 - sent(listed.content) / len(whole.content)))} % less on the wire" in measured
    assert 0.65 <= 1 - len(listed.content) / len(whole.content) < 0.75  # "nearly three quarters"
    assert "the five fields left out were nearly three quarters of its bytes" in measured
    assert near(raw, answers_raw) and near(wire, answers_sent)
    assert f"about {round(raw / wire)} times less" in measured
    files = [
        path.read_bytes()
        for path in (ROOT / "src" / "ordnung" / "web" / "dist").rglob("*")
        if path.is_file() and path.suffix.lower() in _APP_TEXT_FILES
    ]
    packed = [
        min(len(gzip.compress(body, compresslevel=9, mtime=0)), len(body))
        for body in files
        if len(body) >= 1024
    ]
    size = sum(map(len, files))
    gzipped = sum(packed) + sum(len(body) for body in files if len(body) < 1024)
    assert near(size, files_raw) and near(gzipped, files_sent)
    assert f"about {round(size / gzipped)} times less" in measured


def test_readme_says_outlook_files_come_in_as_an_eml_copy() -> None:
    """README: the "Also" line names Outlook's ``.msg``; Limitations no longer say it can't be opened, still say
    Ordnung doesn't fetch mail from a mailbox, and say what an Outlook e-mail loses."""
    readme = _flat(_readme())
    assert (
        "and e-mails (`.eml`, or Outlook's `.msg`) whose PDF and photo attachments become letters" in readme
    )
    assert README_EMAIL_LIMIT in _limitations()
    assert "can't open Outlook's `.msg` files" not in readme


def test_outlook_files_come_in_where_the_docs_say() -> None:
    """d2-outlook against README, the CHANGELOG and SPEC § 8: an Outlook file becomes an ``.eml`` copy named like
    it, the same copy every time, before intake looks at it — at upload and the phone, the watched folder (which
    watches ``.msg`` as SPEC § 8.1 lists), ``ordnung add`` and proof of a sent letter; the web app's pickers take
    it; signed or encrypted ones are refused; olefile is a dependency."""
    from ordnung import cli
    from ordnung.api.routes import documents
    from ordnung.drafts import sent
    from ordnung.ingest import outlook, watcher
    from ordnung.ingest.intake import sniff_mime

    data = _OUTLOOK_FIXTURE.read_bytes()
    body, name = outlook.as_email(data, "outlook-bill.msg")
    assert name == "outlook-bill.eml" and outlook.as_email(data, "outlook-bill.msg") == (body, name)
    assert sniff_mime(body, name) == "message/rfc822"
    assert outlook.as_email(b"%PDF-1.7\n", "x.pdf") == (b"%PDF-1.7\n", "x.pdf")
    assert "signed or encrypted" in outlook.ENCRYPTED
    for function in (documents._normalised, sent.add_proof, cli._add_in_process, watcher.FolderWatcher._add):
        source = inspect.getsource(function)  # called directly or in a thread (asyncio.to_thread)
        assert re.search(r"\bas_email\b", source), function.__qualname__
    listed = re.search(r"Files directly in the folder with a type Ordnung reads \(`([^`]+)`", _spec())
    assert listed is not None and set(listed[1].split()) == set(watcher.WATCHED_SUFFIXES)
    assert "Letters to add (PDF, photos, .txt/.eml/.msg)." in inspect.getsource(cli.add)
    web = ROOT / "web" / "src"
    for picker in (web / "components/shell/AddLetters.tsx", web / "features/letters/AddProofDialog.tsx"):
        assert ".msg" in picker.read_text(encoding="utf-8"), picker.name
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(dependency.startswith("olefile>=") for dependency in pyproject["project"]["dependencies"])


def test_the_spec_architecture_and_privacy_describe_outlook_files() -> None:
    """SPEC § 3.2, § 8 and § 8.1, docs/architecture.md's diagram and trust boundaries, and docs/privacy.md's table:
    an Outlook ``.msg`` comes in as its ``.eml`` copy."""
    spec = _spec()
    for words in (
        "ifaddr (phone access: the network interfaces with their netmasks), olefile (Outlook `.msg` files)",
        "**Outlook files** (`ingest/outlook.py`, policy in its docstring). An Outlook `.msg` (an OLE compound file, "
        "whatever its name) becomes the `.eml` copy Ordnung stores, named like the file (`Rechnung.msg` → "
        "`Rechnung.eml`), before intake looks at its bytes",
        "The `.msg` itself is not kept.",
        "Files directly in the folder with a type Ordnung reads (`.pdf .jpg .jpeg .png .webp .heic .heif .txt .eml "
        ".msg`, any case)",
    ):
        assert words in spec, words
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert 'L["Letters · PDFs · phone photos · .eml · .msg"]' in architecture
    (row,) = [line for line in architecture.splitlines() if line.startswith("| Outlook file → e-mail |")]
    assert "`ingest/outlook.py`" in row and "then passes the upload checks below" in row
    privacy = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    (glance,) = [line for line in privacy.splitlines() if line.startswith("| Original files")]
    assert "an Outlook e-mail as its `.eml` copy" in glance


def test_the_spec_and_architecture_say_how_answers_are_compressed() -> None:
    """SPEC § 13 and docs/architecture.md: what is compressed, on both listeners; the middleware is the outermost,
    decides on an answer's start and lets a live stream through at once; the web app's files are gzipped once."""
    assert (
        "Compression (`api/compress.py`, ADR 0022): on both listeners, a JSON answer to a `GET` that takes gzip goes "
        "out gzipped when it is a `200` of at least 1 KiB in one message (level 6; from 128 KiB in a thread)"
    ) in _spec()
    architecture = _flat((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    concurrency = architecture.split("## Concurrency model", 1)[1].split(" ## ", 1)[0]
    for words in (
        "**Compressed answers** (`api/compress.py`, "
        "[ADR 0022](decisions/0022-compressed-answers-and-a-lighter-letter-list.md)).",
        "the outermost middleware on both listeners (then the security checks or the phone's gate, then sync's gate)",
        "anything else, a live stream first of all, passes at once",
        "The web app's text files are gzipped once and kept in memory, per file and version.",
    ):
        assert words in concurrency, words


def test_the_tests_the_architecture_names_for_d2_exist() -> None:
    """docs/architecture.md's testing strategy names D2's tests; they come with the other D2 packages."""
    architecture = _flat((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    for path in (
        "tests/test_compress.py",
        "web/e2e/real-app-compression.spec.ts",
        "web/e2e/letter-list-rows.spec.ts",
        "tests/test_outlook.py",
        "tests/test_outlook_intake.py",
    ):
        assert f"`{path}`" in architecture, path
        assert (ROOT / path).is_file(), path


def test_the_changelog_keeps_no_note_for_the_d2_integration() -> None:
    """No line of the CHANGELOG waits for the D2 integrator's decision any more."""
    assert "TODO(D2 integration)" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


#: CHANGELOG, Unreleased → Fixed: stopping the daily check waits for its work (d2-races).
D2_TICK_FIXED = (
    "Stopping Ordnung, or handing over to another computer with hand-off sync, while the daily check was at work "
    "(the day's to-dos and Ideas, calendar sync) didn't wait for that work. It went on after the check had stopped: "
    "the day's to-dos were no longer kept apart from a letter being read at that moment, and a hand-over could be "
    "saved before the work ended. Stopping now waits for it, at most 10 seconds."
)
#: CHANGELOG, Unreleased → Fixed: hand-off sync's question settles when it is answered once more (d2-races).
D2_SYNC_FIXED = (
    "When two computers had answered hand-off sync's question (which computer's Ordnung to keep) apart, each "
    "keeping its own, the question came back, as it should. But keeping the same Ordnung once more didn't settle "
    "it: the question came back after every such answer. Now the answer given then stands. A computer whose Ordnung "
    "another computer had already kept, exactly as it is, is no longer asked again."
)
#: SPEC § 9: stopping the daily tick waits for its worker thread.
SPEC_TICK_STOP = (
    "Its work runs in worker threads, and stopping it (Ordnung stops, or hand-off sync stands this computer by) "
    "waits for a running one, at most 10 s (`STOP_WAIT_S`): the ledger lock stays held until the day's work has "
    "ended, and no thread of the tick still uses the store once it closes."
)
#: SPEC § 12c, Versions: two answers given apart, then asked once more.
SPEC_ANSWERED_AGAIN = (
    "A choice that keeps changes another answer dropped (two answers given apart, and the person asked once more) "
    "leaves them out under their old numbers, and the save numbers them anew (`lineage.renumbers`), so the answer "
    "given then stands; a version with the same content as one another computer kept in a choice counts what that "
    "choice dropped as answered (`decide._informed`), so it isn't asked again."
)


def test_the_changelog_says_what_d2_fixed_in_the_daily_check_and_hand_off_sync() -> None:
    """CHANGELOG, Unreleased → Fixed: the daily check's stop and hand-off sync's settled question, after the
    Windows lines; SPEC § 9 and § 12c say the same."""
    fixed = _unreleased("Fixed")
    for line in (D2_TICK_FIXED, D2_SYNC_FIXED):
        assert f"- {line}" in fixed, line
    assert (
        fixed.index("Windows: once Ordnung has stopped")
        < fixed.index(D2_TICK_FIXED)
        < fixed.index(D2_SYNC_FIXED)
    )
    spec = _spec()
    assert SPEC_TICK_STOP in spec.split("## 9. Secretary", 1)[1].split(" ## ", 1)[0]
    assert SPEC_ANSWERED_AGAIN in spec.split("- **Versions** (`sync/lineage.py`, `sync/decide.py`).", 1)[1]
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    (row,) = [
        line
        for line in architecture.splitlines()
        if line.startswith("| **Whose content is newer** (lineage)")
    ]
    assert (
        "(two answers given apart are asked about once more, and the answer given then stands: the changes it keeps "
        "again are numbered anew)"
    ) in row


def test_the_daily_check_and_hand_off_sync_do_what_the_changelog_says() -> None:
    """d2-races against the CHANGELOG and SPEC: every thread call of the daily tick is waited for on a cancel (at
    most 10 s); two answers given apart, then answered once more by keeping the same version, leave the other
    computer seeing that answer as having decided, and the save numbers the kept changes anew; a version with the
    same content as one kept elsewhere counts that choice's drops as answered."""
    import ordnung.tick as tick_module
    from ordnung.sync import decide, push
    from ordnung.sync import lineage as lin

    assert tick_module.STOP_WAIT_S == 10  # "at most 10 seconds"
    assert "asyncio.to_thread(" not in inspect.getsource(DailyTick)
    assert "STOP_WAIT_S" in inspect.getsource(DailyTick.stop)
    a, b = "a" * 32, "b" * 32  # two computers' keys
    this, other = lin.make({a: [(1, 1)]}), lin.make({b: [(1, 1)]})
    first, second = lin.keep_this(this, [other]), lin.keep_this(other, [this])  # each kept its own
    assert lin.relation(first, second) == "diverged"  # asked once more, as it should
    again = lin.keep_this(first, [second])  # the same one kept again
    assert lin.renumbers(first, again)
    saved = lin.bump(again, a, 2)  # the save numbers the kept change anew
    assert lin.relation(second, saved) == "decided" and lin.relation(saved, second) == "behind"
    assert "renumbers(" in inspect.getsource(push.push)
    for rule in (decide._in_use, decide._use_here):
        assert "_informed(" in inspect.getsource(rule), rule.__name__


# --------------------------------------------------------------------------------------------------
# Batch D3 — For taxes on any letter, an Inbox year filter and your household: README, the CHANGELOG,
# docs/privacy.md, SPEC, docs/architecture.md and ADR 0023
# --------------------------------------------------------------------------------------------------

_ADR_HOUSEHOLD = ROOT / "docs" / "decisions" / "0023-letters-for-your-household-are-suggested-never-filed.md"
#: Claims about code the other D3 packages build (d3-tax-choice, d3-household-core, d3-inbox and
#: d3-household-surfaces): on d3-docs's own branch that code is still d3-contract's (an empty household, a 501
#: for a tax choice), so these hold once D3 is merged; the integrator then drops the mark.
_UNTIL_D3 = pytest.mark.xfail(strict=False, reason="until D3 integration")

#: CHANGELOG, Unreleased → Added: *For taxes* on a letter's page (d3-tax-choice), its sentences in order.
D3_FOR_TAXES = (
    "A letter's page has a *For taxes* button: press it to add the letter to your letters for taxes, or to take "
    "one Claude marked off them — private letters too, and on your phone, with Undo.",
    "Your choice stays when the letter is read again; the Tax year page, *Export letters* with *Only letters for "
    "taxes*, the tax-season Idea and the weekly review's *Keep it with your tax papers* follow it.",
    "Ask and *Weekly Ideas* still see Claude's own mark.",
)
#: CHANGELOG, Unreleased → Added: the Inbox's year (d3-inbox).
D3_YEAR = (
    "A *Year* choice next to the kind of letter shows the letters dated in that year (else arrived in it), as "
    "the Tax year page files them; its *Letters for taxes* link then opens that year."
)
#: CHANGELOG, Unreleased → Added: your household (d3-household-core, d3-inbox, d3-household-surfaces), its
#: sentences in order.
D3_HOUSEHOLD = (
    "Add the people whose letters come to you too, such as your partner or your children, in Settings → Profile "
    "& address (Claude never sees the list).",
    "A letter addressed to one of them asks *Is this letter for Alex Rivera?* — one press files it, *Change* "
    "files it for someone else, and nothing is filed by itself "
    "([ADR 0023](docs/decisions/0023-letters-for-your-household-are-suggested-never-filed.md)).",
    "The Inbox shows one person's letters and files the ones addressed to them at once (*File these 3 for Alex "
    "Rivera*); Inbox and Today rows say whose letter it is; a reply to their letter can go out in their name "
    "when they sign their own letters (for a child, it goes out in yours).",
    "A paired phone can file letters but not change the list, and *Download a copy of your records* holds it.",
    "Their letters' dates, reminders and numbers stay yours, and Ask and Ideas still treat them as yours.",
)
#: CHANGELOG, Unreleased → Upgrading: what a computer still on 0.2.0 does with the two new ``meta`` rows. (0.2.0
#: had no addressee policy, ``secretary/addressee.py``, so its composer never offers another name.)
D3_UPGRADING = (
    "A computer still on 0.2.0 keeps the letters you marked or unmarked for taxes but doesn't use your choices: "
    "its Tax year page, export and tax-season Idea go by Claude's marks alone, and a letter deleted for good "
    "there leaves its choice behind (its id and yes or no, nothing of the letter) until you next mark or unmark "
    "a letter on an updated computer. Update both computers.",
    "A computer still on 0.2.0 keeps your household and the letters you filed for its people when it receives "
    "them by hand-off sync or from a backup, but doesn't show them: there every letter is yours, as before. "
    "Update both computers.",
    "A letter deleted for good on a computer still on 0.2.0 leaves its filing behind (its id, nothing of the "
    "letter) until an updated computer in use runs its daily check.",
)
#: README's Limitations: who marks a letter for taxes (it replaced "you can't mark one yourself yet").
README_TAX_LIMIT = (
    "Claude marks a letter for taxes when it reads it; *For taxes* on a letter's page changes that, for private "
    "letters too, and your choice stays when the letter is read again. Ask, and the Ideas Claude suggests each "
    "week, still go by Claude's own mark. A letter still waiting under *From your folder — not read yet* can't "
    "be marked"
)
#: README "Also:": the tax year with *For taxes* and the Inbox's year, and your household.
README_D3_ALSO = (
    "*tax year* — a year's letters for your tax return, by the date on them; mark or unmark any letter "
    "yourself, and the Inbox shows one year at a time",
    "*your household* — file a letter for your partner or your child when Ordnung asks (it never files one by "
    "itself), find their letters, and reply in their name when they sign their own",
)
#: docs/privacy.md, "What is sent to Claude, per feature": the choices never reach Claude; the tax Idea's title.
PRIVACY_FOR_TAXES = (
    "Your *For taxes* choices never reach Claude: Ask and *Weekly Ideas* see the mark Claude gave a letter when "
    "it read it, and *Read again* asks Claude exactly what it would ask without your choice, which stays."
)
PRIVACY_TAX_IDEA = (
    "When a letter you marked makes the tax-season Idea appear, its title (*{title}*: no letter, no count), like "
    "every Idea's, is part of what *Weekly Ideas* and the daily note send."
)
#: docs/privacy.md, "Your household": when a letter is filed, what never reaches Claude, who may change it.
PRIVACY_HOUSEHOLD = (
    "Ordnung suggests who a letter is for from the addressee its reading names, on your computer, and files a "
    "letter for someone only when you press *Yes*, choose them under *Change*, or file a set of letters in the "
    "Inbox; nothing is filed by itself, by a reading, by the daily check or by sync.",
    "**Never sent to Claude.** The list is not put into a prompt, a draft request, Ask's tools, a notification, "
    "a calendar or anything *Weekly Ideas* and the daily note send.",
    "**Who may change it.** Only the computer edits the list, as with your profile; a paired phone can file "
    'letters, and the privacy log notes each time ("Changed who a letter is for on Anna\'s iPhone").',
    "Deleting a letter for good removes its filing in the same step; the trash keeps it, as it keeps the "
    "letter.",
)
#: The modules that build what Claude is given: Ask (its tools and fingerprint), the prompts and the model
#: runtime, the weekly review's snapshot, the daily note and a draft request.
_CLAUDE_FACING = (
    ROOT / "src" / "ordnung" / "assistant",
    ROOT / "src" / "ordnung" / "llm",
    ROOT / "src" / "ordnung" / "secretary" / "review.py",
    ROOT / "src" / "ordnung" / "secretary" / "brief.py",
    ROOT / "src" / "ordnung" / "drafts" / "compose.py",
)
#: The names of the household and the tax choices in code.
_D3_NAMES = frozenset(
    {
        "household",
        "tax_choice",
        "tax_choices",
        "for_taxes",
        "recipient_names",
        "HOUSEHOLD_META_KEY",
        "TAX_CHOICES_META_KEY",
    }
)
_D3_MODULES = ("ordnung.secretary.household", "ordnung.secretary.tax_choice", "ordnung.api.routes.household")


def test_the_changelog_adds_for_taxes_the_inbox_year_and_your_household() -> None:
    """CHANGELOG, Unreleased → Added: *For taxes* on any letter, the Inbox's year and your household, their
    sentences in order, after the Outlook e-mails and before the releases."""
    added = _unreleased("Added")
    for lead, sentences in (
        ("**Mark any letter for taxes yourself.**", D3_FOR_TAXES),
        ("**The Inbox shows one year at a time.**", (D3_YEAR,)),
        ("**Your household.**", D3_HOUSEHOLD),
    ):
        bullet = _bullet(added, lead)
        for sentence in sentences:
            assert sentence in bullet, sentence
        assert [bullet.index(s) for s in sentences] == sorted(bullet.index(s) for s in sentences), lead
    assert (
        added.index("**E-mails saved from Outlook.**")
        < added.index("**Mark any letter for taxes yourself.**")
        < added.index("**The Inbox shows one year at a time.**")
        < added.index("**Your household.**")
        < added.index("**Releases.**")
    )


def test_the_changelog_says_what_a_0_2_0_computer_does_with_the_choices_and_the_household() -> None:
    """CHANGELOG, Unreleased → Upgrading, against the code: both rows are synced ``meta`` rows (0.2.0's scrub
    deletes only its own local and demo keys, as now, so they travel through it untouched), backups keep them,
    and no migration came with them (a 0.2.0 computer refuses a newer schema in sync and backups)."""
    from ordnung.backup import archive
    from ordnung.db import store as store_module

    upgrading = _unreleased("Upgrading")
    for sentence in D3_UPGRADING:
        assert f"- {sentence}" in upgrading, sentence
    keys = {store_module.TAX_CHOICES_META_KEY, store_module.HOUSEHOLD_META_KEY}
    assert keys == {"tax_choices", "household"}
    assert keys <= sync.SYNCED_META
    assert keys.isdisjoint(sync.LOCAL_META | sync.DEMO_META | sync.MERGED_META)
    assert keys.isdisjoint(archive._LEFT_OUT_META)
    migrations = sorted(p.name for p in (ROOT / "src" / "ordnung" / "db" / "migrations").glob("*.sql"))
    assert len(migrations) == 5 and migrations[-1].startswith("0005_"), migrations


def test_readme_names_for_taxes_the_inbox_year_and_your_household() -> None:
    """README: the "Also" line names *For taxes*, the Inbox's year and your household; Privacy says the
    household and the choices are never put into a prompt; Documentation lists ADR 0023 after 0022."""
    also = _flat(_tour().split("**Also:**", 1)[1])
    for words in README_D3_ALSO:
        assert words in also, words
    privacy = _flat(_readme().split("\n## Privacy\n", 1)[1].split("\n## ", 1)[0])
    assert (
        "the address and IBAN in your profile, the people you list as your household and your *For taxes* "
        "choices are never put into a prompt"
    ) in privacy
    documentation = _flat(_readme().split("## Documentation", 1)[1].split("\n## ", 1)[0])
    assert f"(docs/decisions/{_ADR_HOUSEHOLD.name})" in documentation
    assert documentation.index("[0022 compressed answers") < documentation.index(
        "[0023 letters for your household are suggested, never filed]"
    )


def test_the_privacy_page_says_where_the_choices_and_the_household_live(store: Store) -> None:
    """docs/privacy.md: a row each in "At a glance" (``meta``, in backups and hand-off sync, never to Claude); the
    choices never reach Claude, but the tax Idea's title, like every Idea's, does; "Your household"; a phone files
    but never edits the list (the privacy log's words); deleting a letter for good removes both."""
    from ordnung.api import phone_gate
    from ordnung.secretary import review

    text = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    (taxes,) = [line for line in text.splitlines() if line.startswith("| Your *For taxes* choices")]
    (people,) = [line for line in text.splitlines() if line.startswith("| Your household")]
    assert "`tax_choices`" in taxes and "`household`" in people
    for row in (taxes, people):
        assert "encrypted backups and hand-off sync's encrypted copy" in row and "never sent to Claude" in row
    sent = _privacy_section("What is sent to Claude, per feature")
    seed_ledger(store)
    (idea,) = tax_documents(Ledger(store, date(2026, 3, 1)))
    assert PRIVACY_FOR_TAXES in sent
    assert PRIVACY_TAX_IDEA.format(title=idea.title) in sent
    # the weekly review is given Claude's own mark and only the Ideas' titles
    assert '"tax_relevant": doc.tax_relevant' in inspect.getsource(review._document_row)
    assert '"existing_ideas": {"open": open_titles' in inspect.getsource(review)
    household = _privacy_section("Your household")
    for sentence in PRIVACY_HOUSEHOLD:
        assert sentence in household, sentence
    assert phone_scope.CHANGE_LABELS[("PATCH", "/api/household")] == "Changed who a letter is for"
    assert 'f"{label} on {device.name}"' in inspect.getsource(phone_gate)
    phone = _privacy_section("Phone access (optional)")
    assert "mark a letter for taxes and file a letter for someone in your household" in phone
    assert "change settings, your profile, your household's list" in phone
    controls = _privacy_section("Your controls")
    assert "your *For taxes* choice for it and whom you filed it for" in _bullet(
        controls, "**Delete means delete**"
    )
    assert "Your household and your *For taxes* choices travel with your ledger." in _privacy_section(
        "Hand-off sync between your computers (optional)"
    )
    assert "your household and your *For taxes* choices" in _privacy_section("Encrypted backups")


def test_nothing_claude_is_given_reads_the_household_or_the_tax_choices() -> None:
    """docs/privacy.md, ADR 0023 and docs/architecture.md: no module that builds what Claude is given (Ask, the
    prompts, the weekly review, the daily note, a draft request) imports or names the household or the tax
    choices, and no prompt mentions them."""
    files = [
        path
        for root in _CLAUDE_FACING
        for path in ([root] if root.is_file() else sorted(root.rglob("*")))
        if path.is_file() and path.suffix in {".py", ".md"}
    ]
    assert len(files) > 20 and any(path.suffix == ".md" for path in files)
    for path in files:
        text = path.read_text(encoding="utf-8")
        name = path.relative_to(ROOT).as_posix()
        if path.suffix == ".md":
            assert not re.search(r"household|tax_choice", text, re.IGNORECASE), name
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in _D3_MODULES, name
                assert _D3_NAMES.isdisjoint(alias.name for alias in node.names), name
            elif isinstance(node, ast.Import):
                assert not any(alias.name.startswith(_D3_MODULES) for alias in node.names), name
            elif isinstance(node, ast.Name):
                assert node.id not in _D3_NAMES, (name, node.id)
            elif isinstance(node, ast.Attribute):
                assert node.attr not in _D3_NAMES, (name, node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in _D3_NAMES, name


def test_the_choices_and_the_household_leave_ask_s_ledger_as_it_was(store: Store) -> None:
    """ADR 0023 and docs/architecture.md: the two rows are not what Ask reads — its fingerprint and the store's
    ledger token stay as they were when a choice is set and a household is saved."""
    from ordnung.assistant.ask import ledger_fingerprint
    from ordnung.db.store import HOUSEHOLD_META_KEY

    ids = seed_ledger(store)
    token, fingerprint = store.ledger_token(), ledger_fingerprint(store)
    assert store.set_tax_choice(ids["doc_phone"], True)
    household = {
        "format": 1,
        "members": [{"id": "hhm_k3j9x0a1b2c4", "name": "Alex Rivera", "signs": True}],
        "links": {ids["doc_phone"]: "hhm_k3j9x0a1b2c4"},
    }
    store.set_meta(HOUSEHOLD_META_KEY, json.dumps(household))
    assert store.ledger_token() == token
    assert ledger_fingerprint(store) == fingerprint


def test_a_phone_files_letters_but_never_edits_the_household_as_the_docs_say() -> None:
    """SPEC § 12b and ADR 0023: reading the household and filing letters are a phone's; the list itself is
    computer-only ("household edits"), like the profile."""
    assert phone_scope.classify("GET", "/api/household") == "phone"
    assert phone_scope.classify("PATCH", "/api/household") == "phone"
    assert phone_scope.classify("PUT", "/api/household") == "computer"
    assert phone_scope.NEVER_ON_PHONE[("PUT", "/api/household")] == "household edits"
    assert phone_scope.classify("PATCH", "/api/documents/doc_x") == "phone"  # For taxes, as any correction
    spec = _spec()
    assert "says why settings, profile and household edits, phone access" in spec
    assert (
        "`GET` and `PATCH /api/household` are a phone's (filing a letter for someone of the household, logged "
        '"Changed who a letter is for"); `PUT /api/household`, the list itself, is not'
    ) in spec
    adr = _adr(_ADR_HOUSEHOLD)
    assert "A paired phone may file a letter, as it may correct one, but never change the list" in adr


def test_adr_0023_says_suggest_never_file_and_the_policy_cites_it() -> None:
    """ADR 0023 (numbered after 0022): the principle, the policy's points, why a ``meta`` row and what was left
    out; the policy module cites it, and the limits it states are the module's."""
    from ordnung import ids
    from ordnung.secretary import household

    text = _ADR_HOUSEHOLD.read_text(encoding="utf-8")
    assert text.startswith("# ADR 0023 — Letters for your household are suggested, never filed\n")
    assert "**Status:** accepted" in text
    assert sorted(p.name for p in _ADR_HOUSEHOLD.parent.glob("0023-*")) == [_ADR_HOUSEHOLD.name]
    adr = _flat(text)
    for words in (
        "## Principle The addressee suggests, the person decides",
        "1. **Suggest, never file.**",
        "9. **Never seen by Claude.**",
        "## Why a `meta` row",
        "## Rejected or deferred",
        "## Consequences and known limits",
        f"at most {household.MAX_PEOPLE} people",
        f"at most {household.MAX_NAME_CHARS} characters",
        "The *For taxes* choices follow the same rule",
    ):
        assert words in adr, words
    assert "ADR 0023" in (household.__doc__ or "")
    assert "hhm" in ids.PREFIXES


def test_the_spec_names_the_letter_models_and_routes_d3_adds() -> None:
    """SPEC § 4, § 5, § 12c and § 13 against the code: the route-local models (``DocumentRow``'s
    ``ROUTE_FIELDS``, ``LetterDetail``, ``LetterRecord``) and what the routes answer; the two ``meta`` rows;
    ``/api/household``."""
    from ordnung import models
    from ordnung.api.routes import documents

    assert documents.ROUTE_FIELDS == {"found_in", "tax_choice"}
    assert set(documents.LetterDetail.model_fields) == set(models.DocumentDetail.model_fields) | {
        "tax_choice",
        "household",
    }
    assert set(documents.LetterRecord.model_fields) == set(Document.model_fields) | {"tax_choice"}
    paths = openapi_schema()["paths"]

    def answer(path: str) -> Any:
        return paths[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    assert answer("/api/documents/{doc_id}")["$ref"].endswith("/LetterDetail")
    assert answer("/api/documents.json")["items"]["$ref"].endswith("/LetterRecord")
    assert set(paths["/api/household"]) == {"get", "put", "patch"}
    spec = _spec()
    for words in (
        "`DocumentRow` also carries `tax_choice`, the person's own *For taxes* choice",
        "`ROUTE_FIELDS` (`found_in`, `tax_choice`)",
        "`LetterDetail` (`models.DocumentDetail` plus `tax_choice` and `household`",
        "`LetterRecord` (`Document` plus `tax_choice`)",
        '`tax_choices` (`{"<doc_id>": true|false}`',
        "need no migration (`user_version` stays 5)",
        "`delete_document` removes the letter from both in its transaction",
        "Meta `household` and `tax_choices` (the person's household and *For taxes* choices) travel as they are",
        "also `tax_choice`: `true` or `false` is the person's own *For taxes* choice, `null` goes back to "
        "Claude's mark",
        "`household` (GET: the people with their letters",
        "as `LetterRecord`s, each with its `tax_choice`",
    ):
        assert words in spec, words


def test_the_spec_and_architecture_say_how_for_taxes_and_the_household_work() -> None:
    """SPEC § 9, § 11 and § 14 and docs/architecture.md: who decides a letter counts for taxes (``for_taxes``),
    where the choice lives and who never reads it; the household's paragraph, its trust boundary and the
    daily check; the pages."""
    from ordnung.secretary.tax_choice import for_taxes

    marked = Document.model_construct(id="doc_a", tax_relevant=True)
    unmarked = Document.model_construct(id="doc_b", tax_relevant=False)
    assert (for_taxes(marked, {}), for_taxes(unmarked, {})) == (True, False)
    assert (for_taxes(marked, {"doc_a": False}), for_taxes(unmarked, {"doc_b": True})) == (False, True)
    spec = _spec()
    for words in (
        "over the letters that count for taxes (the person's own *For taxes* choice, else Claude's mark; not those "
        "waiting from the folder)",
        "forget the household's filings of letters deleted for good on a computer still on 0.2.0",
        "For a letter the person filed for someone of their household (ADR 0023)",
        "**For taxes** (`aria-pressed`",
        "a **Year** select (`?year=`",
        "**Your household** (`#set-household`",
        '"You marked this for taxes."',
    ):
        assert words in spec, words
    architecture = _flat((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    for words in (
        "**For taxes** is the person's own choice over Claude's mark",
        "`Ledger.tax_choices` is read lazily, so Ask's server, which builds Ledgers, never reads the row",
        "Ask and the weekly review's snapshot for *Weekly Ideas* keep Claude's own mark.",
        "**Your household** (`secretary/household.py`, a written policy;",
        f"[ADR 0023](decisions/{_ADR_HOUSEHOLD.name})",
        "a letter is filed for someone of the person's household only when they press",
    ):
        assert words in architecture, words


@_UNTIL_D3
async def test_a_tax_choice_is_kept_apart_and_followed_as_the_docs_say(data_dir: Path) -> None:
    """d3-tax-choice against the CHANGELOG, README, SPEC and docs/architecture.md: the choice is set by the PATCH
    and never touches Claude's mark; the letter's page, its row and the records carry it; the tax-season Idea
    follows it; a letter waiting from the folder can't be marked; ``Ledger.tax_choices`` is lazy and the ZIP's
    selection takes the choices."""
    import functools

    from helpers_secretary import add_doc

    assert isinstance(inspect.getattr_static(Ledger, "tax_choices"), functools.cached_property)
    assert "choices" in inspect.signature(letters_zip.matches).parameters
    async with api_for(data_dir) as api:
        store = api.ctx.store
        payslip = add_doc(store, "payslip", title="Payslip March", doc_date="2025-03-31")
        waiting = add_doc(store, "waiting", status="held", ai_private=True, doc_date="2025-04-02")
        marked = await api.client.patch(f"/api/documents/{payslip}", json={"tax_choice": True})
        assert marked.status_code == 200, marked.text
        letter = store.get_document(payslip)
        assert letter is not None and letter.tax_relevant is False  # Claude's mark, as it was
        assert (await api.client.get(f"/api/documents/{payslip}")).json()["tax_choice"] is True
        rows = {row["id"]: row for row in (await api.client.get("/api/documents")).json()}
        records = {row["id"]: row for row in (await api.client.get("/api/documents.json")).json()}
        assert rows[payslip]["tax_choice"] is True and records[payslip]["tax_choice"] is True
        (idea,) = tax_documents(Ledger(store, date(2026, 3, 1)))
        assert payslip in {ref.id for ref in idea.refs}
        refused = await api.client.patch(f"/api/documents/{waiting}", json={"tax_choice": True})
        assert refused.status_code == 409
        cleared = await api.client.patch(f"/api/documents/{payslip}", json={"tax_choice": None})
        assert cleared.status_code == 200 and store.tax_choices() == {}


@_UNTIL_D3
async def test_the_household_files_a_letter_only_on_a_press_as_the_docs_say(data_dir: Path) -> None:
    """d3-household-core against ADR 0023, SPEC and docs/privacy.md: adding a person files nothing; a PATCH files
    and the letter's page says so; the person's own name is refused with the docs' words; deleting the letter for
    good leaves no trace; the daily check prunes."""
    from ordnung import tick
    from ordnung.secretary import household

    async with api_for(data_dir) as api:
        ids = seed_ledger(api.ctx.store)
        empty = (await api.client.get("/api/household")).json()
        assert (empty["members"], empty["filed"], empty["mine"]) == ([], {}, [])
        added = await api.client.put(
            "/api/household",
            json={"base": empty["version"], "members": [{"id": None, "name": "Alex Rivera", "signs": True}]},
        )
        assert added.status_code == 200, added.text
        (alex,) = added.json()["members"]
        assert alex["id"].startswith("hhm_") and added.json()["filed"] == {}
        doc = ids["doc_phone"]
        filed = await api.client.patch("/api/household", json={"letters": {doc: alex["id"]}})
        assert filed.status_code == 200 and filed.json()["filed"] == {doc: alex["id"]}
        page = (await api.client.get(f"/api/documents/{doc}")).json()
        assert page["household"]["filed_for"]["name"] == "Alex Rivera"
        own = await api.client.put(
            "/api/household",
            json={
                "base": filed.json()["version"],
                "members": [{"id": alex["id"], "name": "Alex Rivera"}, {"id": None, "name": "Sam Rivera"}],
            },
        )
        assert own.status_code == 422 and own.json()["detail"] == household.OWN_NAME
        assert household.TOO_MANY == "Your household can have at most 12 people."
        purged = await api.client.delete(f"/api/documents/{doc}", params={"purge": True})
        assert purged.status_code == 200
        assert doc not in (await api.client.get("/api/household")).json()["filed"]
        assert doc not in (api.ctx.store.get_meta("household") or "")
    assert "household.prune_gone" in inspect.getsource(tick)


#: The words the docs quote from the pages, and the file each is in (d3-tax-choice, d3-household-core, d3-inbox,
#: d3-household-surfaces).
_D3_PAGE_WORDS = (
    ("features/document/TaxToggle.tsx", "You marked this letter for taxes."),
    (
        "features/document/TaxToggle.tsx",
        "You took this letter off your letters for taxes. Claude had marked it.",
    ),
    ("features/document/TaxToggle.tsx", "Claude marked this letter for taxes when it read it."),
    ("pages/TaxYearPage.tsx", "You marked this for taxes."),
    ("pages/TaxYearPage.tsx", "you can mark or unmark any letter on its page."),
    ("features/inbox/InboxToolbar.tsx", "Year, by the date on the letter"),
    ("features/inbox/InboxToolbar.tsx", "Whose letters"),
    ("features/household/HouseholdCard.tsx", "Claude never sees this list."),
    ("features/household/HouseholdCard.tsx", "Signs their own letters"),
    ("features/household/LetterFor.tsx", "Who is this letter for?"),
    ("features/household/LetterFor.tsx", "Its dates, reminders and numbers stay in your Ordnung either way."),
    ("features/household/LetterFor.tsx", "Also file this letter for"),
    ("features/household/FileThese.tsx", "not filed yet"),
    ("features/letters/LetterComposer.tsx", "who doesn't sign letters, so it goes out in your name."),
    ("features/settings/DataSection.tsx", "people & organisations, your household, your drafts"),
)


@_UNTIL_D3
def test_the_pages_say_what_the_docs_quote() -> None:
    """The words SPEC, README, the CHANGELOG and docs/privacy.md quote from the pages are the pages' own."""
    web = ROOT / "web" / "src"
    for path, words in _D3_PAGE_WORDS:
        assert words in (web / path).read_text(encoding="utf-8"), (path, words)


@_UNTIL_D3
def test_the_tests_the_architecture_names_for_d3_exist() -> None:
    """docs/architecture.md's testing strategy names D3's tests; they come with the other D3 packages."""
    architecture = _flat((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    for path in (
        "tests/test_store_choices.py",
        "tests/test_tax_choice.py",
        "tests/test_household.py",
        "tests/test_api_household.py",
        "tests/test_household_vectors.py",
        "web/src/mocks/householdVectors.json",
        "web/e2e/real-app-household.spec.ts",
        "web/e2e/tax-toggle-layout.spec.ts",
        "web/e2e/real-app-export.spec.ts",
    ):
        assert f"`{path}`" in architecture, path
        assert (ROOT / path).is_file(), path
