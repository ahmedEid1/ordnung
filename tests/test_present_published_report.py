"""The published final run's report says what its files hold, where a reader looks for it.

Once the final run is published, ``docs/evals.md`` (and the report page built from the same ``presentation.json``)
shows, beside the registered sentences: the gap each pre-registered power was simulated at and the
pre-registration's caveat on it; which corrected labels are offered dates that are not scored; only the repository
paths a ``code_hash_changed`` deviation names; the newest recording by when it was written; the rarer high-stakes
kinds where the new kinds hold them; the final run's own replays without the sender's Land and with each code check
switched off, its cost per letter and its flags as a selective prediction; why reminders were missed end to end, by
split and cause; and what the first-attempt sensitivity is for a retaken Ask turn. The Ask benchmark's page points to
the held-out set's result. Every number here is read from the results files and the pre-registration, never typed.

These tests print counts, ids, paths and rates only, never a letter, a label or a prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from evals.ask import report as ask_report
from evals.present import final, finalrun, fmt

from helpers_publication import final_published

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "results"
REPORT = ROOT / "docs" / "evals.md"
ASK_PAGE = ROOT / "docs" / "evals-ask.md"
PRESENTATION = ROOT / "evals" / "present" / "presentation.json"
PREREG = ROOT / "evals" / "preregistration" / "final-0.4.0.json"

published = pytest.mark.skipif(
    not final_published(), reason="the final run is not published in this checkout"
)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _flat(value: str) -> str:
    return " ".join(value.split())


def _section(title: str) -> str:
    report = REPORT.read_text(encoding="utf-8")
    start = report.index(f"\n## {title}\n")
    end = report.find("\n## ", start + 1)
    return report[start : end if end >= 0 else len(report)]


def _final_json() -> tuple[str, dict[str, Any]]:
    (path,) = [path for path in sorted(RESULTS.glob("*-final.json")) if "-ask-" not in path.name]
    return path.name, _json(path)


def _named(pattern: str) -> list[Path]:
    return sorted(RESULTS.glob(pattern))


def _table(section: str, header: str) -> list[list[str]]:
    """The rows of the one table of ``section`` whose header row starts with ``header``, as cells."""
    lines = section.splitlines()
    (start,) = [i for i, line in enumerate(lines) if line.startswith(f"| {header}")]
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def _row(rows: list[list[str]], *first: str) -> list[str]:
    """The one row whose first cells are ``first``."""
    found = [row for row in rows if tuple(row[: len(first)]) == first]
    assert len(found) == 1, (first, len(found))
    return found[0]


# --------------------------------------------------------------------------------------------------
# Units: what the presenter takes from a deviation and from the reads
# --------------------------------------------------------------------------------------------------


def test_a_code_hash_deviation_names_only_the_repository_paths_of_its_evidence() -> None:
    """An evidence line's first word is shown as a changed path only when it is one (``dir/name.ext``): never a
    note's first word, a key such as ``before:`` or a URL."""
    evidence = [
        "clock real 2026-11-17T15:00Z",
        "tests/e2e_support/final_report.py sha256 " + "a" * 64,
        "before: " + "b" * 64,
        "https://github.com/example/example/pull/1",
        "evals/present/text.py (presentation only)",
    ]
    entry = {"id": "D9", "kind": "code_hash_changed", "evidence": evidence}
    shown = finalrun._deviation(entry, "deviations.json")
    assert shown["paths"] == ["tests/e2e_support/final_report.py", "evals/present/text.py"]


def test_a_deviation_s_items_are_told_apart_into_deadlines_and_offered_dates() -> None:
    """A label error on a slot the reads score counts as a deadline; one on an offered date, which is not scored, is
    counted apart; a slot the reads do not show counts as a deadline."""
    required = {("s", "e1"): [True, False], ("s", "e2"): [True]}
    entry = {
        "id": "D9",
        "kind": "label_error",
        "applies_to": {
            "split": "s",
            "items": [
                {"entry_id": "e1", "item": 0},
                {"entry_id": "e1", "item": 1},
                {"entry_id": "e2", "item": 0},
                {"entry_id": "e3", "item": 4},
            ],
        },
    }
    shown = finalrun._deviation(entry, "deviations.json", required)
    assert (shown["items"], shown["offered"]) == (3, 1)


