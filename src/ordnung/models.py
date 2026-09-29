"""Domain and API models — the single source of truth shared by store, services, API and LLM schemas.

Dates are ISO strings (``YYYY-MM-DD``) throughout the models so they serialise identically in the
database, the API and the LLM outputs. Timestamps are ISO-8601 UTC strings.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------------------------------

DocumentKind = Literal[
    "tax_assessment",
    "tax_letter",
    "authority_letter",
    "residence_permit",
    "social_insurance",
    "health_insurance",
    "invoice",
    "dunning",
    "contract",
    "contract_change",
    "price_increase",
    "cancellation_confirmation",
    "payslip",
    "bank_letter",
    "insurance",
    "rent_lease",
    "utility_bill",
    "university",
    "employment",
    "appointment",
    "fine",
    "receipt",
    "identity_document",
    "broadcasting_fee",
    "certificate",
    "personal",
    "other",
]
DOCUMENT_KINDS: tuple[str, ...] = DocumentKind.__args__  # type: ignore[attr-defined]
#: Letters whose deadlines the rules engine handles specially. They are not a :data:`DocumentKind`: the
#: model names one in a field of its own (``DocumentExtraction.high_stakes_kind``, extraction prompt
#: version 9), and code files a letter under one from the reading, checking the kind the model names
#: against it (:mod:`ordnung.rules.routing`, ADR 0010); answers recorded before version 9 name none and
#: are filed as before.
HighStakesKind = Literal[
    "court_payment_order",
    "enforcement_order",
    "dismissal",
    "landlord_notice",
    "rent_increase",
    "operating_costs",
]
HIGH_STAKES_KINDS: tuple[str, ...] = HighStakesKind.__args__  # type: ignore[attr-defined]
#: Letters that demand an earlier invoice's money again and take over its payment: a reminder, and a
#: court order about the claim (the model may read a Mahnbescheid as a reminder; code files it as a
#: court order, and it must still count as one).
PAYMENT_DEMAND_KINDS: tuple[str, ...] = ("dunning", "court_payment_order", "enforcement_order")
#: The kind stored on a letter: the model's reading, or a high-stakes kind code assigned.
LetterKind = Literal[DocumentKind, HighStakesKind]
LETTER_KINDS: tuple[str, ...] = (*DOCUMENT_KINDS, *HIGH_STAKES_KINDS)

#: ``held``: stored and read on this computer only, waiting for the person to say it may be sent to
#: Claude (a file from the watched folder, or an attachment of one — :mod:`ordnung.ingest.held`).
DocumentStatus = Literal["queued", "processing", "processed", "needs_review", "failed", "held"]
Direction = Literal["incoming", "outgoing", "note"]
PartyKind = Literal[
    "authority",
    "tax_office",
    "immigration_office",
    "health_insurer",
    "insurer",
    "bank",
    "landlord",
    "employer",
    "university",
    "utility",
    "telecom",
    "retailer",
    "doctor",
    "gym",
    "public_broadcaster",
    "transport",
    "person",
    "company",
    "other",
]
ItemKind = Literal["deadline", "payment", "appointment", "task", "expiry", "reminder", "milestone"]
ItemStatus = Literal["open", "done", "dismissed", "snoozed", "missed"]
Priority = Literal["low", "normal", "high", "critical"]
Area = Literal[
    "home",
    "work",
    "study",
    "health",
    "money",
    "residence",
    "tax",
    "mobility",
    "insurance",
    "leisure",
    "family",
    "other",
]
AREAS: tuple[str, ...] = Area.__args__  # type: ignore[attr-defined]
SuggestionKind = Literal[
    "deadline", "saving", "risk", "followup", "hygiene", "tax", "opportunity", "scam", "info"
]
SuggestionStatus = Literal["new", "accepted", "dismissed", "snoozed", "done", "expired"]
#: Letters an Idea may offer to draft (part of the review model's schema, so kept as it was).
SuggestedDraftKind = Literal["cancellation", "objection", "general_reply"]
#: Letters written from fixed templates only (:mod:`ordnung.drafts.templates`).
TemplateDraftKind = Literal[
    "withdrawal",
    "extension_request",
    "payment_plan",
    "defect_notice",
    "data_access",
    "receipts_inspection",
    "deposit_return",
    "address_change",
]
DraftKind = Literal[SuggestedDraftKind, TemplateDraftKind]
ContractCategory = Literal[
    "mobile",
    "internet",
    "energy",
    "gas",
    "insurance",
    "gym",
    "streaming",
    "software",
    "rent",
    "employment",
    "transport",
    "bank",
    "membership",
    "other",
]
CostInterval = Literal["monthly", "quarterly", "yearly", "once"]
NoticeUnit = Literal["days", "weeks", "months"]
NoticeBasis = Literal["end_of_term", "any_time", "end_of_month"]
PeriodUnit = Literal["days", "weeks", "months", "years", "business_days", "werktage"]
Confidence = Literal["high", "medium", "low"]
Grounding = Literal["verified", "model_read", "unverified", "user"]
ContractRegime = Literal[
    "bgb309_new",
    "bgb309_old",
    "tkg56",
    "vvg11",
    "sgbv175",
    "stromgvv20",
    "rent573c",
    "employment622",
    "bgb675h",
    "as_written",
]
RemedyType = Literal["einspruch", "widerspruch", "klage", "none", "unclear"]
DateNature = Literal["objection", "payment", "declaration", "notice", "appointment", "other"]
#: How a model call's answer turned out: ``invalid`` — it did not validate (a repair may follow);
#: ``repaired`` — a repair's answer validated; ``failed`` — the call errored or its repair was invalid too.
CallOutcome = Literal["ok", "invalid", "repaired", "failed"]
#: What a step of reading a letter did (``run`` is the reading itself, the root of its spans).
SpanKind = Literal["run", "model", "ocr", "verify", "rules", "link", "plan"]
SpanStatus = Literal["ok", "error"]
#: How a reading of a letter ended: ran to the end (``done``), ``failed``, or was interrupted —
#: ``paused`` by a usage limit or ``stopped`` by a shutdown — and is read again later.
ReadingEnd = Literal["done", "failed", "paused", "stopped"]


class _Model(BaseModel):
    # Serialised models always carry every field, so the API schema (OpenAPI, and the web app's
    # generated types) marks fields with defaults as required in responses.
    model_config = ConfigDict(
        extra="ignore", populate_by_name=True, json_schema_serialization_defaults_required=True
    )


# --------------------------------------------------------------------------------------------------
# Evidence & dates
# --------------------------------------------------------------------------------------------------


class Box(_Model):
    """Highlight rectangle in relative coordinates (0..1) on a rendered page image."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class Evidence(_Model):
    """Where a fact came from.

    ``grounding``: ``verified`` — quote located in the PDF text layer with all digits matching;
    ``model_read`` — located only in the AI transcription of a scan/photo; ``unverified`` — not found;
    ``user`` — confirmed by the person.
    """

    doc_id: str
    page: int | None = None
    quote: str
    grounding: Grounding = "unverified"
    value_consistent: bool = True
    score: float = 0.0
    boxes: list[Box] = Field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.grounding in ("verified", "user")


class DateSpec(_Model):
    """What a document *says* about a date. The rules engine turns this into a concrete date."""

    type: Literal["fixed", "relative", "none"]
    date: str | None = None
    time: str | None = None
    anchor: Literal["document_date", "deemed_delivery", "receipt", "explicit_date", "today"] | None = None
    anchor_date: str | None = None
    amount: int | None = None
    unit: PeriodUnit | None = None
    delivery_rule: Literal["none", "de_admin_post", "de_admin_electronic", "de_admin_portal"] = "none"
    shift_rule: Literal["auto", "none", "next_business_day"] = "auto"
    nature: DateNature = "other"
    legal_basis: str | None = None
    text: str = ""


class ComputationStep(_Model):
    label: str
    date: str | None = None
    rule_id: str | None = None
    citation: str | None = None


class ComputationReceipt(_Model):
    due_date: str | None
    send_by: str | None = None
    safe_date: str | None = None
    holiday_calendar: str = ""
    summary: str = ""
    steps: list[ComputationStep] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: Confidence = "high"


class ExtractedRecurrence(_Model):
    # How a reading says a to-do repeats. Its JSON schema is part of the extraction prompt's, which the
    # benchmark's recordings pin by version (evals/recorded/*/prompts.lock.json), so it keeps prompt 9's
    # fields and no docstring: the prompt version that asks for a working day reads a Recurrence.

    interval: int = 1
    unit: Literal["days", "weeks", "months", "years"] = "months"


