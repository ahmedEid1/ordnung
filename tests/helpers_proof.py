"""Shared set-up for the proof and waiting-for tests (no tests here): a gym contract with its thread,
a sent cancellation of it, and incoming letters and payments."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from ordnung.app_context import AppContext
from ordnung.drafts.compose import compose, mark_sent
from ordnung.models import Draft, Identifier, Item, Profile

TODAY = date(2026, 9, 28)
SENT = date(2026, 9, 1)
TRACKING = "RT 123 456 785 DE"
#: how Ordnung shows it: the groups joined by no-break spaces (never broken inside the number)
TRACKING_SHOWN = TRACKING.replace(" ", "\u00a0")
DRAFT_ANSWER: dict[str, Any] = {
    "subject": "ignored",
    "body": "Sehr geehrte Damen und Herren,\n\nvielen Dank.\n\nMit freundlichen Grüßen",
    "body_translation": "Dear Sir or Madam,\n\nthank you.\n\nKind regards",
    "enclosures": [],
    "notes_for_user": [],
}


@dataclass
class Gym:
    """FitWell: the party, its thread and the membership contract."""

    party: str
    case: str
    contract: str


def gym(ctx: AppContext) -> Gym:
    store = ctx.store
    store.save_profile(Profile(name="Sam Rivera", address="Musterweg 5\n12345 Musterstadt"))
    party = store.add_party(
        name="FitWell Studios GmbH",
        kind="company",
        address="Sportstraße 1, 12345 Musterstadt",
        identifiers=[Identifier(label="Mitgliedsnummer", value="FW-4711")],
    ).id
    case = store.add_case(title="Mitgliedschaft FW-4711", party_id=party, reference="FW-4711").id
    contract = store.add_contract(
        name="FitWell Mitgliedschaft",
        category="gym",
        party_id=party,
        case_id=case,
        customer_number="FW-4711",
        concluded_date="2025-01-02",
        start_date="2025-01-02",
        initial_term_months=12,
        notice_value=1,
        notice_unit="months",
    ).id
    return Gym(party, case, contract)


async def sent_letter(
    ctx: AppContext,
    where: Gym,
    channel: str = "registered_letter",
    *,
    kind: str = "cancellation",
    day: date = SENT,
    **kwargs: Any,
) -> Draft:
    """A cancellation of the gym contract (or another kind about it), marked as sent on ``day``."""
    draft = await compose(ctx, kind, contract_id=where.contract)  # type: ignore[arg-type]
    return mark_sent(ctx, draft.id, channel, day, **kwargs)[0]


def incoming(ctx: AppContext, label: str, **fields: Any) -> str:
    """A read incoming letter with ``fields`` (kind, title, doc_date, party_id, case_id …)."""
    doc = ctx.store.add_document(
        sha256=hashlib.sha256(label.encode()).hexdigest(),
        filename=f"{label}.pdf",
        mime="application/pdf",
        file_path=f"files/{label}.pdf",
    )
    ctx.store.update_document(doc.id, status="processed", **fields)
    return doc.id


def money_in(ctx: AppContext, title: str, **fields: Any) -> Item:
    """An open payment to the person (direction ``in``)."""
    return ctx.store.add_item(kind="payment", title=title, direction="in", currency="EUR", **fields)
