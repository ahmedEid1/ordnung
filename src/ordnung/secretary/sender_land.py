"""The Land the postcode on a sender's letters suggests while the person hasn't set it: a question, never an
answer (ADR 0019).

A sender's Land decides which public holidays move the dates of their letters and, for an authority, whether its
letter counts as delivered after 3 or 4 days. Only the person sets it (``PATCH /api/parties/{id}``); until then
Ordnung counts nationwide holidays and 3 days. :func:`region_suggestion` reads the postcode in the sender's
address as their own letters give it (:func:`ordnung.rules.postcodes.suggest_land`): the newest
:data:`LETTERS_LOOKED_AT` live incoming letters, without those with scam signs, each checked against the
letter's visible text and the person's own Land. Letters that name different Länder suggest nothing, and the
party's stored address (the first letter's, never refreshed) is never a source. It counts the open dates that
confirming the Land may change (:func:`~ordnung.rules.deadlines.waits_for_sender_land`): the sender's, or one
letter's. Nothing here writes ``Party.region``.

:func:`sender_land_ideas` is the ``sender_land`` Idea rule: one Idea for each sender with a suggestion and a date
that may change with it. Its fingerprint holds the Land, so "Don't know" (dismissing it) is remembered for that
Land, and setting the Land expires it. A sender who moved is asked about the new Land only once the letters
looked at agree on it: while an older one among them still names the old Land, nothing is asked.
"""

from __future__ import annotations

import threading
import weakref
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

from ordnung.ids import content_id
from ordnung.ingest.plan import item_context
from ordnung.models import (
    Document,
    Item,
    Party,
    RegionSuggestion,
    Suggestion,
    SuggestionAction,
    SuggestionRef,
)
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.deadlines import place_region, waits_for_sender_land
from ordnung.rules.postcodes import Home, PostcodeLand, suggest_land
from ordnung.secretary.triggers import (
    IdeaText,
    Ledger,
    action_day,
    fingerprint,
    is_active,
    is_decision,
    make_idea,
    parse_day,
    was_history_when_filed,
)

RULE_ID: Final = "sender_land"
#: The newest letters of a sender that are read for a postcode: once a sender who moved has sent this many,
#: their older letters no longer keep the question about the new Land back.
LETTERS_LOOKED_AT: Final = 12
#: Days before its first waiting date within which the Idea is "high" (as ``please_check``'s).
SOON_DAYS: Final = 14
#: The statuses in which a sender's Idea still stands, so the question names it (an expired one doesn't).
_IDEA_STANDS: Final = ("new", "snoozed", "dismissed")

#: English names of the Länder where they differ from the German ones (as the web app's ``BUNDESLAENDER``).
_ENGLISH: Final = {
    "BY": "Bavaria",
    "HE": "Hesse",
    "MV": "Mecklenburg-Western Pomerania",
    "NI": "Lower Saxony",
    "NW": "North Rhine-Westphalia",
    "RP": "Rhineland-Palatinate",
    "SN": "Saxony",
    "ST": "Saxony-Anhalt",
    "TH": "Thuringia",
}


def land_name(code: str) -> str:
    """A Land's name in prose ("Bavaria", "Berlin")."""
    return _ENGLISH.get(code, REGION_NAMES[code])


def idea_id(party_id: str, region: str) -> str:
    """The id of the sender's Idea about ``region`` (deterministic, as every rule Idea's)."""
    return content_id("sug", fingerprint(RULE_ID, party_id, region))


@dataclass(frozen=True)
class _Source:
    """What a sender's letters suggest: the Land, its postcode, and the newest letter that shows it."""

    land: PostcodeLand
    doc_id: str


@dataclass(frozen=True)
class _Dated:
    """An open date of a sender that confirming a Land may change: a to-do, or a contract's decision."""

    ref: SuggestionRef
    day: date | None
    warnings: tuple[str, ...]
    item: Item | None = None


