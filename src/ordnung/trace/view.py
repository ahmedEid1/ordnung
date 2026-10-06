"""A letter's trace as the web app and ``ordnung trace`` show it.

* :func:`document_trace` — one reading (the newest kept unless another is asked for) with its steps
  in display order: each step's offset from the start of the reading and its duration, a model
  step joined with its usage-log row (tokens, cost, latency, prompt, outcome), and the record a step
  points to looked up now — a to-do (by id, or by the slot of the sentence it was read from), the
  sender, the thread, a contract, a key fact of the letter. A record that no longer exists keeps its
  reference and has no label: the trace says what happened then, the label what the record is now.
* :func:`run_summary` — a reading summed up from its root span, its model steps and their calls.
  "Waiting for Claude" is the time at least one model step was under way: the pages of a photo,
  read at the same time, count once.
* Key facts have no stable identity across readings (to-dos have their slot): a quote of a key fact
  is named after the letter's key fact only in the newest reading, whose facts the letter shows;
  in an older one it is "Key fact N".

Labels are the only text a view adds, and they come from the ledger at the moment the trace is
shown (a to-do's title, a sender's name); the stored spans never hold them (:mod:`ordnung.trace.facts`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, get_args

from ordnung.models import (
    DocumentStatus,
    DocumentTrace,
    Item,
    LLMCallRecord,
    ReadingEnd,
    RefLink,
    TraceRun,
    TraceSpan,
    TraceSpanRecord,
)
from ordnung.trace.runs import ending_message

if TYPE_CHECKING:
    from ordnung.db.store import Store

#: Every document status a reading can end in (a letter from the watched folder ends ``held``).
_RESULTS: frozenset[str] = frozenset(get_args(DocumentStatus))
#: What a quote that belongs to no to-do is called (its record is the letter itself).
QUOTE_TARGET_LABELS = {"contract": "Contract", "change": "The announced change", "remedy": "How to object"}


class TraceNotFound(LookupError):
    """The reading asked for is not (or no longer) kept for this letter."""


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ms(start: str, end: str) -> float:
    return round((_moment(end) - _moment(start)).total_seconds() * 1000, 3)


def result_status(value: object) -> DocumentStatus | None:
    """A reading's ``result`` attribute as a document status (``None`` when it is none)."""
    return value if isinstance(value, str) and value in _RESULTS else None  # type: ignore[return-value]


def busy_ms(steps: Sequence[TraceSpanRecord]) -> float:
    """How long at least one of ``steps`` was under way (the union of their intervals)."""
    total, reach = 0.0, None
    for start, end in sorted((_moment(step.started_at), _moment(step.ended_at)) for step in steps):
        if reach is None or start > reach:
            total += (end - start).total_seconds()
            reach = end
        elif end > reach:
            total += (end - reach).total_seconds()
            reach = end
    return round(total * 1000, 3)


def reading_end(root: TraceSpanRecord) -> ReadingEnd:
    """How a reading ended (its ``ended`` attribute; readings stored before it: from its status)."""
    ended = root.attributes.get("ended")
    if ended in ("done", "failed", "paused", "stopped"):
        return ended
    if root.status == "ok":
        return "done"
    return "failed" if root.attributes.get("result") == "failed" else "stopped"


def run_summary(
    root: TraceSpanRecord, calls: Sequence[LLMCallRecord], model_steps: Sequence[TraceSpanRecord] = ()
) -> TraceRun:
    """A reading summed up: when, how long, how it ended and what its model calls used."""
    attributes = root.attributes
    reading = attributes.get("reading")
    ended = reading_end(root)
    return TraceRun(
        trace_id=root.trace_id,
        reading=reading if isinstance(reading, int) and reading > 0 else 1,
        job_id=root.job_id,
        started_at=root.started_at,
        ended_at=root.ended_at,
        duration_ms=_ms(root.started_at, root.ended_at),
        status=root.status,
        ended=ended,
        error=None if ended == "done" else ending_message(root.error or ended),
        trigger="read_again" if attributes.get("trigger") == "read_again" else "read",
        timing="recorded" if attributes.get("timing") == "recorded" else "measured",
        result=result_status(attributes.get("result")),
        model_calls=len(calls),
        cache_hits=sum(call.cache_hit for call in calls),
        # the completeness re-ask names the call it follows too (``repair_of``) but repairs nothing
        repairs=sum(call.repair_of is not None and call.prompt_name != "reading_gaps" for call in calls),
        input_tokens=sum(call.input_tokens for call in calls),
        output_tokens=sum(call.output_tokens for call in calls),
        cache_read_tokens=sum(call.cache_read_tokens for call in calls),
        cache_creation_tokens=sum(call.cache_creation_tokens for call in calls),
        cost_usd=round(sum(call.cost_usd for call in calls), 6),
        model_ms=busy_ms(model_steps),
    )


