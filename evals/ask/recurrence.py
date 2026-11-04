"""The recurrence ledger of "Ask: new questions on the demo household": to-dos that repeat.

**The ledger** is a copy of the base ledger in which the to-dos ``evals/ask/heldout/recurrence.json`` names — each by
its letter and its place in that letter's truth (``<letter>#<index>``), all written blind after the code freeze — are
made to repeat by the rule it gives them, through the app's own edit of a to-do (what ``PATCH /api/items/{id}`` runs:
:func:`ordnung.api.routes.items._update`, so the schedule, the first occurrence on or after the ledger's day and every
date's receipt are the app's). No model is called. The listings' tie-breaking stamps are put back, so the same rules
give the same ledger, its fingerprint and the recordings' keys on every run of the same day.

**Its gold** is never read from it: a recurrence question's gold is computed from the rule and the first occurrence
by the blind writer's ``recurrence_gold.py`` (:func:`evals.ask.heldout_check.recurrence_gold`), and
``python -m evals.ask.heldout --validate`` builds this ledger for each day of the window and holds each to-do's next
date in it to the gold's (:func:`next_dates`), so every question is asked against the ledger its gold assumes.

The held-out runner finds :func:`build_recurrence` by name (:data:`evals.ask.heldout.PROVIDERS`).
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evals.ask import heldout_check
from evals.ask.ledger import LedgerError, SampleLife, benchmark_today, copy_database
from evals.ask.questions import TruthDoc, load_truth
from ordnung.api.routes.items import ItemPatch, _update
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.demo.loader import DB_NAME
from ordnung.models import Item, Recurrence

RULES = heldout_check.HELDOUT_DIR / heldout_check.RECURRENCE_NAME


def _todos(rules: Path) -> list[dict[str, Any]]:
    try:
        return heldout_check.load_recurrence_file(rules)
    except heldout_check.CheckError as exc:
        raise LedgerError(str(exc)) from exc


def _truth_item(todo: Mapping[str, Any], truth: Mapping[str, TruthDoc]) -> dict[str, Any]:
    letter, index = str(todo["letter"]), int(todo["item"])
    if letter not in truth:
        raise LedgerError(f"to-do {todo['id']}: no letter of the sample life is called {letter}")
    items = truth[letter].truth["items"]
    if not 0 <= index < len(items):
        raise LedgerError(f"to-do {todo['id']}: {letter} has no truth item {index}")
    return dict(items[index])


def _ledger_item(store: Store, life: SampleLife, todo: Mapping[str, Any], wanted: Mapping[str, Any]) -> Item:
    """The ledger's to-do that is the truth item ``wanted`` of the to-do's letter: its kind, date and amount."""
    letter = str(todo["letter"])
    if wanted.get("expected_due") is None:
        raise LedgerError(f"to-do {todo['id']}: {letter}#{todo['item']} has no date to repeat from")
    amount = wanted.get("amount")
    found = [
        item
        for item in store.list_items(doc_id=life.doc_ids[letter])
        if item.kind == wanted["kind"]
        and item.due_date == wanted["expected_due"]
        and (amount is None or item.amount is None or abs(float(item.amount) - float(amount)) < 0.005)
    ]
    if len(found) != 1:
        raise LedgerError(
            f"to-do {todo['id']}: the ledger holds {len(found)} to-dos for {letter}#{todo['item']}, not one"
        )
    return found[0]


def _stamps(target: Path) -> dict[str, tuple[str, str]]:
    with contextlib.closing(sqlite3.connect(target / DB_NAME)) as db:
        return {
            row[0]: (row[1], row[2]) for row in db.execute("SELECT id, created_at, updated_at FROM items")
        }


def _restore(target: Path, stamps: Mapping[str, tuple[str, str]]) -> None:
    """Put back the stamps the edit moved to the time of the run: listings break ties by them, so a tool's answer
    — and with it a recorded one — would otherwise depend on the hour of the run."""
    with contextlib.closing(sqlite3.connect(target / DB_NAME)) as db, db:
        for item_id, (created_at, updated_at) in stamps.items():
            db.execute(
                "UPDATE items SET created_at = ?, updated_at = ? WHERE id = ?",
                (created_at, updated_at, item_id),
            )


def build_recurrence(base: Path, target: Path, life: SampleLife, *, rules: Path | None = None) -> Path:
    """A copy of the base ledger's database in ``target`` with each to-do of ``rules`` (default:
    ``evals/ask/heldout/recurrence.json``) made to repeat by its rule, through the app's own edit of a to-do, as of
    the ledger's day (:func:`~evals.ask.ledger.benchmark_today`). A to-do the ledger does not hold once, one that
    repeats already (its letter's rule), or a rule the app does not accept stops the build, named by id."""
    todos = _todos(rules or RULES)
    truth = load_truth()
    wanted = [(todo, _truth_item(todo, truth)) for todo in todos]
    unknown = sorted({str(todo["letter"]) for todo, _ in wanted if str(todo["letter"]) not in life.doc_ids})
    if unknown:
        raise LedgerError(f"no letter of the sample life is called {', '.join(unknown)}")
    copy_database(base, target)
    stamps = _stamps(target)
    today = benchmark_today()
    store = Store.open(Paths(target))
    try:
        for todo, item in wanted:
            found = _ledger_item(store, life, todo, item)
            if found.recurrence is not None or item.get("recurrence"):
                raise LedgerError(
                    f"to-do {todo['id']}: {todo['letter']}#{todo['item']} repeats already, as its letter says"
                )
            try:
                patch = ItemPatch(recurrence=Recurrence(**todo["rule"]))
            except ValidationError as exc:
                raise LedgerError(
                    f"to-do {todo['id']}: its rule is not one a to-do can repeat by ({exc})"
                ) from exc
            _update(store, found.id, patch, today)
    finally:
        store.close()
    _restore(target, stamps)
    return target


def _same_rule(item: Item, rule: Mapping[str, Any]) -> bool:
    if item.recurrence is None:
        return False
    given = Recurrence(**rule)
    keys = ("interval", "unit", "working_day", "day_of_month")
    return all(getattr(item.recurrence, key) == getattr(given, key) for key in keys)


def next_dates(target: Path, *, life: SampleLife, rules: Path | None = None) -> dict[str, date | None]:
    """Each to-do of ``rules``: its next date in a built recurrence ledger (the date of its letter's to-do of its
    kind that repeats by its rule; ``None`` without one)."""
    todos = _todos(rules or RULES)
    truth = load_truth()
    store = Store.open(Paths(target))
    try:
        found: dict[str, date | None] = {}
        for todo in todos:
            kind = _truth_item(todo, truth)["kind"]
            matches: Sequence[Item] = [
                item
                for item in store.list_items(doc_id=life.doc_ids.get(str(todo["letter"]), ""))
                if item.kind == kind and _same_rule(item, todo["rule"])
            ]
            due = matches[0].due_date if len(matches) == 1 else None
            found[str(todo["id"])] = date.fromisoformat(due) if due else None
        return found
    finally:
        store.close()