_SOURCES: weakref.WeakKeyDictionary[Ledger, dict[str, _Source | None]] = weakref.WeakKeyDictionary()
_SOURCES_LOCK = threading.Lock()


def _letters(ledger: Ledger, party: Party) -> list[Document]:
    """The sender's live incoming letters, newest first (by the letter's date, then by when it was added)."""
    mine = [
        doc for doc in ledger.documents.values() if doc.party_id == party.id and doc.direction == "incoming"
    ]
    return sorted(mine, key=lambda doc: (doc.doc_date or doc.created_at, doc.created_at), reverse=True)


def _read_source(ledger: Ledger, party: Party) -> _Source | None:
    home = Home.of(ledger.profile.address, ledger.profile.known_region)
    hits: list[_Source] = []
    for doc in _letters(ledger, party)[:LETTERS_LOOKED_AT]:
        reading = ledger.extraction(doc.id)
        sender = reading.sender if reading is not None else None
        if sender is None or not sender.address or ledger.scam_signs(doc):
            continue
        land = suggest_land(
            sender.address,
            email=sender.email or party.email,
            website=sender.website or party.website,
            visible_text=ledger.store.get_document_text(doc.id),
            home=home,
        )
        if land is not None:
            hits.append(_Source(land, doc.id))
    if not hits or len({hit.land.region for hit in hits}) > 1:
        return None
    return hits[0]


def _source(ledger: Ledger, party: Party) -> _Source | None:
    """What the sender's letters suggest, read once per Ledger."""
    with _SOURCES_LOCK:
        known = _SOURCES.setdefault(ledger, {})
    if party.id not in known:
        known[party.id] = _read_source(ledger, party)
    return known[party.id]


def _may_wait(warnings: Sequence[str]) -> bool:
    """Whether confirming some Land may change a date with these warnings."""
    return any(waits_for_sender_land(warnings, code).waits for code in REGION_NAMES)


def _recomputed_by_land(item: Item) -> bool:
    """A to-do whose dates a sender's Land recomputes (``api.routes.dates.recompute_document_items``): one the
    engine computed from its letter, or one the law adds; never a date the person typed in."""
    return item.origin == "rule" or (
        item.origin == "extracted" and item.date_spec is not None and item.due_date_source != "manual"
    )


def _met_in(ledger: Ledger, item: Item | None, region: str) -> bool:
    """Whether confirming ``region`` as the sender's Land tells the engine whose holidays move ``item``'s date
    (:func:`~ordnung.rules.deadlines.place_region`): not for a payment to a company or a person, owed where the
    payer lives, nor for one counted with both Länder while the person's own Land is unknown."""
    if item is None or item.date_spec is None:
        return True
    ctx = item_context(ledger.store, item, ledger.today)
    return place_region(item.date_spec, replace(ctx, region=region)) is not None


def _open_dates(ledger: Ledger, party: Party, doc_id: str | None) -> list[_Dated]:
    """The open dates a Land may change: the sender's to-dos (``doc_id``: that letter's) that are open and not
    set aside (as the drawer lists them apart), and, for the sender, their open contract decisions."""
    found = [
        _Dated(
            SuggestionRef(type="item", id=item.id), action_day(item), tuple(item.computation.warnings), item
        )
        for item in (ledger.items_of(doc_id) if doc_id is not None else ledger.items_of_party(party.id))
        if item.computation is not None
        and _may_wait(item.computation.warnings)
        and _recomputed_by_land(item)
        and is_active(item, ledger.today)
        and not ledger.is_set_aside(item)
        and not (item.recurrence is None and was_history_when_filed(item))
    ]
    if doc_id is not None:
        return found
    decisions = [
        (contract, computation)
        for contract in ledger.active_contracts()
        if contract.party_id == party.id
        and is_decision(computation := ledger.computation(contract))
        and _may_wait(computation.warnings)
    ]
    decided = ledger.decided_contracts() if decisions else set()
    found.extend(
        _Dated(
            SuggestionRef(type="contract", id=contract.id),
            parse_day(computation.send_by),
            tuple(computation.warnings),
        )
        for contract, computation in decisions
        if contract.id not in decided
    )
    return found


