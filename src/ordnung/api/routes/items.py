"""To-dos & dates: list, add, edit, confirm, delete, and a single to-do as ``.ics``.

A due date the person sets becomes ``due_date_source="manual"`` (with a send-by date from the rules
engine) and marks the to-do ``user_modified`` so reading the letter again never overwrites it.
Status changes (done, snoozed until a day, dismissed …) are explicit clicks; nothing here changes a
status on its own — except that a recurring to-do marked done moves on to its next occurrence and
stays open, and set open again ("Undo") goes back to it (:mod:`ordnung.recurrence`). A to-do added
by hand that repeats on a working day or a day of the month is dated by its rule at once, and its
schedule starts again at its date when it gets a new rule or its rule together with a date (point 2).
After every edit or deletion the letter's "Please check" is brought up to date.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ordnung.api.deps import CtxDep, StoreDep, TodayDep
from ordnung.api.routes.common import IsoDate, ledger_changed, require, set_aside
from ordnung.api.routes.dates import date_nature, manual_date_fields, refresh_review_status, schedule_spec
from ordnung.calendar.ics import build_ics
from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.ingest.plan import item_context, item_contexts
from ordnung.models import (
    Area,
    ComputationReceipt,
    Item,
    ItemKind,
    ItemStatus,
    ListedItem,
    Priority,
    Recurrence,
)
from ordnung.payments import is_collected_or_incoming, pays_on_site
from ordnung.recurrence import (
    SCHEDULE_FIELDS,
    first_scheduled,
    kept_occurrence,
    mark_done,
    over_the_law,
    replaced_occurrence,
    replacement,
    roll_item,
    same_rule,
    settle_rents,
    standing_in,
    undo_done,
    undo_replaced,
)
from ordnung.secretary.triggers import postal_buffer

router = APIRouter(tags=["items"])

NOT_FOUND = "Unknown to-do."
DEFAULT_SNOOZE_DAYS = 7
_CONTENT_FIELDS = ("title", "description", "due_time", "amount", "priority", "area", "location", "recurrence")
_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class ItemCreate(BaseModel):
    """A to-do or date the person adds by hand."""

    model_config = ConfigDict(extra="forbid")

    kind: ItemKind
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    due_date: IsoDate | None = None
    due_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    amount: float | None = None
    currency: str | None = None
    direction: Literal["out", "in"] | None = None
    recurrence: Recurrence | None = None
    priority: Priority = "normal"
    area: Area = "other"
    party_id: str | None = None
    case_id: str | None = None
    contract_id: str | None = None
    doc_id: str | None = None
    location: str | None = None


class ItemPatch(BaseModel):
    """Edits to a to-do; ``notes`` is accepted as another name for ``description``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, validation_alias=AliasChoices("description", "notes"))
    due_date: IsoDate | None = None
    due_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    amount: float | None = None
    status: ItemStatus | None = None
    snoozed_until: IsoDate | None = None
    priority: Priority | None = None
    area: Area | None = None
    location: str | None = None
    recurrence: Recurrence | None = None


# --------------------------------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------------------------------


@router.get("/items", response_model=list[ListedItem])
def list_items(
    store: StoreDep,
    today: TodayDep,
    status_: Annotated[ItemStatus | None, Query(alias="status")] = None,
    kind: ItemKind | None = None,
    from_: Annotated[IsoDate | None, Query(alias="from")] = None,
    to: IsoDate | None = None,
    area: Area | None = None,
    party_id: str | None = None,
    doc_id: str | None = None,
    contract_id: str | None = None,
    case_id: str | None = None,
    include_undated: bool = False,
    limit: Annotated[int | None, Query(ge=1, le=5000)] = None,
) -> list[ListedItem]:
    """To-dos & dates, soonest first. With a ``from``/``to`` range undated ones are left out unless
    ``include_undated``. Each says whether it is set aside (``aside``: not one to act on, as on Today)."""
    ranged = from_ is not None or to is not None
    items = store.list_items(
        status=status_,
        kind=kind,
        from_date=from_,
        to_date=to,
        area=area,
        party_id=party_id,
        doc_id=doc_id,
        contract_id=contract_id,
        case_id=case_id,
        include_undated=include_undated or not ranged,
        limit=limit,
    )
    aside = {entry.item_id: entry for entry in set_aside(store, items, today)}
    return [ListedItem.model_construct(**dict(item), aside=aside.get(item.id)) for item in items]


