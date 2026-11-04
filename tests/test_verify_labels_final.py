"""The final splits' facts: ``evals/dataset/<split>/facts.json`` in the grammar of ``evals/dataset/FACTS.md``.

``evals/verify_labels.py`` re-derives each dated label of a final split from that file instead of its own hand-read
``FACTS``: n days, weeks, months, Werktage or Arbeitstage forward or back from an event; the end of the n-th
calendar month after one; each step with or without the weekend/holiday end shift; the Land whose holidays count.
Every fact names its source, and the conventions it applies must be the ones its label is tagged with. The five
earlier splits keep their hand-read facts and their result.

Every manifest here is synthetic: no test reads a final split's labels.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from evals import verify_labels as vl
from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset"
D = date

CONVENTIONS = [
    {"id": "c02", "disputed": True, "text": "posting date = letter date"},
    {"id": "c03", "disputed": True, "text": "deemed delivery"},
    {"id": "f01", "disputed": False, "text": "a final split's own"},
]


def step(op: str, n: int, unit: str | None = None, *, shift: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"op": op, "n": n, "shift": shift}
    if unit is not None:
        out["unit"] = unit
    return out


def derive(start: str, steps: list[dict[str, Any]], land: str | None = None) -> date:
    """One derivation through the grammar's loader, as a facts.json slot gives it."""
    return vl.derive(date.fromisoformat(start), vl.parse_steps(steps, "test"), region=land)


# --------------------------------------------------------------------------------------------------
# each operation of the grammar, worked by hand
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "steps", "land", "want"),
    [
        # Thu 04.03.2027 + 2 days = Sat 06.03.; the end shift moves it to Mon 08.03.
        ("2027-03-04", [step("forward", 2, "days", shift=False)], None, D(2027, 3, 6)),
        ("2027-03-04", [step("forward", 2, "days", shift=True)], None, D(2027, 3, 8)),
        # Wed 23.12.2026 + 2 weeks = Wed 06.01.2027, Heilige Drei Könige in BW, BY and ST only
        ("2026-12-23", [step("forward", 2, "weeks", shift=True)], "BW", D(2027, 1, 7)),
        ("2026-12-23", [step("forward", 2, "weeks", shift=True)], "NW", D(2027, 1, 6)),
        ("2026-12-23", [step("forward", 2, "weeks", shift=False)], "BW", D(2027, 1, 6)),
        # months: the same day number, else the month's last day (Sun 28.02.2027; shifted to Mon 01.03.)
        ("2027-01-31", [step("forward", 1, "months", shift=False)], None, D(2027, 2, 28)),
        ("2027-01-31", [step("forward", 1, "months", shift=True)], None, D(2027, 3, 1)),
        ("2027-05-31", [step("forward", 1, "months", shift=True)], None, D(2027, 6, 30)),
        ("2028-01-31", [step("forward", 1, "months", shift=False)], None, D(2028, 2, 29)),
        # back: the latest day from which the same step forward ends on or before the event
        ("2027-04-30", [step("back", 1, "months", shift=False)], None, D(2027, 3, 31)),
        ("2027-02-28", [step("back", 1, "months", shift=False)], None, D(2027, 1, 31)),
        ("2027-03-15", [step("back", 2, "weeks", shift=False)], None, D(2027, 3, 1)),
        ("2027-03-01", [step("back", 1, "days", shift=False)], None, D(2027, 2, 28)),
        # back onto Sat 06.03.2027; the shift of a step back moves to the working day before, Fri 05.03.
        ("2027-03-08", [step("back", 2, "days", shift=False)], None, D(2027, 3, 6)),
        ("2027-03-08", [step("back", 2, "days", shift=True)], None, D(2027, 3, 5)),
        # the end of the n-th calendar month after the event (n = 0: its own month)
        ("2026-12-15", [step("month_end", 0, shift=False)], None, D(2026, 12, 31)),
        ("2026-12-15", [step("month_end", 2, shift=False)], None, D(2027, 2, 28)),
        ("2026-12-15", [step("month_end", 2, shift=True)], None, D(2027, 3, 1)),
        ("2027-03-10", [step("month_end", 1, shift=True)], None, D(2027, 4, 30)),
        ("2027-01-10", [step("month_end", 0, shift=True)], None, D(2027, 2, 1)),
        # Arbeitstage (Mon–Fri) and Werktage (Mon–Sat) skip the Land's holidays; the start day is not counted
        ("2027-01-04", [step("forward", 3, "arbeitstage", shift=False)], "BW", D(2027, 1, 8)),
        ("2027-01-04", [step("forward", 3, "arbeitstage", shift=False)], "NW", D(2027, 1, 7)),
        ("2027-01-04", [step("forward", 5, "werktage", shift=False)], "NW", D(2027, 1, 9)),
        ("2027-01-04", [step("forward", 5, "werktage", shift=False)], "BY", D(2027, 1, 11)),
        # a stated date: no step
        ("2027-02-05", [], None, D(2027, 2, 5)),
        # steps chain: posted Thu 25.03.2027, the 4th day is Easter Monday; shifted (Tue 30.03.) or not, then a
        # month with the end shift
        (
            "2027-03-25",
            [step("forward", 4, "days", shift=True), step("forward", 1, "months", shift=True)],
            None,
            D(2027, 4, 30),
        ),
        (
            "2027-03-25",
            [step("forward", 4, "days", shift=False), step("forward", 1, "months", shift=True)],
            None,
            D(2027, 4, 29),
        ),
        # a term of 12 months from 01.03.2027 ends 29.02.2028; a month's notice must arrive by 31.01.2028
        (
            "2027-03-01",
            [step("forward", 12, "months", shift=False), step("back", 1, "days", shift=False)],
            None,
            D(2028, 2, 29),
        ),
        (
            "2027-03-01",
            [
                step("forward", 12, "months", shift=False),
                step("back", 1, "days", shift=False),
                step("back", 1, "months", shift=False),
            ],
            None,
            D(2028, 1, 31),
        ),
    ],
)
def test_each_operation_of_the_grammar(
    start: str, steps: list[dict[str, Any]], land: str | None, want: date
) -> None:
    assert derive(start, steps, land) == want


