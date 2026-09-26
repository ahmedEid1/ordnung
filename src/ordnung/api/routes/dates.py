"""Date work the API does on the person's behalf, always through the rules engine (SPEC §21):

* :func:`recompute_document_items` — after the person confirms when a letter arrived (or corrects
  its date or kind), the letter's extracted to-dos are recomputed from their stored DateSpecs and the
  deadlines the law adds to its kind are filed again;
  :func:`recompute_all_items` does it for every letter after the holiday region changed;
* :func:`manual_date_fields` — a date the person typed in becomes ``due_date_source="manual"`` with
  a send-by date and a receipt from the engine;
* :func:`refresh_review_status` — a letter is "Please check" exactly while one of its open to-dos
  still needs checking (confirmed, re-dated, dismissed, done or deleted ones don't).

Items the person dated by hand (``due_date_source="manual"``) are never recomputed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from ordnung.db.store import Store
from ordnung.ingest.plan import (
    VerifiedItem,
    compute_item,
    consistency_reasons,
    document_context,
    law_deadlines,
    needs_check,
    sync_rule_items,
)
from ordnung.models import (
    ComputationReceipt,
    DateNature,
    DateSpec,
    Document,
    Evidence,
    ExtractedItem,
    Item,
    Page,
)
from ordnung.recurrence import SCHEDULE_FIELDS, at_occurrence, keeps_later_date, rolled
from ordnung.rules import RuleContext, compute_due
from ordnung.secretary.triggers import postal_buffer

MANUAL_SUMMARY = "You set this date yourself."
_KIND_NATURES: dict[str, DateNature] = {"payment": "payment", "appointment": "appointment"}


# --------------------------------------------------------------------------------------------------
# recompute after the arrival date (or the letter's date) was confirmed
# --------------------------------------------------------------------------------------------------


def _verified(item: Item, spec: DateSpec, pages: Sequence[Page]) -> VerifiedItem:
    """The stored item in the shape the pipeline grades: its evidence and quote problems (graded as
    when the letter was read, so values written elsewhere in the letter still count)."""
    evidence = item.evidence[0] if item.evidence else None
    quote = evidence.quote if evidence else ""
    extracted = ExtractedItem(
        kind=item.kind,
        title=item.title,
        date=spec,
        amount=item.amount,
        recurrence=item.recurrence,
        quote=quote,
    )
    reasons: tuple[str, ...] = ()
    if evidence is not None and item.grounding != "user":
        reasons = consistency_reasons(extracted, pages)
    grounding = "user" if item.grounding == "user" else (evidence.grounding if evidence else "unverified")
    graded = (evidence or _placeholder_evidence(item)).model_copy(update={"grounding": grounding})
    return VerifiedItem(item=extracted, evidence=graded, reasons=reasons, slot_key=item.slot_key or item.id)


def _placeholder_evidence(item: Item) -> Evidence:
    return Evidence(doc_id=item.doc_id or "", quote="")


def recomputable(item: Item) -> bool:
    """An extracted to-do whose date the engine computed from a DateSpec (not typed in by hand)."""
    return item.origin == "extracted" and item.date_spec is not None and item.due_date_source != "manual"


def recompute_document_items(store: Store, document: Document, today: date) -> list[Item]:
    """Recompute the letter's extracted to-dos with its current dates; returns the changed items.

    The letter's own ``doc_date`` (possibly corrected by the person) replaces the extracted date,
    and a stored ``received_date`` counts as confirmed (the person entered it). A recurring to-do
    moves on to its current occurrence, as when the letter was read, and never back on its schedule:
    an occurrence it keeps (one paid ahead) gets its dates and receipt in the current context
    (:mod:`ordnung.recurrence`, points 5 and 6).
    """
    ctx = document_context(store, document, today)
    if ctx is None:
        return []
    buffer = postal_buffer(store.get_profile())
    pages = store.list_pages(document.id)
    changed: list[Item] = []
    with store.tx():
        for item in store.list_items(doc_id=document.id):
            if not recomputable(item) or item.date_spec is None:
                continue
            result = compute_item(_verified(item, item.date_spec, pages), ctx, postal_buffer_days=buffer)
            recomputed = item.model_copy(
                update={
                    "due_date": result.due_date,
                    "send_by": result.send_by,
                    "computation": result.receipt,
                    "due_date_source": result.source,
                }
            )
            moved = rolled(recomputed, ctx, postal_buffer_days=buffer) or recomputed
            if keeps_later_date(item, item.recurrence, item.date_spec, moved.due_date):
                moved = at_occurrence(recomputed, item.due_date, ctx, postal_buffer_days=buffer) or item
            fields = {name: getattr(moved, name) for name in SCHEDULE_FIELDS}
            if any(getattr(item, name) != value for name, value in fields.items()):
                changed.append(store.update_item(item.id, **fields))
        changed.extend(_refresh_rule_items(store, document, ctx, today, buffer))
    return changed


def _refresh_rule_items(
    store: Store, document: Document, ctx: RuleContext, today: date, buffer: int
) -> list[Item]:
    """File the deadlines the law adds to the letter's (possibly corrected) kind again; returns the
    rule to-dos that are new or whose dates changed."""
    before = {item.id: item for item in store.list_items(doc_id=document.id) if item.origin == "rule"}
    derived = law_deadlines(document.kind, store.get_extraction(document.id), ctx)
    after = sync_rule_items(store, document, derived, ctx, today=today, postal_buffer_days=buffer)
    dates = ("due_date", "send_by")
    return [
        item
        for item in after
        if item.id not in before or any(getattr(item, n) != getattr(before[item.id], n) for n in dates)
    ]


def recompute_all_items(store: Store, today: date) -> list[Item]:
    """Recompute the extracted to-dos of every letter (the holiday region or the postal buffer changed)."""
    changed: list[Item] = []
    with store.tx():
        for document in store.list_documents(include_deleted=True):
            changed.extend(recompute_document_items(store, document, today))
    return changed


# --------------------------------------------------------------------------------------------------
# dates typed in by the person
# --------------------------------------------------------------------------------------------------


def date_nature(kind: str, spec: DateSpec | None) -> DateNature:
    """What kind of date a to-do has (decides the send-by date): its DateSpec's, else by item kind."""
    return spec.nature if spec is not None else _KIND_NATURES.get(kind, "other")


