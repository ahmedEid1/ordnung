"""Extraction (SPEC § 8 stage 4): one text-mode call turns a document into a ``DocumentExtraction``.

The prompt carries the page-delimited text (visible text only — hidden text never reaches a model)
inside ``<untrusted_document>`` tags, plus context: today, region, country, the person's name and
the known parties (also document-derived, so also wrapped). The cache key holds only stable inputs —
document hash, page text sources, language, region and a simulated today — never the known parties,
which depend on ingestion order. An answer that does not validate gets one repair attempt with the
validation problems appended; a second failure raises :class:`ExtractionError` with a readable message.

A valid answer that the reading check (:func:`~ordnung.ingest.gaps.reading_gap`, on the same pages, the
way ``verify_extraction`` computes it) finds incomplete — almost blank, or without the objection deadline
the letter's own notice states — gets **one** completeness re-ask (:func:`completion_request`, ADR 0016):
the same request with Ordnung's note naming the missing parts appended (the letter stays inside its
untrusted block; the note quotes neither the letter nor the answer), a stricter schema, the version
``<base>.c<n>`` and a ``complete`` marker in its cache key, so every other key stays as it was.

**The re-ask never leaves the letter worse off than the first reading with the code's check behind it**
(the *baseline*): its answer replaces the first only when :func:`judge_completion` finds every rule kept —
less incomplete with the first answer's facts pinned, the letter's date no later, no dated to-do of the first
lost or later, the check's to-do covered, no objection date later than the check's (and none at all where the
check can't date it), every new dated to-do found on the letter, and its quotes found at least as well; a
"Read this letter yourself" the check filed stays beside the accepted answer as a cross-check.
Every other outcome — a rejected, unusable or missing answer — is exactly the baseline: the first reading is
kept and the reading check files its to-do as without the re-ask.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from fractions import Fraction
from typing import Any, Literal

from pydantic import ValidationError

from ordnung.ingest.gaps import (
    Check,
    Gap,
    check_item,
    dates_the_objection,
    letter_date,
    reading_gap,
    remedy_notices,
    start_variants,
)
from ordnung.ingest.plan import Verification, remedy_text, verify_extraction
from ordnung.ingest.text import page_delimited
from ordnung.ingest.verify import check_quote
from ordnung.llm import prompts
from ordnung.llm.base import ClaudeBadOutput, LLMError, LLMRequest, LLMResponse, ReplayMiss
from ordnung.llm.claude_cli import extract_json
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import completion_schema, extraction_schema
from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem, Page, Party, Recurrence
from ordnung.recurrence import rule_day_of_month, rule_working_day
from ordnung.rules import RuleContext, compute_due, is_private_sender, scope_for_party_kind
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.routing import classify_letter, is_court, letter_kind
from ordnung.trace import facts
from ordnung.trace.spans import NO_SPAN, Span

LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fa": "Persian",
    "fr": "French",
    "hi": "Hindi",
    "it": "Italian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "zh": "Chinese",
}
UNTRUSTED_OPEN = "<untrusted_document>"
UNTRUSTED_CLOSE = "</untrusted_document>"
_TAG_LOOKALIKE = re.compile(r"<\s*(/?)\s*untrusted[_\s-]*document\s*>", re.IGNORECASE)
_SLOT = "\x00ordnung-slot-{}\x00"
_MAX_ERRORS = 12


class ExtractionError(RuntimeError):
    """The model's answer could not be turned into a document record (message is user-presentable)."""


@dataclass(frozen=True)
class ExtractionInput:
    """Everything the extraction request is built from."""

    doc_id: str
    sha256: str
    pages: Sequence[Page]
    today: str
    language: str
    region: str
    country: str
    person_name: str
    known_parties: Sequence[Party]
    simulated_today: str | None = None


# --------------------------------------------------------------------------------------------------
# Prompt building
# --------------------------------------------------------------------------------------------------


def wrap_untrusted(text: str) -> str:
    """Wrap document-derived text in ``<untrusted_document>`` tags.

    Look-alike tags inside the text are defused first, so a document cannot close the block early.
    """
    defused = _TAG_LOOKALIKE.sub(r"[\1untrusted document tag removed]", text)
    return f"{UNTRUSTED_OPEN}\n{defused}\n{UNTRUSTED_CLOSE}"


def unwrap_untrusted(text: str) -> str:
    """The content of one :func:`wrap_untrusted` block (``text`` itself when it isn't one)."""
    stripped = text.strip()
    if stripped.startswith(UNTRUSTED_OPEN) and stripped.endswith(UNTRUSTED_CLOSE):
        return stripped[len(UNTRUSTED_OPEN) : -len(UNTRUSTED_CLOSE)].strip("\n")
    return text


def language_name(code: str) -> str:
    """English name of an ISO 639-1 language code (the code itself if unknown)."""
    return LANGUAGE_NAMES.get(code.lower(), code)


def known_parties_text(parties: Sequence[Party]) -> str:
    """One line per known party (name and kind), sorted by name, wrapped as untrusted.

    Only names and kinds: the model needs them to name a sender consistently, while matching by
    customer, file or passport numbers happens in code (:mod:`ordnung.ingest.link`), so numbers read
    from other letters never leave the computer with this one.
    """
    if not parties:
        return "(none yet)"
    lines = [
        f"- {party.name} ({party.kind})" for party in sorted(parties, key=lambda p: (p.name.casefold(), p.id))
    ]
    return wrap_untrusted("\n".join(lines))