def _as_grammar(fn: Any, args: tuple[Any, ...]) -> tuple[date, list[dict[str, Any]]]:
    """A hand-read fact of the five earlier splits, written in the grammar (test-only translation)."""
    name = fn.__name__
    if name == "remedy":
        posted, scope = args
        days = 4 if posted >= D(2025, 1, 1) else 3
        return posted, [
            step("forward", days, "days", shift=scope == "ao"),
            step("forward", 1, "months", shift=True),
        ]
    if name in ("after_days", "after_weeks", "after_months"):
        unit = name.removeprefix("after_")
        return args[0], [step("forward", args[1], unit, shift=True)]
    if name in ("werktage", "arbeitstage"):
        return args[0], [step("forward", args[1], name, shift=False)]
    if name in ("stated", "appointment"):
        return args[0], []
    if name == "day_before":
        return args[0], [step("back", 1, "days", shift=False)]
    term = [step("forward", args[1], "months", shift=False), step("back", 1, "days", shift=False)]
    if name == "term_end":
        return args[0], term
    assert name == "cancel_by", name
    return args[0], [*term, step("back", args[2], "months", shift=False)]


def test_the_grammar_gives_every_hand_read_date_of_the_earlier_splits() -> None:
    """Each hand-read fact (and conflicting date) of dev … holdout3, written in the grammar, gives the same date as
    the hand-read rule under every Land's holidays and under the nationwide ones."""
    rules = [fact for facts in vl.FACTS.values() for fact in facts.values()]
    rules += list(vl.CONFLICT_ALTERNATIVES.values())
    dated = [rule for rule in rules if isinstance(rule, tuple) and callable(rule[0])]
    assert len(dated) > 240
    for fn, args, region in dated:
        start, steps = _as_grammar(fn, args)
        parsed = vl.parse_steps(steps, "test")
        for land in (None, *vl.LAENDER) if region is None else (None, region):
            assert vl.derive(start, parsed, region=land) == fn(*args, region=land), (fn.__name__, args, land)


# --------------------------------------------------------------------------------------------------
# the file: what the grammar refuses
# --------------------------------------------------------------------------------------------------


def dated(start: str, steps: list[dict[str, Any]], *, land: str | None = None, source: str = "A1",
          conventions: list[str] | None = None, **more: Any) -> dict[str, Any]:  # fmt: skip
    fact: dict[str, Any] = {"source": source, "land": land, "from": start, "steps": steps, **more}
    if conventions is not None:
        fact["conventions"] = conventions
    return fact


