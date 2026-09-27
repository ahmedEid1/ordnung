"""What a later reading of a letter decided differently from an earlier one ("Read again and compare").

Written policy (ADR 0007):

* **Step by step, by key.** Two readings are compared step by step, a step matched by its key
  (:mod:`ordnung.trace.spans`), so the date of one to-do is compared with the date of the same to-do.
* **Decisions, not timings.** A change is a difference in what a step *decided*, listed per kind in
  :data:`DECIDED`: a model call's outcome, cache use, the model that answered and the prompt version;
  a quote's grounding, page, digit check and consistency; a date, send-by date, rule ids and
  confidence; which sender, thread or contract a letter was linked to and a payment check's finding;
  the to-do planning ended with, its date and whether it was kept as the person left it; the text
  layer's pages and hidden text; how the reading ended. How long a step took, what it cost and fuzzy
  scores are never changes — they move with every reading (a score shows up only when the grounding
  it decided changes).
* **A reading finding its own earlier work is no change.** The sender, thread and to-dos a first
  reading created are *found* by the next one, so links compare the record they chose (not whether it
  was new) and planning treats "created" and "updated" alike (:data:`SAME_ACTION`).
* **Steps in one reading only** are a change of the field ``present`` (a repair call that was needed
  once and not again; a to-do the new reading no longer has). A to-do whose sentence the model quoted
  differently has a new key, so it shows as one step gone and one added.
* **Order:** the later reading's display order, then the steps only the earlier one had. Labels and
  references are the later reading's (the earlier one's for steps only it had).
* **Compared with what.** By default a reading is compared with the newest earlier reading that was
  done (:func:`compare_base`): a paused or stopped attempt has almost no steps, so nearly every step
  would show as new. Only a letter with no such reading is compared with the newest earlier one.
"""

from __future__ import annotations

from collections.abc import Sequence

from ordnung.models import DocumentTrace, SpanKind, TraceChange, TraceComparison, TraceRun, TraceSpan

DECIDED: dict[SpanKind, tuple[str, ...]] = {
    "run": ("result", "needs_check", "items"),
    "model": ("outcome", "cache_hit", "served_model", "prompt_version", "legible"),
    "ocr": ("pages", "text_pages", "to_transcribe", "hidden_text"),
    "verify": ("grounding", "page", "digits_matched", "consistent", "reasons"),
    "rules": ("due_date", "send_by", "confidence", "rule_ids", "filed"),
    "link": ("party_id", "case_id", "contract_id", "change", "finding"),
    "plan": ("item_id", "action", "due_date", "removed"),
}
#: Planning actions that mean the same when two readings are compared: the to-do was filed from the reading.
SAME_ACTION = {"created": "filed", "updated": "filed"}


def _decided(span: TraceSpan, field: str) -> object:
    value = span.attributes.get(field)
    if span.kind == "plan" and field == "action" and isinstance(value, str):
        return SAME_ACTION.get(value, value)
    return value


def _change(shown: TraceSpan, field: str, before: object, after: object) -> TraceChange:
    return TraceChange(
        key=shown.key,
        kind=shown.kind,
        name=shown.name,
        field=field,
        before=before,
        after=after,
        ref=shown.ref,
        label=shown.label,
    )


def _changes_of(before: TraceSpan, after: TraceSpan) -> list[TraceChange]:
    return [
        _change(after, field, before.attributes.get(field), after.attributes.get(field))
        for field in DECIDED.get(after.kind, ())
        if _decided(before, field) != _decided(after, field)
    ]


def compare_base(runs: Sequence[TraceRun], head: TraceRun) -> TraceRun | None:
    """The reading ``head`` is compared with by default (``runs`` newest first; see the module docstring)."""
    older = [run for run in runs if run.reading < head.reading]
    return next((run for run in older if run.ended == "done"), older[0] if older else None)


def compare_spans(base: Sequence[TraceSpan], head: Sequence[TraceSpan]) -> list[TraceChange]:
    """What the steps of ``head`` decided differently from those of ``base`` (see the module docstring)."""
    earlier = {span.key: span for span in base}
    later = {span.key: span for span in head}
    changes: list[TraceChange] = []
    for span in head:
        old = earlier.get(span.key)
        changes += _changes_of(old, span) if old is not None else [_change(span, "present", False, True)]
    changes += [_change(span, "present", True, False) for span in base if span.key not in later]
    return changes


def compare_traces(base: DocumentTrace, head: DocumentTrace) -> TraceComparison:
    """The comparison of two readings of the same letter (each as :func:`~ordnung.trace.view.document_trace`
    returns it, with its ``run``)."""
    if base.run is None or head.run is None:
        raise ValueError("both readings must be kept to compare them")
    return TraceComparison(
        doc_id=head.doc_id, base=base.run, head=head.run, changes=compare_spans(base.spans, head.spans)
    )
