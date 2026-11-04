"""The benchmark's analysis (``evals/analysis.py``): the held-out splits re-analysed, and the pre-registered final run.

The re-analysis reads the three held-out results files as recorded and must reproduce what the evaluation plan
recomputed from them by independent scripts: 163/168 for Ordnung, 31 vs 4 and 14 vs 5 discordant pairs, the flags
catching none of Ordnung's 5 wrong dates, and the crossover with the rules-text prompt at r = 5.5. The intervals the
pages publish today stay reproducible beside the new ones. The final run's analysis is checked on synthetic reads
whose statistics are worked out by hand, written to disk with every frozen input the pre-registration pins (a
:class:`World`): each mismatch with them is refused unless a deviation recorded at the time names it, and then has
its registered consequence.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import sys
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import analysis, report, stats  # noqa: E402

RESULTS = ROOT / "evals" / "results"
BASELINES = ("llm_only", "llm_rules_text", "llm_rules_tool")
CONDITIONS = ("ordnung", *BASELINES)


@pytest.fixture(scope="module")
def held_out_runs() -> list[analysis.Run]:
    return [analysis.read_run(RESULTS / name) for name in analysis.HELD_OUT_AS_RECORDED]


@pytest.fixture(scope="module")
def reanalysis(held_out_runs: list[analysis.Run]) -> dict[str, Any]:
    return analysis.reanalyse(held_out_runs, date="2026-10-29")


# --------------------------------------------------------------------------------------------------
# The held-out splits as recorded
# --------------------------------------------------------------------------------------------------


def test_the_reanalysis_reproduces_the_pooled_held_out_counts(reanalysis: dict[str, Any]) -> None:
    assert reanalysis["meta"]["pre_registered"] is False
    assert reanalysis["meta"]["splits"] == ["holdout", "holdout2", "holdout3"]
    assert (reanalysis["items"], reanalysis["letters"], reanalysis["clusters"]) == (168, 189, 129)
    expected = {  # right, late, early, missed of 168
        "ordnung": (163, 2, 2, 1),
        "llm_only": (136, 13, 19, 0),
        "llm_rules_text": (154, 1, 13, 0),
        "llm_rules_tool": (167, 1, 0, 0),
    }
    for condition, (right, late, early, missed) in expected.items():
        summary = reanalysis["conditions"][condition]
        assert summary["exact"]["k"] == right and summary["exact"]["n"] == 168
        assert (summary["late"]["k"], summary["early"]["k"], summary["missed"]["k"]) == (late, early, missed)
        assert summary["harmful"]["k"] == late + missed
        assert summary["declined"]["k"] == 0


def test_single_rates_get_exact_intervals_and_keep_the_published_ones(
    reanalysis: dict[str, Any], held_out_runs: list[analysis.Run]
) -> None:
    ordnung = reanalysis["conditions"]["ordnung"]
    assert reanalysis["meta"]["methods"]["single_rate"] == "clopper-pearson"  # one method, stated once
    assert ordnung["exact"]["ci"][0] == pytest.approx(0.9319, abs=5e-5)
    assert ordnung["exact"]["ci"][1] == pytest.approx(0.9903, abs=5e-5)
    # the interval docs/evals.md publishes today (cluster bootstrap, Wilson at 0 or 1) is reproduced beside it
    published = report.pooled_held_out([run.results for run in held_out_runs])
    for condition in CONDITIONS:
        for ours, theirs in (("exact", "due_date_accuracy"), ("late", "dangerous_late_rate")):
            got = reanalysis["conditions"][condition][ours]["published_ci"]
            assert got == pytest.approx(published["metrics"][condition][theirs]["ci"], rel=1e-9)
    assert [round(x * 100, 1) for x in ordnung["exact"]["published_ci"]] == [94.3, 99.4]


def test_paired_tests_on_the_pooled_items(reanalysis: dict[str, Any]) -> None:
    accuracy = reanalysis["paired"]["accuracy"]
    llm_only = accuracy["ordnung-vs-llm_only"]
    assert (llm_only["b"], llm_only["c"], llm_only["n"]) == (31, 4, 168)
    assert llm_only["exact_p"] == pytest.approx(3.4655e-6, rel=1e-3)
    text = accuracy["ordnung-vs-llm_rules_text"]
    assert (text["b"], text["c"]) == (14, 5)
    assert text["exact_p"] == pytest.approx(0.0636, abs=5e-5)
    assert text["midp"] == pytest.approx(0.0414, abs=5e-5)
    assert text["holm_midp"] == pytest.approx(0.0828, abs=5e-5)
    assert text["verdict"] == "suggestive"
    assert [round(x * 100, 1) for x in text["bonett_price"]] == [0.1, 10.5]
    tool = accuracy["ordnung-vs-llm_rules_tool"]
    assert (tool["b"], tool["c"], tool["exact_p"]) == (1, 5, 0.21875)
    assert reanalysis["paired"]["late"]["ordnung-vs-llm_only"]["exact_p"] == pytest.approx(0.0074, abs=5e-5)
    agent = reanalysis["paired"]["agent"]["llm_rules_tool-vs-llm_rules_text"]
    assert (agent["b"], agent["c"]) == (13, 0) and agent["exact_p"] == pytest.approx(2.44e-4, rel=1e-2)
    # harmful = late or missed: Ordnung 3, the model alone 13; no item is late for both (2 vs 13 above)
    harmful = reanalysis["paired"]["harmful"]["ordnung-vs-llm_only"]
    assert harmful["b"] - harmful["c"] == 3 - 13 and harmful["b"] in (2, 3)


def test_a_clear_verdict_needs_the_exact_and_the_clustered_test_after_holm(
    reanalysis: dict[str, Any],
) -> None:
    """Late or missed, Ordnung vs the model alone: 3 vs 13 discordant. Exact McNemar 0.0213 (Holm 0.0638), mid-p
    0.0127 (Holm 0.0382), letter-cluster sign-flip 0.0296 (Holm 0.0888): only the item-level mid-p clears 0.05, so
    the verdict is suggestive, not clear. Late alone (2 vs 13) clears both tests after Holm."""
    harmful = reanalysis["paired"]["harmful"]["ordnung-vs-llm_only"]
    assert (harmful["b"], harmful["c"]) == (3, 13)
    assert harmful["exact_p"] == pytest.approx(0.02127, abs=5e-5)
    assert harmful["holm_exact"] == pytest.approx(0.06381, abs=5e-5)
    assert harmful["holm_midp"] == pytest.approx(0.03818, abs=5e-5)
    assert harmful["signflip"]["p"] == pytest.approx(0.02960, abs=5e-5)
    assert harmful["signflip"]["holm"] == pytest.approx(0.08881, abs=5e-5)
    assert harmful["verdict"] == "suggestive"
    late = reanalysis["paired"]["late"]["ordnung-vs-llm_only"]
    assert late["holm_exact"] < 0.05 and late["signflip"]["holm"] < 0.05 and late["verdict"] == "clear"
    assert reanalysis["paired"]["accuracy"]["ordnung-vs-llm_only"]["verdict"] == "clear"
    method = reanalysis["meta"]["methods"]["verdict"]
    assert "Holm-adjusted exact p" in method and "Holm-adjusted cluster sign-flip p" in method


def test_paired_bootstraps_reproduce_the_published_differences(
    reanalysis: dict[str, Any], held_out_runs: list[analysis.Run]
) -> None:
    published = report.pooled_held_out([run.results for run in held_out_runs])["comparisons"]
    for key, ours in reanalysis["paired"]["accuracy"].items():
        assert ours["published_bootstrap"]["ci"] == pytest.approx(
            published[key]["due_date_accuracy_diff"]["ci"], rel=1e-9
        )
    text = reanalysis["paired"]["accuracy"]["ordnung-vs-llm_rules_text"]["published_bootstrap"]
    assert [round(x * 100, 1) for x in text["ci"]] == [0.6, 10.6]


def test_the_rules_text_claim_is_corrected(reanalysis: dict[str, Any]) -> None:
    claim = reanalysis["findings"]["rules_text_claim"]
    assert claim["text"] == (
        "14 vs 5 discordant, exact p 0.064, Holm-adjusted 0.127 (mid-p 0.041, Holm-adjusted 0.083): suggestive, "
        "not settled"
    )
    assert claim["holm_exact"] == pytest.approx(0.12714, abs=5e-5)
    assert claim["published_text"] == "+5.4 points, 95 % interval +0.6 to +10.6"


def test_flags_caught_none_of_ordnungs_wrong_dates(reanalysis: dict[str, Any]) -> None:
    ordnung = reanalysis["conditions"]["ordnung"]["selective"]
    assert (ordnung["please_check"]["recall_wrong"]["k"], ordnung["please_check"]["recall_wrong"]["n"]) == (
        0,
        5,
    )
    assert (ordnung["any_flag"]["recall_wrong"]["k"], ordnung["any_flag"]["recall_wrong"]["n"]) == (0, 5)
    assert ordnung["please_check"]["recall_wrong"]["ci"][1] == pytest.approx(0.5218, abs=5e-4)
    assert (ordnung["unflagged"]["accuracy"]["k"], ordnung["unflagged"]["accuracy"]["n"]) == (123, 128)
    assert ordnung["auroc"] == pytest.approx(0.5 * 123 / 163)
    assert round(ordnung["aurc"]["aurc"], 3) == 0.038 and round(ordnung["aurc"]["excess"], 3) == 0.037
    tiers = ordnung["tiers"]
    assert (tiers["none"]["right"], tiers["none"]["wrong"]) == (123, 5)
    assert (tiers["second_look"]["right"], tiers["second_look"]["wrong"]) == (34, 0)
    assert (tiers["please_check"]["right"], tiers["please_check"]["wrong"]) == (6, 0)
    assert reanalysis["findings"]["flags"]["ordnung"] == {"caught": 0, "wrong": 5}
    by_confidence = reanalysis["conditions"]["ordnung"]["by_confidence"]
    assert by_confidence["high"] == {"right": 123, "wrong": 4}
    assert by_confidence["medium"] == {"right": 35, "wrong": 0}
    assert by_confidence["low"] == {"right": 5, "wrong": 0}
    # the model alone's own stated confidence is weakly useful: its medium holds 15 of its 32 errors
    llm_only = reanalysis["conditions"]["llm_only"]["selective"]
    assert (llm_only["any_flag"]["recall_wrong"]["k"], llm_only["any_flag"]["recall_wrong"]["n"]) == (15, 32)
    assert (llm_only["unflagged"]["accuracy"]["k"], llm_only["unflagged"]["accuracy"]["n"]) == (106, 123)
    assert round(llm_only["auroc"], 2) == 0.62 and round(llm_only["aurc"]["aurc"], 3) == 0.147


def test_ordnungs_wrong_dates_are_listed_by_id(reanalysis: dict[str, Any]) -> None:
    errors = [e for e in reanalysis["errors"] if e["condition"] == "ordnung"]
    assert {(e["entry_id"], e["outcome"], e["direction"]) for e in errors} == {
        ("holdout-adversarial-conflicting_dates-1", "wrong", "late"),
        ("holdout-adversarial-conflicting_dates-2", "wrong", "late"),
        ("holdout-tax_assessment-F1", "wrong", "early"),
        ("holdout2-tax_assessment-H1", "wrong", "early"),
        ("holdout2-adversarial-injection_visible-1", "missed", None),
    }
    late = {e["entry_id"]: e["days_off"] for e in errors if e["direction"] == "late"}
    assert late == {
        "holdout-adversarial-conflicting_dates-1": 7,
        "holdout-adversarial-conflicting_dates-2": 1,
    }
    assert not any(e["flagged"] for e in errors)
    assert {e["tier"] for e in errors} == {"none"}
    assert len(reanalysis["errors"]) == 5 + 32 + 14 + 1


def test_harm_weighted_loss_and_crossover(reanalysis: dict[str, Any]) -> None:
    loss = reanalysis["conditions"]["ordnung"]["loss"]
    assert (round(loss["1"], 1), round(loss["5"], 1), round(loss["20"], 1)) == (3.0, 10.1, 36.9)
    assert round(reanalysis["conditions"]["llm_only"]["loss"]["1"], 1) == 19.0
    crossover = reanalysis["crossover"]["ordnung-vs-llm_rules_text"]
    assert crossover["outcome"] == "a_then_b" and crossover["r_star"] == 5.5
    shares = crossover["shares"]
    assert set(shares) == {"a_then_b", "b_then_a", "a_lower", "b_lower", "identical"}
    assert sum(shares.values()) == pytest.approx(1.0) and 0 < shares["a_then_b"] < 1
    boot = crossover["bootstrap"]
    # r* is resampled only where the losses cross the same way: a finite range around the point
    assert boot["draws"] == round(shares["a_then_b"] * boot["resamples"])
    assert 1 <= boot["lo"] < 5.5 < boot["hi"] and math.isfinite(boot["hi"])
    # Ordnung (2 early, 3 harmful) against the agent (0 early, 1 harmful): the agent is lower at every r, not a
    # crossing at a negative r; and the model alone (13 harmful) is never lower than Ordnung
    tool = reanalysis["crossover"]["ordnung-vs-llm_rules_tool"]
    assert (tool["outcome"], tool["r_star"]) == ("b_lower", None)
    assert tool["bootstrap"]["lo"] is None and tool["bootstrap"]["draws"] == 0
    assert tool["shares"]["b_lower"] > 0.5
    assert reanalysis["crossover"]["ordnung-vs-llm_only"]["outcome"] == "a_lower"
    assert reanalysis["crossover"]["ordnung-vs-llm_only"]["r_star"] is None
    assert reanalysis["conditions"]["ordnung"]["days_late"] == [1, 7]
    finding = reanalysis["findings"]["rules_text_crossover"]
    assert finding["r_star"] == 5.5 and 1 <= finding["lo"] < 5.5 < finding["hi"]
    assert finding["text"].startswith(
        "Ordnung's harm-weighted loss is the lower one until a late or missed date costs 5.5 early ones; "
    )
    assert "never" not in finding["text"] and "% of 2,000 resamples" in finding["text"]


def test_letters_fully_right_and_cost(reanalysis: dict[str, Any]) -> None:
    fully = {c: reanalysis["conditions"][c]["letters_fully_right"] for c in CONDITIONS}
    assert {c: (v["k"], v["n"]) for c, v in fully.items()} == {
        "ordnung": (146, 159),
        "llm_only": (113, 159),
        "llm_rules_text": (119, 159),
        "llm_rules_tool": (141, 159),
    }
    costs = {c: reanalysis["conditions"][c]["cost"] for c in CONDITIONS}
    assert {
        c: (round(v["usd_per_letter"], 4), round(v["usd_per_right_date"], 4)) for c, v in costs.items()
    } == {
        "ordnung": (0.0845, 0.0980),
        "llm_only": (0.0500, 0.0695),
        "llm_rules_text": (0.0472, 0.0579),
        "llm_rules_tool": (0.0573, 0.0649),
    }
    assert reanalysis["conditions"]["ordnung"]["latency_ms"]["p50"] > 0


def test_the_output_holds_no_letter_text(
    reanalysis: dict[str, Any], held_out_runs: list[analysis.Run]
) -> None:
    """Ids, counts, hashes and metric values only: no title, quote, explanation or warning from the results files."""
    rendered = analysis.render(reanalysis)
    texts: set[str] = set()
    for run in held_out_runs:
        for entry in run.results["entries"]:
            texts.update(item.get("title") or "" for item in entry.get("expected") or [])
            for value in entry["conditions"].values():
                prediction = value.get("prediction") or {}
                texts.update(prediction.get("warnings") or [])
                for item in prediction.get("items") or []:
                    texts.update(
                        [item.get("title") or "", item.get("quote") or "", item.get("explanation") or ""]
                    )
                    texts.update(item.get("notes") or [])
                for item in (value.get("score") or {}).get("items") or []:
                    texts.add(item.get("title") or "")
    leaks = [text for text in texts if len(text) >= 8 and text in rendered]
    assert leaks == []
    for key in ('"title"', '"quote"', '"explanation"', '"warnings"', '"expected"', '"predicted"'):
        assert key not in rendered


def test_the_render_is_deterministic(held_out_runs: list[analysis.Run], reanalysis: dict[str, Any]) -> None:
    again = analysis.reanalyse(list(reversed(held_out_runs)), date="2026-10-29")
    assert analysis.render(again) == analysis.render(reanalysis)


def test_the_committed_reanalysis_is_what_the_results_render() -> None:
    committed = sorted(RESULTS.glob(f"*-claude-sonnet-5-{analysis.REANALYSIS_KIND}.json"))
    assert len(committed) == 1, committed
    assert analysis.main(["--check"]) == 0


def test_write_then_check_and_a_one_character_edit_fails(tmp_path: Path) -> None:
    holdout3 = str(RESULTS / analysis.HELD_OUT_AS_RECORDED[2])  # one split keeps the test quick
    assert analysis.main(["--write", "--date", "2030-01-02", "--out-dir", str(tmp_path), holdout3]) == 0
    written = tmp_path / "2030-01-02-claude-sonnet-5-heldout-reanalysis.json"
    assert written.is_file()
    assert analysis.main(["--check", "--out-dir", str(tmp_path), holdout3]) == 0
    text = written.read_text(encoding="utf-8")
    index = text.index('"items": 56')
    written.write_text(text[:index] + '"items": 57' + text[index + 11 :], encoding="utf-8")
    assert analysis.main(["--check", "--out-dir", str(tmp_path), holdout3]) == 1


def test_check_without_a_committed_file_fails(tmp_path: Path) -> None:
    assert analysis.main(["--check", "--out-dir", str(tmp_path)]) == 1


# --------------------------------------------------------------------------------------------------
# The pre-registered final run, on synthetic reads
# --------------------------------------------------------------------------------------------------

#: (letter, cluster, number of scored items): L6 is the photo of L5, so they share a cluster.
LETTERS = (
    ("L1", "L1", 1),
    ("L2", "L2", 2),
    ("L3", "L3", 1),
    ("L4", "L4", 1),
    ("L5", "L5", 1),
    ("L6", "L5", 1),
)
TRUE_DATE = "2027-03-10"
LATE_DATE = "2027-03-12"
EARLY_DATE = "2027-03-08"
#: The synthetic pre-registration: its window [D0, LAST], the claude version and the model that answer, and the
#: fingerprints every read must carry.
D0, LAST = "2027-01-01", "2027-01-08"
CLI = "2.1.0"
SERVED = "claude-sonnet-5"
FINGERPRINTS = {condition: f"{i:016x}" for i, condition in enumerate(CONDITIONS, start=1)}
#: A results file's manifest hash until :meth:`World.write` knows the synthetic manifest's.
MANIFEST_PENDING = "the synthetic manifest"


def _outcome(condition: str, read: int, letter: str, index: int) -> str:
    """right / late / early / missed, by hand: see the docstring of the final-run tests."""
    if condition == "ordnung" and letter == "L3" and read == 2:
        return "late"
    if condition == "llm_only":
        if letter == "L1":
            return "early"
        if letter == "L2" and index == 0:
            return "missed"
        if letter == "L4" and read == 1:
            return "late"
    if condition == "llm_rules_tool" and letter == "L5" and read == 3:
        return "early"
    return "right"


def _score_item(index: int, outcome: str) -> dict[str, Any]:
    predicted = {"right": TRUE_DATE, "late": LATE_DATE, "early": EARLY_DATE, "missed": None}[outcome]
    return {
        "index": index,
        "outcome": {"right": "correct", "late": "wrong", "early": "wrong", "missed": "missed"}[outcome],
        "expected": TRUE_DATE,
        "direction": outcome if outcome in ("late", "early") else None,
        "days_off": {"late": 2, "early": -2}.get(outcome),
        "predicted": predicted,
        "pred_index": None if outcome == "missed" else index,
        "flagged": False,
        "confidence": None if outcome == "missed" else "high",
        "cause": None,
    }


def _read_day(read: int) -> str:
    """The day each read's units are recorded on, unless a test says otherwise: read r on 2027-01-0r."""
    return f"2027-01-0{read}"


