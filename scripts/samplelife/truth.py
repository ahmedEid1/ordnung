"""Ground truth for each sample document, as written to ``manifest.json``.

The enums are the ones of :mod:`ordnung.models` so that mypy checks the labels. Expected dates are
*literals* in the document modules, derived by hand (the arithmetic is spelled out in comments and in
``reasoning``) and double-checked with :mod:`samplelife.datecheck` — never with ``ordnung.rules``.

Warning vocabulary for ``expected_warnings``: ``scam`` (payment demand is fraudulent),
``hidden_text`` (invisible text on the page), ``prompt_injection`` (text addressed to an AI),
``foreign_iban`` (payee account abroad although the sender claims to be a German body).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ordnung.models import (
    Area,
    ContractCategory,
    ContractRegime,
    CostInterval,
    DateNature,
    DocumentKind,
    ItemKind,
    NoticeBasis,
    NoticeUnit,
    PartyKind,
    RemedyType,
)

DateBasis = Literal["fixed", "relative", "none"]
Recurrence = Literal["monthly", "yearly"]
ChangeType = Literal[
    "price_increase",
    "price_decrease",
    "terms_change",
    "cancellation_confirmation",
    "termination_by_provider",
    "other",
]
Warning = Literal["scam", "hidden_text", "prompt_injection", "foreign_iban"]


@dataclass(frozen=True)
class Ref:
    """An identifier as printed (label + value)."""

    label: str
    value: str


@dataclass(frozen=True)
class Amount:
    """A money amount stated in the document."""

    label: str
    value: float
    currency: str = "EUR"


@dataclass(frozen=True)
class TruthItem:
    """One to-do or date the document creates, with the expected computed due date."""

    kind: ItemKind
    title_hint: str
    expected_due: str | None
    date_basis: DateBasis
    nature: DateNature
    reasoning: str
    quote: str
    expected_time: str | None = None
    amount: float | None = None
    direction: Literal["out", "in"] | None = None
    recurrence: Recurrence | None = None
    location: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class TruthContract:
    """Contract terms as written plus the expected state on the simulated today."""

    name: str
    category: ContractCategory
    regime: ContractRegime
    customer_number: str | None
    concluded_date: str | None
    start_date: str | None
    initial_term_months: int | None
    renewal_term_months: int | None
    notice_value: int | None
    notice_unit: NoticeUnit | None
    notice_basis: NoticeBasis | None
    end_date: str | None
    cost_amount: float | None
    cost_interval: CostInterval | None
    expected_current_term_end: str | None
    expected_cancel_by: str | None
    expected_earliest_exit: str | None
    reasoning: str
    is_consumer: bool = True
    is_basic_supply: bool = False


@dataclass(frozen=True)
class TruthChange:
    """A price or terms change announced by the document."""

    type: ChangeType
    effective_date: str | None
    old_amount: float | None
    new_amount: float | None
    cost_interval: CostInterval | None
    unit_price_old: str | None = None
    unit_price_new: str | None = None


@dataclass(frozen=True)
class TruthRemedy:
    """The legal remedy named in the Rechtsbehelfsbelehrung."""

    type: RemedyType
    addressee: str | None


@dataclass(frozen=True)
class TruthPayment:
    """Payee details printed on the document."""

    iban: str
    payee: str
    reference: str | None


@dataclass(frozen=True)
class Truth:
    """Everything a perfect extraction of the document would contain."""

    kind: DocumentKind
    area: Area
    sender_name: str
    sender_kind: PartyKind
    document_date: str | None
    references: list[Ref]
    amounts: list[Amount]
    items: list[TruthItem]
    key_quotes: list[str]
    contract: TruthContract | None = None
    change: TruthChange | None = None
    remedy: TruthRemedy | None = None
    payment: TruthPayment | None = None
    expected_warnings: list[Warning] = field(default_factory=list)
    tax_relevant: bool = False
    kind_alternatives: list[DocumentKind] = field(default_factory=list)
    related: list[tuple[str, str]] = field(default_factory=list)
    notes: str = ""

    def to_json(self, order_of: Callable[[str], int]) -> dict[str, Any]:
        """Serialise; ``related`` slugs become ``{order, relation}`` records."""
        data = asdict(self)
        data["related"] = [{"order": order_of(slug), "relation": relation} for slug, relation in self.related]
        return data


@dataclass(frozen=True)
class Rendered:
    """The files of one document (JPEG photos keep their source PDF for tests and debugging)."""

    files: list[bytes]
    extension: Literal["pdf", "jpg"]
    pages: int
    source_pdf: bytes | None = None


@dataclass(frozen=True)
class Sample:
    """A document of the sample life: metadata, a renderer and its ground truth."""

    slug: str
    title: str
    language: Literal["de", "en"]
    received_date: str
    render: Callable[[], Rendered]
    truth: Truth
    photo: bool = False
    tray: bool = False
    captured_date: str | None = None
    sort_date: str | None = None
    subject_hint: str = ""
