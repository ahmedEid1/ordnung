"""Typed views of the benchmark manifest and of one condition's answer for one letter.

The manifest (``evals/dataset/manifest.json``) is written by ``evals/generate.py``; its conventions
are documented in the manifest itself and in ``evals/dataset/VERIFICATION.md``. The models here read
it leniently (unknown keys are ignored) so the generator can add fields without breaking the runner.

A :class:`Prediction` is what one condition produced for one letter, normalised to the same shape for
every condition, plus the accounting of the model calls it took. Predictions are cached as JSON, so
they must round-trip through ``model_dump(mode="json")``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConditionName = Literal["ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"]
CONDITIONS: tuple[ConditionName, ...] = ("ordnung", "llm_only", "llm_rules_text", "llm_rules_tool")
CONDITION_LABELS: dict[str, str] = {
    "ordnung": "Ordnung (LLM reads, rules compute)",
    "llm_only": "LLM only",
    "llm_rules_text": "LLM + rule text",
    "llm_rules_tool": "LLM + rules tool (MCP)",
}
SHORT_LABELS: dict[str, str] = {
    "ordnung": "Ordnung",
    "llm_only": "LLM only",
    "llm_rules_text": "LLM + rules text",
    "llm_rules_tool": "LLM + rules tool",
}

#: The demo persona lives in Nordrhein-Westfalen (SPEC § 1.3). Letters whose letterhead names no Land
#: were verified to have the same labels under all 16 Land calendars, so this choice never changes a label.
PERSONA_REGION = "NW"
#: The persona reads German at B1 and prefers English (the language Ordnung writes titles in).
PERSONA_LANGUAGE = "en"

AMBIGUOUS = "ambiguous"


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------------------------------


class TruthSpec(_Lenient):
    """What the letter says about a date, as labelled by the generator (not ``ordnung.models.DateSpec``)."""

    type: Literal["fixed", "relative", "none"]
    anchor: str | None = None
    amount: int | None = None
    unit: str | None = None
    delivery_scope: str | None = None
    posted_on: str | None = None
    anchor_date: str | None = None
    date: str | None = None
    time: str | None = None
    shift: bool | None = None


class TruthItem(_Lenient):
    """One obligation the letter sets, with its legally correct date (or ``None`` / ``"ambiguous"``)."""

    kind: str
    nature: str = "other"
    title: str = ""
    expected_due: str | None = None
    expected_time: str | None = None
    spec: TruthSpec
    amount: float | None = None
    derivation: str = ""
    candidates: list[str] = Field(default_factory=list)
    region_sensitive: bool = False
    due_if_region_ignored: str | None = None

    @property
    def scored(self) -> bool:
        """Whether the item has one concrete expected date (it counts for due-date accuracy)."""
        return self.expected_date is not None

    @property
    def expected_date(self) -> date | None:
        """The expected due date, or ``None`` for undated and ambiguous items."""
        return parse_iso(self.expected_due)

    @property
    def ambiguous(self) -> bool:
        """The letter's date can honestly be read two ways; a confident date is not expected."""
        return self.expected_due == AMBIGUOUS


class TruthReference(_Lenient):
    label: str = ""
    value: str


class TruthContract(_Lenient):
    """Contract terms stated by a letter and the dates the law derives from them."""

    category: str = "other"
    regime: str | None = None
    expected_current_term_end: str | None = None
    expected_cancel_by: str | None = None
    derivation: str = ""


class Truth(_Lenient):
    kind: str
    kind_also_accepted: list[str] = Field(default_factory=list)
    language: str = "de"
    sender_name: str = ""
    document_date: str | None = None
    references: list[TruthReference] = Field(default_factory=list)
    amounts: list[float] = Field(default_factory=list)
    remedy_type: str = "none"
    items: list[TruthItem] = Field(default_factory=list)
    optional_items: list[TruthItem] = Field(default_factory=list)
    contract: TruthContract | None = None
    price_change: dict[str, Any] | None = None
    expected_warnings: list[str] = Field(default_factory=list)
    expect_low_confidence: bool = False


class Entry(_Lenient):
    """One benchmark document (a text PDF or a phone photo) and its truth."""

    id: str
    split: str
    family: str
    variant: str = ""
    file: str
    sha256: str
    media_type: str = "application/pdf"
    photo: bool = False
    source_id: str | None = None
    pages: int = 1
    language: str = "de"
    today: str
    authority_region: str | None = None
    recipient_region: str | None = None
    key_phrases: list[str] = Field(default_factory=list)
    hidden_phrases: list[str] = Field(default_factory=list)
    notes: str = ""
    truth: Truth

    def path(self, dataset_dir: Path) -> Path:
        """The document file inside ``dataset_dir``."""
        return dataset_dir / self.file

    @property
    def today_date(self) -> date:
        """The day the person reads the letter."""
        return date.fromisoformat(self.today)

    @property
    def region(self) -> str:
        """The holiday region every condition is told: the letterhead's Land, else the persona's."""
        return self.authority_region or self.recipient_region or PERSONA_REGION

    @property
    def modality(self) -> Literal["text", "photo"]:
        return "photo" if self.photo else "text"

    @property
    def cluster(self) -> str:
        """Bootstrap unit: a photo and the PDF it was rendered from are resampled together."""
        return self.source_id or self.id

    @property
    def adversarial(self) -> bool:
        return self.family == "adversarial"


