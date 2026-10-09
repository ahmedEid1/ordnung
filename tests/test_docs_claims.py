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

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock, sync
from ordnung.api.app import openapi_schema
from ordnung.app_context import AppContext, build_context
from ordnung.assistant.rules_tools import build_rules_server
from ordnung.backup import MAX_PASSPHRASE_CHARS, MIN_PASSPHRASE_CHARS
from ordnung.backup.container import DEFAULT_KDF, MAX_SCRYPT_BYTES
from ordnung.db.store import Store
from ordnung.drafts.compose import compose
from ordnung.drafts.sent import letter_profile
from ordnung.drafts.template_letters import TEMPLATES
from ordnung.ingest.extract import ExtractionInput, extraction_request
from ordnung.ingest.plan import VerifiedItem, own_context
from ordnung.llm.base import LLMRequest
from ordnung.llm.claude_cli import MIN_CLAUDE_VERSION, version_text
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import BackupCopy, DateSpec, Evidence, ExtractedItem, Identifier, Page, Party, Profile
from ordnung.phone import scope as phone_scope
from ordnung.rules.deadlines import RuleContext, compute_due
from ordnung.rules.postcodes import Home, suggest_land_why
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
    """README's quality table says the rules engine has "`mypy` strict on it": pyproject.toml gives the whole
    package, the rules engine with it, every check of ``mypy --strict``, and no module is let off."""
    mypy = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]
    assert mypy["strict"] is True and mypy["files"] == ["src/ordnung"]
    assert "overrides" not in mypy
    assert "`mypy` strict on it" in _readme()


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
    """README Limitations: a letter addressed to someone else says so and can be answered in their name, but it is
    filed as yours — there is one person's Ordnung, and My numbers takes a number as yours by its label and the
    letter, never by the addressee."""
    assert (
        "One person's Ordnung, in use on one computer at a time. A letter addressed to someone else (a partner, a "
        "child) says so, and a reply to it can go out in their name, but its dates, reminders and numbers count "
        "as yours."
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