@router.get("/items/{item_id}.ics", response_class=Response)
def item_ics(item_id: str, store: StoreDep) -> Response:
    """One to-do as a calendar file (with its reminders)."""
    require(store.get_item(item_id), NOT_FOUND)
    try:
        body = build_ics(store, only_item_id=item_id, include_done=True)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This to-do has no date to put in a calendar."
        ) from exc
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{item_id}.ics"', "Cache-Control": "no-store"},
    )


@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: str, store: StoreDep) -> Item:
    """One to-do (with its evidence and "Why this date?" receipt)."""
    return require(store.get_item(item_id), NOT_FOUND)


# --------------------------------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------------------------------


def _check_links(store: Store, fields: dict[str, Any]) -> None:
    lookups = {
        "party_id": (store.get_party, "Unknown person or organisation."),
        "case_id": (store.get_case, "Unknown thread."),
        "contract_id": (store.get_contract, "Unknown contract."),
        "doc_id": (store.get_document, "Unknown letter."),
    }
    for name, (lookup, message) in lookups.items():
        if fields.get(name) is not None:
            require(lookup(fields[name]), message)


def _create(store: Store, body: ItemCreate, today: date) -> Item:
    fields = body.model_dump()
    _check_links(store, fields)
    due = fields.pop("due_date")
    nature = date_nature(body.kind, None)
    probe = Item.model_construct(**fields)  # judged by its words, as an edit is; never stored
    dates = manual_date_fields(
        store,
        due,
        today,
        nature=nature,
        party_id=body.party_id,
        in_person=pays_on_site(probe),
        collected=is_collected_or_incoming(probe),
    )
    if due is not None and body.recurrence is not None:
        dates["date_spec"] = schedule_spec(due, nature)
    with store.tx():
        item = store.add_item(
            **{**fields, **dates, "grounding": "user", "origin": "manual", "filed_on": today.isoformat()}
        )
        if body.recurrence is not None:
            item = _scheduled_start(store, item, today)
        return _follow_schedule(store, item, today)


@router.post("/items", response_model=Item, status_code=status.HTTP_201_CREATED)
async def create_item(body: ItemCreate, ctx: CtxDep, today: TodayDep) -> Item:
    """Add a to-do or date by hand. One that repeats on a working day or a day of the month is dated
    at once at its first occurrence: the Nth working day of the month ``due_date`` names, or the first
    such day of the month on or after ``due_date``; one already past moves on to the first occurrence
    from today. Any other rule starts on ``due_date``."""
    item = await asyncio.to_thread(_create, ctx.store, body, today)
    await ledger_changed(ctx, item_id=item.id)
    return item


def _status_fields(item: Item, changes: dict[str, Any], today: date) -> dict[str, Any]:
    """Status, snooze and completion time for an explicit status change or snooze date."""
    wanted = changes.get("status")
    if wanted is None and "snoozed_until" in changes:
        wanted = (
            "snoozed" if changes["snoozed_until"] else ("open" if item.status == "snoozed" else item.status)
        )
    if wanted is None:
        return {}
    fields: dict[str, Any] = {"status": wanted, "snoozed_until": None}
    if wanted == "snoozed":
        until = changes.get("snoozed_until") or (today + timedelta(days=DEFAULT_SNOOZE_DAYS)).isoformat()
        fields["snoozed_until"] = until
    if wanted == "done":
        fields["completed_at"] = item.completed_at if item.status == "done" else now_iso()
    else:
        fields["completed_at"] = None
    return fields


def _restarts(item: Item, patch: ItemPatch) -> bool:
    """Whether an edit starts the schedule of a to-do not read from a letter again at its date (recurrence.py,
    point 2): it starts repeating, repeats by a new rule, or is sent its rule together with a date ("from this
    date on"). A date sent alone stands in for one occurrence (point 7)."""
    sent = patch.model_fields_set
    if item.origin == "extracted" or "recurrence" not in sent or patch.recurrence is None:
        return False
    return "due_date" in sent or not same_rule(patch.recurrence, item.recurrence)


