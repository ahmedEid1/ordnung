"""The four benchmark conditions (SPEC § 17): same model, same letter, same "today", same region.

* ``ordnung`` — the ingestion pipeline's own logic without the app, the database or the global
  clock: the text layer (visible text only; invisible text is reported, never sent), transcription
  of pages without a text layer with the pipeline's own request, the pipeline's extraction request
  (:func:`ordnung.ingest.extract.extract_document`, including its repair attempt), verification of
  every quote against the page text, and the rules engine for every date (``compute_due`` with the
  pipeline's confidence grading, ``compute_contract`` for contract terms). The app's check of the reading
  itself runs too (:mod:`ordnung.ingest.gaps`): an incomplete reading's code-made objection deadline is
  scored like any to-do, its undated "read this letter yourself" placeholder is never scored.
* ``llm_only`` — the model reads the letter (the same visible text; a photo is attached as the
  image itself, as a person would share it) and computes every final due date itself. The prompt
  gives today, the region and an explicit instruction to apply current German law.
* ``llm_rules_text`` — the same, plus a verified summary of the relevant rules
  (``evals/prompts/rules_text.md``, condensed from ``docs/deadline-rules.md``).
* ``llm_rules_tool`` — the ``llm_only`` prompts plus a short note on the tools
  (``evals/prompts/rules_tool.md``), and the ``claude`` CLI gets Ordnung's rules-only MCP server
  (``ordnung mcp --rules-only``: ``compute_deadline``, ``german_holidays``, ``add_working_days``,
  ``check_iban``) — an agent with a calculator. The model decides whether to call the tools and
  what to answer; its tool calls are recorded with the answer (``Prediction.tools``).

Every model call carries the benchmark entry id as its ``doc_ids`` (accounting, and the
``RecordingBackend`` privacy guard). A condition returns a :class:`~evals.records.Prediction`; the
runner fills in the per-call accounting collected by :class:`MeteredBackend`.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evals import __version__
from evals.records import (
    PERSONA_LANGUAGE,
    PERSONA_REGION,
    CallRecord,
    ConditionName,
    Entry,
    PredictedContract,
    PredictedItem,
    Prediction,
    ToolUse,
    iso_or_none,
    parse_iso,
)
from ordnung.assistant import rules_tools
from ordnung.ingest.extract import (
    ExtractionError,
    ExtractionInput,
    canonical_json,
    extract_document,
    prompt_pages,
    validation_problems,
    wrap_untrusted,
)
from ordnung.ingest.gaps import CHECK_SLOT
from ordnung.ingest.intake import render_pages
from ordnung.ingest.pipeline import HIDDEN_TEXT_WARNING, NO_TEXT_ERROR, injection_warnings
from ordnung.ingest.plan import (
    ComputedDate,
    VerifiedItem,
    checked_evidence,
    compute_item,
    end_date_grounding,
    remedy_text,
    remedy_warnings,
    verify_extraction,
)
from ordnung.ingest.text import PageText, extract_pdf_pages, page_delimited
from ordnung.ingest.transcribe import PageTranscript, transcribe_page
from ordnung.ingest.verify import parse_amounts
from ordnung.llm import prompts as ordnung_prompts
from ordnung.llm.base import (
    Attachment,
    ClaudeBadOutput,
    LLMBackend,
    LLMError,
    LLMRequest,
    LLMResponse,
    StreamEvent,
    ToolCall,
)
from ordnung.llm.claude_cli import extract_json
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import extraction_schema, schema_for, transcription_schema
from ordnung.models import ContractTerms, DocumentExtraction, DocumentKind, ItemKind, Page, RemedyType
from ordnung.rules import RuleContext, compute_contract, is_private_sender, scope_for_party_kind
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.deadlines import POSTAL_BUFFER_DAYS
from ordnung.rules.routing import announced_end, is_court, is_labour_court, letter_kind
from ordnung.secretary.scam import iban_valid, invalid_iban_message, normalize_iban

EVALS_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = EVALS_DIR / "prompts"
BASELINE_PROMPTS = ("llm_only_system", "llm_only", "document_text", "document_image", "repair")
RULES_PROMPT = "rules_text"
TOOLS_PROMPT = "rules_tool"
TOOLS_CONDITION = "llm_rules_tool"
#: What the tool condition may call: only the rules-only server's tools (no built-in tools at all).
TOOLS_ALLOWED = [f"mcp__{rules_tools.SERVER_NAME}__*"]
TOOL_PREFIX = f"mcp__{rules_tools.SERVER_NAME}__"
#: A cost cap per call, far above a normal answer, so a looping agent is stopped (an infrastructure error).
TOOLS_BUDGET_USD = 1.0
ORDNUNG_PROMPTS = (
    "extract_system",
    "extract",
    "extract_text",
    "extract_repair",
    "transcribe_system",
    "transcribe",
)
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")

_VERSION_RE = re.compile(r"^<!--\s*version:\s*(\S+)\s*-->\s*\n")
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
_SLOT = "\x00evals-slot-{}\x00"
_SRC = Path(__file__).resolve().parents[1] / "src" / "ordnung"


# --------------------------------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------------------------------


@functools.cache
def load_prompt(name: str) -> tuple[str, str]:
    """``(version, template)`` of ``evals/prompts/<name>.md`` (``<!-- version: N -->`` header)."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    match = _VERSION_RE.match(text)
    return (match.group(1), text[match.end() :]) if match else ("1", text)


