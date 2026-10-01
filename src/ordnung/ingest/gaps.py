"""A reading that came back incomplete, and the one to-do code files for it (SPEC § 8 stage 5).

The extraction schema requires only a letter's kind, title, summary and explanation, so a valid answer can
leave out everything a person acts on — a prompt injection's aim, or a model that half-obeys one. After
quote verification, code checks every reading against the letter's own **visible** text (``Page.text``, a
photo's transcript; never ``Page.hidden``), with two rules (:func:`reading_gap`; the first wins):

* ``empty`` — nothing a person could act on or file came back: no to-do, no sender, no letter date, no key
  fact, no reference, no contract, change or payment details, and no remedy;
* ``remedy_left_out`` — the letter explains how to object within a period (:func:`remedy_notices`) and shows
  an administrative act, but no to-do of the reading dates the objection (whatever its ``remedy`` field
  says). Never for the kinds of letter whose deadlines the law already files (:data:`LAW_DATED_KINDS`).

Either way the letter gets **one** to-do in slot :data:`CHECK_SLOT` (:func:`check_item`), always ``low`` and
"Please check" (:data:`~ordnung.ingest.verify.READING_INCOMPLETE`): the objection deadline the letter's own
notice states — its shortest period, counted from the earliest date the letter gives for itself
(:func:`letter_date`), so a period or a date planted in the letter can only make it earlier — or, without a
notice, an undated "Read this letter yourself". Nothing here calls a model; the reading itself (its sender,
date and remedy) stays as the model gave it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from ordnung.ingest.conflicts import header, letter_statements, sentences
from ordnung.ingest.normalize import fold_punctuation
from ordnung.ingest.verify import PageInput, date_spans, parse_periods
from ordnung.models import (
    DateSpec,
    DocumentExtraction,
    ExtractedChange,
    ExtractedContract,
    ExtractedItem,
    PaymentDetails,
)
from ordnung.rules.delivery import shows_administrative_act
from ordnung.rules.routing import letter_kind

__all__ = [
    "CHECK_SLOT",
    "LAW_DATED_KINDS",
    "CheckKind",
    "Gap",
    "RemedyNotice",
    "check_item",
    "gap_warning",
    "letter_date",
    "reading_gap",
    "remedy_notices",
]

#: Slot of the to-do code files for an incomplete reading (one per letter).
CHECK_SLOT = "check:reading"
#: The kinds of letter whose deadlines the law files itself (``routing.derived_deadlines``, through
#: ``plan.law_deadlines``): a court payment order read as "pay" still gets "pay or object", so a reading
#: that leaves their objection out is no gap.
LAW_DATED_KINDS = frozenset(
    {"court_payment_order", "enforcement_order", "dismissal", "landlord_notice", "rent_increase"}
)

Gap = Literal["empty", "remedy_left_out"]
#: The to-do :func:`check_item` files: a dated objection deadline, one whose start the letter doesn't give,
#: or an undated "Read this letter yourself".
CheckKind = Literal["dated", "undated", "read_yourself"]
Unit = Literal["days", "weeks", "months"]

_REMEDY = re.compile(
    r"widerspr\w*|einspr\w*|\bklage\w*|\bklagen\b|\bobjection\w*|\bobject\b|\bappeal\w*", re.IGNORECASE
)
_GERMAN_REMEDY = re.compile(r"widerspr\w*|einspr\w*|\bklage\w*|\bklagen\b", re.IGNORECASE)
#: A sentence after the notice that speaks of money is no part of it.
_PAYMENT = re.compile(r"zahl|überweis|fällig|betrag|\bpay\w*|\bdue\b", re.IGNORECASE)
_MONTH_PERIOD = re.compile(r"\bmonatsfrist\b", re.IGNORECASE)
#: A period that ends before an event ("vor Ablauf …") is no period to object within.
_BACKWARD = re.compile(r"\bvor\s+(?:der|dem|ablauf|beendigung|ende)\b|\bbefore\s+the\s+end\b", re.IGNORECASE)
#: Counted from notification (Bekanntgabe): deemed delivery after the letter's date.
_NOTIFIED = re.compile(r"bekanntgabe|bekannt\s*gegeben|bekanntgegeben|\bnotif\w*", re.IGNORECASE)
#: Counted from formal service or arrival: from the letter's date itself, the earliest it can have arrived.
_ARRIVAL = re.compile(
    r"zustell\w*|zugestellt|\bzugang\b|zugegangen|\berhalt\b|\breceipt\b|\bservice\b|\bserved\b",
    re.IGNORECASE,
)
#: "Musterstadt, 06.11.2026" / "Musterstadt, den 06.11.2026": a place and the letter's date on page 1.
_PLACE_DATE = re.compile(r"^[A-ZÄÖÜ][\w .\-/()]{1,40},\s*(?:den\s+)?$")
#: A line that labels the date under it as another one ("Antrag vom", "geboren am").
_ANOTHER = re.compile(r"\b(?:vom|seit|bis|ab|am|zum|antrag\w*|geboren|geburtsdatum)\s*:?\s*$", re.IGNORECASE)
_UNITS: dict[str, Unit] = {"days": "days", "weeks": "weeks", "months": "months"}
_DAYS: dict[str, int] = {"days": 1, "weeks": 7, "months": 31}
_REMEDIES = (("widerspr", "widerspruch"), ("einspr", "einspruch"), ("klage", "klage"))
_TITLES = {
    "widerspruch": "Deadline to object (Widerspruch)",
    "einspruch": "Deadline to object (Einspruch)",
    "klage": "Deadline for a court action (Klage)",
}

DEADLINE_ACTION = (
    "If you disagree with this decision, send your objection so that it arrives by this date. Ordnung worked "
    "this date out from the letter's own instructions on how to object — check it against the letter first."
)
DEADLINE_CONSEQUENCE = "After this date the decision can usually no longer be challenged."
PLACEHOLDER_ACTION = (
    "Claude's reading of this letter came back almost blank. Read the letter, add any date it asks you to act "
    "by, then mark this to-do done."
)
_PREFIX: dict[Gap, str] = {
    "empty": "Claude's reading of this letter came back almost blank: the sender, the letter's date and its "
    "to-dos were all left out.",
    "remedy_left_out": "This letter explains how to object, but Claude's reading left out the deadline to object.",
}
_SUFFIX: dict[CheckKind, str] = {
    "dated": "Ordnung worked the deadline out from the letter's own instructions on how to object "
    "(Rechtsbehelfsbelehrung) — please check it against the letter before you rely on it.",
    "undated": "Ordnung found the letter's instructions on how to object but couldn't work out the deadline from "
    "them — please find it in the letter and enter it.",
    "read_yourself": "Please read the letter yourself and add anything it asks you to do.",
}


@dataclass(frozen=True)
class RemedyNotice:
    """A sentence of the letter that says how to object within a period — with the sentence after it when that
    one goes on about the period: its words (``quote``, as folded), the page it is on, the period, whether it
    counts from notification (``notified``: deemed delivery) or from service or arrival, and the remedy it
    names (``widerspruch``, ``einspruch``, ``klage`` or ``objection``)."""

    page: int
    quote: str
    amount: int
    unit: Unit
    notified: bool
    remedy: str

    @property
    def days(self) -> int:
        """The period's length for ranking, a month as 31 days."""
        return self.amount * _DAYS[self.unit]


