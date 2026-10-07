"""The factual claims of README.md and docs/, checked against the code.

Written by a documentation audit: each test states a documented claim as an assertion, so a change
that makes the docs untrue fails here.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.assistant.rules_tools import build_rules_server
from ordnung.db.store import Store
from ordnung.drafts.compose import compose
from ordnung.drafts.template_letters import TEMPLATES
from ordnung.ingest.extract import ExtractionInput, extraction_request
from ordnung.ingest.plan import VerifiedItem
from ordnung.llm.base import LLMRequest
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import DateSpec, Evidence, ExtractedItem, Identifier, Page, Party, Profile
from ordnung.phone import scope as phone_scope
from ordnung.rules.deadlines import RuleContext, compute_due
from ordnung.tick import DailyTick

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
    """README.md:232 says 'mypy (strict on the core)': pyproject.toml gives the rules engine the
    per-module checks of ``mypy --strict``."""
    mypy = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]
    strict = [o for o in mypy.get("overrides", []) if "ordnung.rules.*" in o["module"]]
    assert strict and all(
        strict[0].get(flag) is True
        for flag in ("disallow_untyped_defs", "disallow_any_generics", "warn_return_any", "strict_equality")
    )
    assert strict[0].get("implicit_reexport") is False


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


def test_the_numbers_without_the_sender_s_land_match_their_results_file() -> None:
    """M3: README row ⁹, its footnote, the bullet and Limitations, deadline-rules.md and docs/evals.md cite the
    replay without the sender's Land (scripts/eval_without_land.py, as the app runs until the person sets a
    sender's Land): its accuracy per split, no late date, extra misses 1–3 days early — and the numbers with the
    Land it sets them against are the published replays' (rows ⁴, ⁶ and ⁸)."""
    readme = _readme()
    results = _results("2026-10-06-claude-sonnet-5-without-land.json")
    assert results["schema"] == "ordnung-eval-without-land/1"
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


async def test_drafting_a_letter_never_sends_your_address(draft_ctx: tuple[AppContext, FakeBackend]) -> None:
    """docs/privacy.md: your address is never sent; drafting sends the recipient's name (first line)."""
    ctx, backend = draft_ctx
    ctx.store.save_profile(
        Profile(name="Sam Rivera", address="Beispielweg 5\n12345 Musterstadt", language="en", region="NW")
    )
    telecom = ctx.store.add_party(
        name="FunkNetz Mobile",
        kind="telecom",
        address="Funkallee 1\n10115 Berlin",
        identifiers=[Identifier(label="Kundennummer", value="4711-0815")],
    ).id
    contract = ctx.store.add_contract(
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
    draft = await compose(ctx, "cancellation", contract_id=contract, instructions="Bitte bestätigen")
    assert "Beispielweg 5" in draft.sender_block  # the letter itself has the address
    (request,) = [call for call in backend.calls if isinstance(call, LLMRequest) and call.purpose == "draft"]
    sent = request.prompt + request.system
    assert "Beispielweg 5" not in sent and "12345 Musterstadt" not in sent
    assert "10115 Berlin" not in sent


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
    devices on that network — never through a VPN, a tunnel, a container or a virtual machine". The
    address must be a home-network one (no public, shared-carrier, link-local or loopback address), a
    client must be in its subnet, and a tunnel's interface is never offered (design § 16.5, amendment M2)."""
    net = importlib.import_module("ordnung.phone.net")
    assert "over your home Wi-Fi" in _flat(_readme())
    assert (
        "answers only devices on that network — never through a VPN, a tunnel, a container or a virtual "
        "machine"
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
