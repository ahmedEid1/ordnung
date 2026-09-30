"""Two dates for one obligation: a letter that contradicts itself (SPEC § 8 stage 6, § 21).

A letter sometimes prints two different dates for the same thing: "binnen 14 Tagen nach dem
Rechnungsdatum" in the text and "Zahlbar bis" a week later in the payment box, or a tax notice
dated one day in its header and another in its first sentence ("Mit diesem Bescheid vom …"). The
reading takes one of them, and nothing in its own sentence tells that the letter says otherwise
elsewhere. This module checks, in code and on the letter's own text, every dated to-do for such a
second statement:

* :func:`find_rivals` (verify stage) looks in the page text for other deadline statements of the
  same nature as a to-do: for a payment, a date after "zahlbar bis", "fällig am", "bitte überweisen
  Sie … bis zum", "Zahlungsziel:" (or before "… fällig", "… zu zahlen"), and a period after the
  invoice's date or its arrival ("binnen 14 Tagen nach Rechnungsdatum"); for an objection, a date
  after "Widerspruch / Einspruch / Klage … bis"; and, for any period counted from the letter, a
  date the letter gives for itself ("mit diesem Bescheid vom …", "mit Bescheid vom … entscheiden
  wir", "this letter dated …"). Only statements that plausibly concern the *same* obligation count:
  never a recurring to-do, money coming in, or a to-do with no date; never a statement whose sentence
  is the to-do's own quote, whose date is another to-do's, which names a different amount (an
  instalment), a kind of payment the to-do's sentence does not (instalments, a prepayment, a fee, a
  direct debit, a series: "die neuen Abschläge … erstmals am", "die nächste Vorauszahlung"), or —
  for an objection — another remedy (a Klage's date is not a Beschwerde's), which is written in the
  past ("war fällig am …", "wurde"), or which is an early-payment discount (*Skonto*: paying after
  the discount date is not late — the net date is the obligation, so a discount date is never a
  second due date). The page's line breaks stay: a due word counts for a date only on the date's own
  label or in its sentence, never from another label ("Rechnungsdatum: …" above "Zahlbar bis: …"),
  and a remedy's sentence gives no payment period.
* :func:`settle` (compute stage) computes each such statement with the rules engine, as the to-do's
  own date is computed. A statement whose date is the to-do's, or a written date on or before the
  letter's own (the letter's date itself; a reminder repeats the original invoice's due date:
  history, not a second date — before the day it arrived, or today, when the letter's date was not
  read), is no conflict; nor is a reminder's period "after the invoice date" (it counts from the old
  invoice's date, not the reminder's). When the letter does give another date, the to-do keeps the **earlier** one (the safe
  side: acting by it is on time whichever applies), its receipt names both dates and says why the
  earlier one was kept (rule ``conflicting_dates``), its confidence is ``low`` and it is marked
  "Please check" (its evidence is not ``value_consistent``: :func:`~ordnung.ingest.plan.needs_check`).

The check reads code-side only (no model call) and adds dates only where the letter writes them.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from ordnung.ingest.normalize import fold_punctuation, normalise_with_map
from ordnung.ingest.text import PageText
from ordnung.ingest.verify import (
    PageInput,
    date_spans,
    grade_reading,
    parse_amounts,
    parse_periods,
)
from ordnung.models import (
    PAYMENT_DEMAND_KINDS,
    ComputationReceipt,
    ComputationStep,
    DateSpec,
    ExtractedItem,
    Grounding,
    Page,
)
from ordnung.rules import RuleContext, catalog, compute_due
from ordnung.rules.deadlines import parse_date
from ordnung.rules.explain import fmt_date

#: The rule a receipt cites when the letter gives two dates for the to-do (and the reason its evidence
#: is not value-consistent).
CONFLICTING_DATES = "conflicting_dates"

#: How far (characters, in the letter's flattened text) a deadline word may stand from its date.
_CUE_REACH = 90
_AFTER_REACH = 60
#: Characters around a statement in which an amount belongs to it.
_AMOUNT_REACH = 80
#: How much of a statement a warning quotes.
_QUOTE_CHARS = 90

_PAYMENT_CUE = re.compile(
    r"\b(?:zahlbar|fällig\w*|zahlungsziel|zahlungstermin|zahlungsfrist|zahlen\s+sie|überweisen\s+sie"
    r"|begleichen\s+sie|zu\s+(?:zahlen|überweisen|begleichen)|payable|please\s+pay|to\s+be\s+paid"
    r"|(?:payment|amount|total|balance)\s+(?:is\s+)?due|due\s+date|pay(?:ment)?\s+(?:by|before|until|within))\b",
    re.IGNORECASE,
)
#: A payment's words after its date: "bis zum 15.05.2026 zu zahlen", "ist am 15.11.2026 fällig".
_PAYMENT_CUE_AFTER = re.compile(
    r"^\W*(?:\S+\s+){0,6}?(?:fällig|zu\s+zahlen|zu\s+überweisen|zu\s+begleichen|zahlbar)\b", re.IGNORECASE
)
_OBJECTION_CUE = re.compile(r"\b(?:widerspruch|einspruch|klage|objection|appeal)\w*", re.IGNORECASE)
#: The words just before a due date: "bis (zum)", "spätestens", "am", "by" … or a label's colon —
#: a weekday may stand between ("bis Freitag, 28.08.2026").
_DUE_PREPOSITION = re.compile(
    r"(?:\b(?:bis|zum|spätestens|einschließlich|am|by|on|before|until)|:)\s*"
    r"(?:(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday),?\s*)?(?:den\s+)?$",
    re.IGNORECASE,
)
#: An early-payment discount: its date is not the due date ("ohne Abzug" is the net amount, which is).
_DISCOUNT = re.compile(r"skonto|discount|rabatt|nachlass|abzüglich|(?<!ohne )\babzug\b", re.IGNORECASE)
#: A statement about the past ("war fällig am …", "wurde … gesetzt"): history, not a date to meet.
_PAST = re.compile(r"\b(?:war|waren|wurde|wurden|hatte|hatten|was|were|had)\b", re.IGNORECASE)
_NUMBER = (
    r"\d{1,3}|eine[mnrs]?|ein|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|vierzehn|zwanzig"
    r"|dreißig|dreissig|one|two|three|four|five|six|seven|eight|nine|ten|fourteen|twenty|thirty"
)
_PERIOD_UNIT = (
    r"(?:kalender|bank)?(?:tag|tage|tagen|tages)|woche|wochen|monat|monate|monaten|monats"
    r"|(?:calendar\s+)?days?|weeks?|months?"
)
#: A payment period counted from the invoice's date or from its arrival, as the letter writes it.
_RELATIVE_PAYMENT = re.compile(
    rf"(?:\b(?:binnen|innerhalb(?:\s+von)?|within)\s+)?\b(?P<period>(?:{_NUMBER})\s+(?:{_PERIOD_UNIT}))\s+"
    r"(?:nach|ab|after|from|of)\s+(?:dem\s+|der\s+|the\s+)?"
    r"(?P<anchor>rechnungsdatum|rechnungsstellung|datum\s+(?:dieser|der)\s+rechnung"
    r"|rechnungseingang|rechnungserhalt|erhalt|zugang|date\s+of\s+(?:this|the)\s+(?:letter|invoice)"
    r"|invoice\s+date|receipt)\b",
    re.IGNORECASE,
)
_ARRIVAL_ANCHORS = ("rechnungseingang", "rechnungserhalt", "erhalt", "zugang", "receipt")
#: The letter naming its own date: "(mit) diesem Bescheid vom …", "this letter dated …".
_SELF_DATE = re.compile(
    r"(?:\b(?:diese[mnrs]?|vorliegende[mnrs]?)\s+\w*(?:bescheid|schreiben|brief|mahnung|erinnerung"
    r"|aufforderung|mitteilung|festsetzung)|\bthis\s+(?:letter|notice|decision|assessment))\s+"
    r"(?:vom|dated|of)\s*$",
    re.IGNORECASE,
)
#: "mit Bescheid vom 16.03.2026 entscheiden wir …": the letter's own decision, in the present tense.
_OWN_DECISION_BEFORE = re.compile(r"\bmit\s+(?:dem\s+)?(?:bescheid|schreiben)\s+vom\s*$", re.IGNORECASE)
_OWN_DECISION_AFTER = re.compile(
    r"^\s*(?:entscheiden|setzen|lehnen|bewilligen|gewähren|fordern|erheben|stellen|teilen|ändern|heben"
    r"|erstatten|erlassen|bestätigen)\s+wir\b",
    re.IGNORECASE,
)
#: Where a sentence ends: a full stop, "!", "?" or ";" before a capital letter or an opening quote.
_SENTENCE_END = re.compile(r"[.!?;]\s+(?=[A-ZÄÖÜ\"(])")
#: A label's colon ("Rechnungsdatum: …", "Total due: …"), not a time's ("10:00").
_LABEL_COLON = re.compile(r":(?=\s|$)")
#: Where a label's words start on a line ("… fällig. Hinweis:", "02.03.2026 · Zahlbar bis:").
_FIELD_BREAK = re.compile(r"[.!?;,]\s|[·|(]|\s[-–]\s")
#: Words that mark another obligation than a one-off payment: an instalment, an advance payment, a
#: fee, a direct debit, a series ("erstmals am …", "jeweils", "monatlich", "die nächste …"). A statement
#: with one the to-do's own sentence lacks dates something else (a utility's new instalments, a tax
#: prepayment, a first premium collected from the account).
_OTHER_OBLIGATION: dict[str, re.Pattern[str]] = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in {
        "instalment": r"\babschl[aä]g\w*|\braten?\b|\w*ratenzahlung\w*|\bteil(?:zahlung|betr[aä]g)\w*"
        r"|\binstal+ments?\b|\b(?:folge|erst)(?:beitr[aä]g|rate)\w*",
        "advance": r"\bvorauszahlung\w*|\bprepayments?\b|\badvance\s+payments?\b",
        "fee": r"\w*gebühr\w*|\bfees?\b",
        "debit": r"\babgebucht\b|\babbuch\w*|\w*lastschrift\w*|\beingezogen\b|\beinzug\w*|\bdirect\s+debit\w*"
        r"|\bdebited\b",
        "series": r"\berstmal\w*|\bjeweils\b|\b(?:zu)?künftig\w*|\bnächste\w*|\bnext\b|\bthereafter\b"
        r"|\bsubsequent\w*|\beach\s+month\b|\bevery\s+month\b",
        "period": r"\w*monatlich\w*|\w*jährlich\w*|\bmonthly\b|\bquarterly\b|\bannual(?:ly)?\b|\byearly\b",
    }.items()
}
#: The remedy an objection statement names: a date for a Widerspruch is not one for a Klage.
_REMEDIES: dict[str, re.Pattern[str]] = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in {
        "widerspruch": r"widerspr\w*",
        "einspruch": r"einspr\w*",
        "klage": r"\bklage\w*|\bklagen\b",
        "beschwerde": r"beschwerde\w*",
        "objection": r"\bobjection\w*|\bobject\b",
        "appeal": r"\bappeal\w*",
    }.items()
}

Nature = Literal["payment", "objection"]


@dataclass(frozen=True)
class Rival:
    """Another statement in the letter that dates a to-do's obligation: ``spec`` is what it says (a
    date, or a period and what it counts from), ``statement`` the letter's words, ``grounding`` how
    the page it stands on was read (a text layer: ``verified``; an AI transcript: ``model_read``).
    ``letter_date``: the statement is a date the letter gives for *itself*; ``spec`` is then the
    to-do's own, to be counted from that date instead of the letter's date as read."""

    spec: DateSpec
    statement: str
    grounding: Grounding = "verified"
    letter_date: date | None = None


@dataclass(frozen=True)
class _Statement:
    """``window``: the text around the statement in which an amount belongs to it; ``context``: the words
    that stand with its date (not past a label or another date), in which a word marking another
    obligation or a remedy counts."""

    spec: DateSpec
    phrase: str
    window: str
    grounding: Grounding
    letter_date: date | None = None
    context: str = ""


# --------------------------------------------------------------------------------------------------
# Finding the letter's statements (verify stage)
# --------------------------------------------------------------------------------------------------


def _page_text(page: PageInput) -> tuple[str, Grounding]:
    if isinstance(page, PageText):
        return page.text, "verified" if page.source == "text" else "model_read"
    if isinstance(page, Page):
        return page.text, "verified" if page.text_source == "text" else "model_read"
    return page[1], "verified" if page[3] == "text" else "model_read"


def _clauses(text: str) -> list[tuple[str, list[tuple[int, int, date]]]]:
    """The letter's text folded into sentences, each with its dated mentions (dates without a year are
    left out: they can't be compared). The line breaks stay (a label's line is its own:
    :func:`_label_before`); a full stop inside a date ("30. Juni") never ends a sentence."""
    lines = (re.sub(r"\s+", " ", line).strip() for line in fold_punctuation(text).splitlines())
    flat = "\n".join(line for line in lines if line)
    spans = [(start, end, found) for start, end, m in date_spans(flat) if (found := m.as_date()) is not None]
    inside = [(start, end) for start, end, _ in spans]
    cuts = [0]
    for match in _SENTENCE_END.finditer(flat):
        if not any(start <= match.start() < end for start, end in inside):
            cuts.append(match.start() + 1)
    cuts.append(len(flat))
    clauses = []
    for lo, hi in itertools.pairwise(cuts):
        clause = flat[lo:hi]
        local = [(s - lo, e - lo, d) for s, e, d in spans if lo <= s and e <= hi]
        clauses.append((clause, local))
    return clauses


def _label_before(before: str) -> str:
    """The words before a date that are its own. On a label's line ("Zahlbar bis: 16.03.2026") the line
    itself, from the label before it on that line if any ("Fälligkeit: sofort, Datum: 02.03.2026" gives
    "sofort, Datum:"); otherwise the words back to the last label of an earlier line, never into it
    ("Gesamtbetrag fällig: 120,00 EUR" above "Datum: 02.03.2026": that "fällig" is the total's)."""
    line = before.rfind("\n") + 1
    colons = [m.start() for m in _LABEL_COLON.finditer(before)]
    own = [c for c in colons if c >= line]
    if own:
        return before[own[-2] + 1 :] if len(own) > 1 else before[line:]
    earlier = [c for c in colons if c < line]
    return before[earlier[-1] + 1 :] if earlier else before


def _label_after(after: str) -> str:
    """The words after a date that are its own: up to the next label, never into its words ("… 16.03.2026
    zu zahlen", but not the "Zahlbar bis:" after "Rechnungsdatum: 02.03.2026", on the next line or the
    same one)."""
    colon = _LABEL_COLON.search(after)
    if colon is None:
        return after
    line = after.rfind("\n", 0, colon.start())
    if line >= 0:
        return after[:line]
    breaks = list(_FIELD_BREAK.finditer(after, 0, colon.start()))
    return after[: breaks[-1].start()] if breaks else ""


def _explicit(clause: str, dates: list[tuple[int, int, date]], grounding: Grounding) -> list[_Statement]:
    """Dates the clause sets for a payment or an objection ("Zahlbar bis: 16.02.2026",
    "Widerspruch … bis zum 12.05.2026"): a due word on the date's own label or in its sentence —
    never one of another label or beyond another date."""
    found = []
    for index, (start, end, day) in enumerate(dates):
        lo = dates[index - 1][1] if index > 0 else 0
        hi = dates[index + 1][0] if index + 1 < len(dates) else len(clause)
        before = _label_before(clause[max(lo, start - _CUE_REACH) : start])
        after = _label_after(clause[end : min(hi, end + _AFTER_REACH)])
        if not _DUE_PREPOSITION.search(before):
            continue
        nature: Nature | None = None
        cue = None
        payment = list(_PAYMENT_CUE.finditer(before))
        objection = list(_OBJECTION_CUE.finditer(before))
        if payment:
            nature, cue = "payment", payment[-1].start()
        elif _PAYMENT_CUE_AFTER.search(after):
            nature, cue = "payment", len(before)
        elif objection:
            nature, cue = "objection", objection[-1].start()
        if nature is None or cue is None:
            continue
        said = (before[cue:] if cue < len(before) else before[-40:]) + clause[start:end] + after[:30]
        if _PAST.search(said) or _DISCOUNT.search(before + after):
            continue
        phrase = (before[cue:] + clause[start:end]).strip()
        spec = DateSpec(type="fixed", date=day.isoformat(), nature=nature, shift_rule="auto", text=phrase)
        window = clause[max(0, start - _AMOUNT_REACH) : end + _AMOUNT_REACH]
        found.append(_Statement(spec, phrase, window, grounding, context=before + clause[start:end] + after))
    return found


def _relative(clause: str, grounding: Grounding) -> list[_Statement]:
    """Payment periods the clause counts from the invoice's date or its arrival ("binnen 14 Tagen nach
    dem Rechnungsdatum", "Zahlungsziel: 7 Tage nach Rechnungsdatum")."""
    if not _PAYMENT_CUE.search(clause) and not re.search(r"zahlung|überweis", clause, re.IGNORECASE):
        return []
    if _PAST.search(clause) or _DISCOUNT.search(clause):
        return []
    if _OBJECTION_CUE.search(clause):
        return []  # a remedy's period ("Widerspruch … nach Zugang; die Zahlungspflicht bleibt"), not a payment's
    found = []
    for match in _RELATIVE_PAYMENT.finditer(clause):
        periods = parse_periods(match.group("period"))
        if len(periods) != 1:
            continue
        amount, unit = periods[0]
        anchor = match.group("anchor").casefold()
        spec = DateSpec(
            type="relative",
            anchor="receipt" if anchor in _ARRIVAL_ANCHORS else "document_date",
            amount=amount,
            unit=unit,
            nature="payment",
            shift_rule="auto",
            text=match.group().strip(),
        )
        window = clause[max(0, match.start() - _AMOUNT_REACH) : match.end() + _AMOUNT_REACH]
        context = (
            _label_before(clause[max(0, match.start() - _CUE_REACH) : match.start()])
            + match.group()
            + _label_after(clause[match.end() : match.end() + _AFTER_REACH])
        )
        found.append(_Statement(spec, match.group().strip(), window, grounding, context=context))
    return found


def _letter_dates(clause: str, dates: list[tuple[int, int, date]], grounding: Grounding) -> list[_Statement]:
    """Dates the letter gives for itself ("Mit diesem Bescheid vom 06.04.2027 setzen wir …")."""
    found = []
    for start, end, day in dates:
        before = clause[max(0, start - _CUE_REACH) : start]
        cue = _SELF_DATE.search(before)
        if cue is None and _OWN_DECISION_AFTER.match(clause[end:]):
            cue = _OWN_DECISION_BEFORE.search(before)
        if cue is None:
            continue
        phrase = (before[cue.start() :] + clause[start:end]).strip()
        found.append(
            _Statement(DateSpec(type="none", text=phrase), phrase, clause, grounding, letter_date=day)
        )
    return found


def letter_statements(pages: Sequence[PageInput]) -> list[_Statement]:
    """Every deadline statement :func:`find_rivals` can read in the letter, and the dates it gives for
    itself."""
    found: list[_Statement] = []
    for page in pages:
        text, grounding = _page_text(page)
        for clause, dates in _clauses(text):
            found += _explicit(clause, dates, grounding)
            found += _relative(clause, grounding)
            found += _letter_dates(clause, dates, grounding)
    return found


def _nature(item: ExtractedItem) -> Nature | None:
    if item.date.nature == "objection":
        return "objection"
    if item.kind == "payment" or item.date.nature == "payment":
        return "payment"
    return None


def _normalised(text: str) -> str:
    return normalise_with_map(text)[0]


def _is_own(statement: _Statement, item: ExtractedItem) -> bool:
    """Whether the statement is the to-do's own sentence (its quote says it)."""
    phrase = _normalised(statement.phrase)
    return bool(phrase) and phrase in _normalised(item.quote)


def _found(patterns: dict[str, re.Pattern[str]], text: str) -> set[str]:
    return {key for key, pattern in patterns.items() if pattern.search(text)}


def _own_words(item: ExtractedItem) -> str:
    return f"{item.quote} {item.date.text or ''}"


def _other_obligation(statement: _Statement, item: ExtractedItem, others: Sequence[ExtractedItem]) -> bool:
    """Whether the statement dates another to-do of the letter (its date or its period), names an
    amount that is not the to-do's (an instalment, a fee) or a kind of obligation the to-do's own
    sentence does not ("die neuen Abschläge … erstmals am", "die nächste Vorauszahlung ist fällig am"),
    or — for an objection — another remedy than the to-do's (a Klage's date is not a Beschwerde's)."""
    if _found(_OTHER_OBLIGATION, statement.context) - _found(_OTHER_OBLIGATION, _own_words(item)):
        return True
    if statement.spec.nature == "objection":
        remedies = _found(_REMEDIES, f"{_own_words(item)} {item.title}")
        if not remedies & _found(_REMEDIES, statement.context):
            return True  # another remedy, or the to-do names none: whether it is the same can't be told
    spec = statement.spec
    for other in others:
        if other is item or other.date.type == "none":
            continue
        if spec.type == "fixed" and other.date.type == "fixed" and other.date.date == spec.date:
            return True
        if (
            spec.type == "relative"
            and other.date.type == "relative"
            and (other.date.amount, other.date.unit) == (spec.amount, spec.unit)
        ):
            return True
    amounts = parse_amounts(statement.window)
    return item.amount is not None and bool(amounts) and all(abs(a - item.amount) >= 0.005 for a in amounts)


def find_rivals(
    item: ExtractedItem, others: Sequence[ExtractedItem], pages: Sequence[PageInput]
) -> tuple[Rival, ...]:
    """The letter's other statements that date the same obligation as ``item`` (see the module
    docstring); ``others`` are the reading's to-dos, ``item`` among them. Found in the text alone: whether
    a statement's date differs from the to-do's is for :func:`settle` to say."""
    if item.date.type == "none" or item.recurrence is not None or item.direction == "in":
        return ()
    nature = _nature(item)
    if _DISCOUNT.search(item.quote):
        return ()  # its sentence speaks of a discount: which date is the discount's is the reading's to tell
    rivals: list[Rival] = []
    for statement in letter_statements(pages):
        if statement.letter_date is not None:
            if item.date.type == "relative":
                rivals.append(Rival(item.date, statement.phrase, statement.grounding, statement.letter_date))
            continue
        if nature is None or statement.spec.nature != nature or _is_own(statement, item):
            continue
        if _other_obligation(statement, item, others):
            continue
        rivals.append(Rival(statement.spec, statement.phrase, statement.grounding))
    unique = {(rival.spec.model_dump_json(), rival.statement, rival.letter_date): rival for rival in rivals}
    return tuple(unique.values())


# --------------------------------------------------------------------------------------------------
# Settling the dates (compute stage)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settled:
    """A to-do's receipt after :func:`settle`: the earlier date kept, both named. ``fixed``: the date
    kept is one the letter writes (not a period the engine counted)."""

    receipt: ComputationReceipt
    fixed: bool


@dataclass(frozen=True)
class _Candidate:
    due: date
    receipt: ComputationReceipt
    statement: str
    fixed: bool
    rival: Rival | None = None


def _short(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= _QUOTE_CHARS else text[: _QUOTE_CHARS - 1].rstrip() + "…"


def _noun(item: ExtractedItem) -> str:
    return {"payment": "payment", "deadline": "deadline", "appointment": "appointment"}.get(item.kind, "date")


def _history(written: date, ctx: RuleContext) -> bool:
    """Whether a date the letter writes can't be a second date to meet: on or before the letter's own
    date (the letter's date itself, or a reminder's original due date) — or, when the letter's date is
    not known, before the day it arrived (or today)."""
    if ctx.document_date is not None:
        return written <= ctx.document_date
    return written < (ctx.received_date or ctx.today)


def _rival_candidate(rival: Rival, own: date, ctx: RuleContext, postal_buffer_days: int) -> _Candidate | None:
    """The date a rival statement gives, computed as the to-do's own is — ``None`` when it gives the
    same date, none, or a written date that is history (:func:`_history`)."""
    if rival.letter_date is not None:
        if ctx.document_date is None or rival.letter_date == ctx.document_date:
            return None
        counted = replace(ctx, document_date=rival.letter_date)
    else:
        if rival.spec.type == "relative" and ctx.letter_kind in PAYMENT_DEMAND_KINDS:
            return None  # a reminder's "14 Tage nach Rechnungsdatum" counts from the old invoice's date
        written = parse_date(rival.spec.date)
        if written is not None and _history(written, ctx):
            return None
        counted = replace(ctx, quote=rival.statement)
    receipt = grade_reading(
        compute_due(rival.spec, counted, postal_buffer_days=postal_buffer_days), rival.grounding, ()
    )
    due = parse_date(receipt.due_date)
    if due is None or due == own:
        return None
    return _Candidate(due, receipt, rival.statement, rival.spec.type == "fixed", rival)


def _warning(noun: str, own: _Candidate, other: _Candidate, kept: date, ctx: RuleContext) -> str:
    """The warning naming both dates, the earlier first."""
    rival = other.rival
    first, second = sorted((own, other), key=lambda candidate: candidate.due)
    if rival is not None and rival.letter_date is not None and ctx.document_date is not None:
        early, late = sorted((ctx.document_date, rival.letter_date))
        return (
            f"The letter gives two dates for itself: {fmt_date(early)} and {fmt_date(late)} "
            f"(“{_short(rival.statement)}”), so this {noun} is {fmt_date(first.due)} or {fmt_date(second.due)}. "
            f"We use the earlier one, {fmt_date(kept)} — please check which date applies."
        )
    return (
        f"The letter gives two dates for this {noun}: {fmt_date(first.due)} (“{_short(first.statement)}”) "
        f"and {fmt_date(second.due)} (“{_short(second.statement)}”). We use the earlier one, {fmt_date(kept)} "
        "— please check which date applies."
    )


def _step(label: str, day: date | None) -> ComputationStep:
    return ComputationStep(
        label=label,
        date=day.isoformat() if day else None,
        rule_id=CONFLICTING_DATES,
        citation=catalog.citation(CONFLICTING_DATES),
    )


def _lead_step(candidate: _Candidate) -> ComputationStep | None:
    """The step before a rival's own computation, saying where in the letter it comes from."""
    rival = candidate.rival
    if rival is None:
        return None
    if rival.letter_date is not None:
        return _step(
            f"The letter also gives {fmt_date(rival.letter_date)} as its own date (“{_short(rival.statement)}”) "
            "— counted from that date:",
            rival.letter_date,
        )
    return _step(f"The letter also says “{_short(rival.statement)}”:", None)


def _other_step(noun: str, candidate: _Candidate, kept: _Candidate, ctx: RuleContext) -> ComputationStep:
    """The step naming a date the letter gives that is not the one kept."""
    rival = candidate.rival
    if rival is None:  # the to-do's own date, as read
        if kept.rival is not None and kept.rival.letter_date is not None and ctx.document_date is not None:
            return _step(
                f"Counted from {fmt_date(ctx.document_date)}, the letter's date as read: {fmt_date(candidate.due)}",
                candidate.due,
            )
        return _step(
            f"The date as read from the letter is {fmt_date(candidate.due)} (“{_short(candidate.statement)}”)",
            candidate.due,
        )
    if rival.letter_date is not None:
        return _step(
            f"Counted from {fmt_date(rival.letter_date)}, the date the letter also gives for itself "
            f"(“{_short(rival.statement)}”): {fmt_date(candidate.due)}",
            candidate.due,
        )
    return _step(
        f"The letter also gives {fmt_date(candidate.due)} for this {noun} (“{_short(candidate.statement)}”)",
        candidate.due,
    )


def settle(
    receipt: ComputationReceipt,
    item: ExtractedItem,
    rivals: Sequence[Rival],
    ctx: RuleContext,
    *,
    postal_buffer_days: int,
) -> Settled | None:
    """The to-do's receipt when the letter gives it another date (``None`` when it gives none): the
    earliest of the dates kept, with the engine's steps for it, a step per other date and one saying
    why the earlier one is kept, a warning naming both dates, rule ``conflicting_dates`` and ``low``
    confidence. ``receipt`` is the to-do's own (graded), computed in ``ctx``."""
    own_due = parse_date(receipt.due_date)
    if own_due is None or not rivals:
        return None
    own = _Candidate(own_due, receipt, item.date.text or item.quote, item.date.type == "fixed")
    others: list[_Candidate] = []
    for rival in rivals:
        found = _rival_candidate(rival, own_due, ctx, postal_buffer_days)
        if found is not None and all(found.due != seen.due for seen in others):
            others.append(found)
    if not others:
        return None
    noun = _noun(item)
    kept = min([own, *others], key=lambda candidate: candidate.due)
    dates = len({own.due, *(other.due for other in others)})
    count = {2: "two", 3: "three"}.get(dates, str(dates))
    lead = _lead_step(kept)
    steps = [
        *([lead] if lead is not None else []),
        *kept.receipt.steps,
        *(_other_step(noun, other, kept, ctx) for other in [own, *others] if other is not kept),
        _step(
            f"The letter gives {count} different dates for this {noun}: we keep the earliest, "
            f"{fmt_date(kept.due)} — acting by it is on time whichever date applies",
            kept.due,
        ),
    ]
    warnings = [_warning(noun, own, other, kept.due, ctx) for other in others]
    later = ", ".join(fmt_date(c.due) for c in sorted([own, *others], key=lambda c: c.due) if c is not kept)
    summary = f"{kept.receipt.summary} The letter also gives {later}; this is the earlier date.".strip()
    rule_ids = [
        *kept.receipt.rule_ids,
        *([] if CONFLICTING_DATES in kept.receipt.rule_ids else [CONFLICTING_DATES]),
    ]
    settled = kept.receipt.model_copy(
        update={
            "steps": steps,
            "rule_ids": rule_ids,
            "warnings": [*kept.receipt.warnings, *warnings],
            "summary": summary,
            "confidence": "low",
        }
    )
    return Settled(settled, kept.fixed)