def prompt_pages(pages: Sequence[Page]) -> list[tuple[int, str]]:
    """``(page, text)`` of the pages that have readable text (visible text only)."""
    return [(page.page, page.text) for page in pages if page.text.strip()]


def canonical_json(value: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) for cache keys."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def extraction_cache_key(data: ExtractionInput, *, repair: bool = False, complete: Sequence[str] = ()) -> str:
    """Stable inputs only: document hash, page text sources, language, region, simulated today.

    ``repair`` marks the repair attempt, ``complete`` the gaps a completeness re-ask asks about
    (:func:`completion_request`, sorted); each is added only when set, so the extraction's own key — and
    every recording made with it — stays as it was."""
    key: dict[str, Any] = {
        "doc": data.sha256,
        "pages": [[page.page, page.text_source] for page in sorted(data.pages, key=lambda p: p.page)],
        "language": data.language,
        "region": data.region,
        "today": data.simulated_today,
    }
    if repair:
        key["repair"] = True
    if complete:
        key["complete"] = sorted(set(complete))
    return canonical_json(key)


def _render(name: str, untrusted: dict[str, str], **values: object) -> tuple[str, str]:
    """Render a template, inserting document-derived values only after placeholder checks.

    Document text may contain ``{{…}}`` sequences; substituting it last keeps them literal.
    """
    slots = {key: _SLOT.format(key) for key in untrusted}
    version, body = prompts.render(name, **values, **slots)
    for key, text in untrusted.items():
        body = body.replace(slots[key], text)
    return version, body


def extraction_request(data: ExtractionInput, *, model: str) -> LLMRequest:
    """The text-mode extraction request for one document."""
    system_version, system = prompts.render("extract_system", language_name=language_name(data.language))
    text_version, document = _render(
        "extract_text", {"document": wrap_untrusted(page_delimited(prompt_pages(data.pages)))}
    )
    user_version, prompt = _render(
        "extract",
        {"mode_instructions": document, "known_parties": known_parties_text(data.known_parties)},
        today=data.today,
        region=data.region,
        country=data.country,
        person_name=data.person_name or "(not given)",
    )
    return LLMRequest(
        purpose="extract",
        prompt=prompt,
        system=system,
        schema=extraction_schema(),
        doc_ids=[data.doc_id],
        model=model,
        cache_key=extraction_cache_key(data),
        prompt_version=f"{system_version}.{user_version}.{text_version}",
        prompt_name="extract",
    )


def repair_request(request: LLMRequest, data: ExtractionInput, errors: str) -> LLMRequest:
    """The same request with the validation problems appended (its own cache key and version)."""
    version, note = prompts.render("extract_repair", errors=errors)
    return request.model_copy(
        update={
            "prompt": f"{request.prompt}\n\n{note}",
            "cache_key": extraction_cache_key(data, repair=True),
            "prompt_version": f"{request.prompt_version}.r{version}",
            "prompt_name": "extract_repair",
        }
    )


#: What the completeness re-ask names as left out, per gap (:mod:`ordnung.ingest.gaps`), in plain words of
#: Ordnung's own — never the letter's or the first answer's. It is model-facing text outside the prompt file,
#: so its digest is locked beside the prompt's (``evals.conditions.ordnung_prompt_hashes``,
#: ``reading_gaps_parts``): change it only together with ``reading_gaps``'s version.
MISSING_PARTS: dict[str, tuple[str, ...]] = {
    "empty": (
        "who sent it (`sender`)",
        "the letter's own date (`document_date`)",
        "what it asks the person to do, each with its date (`items`)",
        "the deadline to object that its instructions on how to object state, if it has such instructions "
        "(a to-do whose date has the nature `objection`)",
    ),
    "remedy_left_out": (
        "the deadline to object that its instructions on how to object (Rechtsbehelfsbelehrung) state "
        "(a to-do whose date has the nature `objection`, quoting those instructions)",
    ),
}


def missing_parts(gaps: Sequence[str]) -> str:
    """The note's list of what the reading left out (:data:`MISSING_PARTS`), one line per part."""
    return "\n".join(f"- {part}" for gap in sorted(set(gaps)) for part in MISSING_PARTS[gap])


def completion_request(request: LLMRequest, data: ExtractionInput, gaps: Sequence[str]) -> LLMRequest:
    """The extraction ``request`` asked once more for what its answer left out (``gaps``).

    The same system prompt and letter (still inside its ``<untrusted_document>`` block, which nothing is
    added to), with Ordnung's note appended (``reading_gaps``): the missing parts in plain words, the full
    reading asked for again, and text in the letter that asks for less, or claims a period was lifted, named
    as content to warn about. The note carries no letter text and no word of the first answer. The stricter
    schema (:func:`~ordnung.llm.schemas.completion_schema`) requires the sender, the letter's date and the
    to-dos; the cache key gets the ``complete`` marker and the version ``.c<n>``, so the extraction's own key
    is untouched. Built from the extraction's request, never its repair: the same re-ask whether or not a
    repair came first."""
    version, note = prompts.render("reading_gaps", missing=missing_parts(gaps))
    return request.model_copy(
        update={
            "prompt": f"{request.prompt}\n\n{note}",
            "schema_": completion_schema(),
            "cache_key": extraction_cache_key(data, complete=gaps),
            "prompt_version": f"{request.prompt_version}.c{version}",
            "prompt_name": "reading_gaps",
        }
    )


