"""The self-check of "Ask: new questions on the demo household" — the standard library only.

The set's writer runs it next to the sample life's files, with no other code at hand::

    python -m evals.ask.heldout_check --window <D0> <L>

It reads ``questions.json``, ``attacks.json`` and ``recurrence.json`` in ``evals/ask/heldout/`` (``SCHEMA.md`` there
describes them) and checks their shape and vocabulary, the ids (``ho-``, each once), the three phrasings of every
core fact, at most four attacks per letter, injected values outside the sample life's truth, the composition the set
was planned with (``--no-composition`` skips it), and that every gold has the same answer and the same open-or-passed
state on each day from D0 to L. It prints ids, days and counts, never a question's words.

Two more uses, outside the writer's sandbox: ``--strip-gold`` writes the questions without their gold for a blind
second answerer (``questions-blind.json``), and ``--blind-compare REPLIES`` compares that answerer's replies with the
gold, value by value, and prints the agreement per category (writing the ids that disagree or got no reply).

The loader of the set (``evals/ask/heldout.py``) reads the same files with the same vocabulary; the day tokens, the
window check and the recurrence gold live here, so both use one reading of them.
"""

from __future__ import annotations

import argparse
import ast
import calendar
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

NAME = "Ask: new questions on the demo household"
SCHEMA = "ask-heldout/1"
RECURRENCE_SCHEMA = "ask-heldout-recurrence/1"
BLIND_SCHEMA = "ask-heldout-blind/1"
REPLIES_SCHEMA = "ask-heldout-replies/1"
QUESTIONS_NAME = "questions.json"
ATTACKS_NAME = "attacks.json"
RECURRENCE_NAME = "recurrence.json"
GOLD_MODULE_NAME = "recurrence_gold.py"
HELDOUT_DIR = Path(__file__).resolve().parent / "heldout"
ROOT = Path(__file__).resolve().parents[2]

ID_PREFIX = "ho-"
GROUPS = ("core", "household", "recurrence", "unanswerable")
LEDGERS = ("base", "household", "recurrence")
PHRASINGS = ("en", "en-paraphrase", "de")
CATEGORIES = ("deadline", "payment", "contract", "cross_letter", "unanswerable", "household", "recurrence")
ATTACK_KINDS = (
    "moved_date",
    "changed_amount",
    "no_deadline",
    "cite_other",
    "pay_scam",
    "passed_today",
    "member_as_own",
)
CHANNELS = ("page", "summary")
TARGETS = ("rent_item", "rent_contract", "tax_objection_item")
UNITS = ("days", "weeks", "months", "years")
#: What a recurrence question asks for: the next occurrence, the occurrences in a window, a year's total.
ASKS = ("next", "window", "year_total")
MAX_ATTACKS_PER_LETTER = 4
#: The set as planned: 104 questions (core 20 facts × 3 phrasings, household 16, recurrence 12, unanswerable 16 of
#: which 8 near misses) and 60 attacks on at least 15 letters, 6 of them a member's value given as the person's own.
COMPOSITION = {
    "questions": 104,
    "core": 60,
    "household": 16,
    "recurrence": 12,
    "unanswerable": 16,
    "near_miss": 8,
    "attacks": 60,
    "attack_letters": 15,
    "member_as_own": 6,
}
#: Fields of a question or attack that give its answer away: none of them reaches the blind second answerer.
GOLD_FIELDS = (
    "gold",
    "list",
    "near_miss",
    "member",
    "member_values",
    "group",
    "category",
    "fact",
    "recurrence",
)

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_TOKEN = re.compile(r"today(?:\+(\d{1,4}))?")
_MONTHS = {
    **dict.fromkeys(("january", "jan", "januar", "jänner"), 1),
    **dict.fromkeys(("february", "feb", "februar"), 2),
    **dict.fromkeys(("march", "mar", "märz", "maerz", "mär"), 3),
    **dict.fromkeys(("april", "apr"), 4),
    **dict.fromkeys(("may", "mai"), 5),
    **dict.fromkeys(("june", "jun", "juni"), 6),
    **dict.fromkeys(("july", "jul", "juli"), 7),
    **dict.fromkeys(("august", "aug"), 8),
    **dict.fromkeys(("september", "sept", "sep"), 9),
    **dict.fromkeys(("october", "oct", "oktober", "okt"), 10),
    **dict.fromkeys(("november", "nov"), 11),
    **dict.fromkeys(("december", "dec", "dezember", "dez"), 12),
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATES = re.compile(
    rf"""
      (?<!\d)(?P<iy>\d{{4}})-(?P<im>\d{{1,2}})-(?P<id>\d{{1,2}})(?!\d)
    | (?<![\d.])(?P<dd>\d{{1,2}})\.\s?(?P<dm>\d{{1,2}})\.(?:\s?(?P<dy>\d{{4}})(?!\d))?
    | (?<!\d)(?P<hd>\d{{1,2}})-(?P<hm>\d{{1,2}})-(?P<hy>\d{{4}})(?!\d)
    | (?<!\d)(?P<wd>\d{{1,2}})(?:st|nd|rd|th)?\.?\s+(?:of\s+)?(?P<wm>{_MONTH})\b\.?(?:,?\s+(?P<wy>\d{{4}}))?
    | \b(?P<mm>{_MONTH})\b\.?\s+(?P<md>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<my>\d{{4}}))?
    | \b(?:end\s+of\s+|ende\s+)?(?P<em>{_MONTH})\b\.?,?\s+(?P<ey>\d{{4}})
    """,
    re.IGNORECASE | re.VERBOSE,
)
_AMOUNTS = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,\s]\d{3})*|\d+)(?:[.,](\d{1,2}))?(?![\d])")
_AMOUNT_FIELDS = frozenset({"value", "amount", "cost_amount", "old_amount", "new_amount"})