def manual_receipt(
    store: Store, due: str, today: date, *, nature: DateNature, party_id: str | None
) -> ComputationReceipt:
    """Receipt for a date the person set: the date as given plus the engine's send-by date."""
    spec = DateSpec(type="fixed", date=due, nature=nature, shift_rule="none", text=MANUAL_SUMMARY)
    party = store.get_party(party_id) if party_id else None
    profile = store.get_profile()
    ctx = RuleContext(today=today, country=profile.country, region=party.region if party else None)
    receipt = compute_due(spec, ctx, postal_buffer_days=postal_buffer(profile))
    return receipt.model_copy(update={"summary": MANUAL_SUMMARY, "confidence": "high"})


def schedule_spec(due: str, nature: DateNature) -> DateSpec:
    """The first occurrence of a recurring to-do dated by hand: month steps keep its day of the month
    (31 Jan → 28 Feb → 31 Mar), which the current, possibly shortened, date alone would lose."""
    return DateSpec(type="fixed", date=due, nature=nature, shift_rule="none")


def manual_date_fields(
    store: Store, due: str | None, today: date, *, nature: DateNature, party_id: str | None
) -> dict[str, Any]:
    """Item fields for a due date set (or cleared) by the person."""
    if due is None:
        return {"due_date": None, "send_by": None, "computation": None, "due_date_source": "none"}
    receipt = manual_receipt(store, due, today, nature=nature, party_id=party_id)
    return {
        "due_date": due,
        "send_by": receipt.send_by,
        "computation": receipt,
        "due_date_source": "manual",
        "grounding": "user",
    }


# --------------------------------------------------------------------------------------------------
# "Please check"
# --------------------------------------------------------------------------------------------------


def refresh_review_status(store: Store, doc_id: str | None) -> Document | None:
    """Keep a read letter's "Please check" in step with its to-dos: ``needs_review`` while one of them
    needs checking, else ``processed`` (e.g. after "Undo" of "Not a real to-do" it is back)."""
    document = store.get_document(doc_id) if doc_id else None
    if document is None or document.status not in ("needs_review", "processed"):
        return None
    unsure = any(needs_check(item) for item in store.list_items(doc_id=document.id))
    wanted = "needs_review" if unsure else "processed"
    if document.status == wanted:
        return None
    return store.update_document(document.id, status=wanted)