# --------------------------------------------------------------------------------------------------
# The published report
# --------------------------------------------------------------------------------------------------


@published
def test_the_card_names_the_newest_recording_by_when_it_was_written() -> None:
    """The final reads are all of one day: the card names the one whose file was written last, not the first."""
    _, analysis = _final_json()
    reads = [row for row in analysis["meta"]["inputs"] if row["role"] in finalrun.FINAL_INPUTS]
    written = {row["file"]: _json(RESULTS / row["file"])["meta"]["generated_at"] for row in reads}
    newest = max(reads, key=lambda row: (row["date"], written[row["file"]]))
    oldest = min(reads, key=lambda row: (row["date"], written[row["file"]]))
    assert newest["commit"] != oldest["commit"]
    (row,) = [
        line for line in _section("Evaluation card").splitlines() if line.startswith("| Newest recording |")
    ]
    assert f"`{newest['commit']}`" in row and newest["split"] in row
    assert f"`{oldest['commit']}`" not in row


@published
def test_section_3_says_the_new_kinds_hold_the_rarer_high_stakes_kinds() -> None:
    """With the final run's new kinds read, section 3 no longer says the rarer high-stakes kinds are "not among them
    yet": it says they are only in that small set."""
    data = _flat(_section("3. Data and labels"))
    assert "are not among them yet" not in data
    assert "are only in the final run's new kinds, a small set read once" in data


@published
def test_the_power_names_the_gap_it_was_simulated_at_and_the_registered_caveat() -> None:
    """Each tested comparison's power is shown with the gap of the earlier held-out splits it was simulated at, the
    power at half that gap and the minimum detectable difference (the power file's), and the pre-registration's
    caveat on these figures follows, word for word."""
    statistics = _section("7. Statistics")
    prereg = _json(PREREG)
    power = _json(ROOT / prereg["power"]["file"])
    row = power["comparisons"]["F1_accuracy"]["ordnung-vs-llm_only"]
    cells = _row(_table(statistics, "Ordnung minus | Measure | Simulated at"), "LLM only", "Exact date right")
    assert cells[2] == final._formatted(row["observed"]["gap"], "points", "test")
    assert cells[3] == final._formatted(row["power"], "pct_whole", "test")
    assert cells[4] == final._formatted(row["power_half_gap"], "pct_whole", "test")
    assert cells[5] == final._formatted(row["mdd"]["gap"], "points", "test")
    assert _flat(prereg["power"]["caveats"]) in _flat(statistics)


@published
def test_the_corrected_labels_on_offered_dates_are_said_not_scored() -> None:
    """D012 and D013 correct offered dates, which are not scored: section 16 says so instead of "deadlines", and
    the sensitivity table is followed by the sentence that the label-corrected analysis equals the primary."""
    deviations = _section("16. Deviations")
    rows = _table(deviations, "Id | Kind |")
    for ident in ("D012", "D013"):
        cells = _row(rows, f"`{ident}`")
        assert cells[2] == "`holdout4`; offered dates, not scored: 1", cells[2]
    _, analysis = _final_json()
    corrected = analysis["sensitivities"]["label_corrected"]
    assert corrected["items_changed"] == 0 and corrected["same_as_primary"] is True
    results = _flat(_section("6. Results"))
    assert (
        "The labels the blind review corrected (`D012` and `D013`) are offered dates, which are not scored: no "
        "scored answer changes, so the label-corrected analysis equals the primary by construction."
        in results
    )


@published
def test_a_code_hash_deviation_shows_its_path_and_no_word_of_its_notes() -> None:
    rows = _table(_section("16. Deviations"), "Id | Kind |")
    assert _row(rows, "`D014`")[2] == "`tests/e2e_support/final_report.py`"
    assert "https://" not in _row(rows, "`D001`")[2]