class CheckError(ValueError):
    """The set cannot be read as written (the message lists every problem)."""


# --------------------------------------------------------------------------------------------------
# days
# --------------------------------------------------------------------------------------------------


def is_token(value: object) -> bool:
    """Whether ``value`` is a day token: ``"today"`` or ``"today+N"``."""
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def resolve_day(value: object, today: date) -> date:
    """``"YYYY-MM-DD"`` as written, ``"today"`` as ``today`` and ``"today+N"`` as N days after it (the day the set is
    asked on: its recording day); anything else raises :class:`ValueError`."""
    text = str(value)
    match = _TOKEN.fullmatch(text)
    if match:
        return today + timedelta(days=int(match.group(1) or 0))
    if _ISO.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    raise ValueError(f"{value!r} is no ISO date (YYYY-MM-DD) and no day token (today, today+N)")


def days(start: date, end: date) -> list[date]:
    """Every day from ``start`` to ``end``, both included."""
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


# --------------------------------------------------------------------------------------------------
# the sample life's truth (its manifest, read without any other code)
# --------------------------------------------------------------------------------------------------


def samples_manifest(root: Path | None = None) -> Path:
    """The sample life's ``manifest.json`` (``src/<package>/demo/samples/``) under ``root``."""
    found = sorted((root or ROOT).glob("src/*/demo/samples/manifest.json"))
    if len(found) != 1:
        raise CheckError(
            f"found {len(found)} sample-life manifests under {root or ROOT}: give one with --samples"
        )
    return found[0]


def load_truth(manifest: Path) -> dict[str, dict[str, Any]]:
    """Each letter's truth, by its slug (and the sample life's own today as ``"__today__"``)."""
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    truth = {str(doc["slug"]): dict(doc["truth"]) for doc in data["documents"]}
    truth["__today__"] = {"simulated_today": data.get("simulated_today")}
    return truth


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _dates_in(text: str, years: Sequence[int]) -> set[date]:
    """Every date ``text`` names; one written without a year (``19.09.``, ``21 October``) in each of ``years``."""
    found: set[date] = set()

    def add(year: str | None, month: int, day: int) -> None:
        for each in [int(year)] if year else years:
            if (found_day := _date(each, month, day)) is not None:
                found.add(found_day)

    for m in _DATES.finditer(text):
        if m["iy"]:
            add(m["iy"], int(m["im"]), int(m["id"]))
        elif m["dd"]:
            add(m["dy"], int(m["dm"]), int(m["dd"]))
        elif m["hd"]:
            add(m["hy"], int(m["hm"]), int(m["hd"]))
        elif m["wd"]:
            add(m["wy"], _MONTHS[m["wm"].lower()], int(m["wd"]))
        elif m["mm"]:
            add(m["my"], _MONTHS[m["mm"].lower()], int(m["md"]))
        else:
            year, month = int(m["ey"]), _MONTHS[m["em"].lower()]
            add(m["ey"], month, calendar.monthrange(year, month)[1])
            add(m["ey"], month, 1)
    return found


def _cents_in(text: str) -> set[int]:
    found: set[int] = set()
    for m in _AMOUNTS.finditer(text):
        whole = re.sub(r"[.,\s]", "", m.group(1))
        cents = (m.group(2) or "0").ljust(2, "0")
        found.add(int(whole) * 100 + int(cents))
    return found


def truth_values(truth: Mapping[str, Mapping[str, Any]]) -> tuple[set[date], set[int]]:
    """Every date and amount (in cents) the truth states, read generously: its fields, and every date or number its
    words name, so a value this lets through is outside the truth for the loader's own reader too."""
    dates: set[date] = set()
    cents: set[int] = set()
    today = (truth.get("__today__") or {}).get("simulated_today")
    year = date.fromisoformat(str(today)).year if today else date.today().year
    years = (year - 1, year, year + 1)

    def walk(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str):
            dates.update(_dates_in(value, years))
            cents.update(_cents_in(value))
        elif isinstance(value, int | float) and not isinstance(value, bool) and key in _AMOUNT_FIELDS:
            cents.add(round(float(value) * 100))

    for slug, doc in truth.items():
        walk(doc)
        if slug == "__today__" and doc.get("simulated_today"):
            dates.add(date.fromisoformat(str(doc["simulated_today"])))
    return dates, cents


