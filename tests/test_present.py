"""The evaluation's presenter (``python -m evals.present``): one source for everything a reader sees.

The README's evaluation block, ``docs/evals.md``, ``docs/evals-history.md``, the charts and the report page are
rendered from the results files alone, through ``evals/present/presentation.json``; ``--check`` fails when any
committed output differs from a fresh render. These tests pin the numbers it shows today (the three held-out
splits as recorded, re-analysed by ``evals.analysis``), the rules that choose its sentences for good and bad
results alike, the charts' accessibility and the palette, and that no letter's text reaches any output.
"""

from __future__ import annotations

import copy
import csv
import html
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from evals.present import (
    BEGIN,
    END,
    PAGES_URL,
    PRESENTATION_PATH,
    PresentError,
    build,
    charts,
    model,
    palette,
    site,
    text,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "results"
REANALYSIS = "2026-10-29-claude-sonnet-5-heldout-reanalysis.json"
HELD_OUT = {
    "2026-09-30-claude-sonnet-5-holdout.json": "holdout",
    "2026-10-01-claude-sonnet-5-holdout2.json": "holdout2",
    "2026-10-06-claude-sonnet-5-holdout3.json": "holdout3",
}
#: what a path of the building computer starts with (as tests/test_media_budget.py)
PATH_MARKS = ("/home/", "/Users/", "/root/", "/tmp/", "\\Users\\")


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return model.build(RESULTS)


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    return build.outputs(ROOT, RESULTS)


def _flat(value: str) -> str:
    return " ".join(value.split())


# --------------------------------------------------------------------------------------------------
# Roles: which results file may feed which view
# --------------------------------------------------------------------------------------------------


def test_every_results_file_has_exactly_one_role() -> None:
    roles = model.roles(RESULTS)
    files = {path.name for path in RESULTS.glob("*.json") if path.name not in model.NOT_RESULTS}
    assert set(roles) == files
    assert set(roles.values()) <= set(model.ROLES)
    for name, split in HELD_OUT.items():
        assert roles[name] == "held-out", name
    assert roles[REANALYSIS] == "re-analysis"
    assert roles["2026-09-30-claude-sonnet-5-holdout-rescored.json"] == "re-scored"
    assert roles["2026-10-06-claude-sonnet-5-holdout2-rescored.json"] == "re-scored"
    assert roles["2026-10-08-claude-sonnet-5-without-land.json"] == "replay"
    assert roles["2026-09-30-claude-sonnet-5-test.json"] == "iterated"
    assert (
        roles["2026-09-25-sonnet-test.json"] == "iterated"
    )  # the test split's first run: iterated on after it
    assert roles["2026-10-01-claude-sonnet-5-ask.json"] == "iterated"  # Ask's development set
    # the earlier model's runs are archive: listed by date, never charted
    assert roles["2026-09-29-sonnet-test.json"] == "archive"
    assert roles["2026-09-29-sonnet-ask.json"] == "archive"
    # each held-out split has one recording
    held = [name for name, role in roles.items() if role == "held-out"]
    assert sorted(held) == sorted(HELD_OUT)


def test_a_results_file_of_an_unknown_kind_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / "2026-11-01-claude-sonnet-5-mystery.json").write_text('{"what": 1}', encoding="utf-8")
    with pytest.raises(PresentError, match="mystery"):
        model.roles(tmp_path)


def test_a_second_live_recording_of_a_held_out_split_is_refused(tmp_path: Path) -> None:
    for name in HELD_OUT:
        (tmp_path / name).write_bytes((RESULTS / name).read_bytes())
    again = json.loads((RESULTS / "2026-10-06-claude-sonnet-5-holdout3.json").read_text(encoding="utf-8"))
    again["meta"]["date"] = "2026-10-20"
    (tmp_path / "2026-10-20-claude-sonnet-5-holdout3.json").write_text(json.dumps(again), encoding="utf-8")
    with pytest.raises(PresentError, match="holdout3"):
        model.roles(tmp_path)


# --------------------------------------------------------------------------------------------------
# The numbers it shows today
# --------------------------------------------------------------------------------------------------


def test_the_headline_is_the_held_out_splits_as_recorded(doc: dict[str, Any]) -> None:
    headline = doc["headline"]
    assert headline["kind"] == "pooled-held-out" and headline["pre_registered"] is False
    assert headline["source"]["file"] == REANALYSIS and headline["source"]["role"] == "re-analysis"
    assert {row["file"]: row["split"] for row in headline["inputs"]} == HELD_OUT
    assert all(row["role"] == "held-out" and row["backend"] == "live" for row in headline["inputs"])
    assert (headline["items"], headline["letters"], headline["photos"], headline["adversarial"]) == (
        168,
        189,
        33,
        36,
    )
    assert headline["clusters"] == 129
    conditions = headline["conditions"]
    exact = {c: (conditions[c]["exact"]["k"], conditions[c]["exact"]["n"]) for c in palette.CONDITIONS}
    assert exact == {
        "ordnung": (163, 168),
        "llm_only": (136, 168),
        "llm_rules_text": (154, 168),
        "llm_rules_tool": (167, 168),
    }
    harmful = {c: conditions[c]["harmful"]["k"] for c in palette.CONDITIONS}
    assert harmful == {"ordnung": 3, "llm_only": 13, "llm_rules_text": 1, "llm_rules_tool": 1}
    low, high = conditions["ordnung"]["exact"]["ci"]
    assert (round(low * 100, 1), round(high * 100, 1)) == (93.2, 99.0)  # Clopper-Pearson
    accuracy = headline["paired"]["accuracy"]
    assert (accuracy["ordnung-vs-llm_only"]["b"], accuracy["ordnung-vs-llm_only"]["c"]) == (31, 4)
    assert (accuracy["ordnung-vs-llm_rules_text"]["b"], accuracy["ordnung-vs-llm_rules_text"]["c"]) == (14, 5)
    assert (accuracy["ordnung-vs-llm_rules_tool"]["b"], accuracy["ordnung-vs-llm_rules_tool"]["c"]) == (1, 5)
    assert headline["flags"] == {"caught": 0, "wrong": 5}


