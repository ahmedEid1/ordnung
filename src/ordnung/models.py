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
#: Letters whose deadlines the rules engine handles specially. Only code assigns these kinds, from
#: the model's reading (:mod:`ordnung.rules.routing`), so the extraction schema and the benchmark keep
#: the model's own vocabulary (:data:`DocumentKind`) and its recorded answers stay valid.
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

DocumentStatus = Literal["queued", "processing", "processed", "needs_review", "failed"]
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
    "as_written",
]
RemedyType = Literal["einspruch", "widerspruch", "klage", "none", "unclear"]
DateNature = Literal["objection", "payment", "declaration", "notice", "appointment", "other"]


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


class Recurrence(_Model):
    interval: int = 1
    unit: Literal["days", "weeks", "months", "years"] = "months"


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
    """The rule-relevant part of a contract (input of ``rules.contracts.compute_contract``)."""

    category: ContractCategory = "other"
    party_kind: str | None = None
    concluded_date: str | None = None
    start_date: str | None = None
    initial_term_months: int | None = None
    renewal_term_months: int | None = None
    notice_value: int | None = None
    notice_unit: NoticeUnit | None = None
    notice_basis: NoticeBasis | None = None
    end_date: str | None = None
    is_consumer: bool = True
    is_basic_supply: bool = False
    status: Literal["active", "cancelled", "ended"] = "active"


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


class AppSettings(_Model):
    models: ModelSettings = Field(default_factory=ModelSettings)
    concurrency: int = 2
    inbox_dir: str | None = None
    ocr: bool = True
    llm_brief: bool = True
    llm_review: bool = True
    demo: bool = False
    simulated_today: str | None = None


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
    recurrence: Recurrence | None = None
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


class ItemAside(_Model):
    """An open to-do that is not one to act on (worked out on read, never stored).

    ``replaced``: a payment reminder (``replaced_by``, a document id) took over the invoice payment —
    pay once, not twice. ``history``: its date had long passed when the letter was read (an archive
    letter). ``suspicious``: the letter shows signs of a scam.
    """

    item_id: str
    reason: Literal["replaced", "history", "suspicious"]
    replaced_by: str | None = None


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
    """Model use for one purpose (``extract``, ``ask`` …)."""

    calls: int = 0
    cache_hits: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class UsageStats(_Model):
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    by_purpose: dict[str, PurposeUsage] = Field(default_factory=dict)
    recent: list[LLMCallRecord] = Field(default_factory=list)


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


SERVER_EVENTS: dict[str, type[BaseModel]] = {
    str(info.alias): info.annotation  # type: ignore[misc]
    for info in ServerEvents.model_fields.values()
}
"""Live event name → payload model (derived from :class:`ServerEvents`)."""
