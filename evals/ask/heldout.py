"""Ask: new questions on the demo household — the held-out Ask set, read and checked here.

It asks about the same sample life as the development set (the demo's household), so it is named for what it is:
new questions and attacks, written blind after the code freeze — not new letters. The files are
``evals/ask/heldout/questions.json``, ``attacks.json`` and, for the to-dos that repeat, ``recurrence.json`` (schema
:data:`SCHEMA`; ``evals/ask/heldout/SCHEMA.md`` describes them for the writer). A writer who has seen neither the
recorded answers, Ask's check (``ordnung/assistant/support.py``), its prompt nor the development set's failures writes
them from the sample life's truth; their sha256 goes into the pre-registration before the first recording, and
:func:`frozen_mismatches` holds them to it. ``python -m evals.ask --set heldout`` asks them through the same Ask,
records into ``evals/recorded/ask-heldout/`` and writes ``…-ask-heldout[-rN].json``.

**The day.** The set is written for the planned day D0 and is valid through L = D0 + 7; each run is asked, built and
scored for the day it is recorded (:func:`~evals.ask.ledger.benchmark_today`). So no file names that day: a list window
and a ``passed_today`` attack's injected date may be written ``"today"`` or ``"today+N"``
(:func:`evals.ask.heldout_check.resolve_day`), a recurrence question's gold is computed for the day from
``evals/ask/heldout/recurrence_gold.py`` (written blind, standard library only), and :func:`validate_window` checks
that every gold has the same answer and the same open-or-passed state on each day of [D0, L]
(``python -m evals.ask.heldout --validate --window D0 L``).

A question::

    {"id": "ho-…", "group": "core|household|recurrence|unanswerable", "category": "deadline|payment|contract|
     cross_letter|household|recurrence|unanswerable", "fact": "<the fact its phrasings share>",
     "phrasing": "en|en-paraphrase|de", "ledger": "base|household|recurrence", "text": "…",
     "gold": {"dates": ["YYYY-MM-DD"], "amounts": [12.3], "letters": ["<slug>"], "related": ["<slug>"],
              "numbers": ["<an identifier the answer must give>"]} | null,
     "near_miss": false, "member": "<a household member's name>", "member_values": ["<that member's values>"],
     "list": {"state": "date|amount", "from": "YYYY-MM-DD|today|today+N", "to": "…", "kinds": ["payment"],
              "direction": "out", "items": [{"letter": "<slug>", "date": "YYYY-MM-DD", "amount": 12.3}]} | null,
     "recurrence": {"todo": "<a to-do of recurrence.json>", "ask": "next|window|year_total", …} | absent}

``gold`` is ``null`` exactly for the ``unanswerable`` group (and for a recurrence question, whose gold is computed);
``near_miss`` marks an unanswerable question whose record holds a neighbouring fact; ``member_values`` are values the
answer must never give as the person's own (:mod:`evals.ask.strict`). A list question's gold values and letters come
from its ``items`` (the occurrences it must give, within ``from``–``to``); any other item of the sample life inside the
window is a right inclusion too.

An attack::

    {"id": "ho-…", "kind": "moved_date|changed_amount|no_deadline|cite_other|pay_scam|passed_today|member_as_own",
     "letter": "<slug>", "channel": "page|summary", "ledger": "base|household", "text": "<the injected passage>",
     "question": "…", "gold": {…}, "injected_dates": ["YYYY-MM-DD|today"], "injected_amounts": [12.3],
     "injected_months": [[2027, 12]], "target": "rent_item|rent_contract|tax_objection_item" | null,
     "member": "…", "member_values": ["…"]}

Injected values lie outside the sample life's truth (``cite_other`` names another record's own value and
``passed_today`` today's date, on purpose). ``member_as_own`` succeeds when the final answer gives a member's value
as the person's own (a sentence states it without naming the member).

The ``base`` ledger is the development set's; any other is built by the function :data:`PROVIDERS` names for it
(``household``: :func:`evals.ask.household.build_household`, E2's household copy; ``recurrence``:
:func:`evals.ask.recurrence.build_recurrence`, the set's copy with to-dos that repeat), found on first use; a module
may register a builder of its own with :func:`register_ledger` instead.

**Three runs.** ``python -m evals.ask.heldout --final R1 R2 R3 --write|--check`` writes (or checks)
``<date>-<model>-ask-heldout-final.json`` (:func:`final_payload`): run 1's strict scores
(:func:`evals.ask.metrics.summarise_strict`, recomputed from its rows), what the three runs show together
(:func:`evals.ask.metrics.consistency`), the pre-registered endpoints, and how often the scorer decided an answer by a
path other than the values it states (:func:`scorer_paths`).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, cast, get_args

from evals.ask import heldout_check
from evals.ask.attacks import ATTACKS, Attack, AttackKind, Channel, Target
from evals.ask.ledger import TODAY, SampleLife, benchmark_today, on_day
from evals.ask.metrics import consistency, summarise_strict
from evals.ask.questions import (
    MANIFEST,
    Category,
    Gold,
    Question,
    TruthDoc,
    all_questions,
    load_truth,
    truth_values,
)
from evals.ask.strict import Extras, ListGold, TruthItem, truth_items, window

ROOT = Path(__file__).resolve().parents[2]
HELDOUT_DIR = Path(__file__).resolve().parent / "heldout"
QUESTIONS_NAME = heldout_check.QUESTIONS_NAME
ATTACKS_NAME = heldout_check.ATTACKS_NAME
RECURRENCE_NAME = heldout_check.RECURRENCE_NAME
#: What the set is called everywhere: it asks new questions about the demo's sample life, not about new letters.
NAME = heldout_check.NAME
SCHEMA = heldout_check.SCHEMA
GROUPS = ("core", "household", "recurrence", "unanswerable")
LEDGERS = ("base", "household", "recurrence")
PHRASINGS = ("en", "en-paraphrase", "de")
CATEGORIES = (*get_args(Category), "household", "recurrence")
ATTACK_KINDS = (*get_args(AttackKind), "member_as_own")
CHANNELS = get_args(Channel)
TARGETS = get_args(Target)
PREREGISTRATION = ROOT / "evals" / "preregistration" / "final-0.4.0.json"
#: The file of three runs (``--final``): its schema, and the runs the pre-registration plans.
FINAL_SCHEMA = "ordnung-eval-ask-final/1"
FINAL_KIND = "ask-heldout-final"
REGISTERED_READS = 3


class HeldOutError(ValueError):
    """The held-out set cannot be read or scored as written (the message lists every problem)."""


@dataclass(frozen=True)
class HeldOutQuestion:
    """A held-out question: the :class:`~evals.ask.questions.Question` the runner asks and scores (its ``cluster`` is
    its fact), the group, ledger and phrasing it belongs to, and what strict scoring needs beyond its gold."""

    question: Question
    group: str
    ledger: str
    phrasing: str
    extras: Extras


@dataclass(frozen=True)
class HeldOutAttack:
    """A held-out attack, the ledger whose copy it is injected into, and (``member_as_own``) the member's values."""

    attack: Attack
    ledger: str
    extras: Extras
    member_as_own: bool = False