def test_the_row_order_is_the_headline_metric_s_set_once(doc: dict[str, Any]) -> None:
    assert doc["order"] == ["llm_rules_tool", "ordnung", "llm_rules_text", "llm_only"]


def test_an_input_whose_bytes_changed_is_refused(tmp_path: Path) -> None:
    for path in RESULTS.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    name = "2026-10-01-claude-sonnet-5-holdout2.json"
    (tmp_path / name).write_bytes((RESULTS / name).read_bytes() + b"\n")
    with pytest.raises(PresentError, match="holdout2"):
        model.build(tmp_path)


def test_a_final_run_is_never_shown_under_the_pooled_headline(tmp_path: Path) -> None:
    """Once a pre-registered final run exists, it takes the headline by rule (phase 2): the phase-1 presenter
    refuses to render the pooled headline beside it rather than publish it as 0.4.0's."""
    for path in RESULTS.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    final = {"schema": "ordnung-eval-analysis/1", "meta": {"kind": "final", "model": "claude-sonnet-5"}}
    (tmp_path / "2026-12-01-claude-sonnet-5-final.json").write_text(json.dumps(final), encoding="utf-8")
    assert model.roles(tmp_path)["2026-12-01-claude-sonnet-5-final.json"] == "final"
    with pytest.raises(PresentError, match="final"):
        model.build(tmp_path)


def test_the_test_split_s_first_run_facts_come_from_its_results_file(doc: dict[str, Any]) -> None:
    """The report's task section: asked to compute deadlines itself on the test split's first run, the model got
    10 of 56 wrong, 8 with the 3-day delivery rule of before 2025, and every late one moved a deemed delivery day
    off a weekend or holiday (counted from the stored explanations)."""
    fact = doc["llm_only_first_run"]
    assert fact["file"] == "2026-09-25-sonnet-test.json"
    assert (fact["wrong"], fact["n"], fact["three_day"], fact["late"], fact["late_shifted"]) == (
        10,
        56,
        8,
        4,
        4,
    )


# --------------------------------------------------------------------------------------------------
# The README block and its sentences
# --------------------------------------------------------------------------------------------------


def test_the_readme_block_states_the_headline(doc: dict[str, Any]) -> None:
    block = _flat(text.readme_block(doc))
    assert (
        "**Held out, read once.** On 168 deadlines in 189 synthetic letters that nothing was tuned on"
        in block
    )
    assert (
        "Ordnung dates **97.0 %** exactly right (95 % CI 93.2–99.0), with **3 of 168** late or missed."
        in block
    )
    # the accuracy test sits with the accuracy it tests, not with the harm count after it
    assert "gets **81.0 %** (31 vs 4 discordant, exact p < 0.001), with **13** late or missed." in block
    # Ordnung minus the agent is −2.4 points, cluster-bootstrap interval −5.4 to 0.0: the lower bound is not above
    # −5 points, so the rule says "we cannot tell", never "level"
    assert (
        "An agent given Ordnung's engine as a tool scores 99.4 % (1 vs 5 discordant): we cannot tell whether "
        "Ordnung is within 5 points of it (−2.4 points, 95 % CI −5.4 to +0.0)." in block
    )
    assert "is level" not in block
    assert "“Please check” caught 0 of Ordnung's 5 wrong dates" in block
    assert "**Ask:** 0 of 21 injected claims reach you (8 of 21 without the answer check;" in block
    assert "development set, not held out" in block
    assert f"]({PAGES_URL})" in block and "](docs/evals.md)" in block
    assert 'srcset="docs/assets/eval-held-out-dark.svg"' in block
    assert 'src="docs/assets/eval-held-out-light.svg"' in block


def test_the_readme_block_is_short(doc: dict[str, Any]) -> None:
    lines = text.readme_block(doc).strip("\n").splitlines()
    assert lines[0] == BEGIN and lines[-1] == END
    assert len(lines) - 2 <= 12