# --------------------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------------------


def validation_problems(exc: ValidationError) -> str:
    """The validation errors as bullet lines: field path and message, never the input values."""
    lines = []
    for error in exc.errors(include_url=False, include_input=False)[:_MAX_ERRORS]:
        path = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"- {path}: {error['msg']}")
    return "\n".join(lines)


def parse_extraction(data: dict[str, Any] | None, text: str) -> DocumentExtraction:
    """Validate a model answer (structured ``data`` or JSON inside ``text``), completed by
    :func:`with_rent_series`."""
    payload = data if data is not None else extract_json(text)
    return with_rent_series(DocumentExtraction.model_validate(payload if payload is not None else {}))


def _eur(amount: float) -> str:
    """``€670`` / ``€670.50``, as the app writes a whole or a broken amount."""
    return f"€{amount:,.0f}" if float(amount).is_integer() else f"€{amount:,.2f}"


def with_rent_series(extraction: DocumentExtraction) -> DocumentExtraction:
    """The reading with the rent a statement's adjusted advance payments start (§ 560 Abs. 4 BGB) when
    the model put the increase into ``change`` alone: a payment every month of the new amount from the
    day it takes effect, quoting the change's sentence — the item the prompt asks for and the ledger's
    point 9 needs (:mod:`ordnung.recurrence`: October's rent is replaced from November whichever way
    the model wrote the letter up). Only for a monthly price increase with an effective day and a new
    amount on a letter that states a rent contract, never for a rent increase that needs the person's
    consent (§ 558b BGB: the high-stakes kind the model names), and never beside a recurring payment
    that carries the new amount already."""
    change, contract = extraction.change, extraction.contract
    if (
        change is None
        or change.type != "price_increase"
        or change.cost_interval != "monthly"
        or not change.effective_date
        or not change.new_amount
        or contract is None
        or contract.category != "rent"
        or extraction.high_stakes_kind == "rent_increase"
    ):
        return extraction
    try:
        date.fromisoformat(change.effective_date)
    except ValueError:
        return extraction
    if any(
        item.kind == "payment" and item.recurrence is not None and item.amount == change.new_amount
        for item in extraction.items
    ):
        return extraction
    series = ExtractedItem(
        kind="payment",
        title=f"New monthly total rent {_eur(change.new_amount)}",
        date=DateSpec(type="fixed", date=change.effective_date, nature="payment", text=change.quote),
        amount=change.new_amount,
        currency="EUR",
        direction="out",
        recurrence=Recurrence(interval=1, unit="months"),
        quote=change.quote,
    )
    return extraction.model_copy(update={"items": [*extraction.items, series]})


def _parse_answer(response: LLMResponse) -> DocumentExtraction:
    return parse_extraction(response.data, response.text)


# --------------------------------------------------------------------------------------------------
# Completeness
# --------------------------------------------------------------------------------------------------

#: Why a completeness re-ask's answer was not used — every one keeps the first reading, and the reading check
#: behind it (the baseline):
#:
#: * ``no_answer`` — a replay without the re-ask's recording (the benchmark); ``unanswered`` — no answer came
#:   (the app: a timeout, a usage limit, any failed call); ``unusable`` — it doesn't validate or came back
#:   without structured output;
#: * ``not_better`` — not less incomplete than the first, or only by reading the same letter differently (its
#:   kind, sender or date read anew, a high-stakes kind read into it);
#: * ``date`` — a letter date later than the first answer's, or one the letter doesn't give for itself;
#: * ``dropped`` — a dated to-do of the first answer left out, or dated later (an unreadable date counts as
#:   later);
#: * ``uncovered`` — the to-do the check files for the first reading has no counterpart: no to-do dating the
#:   objection, nor a check of its own at least as dated (or, where the check asks the person to read the
#:   letter, no dated to-do found on it);
#: * ``unchecked`` — it dates the objection where the check can't (no date in the letter's own instructions to
#:   hold it against);
#: * ``later`` — an objection date that may end after the check's date, in any Land;
#: * ``ungrounded`` — something it adds isn't found on the letter: a dated to-do's quote, or a sender where the first
#:   answer named none;
#: * ``quotes`` — fewer of its quotes found on the letter than of the first answer's.
KeptBecause = Literal[
    "no_answer",
    "unanswered",
    "unusable",
    "not_better",
    "date",
    "dropped",
    "uncovered",
    "unchecked",
    "later",
    "ungrounded",
    "quotes",
]

#: How incomplete a reading is: a re-ask's answer must be strictly less so.
_GAP_RANK: dict[Gap | None, int] = {"empty": 2, "remedy_left_out": 1, None: 0}
#: How much the check's to-do gives: a date, a deadline to find in the letter, or "read it yourself".
_CHECK_RANK = {"dated": 2, "undated": 1, "read_yourself": 0}
#: The Länder an objection date is compared in (``None``: nationwide holidays only).
_REGIONS: tuple[str | None, ...] = (None, *REGION_NAMES)
_UNITS = ("days", "weeks", "months")
#: A remedy named in a to-do's title or quote (as the reading check names one).
_NAMES_REMEDY = re.compile(
    r"widerspr\w*|einspr\w*|\bklage\w*|\bobjection\w*|\bobject\b|\bappeal\w*", re.IGNORECASE
)