@published
def test_the_ask_retakes_say_their_first_attempt_sensitivity_is_not_computed() -> None:
    """The retaken Ask turns' registered consequence names a first-attempt sensitivity the analysis computes for the
    benchmark's reads only: the page says so, and where the first attempts are published."""
    _, analysis = _final_json()
    assert analysis["sensitivities"]["first_attempt"]["deviations"] == []
    retakes = sorted(path.name for path in (ROOT / "evals" / "retakes").iterdir() if path.is_dir())
    deviations = _flat(_section("16. Deviations"))
    assert "`D004` and `D010` retook a turn of the held-out Ask set." in deviations
    assert "the held-out Ask analysis has none, so none is shown for these retakes" in deviations
    assert f"Their first attempts are published under `evals/retakes/{retakes[-1]}/`." in deviations


@published
def test_the_final_run_s_replays_without_the_land_and_with_the_checks_off_are_shown() -> None:
    """Section 6.4 shows each final read replayed without the sender's Land and section 8 each with every code check
    switched off, every number from the replay's own file."""
    results = _section("6. Results")
    rows = _table(results, "Read | With the letterhead's Land")
    for path in _named("*-without-land-holdout4*.json"):
        data = _json(path)
        numbers = data["splits"]["holdout4"]
        assert f"`{path.name}`" in results
        cells = _row(rows, str(data["meta"]["repeat"]))
        assert cells[1] == fmt.kn(numbers["with_land"]["due_date_accuracy"])
        assert cells[2].startswith(fmt.kn(numbers["without_land"]["due_date_accuracy"]))
        assert cells[4] == str(int(numbers["without_land"]["dangerous_late_rate"]["k"]))
        assert cells[5] == str(len(numbers["changed"]))
    ablations = _section("8. Ablations")
    files = sorted(_named("*-checks-ablated-holdout4*.json"), key=lambda path: _json(path)["meta"]["repeat"])
    assert len(files) == 3
    for path in files:
        assert f"`{path.name}`" in ablations
    first = _json(files[0])
    label = first["meta"]["ablations"]["no_two_dates_check"]["label"]
    cells = _row(_table(ablations, "Configuration | Read 1"), label)
    for read, path in enumerate(files):
        counts = _json(path)["totals"]["all"]["ablations"]["no_two_dates_check"]["counts"]
        assert cells[1 + 2 * read] == f"{int(counts['right'])}/{int(counts['scored'])}"
        assert cells[2 + 2 * read] == str(int(counts["late"]))
    note = "As recorded, not pre-registered: these are the earlier held-out splits"
    assert _flat(ablations).index(label) < _flat(ablations).index(note)


@published
def test_the_final_run_s_cost_and_flags_are_shown_from_its_analysis() -> None:
    """Section 12 shows each condition's registered cost and latency (p50, p95 and mean); section 10 its flags on
    read 1's deadlines and, apart, over the reads, each column the field it names."""
    _, analysis = _final_json()
    conditions = analysis["primary"]["conditions"]
    cost = _section("12. Cost and latency")
    safety = _section("10. Safety and selective prediction")
    for condition, label in (
        ("ordnung", "Ordnung"),
        ("llm_only", "LLM only"),
        ("llm_rules_text", "LLM + rules text"),
        ("llm_rules_tool", "LLM + rules tool"),
    ):
        spent, latency = conditions[condition]["cost"], conditions[condition]["latency_ms"]
        cells = _row(
            _table(
                cost,
                "Condition | $ per letter | $ per right date | Latency p50 | Latency p95 | Latency mean | Letters read",
            ),
            label,
        )
        assert cells[1:] == [
            fmt.usd(spent["usd_per_letter"]),
            fmt.usd(spent["usd_per_right_date"]),
            fmt.seconds(latency["p50"]),
            fmt.seconds(latency["p95"]),
            fmt.seconds(latency["mean"]),
            str(spent["letters"]),
        ]
        flags, over = conditions[condition]["selective"], conditions[condition]["flags_over_reads"]
        cells = _row(
            _table(
                safety,
                "Condition | Wrong dates “Please check” caught | Wrong dates any flag caught | Without a flag: right |",
            ),
            label,
        )
        assert cells[1] == fmt.of(flags["please_check"]["recall_wrong"])
        assert cells[2] == fmt.of(flags["any_flag"]["recall_wrong"])
        assert cells[3] == fmt.kn(flags["unflagged"]["accuracy"])
        # over the reads: each date wrong in any read once, caught when flagged in every read in which it was wrong
        assert cells[-1] == fmt.of(over["caught"]) and int(over["caught"]["n"]) == over["wrong_dates"]


