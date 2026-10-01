"""Date work the API does on the person's behalf, always through the rules engine (SPEC §21):

* :func:`recompute_document_items` — after the person confirms when a letter arrived (or corrects
  its date or kind), the letter's extracted to-dos are recomputed from their stored DateSpecs and so
  are the deadlines the law adds to its kind (filed again only when the person chose the kind);
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
from ordnung.ingest.conflicts import Rival, find_rivals
from ordnung.ingest.gaps import CHECK_SLOT, check_reasons, remedy_notices, square_gap_warnings
from ordnung.ingest.plan import (
    VerifiedItem,
    checked_evidence,
    compute_item,
    consistency_reasons,
    document_context,
    first_dated,
    for_item,
    item_contexts,
    kept_payment_note,
    kind_chosen,
    law_deadlines,
    needs_check,
    payment_note,
    rent_context,
    sync_rule_items,
    with_notice,
    with_payment_note,
)
from ordnung.ingest.verify import ground_evidence
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
from ordnung.recurrence import (
    SCHEDULE_FIELDS,
    at_occurrence,
    keeps_later_date,
    replacement,
    rolled,
    settle_rents,
)
from ordnung.rules import RuleContext, compute_due
from ordnung.secretary.triggers import postal_buffer

MANUAL_SUMMARY = "You set this date yourself."
_KIND_NATURES: dict[str, DateNature] = {"payment": "payment", "appointment": "appointment"}


# --------------------------------------------------------------------------------------------------
# recompute after the arrival date (or the letter's date) was confirmed
# --------------------------------------------------------------------------------------------------


def _extracted(item: Item, spec: DateSpec) -> ExtractedItem:
    """The stored item as the reading it came from (its first evidence's quote)."""
    evidence = item.evidence[0] if item.evidence else None
    return ExtractedItem(
        kind=item.kind,
        title=item.title,
        date=spec,
        amount=item.amount,
        direction=item.direction,
        recurrence=item.recurrence,
        quote=evidence.quote if evidence else "",
    )


def _verified(
    item: Item, spec: DateSpec, pages: Sequence[Page], others: Sequence[ExtractedItem] = ()
) -> VerifiedItem:
    """The stored item in the shape the pipeline grades: its evidence and quote problems (graded as
    when the letter was read, so values written elsewhere in the letter still count), and the letter's
    other statements that date its obligation (``others``: the letter's to-dos as read,
    :func:`~ordnung.ingest.conflicts.find_rivals`) — also once the person confirmed its date, so a recompute
    keeps the earlier one they confirmed (no reasons then: nothing is flagged again). The to-do code
    filed for an incomplete reading stays graded as Ordnung's own date (``READING_INCOMPLETE``: ``low`` and
    "Please check") until the person confirms it. The period the letter's own notice gives is set beside a
    to-do that dates the objection by :func:`recompute_document_items` (:func:`~ordnung.ingest.plan.with_notice`)."""
    evidence = item.evidence[0] if item.evidence else None
    extracted = _extracted(item, spec)
    reasons: tuple[str, ...] = ()
    rivals: tuple[Rival, ...] = ()
    if evidence is not None and item.grounding != "user":
        reasons = consistency_reasons(extracted, pages)
        if item.slot_key == CHECK_SLOT:
            reasons = check_reasons(reasons)
    if evidence is not None:
        # a confirmed to-do keeps the letter's other dates: the date the person confirmed was the earlier one
        rivals = find_rivals(extracted, [extracted, *others], pages)
    grounding = "user" if item.grounding == "user" else (evidence.grounding if evidence else "unverified")
    graded = (evidence or _placeholder_evidence(item)).model_copy(update={"grounding": grounding})
    return VerifiedItem(
        item=extracted, evidence=graded, reasons=reasons, slot_key=item.slot_key or item.id, rivals=rivals
    )


def _placeholder_evidence(item: Item) -> Evidence:
    return Evidence(doc_id=item.doc_id or "", quote="")


def recomputable(item: Item) -> bool:
    """An extracted to-do whose date the engine computed from a DateSpec (not typed in by hand)."""
    return item.origin == "extracted" and item.date_spec is not None and item.due_date_source != "manual"


def recompute_document_items(
    store: Store, document: Document, today: date, *, refile_rules: bool = False
) -> list[Item]:
    """Recompute the letter's extracted to-dos with its current dates; returns the changed items.

    The deadlines the law adds to its kind are recomputed too; only with ``refile_rules`` (the person
    chose the letter's kind) are the missing ones filed again — a rule to-do the person deleted is
    never brought back by a changed region, postal buffer or arrival day.

    The letter's own ``doc_date`` (possibly corrected by the person) replaces the extracted date,
    and a stored ``received_date`` counts as confirmed (the person entered it). A recurring to-do
    moves on to its current occurrence, as when the letter was read (one whose rule has a working day from
    its schedule's first, with its payment note: :func:`~ordnung.ingest.plan.first_dated`, point 8), and
    never back on its schedule: an occurrence it keeps (one paid ahead) gets its dates and receipt in the
    current context (:mod:`ordnung.recurrence`, points 5 and 6). A rent keeps the due day of the rent
    before it on its rent contract and never moves into the month a later one replaces it from (point 9).
    """
    ctx = document_context(store, document, today)
    if ctx is None:
        return []
    buffer = postal_buffer(store.get_profile())
    pages = store.list_pages(document.id)
    extraction = store.get_extraction(document.id)
    note = payment_note(
        document.kind,
        extraction,
        document.title,
        store.get_document_text(document.id),
        ctx,
        chosen=kind_chosen(store, document),
    )
    changed: list[Item] = []
    contexts = item_contexts()
    notices = remedy_notices(pages)
    with store.tx():
        stored = store.list_items(doc_id=document.id)
        read = {
            other.id: _extracted(other, other.date_spec)
            for other in stored
            if other.origin == "extracted" and other.date_spec is not None
        }
        for item in stored:
            if not recomputable(item) or item.date_spec is None:
                continue
            contract = store.get_contract(item.contract_id) if item.contract_id else None
            item_ctx = rent_context(store, item, for_item(ctx, item, note, contract))
            others = [extracted for other_id, extracted in read.items() if other_id != item.id]
            # a reading's objection date weeks after the letter's own notice: that notice beside it, as when read
            [verified] = with_notice(
                [_verified(item, item.date_spec, pages, others)], extraction, pages, notices
            )
            result = with_payment_note(
                compute_item(verified, item_ctx, postal_buffer_days=buffer), item, note
            )
            recomputed = item.model_copy(
                update={
                    "due_date": result.due_date,
                    "send_by": result.send_by,
                    "computation": result.receipt,
                    "due_date_source": result.source,
                }
            )
            starts = contract.start_date if contract else None
            first = first_dated(
                recomputed, item_ctx, postal_buffer_days=buffer, starts=starts, reasons=verified.reasons
            )
            recomputed = first or recomputed
            replaced = replacement(store, item, item_ctx, contexts)  # point 9: never past its last month
            ends = replaced.starts if replaced is not None else None
            moved = rolled(recomputed, item_ctx, postal_buffer_days=buffer, ends=ends) or recomputed
            if keeps_later_date(item, item.recurrence, item.date_spec, moved.due_date, item_ctx):
                moved = at_occurrence(recomputed, item.due_date, item_ctx, postal_buffer_days=buffer) or item
            fields: dict[str, Any] = {name: getattr(moved, name) for name in SCHEDULE_FIELDS}
            if (
                result.conflict
                and item.grounding != "user"
                and item.evidence
                and item.evidence[0].value_consistent
            ):
                # the letter gives the to-do two dates: "Please check", as when it was read (not once confirmed:
                # a to-do the person confirmed keeps the earlier date, and its evidence stays as they confirmed)
                fields["evidence"] = [checked_evidence(verified, result), *item.evidence[1:]]
            if any(getattr(item, name) != value for name, value in fields.items()):
                changed.append(store.update_item(item.id, **fields))
        contracts = [item.contract_id for item in store.list_items(doc_id=document.id)]
        settle_rents(store, today, contexts, contract_ids=contracts)  # point 9, in the new context
        changed.extend(
            _refresh_rule_items(store, document, ctx, today, buffer, create=refile_rules, pages=pages)
        )
    return changed


def _refresh_rule_items(
    store: Store,
    document: Document,
    ctx: RuleContext,
    today: date,
    buffer: int,
    *,
    create: bool,
    pages: Sequence[Page],
) -> list[Item]:
    """Recompute the deadlines the law adds to the letter's (possibly corrected) kind, filing missing
    ones only with ``create``; returns the rule to-dos that are new or whose dates changed."""
    before = {item.id: item for item in store.list_items(doc_id=document.id) if item.origin == "rule"}
    extraction = store.get_extraction(document.id)
    derived = law_deadlines(document.kind, extraction, ctx)
    change = extraction.change if extraction is not None else None
    after = sync_rule_items(
        store,
        document,
        derived,
        ctx,
        today=today,
        postal_buffer_days=buffer,
        create=create,
        end_evidence=ground_evidence(document.id, change.quote, pages) if change and change.quote else None,
    )
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
    store: Store,
    due: str,
    today: date,
    *,
    nature: DateNature,
    party_id: str | None,
    in_person: bool = False,
    collected: bool = False,
) -> ComputationReceipt:
    """Receipt for a date the person set: the date as given plus the engine's send-by date (none for a
    payment made in person, ``in_person``: :func:`~ordnung.payments.pays_on_site`, nor for one nobody
    transfers, ``collected``: :func:`~ordnung.payments.is_collected_or_incoming`)."""
    spec = DateSpec(type="fixed", date=due, nature=nature, shift_rule="none", text=MANUAL_SUMMARY)
    party = store.get_party(party_id) if party_id else None
    profile = store.get_profile()
    ctx = RuleContext(
        today=today,
        country=profile.country,
        region=party.region if party else None,
        in_person=in_person,
        collected=collected,
    )
    receipt = compute_due(spec, ctx, postal_buffer_days=postal_buffer(profile))
    return receipt.model_copy(update={"summary": MANUAL_SUMMARY, "confidence": "high"})