def write_facts(root: Path, split: str, letters: dict[str, Any]) -> Path:
    path = root / split / "facts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"split": split, "letters": letters}, indent=1), encoding="utf-8")
    return path


# Thu 11.03.2027 + 2 days = Sat 13.03.; shifted to Mon 15.03. (no Land has a holiday on these days)
GOOD = {"holdout4-x-K1": {"slots": {"i0": dated("2027-03-11", [step("forward", 2, "days", shift=True)])}}}


def test_a_well_formed_file_loads(tmp_path: Path) -> None:
    letters = vl.load_facts(write_facts(tmp_path, "holdout4", GOOD))
    assert set(letters) == {"holdout4-x-K1"}


@pytest.mark.parametrize(
    ("slot", "fact", "refusal"),
    [
        ("due", dated("2027-03-04", []), "slot"),  # an unknown slot name
        ("i0", dated("2027-03-04", [], source="A2"), "source"),  # an unknown source
        ("i0", {"land": None, "from": "2027-03-04", "steps": []}, "source"),  # no source
        ("i0", dated("2027-03-04", [step("sideways", 2, "days", shift=True)]), "op"),
        ("i0", dated("2027-03-04", [step("forward", 2, "fortnights", shift=True)]), "unit"),
        ("i0", dated("2027-03-04", [{"op": "forward", "n": 2, "unit": "days"}]), "shift"),
        ("i0", dated("2027-03-04", [step("forward", 0, "days", shift=True)]), "n"),
        ("i0", dated("2027-03-04", [step("forward", True, "days", shift=True)]), "n"),  # a bool is no count
        ("i0", dated("2027-03-04", [step("month_end", 1, "days", shift=True)]), "unit"),
        ("i0", dated("2027-02-30", []), "date"),
        ("i0", dated("2027-03-04", [], land="XX"), "Land"),
        ("i0", {"source": "A1", "from": "2027-03-04", "steps": []}, "land"),  # the Land is always stated
        ("i0", dated("2027-03-04", [], note="extra"), "note"),  # an unknown key
        ("i0", {"source": "A1", "undatable": False}, "undatable"),
        (
            "i0",
            {"source": "A1", "land": None, "ambiguous": [{"from": "2027-03-04", "steps": []}]},
            "ambiguous",
        ),
        ("i0", dated("2027-03-04", [], conventions="c02"), "conventions"),
    ],
)
def test_the_grammar_refuses(tmp_path: Path, slot: str, fact: dict[str, Any], refusal: str) -> None:
    path = write_facts(tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {slot: fact}}})
    with pytest.raises(vl.FactsError, match=refusal):
        vl.load_facts(path)


def test_a_file_names_its_own_split(tmp_path: Path) -> None:
    path = write_facts(tmp_path, "holdout4", GOOD)
    path.write_text(json.dumps({"split": "newkinds", "letters": GOOD}), encoding="utf-8")
    with pytest.raises(vl.FactsError, match="split"):
        vl.load_facts(path)


def test_a_price_change_carries_its_source(tmp_path: Path) -> None:
    change = {"effective_date": "2027-03-01", "letter_date": "2027-01-11", "basis": "§ 41 Abs. 5 EnWG",
              "old_amount": 72.0, "new_amount": 81.0}  # fmt: skip
    path = write_facts(tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {}, "price_change": change}})
    with pytest.raises(vl.FactsError, match="source"):
        vl.load_facts(path)
    write_facts(
        tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {}, "price_change": {"source": "A1", **change}}}
    )
    assert vl.load_facts(path)


# --------------------------------------------------------------------------------------------------
# the file against the manifest
# --------------------------------------------------------------------------------------------------