def render_prompt(name: str, *, untrusted: dict[str, str] | None = None, **values: object) -> tuple[str, str]:
    """Fill ``{{placeholders}}``; document-derived ``untrusted`` values are inserted last.

    Letter text may itself contain ``{{…}}`` sequences, so it is substituted only after the
    template has been checked for missing values (the same approach as the extraction prompt).
    """
    version, body = load_prompt(name)
    slots = {key: _SLOT.format(key) for key in untrusted or {}}
    for key, value in {**values, **slots}.items():
        body = body.replace("{{" + key + "}}", str(value))
    missing = sorted(set(_PLACEHOLDER_RE.findall(body)))
    if missing:
        raise KeyError(f"prompt {name!r} is missing values for {missing}")
    for key, text in (untrusted or {}).items():
        body = body.replace(slots[key], text)
    return version, body


# --------------------------------------------------------------------------------------------------
# Accounting
# --------------------------------------------------------------------------------------------------


@dataclass
class CallLog:
    """The calls one (letter, condition) task made, in order."""

    calls: list[CallRecord] = field(default_factory=list)


class MeteredBackend:
    """Wraps the shared backend for one task: sets the per-call timeout and records every call.

    Retries and backoff are the wrapped backend's job (``ClaudeCLIBackend`` retries transient errors
    and timeouts, and a bad structured output once).
    """

    def __init__(self, inner: LLMBackend, log: CallLog, *, timeout_s: float | None = None) -> None:
        self.inner = inner
        self.log = log
        self.timeout_s = timeout_s
        self.name = inner.name

    def _prepare(self, req: LLMRequest) -> LLMRequest:
        return req if self.timeout_s is None else req.model_copy(update={"timeout_s": self.timeout_s})

    async def complete(self, req: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        try:
            resp = await self.inner.complete(self._prepare(req))
        except LLMError as exc:
            self.log.calls.append(
                CallRecord(
                    purpose=req.purpose,
                    backend=self.name,
                    ok=False,
                    error=str(exc)[:300],
                    wall_ms=_ms(started),
                )
            )
            raise
        usage = resp.usage
        self.log.calls.append(
            CallRecord(
                purpose=req.purpose,
                backend=resp.backend or self.name,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_creation_tokens=usage.cache_creation_tokens,
                cost_usd=usage.cost_usd,
                duration_ms=usage.duration_ms,
                wall_ms=_ms(started),
            )
        )
        return resp

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        async for event in self.inner.stream(self._prepare(req)):
            yield event


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


# --------------------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedDocument:
    """A benchmark document as the pipeline sees it after intake and the text stage.

    ``pages`` hold the visible text of PDF pages (``text_source="text"``) or nothing yet
    (``"none"``, to be transcribed); invisible text is kept in ``Page.hidden`` and never sent.
    """

    entry: Entry
    file: Path
    pages: list[Page]

    @property
    def hidden_text(self) -> bool:
        return any(page.hidden.strip() for page in self.pages)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_document(entry: Entry, dataset_dir: Path, work_dir: Path) -> PreparedDocument:
    """Render the pages (as intake does) and read the PDF text layer (as the text stage does).

    Raises ``ValueError`` if the file does not match the manifest's SHA-256 (the fixtures are keyed
    by it, so a changed file would silently replay answers for another letter).
    """
    source = entry.path(dataset_dir)
    if file_sha256(source) != entry.sha256:
        raise ValueError(f"{entry.file} does not match the manifest's SHA-256 — regenerate the dataset")
    rendered = render_pages(source, entry.media_type, work_dir, entry.id)
    texts: dict[int, PageText] = {}
    if entry.media_type == "application/pdf":
        texts = {text.page: text for text in extract_pdf_pages(source, rendered)}
    pages = [_page(entry.id, r.page, r.width, r.height, r.image_path, texts.get(r.page)) for r in rendered]
    return PreparedDocument(entry=entry, file=source, pages=pages)


def _page(doc_id: str, number: int, width: int, height: int, image: Path, text: PageText | None) -> Page:
    if text is None:
        return Page(doc_id=doc_id, page=number, width=width, height=height, image_path=str(image))
    return Page(
        doc_id=doc_id,
        page=number,
        width=width,
        height=height,
        image_path=str(image),
        text=text.text,
        text_source=text.source,
        words=[(w.text, round(w.x0, 5), round(w.y0, 5), round(w.x1, 5), round(w.y1, 5)) for w in text.words],
        hidden=text.hidden_text,
    )


# --------------------------------------------------------------------------------------------------
# Condition: ordnung
# --------------------------------------------------------------------------------------------------


async def transcribe_missing(
    llm: LLMService, pages: Sequence[Page], *, doc_id: str, model: str
) -> tuple[list[Page], list[str]]:
    """Transcribe every page without a text layer, like the pipeline's transcribe stage.

    Returns the pages with transcripts (``text_source="transcript"``) and the pipeline's warnings
    for pages that were empty or illegible.
    """
    todo = [page for page in pages if page.text_source != "text"]
    results: list[PageTranscript] = list(
        await asyncio.gather(
            *(
                transcribe_page(llm, Path(page.image_path), page=page.page, doc_id=doc_id, model=model)
                for page in todo
            )
        )
    )
    by_page = {result.page: result for result in results}
    updated: list[Page] = []
    warnings: list[str] = []
    for page in pages:
        result = by_page.get(page.page)
        if result is None:
            updated.append(page)
            continue
        source = "transcript" if result.text else "none"
        updated.append(page.model_copy(update={"text": result.text, "text_source": source}))
        if not result.text or not result.legible:
            warnings.append(f"Page {page.page} is hard to read — please check it against the paper letter.")
    return updated, warnings


def ordnung_rule_context(
    entry: Entry, extraction: DocumentExtraction, pages: Sequence[Page] = ()
) -> RuleContext:
    """The rules engine's context: the entry's today and Länder, the extracted letter date and scope.

    The holiday region is the authority's Land when the letterhead names one (``None`` → nationwide
    holidays only, which the dataset guarantees gives the legal date). As in the app
    (``ingest.plan.rule_context``), the delivery scope — and whether the sender has deemed delivery at
    all — follows the sender's kind, name and remedy notice; the letter's kind and the end a termination
    announces (graded against the letter's ``pages``) route the dates of high-stakes letters
    (``rules.routing``); and a court's letter is marked as one, and a labour court's, from the sender's
    name. Only what the app learns from the person is left out: the benchmark has no confirmed arrival
    day and no sender record with its Land.
    """
    sender = extraction.sender
    remedy = extraction.remedy
    name = sender.name if sender else ""
    kind = sender.kind if sender else None
    remedy_type = remedy.type if remedy else None
    notice = remedy_text(remedy)
    scope = scope_for_party_kind(
        kind, name=sender.name if sender else None, remedy_type=remedy_type, remedy_text=notice
    )
    return RuleContext(
        today=entry.today_date,
        region=entry.authority_region,
        document_date=parse_iso(extraction.document_date),
        delivery_scope=scope,
        recipient_region=entry.recipient_region or PERSONA_REGION,
        private_sender=is_private_sender(kind, scope=scope, remedy_type=remedy_type, remedy_text=notice),
        sender_kind=kind,
        letter_kind=letter_kind(extraction),
        end_date=announced_end(extraction),
        end_date_grounding=end_date_grounding(extraction, pages),
        court=is_court(name),
        labour_court=is_labour_court(name),
    )


def contract_terms(extraction: DocumentExtraction) -> ContractTerms | None:
    """The extracted contract as rules-engine terms (as ``Contract.terms`` builds them), or ``None``."""
    contract = extraction.contract
    if contract is None:
        return None
    return ContractTerms(
        category=contract.category,
        party_kind=extraction.sender.kind if extraction.sender else None,
        concluded_date=contract.concluded_date,
        start_date=contract.start_date,
        initial_term_months=contract.initial_term_months,
        renewal_term_months=contract.renewal_term_months,
        notice_value=contract.notice_value,
        notice_unit=contract.notice_unit,
        notice_basis=contract.notice_basis,
        notice_day=contract.notice_day,
        notice_before_end=contract.notice_before_end,
        notice_statutory=contract.notice_statutory,
        end_date=contract.end_date,
        is_consumer=contract.is_consumer,
        is_basic_supply=contract.is_basic_supply,
    )


def extraction_amounts(extraction: DocumentExtraction) -> list[float]:
    """Every sum the record states: item amounts, contract cost, old/new price, key-fact amounts."""
    values: list[float] = [item.amount for item in extraction.items if item.amount is not None]
    if extraction.contract and extraction.contract.cost_amount is not None:
        values.append(extraction.contract.cost_amount)
    if extraction.change:
        values += [v for v in (extraction.change.old_amount, extraction.change.new_amount) if v is not None]
    for fact in extraction.key_facts:
        values += parse_amounts(fact.value)
    return unique_amounts(values)


def unique_amounts(values: Sequence[float]) -> list[float]:
    """Amounts rounded to cents, first occurrence kept."""
    return list(dict.fromkeys(round(float(value), 2) for value in values))


def _ordnung_item(verified: VerifiedItem, computed: ComputedDate) -> PredictedItem:
    item, receipt = verified.item, computed.receipt
    return PredictedItem(
        kind=item.kind,
        title=item.title,
        due_date=computed.due_date,
        time=item.date.time,
        amount=item.amount,
        quote=item.quote,
        confidence=receipt.confidence if receipt else None,
        spec=item.date.model_dump(mode="json"),
        grounding=verified.evidence.grounding,
        value_consistent=checked_evidence(verified, computed).value_consistent,
        needs_check=verified.needs_check or computed.conflict,
        rule_ids=list(receipt.rule_ids) if receipt else [],
        explanation=receipt.summary if receipt else "",
        notes=list(receipt.warnings) if receipt else [],
    )


def _payment_signal(extraction: DocumentExtraction) -> str | None:
    """The code's IBAN checksum finding (SPEC § 21 scam checks), as the pipeline words it."""
    payment = extraction.payment
    if payment is None or not payment.iban:
        return None
    iban = normalize_iban(payment.iban)
    return None if iban_valid(iban) else invalid_iban_message(iban)


async def run_ordnung(entry: Entry, document: PreparedDocument, llm: LLMService, *, model: str) -> Prediction:
    """The ``ordnung`` condition for one letter."""
    base = Prediction(entry_id=entry.id, condition="ordnung", model=model, hidden_text=document.hidden_text)
    warnings = [HIDDEN_TEXT_WARNING] if document.hidden_text else []
    signals = ["hidden_text"] if document.hidden_text else []
    try:
        pages, page_warnings = await transcribe_missing(llm, document.pages, doc_id=entry.id, model=model)
    except ClaudeBadOutput as exc:
        return base.model_copy(update={"failed": str(exc)})
    warnings += page_warnings
    if not prompt_pages(pages):
        return base.model_copy(update={"failed": NO_TEXT_ERROR, "warnings": warnings})
    found_injection = injection_warnings(pages)
    warnings += found_injection
    signals += ["injection_phrases"] if found_injection else []
    data = ExtractionInput(
        doc_id=entry.id,
        sha256=entry.sha256,
        pages=pages,
        today=entry.today,
        language=PERSONA_LANGUAGE,
        region=entry.region,
        country="DE",
        person_name="",
        known_parties=[],
        simulated_today=entry.today,
    )
    try:
        extraction = await extract_document(llm, data, model=model)
    except (ExtractionError, ClaudeBadOutput) as exc:
        return base.model_copy(update={"failed": str(exc), "warnings": warnings, "signals": signals})
    verification = verify_extraction(
        entry.id, extraction, pages, check_reading=True, injected=bool(found_injection)
    )
    if any(verified.slot_key == CHECK_SLOT for verified in verification.items):
        signals.append("reading_incomplete")
    # the placeholder of an empty reading without a remedy notice names no obligation: it is never scored
    scored = [
        verified
        for verified in verification.items
        if not (verified.slot_key == CHECK_SLOT and verified.item.date.type == "none")
    ]
    ctx = ordnung_rule_context(entry, extraction, pages)
    computed = [compute_item(v, ctx, postal_buffer_days=POSTAL_BUFFER_DAYS) for v in scored]
    terms = contract_terms(extraction)
    contract = None
    if terms is not None:
        result = compute_contract(terms, ctx, postal_buffer_days=POSTAL_BUFFER_DAYS)
        contract = PredictedContract(current_term_end=result.current_term_end, cancel_by=result.cancel_by)
    iban_warning = _payment_signal(extraction)
    if iban_warning:
        signals.append("invalid_iban")
    warnings += [
        *extraction.warnings,
        *verification.warnings,
        *remedy_warnings(extraction.remedy),
        *([iban_warning] if iban_warning else []),
    ]
    sender = extraction.sender
    return base.model_copy(
        update={
            "kind": extraction.kind,
            "sender_name": sender.name if sender else None,
            "sender_kind": sender.kind if sender else None,
            "delivery_scope": ctx.delivery_scope,
            "document_date": iso_or_none(extraction.document_date),
            "references": [reference.value for reference in extraction.references],
            "amounts": extraction_amounts(extraction),
            "remedy_type": extraction.remedy.type if extraction.remedy else "none",
            "items": [_ordnung_item(v, c) for v, c in zip(scored, computed, strict=True)],
            "contract": contract,
            "warnings": list(dict.fromkeys(w for w in warnings if w.strip())),
            "signals": signals,
        }
    )


# --------------------------------------------------------------------------------------------------
# Conditions: llm_only, llm_rules_text and llm_rules_tool
# --------------------------------------------------------------------------------------------------


class BaselineReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(description="The label as printed, e.g. Steuernummer.")
    value: str = Field(description="The identifier exactly as printed.")


class BaselineItem(BaseModel):
    """One obligation and the exact final day by which it must be fulfilled."""

    model_config = ConfigDict(extra="ignore")

    kind: ItemKind
    title: str = Field(description="Short English title.")
    quote: str = Field(description="The sentence of the letter that sets the date, copied verbatim.")
    computation: str = Field(
        description="Step-by-step working that leads to due_date (start, delivery day, counting, "
        "weekend/holiday adjustments, rule applied). Written before due_date."
    )
    due_date: str | None = Field(
        description="The exact final day, ISO YYYY-MM-DD; null if it cannot be determined."
    )
    confidence: Literal["high", "medium", "low"]
    amount: float | None = Field(default=None, description="The sum for payments (a number), else null.")


class BaselineContract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    current_term_end: str | None = Field(description="Last day of the current term, ISO YYYY-MM-DD.")
    cancel_by: str | None = Field(
        description="Last day a cancellation must reach the provider to end the contract at "
        "current_term_end, ISO YYYY-MM-DD."
    )


class BaselineOutput(BaseModel):
    """The record of one letter: what it is, who sent it, and every obligation with its final date."""

    model_config = ConfigDict(extra="ignore")

    kind: DocumentKind
    sender_name: str
    document_date: str | None = Field(description="The letter's own date, ISO YYYY-MM-DD, or null.")
    references: list[BaselineReference] = Field(default_factory=list)
    amounts: list[float] = Field(
        default_factory=list, description="Sums to pay, to receive or set by the decision (numbers)."
    )
    items: list[BaselineItem]
    remedy_type: RemedyType
    contract: BaselineContract | None = None
    warnings: list[str] = Field(default_factory=list)


@functools.cache
def baseline_schema() -> dict[str, Any]:
    """JSON schema of :class:`BaselineOutput` for ``--json-schema`` (``$ref``s inlined)."""
    return schema_for(BaselineOutput)


def baseline_request(
    entry: Entry, document: PreparedDocument, condition: ConditionName, *, model: str
) -> LLMRequest:
    """The request for ``llm_only``, ``llm_rules_text`` or ``llm_rules_tool`` (``purpose="eval_baseline"``).

    The tool condition's request adds the rules-only MCP server (pinned to the letter's today), the
    permission for its tools only and a cost cap; its prompt version carries the tools' digest.
    """
    system_version, system = load_prompt("llm_only_system")
    versions = [f"s{system_version}"]
    if condition == "llm_rules_text":
        rules_version, rules = load_prompt(RULES_PROMPT)
        system = f"{system}\n\n{rules}"
        versions.append(f"r{rules_version}")
    if condition == TOOLS_CONDITION:
        tools_version, note = load_prompt(TOOLS_PROMPT)
        system = f"{system}\n\n{note}"
        versions.append(f"t{tools_version}")
    attachments: list[Attachment] = []
    if entry.photo:
        if entry.media_type not in IMAGE_TYPES:
            raise ValueError(f"{entry.id}: unsupported photo type {entry.media_type}")
        attachments.append(Attachment(path=document.file, media_type=entry.media_type))
        document_version, document_text = render_prompt("document_image")
        mode = "image"
    else:
        textless = [page.page for page in document.pages if not page.text.strip()]
        if textless:
            # Ordnung would transcribe these pages; the baselines would silently never see them.
            raise ValueError(
                f"{entry.id}: page(s) {textless} have no text layer — the baselines cannot see them"
            )
        text = page_delimited(prompt_pages(document.pages))
        document_version, document_text = render_prompt(
            "document_text", untrusted={"document": wrap_untrusted(text)}
        )
        mode = "text"
    user_version, prompt = render_prompt(
        "llm_only",
        untrusted={"document": document_text},
        today=entry.today,
        weekday=entry.today_date.strftime("%A"),
        region=entry.region,
        region_name=REGION_NAMES.get(entry.region, entry.region),
    )
    versions += [f"u{user_version}", f"d{document_version}", f"h{baseline_prompt_digest(condition)[:8]}"]
    request = LLMRequest(
        purpose="eval_baseline",
        prompt=prompt,
        system=system,
        schema=baseline_schema(),
        attachments=attachments,
        doc_ids=[entry.id],
        model=model,
        cache_key=canonical_json(
            {
                "condition": condition,
                "doc": entry.sha256,
                "mode": mode,
                "today": entry.today,
                "region": entry.region,
            }
        ),
        prompt_version=".".join([condition, *versions]),
    )
    if condition != TOOLS_CONDITION:
        return request
    # The rules server counts from the letter's "today" by default, like every other condition.
    return request.model_copy(
        update={
            "mcp_config": rules_tools.rules_server_config(today=entry.today),
            "allowed_tools": list(TOOLS_ALLOWED),
            "max_budget_usd": TOOLS_BUDGET_USD,
        }
    )


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def baseline_prompt_names(condition: str) -> list[str]:
    extra = {"llm_rules_text": [RULES_PROMPT], TOOLS_CONDITION: [TOOLS_PROMPT]}.get(condition, [])
    return [*BASELINE_PROMPTS, *extra]


@functools.cache
def tool_definitions_digest() -> str:
    """Digest of the rules tools as the model sees them (server instructions; names, descriptions
    and input schemas of the tools)."""
    return text_sha(
        canonical_json({"instructions": rules_tools.INSTRUCTIONS, "tools": rules_tools.tool_definitions()})
    )


@functools.cache
def baseline_prompt_digest(condition: str) -> str:
    """Digest of the full text of the baseline prompts and the answer schema.

    It is part of the request's ``prompt_version`` (and so of the replay key): editing a prompt or the
    schema without bumping a ``version`` header makes recorded answers miss loudly instead of being
    replayed for a prompt they were not made with.
    """
    parts = {name: load_prompt(name) for name in baseline_prompt_names(condition)}
    basis: dict[str, Any] = {"prompts": parts, "schema": baseline_schema()}
    if condition == TOOLS_CONDITION:
        basis["tools"] = tool_definitions_digest()  # a changed tool description is a changed prompt
    return text_sha(canonical_json(basis))


def ordnung_prompt_hashes() -> dict[str, tuple[str, str]]:
    """``name → (version, digest)`` of the app prompts (and extraction schema) the ordnung condition sends.

    The app's replay keys hold only the prompt versions, so the runner compares these digests with
    the ones stored next to the recorded answers (see ``evals.run``).
    """
    hashes = {
        name: (version, text_sha(body))
        for name in ORDNUNG_PROMPTS
        for version, body in [ordnung_prompts.load(name)]
    }
    hashes["extraction_schema"] = (hashes["extract_system"][0], text_sha(canonical_json(extraction_schema())))
    hashes["transcription_schema"] = (
        hashes["transcribe_system"][0],
        text_sha(canonical_json(transcription_schema())),
    )
    return hashes


def parse_baseline(response: LLMResponse) -> BaselineOutput:
    """Validate a baseline answer (structured ``data`` or JSON inside the text)."""
    payload = response.data if response.data is not None else extract_json(response.text)
    return BaselineOutput.model_validate(payload if payload is not None else {})


def baseline_repair_request(request: LLMRequest, problems: str) -> LLMRequest:
    """The same request with the validation problems appended (its own cache key and version)."""
    version, note = render_prompt("repair", errors=problems)
    return request.model_copy(
        update={
            "prompt": f"{request.prompt}\n\n{note}",
            "cache_key": f"{request.cache_key}|repair",
            "prompt_version": f"{request.prompt_version}.repair{version}",
        }
    )


async def complete_baseline(
    llm: LLMService, request: LLMRequest, tool_calls: list[ToolCall] | None = None
) -> BaselineOutput:
    """Run a baseline request with one repair attempt, like the extraction step gets.

    Raises :class:`ValidationError` if the repaired answer is still invalid. The model's tool calls
    (of both attempts) are appended to ``tool_calls`` as they arrive, so they survive a failure.
    """
    response = await llm.complete(request)
    if tool_calls is not None:
        tool_calls.extend(response.tool_calls)
    try:
        return parse_baseline(response)
    except ValidationError as first:
        problems = validation_problems(first)
    repaired = await llm.complete(baseline_repair_request(request, problems))
    if tool_calls is not None:
        tool_calls.extend(repaired.tool_calls)
    return parse_baseline(repaired)


def tool_uses(calls: Sequence[ToolCall]) -> list[ToolUse]:
    """The recorded tool calls as the scorer needs them.

    Policy: a rules tool answers with a JSON object, so any other answer (the CLI's error text for
    refused arguments, or no answer) is a failed call; the date is kept for the date tools
    (``compute_deadline``'s ``due_date``, ``add_working_days``' ``date``).
    """
    uses = []
    for call in calls:
        name = call.name.removeprefix(TOOL_PREFIX)
        parsed = _json_object(call.result)
        data = parsed or {}
        due = iso_or_none(data.get("due_date")) if name == "compute_deadline" else None
        day = iso_or_none(data.get("date")) if name == "add_working_days" else None
        ok = parsed is not None
        error = None if ok else " ".join((call.result or "no answer").split())[:300]
        uses.append(ToolUse(name=name, input=call.input, ok=ok, due_date=due, date=day, error=error))
    return uses


def _json_object(text: str | None) -> dict[str, Any] | None:
    try:
        value = json.loads(text or "")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def baseline_prediction(entry: Entry, output: BaselineOutput, *, condition: str, model: str) -> Prediction:
    """A baseline answer in the shared prediction shape."""
    items = [
        PredictedItem(
            kind=item.kind,
            title=item.title,
            due_date=iso_or_none(item.due_date),
            amount=item.amount,
            quote=item.quote,
            confidence=item.confidence,
            explanation=item.computation,
        )
        for item in output.items
    ]
    contract = (
        PredictedContract(
            current_term_end=iso_or_none(output.contract.current_term_end),
            cancel_by=iso_or_none(output.contract.cancel_by),
        )
        if output.contract
        else None
    )
    return Prediction(
        entry_id=entry.id,
        condition=condition,
        model=model,
        kind=output.kind,
        sender_name=output.sender_name,
        document_date=iso_or_none(output.document_date),
        references=[reference.value for reference in output.references],
        amounts=unique_amounts([*output.amounts, *(i.amount for i in output.items if i.amount is not None)]),
        remedy_type=output.remedy_type,
        items=items,
        contract=contract,
        warnings=[w for w in output.warnings if w.strip()],
    )


async def run_baseline(
    entry: Entry, document: PreparedDocument, llm: LLMService, *, model: str, condition: ConditionName
) -> Prediction:
    """The ``llm_only`` / ``llm_rules_text`` / ``llm_rules_tool`` condition for one letter."""
    if not entry.photo and not prompt_pages(document.pages):
        return Prediction(entry_id=entry.id, condition=condition, model=model, failed=NO_TEXT_ERROR)
    request = baseline_request(entry, document, condition, model=model)
    calls: list[ToolCall] = []
    try:
        output = await complete_baseline(llm, request, calls)
    except (ValidationError, ClaudeBadOutput) as exc:
        message = f"invalid answer after the repair attempt: {exc}"[:500]
        prediction = Prediction(entry_id=entry.id, condition=condition, model=model, failed=message)
    else:
        prediction = baseline_prediction(entry, output, condition=condition, model=model)
    if condition == TOOLS_CONDITION:
        prediction = prediction.model_copy(update={"tools": tool_uses(calls)})
    return prediction


# --------------------------------------------------------------------------------------------------
# Dispatch and cache fingerprints
# --------------------------------------------------------------------------------------------------


async def run_condition(
    condition: ConditionName, entry: Entry, document: PreparedDocument, llm: LLMService, *, model: str
) -> Prediction:
    """Run one condition on one letter (model and infrastructure errors propagate as ``LLMError``)."""
    if condition == "ordnung":
        return await run_ordnung(entry, document, llm, model=model)
    return await run_baseline(entry, document, llm, model=model, condition=condition)


def _digest(paths: Sequence[Path]) -> str:
    sha = hashlib.sha256()
    for path in paths:
        if path.is_file():
            sha.update(path.name.encode())
            sha.update(path.read_bytes())
    return sha.hexdigest()[:16]


@functools.cache
def _code_digest(condition: str) -> str:
    """A digest of the code a cached prediction depends on (so a code change invalidates it)."""
    own = [EVALS_DIR / "conditions.py", EVALS_DIR / "records.py"]
    shared = [
        _SRC / "models.py",
        _SRC / "llm" / "schemas.py",
        *(_SRC / "ingest" / f"{name}.py" for name in ("extract", "intake", "text")),
    ]
    if condition == TOOLS_CONDITION:  # the tools' answers come from the rules engine
        tools = [_SRC / "assistant" / "rules_tools.py", _SRC / "money" / "iban.py"]
        return _digest([*own, *shared, *tools, *sorted((_SRC / "rules").glob("*.py"))])
    if condition != "ordnung":
        return _digest([*own, *shared])
    ingest = [
        _SRC / "ingest" / f"{name}.py"
        for name in (
            "conflicts",
            "extract",
            "gaps",
            "intake",
            "normalize",
            "pipeline",
            "plan",
            "text",
            "transcribe",
            "verify",
        )
    ]
    rules = sorted((_SRC / "rules").glob("*.py"))
    return _digest([*own, *shared, *ingest, *rules, _SRC / "secretary" / "scam.py"])


def fingerprint(condition: str, model: str) -> str:
    """Identifies everything a prediction depends on besides the letter: prompts, code, model.

    Prompts count with their full text (not only their version header), so an edit invalidates
    cached predictions even when nobody bumped the version.
    """
    parts: dict[str, Any] = {"evals": __version__, "condition": condition, "model": model}
    if condition == "ordnung":
        parts["prompts"] = ordnung_prompt_hashes()
    else:
        parts["prompts"] = {
            name: [load_prompt(name)[0], baseline_prompt_digest(condition)]
            for name in baseline_prompt_names(condition)
        }
    parts["code"] = _code_digest(condition)
    return hashlib.sha256(canonical_json(parts).encode()).hexdigest()[:16]
