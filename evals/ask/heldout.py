"""The held-out Ask set: questions and attacks written blind after the code freeze, read and checked here.

The files are ``evals/ask/heldout/questions.json`` and ``attacks.json`` (schema :data:`SCHEMA`). A writer who has
seen neither the recorded answers, Ask's check (``ordnung/assistant/support.py``), its prompt nor the development
set's failures writes them from the sample life's truth; their sha256 goes into the pre-registration before the
first recording, and :func:`frozen_mismatches` holds them to it. ``python -m evals.ask --set heldout`` asks them
through the same Ask, records into ``evals/recorded/ask-heldout/`` and writes ``…-ask-heldout[-rN].json``.

A question::

    {"id": "…", "group": "core|household|recurrence|unanswerable", "category": "deadline|payment|contract|
     cross_letter|household|recurrence|unanswerable", "fact": "<the fact its phrasings share>",
     "phrasing": "en|en-paraphrase|de", "ledger": "base|household|recurrence", "text": "…",
     "gold": {"dates": ["YYYY-MM-DD"], "amounts": [12.3], "letters": ["<slug>"], "related": ["<slug>"],
              "numbers": ["<an identifier the answer must give>"]} | null,
     "near_miss": false, "member": "<a household member's name>", "member_values": ["<that member's values>"],
     "list": {"state": "date|amount", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD", "kinds": ["payment"],
              "direction": "out", "items": [{"letter": "<slug>", "date": "YYYY-MM-DD", "amount": 12.3}]} | null}

``gold`` is ``null`` exactly for the ``unanswerable`` group; ``near_miss`` marks an unanswerable question whose
record holds a neighbouring fact; ``member_values`` are values the answer must never give as the person's own
(:mod:`evals.ask.strict`). A list question's gold values and letters come from its ``items`` (the occurrences it
must give, within ``from``–``to``); any other item of the sample life inside the window is a right inclusion too.

An attack::

    {"id": "…", "kind": "moved_date|changed_amount|no_deadline|cite_other|pay_scam|passed_today|member_as_own",
     "letter": "<slug>", "channel": "page|summary", "ledger": "base|household", "text": "<the injected passage>",
     "question": "…", "gold": {…}, "injected_dates": ["YYYY-MM-DD"], "injected_amounts": [12.3],
     "injected_months": [[2027, 12]], "target": "rent_item|rent_contract|tax_objection_item" | null,
     "member": "…", "member_values": ["…"]}

Injected values lie outside the sample life's truth (``cite_other`` names another record's own value and
``passed_today`` today's date, on purpose). ``member_as_own`` succeeds when the final answer gives a member's value
as the person's own (a sentence states it without naming the member).

The ``base`` ledger is the development set's; any other is built by the module :data:`PROVIDERS` names for it
(``household``: ``evals.ask.household``, E2's household copy; ``recurrence``: ``evals.ask.recurrence``, the held-out
set's copy with repeating to-dos), which is imported on first use and registers its builder with
:func:`register_ledger`.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, cast, get_args

from evals.ask.attacks import ATTACKS, Attack, AttackKind, Channel, Target
from evals.ask.ledger import SampleLife, benchmark_today
from evals.ask.questions import Category, Gold, Question, TruthDoc, all_questions, load_truth, truth_values
from evals.ask.strict import Extras, ListGold, TruthItem, truth_items, window

ROOT = Path(__file__).resolve().parents[2]
HELDOUT_DIR = Path(__file__).resolve().parent / "heldout"
QUESTIONS_NAME = "questions.json"
ATTACKS_NAME = "attacks.json"
SCHEMA = "ordnung-ask-heldout/1"
GROUPS = ("core", "household", "recurrence", "unanswerable")
LEDGERS = ("base", "household", "recurrence")
PHRASINGS = ("en", "en-paraphrase", "de")
CATEGORIES = (*get_args(Category), "household", "recurrence")
ATTACK_KINDS = (*get_args(AttackKind), "member_as_own")
CHANNELS = get_args(Channel)
TARGETS = get_args(Target)
PREREGISTRATION = ROOT / "evals" / "preregistration" / "final-0.4.0.json"


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


def _day(value: Any, where: str, problems: _Problems) -> date | None:
    text = str(value)
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
    except ValueError:
        pass
    problems.check(False, where, f"{value!r} is no ISO date (YYYY-MM-DD)")
    return None


def _days(values: Any, where: str, problems: _Problems) -> tuple[date, ...]:
    return tuple(day for value in values or () if (day := _day(value, where, problems)) is not None)


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
    raw: Mapping[str, Any], items: Sequence[TruthItem], slugs: set[str], where: str, problems: _Problems
) -> tuple[ListGold | None, Gold]:
    state = raw.get("state")
    problems.check(state in ("date", "amount"), where, f"a list states a date or an amount, not {state!r}")
    start, end = _day(raw.get("from"), where, problems), _day(raw.get("to"), where, problems)
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


def load_questions(
    path: Path = HELDOUT_DIR / QUESTIONS_NAME, *, truth: Mapping[str, TruthDoc] | None = None
) -> list[HeldOutQuestion]:
    """The held-out questions, checked against the sample life's truth (every problem at once)."""
    rows = _read(path, "questions")
    loaded = truth if truth is not None else load_truth()
    slugs, items = set(loaded), truth_items(loaded)
    dev = {q.id for q in all_questions(dict(loaded))} | {a.id for a in ATTACKS}
    problems = _Problems()
    seen: set[str] = set()
    phrasings: set[tuple[str, str]] = set()
    found = []
    for number, row in enumerate(rows):
        qid = str(row.get("id") or "")
        where = f"question {qid or number}"
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
                listed, values = _list_gold(raw_list, items, slugs, where, problems)
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
    path: Path = HELDOUT_DIR / ATTACKS_NAME, *, truth: Mapping[str, TruthDoc] | None = None
) -> list[HeldOutAttack]:
    """The held-out attacks, checked against the sample life's truth (every problem at once)."""
    rows = _read(path, "attacks")
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
        dates = _days(row.get("injected_dates"), where, problems)
        amounts = _amounts(row.get("injected_amounts"), where, problems)
        months = tuple((int(year), int(month)) for year, month in row.get("injected_months") or ())
        member, member_values = _member(row, where, problems)
        if kind == "member_as_own":
            problems.check(
                bool(member_values), where, "a member_as_own attack needs the member and member_values"
            )
        elif kind == "passed_today":
            problems.check(
                dates == (benchmark_today(),),
                where,
                f"a passed_today attack injects today's date, {benchmark_today()}",
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
# ledgers
# --------------------------------------------------------------------------------------------------

LedgerBuilder = Callable[[Path, Path, SampleLife], Path]
"""Builds a held-out ledger in ``target`` from the base ledger's folder (a copy plus the ledger's own changes)."""

_BUILDERS: dict[str, LedgerBuilder] = {}
#: The module that builds each ledger: imported on first use, it registers its builder (:func:`register_ledger`).
PROVIDERS = {"household": "evals.ask.household", "recurrence": "evals.ask.recurrence"}


def register_ledger(name: str, build: LedgerBuilder) -> None:
    """Let held-out items ask on the ledger ``name``, built by ``build``."""
    if name not in LEDGERS or name == "base":
        raise HeldOutError(f"{name!r} is not a held-out ledger one registers ({', '.join(LEDGERS[1:])})")
    _BUILDERS[name] = build


def unregister_ledger(name: str) -> None:
    _BUILDERS.pop(name, None)


def ledger_builder(name: str) -> LedgerBuilder | None:
    """How the ledger ``name`` is built (``None``: the base ledger itself)."""
    if name == "base":
        return None
    module = PROVIDERS.get(name, "")
    if name not in _BUILDERS and module:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name != module:  # the module is there but something it imports is not
                raise
    if name not in _BUILDERS:
        raise HeldOutError(
            f"no builder for the {name} ledger: its module ({module or 'none named'}) registers one with "
            "evals.ask.heldout.register_ledger when it is imported"
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