def _page_number(page: PageInput) -> int:
    return page[0] if isinstance(page, tuple) else page.page


def _visible(page: PageInput) -> str:
    """The page's visible text (a photo's transcript), never its hidden text."""
    return page[1] if isinstance(page, tuple) else page.text


def _remedy(sentence: str) -> str:
    found = _REMEDY.search(sentence)
    word = found.group().casefold() if found else ""
    return next((remedy for stem, remedy in _REMEDIES if word.startswith(stem)), "objection")


def remedy_notices(pages: Sequence[PageInput]) -> list[RemedyNotice]:
    """Every sentence of the visible text naming a remedy (Widerspruch, Einspruch, Klage, objection, appeal)
    with a forward period of days, weeks or months (1 to 12) in it — or, when it has none, in it and the
    sentence after it, which counts only when it names neither a remedy nor a payment. "Monatsfrist" is one
    month; a period before an event ("vor Ablauf …") is none; of several periods the shortest counts."""
    found: list[RemedyNotice] = []
    for page in pages:
        folded = sentences(_visible(page))
        for index, sentence in enumerate(folded):
            if not _REMEDY.search(sentence):
                continue
            following = folded[index + 1] if index + 1 < len(folded) else ""
            candidates = [sentence]
            if following and not _REMEDY.search(following) and not _PAYMENT.search(following):
                candidates.append(f"{sentence} {following}")
            for candidate in candidates:  # the sentence alone first: the next one never changes its period
                words = _MONTH_PERIOD.sub("einen Monat", candidate)
                periods = [
                    (amount, _UNITS[unit])
                    for amount, unit in parse_periods(words)
                    if unit in _UNITS and 0 < amount <= 12
                ]
                if periods:
                    break
            if not periods or _BACKWARD.search(candidate):
                continue
            amount, unit = min(periods, key=lambda period: period[0] * _DAYS[period[1]])
            notified = bool(_NOTIFIED.search(candidate)) and not _ARRIVAL.search(candidate)
            found.append(
                RemedyNotice(
                    page=_page_number(page),
                    quote=" ".join(candidate.split()),
                    amount=amount,
                    unit=unit,
                    notified=notified,
                    remedy=_remedy(sentence),
                )
            )
    return found