@published
def test_the_selective_lead_says_which_reads_each_column_counts() -> None:
    """Section 10's lead says what the table counts: read 1's deadlines, caught when read 1 flagged them, as the
    analysis's ``selective`` block counts them; and, for the last column only, every date wrong in any read, caught
    when it was flagged in every read in which it was wrong (``flags_over_reads``)."""
    safety = _flat(_section("10. Safety and selective prediction"))
    name, analysis = _final_json()
    template = _json(PRESENTATION)["final"]["views"]["templates"]["selective.lead"]["text"]
    lead = _flat(template.format(source=name, first=analysis["primary"]["reads_used"][0]))
    assert lead in safety and analysis["primary"]["reads_used"][0] == 1
    first, _, last = lead.partition("The last column")
    assert "read 1" in first and "caught when read 1 flagged it" in first
    assert "over the reads" not in first and "every read" not in first
    assert "in every read in which it was wrong" in last
    # the table the lead describes follows it
    assert safety.index(lead) < safety.index("| Condition | Wrong dates “Please check” caught")
    # the read-1 columns' wrong dates are read 1's, not the dates wrong over the reads
    for condition in ("llm_only", "llm_rules_tool"):
        block = analysis["primary"]["conditions"][condition]
        assert (
            int(block["selective"]["any_flag"]["recall_wrong"]["n"])
            <= block["flags_over_reads"]["wrong_dates"]
        )


#: The earlier splits' note, and the sentence it ends with where the section shows nothing of the final run.
POOLED_NOTE = "As recorded, not pre-registered: these are the earlier held-out splits, re-analysed after their results were known."
ELSEWHERE = "The final run's numbers are in [Results](#6-results) and [Statistics](#7-statistics)."
ABOVE = "The final run's own numbers for this section are above."


@published
def test_the_earlier_splits_note_points_above_where_the_section_shows_the_final_run() -> None:
    """Where a section shows the final run's own table before the earlier splits, the note says the final run's
    numbers are above, never that they are in Results and Statistics; elsewhere it keeps pointing there."""
    for title, header in (
        ("8. Ablations", "| Configuration | Read 1"),
        ("10. Safety and selective prediction", "| Condition | Wrong dates “Please check” caught"),
        ("12. Cost and latency", "| Condition | $ per letter | $ per right date | Latency p50"),
        ("13. From a letter to a reminder", "| Split | Reminded in time |"),
    ):
        section = _flat(_section(title))
        assert ELSEWHERE not in section, title
        assert section.index(header) < section.index(f"{POOLED_NOTE} {ABOVE}"), title
    for title in ("6. Results", "9. Robustness"):
        section = _flat(_section(title))
        assert f"{POOLED_NOTE} {ELSEWHERE}" in section and ABOVE not in section, title