class Recurrence(ExtractedRecurrence):
    """How a to-do repeats: every ``interval`` ``unit``s. ``working_day``: the working day (Werktag) of
    each month it is due by ("spätestens am dritten Werktag eines jeden Monats" is 3), for a rule in months
    or years; Ordnung computes each month's date from it (ordnung.recurrence, point 8). A reading gives
    none yet (:class:`ExtractedRecurrence`)."""

    working_day: int | None = Field(default=None, ge=1, le=10)


# --------------------------------------------------------------------------------------------------
# Core entities
# --------------------------------------------------------------------------------------------------


class Identifier(_Model):
    label: str
    value: str


class Party(_Model):
    id: str
    name: str
    kind: PartyKind = "other"
    aliases: list[str] = Field(default_factory=list)
    identifiers: list[Identifier] = Field(default_factory=list)
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    notes: str | None = None
    region: str | None = None
    ibans: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class Case(_Model):
    id: str
    title: str
    party_id: str | None = None
    reference: str | None = None
    status: Literal["open", "closed"] = "open"
    summary: str | None = None
    area: Area = "other"
    created_at: str
    updated_at: str


class Remedy(_Model):
    type: RemedyType = "none"
    addressee: str | None = None
    period_text: str | None = None
    form_text: str | None = None
    quote: str | None = None


class PaymentDetails(_Model):
    iban: str | None = None
    payee: str | None = None
    iban_valid: bool | None = None
    reference: str | None = None


class KeyFact(_Model):
    label: str
    value: str
    evidence: Evidence | None = None


class Document(_Model):
    id: str
    sha256: str
    filename: str
    mime: str
    pages: int = 1
    direction: Direction = "incoming"
    source: str = "upload"
    status: DocumentStatus = "queued"
    error: str | None = None
    kind: LetterKind | None = None
    area: Area | None = None
    title: str | None = None
    summary: str | None = None
    explanation: str | None = None
    language: str | None = None
    doc_date: str | None = None
    received_date: str | None = None
    party_id: str | None = None
    case_id: str | None = None
    urgency: Priority | None = None
    text_mode: Literal["text", "vision"] | None = None
    key_facts: list[KeyFact] = Field(default_factory=list)
    references: list[Identifier] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tax_relevant: bool = False
    tax_note: str | None = None
    tags: list[str] = Field(default_factory=list)
    remedy: Remedy | None = None
    payment: PaymentDetails | None = None
    hidden_text: bool = False
    ai_private: bool = False
    ai_processed_at: str | None = None
    created_at: str
    updated_at: str
    processed_at: str | None = None
    deleted_at: str | None = None  # set while the document is in the trash


class ContractComputation(_Model):
    regime: ContractRegime = "as_written"
    current_term_end: str | None = None
    cancel_by: str | None = None
    send_by: str | None = None
    safe_date: str | None = None
    confidence: Confidence = "low"
    warnings: list[str] = Field(default_factory=list)
    next_renewal: str | None = None
    earliest_exit: str | None = None
    summary: str = ""
    notes: list[str] = Field(default_factory=list)
    steps: list[ComputationStep] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)


class ContractTerms(_Model):
    """The rule-relevant part of a contract (input of ``rules.contracts.compute_contract``).

    ``notice_day``: a cancellation must arrive by this day of a month to end the contract at the end of
    that month (read with ``notice_basis`` "end_of_month"; a notice period stated too applies as well).
    ``notice_before_end``: a contract with an end date whose own clause lets it be ended earlier by
    ordinary notice (read for a job, § 15 Abs. 4 TzBfG). The rules engine's docstrings hold the policies."""

    category: ContractCategory = "other"
    party_kind: str | None = None
    concluded_date: str | None = None
    start_date: str | None = None
    initial_term_months: int | None = None
    renewal_term_months: int | None = None
    notice_value: int | None = None
    notice_unit: NoticeUnit | None = None
    notice_basis: NoticeBasis | None = None
    notice_day: int | None = None
    notice_before_end: bool = False
    end_date: str | None = None
    is_consumer: bool = True
    is_basic_supply: bool = False
    status: Literal["active", "cancelled", "ended"] = "active"


class CancellationSent(_Model):
    """The person's cancellation of a contract, marked as sent (a ``cancellation`` letter with the
    contract's id): the decision is taken, what is left is waiting for the provider's confirmation."""

    draft_id: str
    sent_on: str | None = None
    channel: str | None = None


class Contract(_Model):
    id: str
    party_id: str | None = None
    case_id: str | None = None
    name: str
    category: ContractCategory = "other"
    customer_number: str | None = None
    concluded_date: str | None = None
    start_date: str | None = None
    initial_term_months: int | None = None
    renewal_term_months: int | None = None
    notice_value: int | None = None
    notice_unit: NoticeUnit | None = None
    notice_basis: NoticeBasis | None = None
    notice_day: int | None = None
    notice_before_end: bool = False
    end_date: str | None = None
    is_basic_supply: bool = False
    cost_amount: float | None = None
    cost_currency: str = "EUR"
    cost_interval: CostInterval | None = None
    is_consumer: bool = True
    status: Literal["active", "cancelled", "ended"] = "active"
    computed: ContractComputation | None = None
    source_doc_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    area: Area = "other"
    created_at: str
    updated_at: str
    # Worked out on read by the API (never stored): whether a consumer cancellation letter applies
    # (not to the broadcasting fee, statutory obligations or a job) and, if not, why.
    cancellable: bool = True
    cancel_hint: str | None = None
    # Worked out on read by the API: the person's cancellation of it, marked as sent (the decision is
    # taken — no "decide by", no "Draft cancellation"; walkthrough of phase 2).
    cancellation_sent: CancellationSent | None = None

    def terms(self, party_kind: str | None = None) -> ContractTerms:
        return ContractTerms(
            category=self.category,
            party_kind=party_kind,
            concluded_date=self.concluded_date,
            is_basic_supply=self.is_basic_supply,
            start_date=self.start_date,
            initial_term_months=self.initial_term_months,
            renewal_term_months=self.renewal_term_months,
            notice_value=self.notice_value,
            notice_unit=self.notice_unit,
            notice_basis=self.notice_basis,
            notice_day=self.notice_day,
            notice_before_end=self.notice_before_end,
            end_date=self.end_date,
            is_consumer=self.is_consumer,
            status=self.status,
        )

    def monthly_cost(self) -> float | None:
        if self.cost_amount is None or self.cost_interval in (None, "once"):
            return None
        factor = {"monthly": 1.0, "quarterly": 1 / 3, "yearly": 1 / 12}[self.cost_interval]
        return round(self.cost_amount * factor, 2)


class Item(_Model):
    id: str
    kind: ItemKind
    title: str
    description: str | None = None
    action: str | None = None
    consequence: str | None = None
    due_date: str | None = None
    due_time: str | None = None
    send_by: str | None = None
    date_spec: DateSpec | None = None
    computation: ComputationReceipt | None = None
    amount: float | None = None
    currency: str | None = None
    direction: Literal["out", "in"] | None = None
    recurrence: Recurrence | None = None
    status: ItemStatus = "open"
    snoozed_until: str | None = None
    priority: Priority = "normal"
    area: Area = "other"
    party_id: str | None = None
    case_id: str | None = None
    contract_id: str | None = None
    doc_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    grounding: Grounding = "unverified"
    slot_key: str | None = None
    user_modified: bool = False
    due_date_source: Literal["computed", "fixed", "manual", "none"] = "none"
    origin: Literal["extracted", "manual", "rule", "capture", "draft"] = "extracted"
    location: str | None = None
    filed_on: str | None = None  # the (possibly simulated) day the item entered the ledger
    created_at: str
    updated_at: str
    completed_at: str | None = None


class SuggestionRef(_Model):
    type: Literal["document", "item", "contract", "party", "case", "draft"]
    id: str


class SuggestionAction(_Model):
    type: Literal["draft", "open", "mark_done", "snooze", "none"] = "none"
    draft_kind: SuggestedDraftKind | None = None
    target_type: str | None = None
    target_id: str | None = None
    label: str | None = None


class Suggestion(_Model):
    id: str
    kind: SuggestionKind
    title: str
    body: str
    rationale: str | None = None
    priority: Priority = "normal"
    status: SuggestionStatus = "new"
    snoozed_until: str | None = None
    fingerprint: str
    refs: list[SuggestionRef] = Field(default_factory=list)
    action: SuggestionAction | None = None
    source: Literal["rule", "review"] = "rule"
    rule_id: str | None = None
    savings_estimate: float | None = None
    due_date: str | None = None
    created_at: str
    updated_at: str