def item(due: str | None, *, conventions: list[str] | None = None, **more: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": "deadline", "expected_due": due, "spec": {}, **more}
    if conventions is not None:
        out["conventions"] = conventions
    return out


def entry(cid: str, *, split: str = "holdout4", items: list[dict[str, Any]] | None = None,
          optional: list[dict[str, Any]] | None = None, contract: dict[str, Any] | None = None,
          final: bool = True, today: str = "2026-12-08", valid_until: str = "2026-12-15",
          region: str | None = None, price_change: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    truth = {"items": items or [], "optional_items": optional or [], "contract": contract,
             "price_change": price_change, "document_date": None}  # fmt: skip
    out: dict[str, Any] = {"id": cid, "split": split, "family": "x", "photo": False, "today": today,
                           "authority_region": region, "truth": truth}  # fmt: skip
    if final:
        out |= {"final_day": today, "valid_until": valid_until}
    return out


def check(
    root: Path, entries: list[dict[str, Any]], *, require_facts: bool = False
) -> tuple[int, list[str], list[str]]:
    """The date part of ``verify_labels.run``: (dated labels re-derived, problems, final splits without facts)."""
    report = vl.check_facts(
        root, entries, vl.convention_ids({"conventions": CONVENTIONS}), require_facts=require_facts
    )
    return report["dated_labels_checked"], report["date_problems"], report["splits_without_facts"]


def test_a_final_split_is_rederived_from_its_facts_file(tmp_path: Path) -> None:
    entries = [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=[])])]
    write_facts(tmp_path, "holdout4", GOOD)
    assert check(tmp_path, entries) == (1, [], [])
    write_facts(
        tmp_path,
        "holdout4",
        {"holdout4-x-K1": {"slots": {"i0": dated("2027-03-11", [step("forward", 2, "days", shift=False)])}}},
    )
    checked, problems, _ = check(tmp_path, entries)
    assert checked == 1 and problems == ["holdout4-x-K1 i0: label 2027-03-15, independent 2027-03-13"]


def test_a_slot_the_truth_does_not_have_is_refused(tmp_path: Path) -> None:
    entries = [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=[])])]
    write_facts(
        tmp_path,
        "holdout4",
        {"holdout4-x-K1": {"slots": {**GOOD["holdout4-x-K1"]["slots"], "i1": dated("2027-03-11", [])}}},
    )
    assert check(tmp_path, entries)[1] == ["holdout4-x-K1 i1: expected in truth but missing"]


def test_facts_for_a_letter_outside_the_split_are_refused(tmp_path: Path) -> None:
    entries = [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=[])]),
               entry("newkinds-y-1", split="newkinds", items=[item("2027-03-15", conventions=[])])]  # fmt: skip
    write_facts(
        tmp_path,
        "holdout4",
        {**GOOD, "holdout4-x-K9": GOOD["holdout4-x-K1"], "newkinds-y-1": GOOD["holdout4-x-K1"]},
    )
    write_facts(tmp_path, "newkinds", {})
    problems = check(tmp_path, entries)[1]
    assert "holdout4-x-K9: facts for a letter that is not in the manifest" in problems
    assert "newkinds-y-1: in holdout4/facts.json, but the letter is in newkinds" in problems


def test_a_refused_file_is_a_problem_and_its_split_is_not_rederived(tmp_path: Path) -> None:
    entries = [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=[])])]
    write_facts(
        tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {"i0": dated("2027-03-11", [], source="A9")}}}
    )
    checked, problems, waiting = check(tmp_path, entries)
    assert checked == 0 and waiting == []
    assert len(problems) == 1 and problems[0].startswith("holdout4/facts.json: ") and "source" in problems[0]


def test_a_final_split_waits_for_its_facts_file(tmp_path: Path) -> None:
    """Before the blind audit the final letters exist without facts: their dates are not re-derived, which the report
    says, and ``--require-facts`` turns into a problem."""
    entries = [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=[])]),
               entry("older-x-A9", split="older", final=False, items=[item("2027-03-15")])]  # fmt: skip
    _, problems, waiting = check(tmp_path, entries)
    assert waiting == ["holdout4"]
    # a split that is not final still needs its facts
    assert problems == ["older-x-A9: no facts for this letter"]
    problems = check(tmp_path, entries, require_facts=True)[1]
    assert "holdout4: no holdout4/facts.json, so none of its dates is re-derived" in problems