@published
def test_the_readme_says_the_block_counts_the_new_kinds_end_to_end() -> None:
    """The block's end-to-end count includes the letters of new kinds and names the scam cause; outside it, the
    README says so and points to what the block does not give: their benchmark result and the other causes."""
    (path,) = _named("*-e2e-holdout4-newkinds.json")
    metrics = _json(path)["metrics"]
    assert "newkinds" in metrics["by_split"] and set(metrics["all"]["not_reminded"]) - {
        "set_aside:scam_signs"
    }
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    outside = _flat(readme[readme.index("<!-- evals:end -->") :])
    assert "leaves out the letters of new kinds" not in outside
    assert (
        "The block counts the letters of new kinds end to end but does not give their benchmark result "
        "([§ 6.1](docs/evals.md#61-the-final-run)), nor why the deadlines it does not put down to a scam got no "
        "reminder ([§ 13](docs/evals.md#13-from-a-letter-to-a-reminder))."
    ) in outside


@published
def test_the_reminders_missed_end_to_end_are_shown_by_split_and_cause() -> None:
    """Every obligation of the final letters that got no reminder in time is in section 13, by split and cause: the
    letters set aside as a scam and those with no to-do stored, as the end-to-end file counts them."""
    (path,) = _named("*-e2e-holdout4-newkinds.json")
    by_split = _json(path)["metrics"]["by_split"]
    section = _section("13. From a letter to a reminder")
    assert f"`{path.name}`" in section
    words = {"set_aside:scam_signs": "set aside as a scam", "not_stored": "no to-do stored for it"}
    shown = 0
    rows = _table(section, "Split | Reminded in time |")
    for split, block in by_split.items():
        cells = _row(rows, f"`{split}`")
        assert cells[1] == fmt.kn(block["reminded_in_time"])
        for cause, count in block["not_reminded"].items():
            assert f"{words[cause]}: {count}" in cells[2]
            shown += count
    assert shown == sum(_json(path)["metrics"]["all"]["not_reminded"].values()) > 0


def test_the_ask_page_points_to_the_held_out_result_and_its_scope() -> None:
    """The Ask benchmark's page is the development set's; it says where the held-out set's result is, and that the
    held-out set holds out only its questions. A held-out run's file renders no such pointer."""
    page = ASK_PAGE.read_text(encoding="utf-8")
    assert ask_report.HELD_OUT in page and "(evals.md#61-the-final-run)" in ask_report.HELD_OUT
    assert page.index("**Development set:**") < page.index(ask_report.HELD_OUT)
    assert ask_report._held_out({"schema": 2, "set": "heldout"}) == []
    assert ask_report._held_out({"schema": 2, "set": "dev"}) == [ask_report.HELD_OUT, ""]


@published
def test_presentation_json_carries_what_the_page_shows_and_the_page_builds_from_it() -> None:
    """The report page is built from ``presentation.json`` alone: it holds the power's gaps, the caveat, the cost,
    the flags and the replays the Markdown report shows."""
    shown = _json(PRESENTATION)["final"]
    prereg = _json(PREREG)
    assert shown["power_caveat"] == prereg["power"]["caveats"]
    power = _json(ROOT / prereg["power"]["file"])["comparisons"]
    for family, rows in shown["power_at"].items():
        for pair, row in rows.items():
            source = power[family][pair]
            assert row["gap"] == source["observed"]["gap"] and row["mdd"] == source["mdd"]["gap"]
    assert [row["read"] for row in shown["replays"]["without_land"]] == [1, 2, 3]
    assert [row["read"] for row in shown["replays"]["ablation"]] == [1, 2, 3]
    _, analysis = _final_json()
    assert (
        shown["cost"]["ordnung"]["usd_per_letter"]
        == analysis["primary"]["conditions"]["ordnung"]["cost"]["usd_per_letter"]
    )
    for condition in final.CONDITIONS:
        theirs = analysis["primary"]["conditions"][condition]
        assert shown["cost"][condition]["latency_ms"] == {
            key: theirs["latency_ms"][key] for key in ("p50", "p95", "mean")
        }
        assert shown["selective"][condition]["over_reads"] == {
            "k": int(theirs["flags_over_reads"]["caught"]["k"]),
            "n": int(theirs["flags_over_reads"]["caught"]["n"]),
        }
