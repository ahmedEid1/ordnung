"""Weekly LLM review: a compact ledger snapshot → at most six new Ideas (SPEC §9, §21).

The model only sees a JSON snapshot (profile basics, open items of the next 120 days, contracts with
their rule-computed dates, recent letters' summaries and warnings, existing Idea titles) wrapped in
``<untrusted_document>``. Its answer is validated by code before anything is stored:

* only the kinds ``saving``, ``hygiene``, ``followup`` and ``opportunity`` (legal rights and dates
  come from deterministic triggers only);
* every ref must name a record of the snapshot that still exists (at least one ref per Idea);
* near-duplicates of existing Ideas — including dismissed ones — are dropped (rapidfuzz ≥ 85);
* free text is checked: sentences with a date, amount or § citation that is not in the snapshot (or
  the rules catalog) are removed; a title with one drops the whole Idea.

The free-text check (:class:`Facts`, :func:`strip_unsupported`) is shared with the daily brief.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError
from rapidfuzz import fuzz

from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.ids import content_id
from ordnung.ingest.verify import parse_amounts, parse_dates
from ordnung.llm.base import LLMRequest
from ordnung.llm.prompts import render
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import review_schema
from ordnung.models import (
    AppSettings,
    Contract,
    Document,
    Item,
    Priority,
    ReviewOutput,
    ReviewSuggestion,
    Suggestion,
    SuggestionAction,
    SuggestionRef,
)
from ordnung.rules import list_rules
from ordnung.secretary.triggers import Ledger, action_day, is_overdue, parse_day

log = logging.getLogger(__name__)

MAX_IDEAS = 6
HORIZON_DAYS = 120
RECENT_DOCUMENT_DAYS = 180
MAX_ITEMS = 60
MAX_DOCUMENTS = 25
DUPLICATE_SCORE = 85.0
LAST_REVIEW_KEY = "last_review_at"
ALLOWED_KINDS = frozenset({"saving", "hygiene", "followup", "opportunity"})
_LABEL_MAX = 40
_DEFAULT_LABELS = {
    "document": "Open the letter",
    "contract": "Open the contract",
    "item": "Open the to-do",
    "party": "Open",
    "case": "Open the thread",
    "draft": "Open the letter",
}
_DRAFTABLE = frozenset({"cancellation", "general_reply"})
_LANGUAGES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ru": "Russian",
    "ar": "Arabic",
    "fa": "Persian",
    "hi": "Hindi",
    "zh": "Chinese",
}


# --------------------------------------------------------------------------------------------------
# prompt-safe JSON and hashing
# --------------------------------------------------------------------------------------------------


def canonical_json(data: Any) -> str:
    """Stable JSON (sorted keys, no whitespace) for hashing."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_hash(data: Any) -> str:
    """SHA-256 hex digest of :func:`canonical_json`."""
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def untrusted_json(data: Any) -> str:
    """Pretty JSON that is safe to embed inside ``<untrusted_document>`` in a prompt template.

    ``<``/``>`` are escaped so document text can never close the tag, and ``{{`` so it can never
    look like a template placeholder (both escapes are valid JSON string escapes).
    """
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1, default=str)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("{{", "{\\u007b")


def language_name(code: str) -> str:
    """``en`` → ``English`` (unknown codes are returned as given)."""
    return _LANGUAGES.get(code.split("-")[0].lower(), code)


# --------------------------------------------------------------------------------------------------
# free-text check: dates, amounts and § citations must come from the source data
# --------------------------------------------------------------------------------------------------

