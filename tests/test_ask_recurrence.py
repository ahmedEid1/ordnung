"""The recurrence ledger of "Ask: new questions on the demo household" (``evals/ask/recurrence.py``): to-dos of the
sample life made to repeat through the app's own to-do edit, from a rules file (``recurrence.json``), with no model
call; and the recurrence gold (``recurrence_gold.py``, written blind) resolved and checked against it.

These tests use small hand-made rules files in a temporary folder and the sample life's truth."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.ask import heldout, heldout_check, recurrence  # noqa: E402
from evals.ask.ledger import LedgerError, SampleLife, build_base, pinned_today  # noqa: E402

from ordnung.assistant.ask import ledger_fingerprint  # noqa: E402
from ordnung.config import Paths  # noqa: E402
from ordnung.db.store import Store  # noqa: E402

DAY = date(2026, 12, 8)
DENTIST = "zahnarzt_terminkarte"  # its truth item 0: an appointment on 2026-10-08
REMINDER = "mahnung_techmarkt"  # its truth item 0: a payment of 94.99 € due on 2026-09-30
RENT = "mietvertrag"  # its truth item 0 repeats every month already, as the lease says


def _todo(todo_id: str, letter: str, item: int, first: str, **rule: Any) -> dict[str, Any]:
    return {"id": todo_id, "letter": letter, "item": item, "rule": rule, "first": first}


TODOS = [
    _todo("ho-rec-dentist", DENTIST, 0, "2026-10-08", interval=6, unit="months"),
    _todo("ho-rec-reminder", REMINDER, 0, "2026-09-30", interval=1, unit="months"),
]


def _rules(folder: Path, todos: list[dict[str, Any]], *, schema: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "recurrence.json"
    payload = {"schema": schema or heldout_check.RECURRENCE_SCHEMA, "todos": todos}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, SampleLife]:
    tmp = tmp_path_factory.mktemp("recurrence-base")
    life = SampleLife.load()
    with pinned_today(DAY):
        build_base(tmp / "base", life, day=DAY)
    return tmp / "base", life


def _items(folder: Path) -> dict[str, Any]:
    store = Store.open(Paths(folder))
    try:
        return {item.id: item for item in store.list_items()}
    finally:
        store.close()


def _fingerprint(folder: Path) -> str:
    store = Store.open(Paths(folder))
    try:
        return ledger_fingerprint(store)
    finally:
        store.close()


def _of(items: dict[str, Any], life: SampleLife, letter: str, kind: str, due: str) -> Any:
    (found,) = [
        item
        for item in items.values()
        if item.doc_id == life.doc_ids[letter] and item.kind == kind and item.due_date == due
    ]
    return found


def test_a_rules_file_makes_sample_life_to_dos_repeat(base: tuple[Path, SampleLife], tmp_path: Path) -> None:
    """Each to-do named by its letter and its truth item gets its rule through the app's own edit of a to-do, which
    moves it to its first occurrence on or after the ledger's day; nothing else in the ledger changes, the stamps
    the listings break ties by included, and the same rules give the same ledger (and fingerprint) on every run."""
    folder, life = base
    rules = _rules(tmp_path / "heldout", TODOS)
    before = _items(folder)
    dentist = _of(before, life, DENTIST, "appointment", "2026-10-08")
    reminder = _of(before, life, REMINDER, "payment", "2026-09-30")
    with pinned_today(DAY):
        built = recurrence.build_recurrence(folder, tmp_path / "one", life, rules=rules)
        again = recurrence.build_recurrence(folder, tmp_path / "two", life, rules=rules)
    after = _items(built)
    assert after[dentist.id].recurrence is not None
    assert (after[dentist.id].recurrence.interval, after[dentist.id].recurrence.unit) == (6, "months")
    assert after[dentist.id].due_date == "2027-04-08"  # 8 Oct 2026, then every six months
    assert after[reminder.id].recurrence is not None and after[reminder.id].due_date == "2026-12-30"
    for item_id, item in before.items():
        if item_id in (dentist.id, reminder.id):
            assert (after[item_id].created_at, after[item_id].updated_at) == (
                item.created_at,
                item.updated_at,
            )
            continue
        assert after[item_id] == item, item_id
    assert _fingerprint(built) == _fingerprint(again) != _fingerprint(folder)
    assert recurrence.next_dates(built, rules=rules, life=life) == {
        "ho-rec-dentist": date(2027, 4, 8),
        "ho-rec-reminder": date(2026, 12, 30),
    }


@pytest.mark.parametrize(
    ("todos", "problem"),
    [
        ([_todo("ho-rec-x", "no_such_letter", 0, "2026-10-08", interval=1, unit="months")], "no_such_letter"),
        ([_todo("ho-rec-x", DENTIST, 7, "2026-10-08", interval=1, unit="months")], "ho-rec-x"),
        ([_todo("ho-rec-x", RENT, 0, "2026-10-05", interval=1, unit="months")], "repeats already"),
        ([_todo("ho-rec-x", DENTIST, 0, "2026-10-08", interval=0, unit="months")], "ho-rec-x"),
        ([_todo("ho-rec-x", DENTIST, 0, "2026-10-08", interval=1, unit="fortnights")], "unit"),
        (
            [
                _todo("ho-rec-x", DENTIST, 0, "2026-10-08", interval=1, unit="months"),
                _todo("ho-rec-x", REMINDER, 0, "2026-09-30", interval=1, unit="months"),
            ],
            "used twice",
        ),
    ],
)
def test_the_builder_refuses_what_the_ledger_cannot_hold(
    base: tuple[Path, SampleLife], tmp_path: Path, todos: list[dict[str, Any]], problem: str
) -> None:
    folder, life = base
    rules = _rules(tmp_path / "heldout", todos)
    with pinned_today(DAY), pytest.raises(LedgerError, match=problem):
        recurrence.build_recurrence(folder, tmp_path / "out", life, rules=rules)


def test_a_rules_file_of_another_schema_or_none_is_refused(
    base: tuple[Path, SampleLife], tmp_path: Path
) -> None:
    folder, life = base
    with pinned_today(DAY), pytest.raises(LedgerError, match=r"recurrence\.json"):
        recurrence.build_recurrence(folder, tmp_path / "out", life, rules=tmp_path / "recurrence.json")
    rules = _rules(tmp_path / "heldout", TODOS, schema="something-else/1")
    with pinned_today(DAY), pytest.raises(LedgerError, match="schema"):
        recurrence.build_recurrence(folder, tmp_path / "out", life, rules=rules)


def test_the_held_out_runner_finds_the_recurrence_and_household_ledgers() -> None:
    """Each held-out ledger has a builder the runner finds by name, with nothing registered by hand first: the
    household copy (E2's) and the recurrence copy."""
    from evals.ask.household import build_household

    assert heldout.ledger_builder("recurrence") is recurrence.build_recurrence
    assert heldout.ledger_builder("household") is build_household


# --------------------------------------------------------------------------------------------------
# the recurrence gold, written blind: resolved per day and checked against the ledger
# --------------------------------------------------------------------------------------------------

#: A stand-in for the blind writer's ``recurrence_gold.py``: plain month steps from the first occurrence, no shift.
GOLD_MODULE = '''
"""Synthetic recurrence gold for the tests: month steps, no weekend or holiday shift."""

import calendar
import datetime


def _step(first, months, n):
    index = first.month - 1 + months * n
    year, month = first.year + index // 12, index % 12 + 1
    return datetime.date(year, month, min(first.day, calendar.monthrange(year, month)[1]))


def _all(todo):
    first = datetime.date.fromisoformat(todo["first"])
    months = todo["rule"]["interval"] * (12 if todo["rule"]["unit"] == "years" else 1)
    return (_step(first, months, n) for n in range(0, 600))


def next_occurrence(todo, today):
    return next(day for day in _all(todo) if day >= today){shift}


def occurrences(todo, start, end):
    return [day for day in _all(todo) if start <= day <= end][:50]


def year_total(todo, year):
    return round(sum(todo["amount"] for day in _all(todo) if day.year == year), 2)
'''


def _gold_module(folder: Path, *, shift: str = "", header: str = "") -> Path:
    path = folder / "recurrence_gold.py"
    path.write_text(header + GOLD_MODULE.replace("{shift}", shift), encoding="utf-8")
    return path


def _recurrence_question(qid: str, todo: str, phrasing: str = "en", **ask: Any) -> dict[str, Any]:
    return {
        "id": qid,
        "group": "recurrence",
        "category": "recurrence",
        "fact": f"rec-{todo}-{ask.get('ask', 'next')}",
        "phrasing": phrasing,
        "ledger": "recurrence",
        "text": f"Synthetic test question about {todo}.",
        "gold": None,
        "list": None,
        "recurrence": {"todo": todo, **ask},
    }


def _questions(folder: Path, rows: list[dict[str, Any]]) -> Path:
    path = folder / heldout.QUESTIONS_NAME
    path.write_text(json.dumps({"schema": heldout.SCHEMA, "questions": rows}, indent=1), encoding="utf-8")
    (folder / heldout.ATTACKS_NAME).write_text(
        json.dumps({"schema": heldout.SCHEMA, "attacks": []}, indent=1), encoding="utf-8"
    )
    return path


def test_recurrence_questions_get_their_gold_from_the_blind_module_on_their_day(tmp_path: Path) -> None:
    """A recurrence question names a to-do of recurrence.json and what it asks (the next occurrence, the occurrences
    in a window, a year's total); its gold is computed when the set is loaded, for the day it is loaded for."""
    folder = tmp_path / "heldout"
    _rules(folder, TODOS)
    _gold_module(folder)
    path = _questions(
        folder,
        [
            _recurrence_question("ho-r-next", "ho-rec-reminder", ask="next", with_amount=True),
            _recurrence_question(
                "ho-r-window", "ho-rec-reminder", ask="window", **{"from": "today", "to": "today+60"}
            ),
            _recurrence_question("ho-r-total", "ho-rec-reminder", ask="year_total", year=2027),
        ],
    )
    on = {q.question.id: q for q in heldout.load_questions(path, today=date(2026, 12, 8))}
    gold = on["ho-r-next"].question.gold
    assert gold is not None and gold.dates == (date(2026, 12, 30),) and gold.amounts == (94.99,)
    assert gold.letters == (REMINDER,)
    listed = on["ho-r-window"].extras.list
    assert listed is not None and len(listed.gold) == 2  # 30 Dec 2026 and 30 Jan 2027
    assert on["ho-r-window"].question.gold is not None
    assert on["ho-r-window"].question.gold.dates == (date(2026, 12, 30), date(2027, 1, 30))
    total = on["ho-r-total"].question.gold
    assert total is not None and total.amounts == (round(12 * 94.99, 2),)
    later = {q.question.id: q for q in heldout.load_questions(path, today=date(2026, 12, 31))}
    later_gold = later["ho-r-next"].question.gold
    assert later_gold is not None and later_gold.dates == (date(2027, 1, 30),)


@pytest.mark.parametrize(
    ("setup", "problem"),
    [
        ("no-module", "recurrence_gold.py"),
        ("not-stdlib", "standard library"),
        ("unknown-todo", "ho-rec-nobody"),
        ("bad-ask", "ask"),
    ],
)
def test_a_recurrence_question_without_its_gold_is_refused(tmp_path: Path, setup: str, problem: str) -> None:
    folder = tmp_path / "heldout"
    _rules(folder, TODOS)
    if setup != "no-module":
        _gold_module(folder, header="import numpy\n" if setup == "not-stdlib" else "")
    todo = "ho-rec-nobody" if setup == "unknown-todo" else "ho-rec-dentist"
    ask = "weather" if setup == "bad-ask" else "next"
    path = _questions(folder, [_recurrence_question("ho-r-1", todo, ask=ask)])
    with pytest.raises(heldout.HeldOutError, match=problem):
        heldout.load_questions(path, today=DAY)


def test_validate_window_holds_the_ledger_to_the_recurrence_gold(tmp_path: Path) -> None:
    """--validate builds the recurrence ledger on each day of the window and compares every to-do's next date in it
    with the blind gold's: a gold that moves a date the ledger does not (or the other way round) is named by id."""
    folder = tmp_path / "heldout"
    _rules(folder, TODOS)
    _gold_module(folder)
    _questions(folder, [_recurrence_question("ho-r-next", "ho-rec-dentist", ask="next")])
    start, end = date(2026, 12, 8), date(2026, 12, 9)
    assert heldout.validate_window(start, end, folder, ledgers=True) == []
    _gold_module(folder, shift=" + datetime.timedelta(days=1)")
    problems = heldout.validate_window(start, end, folder, ledgers=True)
    assert problems and all("ho-rec-" in problem for problem in problems)
    assert any("ho-rec-dentist" in problem and "2026-12-08" in problem for problem in problems)