@dataclass(frozen=True)
class Completion:
    """A completeness re-ask: the ``gap`` that triggered it, whether its answer replaced the first reading
    (``accepted``) and, if not, why (``kept_because``)."""

    gap: Gap
    accepted: bool
    kept_because: KeptBecause | None = None

    @property
    def outcome(self) -> Literal["accepted", "rejected", "missing"]:
        """``missing`` when there was no answer to judge, else whether it was used."""
        if self.accepted:
            return "accepted"
        return "missing" if self.kept_because == "no_answer" else "rejected"


@dataclass(frozen=True)
class Reading:
    """The extraction kept for a letter, and its completeness re-ask if it had one. ``cross_check``: the to-do
    the reading check filed for the first reading, kept beside an accepted re-ask's answer when it asked the person
    to read the letter (:func:`cross_check`) — :func:`~ordnung.ingest.plan.verify_extraction` files it."""

    extraction: DocumentExtraction
    completion: Completion | None = None
    cross_check: Check | None = None


#: The to-do kept beside an accepted answer after an almost blank first reading the check could only answer with
#: "Read this letter yourself" (:func:`cross_check`): a cross-check, low and "Please check" like the check's own.
CROSS_CHECK_TITLE = "Check the letter for a missed deadline"
CROSS_CHECK_ACTION = (
    "Ordnung's first reading of this letter came back blank — check the letter for a deadline Claude may have "
    "missed. If it gives one, give this to-do that date; mark it done once you have checked."
)


def cross_check(floor: Check | None) -> Check | None:
    """The check's to-do for the first reading (``floor``) that stays beside an accepted re-ask's answer: only
    "Read this letter yourself" — an answer can't be held against it (the check found no notice it could read), so
    it is kept as a cross-check: undated, low priority, in the check's slot (graded "Please check")."""
    if floor is None or floor.kind != "read_yourself":
        return None
    item = floor.item.model_copy(
        update={"title": CROSS_CHECK_TITLE, "action": CROSS_CHECK_ACTION, "priority": "low"}
    )
    return floor._replace(item=item)


#: What the first answer left out, as the letter's warning says it once the re-ask's answer was used.
_REASKED: dict[Gap, str] = {
    "empty": "Claude's first answer for this letter left out almost everything (the sender, the letter's date and "
    "what to do)",
    "remedy_left_out": "Claude's first answer for this letter left out the deadline to object",
}
#: Where to send an objection, when the first answer came back almost blank on a letter that carries text
#: addressed to software: the planted text may name another address.
REASK_ADDRESS = (
    "Send an objection only to an address you already know for this authority or court — not to a link, e-mail "
    "address or phone number in this letter."
)
#: The start of the letter's warning when the re-ask's answer was used (:func:`reask_warning`): no scam sign
#: (``secretary.triggers._NOT_A_SIGN``, the web's ``REASK_WARNING``).
REASK_WARNING = re.compile(r"^Claude's first answer for this letter left out")


def reask_warning(gap: Gap, *, injected: bool = False) -> str:
    """The letter's warning when its completeness re-ask's answer was used (``gap``: what the first answer left
    out): the person sees it, not only the trace. ``injected``: the letter carries text addressed to software —
    after an almost blank first answer, the address advice the check's to-do would have given is kept."""
    text = (
        f"{_REASKED[gap]}, so Ordnung asked once more and shows the second answer — check its deadlines against "
        "the letter before you rely on them."
    )
    return f"{text} {REASK_ADDRESS}" if injected and gap == "empty" else text


def reading_gap_of(extraction: DocumentExtraction, pages: Sequence[Page]) -> Gap | None:
    """Why ``extraction`` is incomplete, computed on ``pages`` the way the reading check computes it
    (:func:`~ordnung.ingest.gaps.reading_gap` with the letter's remedy notices), or ``None``."""
    return reading_gap(extraction, pages, remedy_notices(pages))


def located(verification: Verification) -> Fraction:
    """The share of a reading's quotes the verification found on the letter's pages (in its text layer or an
    AI transcript): to-dos, key facts, contract terms, the change and the remedy. A reading that quotes
    nothing counts as fully located — an answer replacing it must then be found in full."""
    evidence = [
        *(verified.evidence for verified in verification.items),
        *(fact.evidence for fact in verification.key_facts if fact.evidence is not None),
        *verification.contract_evidence,
        *(e for e in (verification.change_evidence, verification.remedy_evidence) if e is not None),
    ]
    if not evidence:
        return Fraction(1)
    return Fraction(sum(e.grounding != "unverified" for e in evidence), len(evidence))


def _iso_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value.strip()[:10]) if value else None
    except ValueError:
        return None


def _words(text: str) -> str:
    return " ".join(text.split()).casefold()


def _same_place(first: str, second: str) -> bool:
    """Whether two quotes are the same sentence of the letter (one may quote a little more of it)."""
    a, b = _words(first), _words(second)
    return a in b or b in a


def _is_dated(item: ExtractedItem) -> bool:
    """A to-do with a date: its DateSpec, or the working day or day of the month its recurrence dates it by."""
    rule = item.recurrence
    return (
        item.date.type != "none" or rule_working_day(rule) is not None or rule_day_of_month(rule) is not None
    )