def _blank(details: ExtractedContract | ExtractedChange | PaymentDetails | None) -> bool:
    """A part of the reading that is absent, or holds nothing but its defaults and empty values (a contract's
    required name left blank)."""
    if details is None:
        return True
    dump = details.model_dump(exclude_defaults=True)
    return not any(value.strip() if isinstance(value, str) else value for value in dump.values())


def _empty(extraction: DocumentExtraction) -> bool:
    sender = extraction.sender
    remedy = extraction.remedy
    return (
        not extraction.items
        and (sender is None or not sender.name.strip())
        and not extraction.document_date
        and not extraction.key_facts
        and not extraction.references
        and all(_blank(details) for details in (extraction.contract, extraction.change, extraction.payment))
        and (remedy is None or remedy.type == "none")
    )


def reading_gap(
    extraction: DocumentExtraction, pages: Sequence[PageInput], notices: Sequence[RemedyNotice]
) -> Gap | None:
    """Why the reading is incomplete (module docstring), or ``None``. Its warnings, kind, title, summary and
    explanation are never looked at. A left-out objection counts only on a letter whose visible text shows an
    administrative act (:func:`~ordnung.rules.delivery.shows_administrative_act`: not a direct debit's or a
    contract's right to object), filed as a kind the law doesn't date itself (:data:`LAW_DATED_KINDS`), and
    only when no to-do dates an objection — a ``remedy`` the reading copied without its date doesn't count."""
    if _empty(extraction):
        return "empty"
    if (
        notices
        and shows_administrative_act("\n".join(_visible(page) for page in pages))
        and letter_kind(extraction) not in LAW_DATED_KINDS
        and not any(item.date.nature == "objection" and item.date.type != "none" for item in extraction.items)
    ):
        return "remedy_left_out"
    return None


def _iso(value: str | None) -> date | None:
    """An ISO date as the rules engine reads one (``rules.deadlines.parse_date``)."""
    try:
        return date.fromisoformat(value.strip()[:10]) if value else None
    except ValueError:
        return None