def schedule_spec(due: str, nature: DateNature) -> DateSpec:
    """The first occurrence of a recurring to-do dated by hand: month steps keep its day of the month
    (31 Jan → 28 Feb → 31 Mar), which the current, possibly shortened, date alone would lose."""
    return DateSpec(type="fixed", date=due, nature=nature, shift_rule="none")


def manual_date_fields(
    store: Store,
    due: str | None,
    today: date,
    *,
    nature: DateNature,
    party_id: str | None,
    previous: ComputationReceipt | None = None,
    in_person: bool = False,
    collected: bool = False,
) -> dict[str, Any]:
    """Item fields for a due date set (or cleared) by the person. A payment note the ``previous`` receipt
    carried (a rent increase's new rent, a late statement's back-payment) stays: a date set by hand never
    makes such a payment owed (:func:`~ordnung.ingest.plan.kept_payment_note`). A payment made in person
    (``in_person``), collected or coming in (``collected``) gets no send-by date (:func:`manual_receipt`)."""
    if due is None:
        return {
            "due_date": None,
            "send_by": None,
            "computation": kept_payment_note(previous, None),
            "due_date_source": "none",
        }
    receipt = kept_payment_note(
        previous,
        manual_receipt(
            store, due, today, nature=nature, party_id=party_id, in_person=in_person, collected=collected
        ),
    )
    return {
        "due_date": due,
        "send_by": receipt.send_by if receipt else None,
        "computation": receipt,
        "due_date_source": "manual",
        "grounding": "user",
    }


# --------------------------------------------------------------------------------------------------
# "Please check"
# --------------------------------------------------------------------------------------------------


def refresh_review_status(store: Store, doc_id: str | None) -> Document | None:
    """Keep a read letter's "Please check" in step with its to-dos: ``needs_review`` while one of them
    needs checking, else ``processed`` (e.g. after "Undo" of "Not a real to-do" it is back) — and its warning
    about an incomplete reading in step with the to-do Ordnung added for it (:func:`square_gap_warnings`)."""
    document = store.get_document(doc_id) if doc_id else None
    if document is None or document.status not in ("needs_review", "processed"):
        return None
    items = store.list_items(doc_id=document.id)
    unsure = any(needs_check(item) for item in items)
    wanted = "needs_review" if unsure else "processed"
    warnings = square_gap_warnings(document.warnings, items)
    if document.status == wanted and warnings == document.warnings:
        return None
    return store.update_document(document.id, status=wanted, warnings=warnings)