#: The DateSpec fields that decide a relative date (its wording and legal basis left out).
_DATING = ("type", "date", "amount", "unit", "anchor", "anchor_date", "delivery_rule", "shift_rule")


def _same_or_earlier(mine: ExtractedItem, theirs: ExtractedItem) -> bool:
    """Whether the re-ask dates a to-do of the first answer the same way, or on an earlier fixed day: a fixed
    date parsed, never compared as text (an unreadable one counts as later); any other the same DateSpec and
    the same recurrence."""
    if (mine.recurrence is None) != (theirs.recurrence is None) or (
        mine.recurrence is not None
        and theirs.recurrence is not None
        and mine.recurrence.model_dump() != theirs.recurrence.model_dump()
    ):
        return False
    first, second = mine.date, theirs.date
    if first.type == "fixed" and _iso_day(first.date) is not None:
        day = _iso_day(second.date) if second.type == "fixed" else None
        return day is not None and day <= (_iso_day(first.date) or day)
    return first.model_dump(include=set(_DATING)) == second.model_dump(include=set(_DATING))


def _kept(item: ExtractedItem, first: DocumentExtraction, second: DocumentExtraction, today: date) -> bool:
    """Whether a dated to-do of the first answer is in the re-ask's: the same kind, the same sentence, a date
    no later — by its DateSpec, and as computed in each reading's own context in every Land (the same DateSpec
    counts later under another sender: a tax office's weekend move, a court's arrival)."""
    return any(
        other.kind == item.kind
        and _same_place(item.quote, other.quote)
        and _same_or_earlier(item, other)
        and _due_no_later(item, other, first, second, today)
        for other in second.items
    )


def _due_no_later(
    mine: ExtractedItem,
    theirs: ExtractedItem,
    first: DocumentExtraction,
    second: DocumentExtraction,
    today: date,
) -> bool:
    """Whether ``theirs`` (the re-ask's) ends no later than ``mine`` (the first answer's), each computed in its own
    reading's context in every Land, with or without an arrival on ``today`` confirmed (a court's or a private
    sender's period runs from it): the re-ask's latest against the first's earliest. A date the first's context
    can't compute is held to the DateSpec alone."""
    if mine.date.type == "none":
        return True  # dated by its recurrence alone: held to the same recurrence

    def dues(item: ExtractedItem, reading: DocumentExtraction, region: str | None) -> list[date | None]:
        ctx = replace(_context(reading, today, region), quote=item.quote)
        return [
            _iso_day(
                compute_due(
                    item.date,
                    replace(ctx, received_date=arrival, received_confirmed=arrival is not None),
                    postal_buffer_days=0,
                ).due_date
            )
            for arrival in (None, today)
        ]

    for region in _REGIONS:
        was = [day for day in dues(mine, first, region) if day is not None]
        now = dues(theirs, second, region)
        if was and (None in now or max(day for day in now if day is not None) > min(was)):
            return False
    return True


def _repeated(item: ExtractedItem, first: DocumentExtraction) -> bool:
    """Whether a to-do of the re-ask's answer is one the first answer had (the same kind and sentence)."""
    return any(other.kind == item.kind and _same_place(item.quote, other.quote) for other in first.items)


def _sender_found(
    doc_id: str, first: DocumentExtraction, second: DocumentExtraction, pages: Sequence[Page]
) -> bool:
    """Whether a sender the re-ask names — where the first answer named none, or another — is found on the letter
    (its name looked up like a quote): an invented or renamed sender never becomes the letter's, nor decides its
    delivery rules. The first answer's own sender, named again, needs no looking up."""
    if second.sender is None or not second.sender.name.strip():
        return True
    if first.sender is not None and _words(first.sender.name) == _words(second.sender.name):
        return True
    evidence, _ = check_quote(doc_id, second.sender.name, pages)
    return evidence.grounding != "unverified"


def _pinned(first: DocumentExtraction, second: DocumentExtraction) -> DocumentExtraction:
    """``second`` with the facts the first answer gave pinned to it: its kind and high-stakes kind, and its
    sender and letter date wherever it gave them — the gap must close by what the answer adds, never by reading
    the same letter differently."""
    update: dict[str, Any] = {"kind": first.kind, "high_stakes_kind": first.high_stakes_kind}
    if first.sender is not None and first.sender.name.strip():
        update["sender"] = first.sender
    if first.document_date:
        update["document_date"] = first.document_date
    return second.model_copy(update=update)


def _date_kept(
    first: DocumentExtraction, second: DocumentExtraction, pages: Sequence[Page], notices: Any, today: date
) -> bool:
    """Whether the re-ask's letter date may stand: the first answer's, or — earlier, or where the first gave
    none — exactly the date the letter gives for itself (:func:`~ordnung.ingest.gaps.letter_date` without any
    reading's date); never a later one, nor an earlier one only the reading gives."""
    mine, theirs = _iso_day(first.document_date), _iso_day(second.document_date)
    if mine is not None and theirs == mine:
        return True
    if theirs is None:
        return mine is None and not second.document_date  # a date it gives must be readable
    if mine is not None and theirs > mine:
        return False
    own = letter_date(first.model_copy(update={"document_date": None}), pages, notices, today=today)
    return own is not None and theirs == own


