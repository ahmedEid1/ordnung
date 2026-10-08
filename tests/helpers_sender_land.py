"""Letters whose reading gives the sender's address, and to-dos dated as the rules engine counts them without the
sender's Land (as the app does until the person sets it): for the tests of the Land a postcode suggests."""

from __future__ import annotations

from datetime import date
from typing import Any

from helpers_secretary import TODAY, add_doc, add_item
from ordnung.db.store import Store
from ordnung.models import DateSpec, DocumentExtraction, ExtractedParty, Party
from ordnung.rules.deadlines import RuleContext, compute_due

MUNICH = "Marienplatz 8, 80331 München"
NUREMBERG = "Hauptmarkt 18, 90403 Nürnberg"
DRESDEN = "Theaterplatz 1, 01067 Dresden"
ERFURT = "Fischmarkt 1, 99084 Erfurt"

#: Five working days from Fri 13 Nov 2026, past Buß- und Bettag (Wed 18 Nov, a holiday in Saxony only).
HOLIDAY = DateSpec(
    type="relative",
    anchor="explicit_date",
    anchor_date="2026-11-13",
    amount=5,
    unit="business_days",
    nature="other",
)
#: Five working days back from Mon 23 Nov 2026, past the same holiday: counted backwards.
BACKWARDS = DateSpec(
    type="relative",
    anchor="explicit_date",
    anchor_date="2026-11-23",
    amount=-5,
    unit="business_days",
    nature="declaration",
)
#: An authority's objection period from its letter of Tue 29 Sep 2026: delivered after 3 or 4 days by its Land.
DELIVERY = DateSpec(
    type="relative",
    anchor="deemed_delivery",
    amount=1,
    unit="months",
    delivery_rule="de_admin_post",
    nature="objection",
    legal_basis="§ 70 VwGO",
)
#: Five working days from Mon 5 Oct 2026: no holiday anywhere.
QUIET = DateSpec(
    type="relative",
    anchor="explicit_date",
    anchor_date="2026-10-05",
    amount=5,
    unit="business_days",
    nature="other",
)


def without_land(spec: DateSpec) -> RuleContext:
    """The context the app counts ``spec`` in until the sender's Land is set."""
    if spec is DELIVERY:
        return RuleContext(today=TODAY, region=None, document_date=date(2026, 9, 29), delivery_scope="vwvfg")
    return RuleContext(today=TODAY, region=None)


def letter_from(
    store: Store,
    party: Party,
    address: str | None,
    *,
    day: str = "2026-09-20",
    shown: str | None = None,
    hidden: str = "",
    email: str | None = None,
    **fields: Any,
) -> str:
    """A read letter from ``party`` whose reading gives ``address`` as the sender's; its page shows ``shown``
    (the address, by default) and hides ``hidden``."""
    sender = ExtractedParty(name=party.name, kind=party.kind, address=address, email=email)
    reading = DocumentExtraction(
        kind="other", title="A letter", summary="A letter.", explanation=".", sender=sender
    )
    label = f"{party.id} {day} {address} {fields}"
    doc_id = add_doc(
        store, label, party_id=party.id, doc_date=day, title="A letter", extraction=reading, **fields
    )
    text = f"{party.name}\n{address or ''}\nSehr geehrte Frau Rivera," if shown is None else shown
    page = {
        "page": 1,
        "width": 1240,
        "height": 1754,
        "image_path": "derived/p1.jpg",
        "text": text,
        "hidden": hidden,
    }
    store.set_pages(doc_id, [page])
    return doc_id


def to_do(store: Store, party: Party, doc_id: str, spec: DateSpec, **fields: Any) -> str:
    """A to-do of the letter, dated by the engine from ``spec`` without the sender's Land."""
    receipt = compute_due(spec, without_land(spec))
    fields.setdefault("origin", "extracted")
    fields.setdefault("due_date_source", "computed")
    fields.setdefault("filed_on", "2026-09-21")
    return add_item(
        store,
        kind="deadline",
        title=f"Act ({spec.nature})",
        due_date=receipt.due_date,
        send_by=receipt.send_by,
        computation=receipt,
        date_spec=spec,
        party_id=party.id,
        doc_id=doc_id,
        **fields,
    )