def test_the_land_of_a_fact_counts_as_for_a_hand_read_one(tmp_path: Path) -> None:
    """A Land left open must not matter; a stated Land's holidays must be marked when they move the date."""
    two_weeks = [step("forward", 2, "weeks", shift=True)]
    entries = [entry("holdout4-x-K1", items=[item("2027-01-06", conventions=[])])]
    write_facts(tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {"i0": dated("2026-12-23", two_weeks)}}})
    assert check(tmp_path, entries)[1] == [
        "holdout4-x-K1 i0: label 2027-01-06 depends on municipal-only holidays in ['BW', 'BY', 'ST']",
        "holdout4-x-K1 i0: Land unknown but ['BW', 'BY', 'ST'] holidays change 2027-01-06",
    ]
    marked = item("2027-01-07", conventions=[], region_sensitive=True, due_if_region_ignored="2027-01-06")
    entries = [entry("holdout4-x-K1", region="BW", items=[marked])]
    write_facts(
        tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {"i0": dated("2026-12-23", two_weeks, land="BW")}}}
    )
    assert check(tmp_path, entries) == (1, [], [])
    entries = [entry("holdout4-x-K1", region="BW", items=[item("2027-01-07", conventions=[])])]
    assert check(tmp_path, entries)[1] == [
        "holdout4-x-K1 i0: region_sensitive=None, nationwide gives 2027-01-06",
        "holdout4-x-K1 i0: due_if_region_ignored None != 2027-01-06",
    ]


def test_conventions_must_exist_and_be_applied_as_tagged(tmp_path: Path) -> None:
    fact = dated("2027-03-11", [step("forward", 2, "days", shift=True)], conventions=["c02", "c03"])
    write_facts(tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {"i0": fact}}})
    tagged = [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=["c03", "c02"])])]
    assert check(tmp_path, tagged)[1] == []
    other = [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=["c02"])])]
    assert check(tmp_path, other)[1] == [
        "holdout4-x-K1 i0: the facts apply conventions ['c02', 'c03'], the label is tagged ['c02']"
    ]
    write_facts(
        tmp_path, "holdout4", {"holdout4-x-K1": {"slots": {"i0": {**fact, "conventions": ["c02", "c99"]}}}}
    )
    problems = check(
        tmp_path, [entry("holdout4-x-K1", items=[item("2027-03-15", conventions=["c02", "c99"])])]
    )[1]
    assert problems == ["holdout4-x-K1 i0: unknown convention c99"]


def test_a_contract_applies_its_conventions_over_both_dates(tmp_path: Path) -> None:
    term = [step("forward", 12, "months", shift=False), step("back", 1, "days", shift=False)]
    contract = {
        "expected_current_term_end": "2028-02-29",
        "expected_cancel_by": "2028-01-31",
        "conventions": ["f01"],
    }
    entries = [entry("holdout4-x-K1", contract=contract)]
    slots = {"term_end": dated("2027-03-01", term),
             "cancel_by": dated("2027-03-01", [*term, step("back", 1, "months", shift=False)], conventions=["f01"])}  # fmt: skip
    write_facts(tmp_path, "holdout4", {"holdout4-x-K1": {"slots": slots}})
    assert check(tmp_path, entries) == (2, [], [])
    slots["cancel_by"]["conventions"] = []
    write_facts(tmp_path, "holdout4", {"holdout4-x-K1": {"slots": slots}})
    assert check(tmp_path, entries)[1] == [
        "holdout4-x-K1 contract: the facts apply conventions [], the label is tagged ['f01']"
    ]


def test_an_ambiguous_reading_lies_after_the_window(tmp_path: Path) -> None:
    """A final letter is valid through ``valid_until``, so a candidate on or before it is no plausible reading (a
    letter of an earlier split keeps the bound of its own today)."""
    cands = [{"from": "2026-12-14", "steps": []}, {"from": "2027-03-15", "steps": []}]
    write_facts(
        tmp_path,
        "holdout4",
        {"holdout4-x-K1": {"slots": {"i0": {"source": "A1p", "land": None, "ambiguous": cands}}}},
    )
    ambiguous = item("ambiguous", candidates=["2026-12-14", "2027-03-15"])
    assert check(tmp_path, [entry("holdout4-x-K1", items=[ambiguous])])[1] == [
        "holdout4-x-K1 i0: candidate 2026-12-14 is not a plausible reading (weekday/holiday/not after the window)"
    ]
    assert check(tmp_path, [entry("holdout4-x-K1", items=[ambiguous], valid_until="2026-12-13")])[1] == []