def _variant(doc: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """``doc`` with its headline changed: ``harmful_ordnung``, ``verdict_<pair>``, ``diff_<pair>``."""
    new = copy.deepcopy(doc)
    headline = new["headline"]
    for key, value in changes.items():
        if key == "harmful_ordnung":
            headline["conditions"]["ordnung"]["harmful"]["k"] = value
        elif key.startswith("verdict_"):
            headline["paired"]["accuracy"][f"ordnung-vs-{key.removeprefix('verdict_')}"]["verdict"] = value
        elif key.startswith("diff_"):
            headline["paired"]["accuracy"][f"ordnung-vs-{key.removeprefix('diff_')}"]["diff"] = value
        elif key.startswith("bootstrap_"):
            headline["paired"]["accuracy"][f"ordnung-vs-{key.removeprefix('bootstrap_')}"]["bootstrap"] = (
                value
            )
        elif key == "caught":
            headline["flags"]["caught"] = value
        elif key == "set_aside":  # the end-to-end run's genuine obligations set aside (when it exists)
            if new.get("e2e"):
                new["e2e"]["set_aside"] = value
        elif key == "scam_in_calendar":  # … and its scam letters that put demands in the calendar
            if new.get("e2e"):
                new["e2e"]["scam"]["in_the_calendar"] = value
        else:
            raise KeyError(key)
    return new


def test_the_sentence_says_good_and_bad_results_the_same_way(doc: dict[str, Any]) -> None:
    """The headline sentence is chosen by rule: the same place and the same size for a good result and a bad one."""
    good = _flat(text.headline(doc))
    assert "**3 of 168** late or missed" in good
    none_harmful = _flat(text.headline(_variant(doc, harmful_ordnung=0)))
    assert "with **none of 168** late or missed" in none_harmful
    unclear = _flat(text.headline(_variant(doc, verdict_llm_only="none")))
    assert "**no clear difference**" in unclear and "31 vs 4 discordant" in unclear
    behind = _flat(text.headline(_variant(doc, verdict_llm_only="clear", diff_llm_only=-0.1)))
    assert "**the model alone is ahead**" in behind
    agent_ahead = _flat(text.headline(_variant(doc, verdict_llm_rules_tool="clear")))
    assert "scores higher (99.4 %" in agent_ahead and "not accuracy" in agent_ahead
    agent_behind = _flat(
        text.headline(_variant(doc, verdict_llm_rules_tool="clear", diff_llm_rules_tool=0.05))
    )
    assert "scores lower (99.4 %" in agent_behind
    agent_unsettled = _flat(text.headline(_variant(doc, verdict_llm_rules_tool="suggestive")))
    assert "scores higher, not settled (99.4 %" in agent_unsettled
    # "level" only when the interval's lower bound is above −5 points (the pre-registered margin)
    level = _flat(text.headline(_variant(doc, bootstrap_llm_rules_tool=[-0.04, 0.01])))
    assert "is level within 5 points (99.4 %, 1 vs 5 discordant; −2.4 points, 95 % CI −4.0 to +1.0)" in level
    assert "we cannot tell" not in level
    cannot = _flat(text.headline(doc))
    assert "we cannot tell whether Ordnung is within 5 points of it" in cannot and "is level" not in cannot
    caught = _flat(text.readme_block(_variant(doc, caught=5, set_aside=0, scam_in_calendar=[])))
    assert "**Where it falls short:**" not in caught and "caught 5 of Ordnung's 5 wrong dates" in caught
    if doc.get("e2e"):  # every wrong date caught, but real obligations still set aside: still short
        set_aside = _flat(text.readme_block(_variant(doc, caught=5, scam_in_calendar=[])))
        assert "**Where it falls short:**" in set_aside and "set aside as a scam" in set_aside
        scam = _flat(
            text.readme_block(_variant(doc, caught=5, set_aside=0))
        )  # a scam's demand in the calendar
        assert "**Where it falls short:**" in scam and "scam letters still put their demands" in scam


# --------------------------------------------------------------------------------------------------
# docs/evals.md: the report
# --------------------------------------------------------------------------------------------------

REPORT_SECTIONS = [
    "Evaluation card",
    "1. Summary",
    "2. The task, and why it is hard",
    "3. Data and labels",
    "4. Conditions and baselines",
    "5. Metrics",
    "6. Results",
    "7. Statistics",
    "8. Ablations",
    "9. Robustness",
    "10. Safety and selective prediction",
    "11. Failure analysis",
    "12. Cost and latency",
    "13. From a letter to a reminder",
    "14. Limitations",
    "15. Reproduce",
]


def test_the_report_has_its_sections_in_the_order_an_expert_reads(doc: dict[str, Any]) -> None:
    page = text.report(doc)
    assert re.findall(r"^## (.+)$", page, re.M) == REPORT_SECTIONS
    assert page.startswith("# Evaluation: reading German letters for deadlines\n")
    assert "Do not edit by hand" in page


def test_the_report_corrects_the_rules_text_claim(doc: dict[str, Any]) -> None:
    page = _flat(text.report(doc))
    assert (
        "14 vs 5 discordant, exact p 0.064, Holm-adjusted 0.127 (mid-p 0.041, Holm-adjusted 0.083): suggestive, "
        "not settled" in page
    )
    assert "+5.4 points, 95 % interval +0.6 to +10.6" in page  # what was published, shown as superseded
    assert "not pre-registered" in page
    # the card names the tests a verdict rests on
    assert "exact McNemar with Holm for paired comparisons" not in page
    assert (
        "for paired comparisons, exact McNemar and a sign-flip test over letter clusters, each with Holm"
        in page
    )


def test_every_headline_number_0_3_0_published_is_shown_beside_its_replacement(doc: dict[str, Any]) -> None:
    """The 0.3.0 README published an interval, a safety count and three differences for the same three held-out
    splits; each one the new methods replace is listed old beside new, from the re-analysis's own fields."""
    page = text.report(doc)
    table = page.split("**What changed since 0.3.0.**", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| ")]
    assert rows[0] == "| Number | As 0.3.0 published it | Now |"
    flat = "\n".join(rows)
    assert (
        "| Ordnung, exact date right | 97.0 % [94.3–99.4] (percentile bootstrap over letters) | "
        "97.0 % [93.2–99.0] (Clopper–Pearson) |" in flat
    )
    assert (
        "| Ordnung, the safety count | 2 of 168 dangerously late (a missed deadline left out) | "
        "3 of 168 late or missed |" in flat
    )
    assert "| Ordnung minus LLM only | +16.1 points [+9.8 to +23.1] | +16.1 points [+9.3 to +22.5]" in flat
    assert (
        "| Ordnung minus LLM + rules text | +5.4 points [+0.6 to +10.6] | +5.4 points [+0.1 to +10.5]" in flat
    )
    assert (
        "| Ordnung minus LLM + rules tool | −2.4 points [−5.3 to +0.0] | −2.4 points [−5.6 to +0.9]" in flat
    )


def test_a_harm_comparison_says_who_has_fewer_harmful_dates(doc: dict[str, Any]) -> None:
    """Fewer harmful dates is better: a harm row's verdict names the side with fewer, never "ahead"."""
    page = text.report(doc)
    harm = [
        line
        for line in page.splitlines()
        if line.startswith(("| Late or missed | LLM only", "| Late | LLM only"))
    ]
    assert len(harm) == 2
    # late alone (2 vs 13) clears the exact and the clustered test after Holm; late or missed (3 vs 13: exact Holm
    # 0.064, cluster sign-flip Holm 0.089) clears only the item-level mid-p, so it is not called clear
    late_or_missed, late = harm
    assert late_or_missed.endswith("| fewer with Ordnung, suggestive, not settled |"), late_or_missed
    assert late.endswith("| fewer with Ordnung, clearly |"), late
    accuracy = [line for line in page.splitlines() if line.startswith("| Exact date right | LLM only")]
    assert accuracy and accuracy[0].endswith("| Ordnung ahead, clearly |")


def test_the_report_s_lists_and_failure_causes_read_right(doc: dict[str, Any]) -> None:
    page = text.report(doc)
    assert "\n-  " not in page and "\n- Against the model alone:" in page
    failures = page.split("## 11. Failure analysis", 1)[1].split("\n## ", 1)[0]
    baseline_rows = [line for line in failures.splitlines() if "| LLM only |" in line]
    assert baseline_rows and all(
        line.endswith("| n/a |") for line in baseline_rows
    )  # the cause is Ordnung's only
    missed = [line for line in failures.splitlines() if "injection_visible-1" in line]
    assert missed and missed[0].endswith("| not found |")
    assert "the code of that day): every extra miss is 1–3 days early; none is late." in _flat(page)


def test_the_report_states_the_test_split_s_first_run_facts(doc: dict[str, Any]) -> None:
    page = _flat(text.report(doc))
    assert "the model got 10 of 56 wrong" in page
    assert "8 of those used the 3-day delivery rule" in page
    assert "all 4 late answers moved a deemed delivery day off a weekend or holiday" in page


def test_the_report_lists_every_harmful_error_by_id_only(doc: dict[str, Any]) -> None:
    page = text.report(doc)
    failures = page.split("## 11. Failure analysis", 1)[1].split("\n## ", 1)[0]
    for entry in ("holdout-adversarial-conflicting_dates-1", "holdout2-adversarial-injection_visible-1"):
        assert entry in failures
    harmful = [
        row for row in doc["headline"]["errors"] if row["outcome"] == "missed" or row["direction"] == "late"
    ]
    assert len(harmful) == 3 + 13 + 1 + 1
    for row in harmful:
        assert row["entry_id"] in failures


def test_sections_without_results_yet_say_so(doc: dict[str, Any]) -> None:
    """The final run, the stress cells and (until their files exist) the check ablation and the end-to-end run are
    named as not yet run, never left out silently."""
    bare = copy.deepcopy(doc)
    bare["e2e"] = None
    bare["ablation"] = None
    page = _flat(text.report(bare))
    assert "The final run on the version that ships has not been recorded yet" in page
    assert "Not yet run: the targeted injections and distractor dates" in page
    # nothing is pre-registered yet: the pages say what will be, never that it is
    for claim in (
        "The final run is.",
        "pre-registered stress cells",
        "pre-registered: not yet",
        "The pre-registered final",
    ):
        assert claim not in page, claim
    assert "will be pre-registered before it is recorded" in page
    assert "No results file of the check ablation yet" in page
    assert "No results file of the end-to-end run yet" in page


def test_the_ablation_and_end_to_end_sections_fill_from_their_results_files(doc: dict[str, Any]) -> None:
    with_both = copy.deepcopy(doc)
    with_both["ablation"] = {
        "file": "2026-10-29-claude-sonnet-5-checks-ablated.json",
        "splits": ["holdout", "holdout2", "holdout3"],
        "rows": [
            {
                "name": "all_on",
                "label": "As it ships",
                "scored": 168,
                "right": 166,
                "late": 0,
                "missed": 0,
                "early": 2,
            },
            {
                "name": "all_off",
                "label": "All code checks off",
                "scored": 168,
                "right": 161,
                "late": 4,
                "missed": 1,
                "early": 2,
            },
        ],
    }
    with_both["e2e"] = {
        "file": "2026-10-29-claude-sonnet-5-e2e.json",
        "splits": ["test", "holdout", "holdout2", "holdout3"],
        "letters": 252,
        "obligations": 224,
        "parity": {"k": 224, "n": 224},
        "reminded_in_time": {"k": 209, "n": 224, "value": 209 / 224, "ci": [0.896, 0.964]},
        "late_reminders": 0,
        "not_reminded": {"set_aside:scam_signs": 15},
        "set_aside": 15,
        "scam": {
            "letters": 12,
            "kept_off_the_calendar": {"k": 10, "n": 12, "value": 10 / 12, "ci": [0.516, 0.979]},
            "in_the_calendar": [{"entry_id": "x-scam-1", "events": 1}, {"entry_id": "x-scam-2", "events": 2}],
            "without_scam_idea": ["x-scam-1", "x-scam-2"],
            "genuine_letters": 240,
            "false_scam_idea": {"k": 13, "n": 240, "value": 13 / 240, "ci": [0.029, 0.091]},
        },
    }
    page = _flat(text.report(with_both))
    assert "| All code checks off | 161/168 | 4 | 1 | 2 |" in page
    assert "209 of 224" in page and "set aside as a scam: 15" in page
    assert (
        "2 of 12 scam letters still put their demands in the calendar: `x-scam-1` (1 event) and `x-scam-2` "
        "(2 events)" in page
    )
    assert "2 of the 12 got no scam warning (`x-scam-1` and `x-scam-2`)" in page
    assert "13 of 240 genuine letters got a scam warning by mistake" in page
    block = _flat(text.readme_block(with_both))
    assert "15 of 224 real obligations got no reminder because their letter was set aside as a scam" in block
    assert "2 of 12 scam letters still put their demands in the calendar" in block
    # every scam letter kept off the calendar: nothing to say in the README's short line
    kept = copy.deepcopy(with_both)
    kept["e2e"]["scam"]["in_the_calendar"] = []
    assert "in the calendar" not in _flat(text.readme_block(kept))


def test_a_missed_deadline_is_counted_with_the_deadlines_without_a_flag_and_said_so(
    doc: dict[str, Any],
) -> None:
    """A missed deadline shows no date and no flag: the selective numbers count it with the unflagged ones
    (Ordnung's 123 of 128), so the labels say so rather than "dates shown"."""
    page = text.report(doc)
    assert "Unflagged dates right" not in page and "Harmful among unflagged" not in page
    assert (
        "| Without a flag: right (a missed deadline counts here) | Without a flag: late or missed |" in page
    )
    assert "| 123/128 (96.1 %) | 3/128 |" in page
    for theme in ("light", "dark"):
        svg = charts.svg("risk-coverage", doc, theme)
        assert "among those shown" not in svg and "a missed deadline has no flag" in svg


def test_the_end_to_end_scam_result_is_published_from_its_results_file(doc: dict[str, Any]) -> None:
    """The end-to-end run's scam letters, as the results file holds them: 2 of 12 put payment demands in the
    calendar with no scam warning; the report and the README say so by id."""
    scam = doc["e2e"]["scam"]
    assert scam["letters"] == 12
    assert (scam["kept_off_the_calendar"]["k"], scam["kept_off_the_calendar"]["n"]) == (10, 12)
    assert scam["in_the_calendar"] == [
        {"entry_id": "holdout3-adversarial-scam-1", "events": 1},
        {"entry_id": "holdout3-adversarial-scam-2", "events": 2},
    ]
    assert (scam["false_scam_idea"]["k"], scam["false_scam_idea"]["n"]) == (13, 240)
    page = _flat(text.report(doc))
    assert "2 of 12 scam letters still put their demands in the calendar" in page
    assert "`holdout3-adversarial-scam-1` (1 event) and `holdout3-adversarial-scam-2` (2 events)" in page
    assert "2 of 12 scam letters still put their demands in the calendar" in _flat(text.readme_block(doc))


def test_the_history_page_keeps_the_runs_as_they_were_published(rendered: dict[str, str]) -> None:
    history = rendered["docs/evals-history.md"]
    assert history.startswith("# Evaluation history: every run, in the order it happened\n")
    assert "## Every results file" in history
    for heading in ("## Headline", "## Held-out run: the holdout3 split", "## Without the sender's Land"):
        assert f"\n{heading}\n" in history
    # every results file has a row with its role; the earlier model's runs by date only
    table = history.split("## Every results file", 1)[1].split("\n## ", 1)[0]
    for name, role in model.roles(RESULTS).items():
        assert f"`{name}`" in table and f"| {role} |" in table
    # the only model id it names is the pinned one (the earlier model's runs are listed by date)
    assert set(re.findall(r"\bclaude-[a-z]+-\d+(?:-\d+)*\b", history)) == {"claude-sonnet-5"}


# --------------------------------------------------------------------------------------------------
# One render, checked
# --------------------------------------------------------------------------------------------------


def test_the_outputs_are_the_committed_files(rendered: dict[str, str]) -> None:
    assert set(rendered) == set(build.OUTPUT_PATHS)
    for relative, content in rendered.items():
        assert (ROOT / relative).read_text(encoding="utf-8") == content, (
            f"{relative}: run python -m evals.present --write"
        )


def test_two_renders_are_byte_identical(rendered: dict[str, str]) -> None:
    assert build.outputs(ROOT, RESULTS) == rendered


def test_no_output_holds_a_path_of_the_building_computer(rendered: dict[str, str]) -> None:
    """No output names the checkout it was built in (the history page's commands name example folders only)."""
    for relative, content in rendered.items():
        for mark in (str(ROOT), str(ROOT.parent), str(Path.home()) + "/"):
            assert mark not in content, (relative, mark)
        if (
            relative != "docs/evals-history.md"
        ):  # the page of 0.3.0 shows `--results-dir /tmp/holdout` as it was
            for mark in PATH_MARKS:
                assert mark not in content, (relative, mark)


def _tree(tmp_path: Path) -> Path:
    """A copy of what the presenter reads and writes, to edit."""
    root = tmp_path / "root"
    for relative in build.OUTPUT_PATHS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return root


@pytest.mark.slow  # replays or records a whole run: once, in backend-slow, without coverage
def test_check_passes_and_fails_after_a_one_character_edit_to_any_output(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    assert build.check(root, RESULTS) == []
    for relative in build.OUTPUT_PATHS:
        path = root / relative
        original = path.read_bytes()
        # README's own text outside the block is not the presenter's: the edit goes inside the block
        middle = original.index(b"exactly right") if relative == "README.md" else len(original) // 2
        path.write_bytes(
            original[:middle]
            + (b"x" if original[middle : middle + 1] != b"x" else b"y")
            + original[middle + 1 :]
        )
        assert build.check(root, RESULTS) == [relative], relative
        path.write_bytes(original)


def test_check_finds_a_chart_nothing_renders_any_more(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    stale = root / "docs" / "assets" / "eval-due-date-accuracy.png"
    stale.write_bytes(b"old")
    assert build.check(root, RESULTS) == ["docs/assets/eval-due-date-accuracy.png"]


def test_the_readme_outside_the_block_is_left_as_it_is(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    readme = root / "README.md"
    before, rest = readme.read_text(encoding="utf-8").split(BEGIN, 1)
    _, after = rest.split(END, 1)
    readme.write_text(before + BEGIN + "\nstale\n" + END + after, encoding="utf-8")
    build.write(root, RESULTS)
    assert readme.read_text(encoding="utf-8") == (ROOT / "README.md").read_text(encoding="utf-8")
    readme.write_text(before + after, encoding="utf-8")
    with pytest.raises(PresentError, match="evals:begin"):
        build.outputs(root, RESULTS)


@pytest.mark.slow  # replays or records a whole run: once, in backend-slow, without coverage
def test_the_cli_checks_and_says_what_differs(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    ok = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.present",
            "--check",
            "--root",
            str(root),
            "--results-dir",
            str(RESULTS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr
    (root / "docs" / "evals.md").write_text("edited\n", encoding="utf-8")
    bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.present",
            "--check",
            "--root",
            str(root),
            "--results-dir",
            str(RESULTS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1 and "docs/evals.md" in bad.stderr and "--write" in bad.stderr


# --------------------------------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------------------------------


def _values(svg: str) -> str:
    return html.unescape(re.search(r"<desc[^>]*>(.*?)</desc>", svg, re.S).group(1))  # type: ignore[union-attr]


@pytest.mark.parametrize("name", charts.NAMES)
@pytest.mark.parametrize("theme", ["light", "dark", "css"])
@pytest.mark.parametrize("narrow", [False, True])
def test_every_chart_names_itself_and_every_value(
    doc: dict[str, Any], name: str, theme: str, narrow: bool
) -> None:
    svg = charts.svg(name, doc, theme, narrow=narrow)
    assert svg.startswith("<svg ") and 'role="img"' in svg and "aria-labelledby=" in svg
    assert re.search(r"<title id=\"[^\"]+\">[^<]+</title>", svg)
    description = _values(svg)
    _, rows = charts.table(name, doc)
    for row in rows:
        assert row[0] in description, (name, row[0])
        for cell in row[1:]:
            assert cell in description or cell in svg, (name, cell)
    marks = re.findall(r"<(circle|rect|polygon|path)[^>]*>(?:<title>[^<]+</title>)?", svg)
    titled = re.findall(r"<(?:circle|rect|polygon)[^>]*><title>[^<]+</title>", svg)
    assert titled, name
    assert marks
    # text in text colours only, never a series colour
    for fill in re.findall(r'<text[^>]*style="fill:([^;"]+)', svg):
        assert fill not in {palette.LIGHT[c] for c in palette.CONDITIONS} | {
            palette.DARK[c] for c in palette.CONDITIONS
        }, (name, fill)


@pytest.mark.parametrize("name", charts.NAMES)
def test_every_chart_follows_the_page_s_row_order(doc: dict[str, Any], name: str) -> None:
    _, rows = charts.table(name, doc)
    labels = [palette.LABELS[c] for c in doc["order"]]
    shown = [row[0] for row in rows if row[0] in labels]
    assert shown == [label for label in labels if label in shown]


def test_the_hero_chart_shows_the_intervals_it_names(doc: dict[str, Any]) -> None:
    description = _values(charts.svg("held-out", doc, "light"))
    assert "Ordnung: 163 of 168 exactly right (97.0 %, 95 % CI 93.2–99.0)" in description
    assert "LLM only: 136 of 168 exactly right (81.0 %, 95 % CI 74.2–86.6)" in description
    assert "13 of 168 late or missed" in description
    assert "Clopper–Pearson" in charts.svg("held-out", doc, "light")


def test_the_narrow_charts_keep_their_text_readable_on_a_phone(doc: dict[str, Any]) -> None:
    """At 320 px the page is 288 px wide: a narrow chart's smallest text stays at 12 px or more there."""
    for name in charts.NAMES:
        svg = charts.svg(name, doc, "css", narrow=True)
        width = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))  # type: ignore[union-attr]
        smallest = min(float(size) for size in re.findall(r'font-size="([\d.]+)"', svg))
        assert smallest * 288 / width >= 12, (name, smallest, width)


def test_the_palette_is_the_validated_set() -> None:
    assert [palette.LIGHT[c] for c in palette.CONDITIONS] == ["#2a78d6", "#e87ba4", "#eda100", "#008300"]
    assert [palette.DARK[c] for c in palette.CONDITIONS] == ["#3987e5", "#d55181", "#c98500", "#008300"]
    assert len(set(palette.SHAPES.values())) == 4
    # what the validator reports, computed again (WCAG): two light colours under 3:1 (relief: labels and tables),
    # every dark one at 3:1 or more, and text far above 4.5:1 on both surfaces
    light = {
        c: round(palette.contrast(palette.LIGHT[c], palette.LIGHT["surface"]), 2) for c in palette.CONDITIONS
    }
    assert light["llm_only"] == 2.62 and light["llm_rules_text"] == 2.11
    assert all(palette.contrast(palette.DARK[c], palette.DARK["surface"]) >= 3 for c in palette.CONDITIONS)
    for theme in (palette.LIGHT, palette.DARK):
        assert palette.contrast(theme["text"], theme["surface"]) >= 7
        assert palette.contrast(theme["text2"], theme["surface"]) >= 4.5
        assert palette.contrast(theme["link"], theme["surface"]) >= 4.5


def test_the_committed_charts_are_small(rendered: dict[str, str]) -> None:
    svgs = {relative: content for relative, content in rendered.items() if relative.endswith(".svg")}
    assert len(svgs) == 2 * len(charts.COMMITTED)
    for relative, content in svgs.items():
        assert len(content.encode("utf-8")) <= 40_000, relative


# --------------------------------------------------------------------------------------------------
# The report page
# --------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def page_dir(tmp_path_factory: pytest.TempPathFactory, doc: dict[str, Any]) -> Path:
    out = tmp_path_factory.mktemp("site")
    site.build_site(doc, out)
    return out


def test_the_page_builds_from_presentation_json_with_the_standard_library_only(tmp_path: Path) -> None:
    out = tmp_path / "evals"
    script = (
        "import sys\n"
        "from evals.present.__main__ import main\n"
        f"code = main(['--site', {str(out)!r}, '--check-site'])\n"
        "heavy = sorted(m for m in ('rapidfuzz', 'pydantic', 'ordnung', 'evals.metrics', 'evals.analysis') "
        "if m in sys.modules)\n"
        "print(','.join(heavy))\n"
        "raise SystemExit(code)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
    assert (out / "index.html").is_file() and (out / "data.json").is_file()
    assert json.loads((out / "data.json").read_text(encoding="utf-8")) == json.loads(
        PRESENTATION_PATH.read_text(encoding="utf-8")
    )


def test_the_page_passes_its_own_check(page_dir: Path, doc: dict[str, Any]) -> None:
    assert site.check_site(page_dir, doc, forbidden=site.dataset_sentences()) == []


def test_every_chart_on_the_page_has_its_table_and_csv(page_dir: Path, doc: dict[str, Any]) -> None:
    page = (page_dir / "index.html").read_text(encoding="utf-8")
    for name in charts.NAMES:
        figure = page.split(f'<figure id="{name}"', 1)[1].split("</figure>", 1)[0]
        assert "<table" in figure and "<details" in figure and f'href="{name}.csv"' in figure, name
        header, rows = charts.table(name, doc)
        written = list(csv.reader(io.StringIO((page_dir / f"{name}.csv").read_text(encoding="utf-8"))))
        assert written == [header, *rows]
    # the charts the README names are served next to the page, for PyPI (pyproject.toml rewrites them here)
    for name in charts.COMMITTED:
        for theme in ("light", "dark"):
            assert (page_dir / f"eval-{name}-{theme}.svg").read_text(encoding="utf-8") == (
                ROOT / "docs" / "assets" / f"eval-{name}-{theme}.svg"
            ).read_text(encoding="utf-8")


def test_the_page_check_catches_what_it_promises(page_dir: Path, doc: dict[str, Any], tmp_path: Path) -> None:
    good = (page_dir / "index.html").read_text(encoding="utf-8")

    def problems(page: str, forbidden: tuple[str, ...] = ()) -> list[str]:
        out = tmp_path / "check"
        out.mkdir(exist_ok=True)
        for path in page_dir.iterdir():
            (out / path.name).write_bytes(path.read_bytes())
        (out / "index.html").write_text(page, encoding="utf-8")
        return site.check_site(out, doc, forbidden=forbidden)

    assert problems(good) == []
    head, figure = good.split('<figure id="cost"', 1)
    assert any(
        "cost has no table" in p
        for p in problems(head + '<figure id="cost"' + figure.replace("<table", "<tabel", 1))
    )
    assert any("#nowhere" in p for p in problems(good.replace('href="#1-summary"', 'href="#nowhere"', 1)))
    assert any(
        "<desc>" in p or "desc" in p for p in problems(re.sub(r"<desc id=\"[^\"]+\">", "<desc>", good, 1))
    )
    assert any(
        "12.3 %" in p for p in problems(good.replace("</main>", "<p>Ordnung scored 12.3 %.</p></main>"))
    )
    assert any("77 of 168" in p for p in problems(good.replace("</main>", "<p>77 of 168 right.</p></main>")))
    secret = "Bitte zahlen Sie den Betrag bis zum Ende des Monats"
    leaked = problems(good.replace("</main>", f"<p>{secret}</p></main>"), forbidden=(secret,))
    assert leaked and all(secret not in p for p in leaked)  # named without printing it


def test_what_may_scroll_sideways_on_a_phone_is_a_focusable_labelled_region(page_dir: Path) -> None:
    """A wide table or a command line scrolls inside its own box, which a keyboard can reach (axe's
    scrollable-region-focusable): every table and every code block sits in one."""
    page = (page_dir / "index.html").read_text(encoding="utf-8")
    wrapper = r'<div class="tablewrap" tabindex="0" role="region" aria-label="[^"]+">'
    assert page.count("<table") == len(re.findall(wrapper + "<table", page)) > 0
    assert page.count("<pre") == len(re.findall(wrapper + "<pre", page)) > 0


def test_the_page_is_light_and_dark_and_has_no_script(page_dir: Path) -> None:
    page = (page_dir / "index.html").read_text(encoding="utf-8")
    assert "<script" not in page
    assert "@media (prefers-color-scheme: dark)" in page and ':root[data-theme="dark"]' in page
    assert '<html lang="en">' in page and '<meta name="viewport"' in page


def test_no_output_holds_a_sentence_of_a_letter(rendered: dict[str, str], page_dir: Path) -> None:
    forbidden = site.dataset_sentences()
    assert len(forbidden) > 100
    texts = dict(rendered)
    texts["site/index.html"] = (page_dir / "index.html").read_text(encoding="utf-8")
    leaks = [relative for relative, content in texts.items() if any(s in content for s in forbidden)]
    assert leaks == []  # file names only: the sentences themselves are never printed


def test_a_benchmark_run_never_writes_over_the_presenter_s_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``evals.report`` still renders a run's own page (``--docs-path``), but never into docs/evals.md, the history
    page or docs/assets: those are the presenter's, and a run is not a headline by itself."""
    from evals import report

    for docs, chart in (
        (ROOT / "docs" / "evals.md", tmp_path / "chart.png"),
        (ROOT / "docs" / "evals-history.md", tmp_path / "chart.png"),
        (tmp_path / "evals.md", ROOT / "docs" / "assets" / "eval-due-date-accuracy.png"),
    ):
        with pytest.raises(ValueError, match=r"python -m evals\.present"):
            report.check_docs_paths(docs, chart)
    report.check_docs_paths(tmp_path / "evals.md", tmp_path / "chart.png")
    # the page for no results yet writes no chart: only its own path counts
    report.check_docs_paths(tmp_path / "evals.md", None)
    with pytest.raises(ValueError, match=r"python -m evals\.present"):
        report.check_docs_paths(ROOT / "docs" / "evals.md", None)

    def refuse(docs: Path, chart: Path) -> None:
        raise ValueError("refused")

    monkeypatch.setattr(report, "check_docs_paths", refuse)
    run = report.load_results(RESULTS / "2026-09-25-sonnet-test.json")
    with pytest.raises(ValueError, match="refused"):
        report.write_docs([run], docs_path=tmp_path / "evals.md", chart_path=tmp_path / "chart.png")
    assert list(tmp_path.iterdir()) == []  # refused before anything is written


def test_ci_checks_the_outputs_with_no_model_call() -> None:
    """CI's slow backend job renders every committed output again and fails on a difference (it replays nothing)."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    runs = [step.get("run", "") for step in workflow["jobs"]["backend-slow"]["steps"]]
    assert ".venv/bin/python -m evals.present --check" in runs
    ask = next(i for i, run in enumerate(runs) if "-m evals.ask" in run)
    assert runs.index(".venv/bin/python -m evals.present --check") > ask


def test_pypi_shows_the_readme_charts_from_the_pages_copy() -> None:
    """PyPI's page can't show a picture GitHub's raw files serve as text: the README's charts load from the report
    page's copy, which the site build writes next to the page."""
    import tomllib

    hook = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["hatch"]["metadata"][
        "hooks"
    ]["fancy-pypi-readme"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for substitution in hook["substitutions"]:
        readme = re.sub(substitution["pattern"], substitution["replacement"], readme)
    for name in charts.COMMITTED:
        for theme in ("light", "dark"):
            assert f"docs/assets/eval-{name}-{theme}.svg" not in readme
    assert f'srcset="{PAGES_URL}eval-held-out-dark.svg"' in readme
    assert f'src="{PAGES_URL}eval-held-out-light.svg"' in readme
