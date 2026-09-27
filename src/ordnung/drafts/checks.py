"""Deterministic checks on a letter draft (SPEC §11, §21).

Every check takes the draft and a :class:`CheckContext` (what the ledger knows: reference numbers,
the source letter's text, profile and party details, send guidance) and returns a
:class:`~ordnung.models.DraftCheck` with a plain-English label and, when it fails, what to fix.
Checks never change the draft; they are re-run after every edit.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from functools import cache

from ordnung.db.store import normalize_identifier
from ordnung.drafts.templates import format_date
from ordnung.models import Draft, DraftCheck, SendGuidance
from ordnung.rules import list_rules


@dataclass(frozen=True)
class CheckContext:
    """What a draft is checked against.

    ``references`` are the customer/reference numbers the recipient knows the matter by;
    ``known_ids`` are structured identifiers the letter may repeat (customer numbers, IBANs, the
    person's phone and e-mail); ``known_texts`` are free texts whose identifiers are allowed too
    (addresses, the source letter); ``source_text`` is the source letter's text (for § citations);
    ``channel`` is how the person sends (or sent) the letter.
    """

    references: tuple[str, ...] = ()
    doc_date: date | None = None
    known_ids: tuple[str, ...] = ()
    known_texts: tuple[str, ...] = ()
    source_text: str = ""
    guidance: SendGuidance | None = None
    channel: str | None = None


LABELS: dict[str, str] = {
    "has_reference": "Mentions your customer or reference number",
    "has_dates": "States the dates that matter",
    "recipient_complete": "Recipient's name and address are complete",
    "sender_complete": "Your name and address are complete",
    "no_placeholders": "No placeholders left to fill in",
    "language_matches": "Written in the letter's language",
    "citations_known": "Only laws Ordnung knows are cited",
    "no_new_identifiers": "No unknown account numbers, e-mails or ID numbers",
    "delivery_channel_ok": "Sent in a way that counts",
}

_MIN_REFERENCE_CHARS = 3
_MIN_ID_DIGITS = 6
_POSTCODE_RE = re.compile(r"(?:^|\s)(?:[A-Z]{1,2}-)?\d{4,5}\s+\S")
_STREET_RE = re.compile(r"^(?:Postfach\s+\d|.*[A-Za-zÄÖÜäöüß].*\d)", re.I)
_PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{0,40}\]?|\{[^}\n]{0,40}\}?|\]|\}|\bX{3,}\b|\bTODO\b", re.I)
_DE_DATE_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b")
_EN_DATE_RE = re.compile(
    r"\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December) \d{4}\b"
)
_NEXT_POSSIBLE = ("nächstmöglichen zeitpunkt", "earliest possible date")
_WORD_RE = re.compile(r"[a-zäöüß]+")
_STOPWORDS: dict[str, frozenset[str]] = {
    "de": frozenset(
        [
            "der",
            "die",
            "das",
            "den",
            "dem",
            "des",
            "und",
            "ich",
            "sie",
            "ihnen",
            "ihr",
            "ihre",
            "ihren",
            "zum",
            "zur",
            "mit",
            "von",
            "vom",
            "bitte",
            "für",
            "ein",
            "eine",
            "einen",
            "nicht",
            "ist",
            "wir",
            "hiermit",
            "sowie",
            "auf",
            "an",
            "zu",
            "dass",
            "mir",
            "mich",
            "mein",
            "meine",
            "meinen",
            "vielen",
            "dank",
            "sehr",
            "geehrte",
            "damen",
            "herren",
            "grüßen",
            "freundlichen",
            "gegen",
            "ein",
            "ich",
            "habe",
            "haben",
            "wird",
            "wurde",
            "bei",
            "nach",
        ]
    ),
    "en": frozenset(
        [
            "the",
            "and",
            "to",
            "of",
            "i",
            "you",
            "your",
            "is",
            "for",
            "please",
            "with",
            "this",
            "that",
            "my",
            "we",
            "on",
            "be",
            "are",
            "have",
            "would",
            "dear",
            "thank",
            "hereby",
            "as",
            "it",
            "at",
            "by",
            "from",
            "an",
            "a",
            "sir",
            "madam",
            "yours",
            "faithfully",
            "will",
        ]
    ),
}
_MIN_STOPWORDS = 2

# § citations: "§ 573c Abs. 1, 4 BGB", "§§ 355, 357 AO", "§ 175 Abs. 4 SGB V"
_QUALIFIER = r"(?:Abs\.|Absatz|S\.|Satz|Nr\.|Nummer|Alt\.|Halbsatz|lit\.)"
_LAW = r"[A-ZÄÖÜ][A-Za-zÄÖÜäöü]*[A-ZÄÖÜ](?:\s+[IVX]{1,4}\b)?"
_CITATION_RE = re.compile(
    rf"(?P<mark>§§?)\s*(?P<body>\d+[a-z]?(?:\s*(?:,|und|bis|–|-|{_QUALIFIER})*\s*\d+[a-z]?\b)*)"
    rf"(?:\s+(?P<law>{_LAW}))?"
)
_CITATION_NUMBER_RE = re.compile(rf"(?P<qualifier>{_QUALIFIER})?\s*(?P<number>\d+[a-z]?)")

# identifiers: IBANs, e-mail addresses and long numbers (≥ 6 digits, "/" and "-" allowed inside)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_NUMBER_RE = re.compile(r"(?<![\d/-])\d(?:[\d/-]*\d)?(?![\d/-])")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check(check_id: str, ok: bool, detail: str | None) -> DraftCheck:
    return DraftCheck(id=check_id, label=LABELS[check_id], ok=ok, detail=detail)


def _letter_text(draft: Draft) -> str:
    return f"{draft.subject}\n{draft.body}"


def _parts(block: str) -> list[str]:
    return [part.strip() for line in block.splitlines() for part in line.split(",") if part.strip()]


# --------------------------------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------------------------------


def has_reference(draft: Draft, context: CheckContext) -> DraftCheck:
    """The subject or body repeats a customer/reference number (or the date of their letter)."""
    text = normalize_identifier(_letter_text(draft))
    references = [ref for ref in context.references if len(normalize_identifier(ref)) >= _MIN_REFERENCE_CHARS]
    found = next((ref for ref in references if normalize_identifier(ref) in text), None)
    if found is not None:
        return _check("has_reference", True, f"Mentions {found}.")
    if references:
        listed = ", ".join(references[:3])
        return _check("has_reference", False, f"Add your reference so they can find your file: {listed}.")
    if context.doc_date is not None and _mentions_date(draft, context.doc_date):
        return _check(
            "has_reference", True, f"Refers to their letter of {format_date(context.doc_date, 'de')}."
        )
    return _check(
        "has_reference",
        False,
        "We don't know a customer or reference number for this letter — add one if you have it, so "
        "they can find your file.",
    )


def _mentions_date(draft: Draft, day: date) -> bool:
    text = _letter_text(draft)
    return format_date(day, "de") in text or format_date(day, "en") in text


def _any_date(text: str) -> bool:
    return bool(_DE_DATE_RE.search(text) or _EN_DATE_RE.search(text))


#: Template letters that need a date in them: (passed, what to add).
_DATED_TEMPLATES: dict[str, tuple[str, str]] = {
    "withdrawal": (
        "Names when you ordered or received it.",
        "Add when you ordered or received it, so they find your order.",
    ),
    "extension_request": ("Names the new date you ask for.", "Name the new date you ask for."),
    "payment_plan": ("Names when the instalments start.", "Name the day of the first instalment."),
    "defect_notice": (
        "Says since when, or by when it should be fixed.",
        "Say since when the defect exists or by when it should be fixed.",
    ),
    "deposit_return": ("Names when you handed the flat back.", "Add the day you handed the flat back."),
}


def has_dates(draft: Draft, context: CheckContext) -> DraftCheck:
    """Cancellations name the end date (or "nächstmöglichen Zeitpunkt"); objections the decision date;
    template letters the date they are about (:data:`_DATED_TEMPLATES`)."""
    body = draft.body
    if draft.kind in _DATED_TEMPLATES:
        passed, missing = _DATED_TEMPLATES[draft.kind]
        return _check("has_dates", _any_date(body), passed if _any_date(body) else missing)
    if draft.kind == "cancellation":
        if _any_date(body) or any(phrase in body.casefold() for phrase in _NEXT_POSSIBLE):
            return _check("has_dates", True, "Says when the contract should end.")
        return _check(
            "has_dates",
            False,
            "Say when the contract should end — a date, or „zum nächstmöglichen Zeitpunkt“.",
        )
    if draft.kind == "objection":
        if context.doc_date is not None:
            if _mentions_date(draft, context.doc_date):
                return _check("has_dates", True, "Names the date of the decision.")
            day = format_date(context.doc_date, "de")
            return _check("has_dates", False, f"Name the date of the decision you object to ({day}).")
        if _any_date(body):
            return _check("has_dates", True, "Names the date of the decision.")
        return _check("has_dates", False, "Add the date of the decision you object to.")
    return _check("has_dates", True, "No dates are needed for this letter.")


def _address_gaps(block: str) -> list[str]:
    parts = _parts(block)
    if not parts:
        return ["name", _STREET_GAP, "postcode and town"]
    rest = parts[1:]
    postcode = [part for part in rest if _POSTCODE_RE.search(part)]
    street = [part for part in rest if part not in postcode and _STREET_RE.match(part)]
    gaps = []
    if not street:
        gaps.append(_STREET_GAP)
    if not postcode:
        gaps.append("postcode and town")
    return gaps


_STREET_GAP = "street and house number"


def recipient_complete(draft: Draft, context: CheckContext) -> DraftCheck:
    """The address field has a name, a street (or PO box) and a postcode with town — for a court (its name,
    :func:`~ordnung.rules.routing.may_be_court`), the postcode and town alone: a central Mahngericht is addressed
    by its own postcode ("Amtsgericht Hünfeld / Zentrales Mahngericht / 36088 Hünfeld"; review round 4 of
    phase 2: a correct court address was flagged as missing a street)."""
    from ordnung.rules.routing import may_be_court

    gaps = _address_gaps(draft.recipient_block)
    if any(may_be_court(line) for line in _parts(draft.recipient_block)[:2]):
        gaps = [gap for gap in gaps if gap != _STREET_GAP]
    if gaps:
        return _check("recipient_complete", False, f"Add the recipient's {' and '.join(gaps)}.")
    return _check("recipient_complete", True, None)


def sender_complete(draft: Draft, context: CheckContext) -> DraftCheck:
    """The sender block has the person's name, street and postcode with town."""
    gaps = _address_gaps(draft.sender_block)
    if gaps:
        return _check(
            "sender_complete",
            False,
            f"Add your {' and '.join(gaps)} (Settings → Profile), so they can reply by post.",
        )
    return _check("sender_complete", True, None)


def no_placeholders(draft: Draft, context: CheckContext) -> DraftCheck:
    """No ``[…]``, ``{…}``, ``XXX`` or ``TODO`` left anywhere in the letter."""
    fields = [draft.subject, draft.body, draft.recipient_block, draft.sender_block, draft.place_date]
    found = list(
        dict.fromkeys(
            match.group(0)
            for text in [*fields, *draft.enclosures]
            for match in _PLACEHOLDER_RE.finditer(text)
        )
    )
    if found:
        listed = ", ".join(f"“{token}”" for token in found[:3])
        return _check("no_placeholders", False, f"Replace {listed} before sending.")
    return _check("no_placeholders", True, None)


def language_matches(draft: Draft, context: CheckContext) -> DraftCheck:
    """A rough stopword count: the body reads like the letter's language (German or English)."""
    own = _STOPWORDS.get(draft.language)
    if own is None:
        return _check("language_matches", True, "Not checked for this language.")
    words = _WORD_RE.findall(draft.body.casefold())
    hits = sum(word in own for word in words)
    others = max(
        (sum(word in stop for word in words) for lang, stop in _STOPWORDS.items() if lang != draft.language),
        default=0,
    )
    name = "German" if draft.language == "de" else "English"
    if hits >= _MIN_STOPWORDS and hits > others:
        return _check("language_matches", True, f"Reads like {name}.")
    return _check("language_matches", False, f"Parts of the letter don't look like {name} — check the text.")


def citations(text: str) -> Iterator[tuple[str, str | None]]:
    """``(paragraph number, law)`` for every § citation in ``text`` (law ``None`` when not named)."""
    for match in _CITATION_RE.finditer(text):
        law = match.group("law")
        law = " ".join(law.split()) if law else None
        numbers = [
            m.group("number").lower()
            for m in _CITATION_NUMBER_RE.finditer(match.group("body"))
            if m.group("qualifier") is None
        ]
        for number in numbers if match.group("mark") == "§§" else numbers[:1]:
            yield number, law


@cache
def catalog_citations() -> frozenset[tuple[str, str | None]]:
    """Every § citation in the rules catalog."""
    return frozenset(pair for rule in list_rules() for pair in citations(rule.citation))


def unknown_citations(text: str, source_text: str = "") -> list[str]:
    """Citations in ``text`` found neither in the rules catalog nor in ``source_text``."""
    known = catalog_citations() | frozenset(citations(source_text))
    known_numbers = {number for number, _ in known}
    unknown: list[str] = []
    for number, law in citations(text):
        ok = (number, law) in known if law else number in known_numbers
        label = f"§ {number} {law or ''}".strip()
        if not ok and label not in unknown:
            unknown.append(label)
    return unknown


def citations_known(draft: Draft, context: CheckContext) -> DraftCheck:
    """Every "§ n Gesetz" exists in the rules catalog or in the source letter."""
    unknown = unknown_citations(_letter_text(draft), context.source_text)
    if unknown:
        listed = ", ".join(unknown[:3])
        return _check(
            "citations_known",
            False,
            f"Ordnung can't confirm {listed} — remove it or have it checked before sending.",
        )
    if next(citations(_letter_text(draft)), None) is None:
        return _check("citations_known", True, "No laws are cited.")
    return _check("citations_known", True, "Every law cited is in Ordnung's rules or in the letter.")


def identifiers(text: str) -> set[str]:
    """Normalised IBANs, e-mail addresses and numbers with ≥ 6 digits found in ``text``."""
    found: set[str] = set()
    for match in _IBAN_RE.finditer(text):
        found.add(match.group(0).replace(" ", "").upper())
    rest = _IBAN_RE.sub(" ", text)
    for match in _EMAIL_RE.finditer(rest):
        found.add(match.group(0).lower())
    rest = _EMAIL_RE.sub(" ", rest)
    for match in _NUMBER_RE.finditer(rest):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= _MIN_ID_DIGITS and not _ISO_DATE_RE.match(match.group(0)):
            found.add(digits)
    return found


def _known_identifiers(values: Iterable[str], texts: Iterable[str]) -> set[str]:
    known: set[str] = set()
    for value in values:
        compact = value.strip()
        if not compact:
            continue
        known.add(compact.replace(" ", "").upper())
        known.add(compact.lower())
        known.add(re.sub(r"\D", "", compact))
        known |= identifiers(compact)
    for text in texts:
        known |= identifiers(text)
    return known


def no_new_identifiers(draft: Draft, context: CheckContext) -> DraftCheck:
    """IBANs, e-mails and long numbers in the letter come from the profile, the party or the letter."""
    known = _known_identifiers(
        context.known_ids, [*context.known_texts, draft.sender_block, draft.recipient_block]
    )
    new = sorted(identifiers(_letter_text(draft)) - known)
    if new:
        listed = ", ".join(new[:3])
        return _check(
            "no_new_identifiers",
            False,
            f"Check {listed}: it isn't in your profile, their details or the letter.",
        )
    return _check("no_new_identifiers", True, None)


def delivery_channel_ok(draft: Draft, context: CheckContext) -> DraftCheck:
    """The chosen way of sending meets the form requirement (e.g. rent and employment need a signed letter)."""
    guidance = context.guidance or draft.send_guidance
    channel = context.channel or draft.sent_channel
    if guidance is None:
        return _check("delivery_channel_ok", True, "No special form is needed.")
    if channel:
        entry = next((option for option in guidance.channels if option.channel == channel), None)
        if entry is not None and not entry.allowed:
            return _check(
                "delivery_channel_ok", False, entry.note or f"{entry.label} doesn't count for this letter."
            )
        label = entry.label if entry else channel
        return _check("delivery_channel_ok", True, f"{label} is fine for this letter.")
    if guidance.form == "written_form":
        detail = " ".join(
            part
            for part in (guidance.form_note, "Print it, sign it by hand and send it by Einwurf-Einschreiben.")
            if part
        )
        return _check("delivery_channel_ok", True, detail)
    return _check("delivery_channel_ok", True, guidance.form_note)


CHECKS: tuple[Callable[[Draft, CheckContext], DraftCheck], ...] = (
    has_reference,
    has_dates,
    recipient_complete,
    sender_complete,
    no_placeholders,
    language_matches,
    citations_known,
    no_new_identifiers,
    delivery_channel_ok,
)


def run_checks(draft: Draft, context: CheckContext) -> list[DraftCheck]:
    """All checks, in display order."""
    return [check(draft, context) for check in CHECKS]