def _waiting(ledger: Ledger, dates: list[_Dated], region: str) -> tuple[list[_Dated], bool]:
    """The dates confirming ``region`` may change, and whether one of them may be late until it is confirmed."""
    waiting = [
        (dated, wait)
        for dated in dates
        if (wait := waits_for_sender_land(dated.warnings, region)).waits
        and _met_in(ledger, dated.item, region)
    ]
    return [dated for dated, _ in waiting], any(wait.may_be_late for _, wait in waiting)


def region_suggestion(ledger: Ledger, party: Party, *, doc_id: str | None = None) -> RegionSuggestion | None:
    """The question about ``party``'s Land for their details, or with ``doc_id`` for that letter's page (its own
    dates); ``None`` once the Land is set, when the letters suggest none, and on a letter that is not a live
    incoming one of theirs without scam signs."""
    if party.region:
        return None
    if doc_id is not None:
        doc = ledger.document(doc_id)
        if doc is None or doc.party_id != party.id or doc.direction != "incoming" or ledger.scam_signs(doc):
            return None
    source = _source(ledger, party)
    if source is None:
        return None
    region = source.land.region
    waiting, late = _waiting(ledger, _open_dates(ledger, party, doc_id), region)
    idea = ledger.store.get_suggestion(idea_id(party.id, region))
    if idea is not None and idea.status not in _IDEA_STANDS:
        idea = None
    return RegionSuggestion(
        region=region,
        postcode=source.land.postcode,
        doc_id=source.doc_id,
        waiting=len(waiting),
        may_be_late=late,
        idea_id=idea.id if idea is not None else None,
        declined=idea is not None and idea.status == "dismissed",
    )


def _idea(ledger: Ledger, party: Party, source: _Source, waiting: list[_Dated], late: bool) -> Suggestion:
    region, postcode = source.land.region, source.land.postcode
    count = len(waiting)
    if late:
        until = f"act a working day before {'it' if count == 1 else 'them'}."
    else:
        may = "it may" if count == 1 else "they may"
        until = f"Ordnung counts only nationwide holidays, so {may} be a day or two early."
    body = (
        f"{postcode} is on their letter. Their state's public holidays may change {count} of your dates with "
        f"them; until you answer, {until}"
    )
    days = [dated.day for dated in waiting if dated.day is not None]
    first = min(days) if days else None
    soon = first is not None and (first - ledger.today).days <= SOON_DAYS
    return make_idea(
        RULE_ID,
        party.id,
        (region,),
        IdeaText(f"Is {party.name} in {land_name(region)}?", body),
        kind="deadline",
        priority="high" if soon else "normal",
        refs=[
            SuggestionRef(type="party", id=party.id),
            SuggestionRef(type="document", id=source.doc_id),
            *(dated.ref for dated in waiting),
        ],
        action=SuggestionAction(type="open", target_type="party", target_id=party.id, label="Answer"),
        due_date=first,
    )


def sender_land_ideas(ledger: Ledger) -> list[Suggestion]:
    """``sender_land``: senders without a Land whose letters suggest one while a date of theirs may change with
    it. A sender none of whose dates depends on it is asked in their details only. A dismissed Idea stays
    dismissed (the store keeps the person's answer)."""
    ideas: list[Suggestion] = []
    for party in ledger.parties.values():
        if party.region:
            continue
        dates = _open_dates(ledger, party, None)
        source = _source(ledger, party) if dates else None
        if source is None:
            continue
        waiting, late = _waiting(ledger, dates, source.land.region)
        if waiting:
            ideas.append(_idea(ledger, party, source, waiting, late))
    return ideas