def truth_items(truth: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every to-do of the truth: its letter, index (``<letter>#<index>``), kind, direction, day and cents."""
    found = []
    for slug, doc in truth.items():
        for index, item in enumerate(doc.get("items") or ()):
            due, amount = item.get("expected_due"), item.get("amount")
            found.append(
                {
                    "letter": slug,
                    "index": index,
                    "label": f"{slug}#{index}",
                    "kind": item.get("kind"),
                    "direction": item.get("direction"),
                    "day": date.fromisoformat(due) if due else None,
                    "cents": None if amount is None else round(float(amount) * 100),
                    "amount": amount,
                    "repeats": bool(item.get("recurrence")),
                }
            )
    return found


# --------------------------------------------------------------------------------------------------
# the files
# --------------------------------------------------------------------------------------------------


def _rows(path: Path, key: str, schema: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise CheckError(f"no {path.name} in {path.parent}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CheckError(f"{path.name} is not JSON ({exc})") from exc
    if not isinstance(data, dict) or data.get("schema") != schema or not isinstance(data.get(key), list):
        raise CheckError(f"{path.name} is no file of schema {schema} with a list of {key}")
    rows: list[dict[str, Any]] = data[key]
    if not all(isinstance(row, dict) for row in rows):
        raise CheckError(f"{path.name}: every one of its {key} is an object")
    return rows


def load_rows(folder: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The questions and attacks as written."""
    return (
        _rows(folder / QUESTIONS_NAME, "questions", SCHEMA),
        _rows(folder / ATTACKS_NAME, "attacks", SCHEMA),
    )


def _rule_problems(rule: Any, where: str) -> list[str]:
    if not isinstance(rule, dict):
        return [f"{where}: its rule is an object"]
    problems = [f"{where}: its rule has no field {key}" for key in sorted(set(rule) - {"interval", "unit", "day_of_month", "working_day"})]  # fmt: skip
    interval, unit = rule.get("interval", 1), rule.get("unit", "months")
    if not (isinstance(interval, int) and not isinstance(interval, bool) and 1 <= interval <= 120):
        problems.append(
            f"{where}: its rule repeats every 1 to 120 days, weeks, months or years, not {interval!r}"
        )
    if unit not in UNITS:
        problems.append(f"{where}: its rule's unit {unit!r} is none of {', '.join(UNITS)}")
    day, working = rule.get("day_of_month"), rule.get("working_day")
    if day is not None and not (isinstance(day, int) and 1 <= day <= 31):
        problems.append(f"{where}: its rule's day_of_month is 1 to 31, not {day!r}")
    if working is not None and not (isinstance(working, int) and (working == -1 or 1 <= working <= 10)):
        problems.append(f"{where}: its rule's working_day is 1 to 10 or -1 (the last), not {working!r}")
    if (day is not None or working is not None) and unit in ("days", "weeks"):
        problems.append(f"{where}: a rule in {unit} has no day of the month and no working day")
    return problems


def load_recurrence_file(path: Path) -> list[dict[str, Any]]:
    """The to-dos that repeat in the recurrence ledger, as ``recurrence.json`` gives them (every problem at once)."""
    todos = _rows(path, "todos", RECURRENCE_SCHEMA)
    problems: list[str] = []
    seen: set[str] = set()
    for number, todo in enumerate(todos):
        tid = str(todo.get("id") or "")
        where = f"to-do {tid or number}"
        if not tid or tid in seen:
            problems.append(f"{where}: {tid} is used twice" if tid else f"{where}: it has no id")
        seen.add(tid)
        if not isinstance(todo.get("letter"), str) or not todo.get("letter"):
            problems.append(f"{where}: it names the letter its to-do belongs to")
        item = todo.get("item")
        if not (isinstance(item, int) and not isinstance(item, bool) and item >= 0):
            problems.append(f"{where}: its item is the to-do's place in its letter's truth (0, 1, …)")
        problems += _rule_problems(todo.get("rule"), where)
        try:
            resolve_day(todo.get("first"), date.min)
            if is_token(todo.get("first")):
                raise ValueError(todo.get("first"))
        except ValueError:
            problems.append(f"{where}: its first occurrence is an ISO date (YYYY-MM-DD)")
    if problems:
        raise CheckError(f"{path.name} cannot be read as written:\n- " + "\n- ".join(problems))
    return todos


def load_recurrence(folder: Path) -> list[dict[str, Any]]:
    """The folder's ``recurrence.json`` (none: no to-do repeats)."""
    path = folder / RECURRENCE_NAME
    return load_recurrence_file(path) if path.is_file() else []


def gold_module(folder: Path) -> ModuleType | None:
    """The blind writer's ``recurrence_gold.py`` in ``folder`` (``None`` when there is none), loaded after checking
    that it imports the standard library only."""
    path = folder / GOLD_MODULE_NAME
    if not path.is_file():
        return None
    source = path.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add("." if node.level else (node.module or "").split(".")[0])
    outside = sorted(imported - set(sys.stdlib_module_names) - {"__future__"})
    if outside:
        raise CheckError(
            f"{GOLD_MODULE_NAME} imports {', '.join(outside)}: it uses the standard library only"
        )
    name = "_recurrence_gold_" + hashlib.sha256(source.encode()).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - a .py file always has a loader
        raise CheckError(f"{GOLD_MODULE_NAME} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for function in ("next_occurrence", "occurrences", "year_total"):
        if not callable(getattr(module, function, None)):
            raise CheckError(f"{GOLD_MODULE_NAME} has no function {function}")
    return module


def todo_facts(todo: Mapping[str, Any], truth: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """A recurrence.json to-do with its truth item's kind, amount and direction added (what the gold functions
    get)."""
    letter, index = str(todo["letter"]), int(todo["item"])
    items = (truth.get(letter) or {}).get("items") or []
    if letter not in truth or letter == "__today__":
        raise CheckError(f"to-do {todo['id']}: no letter of the sample life is called {letter}")
    if not 0 <= index < len(items):
        raise CheckError(f"to-do {todo['id']}: {letter} has no truth item {index}")
    item = items[index]
    return {
        **todo,
        "kind": item.get("kind"),
        "amount": item.get("amount"),
        "direction": item.get("direction"),
    }


def recurrence_gold(
    row: Mapping[str, Any],
    todos: Mapping[str, Mapping[str, Any]],
    module: ModuleType | None,
    truth: Mapping[str, Mapping[str, Any]],
    today: date,
) -> dict[str, Any]:
    """The ``gold`` and ``list`` of a recurrence question on ``today``, from ``recurrence_gold.py`` (raises
    :class:`CheckError` naming the question)."""
    where = f"question {row.get('id')}"
    spec = row.get("recurrence")
    if not isinstance(spec, dict):
        raise CheckError(f"{where}: its recurrence is an object naming the to-do and what it asks")
    if row.get("gold") is not None or row.get("list") is not None:
        raise CheckError(f"{where}: a recurrence question's gold is computed: leave gold and list null")
    if module is None:
        raise CheckError(f"{where}: a recurrence question needs {GOLD_MODULE_NAME} beside the questions")
    todo = todos.get(str(spec.get("todo")))
    if todo is None:
        raise CheckError(f"{where}: recurrence.json has no to-do {spec.get('todo')}")
    facts = todo_facts(todo, truth)
    letter, ask = str(facts["letter"]), spec.get("ask")
    amount = facts.get("amount")
    try:
        if ask == "next":
            day = module.next_occurrence(facts, today)
            amounts = [amount] if spec.get("with_amount") and amount is not None else []
            gold = {"dates": [day.isoformat()], "amounts": amounts, "letters": [letter], "related": []}
            return {"gold": gold, "list": None}
        if ask == "window":
            start, end = resolve_day(spec.get("from"), today), resolve_day(spec.get("to"), today)
            occurrences = module.occurrences(facts, start, end)
            listed = {
                "state": spec.get("state", "date"),
                "from": start.isoformat(),
                "to": end.isoformat(),
                "kinds": [facts["kind"]],
                "direction": facts.get("direction"),
                "items": [
                    {"letter": letter, "date": day.isoformat(), "amount": amount} for day in occurrences
                ],
            }
            return {"gold": {"letters": [letter], "related": []}, "list": listed}
        if ask == "year_total":
            total = round(float(module.year_total(facts, int(spec["year"]))), 2)
            return {"gold": {"amounts": [total], "letters": [letter], "related": []}, "list": None}
    except CheckError:
        raise
    except Exception as exc:  # the writer's module failed: name the question, not its words
        raise CheckError(f"{where}: {GOLD_MODULE_NAME} failed ({type(exc).__name__}: {exc})") from exc
    raise CheckError(f"{where}: its ask {ask!r} is none of {', '.join(ASKS)}")


# --------------------------------------------------------------------------------------------------
# the window: the same answer and state on every day of [D0, L]
# --------------------------------------------------------------------------------------------------


Signature = dict[str, Any]


def _fixed(values: Iterable[Any] | None) -> list[str]:
    return sorted(str(value) for value in values or ())


def signature(row: Mapping[str, Any], items: Sequence[Mapping[str, Any]], today: date) -> Signature:
    """What a gold says on ``today`` — its answer, the open-or-passed state of each of its dates (and of the to-dos
    its amounts belong to), and for a list the truth items inside its window — so two days can be compared."""
    gold, listed = row.get("gold"), row.get("list")
    if gold is None and listed is None:
        return {"answer": None}
    gold = gold or {}
    dates = _fixed(gold.get("dates"))
    cents = sorted(round(float(value) * 100) for value in gold.get("amounts") or ())
    letters = set(gold.get("letters") or ())
    found: Signature = {
        "answer": [dates, cents, _fixed(gold.get("numbers")), sorted(letters)],
        "open-or-passed state": [
            [day, date.fromisoformat(day) >= today] for day in dates if _ISO.fullmatch(day)
        ],
    }
    owners = [
        [item["label"], item["day"] >= today]
        for item in items
        if item["letter"] in letters and item["cents"] in cents and item["day"] is not None
    ]
    found["open-or-passed state"] += sorted(owners)
    if isinstance(listed, dict):
        start, end = resolve_day(listed.get("from"), today), resolve_day(listed.get("to"), today)
        kinds, direction = set(listed.get("kinds") or ()), listed.get("direction")
        chosen = [
            [str(entry.get("letter")), str(entry.get("date")), entry.get("amount")]
            for entry in listed.get("items") or ()
        ]
        inside = sorted(
            item["label"]
            for item in items
            if item["day"] is not None
            and start <= item["day"] <= end
            and (not kinds or item["kind"] in kinds)
            and (direction is None or item["direction"] == direction)
        )
        found["answer"].append(sorted(chosen, key=str))
        found["list window"] = inside
        found["open-or-passed state"] += [
            [str(entry[1]), str(entry[1]) >= today.isoformat()] for entry in chosen
        ]
    return found


def window_problems(
    resolve: Callable[[date], tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    start: date,
    end: date,
    items: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Each gold whose answer, open-or-passed state or list window on some day of [start, end] is not what it is on
    ``start``: named by id, what changed and the first day it differs. ``resolve(day)``: the questions and attacks
    with their day tokens and recurrence gold resolved for that day."""
    first: dict[str, Signature] = {}
    problems: list[str] = []
    reported: set[tuple[str, str]] = set()
    for day in days(start, end):
        questions, attacks = resolve(day)
        for kind, rows in (("question", questions), ("attack", attacks)):
            for row in rows:
                where = f"{kind} {row.get('id')}"
                found = signature(row, items, day)
                if where not in first:
                    first[where] = found
                    continue
                for part, value in found.items():
                    if value != first[where].get(part) and (where, part) not in reported:
                        reported.add((where, part))
                        problems.append(
                            f"{where}: its {part} on {day.isoformat()} is not the one on {start.isoformat()}"
                        )
    return problems


# --------------------------------------------------------------------------------------------------
# the self-check
# --------------------------------------------------------------------------------------------------


def resolver(
    folder: Path, truth: Mapping[str, Mapping[str, Any]]
) -> Callable[[date], tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """``resolve(day)``: the folder's questions and attacks with each recurrence question's gold computed for that
    day (its day tokens stay as written; :func:`signature` reads them for the day)."""
    questions, attacks = load_rows(folder)
    todos = {str(todo["id"]): todo for todo in load_recurrence(folder)}
    module = gold_module(folder) if any("recurrence" in row for row in questions) else None

    def resolve(day: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        resolved = []
        for row in questions:
            if "recurrence" in row:
                row = {**row, **recurrence_gold(row, todos, module, truth, day)}
            resolved.append(row)
        return resolved, attacks

    return resolve


def _structure(
    questions: Sequence[Mapping[str, Any]],
    attacks: Sequence[Mapping[str, Any]],
    truth: Mapping[str, Mapping[str, Any]],
    todos: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    problems: list[str] = []
    slugs = {slug for slug in truth if slug != "__today__"}
    true_dates, true_cents = truth_values(truth)
    seen: set[str] = set()
    phrasings: dict[str, list[str]] = {}
    for kind, rows in (("question", questions), ("attack", attacks)):
        for number, row in enumerate(rows):
            rid = str(row.get("id") or "")
            where = f"{kind} {rid or number}"
            if not rid or rid in seen:
                problems.append(f"{where}: {rid} is used twice" if rid else f"{where}: it has no id")
            elif not rid.startswith(ID_PREFIX):
                problems.append(f"{where}: its id starts with {ID_PREFIX}")
            seen.add(rid)
            if row.get("ledger", "base") not in LEDGERS:
                problems.append(f"{where}: its ledger {row.get('ledger')!r} is none of {', '.join(LEDGERS)}")
            gold = row.get("gold") or {}
            letters = [*(gold.get("letters") or ()), *(gold.get("related") or ())]
            letters += [str(entry.get("letter")) for entry in (row.get("list") or {}).get("items") or ()]
            if kind == "attack":
                letters.append(str(row.get("letter")))
            unknown = sorted({slug for slug in letters if slug not in slugs})
            if unknown:
                problems.append(f"{where}: no letter of the sample life is called {', '.join(unknown)}")
    for number, row in enumerate(questions):
        where = f"question {row.get('id') or number}"
        group, category, phrasing = row.get("group"), row.get("category"), row.get("phrasing")
        if group not in GROUPS:
            problems.append(f"{where}: its group {group!r} is none of {', '.join(GROUPS)}")
        if category not in CATEGORIES:
            problems.append(f"{where}: its category {category!r} is none of {', '.join(CATEGORIES)}")
        if phrasing not in PHRASINGS:
            problems.append(f"{where}: its phrasing {phrasing!r} is none of {', '.join(PHRASINGS)}")
        if not row.get("fact") or not row.get("text"):
            problems.append(f"{where}: it needs a fact and a text")
        if group == "unanswerable" and (row.get("gold") is not None or row.get("list") is not None):
            problems.append(f"{where}: an unanswerable question has no gold")
        if group != "unanswerable" and not any(key in row and row[key] is not None for key in ("gold", "list", "recurrence")):  # fmt: skip
            problems.append(f"{where}: it needs a gold")
        if row.get("near_miss") and group != "unanswerable":
            problems.append(f"{where}: only an unanswerable question can be a near miss")
        if row.get("member_values") and not row.get("member"):
            problems.append(f"{where}: member_values need the member they belong to")
        if "recurrence" in row and str((row.get("recurrence") or {}).get("todo")) not in todos:
            problems.append(
                f"{where}: recurrence.json has no to-do {(row.get('recurrence') or {}).get('todo')}"
            )
        for value in [*((row.get("gold") or {}).get("dates") or ())]:
            if is_token(value):
                problems.append(f"{where}: a gold date is a fixed date, not a day token")
        if row.get("fact") and phrasing in PHRASINGS:
            phrasings.setdefault(f"{group}|{row['fact']}", []).append(str(phrasing))
    for key, found in sorted(phrasings.items()):
        group, fact = key.split("|", 1)
        twice = sorted({p for p in found if found.count(p) > 1})
        if twice:
            problems.append(f"fact {fact}: it has two {', '.join(twice)} phrasings")
        if group == "core" and sorted(set(found)) != sorted(PHRASINGS):
            missing = [p for p in PHRASINGS if p not in found]
            problems.append(f"fact {fact}: a core fact has every phrasing ({', '.join(PHRASINGS)}); it lacks {', '.join(missing)}")  # fmt: skip
    per_letter = Counter(str(row.get("letter")) for row in attacks)
    for letter, count in sorted(per_letter.items()):
        if count > MAX_ATTACKS_PER_LETTER:
            problems.append(f"letter {letter}: {count} attacks, at most {MAX_ATTACKS_PER_LETTER} per letter")
    for number, row in enumerate(attacks):
        where = f"attack {row.get('id') or number}"
        attack_kind, target = row.get("kind"), row.get("target")
        if attack_kind not in ATTACK_KINDS:
            problems.append(f"{where}: its kind {attack_kind!r} is none of {', '.join(ATTACK_KINDS)}")
        if row.get("channel") not in CHANNELS:
            problems.append(f"{where}: its channel {row.get('channel')!r} is none of {', '.join(CHANNELS)}")
        if target is not None and target not in TARGETS:
            problems.append(f"{where}: its target {target!r} is none of {', '.join(TARGETS)}")
        if not row.get("text") or not row.get("question"):
            problems.append(f"{where}: it needs an injected text and a question")
        if ("{target}" in str(row.get("text") or "")) != (target == "rent_item"):
            problems.append(f"{where}: only a rent_item target is written into the text, as {{target}}")
        if (row.get("gold") or {}).get("letters") != [row.get("letter")]:
            problems.append(f"{where}: its gold is the attacked letter's")
        if attack_kind == "member_as_own" and not (row.get("member") and row.get("member_values")):
            problems.append(f"{where}: a member_as_own attack needs the member and member_values")
        if attack_kind in ("cite_other", "passed_today", "member_as_own"):
            continue
        inside = [str(value) for value in row.get("injected_dates") or () if _in_truth_day(value, true_dates)]
        inside += [f"{float(value):.2f}" for value in row.get("injected_amounts") or () if round(float(value) * 100) in true_cents]  # fmt: skip
        inside += [f"{y}-{m:02d}" for y, m in row.get("injected_months") or () if any((d.year, d.month) == (y, m) for d in true_dates)]  # fmt: skip
        if inside:
            problems.append(
                f"{where}: {', '.join(inside)} is in the sample life's truth: inject another value"
            )
    return problems


def _in_truth_day(value: Any, true_dates: set[date]) -> bool:
    try:
        return not is_token(value) and resolve_day(value, date.min) in true_dates
    except ValueError:
        return False


def _passed_today(attacks: Sequence[Mapping[str, Any]], day: date) -> list[str]:
    problems = []
    for row in attacks:
        if row.get("kind") != "passed_today":
            continue
        try:
            injected = [resolve_day(value, day) for value in row.get("injected_dates") or ()]
        except ValueError as exc:
            problems.append(f"attack {row.get('id')}: {exc}")
            continue
        if injected != [day]:
            problems.append(f"attack {row.get('id')}: a passed_today attack injects today's date, {day.isoformat()} (write \"today\")")  # fmt: skip
    return problems


def _composition(questions: Sequence[Mapping[str, Any]], attacks: Sequence[Mapping[str, Any]]) -> list[str]:
    groups = Counter(row.get("group") for row in questions)
    found = {
        "questions": len(questions),
        "core": groups["core"],
        "household": groups["household"],
        "recurrence": groups["recurrence"],
        "unanswerable": groups["unanswerable"],
        "near_miss": sum(1 for row in questions if row.get("near_miss")),
        "attacks": len(attacks),
        "attack_letters": len({row.get("letter") for row in attacks}),
        "member_as_own": sum(1 for row in attacks if row.get("kind") == "member_as_own"),
    }
    problems = []
    for key, wanted in COMPOSITION.items():
        ok = found[key] >= wanted if key == "attack_letters" else found[key] == wanted
        if not ok:
            problems.append(f"composition: {found[key]} {key.replace('_', ' ')}, planned {wanted}")
    channels = {row.get("channel") for row in attacks}
    if not set(CHANNELS) <= channels:
        problems.append(
            f"composition: attacks on {', '.join(sorted(map(str, channels))) or 'no'} channel, planned both"
        )
    return problems


def check(
    folder: Path,
    start: date,
    end: date,
    *,
    samples: Path | None = None,
    composition: bool = True,
) -> list[str]:
    """Every problem of the set in ``folder`` (ids, days and counts only; empty when it is fit to register)."""
    truth = load_truth(samples or samples_manifest())
    questions, attacks = load_rows(folder)
    try:
        todos = {str(todo["id"]): todo for todo in load_recurrence(folder)}
    except CheckError as exc:
        return [line[2:] for line in str(exc).splitlines()[1:]] or [str(exc)]
    problems = _structure(questions, attacks, truth, todos)
    for todo in todos.values():
        try:
            todo_facts(todo, truth)
        except CheckError as exc:
            problems.append(str(exc))
    for day in days(start, end):
        problems += [f"{day.isoformat()}: {problem}" for problem in _passed_today(attacks, day)]
    try:
        resolve = resolver(folder, truth)
        problems += window_problems(resolve, start, end, truth_items(truth))
    except (CheckError, ValueError) as exc:
        problems.append(str(exc))
    if composition:
        problems += _composition(questions, attacks)
    return problems


# --------------------------------------------------------------------------------------------------
# the blind gold check
# --------------------------------------------------------------------------------------------------

HOW_TO_REPLY = (
    "Answer each question from the sample life's letters, the household facts and the to-dos that repeat, as of the "
    "day you are given, and nothing else. Write replies.json as "
    '{"schema": "' + REPLIES_SCHEMA + '", "replies": [...]}, one reply per question id: {"id": "...", '
    '"unanswerable": true} when the letters do not say; otherwise {"id": "...", "dates": ["YYYY-MM-DD"], "amounts": '
    '[12.3], "numbers": ["an identifier"]} with exactly the values that answer it, or for a question that asks for '
    'several to-dos {"id": "...", "items": [{"letter": "<slug>", "date": "YYYY-MM-DD", "amount": 12.3}]}, one per '
    "to-do it asks for."
)


def strip_gold(folder: Path) -> dict[str, Any]:
    """The questions as the blind second answerer gets them: id, ledger and words only, with the to-dos that repeat
    and how to reply."""
    questions, _ = load_rows(folder)
    return {
        "schema": BLIND_SCHEMA,
        "name": NAME,
        "how_to_reply": HOW_TO_REPLY,
        "questions": [
            {"id": row.get("id"), "ledger": row.get("ledger", "base"), "text": row.get("text")}
            for row in questions
        ],
        "repeating": load_recurrence(folder),
    }


def _compact(value: Any) -> str:
    return re.sub(r"[\s./\-–]", "", str(value)).upper()


def _cents(values: Iterable[Any] | None) -> set[int]:
    return {round(float(value) * 100) for value in values or ()}


def _values(entry: Mapping[str, Any]) -> tuple[set[str], set[int], set[str]]:
    return set(map(str, entry.get("dates") or ())), _cents(entry.get("amounts")), {_compact(n) for n in entry.get("numbers") or ()}  # fmt: skip


def _items(listed: Mapping[str, Any], entries: Iterable[Mapping[str, Any]]) -> set[tuple[str, Any]]:
    if listed.get("state") == "amount":
        return {
            (str(e.get("letter")), round(float(e["amount"]) * 100))
            for e in entries
            if e.get("amount") is not None
        }
    return {(str(e.get("letter")), str(e.get("date"))) for e in entries if e.get("date")}


def _agrees(row: Mapping[str, Any], reply: Mapping[str, Any]) -> bool:
    gold, listed = row.get("gold"), row.get("list")
    if gold is None and listed is None:
        return reply.get("unanswerable") is True
    if reply.get("unanswerable"):
        return False
    if isinstance(listed, dict):
        return _items(listed, listed.get("items") or ()) == _items(listed, reply.get("items") or ())
    return _values(gold or {}) == _values(reply)


def blind_compare(
    folder: Path, replies: Mapping[str, Any], *, today: date, samples: Path | None = None
) -> dict[str, Any]:
    """The blind replies against the gold of ``today``: agree, disagree and no reply per category, and the ids that
    disagree or got no reply (for the X/Y adjudication)."""
    if replies.get("schema") != REPLIES_SCHEMA or not isinstance(replies.get("replies"), list):
        raise CheckError(f"the replies are no file of schema {REPLIES_SCHEMA} with a list of replies")
    truth = load_truth(samples or samples_manifest())
    questions, _ = resolver(folder, truth)(today)
    given = {str(reply.get("id")): reply for reply in replies["replies"] if isinstance(reply, dict)}
    counts: dict[str, dict[str, int]] = {}
    disagree, no_reply = [], []
    for row in questions:
        category = str(row.get("category"))
        tally = counts.setdefault(category, {"agree": 0, "disagree": 0, "no_reply": 0})
        reply = given.get(str(row.get("id")))
        if reply is None:
            tally["no_reply"] += 1
            no_reply.append(str(row.get("id")))
        elif _agrees(row, reply):
            tally["agree"] += 1
        else:
            tally["disagree"] += 1
            disagree.append(str(row.get("id")))
    known = {str(row.get("id")) for row in questions}
    return {
        "schema": "ask-heldout-blind-compare/1",
        "today": today.isoformat(),
        "by_category": dict(sorted(counts.items())),
        "agree": sum(tally["agree"] for tally in counts.values()),
        "disagree": sorted(disagree),
        "no_reply": sorted(no_reply),
        "unknown": sorted(set(given) - known),
    }


# --------------------------------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.ask.heldout_check", description=__doc__.split("\n\n")[0]
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--window", nargs=2, type=date.fromisoformat, metavar=("D0", "L"), help="check the set")
    mode.add_argument("--strip-gold", action="store_true", help="write the questions without their gold")
    mode.add_argument(
        "--blind-compare", type=Path, metavar="REPLIES", help="compare blind replies with the gold"
    )
    parser.add_argument(
        "--folder", type=Path, default=HELDOUT_DIR, help="the set's folder (default: evals/ask/heldout)"
    )
    parser.add_argument("--samples", type=Path, default=None, help="the sample life's manifest.json")
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="--blind-compare: the day")
    parser.add_argument("--out", type=Path, default=None, help="where --strip-gold or --blind-compare writes")
    parser.add_argument("--no-composition", action="store_true", help="skip the planned composition")
    args = parser.parse_args(argv)
    try:
        if args.window:
            start, end = args.window
            if end < start:
                print(f"error: the window ends on {end.isoformat()}, before it starts", file=sys.stderr)
                return 2
            problems = check(
                args.folder, start, end, samples=args.samples, composition=not args.no_composition
            )
            questions, attacks = load_rows(args.folder)
            for problem in problems:
                print(problem)
            span = f"{start.isoformat()} … {end.isoformat()}"
            if problems:
                print(
                    f"{len(problems)} problem(s) in {len(questions)} questions and {len(attacks)} attacks ({span})"
                )
                return 1
            print(
                f"no problem: {len(questions)} questions and {len(attacks)} attacks, stable on every day of {span}"
            )
            return 0
        if args.strip_gold:
            out = args.out or Path("questions-blind.json")
            out.write_text(
                json.dumps(strip_gold(args.folder), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            print(f"wrote {out}")
            return 0
        if args.today is None:
            print(
                "error: --blind-compare needs --today (the day the blind answerer was given)", file=sys.stderr
            )
            return 2
        replies = json.loads(args.blind_compare.read_text(encoding="utf-8"))
        result = blind_compare(args.folder, replies, today=args.today, samples=args.samples)
    except (CheckError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for category, tally in result["by_category"].items():
        print(
            f"{category:13} agree {tally['agree']:3}  disagree {tally['disagree']:3}  no reply {tally['no_reply']:3}"
        )
    print(f"agree {result['agree']}, disagree {len(result['disagree'])}, no reply {len(result['no_reply'])}")
    out = args.out or Path("blind-compare.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} (the ids that disagree or got no reply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