def _header_dates(pages: Sequence[PageInput]) -> list[date]:
    """The dates page 1 gives for the letter when no reader of :func:`letter_statements` finds one: on a line of
    its own before the first remedy, a single date that reads one way and ends the line, either after a place
    ("Musterstadt, (den) 06.11.2026") or — in the header, not under a line that labels another date ("Antrag
    vom") — alone. A place's dates first, else the header's."""
    if not pages:
        return []
    lines = fold_punctuation(_visible(pages[0])).splitlines()
    rows = len(header(lines))
    placed: list[date] = []
    bare: list[date] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _GERMAN_REMEDY.search(stripped):
            break
        spans = date_spans(stripped)
        if len(spans) != 1:
            continue
        start, end, mention = spans[0]
        day = mention.as_date()
        if day is None or mention.ambiguous or end != len(stripped):
            continue
        before = stripped[:start]
        if _PLACE_DATE.match(before):
            placed.append(day)
        elif not before.strip() and index < rows:
            previous = lines[index - 1].rstrip() if index else ""
            if not _ANOTHER.search(previous):
                bare.append(day)
    return placed or bare


def letter_date(extraction: DocumentExtraction, pages: Sequence[PageInput]) -> date | None:
    """The earliest date the letter gives for itself — its header's "Datum:", "mit diesem Bescheid vom …"
    (:func:`~ordnung.ingest.conflicts.letter_statements`), else a date on a line of its own on page 1
    (:func:`_header_dates`) — or the reading gives it; ``None`` when there is none."""
    days = [statement.letter_date for statement in letter_statements(pages) if statement.letter_date]
    if not days:
        days = _header_dates(pages)
    read = _iso(extraction.document_date)
    return min([*days, *([read] if read else [])], default=None)


def _choose(notices: Sequence[RemedyNotice]) -> tuple[RemedyNotice, bool]:
    """The notice whose deadline comes first, and whether it counts with delivery days: the shortest period
    (a month as 31 days — with periods of 1 to 12 days, weeks or months that order is the calendar's), on a tie
    the one without delivery days. Delivery days count only when every notice counts from notification: four
    weeks after notification can end after one month from service, so a notice with a start of its own (planted
    or not) never makes the date later either."""
    notice = min(notices, key=lambda found: (found.days, found.notified))
    return notice, notice.notified and all(found.notified for found in notices)


def check_item(
    extraction: DocumentExtraction, pages: Sequence[PageInput]
) -> tuple[Gap, ExtractedItem, CheckKind] | None:
    """The to-do an incomplete reading gets (module docstring), why, and which kind it is; ``None`` for a
    complete reading.

    With a remedy notice, a ``deadline``: the notice's period counted from the letter's date
    (:func:`letter_date`, carried in the DateSpec's ``anchor_date``, so it computes without a date in the
    reading and keeps it when recomputed) — with deemed delivery after a notification ("nach Bekanntgabe";
    the earlier of that date and the letter's date as stored counts), else from that date itself, fixed
    (formal service or arrival can't be before the letter's date). Without one, a ``task``: read the letter."""
    notices = remedy_notices(pages)
    gap = reading_gap(extraction, pages, notices)
    if gap is None:
        return None
    if not notices:
        placeholder = ExtractedItem(
            kind="task",
            title="Read this letter yourself",
            action=PLACEHOLDER_ACTION,
            date=DateSpec(type="none"),
            priority="high",
            quote="",
        )
        return gap, placeholder, "read_yourself"
    written = letter_date(extraction, pages)
    notice, notified = _choose(notices)
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery" if notified else "explicit_date",
        anchor_date=written.isoformat() if written else None,
        amount=notice.amount,
        unit=notice.unit,
        delivery_rule="de_admin_post" if notified else "none",
        shift_rule="auto",
        nature="objection",
        text=notice.quote,
    )
    deadline = ExtractedItem(
        kind="deadline",
        title=_TITLES.get(notice.remedy, "Deadline to object"),
        action=DEADLINE_ACTION,
        consequence=DEADLINE_CONSEQUENCE,
        date=spec,
        priority="high",
        quote=notice.quote,
    )
    return gap, deadline, "dated" if written else "undated"


def gap_warning(gap: Gap, kind: CheckKind) -> str:
    """The letter's warning for an incomplete reading: why (``gap``), then what Ordnung did (``kind``)."""
    return f"{_PREFIX[gap]} {_SUFFIX[kind]}"