def _period_end(start: date, amount: int, unit: str) -> date:
    """``start`` plus a period (§ 188 BGB, no weekend or delivery days): the floor's earliest possible end."""
    if unit == "days":
        return start + timedelta(days=amount)
    if unit == "weeks":
        return start + timedelta(weeks=amount)
    month = start.month - 1 + amount
    year, month = start.year + month // 12, month % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _context(extraction: DocumentExtraction, today: date, region: str | None) -> RuleContext:
    """The rules engine's context for a reading as the app plans it before it knows anything else (no sender
    record, no arrival day the person confirmed): the scope, private sender, court and letter kind its sender
    and remedy give (:func:`ordnung.ingest.plan.rule_context`), in Land ``region``."""
    sender, remedy = extraction.sender, extraction.remedy
    kind, name = (sender.kind, sender.name) if sender else (None, "")
    remedy_type = remedy.type if remedy else None
    notice = remedy_text(remedy)
    scope = scope_for_party_kind(kind, name=name or None, remedy_type=remedy_type, remedy_text=notice)
    return RuleContext(
        today=today,
        region=region,
        document_date=_iso_day(extraction.document_date),
        delivery_scope=scope,
        private_sender=is_private_sender(kind, scope=scope, remedy_type=remedy_type, remedy_text=notice),
        sender_kind=kind,
        letter_kind=letter_kind(extraction),
        court=is_court(name, kind),
    )


def _not_later_spec(floor: DateSpec, spec: DateSpec, second: DocumentExtraction, ctx: RuleContext) -> bool:
    """Whether ``spec`` can never end after the check's dated ``floor`` (a period from an explicit start) when
    both are counted in the same context — whatever the Land, the weekend or a later recompute: a fixed date on
    or before the floor's start plus its period; or the same kind of period, no longer, from a start no later,
    with delivery days only where the floor has the same. Never one counted from the arrival or from today, nor
    from deemed delivery where the sender has none (a private sender, a court: counted from the arrival)."""
    start = _iso_day(floor.anchor_date)
    if floor.type != "relative" or start is None or floor.amount is None or floor.unit not in _UNITS:
        return False
    if spec.type == "fixed":
        day = _iso_day(spec.date)
        return day is not None and day <= _period_end(start, floor.amount, floor.unit)
    if (
        spec.type != "relative"
        or spec.amount is None
        or spec.unit != floor.unit
        or spec.amount > floor.amount
    ):
        return False
    if spec.anchor == "explicit_date":
        begin = _iso_day(spec.anchor_date)
    elif spec.anchor in ("document_date", "deemed_delivery"):
        begin = _iso_day(second.document_date)
    else:
        return False  # from the arrival or from today: a later arrival would move it later
    if begin is None or begin > start:
        return False
    if spec.anchor == "deemed_delivery":
        if ctx.private_sender or ctx.court or spec.delivery_rule != floor.delivery_rule:
            return False
        return floor.delivery_rule != "none"
    return spec.delivery_rule in ("none", floor.delivery_rule)


def _floor_due(floor: DateSpec, ctx: RuleContext) -> date | None:
    """The check's to-do's date in ``ctx``, as planning computes it: the earliest of its start variants
    (:func:`~ordnung.ingest.gaps.start_variants`)."""
    days = [
        _iso_day(compute_due(variant, variant_ctx, postal_buffer_days=0).due_date)
        for variant, variant_ctx in start_variants(floor, ctx)
    ]
    found = [day for day in days if day is not None]
    return min(found) if found else None


def _arrived(ctx: RuleContext, region: str | None, arrival: date | None) -> RuleContext:
    """``ctx`` in Land ``region``, with ``arrival`` confirmed as the day the letter arrived (``None``: no day)."""
    return replace(ctx, region=region, received_date=arrival, received_confirmed=arrival is not None)


def _never_later(
    floor: DateSpec,
    dating: Sequence[tuple[DateSpec, str, bool]],
    first: DocumentExtraction,
    second: DocumentExtraction,
    today: date,
) -> bool:
    """Whether every objection date of the re-ask's reading (``dating``: its DateSpec, its quote, and whether it
    is the check's own to-do for that reading) ends no later than the check's date for the first: by shape
    (:func:`_not_later_spec`), and computed by the rules engine — the floor in the first reading's context, as the
    baseline dates it, each date of the re-ask's in its own — in every Land, without an arrival day and with
    ``today`` confirmed as one (a period from formal service runs from it)."""
    base = _context(second, today, None)
    if not all(_not_later_spec(floor, spec, second, base) for spec, _, _ in dating):
        return False
    # the floor as the baseline dates it: in the first reading's context (its sender, or none), never the second's
    floor_base = _context(first, today, None)
    for region in _REGIONS:
        for arrival in (None, today):
            ctx = _arrived(base, region, arrival)
            limit = _floor_due(floor, replace(_arrived(floor_base, region, arrival), letter_kind=None))
            for spec, quote, own in dating:
                if own:
                    due = _floor_due(spec, replace(ctx, letter_kind=None))
                else:
                    due = _iso_day(
                        compute_due(spec, replace(ctx, quote=quote), postal_buffer_days=0).due_date
                    )
                if limit is None or due is None or due > limit:
                    return False
    return True