_PARAGRAPH_RE = re.compile(
    r"§§?\s*(?P<num>\d+[a-z]?)"
    r"(?:\s*(?:Abs\.|Absatz|S\.|Satz|Nr\.|Nummer|Alt\.)\s*\d+[a-z]?)*"
    r"(?:\s+(?P<law>[A-ZÄÖÜ][A-Za-zÄÖÜäöü]*[A-Z](?:\s+[IVX]{1,4}\b)?))?"
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_NO_BREAK_BEFORE = re.compile(
    r"(?:\b\d{1,2}|\bAbs|\bNr|\bS|\bSatz|\bca|\bz\.B|\be\.g|\bi\.e|\bvs|\bDr|\bSt)[.]$"
)


def _paragraphs(text: str) -> Iterator[tuple[str, str | None]]:
    for match in _PARAGRAPH_RE.finditer(text):
        law = match.group("law")
        yield match.group("num").lower(), " ".join(law.split()) if law else None


def _strings_and_numbers(data: Any) -> Iterator[str | float]:
    if isinstance(data, str):
        yield data
    elif isinstance(data, bool) or data is None:
        return
    elif isinstance(data, int | float):
        yield float(data)
    elif isinstance(data, dict):
        for value in data.values():
            yield from _strings_and_numbers(value)
    elif isinstance(data, list | tuple):
        for value in data:
            yield from _strings_and_numbers(value)


def _cents(value: float) -> int:
    return round(value * 100)


@dataclass(frozen=True)
class Facts:
    """The dates, amounts and § citations a free text may mention."""

    dates: frozenset[date]
    day_months: frozenset[tuple[int, int]]
    cents: frozenset[int]
    paragraphs: frozenset[tuple[str, str | None]]

    @classmethod
    def from_data(cls, data: Any, *, extra_texts: Iterable[str] = ()) -> Facts:
        """Collect facts from every string (parsed) and number (as an amount) in ``data``."""
        dates: set[date] = set()
        day_months: set[tuple[int, int]] = set()
        cents: set[int] = set()
        paragraphs: set[tuple[str, str | None]] = set()
        for value in [*_strings_and_numbers(data), *extra_texts]:
            if isinstance(value, float):
                cents.add(_cents(value))
                continue
            for mention in parse_dates(value):
                day_months.add((mention.day, mention.month))
                if (full := mention.as_date()) is not None:
                    dates.add(full)
            cents.update(_cents(amount) for amount in parse_amounts(value))
            paragraphs.update(_paragraphs(value))
        return cls(frozenset(dates), frozenset(day_months), frozenset(cents), frozenset(paragraphs))

    def supports_date(self, value: date) -> bool:
        """Whether ``value`` appears in the source data."""
        return value in self.dates

    def supports_amount(self, value: float) -> bool:
        """Whether ``value`` (to the cent) appears in the source data."""
        return _cents(value) in self.cents

    def unsupported(self, text: str) -> list[str]:
        """Dates, amounts and § citations in ``text`` that the source data does not contain."""
        problems: list[str] = []
        readings: dict[str, bool] = {}
        for mention in parse_dates(text):
            full = mention.as_date()
            ok = full in self.dates if full is not None else (mention.day, mention.month) in self.day_months
            readings[mention.text] = readings.get(mention.text, False) or ok
        problems.extend(raw for raw, ok in readings.items() if not ok)
        problems.extend(f"{amount:.2f}" for amount in parse_amounts(text) if not self.supports_amount(amount))
        numbers = {number for number, _ in self.paragraphs}
        for number, law in _paragraphs(text):
            if (number, law) not in self.paragraphs and (law is not None or number not in numbers):
                problems.append(f"§ {number} {law or ''}".strip())
        return problems


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking ``15. Oktober`` or ``§ 81 Abs. 4``."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        head = text[start : match.start()]
        if _NO_BREAK_BEFORE.search(head):
            continue
        sentences.append(head.strip())
        start = match.end()
    sentences.append(text[start:].strip())
    return [sentence for sentence in sentences if sentence]


#: Weekday names by weekday (Monday first), in the forms a note may use: English full and short,
#: German full and short.
_WEEKDAY_NAMES = (
    ("Monday", "Mon", "Montag", "Mo"),
    ("Tuesday", "Tue", "Dienstag", "Di"),
    ("Wednesday", "Wed", "Mittwoch", "Mi"),
    ("Thursday", "Thu", "Donnerstag", "Do"),
    ("Friday", "Fri", "Freitag", "Fr"),
    ("Saturday", "Sat", "Samstag", "Sa"),
    ("Sunday", "Sun", "Sonntag", "So"),
)
_WEEKDAY_FORM = {name: form for names in _WEEKDAY_NAMES for form, name in enumerate(names)}
_WEEKDAY_BEFORE = re.compile(
    r"\b(" + "|".join(sorted(_WEEKDAY_FORM, key=len, reverse=True)) + r")(\.?,?[ \t]+)(?=\d)"
)


def _nearest_year(day: int, month: int, today: date) -> date | None:
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    return min(candidates, key=lambda value: abs((value - today).days), default=None)


def correct_weekdays(text: str, today: date) -> str:
    """``text`` with every weekday name written just before a date set to that date's real weekday.

    A model adds weekday names itself and sometimes names the wrong day ("Thu 2 Oct 2026" for a
    Friday); code knows the calendar. A date without a year is read in the year closest to ``today``.
    """

    def fix(match: re.Match[str]) -> str:
        tail = text[match.end() : match.end() + 40]
        mentions = parse_dates(tail)
        if not mentions or not tail.startswith(mentions[0].text):
            return match.group(0)
        mention = mentions[0]
        day = mention.as_date() or _nearest_year(mention.day, mention.month, today)
        if day is None:
            return match.group(0)
        return _WEEKDAY_NAMES[day.weekday()][_WEEKDAY_FORM[match.group(1)]] + match.group(2)

    return _WEEKDAY_BEFORE.sub(fix, text)


def strip_unsupported(text: str, facts: Facts) -> str:
    """``text`` without the sentences that mention an unsupported date, amount or § citation."""
    kept = [sentence for sentence in split_sentences(text) if not facts.unsupported(sentence)]
    return " ".join(kept)


# --------------------------------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """What the review model sees, plus what the validator needs."""

    data: dict[str, Any]
    refs: frozenset[tuple[str, str]]
    doc_ids: list[str]
    existing_titles: list[str]

    @property
    def cache_key(self) -> str:
        """Canonical stable input of the review call: the hash of the snapshot."""
        return "review:" + stable_hash(self.data)


def _item_row(ledger: Ledger, item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "due_date": item.due_date,
        "send_by": item.send_by,
        "overdue": is_overdue(item, ledger.today),
        "amount": item.amount,
        "currency": item.currency,
        "area": item.area,
        "party_id": item.party_id,
        "contract_id": item.contract_id,
        "doc_id": item.doc_id,
    }


def _contract_row(ledger: Ledger, contract: Contract) -> dict[str, Any]:
    comp = ledger.computation(contract)
    monthly = contract.monthly_cost()
    return {
        "id": contract.id,
        "name": contract.name,
        "category": contract.category,
        "party_id": contract.party_id,
        "start_date": contract.start_date,
        "cost_amount": contract.cost_amount,
        "cost_interval": contract.cost_interval,
        "monthly_cost": monthly,
        "yearly_cost": round(monthly * 12, 2) if monthly is not None else None,
        "current_term_end": comp.current_term_end,
        "cancel_by": comp.cancel_by,
        "send_by": comp.send_by,
        "next_renewal": comp.next_renewal,
        "earliest_exit": comp.earliest_exit,
        "rules_summary": comp.summary,
    }


def _document_row(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "kind": doc.kind,
        "title": doc.title or doc.filename,
        "date": doc.doc_date or doc.received_date,
        "party_id": doc.party_id,
        "area": doc.area,
        "summary": doc.summary,
        "warnings": list(doc.warnings),
        "tax_relevant": doc.tax_relevant,
    }


def _recent_documents(ledger: Ledger, private: set[str]) -> list[Document]:
    since = (ledger.today - timedelta(days=RECENT_DOCUMENT_DAYS)).isoformat()
    docs = [
        doc
        for doc in ledger.documents.values()
        if doc.id not in private and (doc.doc_date or doc.received_date or since) >= since
    ]
    docs.sort(key=lambda doc: (doc.doc_date or doc.received_date or "", doc.id), reverse=True)
    return docs[:MAX_DOCUMENTS]


def build_snapshot(store: Store, today: date) -> Snapshot:
    """The compact, canonical ledger snapshot for the review (no ``ai_private`` letters, no wall-clock
    data; every list sorted by stable keys so the same ledger always gives the same cache key)."""
    ledger = Ledger(store, today)
    private = {doc.id for doc in ledger.documents.values() if doc.ai_private}
    horizon = today + timedelta(days=HORIZON_DAYS)
    items = [
        item
        for item in ledger.active_items()
        if item.doc_id not in private and (parse_day(item.due_date) or today) <= horizon
    ]
    items.sort(key=lambda item: ((action_day(item) or date.max).isoformat(), item.id))
    contracts = sorted(
        (c for c in ledger.active_contracts() if c.source_doc_id not in private),
        key=lambda c: (c.name.casefold(), c.id),
    )
    documents = _recent_documents(ledger, private)
    linked = (
        [row.party_id for row in items] + [c.party_id for c in contracts] + [d.party_id for d in documents]
    )
    party_ids = sorted({pid for pid in linked if pid is not None and pid in ledger.parties})
    ideas = store.list_suggestions()
    open_titles = sorted({idea.title for idea in ideas if idea.status in ("new", "snoozed", "accepted")})
    dismissed_titles = sorted({idea.title for idea in ideas if idea.status in ("dismissed", "done")})
    item_rows = [_item_row(ledger, item) for item in items[:MAX_ITEMS]]
    contract_rows = [_contract_row(ledger, contract) for contract in contracts]
    document_rows = [_document_row(doc) for doc in documents]
    party_rows = [
        {"id": pid, "name": ledger.parties[pid].name, "kind": ledger.parties[pid].kind} for pid in party_ids
    ]
    profile = ledger.profile
    data: dict[str, Any] = {
        "today": today.isoformat(),
        "profile": {
            "language": profile.language,
            "country": profile.country,
            "region": profile.region,
            "is_student_visa": profile.is_student_visa,
        },
        "open_items": item_rows,
        "contracts": contract_rows,
        "recent_documents": document_rows,
        "parties": party_rows,
        "existing_ideas": {"open": open_titles, "dismissed": dismissed_titles},
    }
    refs = frozenset(
        [("item", str(row["id"])) for row in item_rows]
        + [("contract", str(row["id"])) for row in contract_rows]
        + [("document", str(row["id"])) for row in document_rows]
        + [("party", str(row["id"])) for row in party_rows]
    )
    return Snapshot(
        data=data,
        refs=refs,
        doc_ids=sorted(doc.id for doc in documents),
        existing_titles=[idea.title for idea in ideas],
    )


# --------------------------------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------------------------------


def _ref_exists(store: Store, ref: SuggestionRef) -> bool:
    getters = {
        "document": store.get_document,
        "item": store.get_item,
        "contract": store.get_contract,
        "party": store.get_party,
        "case": store.get_case,
        "draft": store.get_draft,
    }
    found = getters[ref.type](ref.id)
    return found is not None and getattr(found, "deleted_at", None) is None


def is_duplicate(title: str, others: Iterable[str]) -> bool:
    """Whether ``title`` is a near-duplicate (rapidfuzz token-sort ratio ≥ 85) of any of ``others``."""
    folded = title.casefold()
    return any(fuzz.token_sort_ratio(folded, other.casefold()) >= DUPLICATE_SCORE for other in others)


def _label(label: str | None, default: str, facts: Facts) -> str:
    text = (label or "").strip()
    if not text or len(text) > _LABEL_MAX or facts.unsupported(text):
        return default
    return text


def _checked_action(
    action: SuggestionAction | None, refs: list[SuggestionRef], facts: Facts
) -> SuggestionAction:
    """Keep a draft action only for a cancellation/general reply on a ref'd contract or letter;
    anything else (including "mark done") becomes "open" on a ref'd record."""
    by_key: dict[tuple[str, str], SuggestionRef] = {(ref.type, ref.id): ref for ref in refs}
    target = by_key.get((action.target_type or "", action.target_id or "")) if action else None
    if (
        action is not None
        and action.type == "draft"
        and action.draft_kind in _DRAFTABLE
        and target is not None
        and target.type in ("contract", "document")
    ):
        default = "Draft cancellation" if action.draft_kind == "cancellation" else "Draft a reply"
        return SuggestionAction(
            type="draft",
            draft_kind=action.draft_kind,
            target_type=target.type,
            target_id=target.id,
            label=_label(action.label, default, facts),
        )
    chosen = target or refs[0]
    default = _DEFAULT_LABELS[chosen.type]
    label = _label(action.label if action and action.type == "open" else None, default, facts)
    return SuggestionAction(type="open", target_type=chosen.type, target_id=chosen.id, label=label)


def review_fingerprint(title: str) -> str:
    """``review:<12 hex chars of the normalised title>``."""
    normalised = " ".join(title.casefold().split())
    return "review:" + hashlib.sha1(normalised.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


@dataclass(frozen=True)
class _Validator:
    store: Store
    snapshot: Snapshot
    facts: Facts
    today: date

    def refs(self, idea: ReviewSuggestion) -> list[SuggestionRef] | None:
        refs = list({(ref.type, ref.id): ref for ref in idea.refs}.values())
        if not refs or any((ref.type, ref.id) not in self.snapshot.refs for ref in refs):
            return None
        if not all(_ref_exists(self.store, ref) for ref in refs):
            return None
        return refs

    def due_date(self, value: str | None) -> str | None:
        day = parse_day(value)
        if day is None or day < self.today or not self.facts.supports_date(day):
            return None
        return day.isoformat()

    def savings(self, value: float | None) -> float | None:
        if value is None or value <= 0 or not self.facts.supports_amount(value):
            return None
        return round(value, 2)

    def check(self, idea: ReviewSuggestion, accepted: list[str]) -> Suggestion | None:
        title = " ".join(idea.title.split())
        if idea.kind not in ALLOWED_KINDS or not title or self.facts.unsupported(title):
            return None
        if is_duplicate(title, [*self.snapshot.existing_titles, *accepted]):
            return None
        refs = self.refs(idea)
        body = correct_weekdays(strip_unsupported(idea.body, self.facts), self.today)
        if refs is None or not body:
            return None
        rationale = correct_weekdays(strip_unsupported(idea.rationale, self.facts), self.today) or None
        priority: Priority = "high" if idea.priority == "critical" else idea.priority
        fp = review_fingerprint(title)
        now = now_iso()
        return Suggestion(
            id=content_id("sug", fp),
            kind=idea.kind,
            title=title,
            body=body,
            rationale=rationale,
            priority=priority,
            fingerprint=fp,
            refs=refs,
            action=_checked_action(idea.action, refs, self.facts),
            source="review",
            savings_estimate=self.savings(idea.savings_estimate),
            due_date=self.due_date(idea.due_date),
            created_at=now,
            updated_at=now,
        )


def catalog_texts() -> list[str]:
    """Citations of the rules catalog (the § references any free text may use)."""
    return [rule.citation for rule in list_rules()]


def validate_review(store: Store, snapshot: Snapshot, output: ReviewOutput, today: date) -> list[Suggestion]:
    """Turn the model's proposals into at most :data:`MAX_IDEAS` safe, grounded Ideas (not stored)."""
    validator = _Validator(
        store, snapshot, Facts.from_data(snapshot.data, extra_texts=catalog_texts()), today
    )
    accepted: list[Suggestion] = []
    for proposal in output.suggestions:
        idea = validator.check(proposal, [chosen.title for chosen in accepted])
        if idea is not None:
            accepted.append(idea)
        if len(accepted) == MAX_IDEAS:
            break
    return accepted


# --------------------------------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------------------------------


def review_request(snapshot: Snapshot, settings: AppSettings, language: str) -> LLMRequest:
    """The ``review`` model call for ``snapshot``."""
    system_version, system = render(
        "review_system", max_ideas=MAX_IDEAS, language_name=language_name(language)
    )
    version, prompt = render(
        "review", today=snapshot.data["today"], snapshot=untrusted_json(snapshot.data), max_ideas=MAX_IDEAS
    )
    return LLMRequest.model_validate(
        {
            "purpose": "review",
            "prompt": prompt,
            "system": system,
            "schema": review_schema(),
            "model": settings.models.review,
            "cache_key": snapshot.cache_key,
            "prompt_version": f"{system_version}+{version}",
            "doc_ids": snapshot.doc_ids,
        }
    )


def _parse_output(data: dict[str, Any] | None, text: str) -> ReviewOutput | None:
    try:
        if data is not None:
            return ReviewOutput.model_validate(data)
        return ReviewOutput.model_validate_json(text)
    except ValidationError:
        log.warning("review output did not match the schema; ignoring it")
        return None


async def run_review(
    store: Store, llm: LLMService, today: date, *, settings: AppSettings | None = None
) -> list[Suggestion]:
    """Run the weekly review and store its validated Ideas (``source="review"``).

    Returns the stored Ideas. Records the review day in meta ``last_review_at``. Model errors
    (:class:`~ordnung.llm.base.LLMError`) propagate to the caller; an empty ledger makes no call.
    """
    snapshot = build_snapshot(store, today)
    data = snapshot.data
    if not (data["open_items"] or data["contracts"] or data["recent_documents"]):
        store.set_meta(LAST_REVIEW_KEY, today.isoformat())
        return []
    chosen = settings or store.get_settings()
    response = await llm.complete(review_request(snapshot, chosen, store.get_profile().language))
    output = _parse_output(response.data, response.text)
    ideas = validate_review(store, snapshot, output, today) if output else []
    with store.tx():
        stored = [store.upsert_suggestion(idea) for idea in ideas]
        store.set_meta(LAST_REVIEW_KEY, today.isoformat())
    return stored
