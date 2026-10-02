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
``<base>.c<n>`` and a ``complete`` marker in its cache key, so every other key stays as it was. Its answer
replaces the first only when it is strictly less incomplete and its quotes are found on the pages at least
as well (:func:`judge_completion`); an unusable answer keeps the first. The reading check still runs on
whichever reading is kept, as the last line of defence.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Any, Literal

from pydantic import ValidationError

from ordnung.ingest.gaps import Gap, reading_gap, remedy_notices
from ordnung.ingest.plan import Verification, verify_extraction
from ordnung.ingest.text import page_delimited
from ordnung.llm import prompts
from ordnung.llm.base import ClaudeBadOutput, LLMError, LLMRequest, LLMResponse
from ordnung.llm.claude_cli import extract_json
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import completion_schema, extraction_schema
from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem, Page, Party, Recurrence
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

#: Why a completeness re-ask's answer was not used: no answer (a replay without its recording, in the
#: benchmark), an unusable one (it doesn't validate, or no structured output came back), one no less
#: incomplete than the first, or one whose quotes are found on the pages less well than the first's.
KeptBecause = Literal["no_answer", "unusable", "not_better", "quotes"]

#: How incomplete a reading is: a re-ask's answer must be strictly less so.
_GAP_RANK: dict[Gap | None, int] = {"empty": 2, "remedy_left_out": 1, None: 0}


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
    """The extraction kept for a letter, and its completeness re-ask if it had one."""

    extraction: DocumentExtraction
    completion: Completion | None = None


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


def judge_completion(
    doc_id: str,
    first: DocumentExtraction,
    second: DocumentExtraction,
    pages: Sequence[Page],
    *,
    gap: Gap,
) -> KeptBecause | None:
    """Why the re-ask's answer ``second`` must not replace ``first`` (whose gap is ``gap``), or ``None`` to use
    it: it must be strictly less incomplete (``empty`` → ``remedy_left_out`` or complete; ``remedy_left_out``
    → complete), and the share of its quotes the existing verification
    (:func:`~ordnung.ingest.plan.verify_extraction`) finds on the pages must be at least the first's."""
    if _GAP_RANK[reading_gap_of(second, pages)] >= _GAP_RANK[gap]:
        return "not_better"
    if located(verify_extraction(doc_id, second, pages)) < located(verify_extraction(doc_id, first, pages)):
        return "quotes"
    return None


async def _read(
    llm: LLMService, request: LLMRequest, data: ExtractionInput, *, use_cache: bool, trace: Span
) -> tuple[DocumentExtraction, int | None]:
    """The extraction call, with one repair attempt if the answer does not validate: the reading and the
    usage-log id of the call that gave it."""
    with trace.span("model", "Extract", key="extract", stage="extract") as step:
        response = await llm.complete(request, use_cache=use_cache, trace=step, validate=_parse_answer)
        try:
            return parse_extraction(response.data, response.text), response.call_id
        except ValidationError as first:
            problems = validation_problems(first)
            step.set(problems=len(first.errors()))
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
) -> Reading:
    """The one completeness re-ask of a reading found incomplete (``gap``), on a model step of its own whose
    usage-log row names the call it completes (``completes``, kept as the row's ``repair_of``)."""
    kept = first
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
        except (ValidationError, ClaudeBadOutput):
            completion = Completion(gap, accepted=False, kept_because="unusable")
        else:
            reason = await asyncio.to_thread(
                judge_completion, data.doc_id, first, second, data.pages, gap=gap
            )
            completion = Completion(gap, accepted=reason is None, kept_because=reason)
            if completion.accepted:
                kept = second
        step.set(**facts.completion(gap, accepted=completion.accepted, kept_because=completion.kept_because))
    return Reading(kept, completion)


async def read_document(
    llm: LLMService,
    data: ExtractionInput,
    *,
    model: str,
    use_cache: bool = True,
    trace: Span = NO_SPAN,
    unrecorded: tuple[type[LLMError], ...] = (),
) -> Reading:
    """The extraction call (with its repair attempt), then — only when the reading check finds the reading
    incomplete — one completeness re-ask (module docstring).

    ``trace`` gets a model step per call; a repair's and a re-ask's usage-log rows name the call they follow
    (``repair_of``), and the re-ask's step says which gap triggered it and whether its answer was used
    (:func:`ordnung.trace.facts.completion`). Only an unusable re-ask answer (``ValidationError``,
    ``ClaudeBadOutput``) and the errors in ``unrecorded`` (the benchmark's replay miss: no answer was
    recorded) keep the first reading; every other error propagates as the extraction's would.
    """
    request = extraction_request(data, model=model)
    extraction, call_id = await _read(llm, request, data, use_cache=use_cache, trace=trace)
    gap = await asyncio.to_thread(reading_gap_of, extraction, data.pages)
    if gap is None:
        return Reading(extraction)
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