def _scheduled_start(store: Store, item: Item, today: date) -> Item:
    """Where the schedule of a to-do not read from a letter starts (points 2, 8 and 10): a rule with a working
    day dates it in the month its date names, one with a day of the month on the first such day on or after
    its date (:func:`~ordnung.recurrence.first_scheduled`); any other rule starts on the date itself."""
    if item.recurrence is None or item.due_date is None:
        return item
    ctx = item_context(store, item, today)
    first = first_scheduled(item, ctx, postal_buffer_days=postal_buffer(store.get_profile()))
    if first is None:
        return item
    return store.update_item(item.id, **{name: getattr(first, name) for name in SCHEDULE_FIELDS})


def _schedule_fields(item: Item, fields: dict[str, Any], *, restart: bool) -> dict[str, Any]:
    """Where a recurring to-do's schedule starts (recurrence.py, point 2): a to-do whose DateSpec gives
    no date (added by hand, or undated in its letter) keeps the first date it gets as a fixed DateSpec
    (its day of the month; the letter's words kept), and so does a to-do added by hand that starts
    repeating or repeats by a new rule. A date moved by hand later leaves the schedule as it is: it
    stands in for the occurrence it replaced until it passes (point 7). A date its working day gave it
    (point 8: ``computed``, though its DateSpec gives none) is not one it got from the person; one the
    person gives a rent the law's working day dates replaces the law's day for every month, and says so
    on its receipt when it is later (:func:`~ordnung.recurrence.over_the_law`)."""
    recurrence = fields.get("recurrence", item.recurrence)
    due = fields.get("due_date", item.due_date)
    spec = item.date_spec
    if recurrence is None or due is None:
        return {}
    if spec is not None and spec.type == "none":
        if "due_date" not in fields and item.due_date_source == "computed":
            return {}
        return {"date_spec": spec.model_copy(update={"type": "fixed", "date": due})}
    if spec is None or restart:
        return {"date_spec": schedule_spec(due, date_nature(item.kind, spec))}
    return {}


def _kept_day_stands_in(store: Store, dated: Item, today: date) -> ComputationReceipt | None:
    """The receipt of the first date the person gives an undated to-do (``dated``: with it): for a rent that
    keeps an earlier rent's due day, one naming the occurrence of that month it stands in for, so marked paid
    it moves on past that month (:func:`~ordnung.recurrence.kept_occurrence`, points 7 and 9)."""
    if dated.recurrence is None or dated.computation is None:
        return dated.computation
    buffer = postal_buffer(store.get_profile())
    kept = kept_occurrence(dated, item_context(store, dated, today), postal_buffer_days=buffer)
    return dated.computation if kept is None else standing_in(dated.computation, kept)


def _follow_schedule(
    store: Store, item: Item, today: date, *, done: bool = False, reopened: bool = False
) -> Item:
    """A recurring to-do follows its schedule (:mod:`ordnung.recurrence`): marked done it moves on to
    its next occurrence and stays open, and set open again ("Undo") it goes back to the occurrence
    marked done; a date that has passed moves on to the current occurrence. A rent a later one replaces
    never moves into the month that one starts: marked done at its last occurrence it closes there, and
    the rents of its contract follow (point 9: :func:`~ordnung.recurrence.settle_rents`; a rent a payment
    closed opens again with its "Undo": :func:`~ordnung.recurrence.undo_replaced`)."""
    if item.recurrence is None:
        return item
    contexts = item_contexts()
    ctx = contexts(store, item, today)
    buffer = postal_buffer(store.get_profile())
    replaced = replacement(store, item, ctx, contexts)
    if done:
        item = mark_done(store, item, ctx, postal_buffer_days=buffer, replaced=replaced) or item
    else:
        undone = undo_done(store, item) if reopened else None
        if undone is not None:  # and a rent its payment closed is back (point 9)
            item = undone
            undo_replaced(store, item, contexts, today)
        ends = replaced.starts if replaced is not None else None
        item = roll_item(store, item, ctx, postal_buffer_days=buffer, ends=ends)
    if item.contract_id is not None and settle_rents(store, today, contexts, contract_ids=[item.contract_id]):
        item = store.get_item(item.id) or item
    return item