def test_conflicting_dates_and_undatable_slots(tmp_path: Path) -> None:
    later = [{"from": "2027-03-22", "steps": []}]
    slots = {"i0": dated("2027-03-11", [step("forward", 2, "days", shift=True)], conflicting=later),
             "i1": {"source": "A1re", "undatable": True}}  # fmt: skip
    write_facts(tmp_path, "holdout4", {"holdout4-x-K1": {"slots": slots}})
    conflict = item("2027-03-15", conventions=[], candidates=["2027-03-15", "2027-03-22"])
    entries = [entry("holdout4-x-K1", items=[conflict, item(None)])]
    assert check(tmp_path, entries) == (2, [], [])
    conflict["candidates"] = ["2027-03-15", "2027-03-23"]
    assert check(tmp_path, entries)[1] == [
        "holdout4-x-K1 i0: candidates ['2027-03-15', '2027-03-23'] should hold 2027-03-22 and the label the earlier date"
    ]


def test_a_price_change_is_checked_like_a_hand_read_one(tmp_path: Path) -> None:
    change = {"source": "A1", "effective_date": "2027-03-01", "letter_date": "2027-01-11",
              "basis": "§ 41 Abs. 5 EnWG", "old_amount": 72.0, "new_amount": 81.0}  # fmt: skip
    write_facts(
        tmp_path,
        "holdout4",
        {
            "holdout4-x-K1": {
                "slots": {"o0": dated("2027-03-01", [step("back", 1, "days", shift=False)])},
                "price_change": change,
            }
        },
    )
    truth_change = {"effective_date": "2027-03-01", "old_amount": 72.0, "new_amount": 81.0, "extra_cost_per_year": 108.0,
                    "special_cancellation": {"basis": "§ 41 Abs. 5 EnWG", "cancel_by_to_avoid_new_price": "2027-02-28",
                                             "window_end": "2027-02-28", "window_end_if_received_on_letter_date": None}}  # fmt: skip
    entries = [entry("holdout4-x-K1", optional=[item("2027-02-28")], price_change=truth_change)]
    assert check(tmp_path, entries) == (3, [], [])
    truth_change["new_amount"] = 82.0
    assert check(tmp_path, entries)[1] == ["holdout4-x-K1: price_change new_amount = 82.0, independent 81.0"]


# --------------------------------------------------------------------------------------------------
# the window of a final letter
# --------------------------------------------------------------------------------------------------


def test_every_scored_contract_and_appointment_date_lies_after_the_window() -> None:
    appointment = {"kind": "appointment", "expected_due": "2026-12-15"}
    contract = {"expected_current_term_end": "2027-11-30", "expected_cancel_by": "2026-12-14"}
    entries = [
        entry(
            "holdout4-x-K1",
            items=[item("2026-12-15"), item("ambiguous", candidates=["2026-12-10", "2027-01-11"])],
            optional=[appointment, item("2026-12-01")],
            contract=contract,
        ),
        entry("holdout4-x-K2", items=[item("2026-12-16")]),
        entry("dev-x-A1", split="dev", final=False, items=[item("2025-01-02")]),
    ]
    assert vl.check_window(entries) == [
        "holdout4-x-K1 items[0]: 2026-12-15 is not after the window (valid until 2026-12-15)",
        "holdout4-x-K1 items[1]: 2026-12-10 is not after the window (valid until 2026-12-15)",
        "holdout4-x-K1 optional_items[0]: 2026-12-15 is not after the window (valid until 2026-12-15)",
        "holdout4-x-K1 contract.expected_cancel_by: 2026-12-14 is not after the window (valid until 2026-12-15)",
    ]


def test_a_final_letter_is_read_on_its_final_day() -> None:
    late = entry("holdout4-x-K1", items=[item("2027-01-11")]) | {"today": "2026-12-09"}
    backwards = entry("holdout4-x-K2", items=[item("2027-01-11")], valid_until="2026-12-01")
    half = entry("holdout4-x-K3", items=[item("2027-01-11")])
    del half["final_day"]
    assert vl.check_window([late, backwards, half]) == [
        "holdout4-x-K1: today 2026-12-09 is not its final day 2026-12-08",
        "holdout4-x-K2: valid until 2026-12-01, before its final day 2026-12-08",
        "holdout4-x-K3: final_day and valid_until come together",
    ]


# --------------------------------------------------------------------------------------------------
# the whole check: a synthetic final split with a letter, and the committed dataset
# --------------------------------------------------------------------------------------------------