def judge_completion(
    doc_id: str,
    first: DocumentExtraction,
    second: DocumentExtraction,
    pages: Sequence[Page],
    *,
    gap: Gap,
    today: date | None = None,
    injected: bool = False,
) -> KeptBecause | None:
    """Why the re-ask's answer ``second`` must not replace ``first`` (whose gap is ``gap``), or ``None`` to use
    it — :data:`KeptBecause` in the order checked. The *floor* is the to-do the reading check files for
    ``first`` (:func:`~ordnung.ingest.gaps.check_item`, with the same ``today`` and ``injected`` as the check
    at verify): the answer is used only when the letter ends no worse off than with that to-do —

    1. strictly less incomplete, also with the first answer's kind, high-stakes kind, sender and letter date
       pinned wherever it gave them, and filed as the same high-stakes kind;
    2. the first answer's letter date, or — earlier, or where the first gave none — exactly the date the letter
       gives for itself;
    3. every dated to-do of the first answer kept, on the same or an earlier date: by its DateSpec, and as
       computed in each reading's own context (sender, letter kind) in every Land, with and without an arrival;
    4. the floor covered: a to-do dating the objection (read as the check reads it, with the letter's date as
       :func:`~ordnung.ingest.gaps.reading_gap` knows it), or the check's own to-do for this reading at least
       as dated; where the floor asks the person to read the letter, a dated to-do found on it (the floor is
       then kept beside it as a cross-check: :func:`cross_check`);
    5. no objection date — nor a dated to-do naming a remedy, whatever nature it is filed under — where the
       floor has none (the check couldn't date it: nothing to hold the answer's date against), and none that may
       end after a dated floor, the floor dated in the first reading's context (:func:`_never_later`);
    6. every dated to-do it adds found on the letter (in its text layer or a photo's transcript), and so the
       sender it names where the first answer named none or another;
    7. at least the first answer's share of its quotes found on the letter (:func:`located`)."""
    day = today or date.today()
    notices = remedy_notices(pages)
    own_gap = reading_gap(second, pages, notices)
    if (
        _GAP_RANK[own_gap] >= _GAP_RANK[gap]
        or _GAP_RANK[reading_gap(_pinned(first, second), pages, notices)] >= _GAP_RANK[gap]
        or classify_letter(second) != classify_letter(first)
    ):
        return "not_better"
    if not _date_kept(first, second, pages, notices, day):
        return "date"
    if not all(_kept(item, first, second, day) for item in first.items if _is_dated(item)):
        return "dropped"
    floor: Check | None = check_item(first, pages, injected=injected, today=day)
    own: Check | None = check_item(second, pages, injected=injected, today=day) if own_gap else None
    # the letter's date as reading_gap knows it: a period from it computes only when the reading gives one, or
    # the letter gives none the check could count from
    dated = _iso_day(second.document_date) is not None or letter_date(second, pages, notices) is None
    objections = [item for item in second.items if dates_the_objection(item, notices, second, dated=dated)]
    # a dated to-do it adds that names a remedy but isn't read as dating the objection (filed under another nature,
    # quoting words outside the notice): held to the floor like one — never a later "Widerspruch" beside it
    named = [
        item
        for item in second.items
        if item not in objections
        and item.kind != "payment"
        and item.date.nature != "payment"
        and _is_dated(item)
        and not _repeated(item, first)
        and _NAMES_REMEDY.search(f"{item.title} {item.quote}")
    ]
    verified = verify_extraction(doc_id, second, pages)
    found = [v for v in verified.items if _is_dated(v.item) and v.evidence.grounding != "unverified"]
    if floor is not None:
        if floor.kind == "read_yourself":
            covered = bool(found) or own is not None
        else:
            covered = bool(objections) or (
                own is not None and _CHECK_RANK[own.kind] >= _CHECK_RANK[floor.kind]
            )
        if not covered:
            return "uncovered"
    if (objections or named) and (floor is None or floor.kind != "dated"):
        return "unchecked"
    if floor is not None and floor.kind == "dated":
        dating = [(item.date, item.quote, False) for item in (*objections, *named)]
        if own is not None:
            if own.kind != "dated":
                return "uncovered"
            dating.append((own.item.date, own.item.quote, True))
        if not _never_later(floor.item.date, dating, first, second, day):
            return "later"
    if any(
        _is_dated(v.item) and v.evidence.grounding == "unverified" and not _repeated(v.item, first)
        for v in verified.items
    ) or not _sender_found(doc_id, first, second, pages):
        return "ungrounded"
    if located(verified) < located(verify_extraction(doc_id, first, pages)):
        return "quotes"
    return None


async def _read(
    llm: LLMService,
    request: LLMRequest,
    data: ExtractionInput,
    *,
    use_cache: bool,
    trace: Span,
    before_again: Callable[[], object] | None,
) -> tuple[DocumentExtraction, int | None]:
    """The extraction call, with one repair attempt if the answer does not validate: the reading and the
    usage-log id of the call that gave it. ``before_again`` runs right before the repair sends the letter
    again."""
    with trace.span("model", "Extract", key="extract", stage="extract") as step:
        response = await llm.complete(request, use_cache=use_cache, trace=step, validate=_parse_answer)
        try:
            return parse_extraction(response.data, response.text), response.call_id
        except ValidationError as first:
            problems = validation_problems(first)
            step.set(problems=len(first.errors()))
    if before_again is not None:
        before_again()
    with trace.span("model", "Extract · repair", key="extract_repair", stage="extract") as step:
        repaired = await llm.complete(
            repair_request(request, data, problems),
            use_cache=use_cache,
            trace=step,
            validate=_parse_answer,
            repair_of=response.call_id,
        )
        try:
            return parse_extraction(repaired.data, repaired.text), repaired.call_id
        except ValidationError as second:
            step.set(problems=len(second.errors()))
            raise ExtractionError(
                "Claude's answer for this document could not be understood, even after a second try "
                f"({len(second.errors())} problem(s), e.g. {validation_problems(second).splitlines()[0][2:]}). "
                "Try “Reprocess” later."
            ) from second