def _update(store: Store, item_id: str, patch: ItemPatch, today: date) -> Item:
    item = require(store.get_item(item_id), NOT_FOUND)
    changes = patch.model_dump(exclude_unset=True)
    fields: dict[str, Any] = {name: changes[name] for name in _CONTENT_FIELDS if name in changes}
    if "recurrence" in fields:  # the rule as read, so the same rule sent again compares equal to it
        fields["recurrence"] = patch.recurrence
    restart = _restarts(item, patch)
    # a date of your own that stops repeating keeps the date it stood at, as a date you set: its receipt no
    # longer tells how it repeats ("Why this date?", the calendar file)
    stops = item.origin != "extracted" and item.recurrence is not None and "recurrence" in fields
    stops = stops and fields["recurrence"] is None
    if "due_date" in changes or (stops and item.due_date is not None):
        nature = date_nature(item.kind, item.date_spec)
        fields |= manual_date_fields(
            store,
            changes.get("due_date", item.due_date),
            today,
            nature=nature,
            party_id=item.party_id,
            previous=item.computation,
            in_person=pays_on_site(item.model_copy(update=fields)),
            collected=is_collected_or_incoming(item.model_copy(update=fields)),
        )
        # a new start, or no more repeats, stands in for nothing
        replaced = None if restart or stops else replaced_occurrence(item)
        if item.recurrence is not None and fields["computation"] is not None and replaced is not None:
            fields["computation"] = standing_in(fields["computation"], replaced)  # recurrence.py, point 7
        if not stops:
            fields["computation"] = over_the_law(item, fields["due_date"], fields["computation"])  # point 8
    fields |= _schedule_fields(item, fields, restart=restart)
    if "due_date" in changes and fields["computation"] is not None and replaced_occurrence(item) is None:
        fields["computation"] = _kept_day_stands_in(store, item.model_copy(update=fields), today)
    if fields:
        fields["user_modified"] = True
    fields |= _status_fields(item, changes, today)
    if not fields:
        return item
    # an open recurring to-do set open again: the "Undo" of marking it done, which moved it on (or closed
    # a rent at its last occurrence, which stays done until set open again: recurrence.py, point 9)
    reopened = item.status in ("open", "done") and fields.get("status") == "open"
    done = item.status != "done" and fields.get("status") == "done"
    with store.tx():
        updated = store.update_item(item_id, **fields)
        if restart:
            updated = _scheduled_start(store, updated, today)
        updated = _follow_schedule(store, updated, today, done=done, reopened=reopened)
        refresh_review_status(store, updated.doc_id)
    return updated


@router.patch("/items/{item_id}", response_model=Item)
async def update_item(item_id: str, patch: ItemPatch, ctx: CtxDep, today: TodayDep) -> Item:
    """Edit a to-do: done / snoozed / dismissed, a date of your own, how it repeats, title and notes.

    For a to-do not read from a letter, ``recurrence`` sent together with ``due_date`` starts its
    schedule again at that date, and a new rule sent alone starts it again at its current date; a
    working day or a day of the month is dated from there at once. ``{"recurrence": null}`` stops it
    repeating and keeps its date. A date sent alone stands in for one occurrence. To-dos read from a
    letter keep following their letter's schedule."""
    item = await asyncio.to_thread(_update, ctx.store, item_id, patch, today)
    await ledger_changed(ctx, item_id=item.id)
    return item


def _confirm(store: Store, item_id: str) -> Item:
    require(store.get_item(item_id), NOT_FOUND)
    with store.tx():
        item = store.update_item(item_id, grounding="user", user_modified=True)
        refresh_review_status(store, item.doc_id)
    return item


@router.post("/items/{item_id}/confirm", response_model=Item)
async def confirm_item(item_id: str, ctx: CtxDep) -> Item:
    """ "Yes, that's right": the person checked this to-do against the letter."""
    item = await asyncio.to_thread(_confirm, ctx.store, item_id)
    await ledger_changed(ctx, item_id=item.id)
    return item


def _delete(store: Store, item_id: str) -> None:
    item = require(store.get_item(item_id), NOT_FOUND)
    with store.tx():
        store.delete_item(item_id)
        refresh_review_status(store, item.doc_id)
        store.log_activity(
            "item.deleted", f"Deleted the to-do “{item.title}”", ref_type="item", ref_id=item_id
        )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_item(item_id: str, ctx: CtxDep) -> Response:
    """Delete a to-do (an explicit click; nothing else ever deletes an obligation)."""
    await asyncio.to_thread(_delete, ctx.store, item_id)
    await ledger_changed(ctx, item_id=item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