def _letter(path: Path, lines: list[str]) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in lines:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def test_run_and_main_on_a_final_split(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = entry("holdout4-x-K1", items=[item("2027-03-15", conventions=["c02"])])
    fixture["truth"] |= {"sender_name": "Beispiel Werke Nord", "document_date": "2026-12-03", "references": [],
                         "amounts": [], "remedy_type": "none"}  # fmt: skip
    fixture |= {"file": "holdout4/x-K1.pdf", "pages": 1, "source_id": None, "language": "en"}
    _letter(tmp_path / fixture["file"], ["Beispiel Werke Nord", "03.12.2026", "Pay within a fortnight."])
    (tmp_path / "manifest.json").write_text(
        json.dumps({"conventions": CONVENTIONS, "entries": [fixture]}), encoding="utf-8"
    )
    report = vl.run(tmp_path)
    assert report["splits_without_facts"] == ["holdout4"] and report["dated_labels_checked"] == 0
    assert vl.main(["--dataset", str(tmp_path)]) == 0
    assert vl.main(["--dataset", str(tmp_path), "--require-facts"]) == 1
    assert "dates not re-derived yet (no facts.json): holdout4" in capsys.readouterr().out
    write_facts(
        tmp_path,
        "holdout4",
        {
            "holdout4-x-K1": {
                "slots": {
                    "i0": dated("2027-03-11", [step("forward", 2, "days", shift=True)], conventions=["c02"])
                }
            }
        },
    )
    report = vl.run(tmp_path, require_facts=True)
    assert report["dated_labels_checked"] == 1 and report["splits_without_facts"] == []
    assert not any(report[key] for key in vl.PROBLEM_KEYS)
    assert vl.main(["--dataset", str(tmp_path), "--require-facts"]) == 0


def test_the_earlier_splits_are_unchanged() -> None:
    """The committed dataset (dev … holdout3, no final letters yet) is re-derived from the hand-read facts alone:
    every one of its 272 dated labels, with no problem and nothing waiting for facts."""
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    earlier = [
        e for e in manifest["entries"] if e["split"] in ("dev", "test", "holdout", "holdout2", "holdout3")
    ]
    report = vl.check_facts(DATASET, earlier, vl.convention_ids(manifest))
    assert report["dated_labels_checked"] == 272
    assert report["date_problems"] == [] and report["splits_without_facts"] == []
    assert vl.check_window(earlier) == []


def test_every_final_split_in_the_dataset_has_its_facts_file() -> None:
    """Once a final split's letters are committed, its facts are too (the blind audit's), so CI re-derives them."""
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    final = {e["split"] for e in manifest["entries"] if "valid_until" in e}
    assert sorted(split for split in final if not (DATASET / split / "facts.json").is_file()) == []


def test_the_grammar_is_written_down_for_people() -> None:
    """``evals/dataset/FACTS.md`` names every operation, unit, source and key the loader accepts."""
    text = (DATASET / "FACTS.md").read_text(encoding="utf-8")
    words = [
        *vl.OPS,
        *vl.UNITS,
        *vl.SOURCES,
        *vl.DATED_KEYS,
        *vl.STEP_KEYS,
        "undatable",
        "ambiguous",
        "price_change",
    ]
    assert [word for word in words if f"`{word}`" not in text] == []


def test_the_grammar_s_examples_decide_no_disputed_reading() -> None:
    """The blind readers get ``FACTS.md`` and no convention: no worked example may end on a Saturday, a Sunday or a
    public holiday, where whether a date moves is a reading the conventions decide; every weekday it names is the
    date's own. Nor does it state the label's own rules (which date a label takes, what tags it carries)."""
    import holidays

    text = (DATASET / "FACTS.md").read_text(encoding="utf-8")
    months = ("January February March April May June July August September October November December").split()
    days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    named = re.compile(rf"(?:({'|'.join(days)}) )?(\d{{1,2}}) ({'|'.join(months)}) (\d{{4}})")
    found = [
        (weekday or None, date(int(year), months.index(month) + 1, int(day)))
        for weekday, day, month, year in named.findall(text)
    ]
    found += [(None, date.fromisoformat(iso)) for iso in re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", text)]
    assert found
    national = holidays.country_holidays("DE", years=range(2030, 2034))
    for weekday, day in found:
        assert weekday in (None, days[day.weekday()]), (weekday, day)
        assert day.weekday() < 5 and day not in national, day
    for rule in ("must be the earliest", "the label is tagged with", "must be a working day", "valid_until"):
        assert rule not in text, rule