class _Records:
    """The ledger records a letter's steps point to, looked up once per view."""

    def __init__(self, store: Store, doc_id: str, *, newest: bool = True) -> None:
        self.store = store
        self.doc_id = doc_id
        #: whether the reading shown is the newest kept (the one whose key facts the letter has)
        self.newest = newest
        self._by_slot: dict[str, Item] | None = None
        self._document = store.get_document(doc_id)

    def item_by_slot(self, slot: str) -> Item | None:
        if self._by_slot is None:
            self._by_slot = {
                item.slot_key: item for item in self.store.list_items(doc_id=self.doc_id) if item.slot_key
            }
        return self._by_slot.get(slot)

    def item(self, attributes: dict[str, Any]) -> tuple[RefLink, str | None] | None:
        item_id, slot = attributes.get("item_id"), attributes.get("slot_key")
        found = self.store.get_item(item_id) if isinstance(item_id, str) else None
        if found is None and isinstance(slot, str):
            found = self.item_by_slot(slot)
        if found is not None:
            return RefLink(type="item", id=found.id), found.title
        if isinstance(item_id, str):
            return RefLink(type="item", id=item_id), None
        return None

    def named(self, kind: str, record_id: object) -> tuple[RefLink, str | None] | None:
        if not isinstance(record_id, str):
            return None
        label: str | None = None
        if kind == "party":
            party = self.store.get_party(record_id)
            label = party.name if party else None
        elif kind == "case":
            case = self.store.get_case(record_id)
            label = case.title if case else None
        elif kind == "contract":
            contract = self.store.get_contract(record_id)
            label = contract.name if contract else None
        return RefLink(type=kind, id=record_id), label

    def quote_target(self, attributes: dict[str, Any]) -> tuple[RefLink, str | None] | None:
        target, index = attributes.get("target"), attributes.get("index")
        if target == "item":
            return self.item(attributes)
        ref = RefLink(type="document", id=self.doc_id)
        if target == "key_fact" and isinstance(index, int):
            facts = self._document.key_facts if self._document is not None and self.newest else []
            return ref, facts[index].label if 0 <= index < len(facts) else f"Key fact {index + 1}"
        if isinstance(target, str) and target in QUOTE_TARGET_LABELS:
            return ref, QUOTE_TARGET_LABELS[target]
        return None

    def of(self, span: TraceSpanRecord) -> tuple[RefLink, str | None] | None:
        """The record ``span`` points to, and its name now."""
        attributes = span.attributes
        if span.kind == "verify" and "target" in attributes:
            return self.quote_target(attributes)
        if "item_id" in attributes or ("slot_key" in attributes and span.kind in ("rules", "plan")):
            return self.item(attributes)
        for key, kind in (("party_id", "party"), ("case_id", "case"), ("contract_id", "contract")):
            if attributes.get(key):
                return self.named(kind, attributes[key])
        return None


def span_views(
    spans: Sequence[TraceSpanRecord], calls: dict[str, LLMCallRecord], records: _Records | None = None
) -> list[TraceSpan]:
    """The steps of one reading (``spans`` in ``seq`` order) as the view shows them."""
    if not spans:
        return []
    start = spans[0].started_at
    depth: dict[str, int] = {}
    views = []
    for span in spans:
        depth[span.id] = depth.get(span.parent_id or "", -1) + 1 if span.parent_id else 0
        found = records.of(span) if records is not None else None
        views.append(
            TraceSpan(
                id=span.id,
                parent_id=span.parent_id,
                depth=depth[span.id],
                key=span.key,
                kind=span.kind,
                name=span.name,
                stage=span.stage,
                start_ms=_ms(start, span.started_at),
                duration_ms=_ms(span.started_at, span.ended_at),
                status=span.status,
                error=span.error,
                attributes=span.attributes,
                call=calls.get(span.id),
                ref=found[0] if found else None,
                label=found[1] if found else None,
            )
        )
    return views


def document_trace(store: Store, doc_id: str, trace_id: str | None = None) -> DocumentTrace:
    """How ``doc_id`` was read: the reading ``trace_id`` (default: the newest kept) and every reading
    kept. Raises :class:`TraceNotFound` for a ``trace_id`` that is not one of them. Every query reads
    the same state of the database (a reading stored meanwhile is wholly in the view or not at all)."""
    with store.snapshot():
        return _document_trace(store, doc_id, trace_id)


def _document_trace(store: Store, doc_id: str, trace_id: str | None) -> DocumentTrace:
    roots = store.trace_runs(doc_id)
    calls = store.trace_calls(doc_id)
    model_steps: dict[str, list[TraceSpanRecord]] = {}
    for step in store.trace_steps(doc_id, "model"):
        model_steps.setdefault(step.trace_id, []).append(step)
    runs = [
        run_summary(root, calls.get(root.trace_id, []), model_steps.get(root.trace_id, [])) for root in roots
    ]
    if trace_id is None and not roots:
        return DocumentTrace(doc_id=doc_id)
    chosen = next((root for root in roots if root.trace_id == trace_id), None) if trace_id else roots[0]
    if chosen is None:
        raise TraceNotFound(f"This letter has no kept reading {trace_id!r}.")
    by_span = {call.span_id: call for call in calls.get(chosen.trace_id, []) if call.span_id}
    return DocumentTrace(
        doc_id=doc_id,
        run=runs[roots.index(chosen)],
        runs=runs,
        spans=span_views(
            store.trace_spans(chosen.trace_id), by_span, _Records(store, doc_id, newest=chosen is roots[0])
        ),
    )
