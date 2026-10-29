"""The benchmark's analysis (``evals/analysis.py``): the held-out splits re-analysed, and the pre-registered final run.

The re-analysis reads the three held-out results files as recorded and must reproduce what the evaluation plan
recomputed from them by independent scripts: 163/168 for Ordnung, 31 vs 4 and 14 vs 5 discordant pairs, the flags
catching none of Ordnung's 5 wrong dates, and the crossover with the rules-text prompt at r = 5.5. The intervals the
pages publish today stay reproducible beside the new ones. The final run's analysis is checked on synthetic reads
whose statistics are worked out by hand.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable
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
        "direction": outcome if outcome in ("late", "early") else None,
        "days_off": {"late": 2, "early": -2}.get(outcome),
        "predicted": predicted,
        "pred_index": None if outcome == "missed" else index,
        "flagged": False,
        "confidence": None if outcome == "missed" else "high",
        "cause": None,
    }


def _synthetic_run(
    split: str,
    read: int,
    *,
    model: str = "claude-sonnet-5",
    letters: tuple[tuple[str, str, int], ...] = LETTERS,
    outcome: Callable[[str, int, str, int], str] = _outcome,
) -> dict[str, Any]:
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
                    "failed": None,
                    "error": None,
                },
            }
        entries.append(
            {
                "id": f"{split}-{letter}",
                "family": "f",
                "modality": "photo" if letter == "L6" else "text",
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
        },
        "entries": entries,
    }


def _write(tmp_path: Path, name: str, data: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture()
def final_inputs(tmp_path: Path) -> tuple[Path, list[Path]]:
    prereg = {"analysis": analysis.default_prereg_analysis()}
    prereg["analysis"]["pool_with"] = []
    prereg_path = _write(tmp_path, "final.json", prereg)
    reads = [_write(tmp_path, f"holdout4-r{r}.json", _synthetic_run("holdout4", r)) for r in (1, 2, 3)]
    newkinds = _write(tmp_path, "newkinds.json", _synthetic_run("newkinds", 1, letters=LETTERS[:2]))
    return prereg_path, [*reads, newkinds]


def test_the_final_run_families_by_hand(final_inputs: tuple[Path, list[Path]]) -> None:
    """Over three reads, Ordnung minus the model alone, per letter cluster (×3 to integers): accuracy 3, 3, −1, 1
    (sign-flip exact p 6/16), harm −3, 1, −1 (6/8). Unstable items: Ordnung's L3, the model alone's L4."""
    prereg_path, paths = final_inputs
    result = analysis.final_from_files(prereg_path, paths)
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


def test_the_final_run_stability_and_secondary_numbers(final_inputs: tuple[Path, list[Path]]) -> None:
    prereg_path, paths = final_inputs
    primary = analysis.final_from_files(prereg_path, paths)["primary"]
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
    result = analysis.final_from_files(prereg_path, paths)
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
    prereg = {"analysis": {**analysis.default_prereg_analysis(), "pool_with": []}}
    prereg_path = _write(tmp_path, "final.json", prereg)
    reads = [
        _write(
            tmp_path,
            f"r{r}.json",
            _synthetic_run("holdout4", r, letters=EIGHT, outcome=_baselines_ahead),
        )
        for r in (1, 2, 3)
    ]
    nk = _write(tmp_path, "nk.json", _synthetic_run("newkinds", 1, letters=EIGHT[:2]))
    primary = analysis.final_from_files(prereg_path, [*reads, nk])["primary"]
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
    for code in ("non_inferior", "agent_higher", "baseline_higher", "cannot_tell"):
        assert code in analysis.DECISION_SENTENCES


def test_the_final_run_refuses_reads_that_do_not_fit(tmp_path: Path) -> None:
    prereg = {"analysis": {**analysis.default_prereg_analysis(), "pool_with": []}}
    prereg_path = _write(tmp_path, "final.json", prereg)
    reads = [_write(tmp_path, f"r{r}.json", _synthetic_run("holdout4", r)) for r in (1, 2, 3)]
    nk = _write(tmp_path, "nk.json", _synthetic_run("newkinds", 1))
    with pytest.raises(analysis.AnalysisError, match="read 3"):
        analysis.final_from_files(prereg_path, [reads[0], reads[1], nk])
    twice = _write(tmp_path, "twice.json", _synthetic_run("holdout4", 2))
    with pytest.raises(analysis.AnalysisError, match="twice"):
        analysis.final_from_files(prereg_path, [*reads, twice, nk])
    other = _write(tmp_path, "other.json", _synthetic_run("holdout4", 3, model="another-model"))
    with pytest.raises(analysis.AnalysisError, match="model"):
        analysis.final_from_files(prereg_path, [reads[0], reads[1], other, nk])
    short = _write(tmp_path, "short.json", _synthetic_run("holdout4", 3, letters=LETTERS[:3]))
    with pytest.raises(analysis.AnalysisError, match="same items"):
        analysis.final_from_files(prereg_path, [reads[0], reads[1], short, nk])
    uneven = _synthetic_run("holdout4", 1)
    uneven["entries"][0]["conditions"]["llm_only"]["score"]["items"] = []
    with pytest.raises(
        analysis.AnalysisError, match="conditions of holdout4 read 1 do not hold the same items"
    ):
        analysis.final_from_files(
            prereg_path, [_write(tmp_path, "uneven.json", uneven), reads[1], reads[2], nk]
        )
    incomplete = {"analysis": {"model": "claude-sonnet-5"}}
    with pytest.raises(analysis.AnalysisError, match="pre-registration"):
        analysis.final_from_files(_write(tmp_path, "bad.json", incomplete), [*reads, nk])


def test_the_final_render_is_deterministic_and_checked(
    final_inputs: tuple[Path, list[Path]], tmp_path: Path
) -> None:
    prereg_path, paths = final_inputs
    out = tmp_path / "out"
    args = ["--prereg", str(prereg_path), *map(str, paths), "--out-dir", str(out)]
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