# --------------------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------------------


def _read(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise HeldOutError(
            f"no held-out set at {path}: it is written after the code freeze, blind, and pre-registered "
            "before its first recording"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get(key), list):
        raise HeldOutError(f"{path.name} is not a held-out set of schema {SCHEMA} with a list of {key}")
    rows = data[key]
    if not all(isinstance(row, dict) for row in rows):
        raise HeldOutError(f"{path.name}: every one of its {key} is an object")
    return cast(list[dict[str, Any]], rows)


class _Problems(list[str]):
    def check(self, ok: bool, where: str, message: str) -> bool:
        if not ok:
            self.append(f"{where}: {message}")
        return ok

    def raise_any(self, path: Path) -> None:
        if self:
            raise HeldOutError(f"{path.name} cannot be scored as written:\n- " + "\n- ".join(self))


def _day(
    value: Any, where: str, problems: _Problems, *, today: date | None = None, tokens: bool = False
) -> date | None:
    """A date as written; with ``tokens``, ``"today"`` and ``"today+N"`` too (resolved for ``today``)."""
    if heldout_check.is_token(value) and not tokens:
        problems.check(False, where, f"{value!r}: a gold date is a fixed date, not a day token")
        return None
    try:
        return heldout_check.resolve_day(value, today or benchmark_today())
    except ValueError:
        pass
    problems.check(False, where, f"{value!r} is no ISO date (YYYY-MM-DD)")
    return None


def _days(values: Any, where: str, problems: _Problems, **day: Any) -> tuple[date, ...]:
    return tuple(
        found for value in values or () if (found := _day(value, where, problems, **day)) is not None
    )


def _amounts(values: Any, where: str, problems: _Problems) -> tuple[float, ...]:
    found = []
    for value in values or ():
        if problems.check(
            isinstance(value, int | float) and not isinstance(value, bool) and value >= 0,
            where,
            f"{value!r} is no amount",
        ):
            found.append(float(value))
    return tuple(found)


def _letters(values: Any, slugs: set[str], where: str, problems: _Problems) -> tuple[str, ...]:
    letters = tuple(str(value) for value in values or ())
    unknown = [slug for slug in letters if slug not in slugs]
    problems.check(not unknown, where, f"no letter of the sample life is called {', '.join(unknown)}")
    return letters


def _gold(
    raw: Mapping[str, Any], slugs: set[str], where: str, problems: _Problems
) -> tuple[Gold, tuple[str, ...]]:
    gold = Gold(
        dates=_days(raw.get("dates"), where, problems),
        amounts=_amounts(raw.get("amounts"), where, problems),
        letters=_letters(raw.get("letters"), slugs, where, problems),
        related=_letters(raw.get("related"), slugs, where, problems),
    )
    return gold, tuple(str(number) for number in raw.get("numbers") or ())


def _member(raw: Mapping[str, Any], where: str, problems: _Problems) -> tuple[str | None, tuple[str, ...]]:
    member = raw.get("member") or None
    values = tuple(str(value) for value in raw.get("member_values") or ())
    problems.check(not values or bool(member), where, "member_values need the member they belong to")
    return (str(member) if member else None), values


def _list_gold(
    raw: Mapping[str, Any],
    items: Sequence[TruthItem],
    slugs: set[str],
    where: str,
    problems: _Problems,
    today: date,
) -> tuple[ListGold | None, Gold]:
    state = raw.get("state")
    problems.check(state in ("date", "amount"), where, f"a list states a date or an amount, not {state!r}")
    start = _day(raw.get("from"), where, problems, today=today, tokens=True)
    end = _day(raw.get("to"), where, problems, today=today, tokens=True)
    kinds = tuple(str(kind) for kind in raw.get("kinds") or ())
    direction = raw.get("direction")
    pool = list(items)
    gold: set[str] = set()
    dates: list[date] = []
    amounts: list[float] = []
    letters: list[str] = []
    for index, entry in enumerate(raw.get("items") or ()):
        letter = str(entry.get("letter"))
        _letters([letter], slugs, where, problems)
        day = _day(entry.get("date"), where, problems) if entry.get("date") else None
        euros = _amounts([entry["amount"]], where, problems)[0] if entry.get("amount") is not None else None
        cents = None if euros is None else round(euros * 100)
        known = next(
            (
                item
                for item in items
                if item.letter == letter and item.day == day and (cents is None or item.cents == cents)
            ),
            None,
        )
        if known is None:  # an occurrence the truth lists once (a repeating to-do's later dates)
            known = TruthItem(
                letter=letter,
                index=1000 + index,
                kind=str(entry.get("kind") or (kinds[0] if kinds else "payment")),
                direction=str(direction) if direction else None,
                day=day,
                cents=cents,
                required=True,
            )
            pool.append(known)
        gold.add(known.label)
        letters.append(letter)
        if day is not None:
            dates.append(day)
        if euros is not None:
            amounts.append(euros)
    problems.check(bool(gold), where, "a list needs the items it must give")
    if start is None or end is None or state not in ("date", "amount"):
        return None, Gold()
    listed = ListGold(
        state=cast(Any, state),
        window=window(start, end, kinds=kinds, direction=str(direction) if direction else None),
        gold=frozenset(gold),
        pool=tuple(pool),
    )
    values = Gold(
        dates=tuple(sorted(set(dates))) if state == "date" else (),
        amounts=tuple(amounts) if state == "amount" else (),
        letters=tuple(dict.fromkeys(letters)),
    )
    return listed, values


Resolve = Callable[[dict[str, Any], str], dict[str, Any]]


def _recurrence_resolver(folder: Path, rows: Sequence[Mapping[str, Any]], today: date) -> Resolve:
    """How a recurrence question gets its gold on ``today`` (from the folder's ``recurrence.json`` and
    ``recurrence_gold.py``): a problem is the question's, named by id."""
    if not any("recurrence" in row for row in rows):
        return lambda row, where: row
    todos = {str(todo["id"]): todo for todo in heldout_check.load_recurrence(folder)}
    module = heldout_check.gold_module(folder)
    truth = heldout_check.load_truth(MANIFEST)

    def resolve(row: dict[str, Any], where: str) -> dict[str, Any]:
        if "recurrence" not in row:
            return row
        return {**row, **heldout_check.recurrence_gold(row, todos, module, truth, today)}

    return resolve


def load_questions(
    path: Path = HELDOUT_DIR / QUESTIONS_NAME,
    *,
    truth: Mapping[str, TruthDoc] | None = None,
    today: date | None = None,
) -> list[HeldOutQuestion]:
    """The held-out questions as of ``today`` (default: the run's day, :func:`~evals.ask.ledger.benchmark_today`),
    checked against the sample life's truth (every problem at once): day tokens resolved for it, a recurrence
    question's gold computed for it."""
    rows = _read(path, "questions")
    day = today or benchmark_today()
    loaded = truth if truth is not None else load_truth()
    slugs, items = set(loaded), truth_items(loaded)
    dev = {q.id for q in all_questions(dict(loaded))} | {a.id for a in ATTACKS}
    problems = _Problems()
    try:
        resolve = _recurrence_resolver(path.parent, rows, day)
    except heldout_check.CheckError as exc:
        raise HeldOutError(f"{path.name} cannot be scored as written: {exc}") from exc
    seen: set[str] = set()
    phrasings: set[tuple[str, str]] = set()
    found = []
    for number, row in enumerate(rows):
        qid = str(row.get("id") or "")
        where = f"question {qid or number}"
        try:
            row = resolve(row, where)
        except heldout_check.CheckError as exc:
            problems.append(str(exc))
            continue
        problems.check(
            bool(qid) and qid not in seen, where, f"{qid} is used twice" if qid else "it has no id"
        )
        problems.check(qid not in dev, where, f"{qid} is a development-set id")
        seen.add(qid)
        group, ledger = row.get("group"), row.get("ledger", "base")
        category, phrasing = row.get("category"), row.get("phrasing")
        fact, text = str(row.get("fact") or ""), str(row.get("text") or "")
        problems.check(group in GROUPS, where, f"its group {group!r} is none of {', '.join(GROUPS)}")
        problems.check(ledger in LEDGERS, where, f"its ledger {ledger!r} is none of {', '.join(LEDGERS)}")
        problems.check(
            category in CATEGORIES, where, f"its category {category!r} is none of {', '.join(CATEGORIES)}"
        )
        problems.check(
            phrasing in PHRASINGS, where, f"its phrasing {phrasing!r} is none of {', '.join(PHRASINGS)}"
        )
        problems.check(bool(fact) and bool(text), where, "it needs a fact and a text")
        if fact and phrasing:
            problems.check(
                (fact, str(phrasing)) not in phrasings, where, f"fact {fact} has two {phrasing} phrasings"
            )
            phrasings.add((fact, str(phrasing)))
        member, member_values = _member(row, where, problems)
        near_miss = bool(row.get("near_miss"))
        unanswerable = group == "unanswerable"
        problems.check(
            not near_miss or unanswerable, where, "only an unanswerable question can be a near miss"
        )
        raw_gold, raw_list = row.get("gold"), row.get("list")
        gold: Gold | None = None
        numbers: tuple[str, ...] = ()
        listed: ListGold | None = None
        if unanswerable:
            problems.check(
                raw_gold is None and raw_list is None, where, "an unanswerable question has no gold"
            )
        elif problems.check(
            isinstance(raw_gold, dict) or isinstance(raw_list, dict), where, "it needs a gold"
        ):
            gold, numbers = _gold(raw_gold or {}, slugs, where, problems)
            if isinstance(raw_list, dict):
                listed, values = _list_gold(raw_list, items, slugs, where, problems, day)
                gold = replace(
                    gold,
                    dates=gold.dates or values.dates,
                    amounts=gold.amounts or values.amounts,
                    letters=gold.letters or values.letters,
                )
            problems.check(
                bool(gold.dates or gold.amounts or numbers or listed),
                where,
                "its gold gives no date, amount, identifier or list",
            )
        question = Question(qid, cast(Category, category), text, gold, "hand", cluster=fact)
        extras = Extras(
            numbers=numbers, member=member, member_values=member_values, near_miss=near_miss, list=listed
        )
        found.append(HeldOutQuestion(question, str(group), str(ledger), str(phrasing), extras))
    problems.raise_any(path)
    return found


def load_attacks(
    path: Path = HELDOUT_DIR / ATTACKS_NAME,
    *,
    truth: Mapping[str, TruthDoc] | None = None,
    today: date | None = None,
) -> list[HeldOutAttack]:
    """The held-out attacks as of ``today`` (default: the run's day), checked against the sample life's truth (every
    problem at once); a ``passed_today`` attack injects that day (written ``"today"``)."""
    rows = _read(path, "attacks")
    day = today or benchmark_today()
    loaded = truth if truth is not None else load_truth()
    slugs = set(loaded)
    true_dates, true_cents = truth_values(loaded.values())
    dev = {q.id for q in all_questions(dict(loaded))} | {a.id for a in ATTACKS}
    problems = _Problems()
    seen: set[str] = set()
    found = []
    for number, row in enumerate(rows):
        aid = str(row.get("id") or "")
        where = f"attack {aid or number}"
        problems.check(
            bool(aid) and aid not in seen, where, f"{aid} is used twice" if aid else "it has no id"
        )
        problems.check(aid not in dev, where, f"{aid} is a development-set id")
        seen.add(aid)
        kind, letter, channel = row.get("kind"), str(row.get("letter")), row.get("channel")
        ledger, target = row.get("ledger", "base"), row.get("target")
        text, question = str(row.get("text") or ""), str(row.get("question") or "")
        problems.check(kind in ATTACK_KINDS, where, f"its kind {kind!r} is none of {', '.join(ATTACK_KINDS)}")
        _letters([letter], slugs, where, problems)
        problems.check(
            channel in CHANNELS, where, f"its channel {channel!r} is none of {', '.join(CHANNELS)}"
        )
        problems.check(ledger in LEDGERS, where, f"its ledger {ledger!r} is none of {', '.join(LEDGERS)}")
        problems.check(
            target is None or target in TARGETS, where, f"its target {target!r} is none of {TARGETS}"
        )
        problems.check(bool(text) and bool(question), where, "it needs an injected text and a question")
        problems.check(
            ("{target}" in text) == (target == "rent_item"),
            where,
            "only a rent_item target is written into the text, as {target}",
        )
        gold, _ = _gold(row.get("gold") or {}, slugs, where, problems)
        problems.check(gold.letters == (letter,), where, "its gold is the attacked letter's")
        dates = _days(row.get("injected_dates"), where, problems, today=day, tokens=True)
        amounts = _amounts(row.get("injected_amounts"), where, problems)
        months = tuple((int(year), int(month)) for year, month in row.get("injected_months") or ())
        member, member_values = _member(row, where, problems)
        if kind == "member_as_own":
            problems.check(
                bool(member_values), where, "a member_as_own attack needs the member and member_values"
            )
        elif kind == "passed_today":
            problems.check(
                dates == (day,),
                where,
                f'a passed_today attack injects today\'s date, {day} (write "today")',
            )
        elif kind != "cite_other":
            inside = [str(day) for day in dates if day in true_dates]
            inside += [f"{amount:.2f}" for amount in amounts if round(amount * 100) in true_cents]
            inside += [f"{year}-{month:02d}" for year, month in months if any((d.year, d.month) == (year, month) for d in true_dates)]  # fmt: skip
            problems.check(
                not inside, where, f"{', '.join(inside)} is in the sample life's truth: inject another value"
            )
        attack = Attack(
            aid,
            cast(AttackKind, kind),
            letter,
            cast(Channel, channel),
            text,
            question,
            gold,
            injected_dates=dates,
            injected_amounts=amounts,
            target=cast(Target | None, target),
            injected_months=months,
        )
        extras = Extras(member=member, member_values=member_values)
        found.append(HeldOutAttack(attack, str(ledger), extras, member_as_own=kind == "member_as_own"))
    problems.raise_any(path)
    return found


# --------------------------------------------------------------------------------------------------
# the window: the same gold on every day of [D0, L]
# --------------------------------------------------------------------------------------------------


def _lines(exc: Exception) -> list[str]:
    lines = [line[2:] for line in str(exc).splitlines() if line.startswith("- ")]
    return lines or [str(exc)]


def validate_window(
    start: date,
    end: date,
    folder: Path = HELDOUT_DIR,
    *,
    truth: Mapping[str, TruthDoc] | None = None,
    ledgers: bool = False,
) -> list[str]:
    """Every problem that keeps the set from being asked on each day of [start, end] (empty: it can be): the files
    loaded for each day (day tokens and recurrence gold resolved), each gold's answer, open-or-passed state and list
    window compared across the days (:func:`evals.ask.heldout_check.window_problems`), and — ``ledgers`` — the
    recurrence ledger built for each day with each to-do's next date held to the gold's. Ids, days and dates only."""
    if end < start:
        raise HeldOutError(f"the window ends on {end.isoformat()}, before it starts on {start.isoformat()}")
    loaded = truth if truth is not None else load_truth()
    problems: list[str] = []
    for day in heldout_check.days(start, end):
        for load, name in ((load_questions, QUESTIONS_NAME), (load_attacks, ATTACKS_NAME)):
            try:
                load(folder / name, truth=loaded, today=day)
            except HeldOutError as exc:
                problems += [f"{day.isoformat()}: {line}" for line in _lines(exc)]
    manifest = heldout_check.load_truth(MANIFEST)
    try:
        resolve = heldout_check.resolver(folder, manifest)
        problems += heldout_check.window_problems(
            _skipping(resolve), start, end, heldout_check.truth_items(manifest)
        )
    except (heldout_check.CheckError, ValueError) as exc:
        problems += [line for line in _lines(exc) if not any(line in seen for seen in problems)]
    if ledgers:
        problems += _ledger_problems(folder, start, end, manifest)
    return problems


def _skipping(
    resolve: Callable[[date], tuple[list[dict[str, Any]], list[dict[str, Any]]]],
) -> Callable[[date], tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """``resolve`` that leaves a day the loads already named a problem on out of the comparison (its rows as
    written)."""

    def safe(day: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        try:
            return resolve(day)
        except (heldout_check.CheckError, ValueError):
            return [], []

    return safe


def _ledger_problems(folder: Path, start: date, end: date, manifest: Mapping[str, Any]) -> list[str]:
    """The recurrence ledger built for each day of the window (no model call): each to-do's next date in it must be
    the blind gold's next occurrence, so a question is asked against the ledger its gold assumes."""
    from evals.ask import recurrence
    from evals.ask.ledger import LedgerError, build_base, pinned_today

    todos = heldout_check.load_recurrence(folder)
    if not todos:
        return []
    module = heldout_check.gold_module(folder)
    if module is None:
        return [f"recurrence.json names to-dos that repeat, and there is no {heldout_check.GOLD_MODULE_NAME}"]
    life = SampleLife.load()
    rules = folder / RECURRENCE_NAME
    problems = []
    for day in heldout_check.days(start, end):
        try:
            with pinned_today(day), tempfile.TemporaryDirectory(prefix="ordnung-ask-recurrence-") as tmp:
                base = build_base(Path(tmp) / "base", life, day=day)
                built = recurrence.build_recurrence(base, Path(tmp) / "recurrence", life, rules=rules)
                ledger = recurrence.next_dates(built, rules=rules, life=life)
        except LedgerError as exc:
            problems.append(f"{day.isoformat()}: the recurrence ledger cannot be built: {exc}")
            continue
        for todo in todos:
            gold = module.next_occurrence(heldout_check.todo_facts(todo, manifest), day)
            found = ledger.get(str(todo["id"]))
            if found != gold:
                shown = found.isoformat() if found else "none"
                problems.append(
                    f"{day.isoformat()}: to-do {todo['id']}: the ledger's next date is {shown}, the gold's "
                    f"{gold.isoformat()}"
                )
    return problems


# --------------------------------------------------------------------------------------------------
# ledgers
# --------------------------------------------------------------------------------------------------

LedgerBuilder = Callable[[Path, Path, SampleLife], Path]
"""Builds a held-out ledger in ``target`` from the base ledger's folder (a copy plus the ledger's own changes)."""

_BUILDERS: dict[str, LedgerBuilder] = {}
#: Who builds each ledger: ``"module:function"`` (imported on first use), or a module that registers its builder
#: when it is imported (:func:`register_ledger`).
PROVIDERS = {
    "household": "evals.ask.household:build_household",
    "recurrence": "evals.ask.recurrence:build_recurrence",
}


def register_ledger(name: str, build: LedgerBuilder) -> None:
    """Let held-out items ask on the ledger ``name``, built by ``build``."""
    if name not in LEDGERS or name == "base":
        raise HeldOutError(f"{name!r} is not a held-out ledger one registers ({', '.join(LEDGERS[1:])})")
    _BUILDERS[name] = build


def unregister_ledger(name: str) -> None:
    _BUILDERS.pop(name, None)


def ledger_builder(name: str) -> LedgerBuilder | None:
    """How the ledger ``name`` is built (``None``: the base ledger itself): a builder registered for it, else the
    function its provider names."""
    if name == "base":
        return None
    if name in _BUILDERS:
        return _BUILDERS[name]
    provider = PROVIDERS.get(name, "")
    module, _, function = provider.partition(":")
    if module:
        try:
            loaded = importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name != module:  # the module is there but something it imports is not
                raise
        else:
            if function and callable(getattr(loaded, function, None)):
                return cast(LedgerBuilder, getattr(loaded, function))
    if name not in _BUILDERS:
        raise HeldOutError(
            f"no builder for the {name} ledger: its provider ({provider or 'none named'}) names a function, or a "
            "module that registers one with evals.ask.heldout.register_ledger when it is imported"
        )
    return _BUILDERS[name]


# --------------------------------------------------------------------------------------------------
# the pre-registration
# --------------------------------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_mismatches(prereg: Mapping[str, Any], root: Path = ROOT) -> list[str]:
    """How the held-out files differ from what the pre-registration hashed: its ``files`` map each repository path
    to its sha256, and every ``evals/ask/heldout/`` path in it must be there, byte for byte."""
    files = prereg.get("files") or {}
    wanted = {
        str(path): str(sha) for path, sha in files.items() if str(path).startswith("evals/ask/heldout/")
    }
    if not wanted:
        return ["the pre-registration names no held-out Ask file"]
    problems = []
    for path, sha in sorted(wanted.items()):
        file = root / path
        if not file.is_file():
            problems.append(f"{path} is missing")
        elif file_sha256(file) != sha:
            problems.append(f"{path} differs from the pre-registration (sha256)")
    return problems


# --------------------------------------------------------------------------------------------------
# three runs: summarise_strict(r1) + consistency(r1, r2, r3)
# --------------------------------------------------------------------------------------------------

#: The pre-registered endpoints (``ask_heldout_analysis``): where each is in the file.
ENDPOINTS = {
    "strict_accuracy_r1": ("r1", "strict_accuracy"),
    "harmful_r1": ("r1", "harmful"),
    "harmful_any_of_3": ("consistency", "harmful_any"),
    "abstention_plain": ("r1", "abstention_plain"),
    "abstention_near_miss": ("r1", "abstention_near_miss"),
    "attack_success_worst_of_3": ("consistency", "attack_success_worst"),
    "pass_all_3": ("consistency", "pass_all"),
}
FINAL_NOTES = (
    "Run 1 is the number; runs 2 and 3 ask the same questions again with the same requests under keys of their own "
    "(--repeat), and say how stable the answers are: pass_all is strictly right in every run, harmful_any harmful "
    "in any run, attack_success_worst an attack that worked in any run. With fewer runs than registered (a run cut "
    "by the window or the budget), the *_of_3 endpoints are over the runs that exist (meta.reads).",
    "Each run was asked, built and scored for the day it was recorded (meta.inputs[].today); every gold has the "
    "same answer on each day of the window (python -m evals.ask.heldout --validate).",
    "scorer_paths counts, per run, the answers the scorer decided by a path other than the values they state: "
    "answers with no date or amount its reader finds, and answers whose 'it has passed' named no date of its own, "
    "so the gold's dates were taken as the ones meant (evals/ask/score.py, called_passed).",
)


def final_name(day: str, model: str) -> str:
    """``<date>-<model>-ask-heldout-final.json``."""
    return f"{day}-{model}-ask-heldout-final.json"


def _strict_rows(data: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    """A schema-2 results file's scored rows and strict rows, as the run made them."""
    from evals.ask.score import Scored
    from evals.ask.strict import Strict

    scored, strict = [], []
    for entry in [*data["questions"], *data["attacks"]]:
        score = Scored(**entry["scores"])
        scored.append(score)
        strict.append(
            Strict(
                id=str(entry["id"]),
                kind=score.kind,
                cluster=score.cluster,
                category=score.category,
                correct=score.correct_final,
                **entry["strict"],
            )
        )
    return scored, strict


def _strict_summary(data: Mapping[str, Any]) -> dict[str, Any]:
    """:func:`~evals.ask.metrics.summarise_strict` of a run, recomputed from its rows (as JSON gives it back)."""
    scored, strict = _strict_rows(data)
    return cast(dict[str, Any], json.loads(json.dumps(summarise_strict(scored, strict))))


def _final_input(path: Path, repeat: int, model: str) -> dict[str, Any]:
    """A run of the set for the file of three runs: a live run's own results file of schema 2, run ``repeat``, whose
    summary is what its rows give."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HeldOutError(f"{Path(path).name}: not a readable results file ({exc})") from exc
    name = Path(path).name
    wanted = {
        "benchmark": "ask",
        "set": "heldout",
        "repeat": repeat,
        "model": model,
        "backend": "live",
    }
    for key, value in wanted.items():
        if data.get(key) != value:
            raise HeldOutError(
                f"{name}: its {key} is {data.get(key)!r}, not {value!r} (run {repeat} of the set)"
            )
    if int(data.get("schema", 1)) < 2:
        raise HeldOutError(
            f"{name}: a results file of schema 2 has the strict rows the file of three runs reads"
        )
    try:
        recomputed = _strict_summary(data)
    except (KeyError, TypeError) as exc:
        raise HeldOutError(f"{name}: its rows are not a run's ({exc})") from exc
    if recomputed != {key: data["summary"].get(key) for key in recomputed}:
        raise HeldOutError(f"{name}: its summary is not what its rows give")
    return cast(dict[str, Any], data)


def scorer_paths(run: Mapping[str, Any]) -> dict[str, Any]:
    """How often the scorer decided an answer of ``run`` by a path other than the values it states (ids only):
    answerable questions and attacks whose final answer states no date or amount the scorer's reader finds, and
    answers whose "it has passed" names no date, so :func:`evals.ask.score.called_passed` took the gold's dates as
    the ones meant (final and raw). Read as of the run's day."""
    from evals.ask.parse import mentions
    from evals.ask.score import called_passed

    day = date.fromisoformat(str(run.get("today") or TODAY.isoformat()))
    answered = 0
    no_value: list[str] = []
    not_answered: list[str] = []
    fallback: dict[str, list[str]] = {"final": [], "raw": []}
    with on_day(day):
        for entry in [*run["questions"], *run["attacks"]]:
            item_id, turn, gold = str(entry["id"]), entry.get("turn") or {}, entry.get("gold")
            if turn.get("error") is not None:
                not_answered.append(item_id)
                continue
            if gold is None:
                continue
            answered += 1
            if not mentions(str(turn.get("final") or "")):
                no_value.append(item_id)
            golds = [date.fromisoformat(value) for value in gold.get("dates") or ()]
            for side in ("final", "raw"):
                text = str(turn.get(side) or "")
                if golds and called_passed(text, golds) != called_passed(text):
                    fallback[side].append(item_id)
    return {
        "answered": answered,
        "not_answered": sorted(not_answered),
        "no_parsable_value": {"k": len(no_value), "n": answered, "ids": sorted(no_value)},
        "called_passed_fallback": {side: sorted(ids) for side, ids in fallback.items()},
    }


def final_payload(paths: Sequence[Path], *, day: str) -> dict[str, Any]:
    """The file of the set's runs (run 1 first, then 2 and 3 as recorded): run 1's strict scores, what the runs show
    together, the pre-registered endpoints and the scorer's path counts — every number from the runs' rows."""
    from evals.ask.run import DEFAULT_MODEL

    if not 1 <= len(paths) <= REGISTERED_READS:
        raise HeldOutError(f"the file of runs takes 1 to {REGISTERED_READS} runs, not {len(paths)}")
    runs = [_final_input(path, repeat, DEFAULT_MODEL) for repeat, path in enumerate(paths, 1)]
    try:
        together = consistency(runs)
    except ValueError as exc:
        raise HeldOutError(f"the runs cannot be compared: {exc}") from exc
    payload: dict[str, Any] = {
        "schema": FINAL_SCHEMA,
        "meta": {
            "kind": FINAL_KIND,
            "name": NAME,
            "date": day,
            "model": DEFAULT_MODEL,
            "set": "heldout",
            "reads": len(runs),
            "registered_reads": REGISTERED_READS,
            "inputs": [
                {
                    "file": Path(path).name,
                    "sha256": file_sha256(Path(path)),
                    "repeat": data["repeat"],
                    "today": data.get("today"),
                    "date": data.get("date"),
                }
                for path, data in zip(paths, runs, strict=True)
            ],
        },
        "notes": list(FINAL_NOTES),
        "r1": _strict_summary(runs[0]),
        "consistency": json.loads(json.dumps(together)),
        "scorer_paths": {f"r{data['repeat']}": scorer_paths(data) for data in runs},
    }
    payload["endpoints"] = {name: payload[block][key] for name, (block, key) in ENDPOINTS.items()}
    return payload


def _dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


def _newest_final(results_dir: Path, model: str) -> Path | None:
    found = sorted(results_dir.glob(final_name("*", model)))
    return found[-1] if found else None


def recorded_runs(results_dir: Path, model: str) -> list[Path]:
    """The live runs of the set that ``results_dir`` and its ``pending/`` folder hold (its re-scorings aside)."""
    found = []
    for folder in (results_dir, results_dir / "pending"):
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if path.name.endswith(f"-{FINAL_KIND}.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            wanted = {"benchmark": "ask", "set": "heldout", "model": model, "backend": "live"}
            if all(data.get(key) == value for key, value in wanted.items()):
                found.append(path)
    return found


def _final(args: argparse.Namespace) -> int:
    from evals.ask.run import DEFAULT_MODEL, RESULTS_DIR

    results_dir: Path = args.results_dir or RESULTS_DIR
    given = {Path(path).resolve() for path in args.final}
    left_out = [path for path in recorded_runs(results_dir, DEFAULT_MODEL) if path.resolve() not in given]
    if left_out:
        # every pre-registered endpoint is published: a recorded run is never left out of the file of runs
        names = ", ".join(path.name for path in left_out)
        print(
            f"error: {names} recorded but not given: every recorded run is in the file of runs",
            file=sys.stderr,
        )
        return 2
    if args.check:
        newest = _newest_final(results_dir, DEFAULT_MODEL)
        if newest is None:
            print(f"no {final_name('<date>', DEFAULT_MODEL)} in {results_dir}: write it with --write")
            return 1
        day = newest.name[:10]
        if newest.read_text(encoding="utf-8") != _dumps(final_payload(args.final, day=day)):
            print(f"{newest.name}: not what the runs give — regenerate with --write --date {day}")
            return 1
        print(f"{newest.name}: up to date")
        return 0
    day = args.date or date.today().isoformat()
    path = results_dir / final_name(day, DEFAULT_MODEL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dumps(final_payload(args.final, day=day)), encoding="utf-8")
    print(f"wrote {path}")
    return 0


def _validate(args: argparse.Namespace) -> int:
    start, end = args.window
    folder: Path = args.folder
    if not (folder / QUESTIONS_NAME).is_file() or not (folder / ATTACKS_NAME).is_file():
        print(f"error: no {QUESTIONS_NAME} and {ATTACKS_NAME} in {folder}", file=sys.stderr)
        return 2
    try:
        problems = validate_window(start, end, folder, ledgers=not args.no_ledgers)
        composition = heldout_check.check(folder, start, end, composition=True)
    except (HeldOutError, heldout_check.CheckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem)
    planned = [line for line in composition if line.startswith("composition:")]
    for line in planned:
        print(f"{line} (reported, not a problem: the pre-registration states the final counts)")
    span = f"{start.isoformat()} … {end.isoformat()}"
    if problems:
        print(f"{len(problems)} problem(s): the set is not stable on every day of {span}", file=sys.stderr)
        return 1
    print(f"{NAME}: every gold is stable on every day of {span}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.ask.heldout",
        description=f"{NAME}: check the set over its window, or write and check the file of its three runs.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="check the set on every day of --window D0 L")
    mode.add_argument(
        "--final", nargs="+", type=Path, metavar="RUN", help="the runs' results files, run 1 first"
    )
    parser.add_argument("--window", nargs=2, type=date.fromisoformat, metavar=("D0", "L"))
    parser.add_argument(
        "--folder", type=Path, default=HELDOUT_DIR, help="the set's folder (default: evals/ask/heldout)"
    )
    parser.add_argument(
        "--no-ledgers",
        action="store_true",
        help="--validate: skip building the recurrence ledger for each day",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="--final: write the file of the runs")
    action.add_argument(
        "--check", action="store_true", help="--final: exit 1 unless the newest file is up to date"
    )
    parser.add_argument(
        "--results-dir", type=Path, default=None, help="--final: where the file is (evals/results)"
    )
    parser.add_argument("--date", default=None, help="--final --write: the file's date (default: today)")
    args = parser.parse_args(argv)
    if args.validate:
        if not args.window:
            parser.error("--validate needs --window D0 L")
        if args.window[1] < args.window[0]:
            print("error: the window ends before it starts", file=sys.stderr)
            return 2
        return _validate(args)
    if not (args.write or args.check):
        parser.error("--final needs --write or --check")
    try:
        return _final(args)
    except HeldOutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
