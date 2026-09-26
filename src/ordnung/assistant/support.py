"""Claim-level support: which sentences of an Ask answer may stay (ADR 0007, ADR 0008).

Ask's tools answer in two channels (:mod:`ordnung.assistant.channels`): Ordnung's *record* (what
code computed, the person confirmed or the pipeline filed with verified evidence) and the *letter
text* (every word that comes from a letter). An answer is checked sentence by sentence against the
record of the records it cites, with this written policy:

1. **What is checked.** Every sentence of the answer (Markdown lines, list bullets and headings keep
   their structure; citation markers are ignored while reading). A sentence *states* a date or an
   amount when :func:`~ordnung.ingest.verify.parse_dates` or
   :func:`~ordnung.ingest.verify.amount_mentions` find one in it. A sentence made only of citation
   markers belongs to the sentence before it.
2. **Supported.** A stated date or amount is supported when it is in the record part of a record the
   sentence cites — a record that appeared in a record part of this turn's tool results. A record's
   part includes the records listed inside it or linked to it: a letter's to-dos and contracts, a
   contract's letter, a person's to-dos (``doc_id``, ``contract_id``, ``party_id``,
   ``source_doc_id``). Dates without a year match by day and month. Three kinds of values need no
   citation: today's date, what the person wrote in their own questions, and the overview values
   Ordnung's code adds up outside any one record (``today`` and the money totals of
   ``money_summary``).
3. **Quoted.** A date or amount that is not supported may stay only as a quote of a letter: the
   sentence names the letter as its source with one of the phrases in :data:`LETTER_QUOTE` ("the
   letter says …", "laut dem Schreiben …") *and* the value is in the letter text of a record it
   cites. The value is then put in quotation marks (“31.12.2027”) and the answer gets a note that
   quoted values are the letter's words, not Ordnung's.
4. **Removed.** Every other sentence that states a date or amount is removed; a note under the answer
   says how many. A sentence naming a § that is neither in the rules catalog nor in this turn's tool
   results is removed too (the earlier, weaker rule for laws). When nothing is left, Ask answers with
   a fixed fallback instead.

The check is deterministic and linear in the size of the answer and the tool results: each sentence
is parsed once and each value is looked up in hash sets of the cited records.

Known limits — documented, not bugs:

- Support is literal, not semantic: a value in a cited record supports a sentence that says
  something else about it ("you owe the library 640.00 € [item:rent]" passes when the rent to-do
  holds 640.00 €). A letter can therefore still steer *which* record the model cites.
- Dates in words ("next Friday", "end of the month") and claims without a date or amount ("there
  is no deadline") are not read; the prompt and the record are the only defence there.
- A quote is recognised only by the listed phrases; other wording is treated as Ordnung's own claim.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from ordnung.assistant.channels import parse_tool_result
from ordnung.assistant.citations import parse_citations, remove_markers
from ordnung.ingest.verify import DateMention, amount_mentions, parse_dates
from ordnung.secretary.review import paragraphs_in, split_sentences

CITABLE_ID = re.compile(r"(?:doc|itm|ctr|pty)_[a-z0-9]+")
LINK_KEYS = ("doc_id", "contract_id", "party_id", "source_doc_id")
AMOUNT_KEYS = frozenset({"amount", "monthly", "monthly_cost", "due_this_month", "fixed_costs_monthly"})
"""Numeric fields that are money (other numbers — pages, months, counts — never support an amount)."""
AMOUNT_MAPS = frozenset({"fixed_costs_by_category", "fixed_costs_monthly_other_currencies"})
"""Fields whose values are all money (``{"rent": 640.0, …}``)."""
CONTEXT_KEYS = frozenset({"today", *AMOUNT_MAPS, "due_this_month", "fixed_costs_monthly"})
"""Top-level record fields that belong to no one record: overview values Ordnung's code worked out."""

NOTE_PREFIX = "Checked by Ordnung:"
_QUOTE_OPEN, _QUOTE_CLOSE = "“", "”"