async def _complete(
    llm: LLMService,
    request: LLMRequest,
    data: ExtractionInput,
    first: DocumentExtraction,
    *,
    gap: Gap,
    completes: int | None,
    use_cache: bool,
    trace: Span,
    unrecorded: tuple[type[LLMError], ...],
    unanswered: tuple[type[LLMError], ...],
    today: date,
    injected: bool,
) -> Reading:
    """The one completeness re-ask of a reading found incomplete (``gap``), on a model step of its own whose
    usage-log row names the call it completes (``completes``, kept as the row's ``repair_of``)."""
    kept, kept_check = first, None
    with trace.span("model", "Extract · complete", key="extract_complete", stage="extract") as step:
        try:
            response = await llm.complete(
                completion_request(request, data, [gap]),
                use_cache=use_cache,
                trace=step,
                validate=_parse_answer,
                repair_of=completes,
            )
            second = parse_extraction(response.data, response.text)
        except unrecorded:
            completion = Completion(gap, accepted=False, kept_because="no_answer")
        except ReplayMiss:
            raise  # a replay must hold every call it makes (the demo, CI)
        except (ValidationError, ClaudeBadOutput):
            completion = Completion(gap, accepted=False, kept_because="unusable")
        except unanswered:
            completion = Completion(gap, accepted=False, kept_because="unanswered")
        else:
            reason = await asyncio.to_thread(
                judge_completion,
                data.doc_id,
                first,
                second,
                data.pages,
                gap=gap,
                today=today,
                injected=injected,
            )
            completion = Completion(gap, accepted=reason is None, kept_because=reason)
            if completion.accepted:
                kept = second
                floor = await asyncio.to_thread(check_item, first, data.pages, injected=injected, today=today)
                kept_check = cross_check(floor)
        step.set(**facts.completion(gap, accepted=completion.accepted, kept_because=completion.kept_because))
    return Reading(kept, completion, kept_check)


async def read_document(
    llm: LLMService,
    data: ExtractionInput,
    *,
    model: str,
    use_cache: bool = True,
    trace: Span = NO_SPAN,
    unrecorded: tuple[type[LLMError], ...] = (),
    unanswered: tuple[type[LLMError], ...] = (),
    before_again: Callable[[], object] | None = None,
    arrived: date | None = None,
    injected: bool = False,
) -> Reading:
    """The extraction call (with its repair attempt), then — only when the reading check finds the reading
    incomplete — one completeness re-ask (module docstring).

    ``trace`` gets a model step per call; a repair's and a re-ask's usage-log rows name the call they follow
    (``repair_of``), and the re-ask's step says which gap triggered it and whether its answer was used
    (:func:`ordnung.trace.facts.completion`). Errors of the re-ask: an unusable answer (``ValidationError``,
    ``ClaudeBadOutput``) keeps the first reading, and so do the errors in ``unrecorded`` (the benchmark's replay
    miss: ``no_answer``) and in ``unanswered`` (the app: every model error, so a re-ask without an answer never
    fails a usable reading); any other replay miss and every other error propagate.

    ``before_again`` runs right before a further call sends the letter again (the repair, the re-ask) and
    raises to stop it (the app: the letter was trashed or deleted meanwhile). ``arrived`` and ``injected`` are
    what the reading check at verify gets (the day the letter arrived, default ``data.today``; text addressed
    to software), so the re-ask is judged against the very to-do the check would file. An accepted answer
    after a first reading the check could only meet with "Read this letter yourself" carries that to-do as
    :attr:`Reading.cross_check`, for ``verify_extraction(cross_check=…)`` to file beside it.
    """
    request = extraction_request(data, model=model)
    extraction, call_id = await _read(
        llm, request, data, use_cache=use_cache, trace=trace, before_again=before_again
    )
    gap = await asyncio.to_thread(reading_gap_of, extraction, data.pages)
    if gap is None:
        return Reading(extraction)
    if before_again is not None:
        before_again()
    return await _complete(
        llm,
        request,
        data,
        extraction,
        gap=gap,
        completes=call_id,
        use_cache=use_cache,
        trace=trace,
        unrecorded=unrecorded,
        unanswered=unanswered,
        today=arrived or _iso_day(data.today) or date.today(),
        injected=injected,
    )


async def extract_document(
    llm: LLMService, data: ExtractionInput, *, model: str, use_cache: bool = True, trace: Span = NO_SPAN
) -> DocumentExtraction:
    """The reading kept for the letter (:func:`read_document`): the extraction, repaired once if it does not
    validate and asked once more if the reading check finds it incomplete.

    ``trace`` gets a model step per call; the repair's usage-log row names the call it retries
    (``repair_of``) and the outcomes say which answer was usable (``invalid`` → ``repaired``/``failed``).
    """
    reading = await read_document(llm, data, model=model, use_cache=use_cache, trace=trace)
    return reading.extraction