def load_manifest(path: Path) -> list[Entry]:
    """All entries of a manifest, sorted by id."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return sorted((Entry.model_validate(entry) for entry in raw["entries"]), key=lambda e: e.id)


def select_entries(
    entries: Sequence[Entry],
    *,
    split: str | None = None,
    families: Iterable[str] | None = None,
    ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[Entry]:
    """Filter entries by split, family and id (in manifest order), then keep the first ``limit``."""
    wanted_families = set(families) if families else None
    wanted_ids = set(ids) if ids else None
    selected = [
        entry
        for entry in entries
        if (split is None or entry.split == split)
        and (wanted_families is None or entry.family in wanted_families)
        and (wanted_ids is None or entry.id in wanted_ids)
    ]
    if wanted_ids is not None:
        unknown = wanted_ids - {entry.id for entry in entries}
        if unknown:
            raise ValueError(f"unknown entry ids: {', '.join(sorted(unknown))}")
    return selected[:limit] if limit is not None else selected


def parse_iso(value: str | None) -> date | None:
    """An ISO ``YYYY-MM-DD`` date (a longer ISO string is cut to its date); ``None`` if not a date."""
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def iso_or_none(value: str | None) -> str | None:
    """``value`` normalised to ``YYYY-MM-DD``, or ``None``."""
    parsed = parse_iso(value)
    return parsed.isoformat() if parsed else None


# --------------------------------------------------------------------------------------------------
# Predictions
# --------------------------------------------------------------------------------------------------

Confidence = Literal["high", "medium", "low"]


class CallRecord(BaseModel):
    """Accounting for one model call (never the prompt or the answer)."""

    purpose: str
    backend: str = ""
    ok: bool = True
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    wall_ms: int = 0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens

    @property
    def latency_ms(self) -> int:
        """The model's own duration as recorded (stable under replay), else the measured wall time."""
        return self.duration_ms or self.wall_ms


class PredictedItem(BaseModel):
    """One obligation as a condition reported it."""

    kind: str
    title: str = ""
    due_date: str | None = None
    time: str | None = None
    amount: float | None = None
    quote: str = ""
    confidence: Confidence | None = None
    # Ordnung only: what the model read and how the rules engine and the verifier judged it.
    spec: dict[str, Any] | None = None
    grounding: str | None = None
    value_consistent: bool | None = None
    needs_check: bool = False
    rule_ids: list[str] = Field(default_factory=list)
    explanation: str = ""  # Ordnung: the receipt's summary; baselines: the model's own computation
    notes: list[str] = Field(default_factory=list)  # Ordnung: the receipt's warnings
    #: ``code``: the to-do Ordnung files itself for an incomplete reading (``ingest/gaps.py``), not one the
    #: model read — its date is scored (a wrong one has cause "check"), but it counts for none of the reading's
    #: extraction and grounding metrics, which match the reading's own to-dos alone.
    origin: Literal["model", "code"] = "model"

    @property
    def dated(self) -> bool:
        """Whether the item carries (or was meant to carry) a date."""
        if self.due_date is not None:
            return True
        return self.spec is not None and self.spec.get("type") not in (None, "none")

    @property
    def flagged(self) -> bool:
        """Whether the person is told to double-check this date (low confidence or "Please check")."""
        return self.confidence == "low" or self.needs_check


class ToolUse(BaseModel):
    """One tool call a condition's model made (``llm_rules_tool``), as the scorer needs it.

    ``ok`` is false when the tool refused the arguments (its answer was not a JSON object);
    ``due_date`` is what ``compute_deadline`` returned and ``date`` what ``add_working_days``
    returned (``None`` for no date or other tools).
    """

    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    due_date: str | None = None
    date: str | None = None
    error: str | None = None


class PredictedContract(BaseModel):
    current_term_end: str | None = None
    cancel_by: str | None = None


class Prediction(BaseModel):
    """What one condition produced for one letter, normalised across conditions."""

    entry_id: str
    condition: str
    model: str
    kind: str | None = None
    sender_name: str | None = None
    sender_kind: str | None = None
    delivery_scope: str | None = None  # Ordnung: derived by code from the sender's kind
    document_date: str | None = None
    references: list[str] = Field(default_factory=list)
    amounts: list[float] = Field(default_factory=list)
    remedy_type: str | None = None
    items: list[PredictedItem] = Field(default_factory=list)
    contract: PredictedContract | None = None
    warnings: list[str] = Field(default_factory=list)
    #: Findings made by code, not by the model: ``hidden_text``, ``injection_phrases``, ``invalid_iban``.
    signals: list[str] = Field(default_factory=list)
    #: Whether invisible text was detected; ``None`` when the condition cannot observe it.
    hidden_text: bool | None = None
    #: The model's tool calls in order; ``None`` for conditions without tools (``[]``: had tools, used none).
    tools: list[ToolUse] | None = None
    calls: list[CallRecord] = Field(default_factory=list)
    #: The system gave no usable answer (e.g. invalid output after the repair attempt) — scored as empty.
    failed: str | None = None
    #: An infrastructure problem (replay miss, CLI error, timeout) — the run is incomplete.
    error: str | None = None
    fingerprint: str = ""

    @property
    def cost_usd(self) -> float:
        return sum(call.cost_usd for call in self.calls)

    @property
    def latency_ms(self) -> int:
        return sum(call.latency_ms for call in self.calls)

    @property
    def tokens(self) -> int:
        return sum(call.tokens for call in self.calls)