_LETTER_WORDS = (
    r"letter|notice|document|reminder|invoice|bill|statement|card|contract|page|text|sender|e-?mail|"
    r"assessment|decision|form"
)
_SAYS = (
    r"says|say|said|states|stated|claims|claimed|writes|wrote|mentions|mentioned|asks|asked|demands|"
    r"demanded|reads|lists|listed|gives|gave|names|named|asserts|asserted|announces|announced"
)
_DE_LETTER = r"Brief|Schreiben|Bescheid|Dokument|Rechnung|Mahnung|Absender|Text|Vertrag|Karte"
_SENDER_SPAN = "{1,60}"  # "the letter from <up to 60 characters> says"; bounded, so matching stays linear
LETTER_QUOTE = re.compile(
    rf"""
      \b(?:the|this|that|your|its|their)\s+(?:{_LETTER_WORDS})(?:'s\s+text)?
        (?:\s+(?:from|of)\s+[^.;:!?\n]{_SENDER_SPAN}?)?\s+(?:also\s+)?(?:{_SAYS})\b
    | \baccording\s+to\s+(?:the|this|that|your)\s+(?:{_LETTER_WORDS})\b
    | \b(?:it|this)\s+says\s+in\s+the\s+(?:{_LETTER_WORDS})\b
    | \b(?:laut|gemäß|gemaess)\s+(?:dem\s+|des\s+|diesem\s+|diesen\s+|ihrem\s+|ihres\s+)?(?:{_DE_LETTER})s?\b
    | \b(?:im|in\s+dem|in\s+diesem)\s+(?:{_DE_LETTER})\s+(?:steht|heißt\s+es|wird\s+behauptet)\b
    | \b(?:der|das|die|dieser|dieses|diese)\s+(?:{_DE_LETTER})\s+(?:sagt|schreibt|behauptet|nennt|gibt\s+an|
        verlangt|fordert|erwähnt)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
"""The phrases that make a sentence a quote of a letter (policy rule 3). When in doubt, it is not."""

_BULLET_PREFIX = re.compile(r"^(\s*(?:[-*+]\s+|#{1,6}\s+|>\s*)?)")
_NUMBER_CHAR = re.compile(r"[\d.,]")
_CURRENCY_AFTER = re.compile(r"(?:\s?(?:€|EUR\b|Euro\b|euros?\b))", re.IGNORECASE)
_CURRENCY_BEFORE = re.compile(r"(?:€|EUR|Euro)\s?$", re.IGNORECASE)
_WEEKDAY_BEFORE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\.?,?\s$"
)

Verdict = Literal["kept", "quoted", "removed"]


# --------------------------------------------------------------------------------------------------
# facts
# --------------------------------------------------------------------------------------------------


@dataclass
class FactSet:
    """Dates (full, and by day and month) and amounts (in cents) — a record's, a letter's or context."""

    dates: set[date] = field(default_factory=set)
    day_months: set[tuple[int, int]] = field(default_factory=set)
    cents: set[int] = field(default_factory=set)

    def add_text(self, text: str) -> None:
        """Every date and amount written in ``text``."""
        for mention in parse_dates(text):
            self.day_months.add((mention.day, mention.month))
            if (full := mention.as_date()) is not None:
                self.dates.add(full)
        for _, value in amount_mentions(text):
            self.add_amount(value)

    def add_amount(self, value: float) -> None:
        self.cents.add(round(value * 100))

    def add_date(self, value: date) -> None:
        self.dates.add(value)
        self.day_months.add((value.day, value.month))

    def has_date(self, mention: DateMention) -> bool:
        full = mention.as_date()
        return full in self.dates if full is not None else (mention.day, mention.month) in self.day_months

    def has_amount(self, value: float) -> bool:
        return round(value * 100) in self.cents


_EMPTY = FactSet()


@dataclass(frozen=True)
class Value:
    """A date or amount stated in a sentence: its text as written and its readings."""

    text: str
    dates: tuple[DateMention, ...] = ()
    amount: float | None = None

    def found_in(self, facts: FactSet) -> bool:
        if self.amount is not None:
            return facts.has_amount(self.amount)
        return any(facts.has_date(reading) for reading in self.dates)  # a slash date may read two ways


def stated_values(text: str) -> list[Value]:
    """The dates and amounts ``text`` states (citation markers already removed)."""
    readings: dict[str, list[DateMention]] = defaultdict(list)
    for mention in parse_dates(text):
        readings[mention.text].append(mention)
    values = [Value(raw, dates=tuple(found)) for raw, found in readings.items()]
    values += [Value(raw, amount=amount) for raw, amount in amount_mentions(text)]
    return values


# --------------------------------------------------------------------------------------------------
# what this turn's tool results establish
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TurnEvidence:
    """What the tool results of one Ask turn establish, by record id.

    ``record``: the dates and amounts of each record's record part (and of the records inside it or
    linked to it); ``letters``: those of its letter text (and of the records crediting it);
    ``context``: values that need no citation; ``seen_ids``: every citable id in a record part;
    ``paragraphs``: the § citations known from the rules catalog and the tool results.
    """

    record: Mapping[str, FactSet]
    letters: Mapping[str, FactSet]
    context: FactSet
    seen_ids: frozenset[str]
    paragraphs: frozenset[tuple[str, str | None]]

    @classmethod
    def from_results(
        cls,
        results: Iterable[str],
        *,
        today: date,
        person: Iterable[str] = (),
        catalog: Iterable[str] = (),
    ) -> TurnEvidence:
        """Read the turn's rendered tool results; ``person`` are the person's own questions."""
        collector = _Collector()
        collector.context.add_date(today)
        for text in person:
            collector.context.add_text(text)
        paragraphs: set[tuple[str, str | None]] = set()
        for text in catalog:
            paragraphs.update(paragraphs_in(text))
        letter_bags: dict[str, FactSet] = defaultdict(FactSet)
        for text in results:
            paragraphs.update(paragraphs_in(text))
            parsed = parse_tool_result(text)
            if parsed.record is not None:
                collector.walk(parsed.record)
            for record_id, fields in parsed.letters.items():
                if isinstance(record_id, str):
                    _collect_letter(fields, letter_bags[record_id], money=False, key=None)
        letters: dict[str, FactSet] = defaultdict(FactSet)
        for record_id, bag in letter_bags.items():
            for owner in collector.credit.get(record_id, {record_id}):
                _merge(letters[owner], bag)
        return cls(
            record=dict(collector.record),
            letters=dict(letters),
            context=collector.context,
            seen_ids=frozenset(collector.seen),
            paragraphs=frozenset(paragraphs),
        )

    def supports(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 2: in the context, or in the record part of a cited record."""
        return value.found_in(self.context) or any(
            value.found_in(self.record.get(ref_id, _EMPTY)) for ref_id in cited
        )

    def quotes(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 3 (second half): in the letter text of a cited record."""
        return any(value.found_in(self.letters.get(ref_id, _EMPTY)) for ref_id in cited)

    def knows_paragraph(self, number: str, law: str | None) -> bool:
        """A § citation from the catalog or the tool results (a bare number: any law with it)."""
        if law is not None:
            return (number, law) in self.paragraphs
        return any(known == number for known, _ in self.paragraphs)


class _Collector:
    """Walks record parts: which record ids get credit for each value (itself, parents and links)."""

    def __init__(self) -> None:
        self.record: dict[str, FactSet] = defaultdict(FactSet)
        self.credit: dict[str, set[str]] = defaultdict(set)
        self.context = FactSet()
        self.seen: set[str] = set()

    def walk(self, node: Any) -> None:
        """Collect one record part (its top-level overview fields are the context)."""
        self._visit(node, frozenset(), key=None, money=False, context=False, top=True)

    def _visit(
        self,
        node: Any,
        owners: frozenset[str],
        *,
        key: str | None,
        money: bool,
        context: bool,
        top: bool = False,
    ) -> None:
        if isinstance(node, dict):
            here = owners | frozenset(_citable_ids(node))
            own = node.get("id")
            if isinstance(own, str) and CITABLE_ID.fullmatch(own):
                self.credit[own].update(here)
            for child_key, value in node.items():
                self._visit(
                    value,
                    here,
                    key=child_key,
                    money=money or child_key in AMOUNT_MAPS,
                    context=context or (top and child_key in CONTEXT_KEYS),
                )
        elif isinstance(node, list):
            for value in node:
                self._visit(value, owners, key=key, money=money, context=context)
        else:
            self._scalar(node, owners, key=key, money=money, context=context)

    def _scalar(
        self, value: Any, owners: frozenset[str], *, key: str | None, money: bool, context: bool
    ) -> None:
        bags = [self.record[owner] for owner in owners] or ([self.context] if context else [])
        if isinstance(value, str):
            if CITABLE_ID.fullmatch(value):
                self.seen.add(value)
                return
            for bag in bags:
                bag.add_text(value)
        elif isinstance(value, int | float) and not isinstance(value, bool) and (money or key in AMOUNT_KEYS):
            for bag in bags:
                bag.add_amount(float(value))


def _citable_ids(node: Mapping[str, Any]) -> Iterator[str]:
    """The record's own id and the records it links to."""
    for key in ("id", *LINK_KEYS):
        value = node.get(key)
        if isinstance(value, str) and CITABLE_ID.fullmatch(value):
            yield value


def _collect_letter(node: Any, bag: FactSet, *, money: bool, key: str | None) -> None:
    if isinstance(node, dict):
        for child_key, value in node.items():
            _collect_letter(value, bag, money=money or child_key in AMOUNT_MAPS, key=child_key)
    elif isinstance(node, list):
        for value in node:
            _collect_letter(value, bag, money=money, key=key)
    elif isinstance(node, str):
        bag.add_text(node)
    elif isinstance(node, int | float) and not isinstance(node, bool) and (money or key in AMOUNT_KEYS):
        bag.add_amount(float(node))


def _merge(target: FactSet, source: FactSet) -> None:
    target.dates |= source.dates
    target.day_months |= source.day_months
    target.cents |= source.cents


# --------------------------------------------------------------------------------------------------
# checking an answer
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SentenceCheck:
    """The verdict on one sentence that states a date, an amount or a §.

    ``values``: what it states, as written; ``unsupported``: those not in the record part of a record
    it cites; ``result``: the sentence as it stays in the answer (empty when removed).
    """

    text: str
    verdict: Verdict
    values: tuple[str, ...]
    unsupported: tuple[str, ...] = ()
    result: str = ""


@dataclass(frozen=True)
class CheckedAnswer:
    """The answer after the check, and the verdict on every sentence that stated something checkable."""

    text: str
    sentences: tuple[SentenceCheck, ...]

    @property
    def removed(self) -> list[SentenceCheck]:
        return [check for check in self.sentences if check.verdict == "removed"]

    @property
    def quoted(self) -> list[SentenceCheck]:
        return [check for check in self.sentences if check.verdict == "quoted"]

    def note(self) -> str | None:
        """The visible note under the answer (``None`` when nothing was left out or quoted)."""
        parts = []
        removed = len(self.removed)
        if removed == 1:
            parts.append(
                "1 sentence was left out because its date or amount could not be matched to your records."
            )
        elif removed:
            parts.append(
                f"{removed} sentences were left out because their dates or amounts could not be matched to "
                "your records."
            )
        if self.quoted:
            parts.append(
                f"Values in {_QUOTE_OPEN}quotation marks{_QUOTE_CLOSE} are quoted from a letter; "
                "Ordnung has not confirmed them."
            )
        return f"{NOTE_PREFIX} {' '.join(parts)}" if parts else None


def check_answer(text: str, evidence: TurnEvidence, *, citable: Collection[str]) -> CheckedAnswer:
    """Apply the policy of this module to ``text``; ``citable`` are the ids that may stay cited."""
    lines: list[str] = []
    checks: list[SentenceCheck] = []
    for line in text.splitlines():
        prefix = _BULLET_PREFIX.match(line)
        lead = prefix.group(1) if prefix else ""
        body = line[len(lead) :]
        if not body.strip():
            lines.append(line)
            continue
        kept = []
        for sentence in sentences_of(body):
            check = check_sentence(sentence, evidence, citable=citable)
            if check is None:
                kept.append(sentence)
                continue
            checks.append(check)
            if check.result:
                kept.append(check.result)
        if kept:
            lines.append(lead + " ".join(kept))
    return CheckedAnswer("\n".join(lines), tuple(checks))


def sentences_of(body: str) -> list[str]:
    """:func:`split_sentences`, with citation markers that open a sentence (``Due 30 Sep. [item:x]
    Then …``) moved to the sentence before, which they belong to."""
    sentences: list[str] = []
    for sentence in split_sentences(body):
        end = 0
        for citation in parse_citations(sentence):
            start, stop = citation.span
            if sentence[end:start].strip(" \t.,;:"):
                break
            end = stop
        leading, rest = sentence[:end].strip(), sentence[end:].strip()
        if leading and sentences:
            sentences[-1] = f"{sentences[-1]} {leading}"
        elif leading:
            rest = sentence
        if rest.strip(" \t.,;:"):
            sentences.append(rest)
        elif rest and sentences:
            sentences[-1] += rest
    return sentences


def check_sentence(
    sentence: str, evidence: TurnEvidence, *, citable: Collection[str]
) -> SentenceCheck | None:
    """The verdict on one sentence (``None`` when it states no date, amount or §)."""
    plain = remove_markers(sentence)
    values = stated_values(plain)
    laws = list(paragraphs_in(plain))
    if not values and not laws:
        return None
    stated = tuple(value.text for value in values)
    unknown_laws = [
        f"§ {number} {law or ''}".strip() for number, law in laws if not evidence.knows_paragraph(number, law)
    ]
    if unknown_laws:
        return SentenceCheck(sentence, "removed", stated, tuple(unknown_laws))
    cited = [citation.id for citation in parse_citations(sentence) if citation.id in citable]
    missing = [value for value in values if not evidence.supports(value, cited)]
    if not missing:
        return SentenceCheck(sentence, "kept", stated, result=sentence)
    unsupported = tuple(value.text for value in missing)
    if LETTER_QUOTE.search(plain) and all(evidence.quotes(value, cited) for value in missing):
        quoted = sentence
        for value in missing:
            quoted = quote_value(quoted, value.text)
        return SentenceCheck(sentence, "quoted", stated, unsupported, result=quoted)
    return SentenceCheck(sentence, "removed", stated, unsupported)


def quote_value(sentence: str, needle: str) -> str:
    """``sentence`` with the first unquoted ``needle`` (plus its currency or weekday) in quotation marks."""
    start = 0
    while (found := sentence.find(needle, start)) >= 0:
        begin, end = found, found + len(needle)
        start = end
        if _NUMBER_CHAR.match(sentence[begin - 1 : begin]) or sentence[end : end + 1].isdigit():
            continue  # part of a longer number
        if after := _CURRENCY_AFTER.match(sentence, end):
            end = after.end()
        head = sentence[:begin]
        if before := _CURRENCY_BEFORE.search(head) or _WEEKDAY_BEFORE.search(head):
            begin = before.start()
        if sentence[begin - 1 : begin] != _QUOTE_OPEN:
            return f"{sentence[:begin]}{_QUOTE_OPEN}{sentence[begin:end]}{_QUOTE_CLOSE}{sentence[end:]}"
    return sentence