class SendChannel(_Model):
    channel: Literal["online_button", "email", "fax", "letter", "registered_letter", "in_person", "portal"]
    label: str
    allowed: bool = True
    recommended: bool = False
    note: str | None = None
    citation: str | None = None


class SendGuidance(_Model):
    send_by: str | None = None
    must_arrive_by: str | None = None
    #: The usual time to post it has passed: a letter posted today may arrive too late (``send_by`` is today).
    post_too_late: bool = False
    form: Literal["text_form", "written_form", "any"] = "text_form"
    form_note: str | None = None
    channels: list[SendChannel] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)


class DraftCheck(_Model):
    id: str
    label: str
    ok: bool
    detail: str | None = None


class Draft(_Model):
    id: str
    kind: DraftKind
    language: str = "de"
    party_id: str | None = None
    case_id: str | None = None
    doc_id: str | None = None
    contract_id: str | None = None
    sender_block: str = ""
    recipient_block: str = ""
    place_date: str = ""
    subject: str = ""
    body: str = ""
    body_translation: str = ""
    enclosures: list[str] = Field(default_factory=list)
    notes_for_user: list[str] = Field(default_factory=list)
    checks: list[DraftCheck] = Field(default_factory=list)
    send_guidance: SendGuidance | None = None
    sent_channel: str | None = None
    status: Literal["draft", "final", "sent"] = "draft"
    sent_at: str | None = None
    #: The Einschreiben's tracking number, normalised (``drafts.proof.parse_tracking_number``).
    tracking_number: str | None = None
    #: The day the person said the sent letter was answered (``drafts.sent.mark_answered``) and the
    #: letter they said is the answer (``None``: answered by phone, e-mail … or not said).
    answered_on: str | None = None
    answer_doc_id: str | None = None
    created_at: str
    updated_at: str