def _synthetic_run(
    split: str,
    read: int,
    *,
    model: str = "claude-sonnet-5",
    letters: tuple[tuple[str, str, int], ...] = LETTERS,
    outcome: Callable[[str, int, str, int], str] = _outcome,
    day: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """One results file as the runner writes it: the frozen inputs the pre-registration pins (the fingerprints, the
    manifest, a clean tree, the claude version) and each letter's today, the day its unit was recorded."""
    entries = []
    for letter, cluster, count in letters:
        conditions = {}
        for condition in CONDITIONS:
            items = [_score_item(i, outcome(condition, read, letter, i)) for i in range(count)]
            prediction_items = [
                {"spec": {"type": "relative", "amount": 2, "unit": "weeks", "anchor": "document_date"}}
                for _ in range(count)
            ]
            conditions[condition] = {
                "prediction": {
                    "items": prediction_items,
                    "document_date": "2027-02-24",
                    "sender_kind": "authority",
                    "fingerprint": FINGERPRINTS[condition],
                },
                "score": {
                    "cluster": cluster,
                    "items": items,
                    "false_positives": 0,
                    "cost_usd": 0.01 * (1 + CONDITIONS.index(condition)),
                    "latency_ms": 1000 * read,
                    "calls": 1,
                    "kind_ok": letter != "L1",
                    "tool_calls": {"compute_deadline": 1} if condition == "llm_rules_tool" else None,
                    "adversarial": {},
                    "failed": None,
                    "error": None,
                },
            }
        entries.append(
            {
                "id": f"{split}-{letter}",
                "family": "f",
                "modality": "photo" if letter == "L6" else "text",
                "today": day(letter) if day is not None else _read_day(read),
                "conditions": conditions,
            }
        )
    return {
        "schema": 1,
        "meta": {
            "date": f"2027-01-0{read}",
            "model": model,
            "split": split,
            "repeat": read,
            "backend": "live",
            "commit": "abc1234",
            "conditions": list(CONDITIONS),
            "partial": False,
            "seed": 20260925,
            "resamples": 2000,
            "fingerprints": dict(FINGERPRINTS),
            "dataset": {"name": "synthetic", "version": 1, "manifest_sha256": MANIFEST_PENDING},
            "dirty": [],
            "cli_version": CLI,
            "simulated_today": sorted({entry["today"] for entry in entries}),
            "recording_day": None,
        },
        "metrics": {},
        "entries": entries,
    }


def _write(tmp_path: Path, name: str, data: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class World:
    """A synthetic final run on disk: holdout4 read three times and newkinds once, the pre-registration, its
    deviations file, the dataset manifest, the day index and the ledger — every frozen input as registered, until a
    test changes one."""

    def __init__(
        self,
        root: Path,
        *,
        letters: tuple[tuple[str, str, int], ...] = LETTERS,
        outcome: Callable[[str, int, str, int], str] = _outcome,
        pool_with: tuple[str, ...] = (),
        prereg_name: str = "final.json",
        results: Path | None = None,
    ) -> None:
        self.root = root
        #: Where the results files go (and the earlier splits ``pool_with`` names are read).
        self.results = results or root
        self.recorded = root / "recorded"
        self.dataset = root / "dataset"
        self.prereg_path = root / prereg_name
        self.docs: dict[tuple[str, int], dict[str, Any]] = {
            ("holdout4", read): _synthetic_run("holdout4", read, letters=letters, outcome=outcome)
            for read in (1, 2, 3)
        }
        self.docs[("newkinds", 1)] = _synthetic_run("newkinds", 1, letters=letters[:2])
        #: More results files, by name (a second copy of a read, another model's …).
        self.extra: dict[str, dict[str, Any]] = {}
        #: Per (entry id, item index): the dates a disputed convention's other reading gives.
        self.alternatives: dict[tuple[str, int], list[str]] = {}
        #: Per (split, read, entry id): the claude version the day index records (default CLI).
        self.cli: dict[tuple[str, int, str], str] = {}
        #: Per (read, entry id): the model the ledger says answered (default SERVED).
        self.served: dict[tuple[int, str], str] = {}
        self.deviations: list[dict[str, Any]] = []
        self.deviations_path = root / "deviations-0.4.0.json"
        #: The synthetic manifest's sha256 as last written (a file or the pre-registration that still holds it
        #: follows the manifest; one a test set to another value keeps it).
        self.manifest_sha256 = MANIFEST_PENDING
        section = analysis.default_prereg_analysis()
        section["pool_with"] = list(pool_with)
        self.prereg: dict[str, Any] = {
            "analysis": section,
            "registered": {"planned_day": D0, "valid_until": LAST},
            "frozen": {
                "fingerprints": dict(FINGERPRINTS),
                "cli_versions": [CLI],
                "served_models": [SERVED],
            },
            "data": {"manifest_sha256": None},
            "deviation_kinds": dict(analysis.DEVIATION_CONSEQUENCES),
            "deviations_file": str(self.deviations_path),
        }

    def doc(self, split: str = "holdout4", read: int = 1) -> dict[str, Any]:
        return self.docs[(split, read)]

    def entry(self, entry_id: str, split: str = "holdout4", read: int = 1) -> dict[str, Any]:
        return next(entry for entry in self.doc(split, read)["entries"] if entry["id"] == entry_id)

    def deviate(self, kind: str, applies_to: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
        """A deviation as recorded at the time: posted on the issue, timestamped, in a pushed checkpoint."""
        entry: dict[str, Any] = {
            "id": f"D{len(self.deviations) + 1:03d}",
            "kind": kind,
            "at": "2027-01-02T10:00:00Z",
            "step": "R4",
            "what": "ids and counts",
            "evidence": ["a path and its sha256"],
            "consequence": analysis.DEVIATION_CONSEQUENCES[kind],
            "issue_comment_url": "https://github.com/owner/repo/issues/7#issuecomment-1",
            "created_at": "2027-01-02T10:01:00Z",
            "checkpoint_sha": "a" * 40,
        }
        if applies_to is not None:
            entry["applies_to"] = applies_to
        entry.update(fields)
        self.deviations.append(entry)
        return entry

    def write(self) -> tuple[Path, list[Path]]:
        """Everything on disk; the pre-registration's path and the four results files (r1, r2, r3, newkinds)."""
        docs = {f"{split}-r{read}.json": doc for (split, read), doc in self.docs.items()} | self.extra
        seen: dict[str, dict[str, Any]] = {}
        for doc in docs.values():
            for entry in doc["entries"]:
                count = len(entry["conditions"]["ordnung"]["score"]["items"])
                items = []
                for index in range(count):
                    item: dict[str, Any] = {"expected_due": TRUE_DATE}
                    if (entry["id"], index) in self.alternatives:
                        item["convention_alternatives"] = self.alternatives[(entry["id"], index)]
                    items.append(item)
                seen.setdefault(entry["id"], {"id": entry["id"], "truth": {"items": items}})
        raw = json.dumps({"name": "synthetic", "version": 1, "entries": list(seen.values())}).encode()
        self.dataset.mkdir(parents=True, exist_ok=True)
        (self.dataset / "manifest.json").write_bytes(raw)
        digest, previous = hashlib.sha256(raw).hexdigest(), self.manifest_sha256
        self.manifest_sha256 = digest
        data = self.prereg.get("data")
        if isinstance(data, dict) and data.get("manifest_sha256") in (None, previous):
            data["manifest_sha256"] = digest
        index: dict[str, dict[str, dict[str, Any]]] = {}
        ledger = []
        for name, doc in docs.items():
            meta = doc["meta"]
            if meta["dataset"]["manifest_sha256"] in (MANIFEST_PENDING, previous):
                meta["dataset"]["manifest_sha256"] = digest
            split, read = meta["split"], meta["repeat"]
            for entry in doc["entries"]:
                cli = self.cli.get((split, read, entry["id"]), CLI)
                index.setdefault(split, {}).setdefault(f"r{read}", {})[entry["id"]] = {
                    "day": entry["today"],
                    "cli": cli,
                }
                for purpose in ("extract", "eval_baseline"):
                    ledger.append(
                        {
                            "at": f"{entry['today']}T08:00:00+00:00",
                            "purpose": purpose,
                            "key": "0" * 24,
                            "docs": [entry["id"]],
                            "repeat": read,
                            "outcome": "ok",
                            "cost_usd": 0.01,
                            "duration_ms": 1,
                            "wall_ms": 1,
                            "served_model": self.served.get((read, entry["id"]), SERVED),
                            "cli_version": cli,
                        }
                    )
            self.results.mkdir(parents=True, exist_ok=True)
            _write(self.results, name, doc)
        folder = self.recorded / "claude-sonnet-5"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "final-days.json").write_text(json.dumps(index), encoding="utf-8")
        (folder / "ledger.jsonl").write_text(
            "".join(json.dumps(line, sort_keys=True) + "\n" for line in ledger), encoding="utf-8"
        )
        self.deviations_path.write_text(json.dumps(self.deviations), encoding="utf-8")
        self.prereg_path.parent.mkdir(parents=True, exist_ok=True)
        self.prereg_path.write_text(json.dumps(self.prereg), encoding="utf-8")
        standard = [self.results / f"holdout4-r{read}.json" for read in (1, 2, 3)]
        return self.prereg_path, [*standard, self.results / "newkinds-r1.json"]

    def final(self, names: list[str] | None = None, **options: Any) -> dict[str, Any]:
        """The final analysis of these results files (by name; default the four of :meth:`write`)."""
        prereg, standard = self.write()
        paths = standard if names is None else [self.results / name for name in names]
        options.setdefault("results_dir", self.results)
        return analysis.final_from_files(
            prereg, paths, recorded_dir=self.recorded, dataset_dir=self.dataset, **options
        )

    def cli_args(self) -> list[str]:
        prereg, standard = self.write()
        return ["--prereg", str(prereg), *map(str, standard)]


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """The synthetic final run; the command line reads its recordings and dataset folders."""
    found = World(tmp_path)
    monkeypatch.setattr(analysis, "RECORDED_DIR", found.recorded)
    monkeypatch.setattr(analysis, "DATASET_DIR", found.dataset)
    return found


def test_the_final_run_families_by_hand(world: World) -> None:
    """Over three reads, Ordnung minus the model alone, per letter cluster (×3 to integers): accuracy 3, 3, −1, 1
    (sign-flip exact p 6/16), harm −3, 1, −1 (6/8). Unstable items: Ordnung's L3, the model alone's L4."""
    result = world.final()
    primary = result["primary"]
    assert (
        primary["split"],
        primary["reads"],
        primary["items"],
        primary["letters"],
        primary["clusters"],
    ) == (
        "holdout4",
        3,
        7,
        6,
        5,
    )
    f1 = primary["families"]["F1_accuracy"]["ordnung-vs-llm_only"]
    assert f1["diff"] == pytest.approx(2 / 7)
    assert (
        f1["signflip"]["p"] == 0.375
        and f1["signflip"]["method"] == "exact"
        and f1["signflip"]["nonzero"] == 4
    )
    assert f1["holm"] >= f1["signflip"]["p"]
    assert f1["bootstrap"]["lo"] <= f1["diff"] <= f1["bootstrap"]["hi"]
    f2 = primary["families"]["F2_harm"]["ordnung-vs-llm_only"]
    assert f2["diff"] == pytest.approx((1 / 3 - 4 / 3) / 7)
    assert f2["signflip"]["p"] == 0.75
    f3 = primary["families"]["F3_stability"]
    assert (f3["ordnung-vs-llm_only"]["b"], f3["ordnung-vs-llm_only"]["c"]) == (1, 1)
    assert f3["ordnung-vs-llm_only"]["midp"] == 1.0
    assert (f3["ordnung-vs-llm_rules_text"]["b"], f3["ordnung-vs-llm_rules_text"]["c"]) == (1, 0)
    assert f3["ordnung-vs-llm_rules_text"]["midp"] == 0.5
    sensitivity = primary["sensitivity_r1"]["accuracy"]["ordnung-vs-llm_only"]
    assert (sensitivity["b"], sensitivity["c"], sensitivity["exact_p"]) == (3, 0, 0.25)


def test_the_final_run_stability_and_secondary_numbers(world: World) -> None:
    primary = world.final()["primary"]
    ordnung, llm_only = primary["conditions"]["ordnung"], primary["conditions"]["llm_only"]
    assert [r["k"] for r in ordnung["exact_per_read"]] == [7, 6, 7]
    assert (ordnung["pass_all"]["k"], ordnung["pass_any"]["k"]) == (6, 7)
    assert (llm_only["pass_all"]["k"], llm_only["pass_any"]["k"]) == (4, 5)
    assert (ordnung["unstable"]["k"], llm_only["unstable"]["k"]) == (1, 1)
    assert primary["conditions"]["llm_rules_text"]["unstable"]["k"] == 0
    assert (ordnung["harmful_any_read"]["k"], llm_only["harmful_any_read"]["k"]) == (1, 2)
    assert ordnung["mean_accuracy"]["value"] == pytest.approx(20 / 21)
    # L3's date changed with the same reading in every read: not the engine (synthetic), but counted apart
    assert ordnung["reading_agreement"] == {
        "items": 7,
        "same_reading": 7,
        "absorbed": 0,
        "same_reading_other_date": 1,
    }
    assert primary["conditions"]["llm_rules_tool"]["tool_use_consistency"] == {
        "letters": 6,
        "date_tool_every_read": 6,
        "date_tool_some_reads": 0,
        "date_tool_no_read": 0,
    }
    decisions = primary["decisions"]
    assert decisions["beats_llm_only"] == "no_clear_difference"
    assert decisions["vs_llm_rules_text"] == "level_within_noise"
    assert decisions["vs_llm_rules_tool"] == "cannot_tell"
    assert decisions["more_stable_than_llm_only"] is False
    assert decisions["harmful"] == {"dates": 1, "reads": 21, "none": False}
    assert decisions["flags_caught"] == {"caught": 0, "wrong": 1, "caught_reads": 0, "wrong_reads": 1}
    # a rate of 1 over three reads gets an exact bound over its 5 clusters, never "100 % [100–100]"
    perfect = primary["conditions"]["llm_rules_text"]
    assert perfect["mean_accuracy"]["value"] == 1.0
    assert (
        perfect["mean_accuracy"]["ci"][0] == pytest.approx(0.025 ** (1 / 5))
        and perfect["mean_accuracy"]["ci"][1] == 1
    )
    assert perfect["mean_accuracy"]["method"] == "clopper-pearson over clusters"
    assert perfect["mean_harmful"]["ci"][1] > 0
    # selective prediction counts items, not item × read: read 1's items, and each wrong date once over the reads
    alone = llm_only["selective"]["please_check"]["recall_wrong"]
    assert (alone["k"], alone["n"]) == (0, 3)  # read 1: L1 early, L2's first date missed, L4 late
    assert llm_only["flags_over_reads"] == {
        "reads": 3,
        "wrong_dates": 3,
        "caught_dates": 0,
        "wrong_reads": 7,
        "caught_reads": 0,
        "caught": {"k": 0, "n": 3, "value": 0.0, "ci": [0.0, pytest.approx(0.7076, abs=5e-5)]},
    }
    assert ordnung["selective"]["please_check"]["recall_wrong"]["n"] == 0  # L3 is wrong in read 2 only
    assert ordnung["flags_over_reads"]["wrong_dates"] == 1
    result = world.final()
    newkinds = result["secondary"]["newkinds"]
    assert newkinds["conditions"]["ordnung"]["exact"]["k"] == 3
    assert newkinds["conditions"]["ordnung"]["kind_recognised"]["k"] == 1  # L1's kind is not recognised


#: Eight one-date letters, each its own cluster.
EIGHT = tuple((f"L{i}", f"L{i}", 1) for i in range(1, 9))


def _baselines_ahead(condition: str, read: int, letter: str, index: int) -> str:
    """Ordnung early on every letter in every read; every baseline right."""
    return "early" if condition == "ordnung" else "right"


def test_a_baseline_clearly_ahead_is_said_so_never_no_clear_difference(tmp_path: Path) -> None:
    """Ordnung wrong on all 8 clusters in every read, every baseline right: sign-flip p = 2/256 for each pair, Holm
    0.023, and the interval lies below 0. The pre-registered rules must code that as the baseline ahead (never "no
    clear difference" or "level within noise"), and the 3-read selective numbers count 8 wrong dates, not 24."""
    primary = World(tmp_path, letters=EIGHT, outcome=_baselines_ahead).final()["primary"]
    f1 = primary["families"]["F1_accuracy"]["ordnung-vs-llm_only"]
    assert f1["signflip"]["p"] == pytest.approx(2 / 256) and f1["holm"] == pytest.approx(3 * 2 / 256)
    assert f1["bootstrap"]["hi"] < 0 and f1["bootstrap"]["lo"] < f1["bootstrap"]["hi"]
    decisions = primary["decisions"]
    assert decisions["beats_llm_only"] == "baseline_ahead"
    assert decisions["vs_llm_rules_text"] == "baseline_ahead"
    assert decisions["vs_llm_rules_tool"] == "agent_higher"
    assert decisions["flags_caught"] == {"caught": 0, "wrong": 8, "caught_reads": 0, "wrong_reads": 24}
    ours = primary["conditions"]["ordnung"]
    assert ours["selective"]["please_check"]["recall_wrong"]["n"] == 8
    assert ours["selective"]["please_check"]["recall_wrong"]["ci"][1] == pytest.approx(0.3694, abs=5e-5)
    assert ours["selective"]["unflagged"]["accuracy"]["n"] == 8
    assert ours["mean_accuracy"]["ci"] == [0.0, pytest.approx(stats.clopper_pearson(0, 8)[1])]
    # every code the rules can give has its sentence for the presenter
    for code in ("clear", "baseline_ahead", "no_clear_difference", "level_within_noise"):
        assert code in analysis.DECISION_SENTENCES
    for code in ("non_inferior", "agent_higher", "baseline_higher", "cannot_tell", "fewer", "more"):
        assert code in analysis.DECISION_SENTENCES


def test_the_final_run_refuses_reads_that_do_not_fit(world: World) -> None:
    world.extra["twice.json"] = _synthetic_run("holdout4", 2)
    world.extra["other.json"] = _synthetic_run("holdout4", 3, model="another-model")
    world.extra["short.json"] = _synthetic_run("holdout4", 3, letters=LETTERS[:3])
    uneven = _synthetic_run("holdout4", 1)
    uneven["entries"][0]["conditions"]["llm_only"]["score"]["items"] = []
    world.extra["uneven.json"] = uneven
    reads = ["holdout4-r1.json", "holdout4-r2.json", "holdout4-r3.json"]
    nk = "newkinds-r1.json"
    with pytest.raises(analysis.AnalysisError, match="read 3"):
        world.final([reads[0], reads[1], nk])
    with pytest.raises(analysis.AnalysisError, match="twice"):
        world.final([*reads, "twice.json", nk])
    with pytest.raises(analysis.AnalysisError, match="model"):
        world.final([reads[0], reads[1], "other.json", nk])
    with pytest.raises(analysis.AnalysisError, match="same items"):
        world.final([reads[0], reads[1], "short.json", nk])
    with pytest.raises(
        analysis.AnalysisError, match="conditions of holdout4 read 1 do not hold the same items"
    ):
        world.final(["uneven.json", reads[1], reads[2], nk])
    world.prereg = {"analysis": {"model": "claude-sonnet-5"}}
    with pytest.raises(analysis.AnalysisError, match="pre-registration"):
        world.final()


def test_the_final_render_is_deterministic_and_checked(world: World, tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = [*world.cli_args(), "--out-dir", str(out)]
    assert analysis.main([*args, "--write"]) == 0
    written = sorted(out.glob("*-claude-sonnet-5-final.json"))
    assert [path.name for path in written] == ["2027-01-03-claude-sonnet-5-final.json"]
    assert analysis.main([*args, "--check"]) == 0
    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["meta"]["pre_registered"] is True and data["meta"]["kind"] == "final"
    assert analysis.render(data) == written[0].read_text(encoding="utf-8")
    data["primary"]["items"] = 8
    written[0].write_text(analysis.render(data), encoding="utf-8")
    assert analysis.main([*args, "--check"]) == 1
    # the publish day names the file when it is given, and the check renders it with the same date
    assert analysis.main([*args, "--write", "--date", "2027-02-01"]) == 0
    assert (out / "2027-02-01-claude-sonnet-5-final.json").is_file()
    assert analysis.main([*args, "--check", "--date", "2027-02-01"]) == 0


def test_the_published_final_analysis_reads_the_registered_pre_registration_only(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What lands in the repository's results reads ``evals/preregistration/final-0.4.0.json``: another
    pre-registration file (an edited copy, a second version) is refused before anything is read or written."""
    published = tmp_path / "repo-results"
    published.mkdir()
    monkeypatch.setattr(analysis, "RESULTS_DIR", published)
    for mode in ("--write", "--check"):
        assert analysis.main([*world.cli_args(), mode]) == 2
        assert "final-0.4.0.json" in capsys.readouterr().err
        assert analysis.main([*world.cli_args(), mode, "--out-dir", str(published)]) == 2
        capsys.readouterr()
    assert not list(published.iterdir())
    monkeypatch.setattr(analysis, "PREREG_FILE", world.write()[0])  # the registered file itself is read
    assert analysis.main([*world.cli_args(), "--write"]) == 0
    assert [path.name for path in published.iterdir()] == ["2027-01-03-claude-sonnet-5-final.json"]


# --------------------------------------------------------------------------------------------------
# The final run's inputs: their roles, and the pre-registration by its path in the repository
# --------------------------------------------------------------------------------------------------


def test_the_inputs_say_their_role_and_the_preregistration_its_path_in_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make eval-reproduce`` runs the check from the repository's root with what the file recorded: the
    pre-registration by its path there (not its bare name), and each input with its role, so that only the reads
    are given back on the command line and the earlier splits are read from ``pool_with`` again."""
    monkeypatch.setattr(analysis, "ROOT", tmp_path)
    world = World(
        tmp_path,
        pool_with=analysis.HELD_OUT_AS_RECORDED,
        prereg_name="evals/preregistration/final-0.4.0.json",
    )
    for name in analysis.HELD_OUT_AS_RECORDED:
        shutil.copy(RESULTS / name, tmp_path / name)
    result = world.final()
    meta = result["meta"]
    raw = (tmp_path / "evals/preregistration/final-0.4.0.json").read_bytes()
    assert meta["prereg"] == {
        "file": "evals/preregistration/final-0.4.0.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert [(item["file"], item["role"]) for item in meta["inputs"]] == [
        ("holdout4-r1.json", "primary"),
        ("holdout4-r2.json", "primary"),
        ("holdout4-r3.json", "primary"),
        ("newkinds-r1.json", "secondary"),
        *((name, "pooled") for name in analysis.HELD_OUT_AS_RECORDED),
    ]
    assert result["exploratory"]["pooled_held_out"]["splits"] == [
        "holdout",
        "holdout2",
        "holdout3",
        "holdout4",
    ]


def test_write_then_check_with_the_earlier_held_out_splits_pooled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final file pools the held-out splits as recorded (``pool_with``): written once, it is checked with only
    its reads given back (as ``evals/reproduce.py`` gives them), and a one-character edit fails the check."""
    world = World(tmp_path, pool_with=analysis.HELD_OUT_AS_RECORDED)
    monkeypatch.setattr(analysis, "RECORDED_DIR", world.recorded)
    monkeypatch.setattr(analysis, "DATASET_DIR", world.dataset)
    out = tmp_path / "out"
    args = [*world.cli_args(), "--results-dir", str(RESULTS), "--out-dir", str(out)]
    assert analysis.main([*args, "--write"]) == 0
    (written,) = sorted(out.glob("*-final.json"))
    meta = json.loads(written.read_text(encoding="utf-8"))["meta"]
    given = [str(tmp_path / item["file"]) for item in meta["inputs"] if item["role"] != "pooled"]
    check = ["--prereg", meta["prereg"]["file"], *given, "--date", meta["date"], "--check"]
    assert analysis.main([*check, "--results-dir", str(RESULTS), "--out-dir", str(out)]) == 0
    text = written.read_text(encoding="utf-8")
    index = text.index('"reads": 3')
    written.write_text(text[:index] + '"reads": 4' + text[index + 10 :], encoding="utf-8")
    assert analysis.main([*check, "--results-dir", str(RESULTS), "--out-dir", str(out)]) == 1


# --------------------------------------------------------------------------------------------------
# The frozen inputs: each mismatch is a deviation of a kind with a fixed consequence, recorded at the time
# --------------------------------------------------------------------------------------------------


def _fingerprint(world: World) -> None:
    world.doc("holdout4", 3)["meta"]["fingerprints"]["ordnung"] = "0" * 16


def _prediction_fingerprint(world: World) -> None:
    entry = world.entry("holdout4-L2", read=3)
    entry["conditions"]["llm_only"]["prediction"]["fingerprint"] = "0" * 16


def _served(world: World) -> None:
    world.served[(3, "holdout4-L2")] = "another-model"


def _manifest(world: World) -> None:
    world.doc("holdout4", 3)["meta"]["dataset"]["manifest_sha256"] = "f" * 64


def _dirty(world: World) -> None:
    world.doc("holdout4", 3)["meta"]["dirty"] = ["evals/run.py"]


#: (what breaks read 3, the deviation kind that names it, the mismatch the refusal names, the consequence)
READ_MISMATCHES = (
    (_fingerprint, "fingerprint", "fingerprint", "invalid"),
    (_fingerprint, "code_digest", "fingerprint", "invalid"),
    (_prediction_fingerprint, "prompt_hash", "fingerprint", "invalid"),
    (_served, "model", "model", "invalid"),
    (_manifest, "manifest_mismatch", "manifest_mismatch", "exclude_read"),
    (_dirty, "dirty_tree", "dirty_tree", "exclude_read"),
)


@pytest.mark.parametrize(("breaks", "kind", "mismatch", "effect"), READ_MISMATCHES)
def test_a_read_that_differs_from_the_frozen_inputs_needs_a_deviation_and_is_then_left_out(
    world: World, breaks: Callable[[World], None], kind: str, mismatch: str, effect: str
) -> None:
    """Never waivable (fingerprint, code digest, prompt hash, served model) and "exclude the read" (another
    manifest, a dirty tree): without a deviation recorded at the time the analysis is refused; with one, read 3 is
    left out (listed with its deviation and consequence) and the analysis runs on the reads that stand."""
    breaks(world)
    with pytest.raises(analysis.AnalysisError, match=rf"{mismatch}.*deviation"):
        world.final()
    world.deviate(kind, {"split": "holdout4", "repeat": 3})
    result = world.final()
    assert result["primary"]["reads"] == 2 and result["primary"]["reads_used"] == [1, 2]
    (left,) = result["meta"]["frozen_check"]["reads_left_out"]
    assert (left["split"], left["repeat"], left["file"], left["effect"]) == (
        "holdout4",
        3,
        "holdout4-r3.json",
        effect,
    )
    assert left["deviations"] == ["D001"] and left["mismatches"] == [mismatch]
    assert result["primary"]["families"]["F3_stability"] is not None  # k = 2 = min_reads: F3 still runs
    # the deviation must name the read: one for read 2 excuses nothing in read 3
    world.deviations[0]["applies_to"] = {"split": "holdout4", "repeat": 2}
    with pytest.raises(analysis.AnalysisError, match=mismatch):
        world.final()


def test_a_deviation_recorded_while_a_read_is_under_way_leaves_its_tree_clean(world: World) -> None:
    """A deviation is recorded at the time, into the deviations file, and committed with the next checkpoint: a read
    resumed before that checkpoint is still recorded from a clean tree. Any other changed path is a dirty tree."""
    meta = world.doc("holdout4", 3)["meta"]
    meta["dirty"] = ["evals/preregistration/deviations-0.4.0.json"]
    assert world.final()["primary"]["reads_used"] == [1, 2, 3]
    meta["dirty"] = ["evals/preregistration/deviations-0.4.0.json", "evals/run.py"]
    with pytest.raises(analysis.AnalysisError, match="dirty_tree"):
        world.final()


def test_a_read_recorded_again_after_a_runner_fix_is_analysed_with_the_fixed_code_s_fingerprints(
    world: World,
) -> None:
    """The runner-defect rule: the defect is fixed in its own change with a ``code_hash_changed`` deviation, and a
    read that does not replay identically is recorded again. That read carries the fixed code's fingerprints: the
    deviation that names it and holds exactly those fingerprints lets it in (listed); any other fingerprint is still
    a mismatch."""
    doc = world.doc("holdout4", 3)
    fixed = {condition: "f" * 16 for condition in doc["meta"]["fingerprints"]}
    doc["meta"]["fingerprints"] = dict(fixed)
    for entry in doc["entries"]:
        for condition, outcome in entry["conditions"].items():
            outcome["prediction"]["fingerprint"] = fixed[condition]
    world.deviate("code_hash_changed", {"split": "holdout4", "repeat": 3})
    with pytest.raises(analysis.AnalysisError, match="fingerprint"):
        world.final()
    world.deviations[0]["applies_to"]["fingerprints"] = {**fixed, "ordnung": "e" * 16}
    with pytest.raises(analysis.AnalysisError, match="fingerprint"):
        world.final()
    world.deviations[0]["applies_to"]["fingerprints"] = fixed
    result = world.final()
    assert result["primary"]["reads_used"] == [1, 2, 3]
    assert result["meta"]["frozen_check"]["reads_after_runner_fix"] == [
        {"split": "holdout4", "repeat": 3, "deviations": ["D001"]}
    ]
    # a never-waivable deviation naming the read still makes it invalid
    world.deviate("code_digest", {"split": "holdout4", "repeat": 3})
    assert world.final()["primary"]["reads_used"] == [1, 2]


def test_a_unit_recorded_outside_the_window_needs_a_deviation_and_is_then_excluded(world: World) -> None:
    """A unit (one letter in one read, all its conditions) told a day outside [D0, L]: refused without a deviation;
    with a ``day_outside_window`` deviation naming it, its letter leaves the paired analysis (listed)."""
    entry = world.entry("holdout4-L4", read=2)
    entry["today"] = "2027-01-09"  # L + 1
    with pytest.raises(analysis.AnalysisError, match=r"day_outside_window.*holdout4-L4"):
        world.final()
    world.deviate("day_outside_window", {"split": "holdout4", "repeat": 2, "entries": ["holdout4-L4"]})
    result = world.final()
    primary = result["primary"]
    assert (primary["reads"], primary["items"], primary["letters"]) == (3, 6, 5)
    assert result["meta"]["frozen_check"]["units_excluded"] == [
        {
            "split": "holdout4",
            "repeat": 2,
            "entry_id": "holdout4-L4",
            "day": "2027-01-09",
            "deviations": ["D001"],
        }
    ]
    # an excluded unit is not listed among the letters left without an answer as well
    entry["conditions"]["llm_only"]["score"]["error"] = "timed out after 300 s"
    world.deviate("unanswered", {"split": "holdout4", "repeat": 2, "entries": ["holdout4-L4"]})
    assert world.final()["primary"]["unanswered"] == []


def test_a_read_left_out_takes_its_units_with_it(world: World) -> None:
    """A read left out as invalid brings nothing into the analysis: neither the exclusion of one of its units (the
    letter stays in the reads that stand) nor its letters left without an answer."""
    world.doc("holdout4", 3)["meta"]["fingerprints"]["ordnung"] = "0" * 16
    world.entry("holdout4-L4", read=3)["today"] = "2027-01-09"
    world.entry("holdout4-L2", read=3)["conditions"]["ordnung"]["score"]["error"] = "timed out after 300 s"
    world.deviate("fingerprint", {"split": "holdout4", "repeat": 3})
    world.deviate("day_outside_window", {"split": "holdout4", "repeat": 3, "entries": ["holdout4-L4"]})
    world.deviate("unanswered", {"split": "holdout4", "repeat": 3, "entries": ["holdout4-L2"]})
    result = world.final()
    assert result["primary"]["reads_used"] == [1, 2] and result["primary"]["items"] == 7
    assert result["meta"]["frozen_check"]["units_excluded"] == [] and result["primary"]["unanswered"] == []


def test_a_units_day_is_the_day_index_s_and_the_letters_today(world: World) -> None:
    """The day index (``final-days.json``) and the results file must agree on a unit's day: two days for one unit
    are never analysed."""
    world.write()
    path = world.recorded / "claude-sonnet-5" / "final-days.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    index["holdout4"]["r2"]["holdout4-L1"]["day"] = "2027-01-04"
    reads = [world.results / f"holdout4-r{r}.json" for r in (1, 2, 3)]
    path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(analysis.AnalysisError, match="holdout4-L1"):
        analysis.final_from_files(
            world.prereg_path,
            [*reads, world.results / "newkinds-r1.json"],
            results_dir=world.results,
            recorded_dir=world.recorded,
            dataset_dir=world.dataset,
        )


def test_another_claude_version_is_included_with_a_deviation_and_f3_within_one_version(world: World) -> None:
    """A unit recorded by another ``claude`` version: refused without a ``cli_version`` deviation; with one, the read
    is included, each read's versions are listed, and F3 is also given over the items whose reads share a version."""
    for letter in ("L1", "L2", "L3"):
        world.cli[("holdout4", 3, f"holdout4-{letter}")] = "2.1.9"
    with pytest.raises(analysis.AnalysisError, match="cli_version"):
        world.final()
    world.deviate("cli_version", {"split": "holdout4", "repeat": 3})
    result = world.final()
    assert result["primary"]["reads"] == 3
    assert result["meta"]["frozen_check"]["cli_versions"] == {
        "holdout4/r1": [CLI],
        "holdout4/r2": [CLI],
        "holdout4/r3": [CLI, "2.1.9"],
        "newkinds/r1": [CLI],
    }
    same_cli = result["sensitivities"]["same_cli_f3"]
    assert same_cli["versions"] == [CLI, "2.1.9"] and same_cli["items"] == 3  # L4, L5, L6
    assert same_cli["F3_stability"]["ordnung-vs-llm_only"]["n"] == 3
    # one version everywhere: nothing to compare apart
    clean = World(world.root / "clean").final()
    assert clean["sensitivities"]["same_cli_f3"] == {"versions": [CLI], "same_as_primary": True}


def test_an_unanswered_letter_needs_a_deviation_and_model_failures_are_counted(world: World) -> None:
    """An infrastructure error left after three resumes (``score.error``) is refused unless an ``unanswered``
    deviation names it; then it is scored as the file has it (empty) and listed. A model failure is scored and
    counted, with no deviation."""
    world.entry("holdout4-L2", read=2)["conditions"]["ordnung"]["score"]["error"] = "timed out after 300 s"
    world.entry("holdout4-L1", read=1)["conditions"]["llm_only"]["score"]["failed"] = "no usable answer"
    with pytest.raises(analysis.AnalysisError, match=r"unanswered.*holdout4-L2"):
        world.final()
    world.deviate("unanswered", {"split": "holdout4", "repeat": 2, "entries": ["holdout4-L2"]})
    primary = world.final()["primary"]
    assert primary["unanswered"] == [
        {"read": 2, "entry_id": "holdout4-L2", "condition": "ordnung", "deviations": ["D001"]}
    ]
    assert primary["conditions"]["ordnung"]["unanswered_per_read"] == [0, 1, 0]
    assert primary["conditions"]["llm_only"]["model_failed_per_read"] == [1, 0, 0]
    assert primary["conditions"]["ordnung"]["model_failed_per_read"] == [0, 0, 0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issue_comment_url", None),
        ("created_at", None),
        ("checkpoint_sha", None),
        ("issue_comment_url", "file:///scratch/issue.md#D001"),
        ("checkpoint_sha", "abc"),
        ("created_at", "yesterday"),
        ("consequence", "include"),
        ("kind", "excuse"),
    ],
)
def test_a_deviation_not_recorded_at_the_time_or_off_the_table_is_refused(
    world: World, field: str, value: Any
) -> None:
    """A deviation counts only with its issue comment, its time and the checkpoint that pushed it, and only as the
    pre-registration's table says: any entry of the file that lacks them is refused, used or not."""
    world.deviate("infrastructure", {"split": "holdout4", "repeat": 2})
    world.final()  # well-formed: accepted (and an infrastructure loss changes nothing)
    if value is None:
        del world.deviations[0][field]
    else:
        world.deviations[0][field] = value
    with pytest.raises(analysis.AnalysisError, match="D001"):
        world.final()


def test_the_registered_table_of_deviation_kinds_is_the_one_the_analysis_applies(world: World) -> None:
    world.prereg["deviation_kinds"]["cli_version"] = "exclude the read"
    with pytest.raises(analysis.AnalysisError, match="cli_version"):
        world.final()
    del world.prereg["deviation_kinds"]["cli_version"]
    with pytest.raises(analysis.AnalysisError, match="cli_version"):
        world.final()


def test_a_missing_read_needs_a_deviation_and_the_analysis_runs_on_two_reads_or_one(world: World) -> None:
    """``min_reads`` = 2: with read 3 not recorded (a ``window_closed`` deviation), F1–F3 run on two reads; with
    only read 1, the cluster sign-flip and bootstrap on read 1 stay primary, McNemar beside them, and F3 is not
    run."""
    two = ["holdout4-r1.json", "holdout4-r2.json", "newkinds-r1.json"]
    del world.docs[("holdout4", 3)]  # read 3 was never recorded: no results file, no unit in the day index
    with pytest.raises(analysis.AnalysisError, match="read 3"):
        world.final(two)
    world.deviate("window_closed", {"split": "holdout4", "repeat": 3})
    primary = world.final(two)["primary"]
    assert (primary["reads"], primary["reads_used"]) == (2, [1, 2])
    assert primary["reads_missing"] == [{"read": 3, "kinds": ["window_closed"], "deviations": ["D001"]}]
    assert primary["families"]["F3_stability"]["ordnung-vs-llm_only"]["n"] == 7
    assert isinstance(primary["decisions"]["more_stable_than_llm_only"], bool)
    world.deviate("window_closed", {"split": "holdout4", "repeat": 2})
    del world.docs[("holdout4", 2)]
    (world.results / "holdout4-r2.json").unlink()  # written for the analysis on two reads
    one = world.final(["holdout4-r1.json", "newkinds-r1.json"])["primary"]
    assert (one["reads"], one["reads_used"]) == (1, [1])
    assert one["families"]["F3_stability"] is None and one["decisions"]["more_stable_than_llm_only"] is None
    assert one["not_run"] == {"F3_stability": "fewer reads than min_reads (2)"}
    f1 = one["families"]["F1_accuracy"]["ordnung-vs-llm_only"]
    beside = one["sensitivity_r1"]["accuracy"]["ordnung-vs-llm_only"]
    assert f1["signflip"]["p"] == beside["signflip"]["p"]  # the cluster test on read 1 is the primary
    assert (beside["b"], beside["c"], beside["exact_p"]) == (3, 0, 0.25)  # McNemar beside it
    assert one["decisions"]["beats_llm_only"] in ("clear", "baseline_ahead", "no_clear_difference")


def test_a_recorded_read_is_never_missing_by_omission(world: World) -> None:
    """A read whose results file exists, or whose units the day index holds complete, is analysed: a deviation that
    says it was not run (or any other) cannot leave it out by leaving its file off the command line."""
    world.deviate("budget_cut", {"split": "holdout4", "repeat": 3})
    two = ["holdout4-r1.json", "holdout4-r2.json", "newkinds-r1.json"]
    with pytest.raises(analysis.AnalysisError, match=r"holdout4 read 3.*recorded"):
        world.final(two)
    # its results file set aside, the day index still holds its units complete
    prereg, _ = world.write()
    aside = world.root / "aside"
    aside.mkdir()
    (world.results / "holdout4-r3.json").rename(aside / "holdout4-r3.json")
    files = {
        "results_dir": world.results,
        "recorded_dir": world.recorded,
        "dataset_dir": world.dataset,
    }
    with pytest.raises(analysis.AnalysisError, match=r"holdout4 read 3.*day index"):
        analysis.final_from_files(prereg, [world.results / name for name in two], **files)
    # its results file in pending/, one of its units not in the day index
    (world.results / "pending").mkdir()
    (aside / "holdout4-r3.json").rename(world.results / "pending" / "holdout4-r3.json")
    index_path = world.recorded / "claude-sonnet-5" / "final-days.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["holdout4"]["r3"].pop("holdout4-L1")
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(analysis.AnalysisError, match=r"holdout4 read 3.*pending"):
        analysis.final_from_files(prereg, [world.results / name for name in two], **files)


def test_read_1_cannot_be_missing(world: World) -> None:
    world.deviate("window_closed", {"split": "holdout4", "repeat": 1})
    with pytest.raises(analysis.AnalysisError, match="read 1"):
        world.final(["holdout4-r2.json", "holdout4-r3.json", "newkinds-r1.json"])


def test_a_retired_set_and_a_replayed_file_are_not_the_final_run(world: World) -> None:
    world.doc("holdout4", 2)["meta"]["backend"] = "replay"
    with pytest.raises(analysis.AnalysisError, match="live"):
        world.final()
    world.doc("holdout4", 2)["meta"]["backend"] = "live"
    world.deviate("retired_set", {"split": "holdout4"})
    with pytest.raises(analysis.AnalysisError, match="retired"):
        world.final()


# --------------------------------------------------------------------------------------------------
# Non-inferiority against the agent: the inverted cluster sign-flip
# --------------------------------------------------------------------------------------------------

#: A textbook case: per cluster, the difference of hits (ours minus theirs) and the item-reads.
TEXTBOOK = ((1, 1), (1, 1), (1, 2), (2, 2), (0, 1), (1, 3), (-1, 1), (1, 1), (0, 2), (2, 3))


def _grid_bounds(
    clusters: tuple[tuple[int, int], ...], *, step: Fraction, exact_max: int, draws: int, seed: int
) -> tuple[Fraction, Fraction]:
    """The smallest and largest δ on a grid that the registered test does not reject at 5 % (brute force: the
    sign-flip test of the centred cluster totals d − δ·n, run at every grid point)."""
    kept = []
    delta = Fraction(-1)
    while delta <= 1:
        centred = [Fraction(d) - delta * n for d, n in clusters]
        if exact_max >= len(clusters):
            p = stats.cluster_signflip(centred, exact_max=exact_max).p
        else:  # the same random sign patterns as the inversion: every cluster flipped by its bit
            rng = random.Random(seed)
            total = sum(centred)
            hits = 0
            for _ in range(draws):
                mask = rng.getrandbits(len(clusters))
                flipped = sum(x for bit, x in enumerate(centred) if mask >> bit & 1)
                hits += abs(total - 2 * flipped) >= abs(total)
            p = (hits + 1) / (draws + 1)
        if p >= 0.05:
            kept.append(delta)
        delta += step
    return min(kept), max(kept)


def _within_one_step(bound: dict[str, Any], lo: Fraction, hi: Fraction, step: Fraction) -> None:
    """The grid's kept points lie inside the bound, and its ends are within one step of the bound's (the bound is a
    float of an exact fraction: one rounding apart at most)."""
    tiny = 1e-12
    assert bound["lo"] - tiny <= lo < bound["lo"] + step + tiny
    assert bound["hi"] - step - tiny < hi <= bound["hi"] + tiny


def test_the_test_inversion_bound_matches_a_brute_force_grid() -> None:
    """Exact (every sign pattern) on ten clusters: the bound's ends are the grid's to within one step, and the
    grid never keeps a point outside them."""
    bound = analysis.signflip_interval(TEXTBOOK, level=0.95, exact_max=20, draws=1000, seed=7)
    assert bound["method"] == "exact" and bound["clusters"] == 10
    step = Fraction(1, 500)
    lo, hi = _grid_bounds(TEXTBOOK, step=step, exact_max=20, draws=1000, seed=7)
    _within_one_step(bound, lo, hi, step)
    assert bound["lo"] < bound["estimate"] < bound["hi"]
    assert bound["estimate"] == pytest.approx(sum(d for d, _ in TEXTBOOK) / sum(n for _, n in TEXTBOOK))


def test_the_monte_carlo_inversion_matches_a_grid_with_the_same_draws() -> None:
    bound = analysis.signflip_interval(TEXTBOOK, level=0.95, exact_max=0, draws=400, seed=11)
    assert bound["method"] == "monte-carlo" and (bound["draws"], bound["seed"]) == (400, 11)
    step = Fraction(1, 200)
    lo, hi = _grid_bounds(TEXTBOOK, step=step, exact_max=0, draws=400, seed=11)
    _within_one_step(bound, lo, hi, step)


def test_few_clusters_never_reject_and_one_sided_clusters_pin_the_bound() -> None:
    """Five clusters cannot reject at 5 % (2 of 32 patterns): every δ is kept, the bound is the whole [−1, 1].
    Eight clusters all at −1 per item-read: only δ = −1 is kept."""
    loose = analysis.signflip_interval([(1, 1)] * 5, level=0.95, exact_max=20, draws=10, seed=1)
    assert (loose["lo"], loose["hi"]) == (-1.0, 1.0)
    tight = analysis.signflip_interval([(-3, 3)] * 8, level=0.95, exact_max=20, draws=10, seed=1)
    assert (tight["lo"], tight["hi"]) == (-1.0, -1.0)


def test_the_agent_is_higher_only_when_the_whole_bound_is_below_zero() -> None:
    decide = analysis.noninferiority_decision
    assert (
        decide(-0.02, -0.001, 0.05, "llm_rules_tool") == "agent_higher"
    )  # also within the margin: higher wins
    assert decide(-0.02, 0.0, 0.05, "llm_rules_tool") == "non_inferior"  # an upper bound of 0 is not below 0
    assert decide(-0.06, 0.01, 0.05, "llm_rules_tool") == "cannot_tell"
    assert decide(-0.05, 0.01, 0.05, "llm_rules_tool") == "cannot_tell"  # the margin itself is not inside
    assert decide(-0.2, -0.1, 0.05, "llm_rules_text") == "baseline_higher"


def test_non_inferiority_uses_the_inverted_test_and_keeps_the_bootstrap_descriptive(world: World) -> None:
    primary = world.final()["primary"]
    block = primary["noninferiority"]["ordnung-vs-llm_rules_tool"]
    assert block["margin"] == 0.05 and block["decision"] == primary["decisions"]["vs_llm_rules_tool"]
    assert block["bound"]["method"] == "exact" and (block["bound"]["lo"], block["bound"]["hi"]) == (-1.0, 1.0)
    assert block["bootstrap"] == primary["families"]["F1_accuracy"]["ordnung-vs-llm_rules_tool"]["bootstrap"]
    # errors over item-reads: Ordnung's L3 in read 2; the agent's L5 in read 3
    assert block["errors"] == {"ours": 1, "theirs": 1, "ratio": 1.0}


# --------------------------------------------------------------------------------------------------
# One confirmatory endpoint, F2's codes and the rules the pre-registration names
# --------------------------------------------------------------------------------------------------


def _ordnung_late(condition: str, read: int, letter: str, index: int) -> str:
    return "late" if condition == "ordnung" else "right"


def _baselines_late(condition: str, read: int, letter: str, index: int) -> str:
    return "right" if condition == "ordnung" else "late"


def test_f2_has_its_codes_and_one_decision_is_confirmatory(tmp_path: Path) -> None:
    worse = World(tmp_path / "worse", letters=EIGHT, outcome=_ordnung_late).final()["primary"]
    better = World(tmp_path / "better", letters=EIGHT, outcome=_baselines_late).final()["primary"]
    for baseline in ("llm_only", "llm_rules_text"):
        assert worse["decisions"][f"f2_vs_{baseline}"] == "more"
        assert better["decisions"][f"f2_vs_{baseline}"] == "fewer"
    # harm against the agent is described, not tested: its row is there, no decision is taken on it
    assert (
        "f2_vs_llm_rules_tool" not in worse["decisions"] and "f2_vs_llm_rules_tool" not in better["decisions"]
    )
    assert worse["families"]["F2_harm"]["ordnung-vs-llm_rules_tool"]["diff"] > 0
    assert better["decisions"]["beats_llm_only"] == "clear"
    roles = better["decision_roles"]
    assert roles["beats_llm_only"] == "confirmatory"
    assert [key for key, role in roles.items() if role == "confirmatory"] == ["beats_llm_only"]
    assert (
        roles["vs_llm_rules_text"]
        == roles["f2_vs_llm_only"]
        == roles["more_stable_than_llm_only"]
        == "secondary"
    )
    assert roles["harmful"] == roles["flags_caught"] == "descriptive"
    assert better["confirmatory"] == {
        "decision": "beats_llm_only",
        "family": "F1_accuracy",
        "pair": "ordnung-vs-llm_only",
        "code": "clear",
    }
    neutral = World(tmp_path / "neutral").final()["primary"]["decisions"]
    assert neutral["f2_vs_llm_only"] == "no_clear_difference"


def test_the_rules_the_analysis_implements_are_named_in_the_preregistration(world: World) -> None:
    section = analysis.default_prereg_analysis()
    assert section["rules"] == analysis.RULES and section["min_reads"] == 2
    assert section["confirmatory"] == {"family": "F1_accuracy", "baseline": "llm_only"}
    assert set(section["sensitivities"]) == {
        "s_conv",
        "label_corrected",
        "first_attempt",
        "same_day_f3",
        "same_cli_f3",
    }
    assert set(section["exploratory"]) == {
        "by_family",
        "by_modality",
        "by_adversarial_class",
        "by_recording_day",
        "pooled_held_out",
    }
    for change, match in (
        ({"rules": {**analysis.RULES, "noninferiority": "bootstrap_lower_bound"}}, "noninferiority"),
        ({"min_reads": 0}, "min_reads"),
        ({"min_reads": 4}, "min_reads"),
        ({"confirmatory": {"family": "F2_harm", "baseline": "llm_only"}}, "confirmatory"),
        ({"sensitivities": ["s_conv", "post_hoc"]}, "post_hoc"),
        ({"exploratory": ["by_weekday"]}, "by_weekday"),
    ):
        broken = {"analysis": {**section, **change}}
        with pytest.raises(analysis.AnalysisError, match=match):
            analysis.parse_prereg(broken)
    stale = {key: value for key, value in section.items() if key != "rules"}
    with pytest.raises(analysis.AnalysisError, match="rules"):
        analysis.parse_prereg({"analysis": stale})


# --------------------------------------------------------------------------------------------------
# Sensitivities, beside the primary and never instead of it
# --------------------------------------------------------------------------------------------------


def test_s_conv_accepts_a_disputed_conventions_other_date(world: World) -> None:
    """L4's label rests on a disputed convention whose other reading gives the late date: the model alone's late
    date in read 1 counts as right under S-conv, and the primary does not move."""
    plain = world.final()
    world.alternatives[("holdout4-L4", 0)] = [LATE_DATE]
    result = world.final()
    assert result["primary"] == plain["primary"]
    s_conv = result["sensitivities"]["s_conv"]
    assert (s_conv["tagged_items"], s_conv["items_changed"]) == (1, 1)
    assert s_conv["conditions"]["llm_only"]["exact_per_read"] == [5, 5, 5]
    assert s_conv["F1_accuracy"]["ordnung-vs-llm_only"]["diff"] == pytest.approx(5 / 21)
    assert set(s_conv["decisions"]) >= {
        "beats_llm_only",
        "vs_llm_rules_text",
        "vs_llm_rules_tool",
        "f2_vs_llm_only",
    }
    assert plain["sensitivities"]["s_conv"] == {
        "tagged_items": 0,
        "items_changed": 0,
        "same_as_primary": True,
    }


def test_the_label_corrected_sensitivity_applies_label_errors_to_all_four_conditions(world: World) -> None:
    plain = world.final()
    world.deviate(
        "label_error",
        {"split": "holdout4", "items": [{"entry_id": "holdout4-L1", "item": 0, "date": EARLY_DATE}]},
    )
    result = world.final()
    assert result["primary"] == plain["primary"]
    corrected = result["sensitivities"]["label_corrected"]
    assert corrected["deviations"] == ["D001"] and corrected["items_changed"] == 12  # 4 conditions × 3 reads
    # under the corrected label the model alone's early date is right, and every other condition's date is late
    assert corrected["conditions"]["llm_only"]["exact_per_read"] == [5, 6, 6]
    assert corrected["conditions"]["ordnung"]["exact_per_read"] == [6, 5, 6]
    assert corrected["conditions"]["llm_rules_text"]["harmful_item_reads"] == 3


def test_the_first_attempt_sensitivity_scores_a_timed_out_first_attempt_as_missed(world: World) -> None:
    plain = world.final()
    world.deviate(
        "retake",
        {
            "split": "holdout4",
            "repeat": 1,
            "entries": ["holdout4-L2"],
            "first_attempt": [
                {"entry_id": "holdout4-L2", "condition": "ordnung", "outcome": "timeout"},
                {"entry_id": "holdout4-L2", "condition": "llm_only", "outcome": "ok"},
            ],
        },
    )
    result = world.final()
    assert result["primary"] == plain["primary"]
    first = result["sensitivities"]["first_attempt"]
    assert first["items_changed"] == 2 and first["deviations"] == ["D001"]
    assert first["conditions"]["ordnung"]["exact_per_read"] == [5, 6, 7]
    assert first["conditions"]["ordnung"]["harmful_item_reads"] == 3


def test_same_day_f3_uses_the_items_whose_reads_share_one_day(tmp_path: Path) -> None:
    every_read_apart = World(tmp_path / "apart").final()["sensitivities"]["same_day_f3"]
    assert every_read_apart["items"] == 0 and every_read_apart["F3_stability"] is None
    world = World(tmp_path / "some")
    for read in (1, 2, 3):
        for letter in ("L1", "L2", "L3"):
            world.entry(f"holdout4-{letter}", read=read)["today"] = D0
    same_day = world.final()["sensitivities"]["same_day_f3"]
    assert same_day["items"] == 4  # L1, L2's two dates, L3
    assert same_day["F3_stability"]["ordnung-vs-llm_only"]["n"] == 4
    assert same_day["F3_stability"]["ordnung-vs-llm_only"]["b"] == 1  # Ordnung's L3
    one_day = World(tmp_path / "one")
    for doc in one_day.docs.values():
        for entry in doc["entries"]:
            entry["today"] = D0
    assert one_day.final()["sensitivities"]["same_day_f3"] == {"items": 7, "same_as_primary": True}


# --------------------------------------------------------------------------------------------------
# Exploratory blocks: rates only, no p-value
# --------------------------------------------------------------------------------------------------


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_the_exploratory_blocks_hold_rates_and_no_p_value(world: World) -> None:
    for letter in ("L1", "L2", "L3"):
        for read in (1, 2, 3):
            world.entry(f"holdout4-{letter}", read=read)["family"] = "tax"
    world.entry("holdout4-L5", read=1)["conditions"]["ordnung"]["score"]["adversarial"] = {
        "injection_resisted": True
    }
    world.entry("holdout4-L5", read=1)["conditions"]["llm_only"]["score"]["adversarial"] = {
        "injection_resisted": False
    }
    exploratory = world.final()["exploratory"]
    assert set(exploratory) == {"by_family", "by_modality", "by_adversarial_class", "by_recording_day"}
    assert not _keys(exploratory) & {"p", "exact_p", "midp", "holm", "holm_exact", "holm_midp", "signflip"}
    by_family = exploratory["by_family"]
    assert by_family["groups"]["tax"]["item_reads"] == 12 and by_family["groups"]["f"]["item_reads"] == 9
    assert by_family["groups"]["tax"]["conditions"]["llm_only"]["exact"]["k"] == 6  # L2's second date, L3
    assert set(exploratory["by_modality"]["groups"]) == {"text", "photo"}
    days = exploratory["by_recording_day"]["groups"]
    assert sorted(days) == ["2027-01-01", "2027-01-02", "2027-01-03"]
    assert days["2027-01-02"]["conditions"]["ordnung"]["exact"]["k"] == 6
    resisted = exploratory["by_adversarial_class"]["groups"]["injection_resisted"]["conditions"]
    assert (resisted["ordnung"]["k"], resisted["ordnung"]["n"]) == (1, 1)
    assert (resisted["llm_only"]["k"], resisted["llm_only"]["n"]) == (0, 1)
    for block in exploratory.values():
        assert block["label"].startswith("exploratory")