def _iso_day(value: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ValueError(f"“{value}” is not a date; use the form YYYY-MM-DD.") from exc


#: A ``YYYY-MM-DD`` day (validated and normalised).
IsoDay = Annotated[str, AfterValidator(_iso_day)]


def _one_line(value: str) -> str:
    return " ".join(value.split())


#: Text that ends up in a letter's subject line: line breaks and runs of spaces become one space.
OneLine = Annotated[str, AfterValidator(_one_line)]


class LetterDetails(_Model):
    """Facts a template letter needs besides the letter, contract or person it is about.

    Everything is optional here; each template names the facts it requires
    (:data:`ordnung.drafts.templates.TEMPLATES`). Dates are ISO ``YYYY-MM-DD`` (anything else is refused
    with a clear message, never a server error), amounts in euros.
    """

    subject_matter: OneLine | None = Field(
        default=None, max_length=200, description="what was ordered or agreed, e.g. 'Kaffeemaschine'"
    )
    ordered_on: IsoDay | None = Field(default=None, description="the day the contract was concluded")
    received_on: IsoDay | None = Field(default=None, description="the day the goods arrived")
    instructions_missing: bool = Field(
        default=False, description="no (or wrong) instructions about the right of withdrawal were given"
    )
    deadline: IsoDay | None = Field(default=None, description="the deadline that should be extended")
    until: IsoDay | None = Field(default=None, description="the new date asked for")
    amount: float | None = Field(default=None, ge=0, description="the total owed, or the deposit")
    instalment: float | None = Field(default=None, gt=0, description="the monthly instalment offered")
    first_instalment: IsoDay | None = Field(default=None, description="the day of the first instalment")
    defect: str | None = Field(default=None, max_length=1000, description="what is broken or wrong")
    noticed_on: IsoDay | None = Field(default=None, description="since when the defect exists")
    fix_by: IsoDay | None = Field(default=None, description="the day by which it should be repaired")
    period: OneLine | None = Field(default=None, max_length=80, description="the billing period")
    moved_out_on: IsoDay | None = Field(default=None, description="the day the flat was handed back")
    moved_on: IsoDay | None = Field(default=None, description="the day of the move")
    old_address: str | None = Field(default=None, max_length=300)
    new_address: str | None = Field(default=None, max_length=300)
    recipient: str | None = Field(
        default=None, max_length=300, description="name and address of a recipient not in Ordnung yet"
    )


class Note(_Model):
    id: str
    text: str
    item_ids: list[str] = Field(default_factory=list)
    created_at: str


#: ``Document.source`` of a proof file: a private outgoing document that belongs to its letter
#: (``drafts.proof``) and is never listed or counted as a letter.
PROOF_SOURCE = "proof"


class SentSigner(_Model):
    """What a letter's PDF showed of the sender when it was marked as sent (the profile may change later)."""

    name: str = ""
    email: str = ""
    phone: str = ""


#: What a piece of proof of a sent letter is (``drafts.proof.PROOF_KINDS`` says what each one shows).
ProofKind = Literal[
    "posting_receipt",  # Einlieferungsbeleg
    "delivery_record",  # Auslieferungsbeleg
    "return_receipt",  # Rückschein
    "fax_report",  # Sendebericht
    "sent_email",
    "cancel_confirmation",  # § 312k BGB: the saved page or the provider's confirmation
    "other",
]


class Proof(_Model):
    """One piece of proof that a letter was sent or arrived. ``doc_id`` is its file: a private outgoing
    document (``source="proof"``) that is never sent to a model. ``on_date`` is the day it shows (the
    day posted, delivered, faxed or confirmed)."""

    id: str
    draft_id: str
    kind: ProofKind
    doc_id: str | None = None
    on_date: str | None = None
    note: str | None = None
    created_at: str
    updated_at: str


class CallNote(_Model):
    """A phone call the person noted (Gesprächsnotiz): when, with whom, what was said and what was
    promised. A promise with a date is waited for (``secretary.waiting``)."""

    id: str
    party_id: str | None = None
    case_id: str | None = None
    called_on: str
    contact: str | None = None
    summary: str
    promise: str | None = None
    promise_due: str | None = None
    promise_amount: float | None = None
    promise_kept_on: str | None = None
    created_at: str
    updated_at: str


class Activity(_Model):
    id: int
    ts: str
    kind: str
    message: str
    ref_type: str | None = None
    ref_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class LLMCallRecord(_Model):
    id: int
    ts: str
    purpose: str
    model: str
    backend: str
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    ok: bool = True
    error: str | None = None
    cache_hit: bool = False
    doc_ids: list[str] = Field(default_factory=list)
    pages_sent: int = 0
    bytes_sent: int = 0
    #: the replay and cache key (``purpose:prompt_version:model:sha256(inputs)``, ADR 0004); cleared
    #: when a document the call carried is deleted
    request_key: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None
    #: the model that answered, as the CLI reported it (``model`` is that model, else the one asked for)
    served_model: str | None = None
    job_id: str | None = None
    stage: str | None = None
    span_id: str | None = None
    #: the call (``id``) this call retried with the validation problems appended
    repair_of: int | None = None
    outcome: CallOutcome = "ok"


class Job(_Model):
    id: str
    kind: Literal["ingest", "reprocess", "review"] = "ingest"
    status: Literal["queued", "running", "waiting", "done", "failed"] = "queued"
    stage: str | None = None
    progress: float = 0.0
    doc_id: str | None = None
    attempts: int = 0
    force: bool = False
    not_before: str | None = None
    waiting_reason: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class ChatMessage(_Model):
    id: str
    thread_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[SuggestionRef] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


# --------------------------------------------------------------------------------------------------
# Profile & settings
# --------------------------------------------------------------------------------------------------


def _default_reminder_days() -> dict[str, list[int]]:
    return {
        "deadline": [14, 7, 3, 1],
        "payment": [7, 2],
        "appointment": [2, 0],
        "expiry": [90, 30, 7],
        "task": [3],
        "reminder": [0],
        "milestone": [7],
    }


class Profile(_Model):
    name: str = ""
    address: str = ""
    email: str = ""
    phone: str = ""
    language: str = "en"
    country: str = "DE"
    region: str = "NW"
    timezone: str = "Europe/Berlin"
    reminder_days: dict[str, list[int]] = Field(default_factory=_default_reminder_days)
    postal_buffer_days: int = 4
    is_student_visa: bool = False
    onboarded: bool = False
    #: The person's own account, only for letters that ask for money back (e.g. the deposit).
    iban: str = ""

    @property
    def known_region(self) -> str | None:
        """The Land the person chose during onboarding; ``None`` before (``region`` is then a default).

        The rules engine uses it for the payer's holidays and a tax letter's delivery day, so an unchosen
        default must never count as known (SPEC § 21: unknown region → nationwide holidays only).
        """
        return self.region if self.onboarded else None


class ModelSettings(_Model):
    transcribe: str = "sonnet"
    extract: str = "sonnet"
    review: str = "sonnet"
    ask: str = "sonnet"
    draft: str = "sonnet"
    brief: str = "haiku"
    capture: str = "haiku"
    bank: str = "haiku"


DesktopNotifyMode = Literal["off", "discreet", "full"]


class AppSettings(_Model):
    models: ModelSettings = Field(default_factory=ModelSettings)
    concurrency: int = 2
    inbox_dir: str | None = None
    #: Files from the watched folder are read by Claude at once; off (the default), they wait for the
    #: person's "Read these" (:mod:`ordnung.ingest.watcher`).
    inbox_auto_read: bool = False
    ocr: bool = True
    llm_brief: bool = True
    llm_review: bool = True
    #: The morning desktop notification (:mod:`ordnung.notify.desktop`): off, a count only, or the details.
    desktop_notifications: DesktopNotifyMode = "off"
    #: Local time (``HH:MM``) from which the day's desktop notification is shown.
    desktop_notify_time: str = "08:00"
    demo: bool = False
    simulated_today: str | None = None


CalendarSyncMode = Literal["discreet", "full"]
CalendarSyncErrorKind = Literal[
    "address",
    "auth",
    "forbidden",
    "not_found",
    "not_calendar",
    "network",
    "tls",
    "conflict",
    "server",
    "unavailable",
    "not_connected",
]


class CalendarSyncReport(_Model):
    """What one calendar sync did (:mod:`ordnung.calendar.caldav`)."""

    at: str
    sent: int = 0
    removed: int = 0
    unchanged: int = 0
    failed: int = 0
    #: events Ordnung had sent that were no longer in the calendar (sent again, counted in ``sent``)
    missing: int = 0
    error: str | None = None
    error_kind: CalendarSyncErrorKind | None = None


class CalendarSyncState(_Model):
    """The calendar-sync connection (meta ``calendar_sync``): where, in which mode, and a digest of
    every event Ordnung put there. Never the password (that lives in the OS keyring)."""

    url: str
    username: str
    mode: CalendarSyncMode = "discreet"
    calendar_name: str | None = None
    #: this data folder's connection: names its password in the keyring (a restored copy gets a new
    #: one, so it never reads or deletes the password of the Ordnung it came from)
    connection: str = ""
    #: resource name (``ordnung-<id>.ics``) → SHA-256 of the event as last sent
    events: dict[str, str] = Field(default_factory=dict)
    last: CalendarSyncReport | None = None
    #: automatic syncing waits after the server refused the password (until a manual sync or reconnect)
    paused: bool = False
    #: the app password was in the keyring when Ordnung last needed it (Settings never reads it)
    password_saved: bool = True
    #: the day Ordnung last checked that the events it sent are still in the calendar (ISO date)
    checked_on: str | None = None


class CalendarEventPreview(_Model):
    """One event exactly as calendar sync would send it."""

    uid: str
    summary: str
    #: ISO date (all-day) or local date-time with offset
    start: str
    all_day: bool
    description: str
    location: str | None = None
    #: when each alarm rings, in words ("3 days before at 09:00"), earliest first
    alarms: list[str] = Field(default_factory=list)
    #: how many of those (the first ones) fell before today: they won't ring any more
    alarms_passed: int = 0


# --------------------------------------------------------------------------------------------------
# LLM structured outputs
# --------------------------------------------------------------------------------------------------


class ExtractedParty(_Model):
    name: str
    kind: PartyKind = "other"
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    identifiers: list[Identifier] = Field(default_factory=list)


class ExtractedFact(_Model):
    label: str
    value: str
    quote: str


class ExtractedItem(_Model):
    kind: ItemKind
    title: str
    action: str | None = None
    consequence: str | None = None
    date: DateSpec
    amount: float | None = None
    currency: str | None = None
    direction: Literal["out", "in"] | None = None
    recurrence: ExtractedRecurrence | None = None
    priority: Priority = "normal"
    quote: str
    location: str | None = None


class ExtractedContract(_Model):
    name: str
    category: ContractCategory = "other"
    customer_number: str | None = None
    concluded_date: str | None = None
    start_date: str | None = None
    initial_term_months: int | None = None
    renewal_term_months: int | None = None
    notice_value: int | None = None
    notice_unit: NoticeUnit | None = None
    notice_basis: NoticeBasis | None = None
    notice_day: int | None = Field(default=None, ge=1, le=31)
    notice_before_end: bool = False
    end_date: str | None = None
    cost_amount: float | None = None
    cost_interval: CostInterval | None = None
    is_consumer: bool = True
    is_basic_supply: bool = False
    quotes: list[str] = Field(default_factory=list)


class ExtractedChange(_Model):
    type: Literal[
        "price_increase",
        "price_decrease",
        "terms_change",
        "cancellation_confirmation",
        "termination_by_provider",
        "other",
    ]
    effective_date: str | None = None
    old_amount: float | None = None
    new_amount: float | None = None
    cost_interval: CostInterval | None = None
    unit_price_old: str | None = None
    unit_price_new: str | None = None
    quote: str = ""


class DocumentExtraction(_Model):
    kind: DocumentKind
    #: the model's own answer (extraction prompt version 9, ADR 0010); code checks it
    #: (:func:`ordnung.rules.routing.classify_letter`). Readings recorded before have none.
    high_stakes_kind: HighStakesKind | None = None
    area: Area = "other"
    title: str
    language: str = "de"
    sender: ExtractedParty | None = None
    recipient_name: str | None = None
    document_date: str | None = None
    references: list[Identifier] = Field(default_factory=list)
    summary: str
    explanation: str
    key_facts: list[ExtractedFact] = Field(default_factory=list)
    items: list[ExtractedItem] = Field(default_factory=list)
    contract: ExtractedContract | None = None
    change: ExtractedChange | None = None
    remedy: Remedy | None = None
    payment: PaymentDetails | None = None
    urgency: Priority = "normal"
    tax_relevant: bool = False
    tax_note: str | None = None
    case_title: str = ""
    warnings: list[str] = Field(default_factory=list)
    transcript: str | None = None


class TranscriptionOutput(_Model):
    text: str
    language: str = "de"
    legible: bool = True
    notes: str | None = None


class ReviewSuggestion(_Model):
    kind: SuggestionKind
    title: str
    body: str
    rationale: str
    priority: Priority = "normal"
    refs: list[SuggestionRef] = Field(default_factory=list)
    action: SuggestionAction | None = None
    savings_estimate: float | None = None
    due_date: str | None = None


class ReviewOutput(_Model):
    suggestions: list[ReviewSuggestion] = Field(default_factory=list)


class BriefOutput(_Model):
    text: str


class CapturedItem(_Model):
    kind: ItemKind
    title: str
    date: DateSpec
    recurrence: Recurrence | None = None
    area: Area = "other"
    priority: Priority = "normal"
    location: str | None = None
    amount: float | None = None
    notes: str | None = None


class CaptureOutput(_Model):
    items: list[CapturedItem] = Field(default_factory=list)


class DraftOutput(_Model):
    subject: str
    body: str
    body_translation: str = ""
    enclosures: list[str] = Field(default_factory=list)
    notes_for_user: list[str] = Field(default_factory=list)


class DraftTranslationOutput(_Model):
    """A fresh translation of a letter the person edited ("Re-translate")."""

    body_translation: str


# --------------------------------------------------------------------------------------------------
# API view models
# --------------------------------------------------------------------------------------------------


class RefLink(_Model):
    type: str
    id: str


class TimelineEntry(_Model):
    id: str
    date: str
    time: str | None = None
    type: Literal[
        "document",
        "deadline",
        "payment",
        "appointment",
        "task",
        "expiry",
        "contract",
        "draft",
        "milestone",
        "reminder",
    ]
    title: str
    subtitle: str | None = None
    status: str | None = None
    priority: Priority = "normal"
    area: Area = "other"
    ref: RefLink
    party_name: str | None = None
    amount: float | None = None
    currency: str | None = None  # of the amount (None: euros)
    past: bool = False
    #: A payment's direction: money coming in ("in") is never due from the person, never overdue.
    direction: Literal["in", "out"] | None = None
    #: Why an open to-do is not one to act on (``ItemAside.reason``): a payment reminder replaced it, the bill
    #: attached to the e-mail repeats it, or its date had long passed when the letter was read.
    aside: Literal["replaced", "attached", "history"] | None = None


class AreaStatus(_Model):
    area: Area
    label: str
    status: Literal["ok", "attention", "urgent"] = "ok"
    headline: str
    next_date: str | None = None
    count: int = 0


class MoneySummary(_Model):
    due_this_month: float = 0.0  # euros
    fixed_costs_monthly: float = 0.0  # euros: contracts in other currencies are summed per currency below
    fixed_costs_monthly_other_currencies: dict[str, float] = Field(default_factory=dict)
    upcoming_payments: list[Item] = Field(default_factory=list)
    by_category: dict[str, float] = Field(default_factory=dict)  # euros


class DashboardStats(_Model):
    documents: int = 0
    open_items: int = 0
    contracts: int = 0
    parties: int = 0
    verified_ratio: float = 0.0


class Dashboard(_Model):
    today: str
    greeting_name: str
    simulated: bool = False
    attention: list[Item] = Field(default_factory=list)
    upcoming: list[Item] = Field(default_factory=list)
    decisions: list[Contract] = Field(default_factory=list)
    money: MoneySummary = Field(default_factory=MoneySummary)
    areas: list[AreaStatus] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    recent_documents: list[Document] = Field(default_factory=list)
    #: Letters waiting for the person's "Read these" (``held``, from the watched folder): not read, so
    #: in no other part of the page — Today says they wait instead of "nothing needs you".
    waiting: int = 0
    stats: DashboardStats = Field(default_factory=DashboardStats)


class PageInfo(_Model):
    page: int
    width: int
    height: int
    text_source: Literal["text", "transcript", "none"] = "none"


class Page(PageInfo):
    """A stored page (``pages`` table): render path, text layer or transcript, word boxes."""

    doc_id: str
    image_path: str
    text: str = ""
    words: list[tuple[str, float, float, float, float]] = Field(default_factory=list)  # text, x0..y1 (0..1)
    hidden: str = ""  # invisible text found on the page (never sent to a model)


class HelpLink(_Model):
    """Independent, free or low-cost help for a high-stakes letter (information, not legal advice)."""

    name: str
    what: str
    url: str | None = None


class AdviceFact(_Model):
    """One computed or legal point on a high-stakes letter's card (e.g. the rent cap check)."""

    title: str
    text: str
    tone: Literal["info", "warn", "good"] = "info"
    citation: str | None = None


class LetterAdvice(_Model):
    """The "get advice" card of a high-stakes letter, worked out on read (:mod:`ordnung.rules.advice`).

    ``urgent`` letters (court orders, a dismissal) always carry it; the others show it as information.
    """

    kind: HighStakesKind
    title: str
    summary: str
    urgent: bool = False
    steps: list[str] = Field(default_factory=list)
    facts: list[AdviceFact] = Field(default_factory=list)
    help: list[HelpLink] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    #: The letter the card offers to draft; ``None`` when none fits (no hardship objection to a notice
    #: without notice period; court orders get theirs from the verdict's main button).
    draft: DraftKind | None = None
    #: The person has dealt with the letter (:func:`ordnung.rules.advice.settles`, or ``closable`` and they said
    #: so): it has a to-do that carries
    #: its legal deadline (never a recurring one or a rent increase's new rent), and every such to-do is
    #: closed — an operating-cost statement that came in time has none, so it is never handled. The card is
    #: then no longer urgent, and the verdict says it is filed.
    handled: bool = False
    #: No to-do carries this letter's deadline (a landlord's notice without notice period, or with no
    #: objection to-do), so only the person can say they have dealt with it: the card offers "I've dealt
    #: with this", stored as the letter's tag ``dealt-with`` (ADR 0006: nothing is closed for them).
    closable: bool = False


# --------------------------------------------------------------------------------------------------
# GiroCode (worked out on read by ordnung.secretary.girocode_gate, never stored)
# --------------------------------------------------------------------------------------------------

#: Why a payment has no GiroCode. ``check_letter`` is the one the person can resolve in the app, by
#: comparing the details with the paper letter; the others are resolved on the letter, or not at all.
GiroCodeBlock = Literal[
    "incoming",
    "direct_debit",
    "settled",
    "replaced",
    "several",
    "scam",
    "currency",
    "no_amount",
    "no_iban",
    "invalid_iban",
    "no_payee",
    "invalid",
    "check_letter",
]
#: A transfer detail whose grounding the gate checks (the payee's name is checked by the payer's bank).
TransferField = Literal["amount", "iban", "reference"]


class TransferValues(_Model):
    """The transfer details a GiroCode carries — what the person compares with the paper letter."""

    payee: str | None = None
    iban: str | None = None
    reference: str | None = None
    amount: float | None = None


class GiroCodeReady(_Model):
    """A GiroCode for one payment: ``payload`` is the EPC069-12 text to show as a QR code at error
    correction level M. ``checked``: the person compared these details with the paper letter."""

    status: Literal["ready"] = "ready"
    item_id: str
    payload: str
    checked: bool = False


class GiroCodeBlocked(_Model):
    """Why a payment has no GiroCode, in plain words (``message``). For ``check_letter``, ``to_check``
    names the details to compare with the paper letter and ``values`` are the ones to confirm."""

    status: Literal["blocked"] = "blocked"
    item_id: str
    reason: GiroCodeBlock
    message: str
    to_check: list[TransferField] = Field(default_factory=list)
    values: TransferValues | None = None


GiroCode = Annotated[GiroCodeReady | GiroCodeBlocked, Field(discriminator="status")]


AttachmentOutcome = Literal["added", "known", "inline", "not_read", "refused", "over_limit"]


class EmailAttachment(_Model):
    """One attachment of an e-mail and what Ordnung did with it (:mod:`ordnung.ingest.attachments`).

    ``added``: it became a letter of its own (``doc_id``); ``known``: the same file was already in
    Ordnung (``doc_id``); ``inline``: a picture shown inside the e-mail (a logo), skipped; ``not_read``: a
    type Ordnung does not read from e-mails (a zip, a Word file …), listed only; ``refused``: intake
    refused it (``detail`` says why); ``over_limit``: past the most attachments read from one e-mail.
    ``doc_id`` is only set while that letter exists and is not in the trash.
    """

    filename: str
    outcome: AttachmentOutcome
    detail: str = ""
    doc_id: str | None = None
    #: That letter's status now (``held`` while it waits for the person); ``None`` without ``doc_id``.
    status: DocumentStatus | None = None


class ItemAside(_Model):
    """An open to-do that is not one to act on (worked out on read, never stored).

    ``replaced``: a payment reminder (``replaced_by``, a document id) took over the invoice payment —
    pay once, not twice. ``attached``: an e-mail's payment that the bill attached to it
    (``replaced_by``) asks for too. ``history``: its date had long passed when the letter was read (an
    archive letter). ``suspicious``: the letter shows signs of a scam.
    """

    item_id: str
    reason: Literal["replaced", "attached", "history", "suspicious"]
    replaced_by: str | None = None


class ListedItem(Item):
    """A to-do as the list (``GET /api/items``) returns it.

    ``aside`` is worked out on read (never stored): why the to-do is not one to act on — the same
    rules as Today, the letter's verdict and the party drawer (:class:`ItemAside`) — so the Inbox
    neither counts it nor shows it as a letter's next step; ``None`` for one to act on.
    """

    aside: ItemAside | None = None


class ProofLink(_Model):
    """A sent letter this document is proof of (``drafts.proof``): the letter and what the proof is."""

    draft_id: str
    subject: str
    proof_id: str
    kind: ProofKind


class DocumentDetail(_Model):
    document: Document
    advice: LetterAdvice | None = None
    pages: list[PageInfo] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    contracts: list[Contract] = Field(default_factory=list)
    party: Party | None = None
    case: Case | None = None
    related: list[Document] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    drafts: list[Draft] = Field(default_factory=list)
    #: The letter's open to-dos that are not one to act on (the same rules as Today and the party
    #: drawer): the verdict never leads with them ("362 days overdue", an invoice its reminder replaced).
    set_aside: list[ItemAside] = Field(default_factory=list)
    #: one per payment to-do of the letter (:mod:`ordnung.secretary.girocode_gate`)
    girocodes: list[GiroCode] = Field(default_factory=list)
    #: An e-mail's attachments and what became of each (empty for other letters).
    attachments: list[EmailAttachment] = Field(default_factory=list)
    #: More parts of that e-mail, past the most that are listed.
    attachments_more: int = 0
    #: The e-mail this letter came attached to (``None``: it did not, or that e-mail is gone).
    email: Document | None = None
    #: Whether its "Keep private" can be undone: it was kept private while it waited for the person,
    #: and nothing was read since (:func:`ordnung.ingest.held.was_kept_from_waiting`).
    can_wait_again: bool = False
    #: the sent letters this file is proof of (a proof file, or a letter also linked as proof)
    proof_of: list[ProofLink] = Field(default_factory=list)
    #: The letter's scam warning signs, as its Idea lists them (empty: none;
    #: :func:`ordnung.secretary.triggers.scam_signs`).
    scam_signs: list[str] = Field(default_factory=list)


class TrackingInfo(_Model):
    """A letter's tracking number as Ordnung read it (``drafts.proof.parse_tracking_number``)."""

    number: str
    #: grouped for reading, the groups joined by no-break spaces (never breaks inside the number)
    display: str
    #: ``online_stamp``: the 20 characters next to an online stamp's square code (Internetmarke);
    #: ``unknown``: a stored number the current policy no longer accepts (shown as typed)
    format: Literal["s10", "online_stamp", "domestic", "unknown"]
    #: The check digit was verified (UPU S10); the other formats have no check Ordnung knows.
    checked: bool
    note: str | None = None


class ProofEntry(_Model):
    """A proof with its file and, in code-written words, what it shows and what it does not."""

    proof: Proof
    document: Document | None = None
    label: str
    shows: str
    does_not_show: str


class ProofEvent(_Model):
    """One line of a sent letter's timeline (the "Nachweis"). ``date`` is ``None`` for a proof without a
    day (listed apart, with ``added_on``: the day it was added). ``possible_answer``: a letter that may be
    the answer — shown to the person, never written into the Nachweis."""

    date: str | None = None
    kind: Literal["created", "sent", "tracking", "proof", "delivered", "answered", "possible_answer"]
    label: str
    detail: str | None = None
    ref: RefLink | None = None
    added_on: str | None = None


WaitingSource = Literal["letter", "money", "call"]
WaitingStatus = Literal["waiting", "overdue", "answered", "closed"]


class WaitingEntry(_Model):
    """Something the person is owed — a reply, money or a callback (``secretary.waiting``), worked out on
    read. ``answered``: a letter linked to it arrived (``answered_by``); nothing is closed for the person,
    closing the follow-up to-do (``followup_item_id``) or marking the money received is their click."""

    id: str
    source: WaitingSource
    status: WaitingStatus
    title: str
    about: str
    note: str
    since: str | None = None
    expected_by: str | None = None
    party_id: str | None = None
    party_name: str | None = None
    amount: float | None = None
    currency: str | None = None
    area: Area = "other"
    ref: RefLink
    answered_by: RefLink | None = None
    answered_on: str | None = None
    followup_item_id: str | None = None
    #: the letter it comes from: the one a sent letter answers, or the one that promised the money
    doc_id: str | None = None
    #: the thread it belongs to (a sent letter's, a call's): a call noted about it goes there
    case_id: str | None = None


class ProofOverview(_Model):
    """``GET /api/drafts/{id}/proof``: a letter's tracking number, proofs, timeline, what is missing and
    what it waits for."""

    draft_id: str
    sent: bool
    channel: str | None = None
    tracking: TrackingInfo | None = None
    proofs: list[ProofEntry] = Field(default_factory=list)
    timeline: list[ProofEvent] = Field(default_factory=list)
    #: what would make the proof stronger, in the person's words (empty: nothing Ordnung knows of)
    missing: list[str] = Field(default_factory=list)
    #: proof days that contradict the day the letter is marked as sent (one of them is wrong)
    conflicts: list[str] = Field(default_factory=list)
    #: only in the answer to adding a proof: what to tell the person about a file that was already in
    #: Ordnung (made private now, or already read by AI); ``None``: it was stored privately
    notice: str | None = None
    waiting: WaitingEntry | None = None
    #: the fixed caveat: proof of sending never shows what was inside
    caveat: str = ""


class PartyDetail(_Model):
    party: Party
    documents: list[Document] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    contracts: list[Contract] = Field(default_factory=list)
    cases: list[Case] = Field(default_factory=list)
    #: open items of ``items`` the drawer lists apart as "older or replaced" (Today leaves them out)
    set_aside: list[ItemAside] = Field(default_factory=list)


class CaseDetail(_Model):
    case: Case
    party: Party | None = None
    documents: list[Document] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    drafts: list[Draft] = Field(default_factory=list)


class PurposeUsage(_Model):
    """Model use for one purpose (``extract``, ``ask`` …). ``input_tokens`` counts every prompt token, those
    read from or written to the prompt cache too."""

    calls: int = 0
    cache_hits: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class UsageStats(_Model):
    """Model use in total and per purpose; ``input_tokens`` counts every prompt token, cached ones too."""

    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    by_purpose: dict[str, PurposeUsage] = Field(default_factory=dict)
    recent: list[LLMCallRecord] = Field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# Traces: how a letter was read (ordnung.trace)
# --------------------------------------------------------------------------------------------------


class TraceSpanRecord(_Model):
    """One stored step of one reading of a letter (``trace_spans``).

    ``key`` names the step within its reading (``run/verify:quotes/verify:item:<slot>``) and is the
    same in every reading of the letter, so two readings can be compared step by step. ``attributes``
    hold only what code computed or decided and the ids of the records a step used or produced —
    never letter text (the written policy is :mod:`ordnung.trace.facts`).
    """

    id: str
    trace_id: str
    doc_id: str
    job_id: str | None = None
    parent_id: str | None = None
    key: str
    seq: int = 0
    kind: SpanKind
    name: str
    stage: str | None = None
    started_at: str
    ended_at: str
    status: SpanStatus = "ok"
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceRun(_Model):
    """One reading of a letter, summed up (its root span and its model calls)."""

    trace_id: str
    #: the letter's reading this was: 1 for the first, then 2, 3 … (older ones may no longer be kept)
    reading: int = 1
    job_id: str | None = None
    started_at: str
    ended_at: str
    duration_ms: float = 0.0
    status: SpanStatus = "ok"
    #: how it ended (``paused`` and ``stopped`` readings are read again later)
    ended: ReadingEnd = "done"
    #: why it did not run to the end, in words (``None`` when it was done)
    error: str | None = None
    trigger: Literal["read", "read_again"] = "read"
    #: ``measured`` by the computer's clock; ``recorded`` in the demo: laid out from the recorded
    #: model latencies, the steps of code shown without a duration
    timing: Literal["measured", "recorded"] = "measured"
    #: the letter's status the reading ended with (``None`` when it failed)
    result: DocumentStatus | None = None
    model_calls: int = 0
    cache_hits: int = 0
    repairs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: prompt tokens read from or written to the model's prompt cache (not in ``input_tokens``)
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    #: how long at least one call to Claude was under way (calls at the same time count once)
    model_ms: float = 0.0


class TraceSpan(_Model):
    """A step of a reading as the "How it was read" view shows it (display order, depth-first)."""

    id: str
    parent_id: str | None = None
    depth: int = 0
    key: str
    kind: SpanKind
    name: str
    stage: str | None = None
    #: milliseconds from the start of the reading
    start_ms: float = 0.0
    duration_ms: float = 0.0
    status: SpanStatus = "ok"
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    #: a model step's call from the usage log (tokens, cost, prompt, outcome)
    call: LLMCallRecord | None = None
    #: the record the step used or produced (a to-do, the sender, the thread, a contract)
    ref: RefLink | None = None
    #: that record's name now (``None`` when it no longer exists)
    label: str | None = None


class DocumentTrace(_Model):
    """How a letter was read: the reading shown (the latest unless another was asked for), its steps
    and every reading Ordnung keeps (newest first)."""

    doc_id: str
    run: TraceRun | None = None
    runs: list[TraceRun] = Field(default_factory=list)
    spans: list[TraceSpan] = Field(default_factory=list)


class TraceChange(_Model):
    """One thing two readings of a letter decided differently (a date, a quote's grounding, a
    model call's outcome …); ``before``/``after`` are ``None`` when the step is missing in that reading."""

    key: str
    kind: SpanKind
    name: str
    field: str
    before: Any = None
    after: Any = None
    ref: RefLink | None = None
    label: str | None = None


class TraceComparison(_Model):
    """What a later reading (``head``) decided differently from an earlier one (``base``)."""

    doc_id: str
    base: TraceRun
    head: TraceRun
    changes: list[TraceChange] = Field(default_factory=list)


class TraceExport(_Model):
    """Every kept reading of the letters not in the trash, as stored (for "Download your records")."""

    spans: list[TraceSpanRecord] = Field(default_factory=list)
    calls: list[LLMCallRecord] = Field(default_factory=list)


class ClaudeStatus(_Model):
    installed: bool = False
    version: str | None = None
    path: str | None = None
    ok: bool | None = None
    detail: str | None = None


CheckStatus = Literal["ok", "warn", "fail"]


class DoctorCheck(_Model):
    """One ``ordnung doctor`` check: what was looked at, the outcome and — when it is not ok — how to
    fix it."""

    id: str
    label: str
    status: CheckStatus
    detail: str = ""
    fix: str | None = None


class Health(_Model):
    version: str
    data_dir: str
    demo: bool = False
    simulated_today: str | None = None
    today: str
    backend: str
    claude: ClaudeStatus = Field(default_factory=ClaudeStatus)
    rules_last_checked: str = Field(
        description="The day the rules catalog was last checked against the law (“Based on the law as of …”)"
    )
    checks: list[DoctorCheck] = Field(
        default_factory=list, description="The doctor's checks — only with ``?probe=1`` (“Run check”)"
    )


class RuleInfo(_Model):
    id: str
    title: str
    citation: str
    summary: str
    url: str | None = None
    effective_from: str | None = None
    topic: str | None = Field(
        default=None, description="The group it is listed under (“Counting periods”, “Price increases” …)"
    )


class LaneBar(_Model):
    id: str
    label: str
    start: str
    end: str
    kind: Literal["contract", "notice_window", "validity", "period", "event"] = "period"
    status: Literal["ok", "attention", "urgent", "past"] = "ok"
    markers: list[TimelineMarker] = Field(default_factory=list)
    ref: RefLink | None = None
    #: the life area of what the bar stands for (the Contracts lane holds contracts of every area)
    area: Area | None = None
    #: no end date (an open-ended contract): ``end`` is only where the lanes stop drawing it
    open_end: bool = False


class TimelineMarker(_Model):
    date: str
    label: str
    kind: Literal[
        "deadline", "send_by", "cancel_by", "renewal", "expiry", "payment", "appointment", "other"
    ] = "other"
    #: the life area and the to-do or contract the date belongs to (to filter the lanes and open it)
    area: Area | None = None
    ref: RefLink | None = None


class Lane(_Model):
    id: str
    label: str
    area: Area = "other"
    bars: list[LaneBar] = Field(default_factory=list)
    markers: list[TimelineMarker] = Field(default_factory=list)


class SearchHit(_Model):
    doc_id: str
    title: str
    snippet: str
    score: float = 0.0


class TourState(_Model):
    active: bool = False
    step: int = 0
    completed: bool = False


class MailTrayItem(_Model):
    id: str
    filename: str
    sender: str
    subject: str
    kind_hint: str
    photo: bool = False
    opened: bool = False
    doc_id: str | None = None
    #: the day the letter arrived (ISO date), for the tray's postmark
    received_date: str | None = None


# --------------------------------------------------------------------------------------------------
# My numbers (``GET /api/numbers``, :mod:`ordnung.numbers`)
# --------------------------------------------------------------------------------------------------

NumberKind = Literal[
    "tax_id",
    "tax_number",
    "social_insurance",
    "health_insurance",
    "student",
    "broadcasting_fee",
    "vehicle",
    "passport",
    "residence_permit",
    "id_card",
    "customer",
    "contract",
    "policy",
    "member",
    "employee",
    "account",
    "mandate",
    "meter",
    "other",
    "case_file",
    "payment_reference",
    "invoice",
    "order",
    "tracking",
    "reference",
    "vat_id",
    "register",
    "creditor_id",
    "iban",
    "bic",
    "their_tax_number",
    "their_other",
]
#: ``about_you`` (issued to the person), ``document`` (an identity document's number), ``organisation``
#: (yours with one organisation), ``case`` (one matter) or ``theirs`` (the organisation's own).
NumberGroup = Literal["about_you", "document", "organisation", "case", "theirs"]
#: The check-digit test: ``ok``, ``fails`` or ``none`` (no public algorithm for this kind of number).
NumberCheck = Literal["ok", "fails", "none"]


class LetterRef(_Model):
    """A letter a number or case links to."""

    id: str
    title: str
    date: str | None = None
    kind: LetterKind | None = None


class MyNumber(_Model):
    """One number as Ordnung sorted it (:mod:`ordnung.numbers`): the value as printed, how to read and
    copy it, the check-digit test and the latest letter that shows it."""

    key: str
    kind: NumberKind
    group: NumberGroup
    name: str = Field(description="What it is, in plain English (“Tax ID (Steuer-ID)”)")
    label: str = Field(description="The label the letter prints next to it")
    value: str = Field(description="The value as printed")
    display: str = Field(description="The value grouped for reading")
    copy_value: str = Field(description="What “Copy” puts on the clipboard (forms want no spaces)")
    check: NumberCheck = "none"
    check_note: str | None = None
    party_id: str | None = None
    party_name: str | None = None
    letter: LetterRef | None = Field(default=None, description="The latest letter that shows it")
    letters: int = Field(default=1, description="How many letters show it")


class IdentityDocument(_Model):
    """A passport, residence permit or ID card: its number (when a letter shows it) and expiry."""

    key: str
    kind: Literal["passport", "residence_permit", "id_card", "identity_document"]
    name: str
    number: MyNumber | None = None
    valid_until: str | None = None
    status: Literal["ok", "renew_soon", "expired", "unknown"] = "unknown"
    note: str | None = Field(default=None, description="What to do about it (written by code)")
    item_id: str | None = Field(default=None, description="The expiry to-do")
    needs_check: bool = Field(
        default=False, description="The expiry date is not confirmed against the letter (compare it)"
    )
    letter: LetterRef | None = None


class CaseItemRef(_Model):
    """The next open to-do of a case."""

    id: str
    title: str
    kind: ItemKind
    due_date: str | None = None
    send_by: str | None = Field(default=None, description="None for a fee paid at an appointment")
    at_appointment: bool = Field(
        default=False, description="A fee paid in person at the appointment: on its day, never a transfer"
    )
    needs_check: bool = Field(
        default=False, description="Its date or amount is not confirmed against the letter (compare it)"
    )
    direction: Literal["out", "in"] | None = Field(
        default=None,
        description="A payment's direction: money coming in is expected on its day, never overdue",
    )


class OpenCase(_Model):
    """A matter with an open one-off to-do, and the references to quote when you call or write."""

    key: str
    case_id: str | None = None
    title: str
    party_id: str | None = None
    party_name: str | None = None
    references: list[MyNumber] = Field(default_factory=list)
    next_item: CaseItemRef | None = None
    open_items: int = 0
    letter: LetterRef | None = Field(default=None, description="The case's latest letter")


class CallSheet(_Model):
    """Everything to have at hand when you call or write to one organisation."""

    party_id: str
    name: str
    kind: PartyKind = "other"
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    numbers: list[MyNumber] = Field(default_factory=list, description="Your numbers its letters show")
    their_numbers: list[MyNumber] = Field(default_factory=list, description="Its own (registry, bank)")
    open_cases: list[OpenCase] = Field(default_factory=list)
    last_letter: LetterRef | None = None
    open_items: int = 0


class MyNumbers(_Model):
    """The *My numbers* page."""

    today: str
    about_you: list[MyNumber] = Field(default_factory=list)
    documents: list[IdentityDocument] = Field(default_factory=list)
    organisations: list[CallSheet] = Field(default_factory=list)
    open_cases: list[OpenCase] = Field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# The weekly session (``GET /api/week``, :mod:`ordnung.secretary.week`)
# --------------------------------------------------------------------------------------------------

WeekStepId = Literal["now", "new", "check", "pay", "post", "waiting", "decide", "file"]
#: What a row's day means (:mod:`ordnung.secretary.week`, "The day on a row"): ``act_today`` once a
#: send-by day has passed but the due date has not (the due date is then ``WeekEntry.due_date``),
#: ``at_appointment`` for a fee paid in person on the appointment's day.
WeekDateRole = Literal[
    "added",
    "due",
    "by",
    "on",
    "expires",
    "send_by",
    "transfer_by",
    "pay_by",
    "act_today",
    "at_appointment",
    "collected",
    "expected",
    "decide_by",
    "sent",
    "reply_by",
    "promised_by",
    "done",
]


class WeekEntry(_Model):
    """One row of a weekly-session step: a letter, a to-do, a contract decision or a letter you wrote."""

    key: str
    ref: RefLink
    title: str
    kind: str = Field(
        description="The item's, letter's or draft's kind, or “contract” (or “call”, a promise)"
    )
    date: str | None = None
    date_role: WeekDateRole | None = None
    due_date: str | None = Field(
        default=None,
        description="The due date, when the row's date is an earlier day to act (send by, act today)",
    )
    amount: float | None = None
    currency: str | None = None
    party_id: str | None = None
    party_name: str | None = None
    doc_id: str | None = None
    status: str | None = None
    note: str | None = Field(default=None, description="One line written by code")
    tone: Literal["neutral", "warn", "danger", "ok"] = "neutral"
    overdue: bool = Field(
        default=False, description="Counted in the session's overdue (never on Compare with the letter)"
    )
    item: Item | None = Field(default=None, description="The to-do itself (Pay and Confirm need it)")


class WeekStep(_Model):
    """One step of the weekly session."""

    id: WeekStepId
    title: str
    summary: str
    entries: list[WeekEntry] = Field(default_factory=list)
    more: int = Field(default=0, description="Rows left out to keep the step short")
    total: float | None = Field(default=None, description="Euros (the pay step)")
    total_other_currencies: dict[str, float] = Field(default_factory=dict)


class WeeklySession(_Model):
    """The guided weekly review: seven steps (and *Act now* first when something is overdue or due
    today), how it ends and whether Today should suggest it."""

    today: str
    since: str = Field(description="New since this day (the last session, else a week ago)")
    last_session: str | None = None
    due: bool = Field(description="Today shows its one gentle prompt")
    next_prompt: str | None = Field(
        default=None, description="The day Today suggests the session next (none while it is due)"
    )
    minutes: int = 10
    steps: list[WeekStep] = Field(default_factory=list)
    overdue: int = Field(
        default=0, description="Deadlines, payments and tasks past their due date: never “All clear”"
    )
    next_deadline: WeekEntry | None = Field(
        default=None, description="The earliest day to act from today on: “All clear until …”"
    )
    due_today: int = Field(
        default=0, description="How many days to act from today on are today (the ending counts them)"
    )


FolderState = Literal["off", "watching", "problem"]
FolderOutcome = Literal["added", "known", "refused"]


class FolderPickup(_Model):
    """A file the watched folder brought in (from the activity log, newest first).

    ``added``: it became a letter (``doc_id``, its ``status`` now); ``known``: the same file was already
    in Ordnung; ``refused``: intake refused it (``detail`` says why). ``doc_id`` and ``status`` are
    ``None`` once that letter is gone.
    """

    at: str
    filename: str
    outcome: FolderOutcome
    detail: str = ""
    doc_id: str | None = None
    status: DocumentStatus | None = None


class FolderStatus(_Model):
    """``GET /api/folder``: the watched folder, whether it is watched, and what it brought in."""

    folder: str | None = None
    state: FolderState = "off"
    #: Why the folder is not watched right now (missing, not readable …), for the person.
    problem: str | None = None
    auto_read: bool = False
    #: Whether letters can be read here at all (not in the demo that only replays): else files always wait.
    can_read: bool = True
    #: Letters waiting for the person's "Read these" (``held``), from the folder or attached to its e-mails.
    waiting: int = 0
    #: Ordnung's own inbox folder in the data directory, offered as a ready-made choice.
    suggested: str = ""
    recent: list[FolderPickup] = Field(default_factory=list)


LaneBar.model_rebuild()


# --------------------------------------------------------------------------------------------------
# Live events (``GET /api/events``): the JSON ``data`` of each SSE event, by event name
# --------------------------------------------------------------------------------------------------


class _Event(BaseModel):
    """The payload of one live event. Fields with a default may be left out by the publisher."""

    model_config = ConfigDict(extra="forbid")


JobStage = Literal["intake", "text", "transcribe", "extract", "verify", "compute", "link", "plan", "done"]
"""The reading pipeline's stages, in order (``ingest.pipeline.Stage``)."""


class JobProgressEvent(_Event):
    """``job.progress``: a reading job moved to another stage (or finished, failed or is waiting)."""

    job_id: str | None
    doc_id: str | None
    stage: JobStage
    progress: float
    status: Literal["queued", "running", "waiting", "done", "failed"]
    error: str | None = None
    waiting_reason: str | None = None


class DocumentProcessedEvent(_Event):
    """``document.processed``: a letter was read (``status`` is its new status)."""

    doc_id: str
    status: DocumentStatus


class DocumentUpdatedEvent(_Event):
    """``document.updated``: the person corrected a letter."""

    doc_id: str


class DocumentDeletedEvent(_Event):
    """``document.deleted``: a letter went to the trash (or was deleted for good)."""

    doc_id: str
    purged: bool


class ItemUpdatedEvent(_Event):
    """``item.updated``: to-dos changed (``item_id`` when it was one)."""

    item_id: str | None = None


class ContractUpdatedEvent(_Event):
    """``contract.updated``: the person corrected a contract."""

    contract_id: str


class SuggestionsUpdatedEvent(_Event):
    """``suggestions.updated``: Ideas changed (triggers, a review, an answer, the daily tick)."""

    reason: Literal["answered", "review", "tick"] | None = None
    suggestion_id: str | None = None
    created: int | None = None
    live: int | None = None
    new: int | None = None
    expired: int | None = None
    by_rule: dict[str, int] | None = None


class ReviewFailedEvent(_Event):
    """``review.failed``: the on-demand review could not run."""

    error: str


class BriefUpdatedEvent(_Event):
    """``brief.updated``: a new secretary's note was written."""

    date: str
    source: Literal["llm", "template"]


class DayChangedEvent(_Event):
    """``day.changed``: the app's today moved on (``previous`` is ``None`` on the first run)."""

    date: str
    previous: str | None = None


class LlmPausedEvent(_Event):
    """``llm.paused``: Claude's usage limit was reached; reading continues at ``until``."""

    until: str
    reason: str


class EmptyEvent(_Event):
    """An event without data (``llm.resumed``, ``profile.updated``)."""


class DraftCreatedEvent(_Event):
    """``draft.created``: a letter was drafted."""

    draft_id: str
    kind: DraftKind


class DraftSentEvent(_Event):
    """``draft.sent``: the person sent a letter; ``item_id`` is the follow-up to-do."""

    draft_id: str
    item_id: str


class FolderUpdatedEvent(_Event):
    """``folder.updated``: the watched folder started, stopped, hit a problem or brought in a file."""

    state: FolderState
    doc_id: str | None = None
    held: bool | None = None


class DemoMailEvent(_Event):
    """``demo.mail``: a letter of the demo's New-mail tray was opened."""

    id: str
    doc_id: str
    opened: bool


class ServerEvents(BaseModel):
    """Every live event of ``GET /api/events``: the SSE event name → the model of its JSON data.

    Publishing an event that is not listed here (or with other fields) is a bug; a test checks it.
    """

    model_config = ConfigDict(populate_by_name=True)

    job_progress: JobProgressEvent = Field(alias="job.progress")
    document_processed: DocumentProcessedEvent = Field(alias="document.processed")
    document_updated: DocumentUpdatedEvent = Field(alias="document.updated")
    document_deleted: DocumentDeletedEvent = Field(alias="document.deleted")
    item_updated: ItemUpdatedEvent = Field(alias="item.updated")
    contract_updated: ContractUpdatedEvent = Field(alias="contract.updated")
    suggestions_updated: SuggestionsUpdatedEvent = Field(alias="suggestions.updated")
    review_failed: ReviewFailedEvent = Field(alias="review.failed")
    brief_updated: BriefUpdatedEvent = Field(alias="brief.updated")
    day_changed: DayChangedEvent = Field(alias="day.changed")
    llm_paused: LlmPausedEvent = Field(alias="llm.paused")
    llm_resumed: EmptyEvent = Field(alias="llm.resumed")
    profile_updated: EmptyEvent = Field(alias="profile.updated")
    draft_created: DraftCreatedEvent = Field(alias="draft.created")
    draft_sent: DraftSentEvent = Field(alias="draft.sent")
    demo_mail: DemoMailEvent = Field(alias="demo.mail")
    folder_updated: FolderUpdatedEvent = Field(alias="folder.updated")


SERVER_EVENTS: dict[str, type[BaseModel]] = {
    str(info.alias): info.annotation  # type: ignore[misc]
    for info in ServerEvents.model_fields.values()
}
"""Live event name → payload model (derived from :class:`ServerEvents`)."""
