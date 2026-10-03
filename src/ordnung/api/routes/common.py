"""Helpers shared by the route modules: lookups that 404, ISO date fields, contract dates computed on
read, and announcing ledger changes (bus event + deterministic triggers, run in the background by the
worker: the request doesn't wait for the Ideas, which announce themselves with ``suggestions.updated``)."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, TypeVar

from fastapi import HTTPException, status
from pydantic import AfterValidator

from ordnung.app_context import AppContext
from ordnung.db.store import Store
from ordnung.llm.replay import ReplayBackend
from ordnung.models import CancellationSent, Contract, Item, ItemAside, Party, Profile
from ordnung.secretary.triggers import (
    Ledger,
    cancellations_sent,
    contract_computation,
    was_history_when_filed,
)

T = TypeVar("T")


def require(value: T | None, message: str) -> T:
    """``value``, or a 404 with ``message`` when it is missing."""
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, message)
    return value


def _iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"“{value}” is not a date; use the form YYYY-MM-DD.") from exc


IsoDate = Annotated[str, AfterValidator(_iso_date)]
"""A ``YYYY-MM-DD`` string (validated and normalised)."""


BROADCASTING_FEE_HINT = (
    "The broadcasting fee (Rundfunkbeitrag) is required by law for every household, so there is "
    "nothing to cancel. You can only de-register it — for example when you move abroad or move in "
    "with someone who already pays."
)
STATUTORY_HINT = (
    "This is an obligation set by law, not a contract you can cancel. If a decision about it looks "
    "wrong, you can object to that decision."
)
EMPLOYMENT_HINT = (
    "A job ends with a resignation, not a consumer cancellation: print it, sign it by hand and hand "
    "it over or post it (§ 623 BGB — email is not enough)."
)
_STATUTORY_PARTY_KINDS = frozenset({"authority", "tax_office", "immigration_office"})
_BROADCASTING_FEE_RE = re.compile(r"rundfunkbeitrag|beitragsservice|broadcasting fee", re.IGNORECASE)


def cancellability(contract: Contract, party: Party | None) -> tuple[bool, str | None]:
    """Whether a consumer cancellation letter (Kündigung) applies to ``contract``, else why not.

    Not for the broadcasting fee (public broadcaster), obligations towards authorities, or a job
    (that is a resignation, with its own form rules).
    """
    kind = party.kind if party is not None else None
    names = (contract.name, party.name if party is not None else "")
    if kind == "public_broadcaster" or any(_BROADCASTING_FEE_RE.search(name) for name in names):
        return False, BROADCASTING_FEE_HINT
    if kind in _STATUTORY_PARTY_KINDS:
        return False, STATUTORY_HINT
    if contract.category == "employment":
        return False, EMPLOYMENT_HINT
    return True, None


def with_computation(
    contract: Contract,
    party: Party | None,
    today: date,
    profile: Profile,
    *,
    sent: CancellationSent | None = None,
) -> Contract:
    """The contract with its cancellation dates recomputed by the rules engine for ``today``, whether it
    can be cancelled (:func:`cancellability`) and the person's cancellation of it marked as sent."""
    cancellable, hint = cancellability(contract, party)
    return contract.model_copy(
        update={
            "computed": contract_computation(contract, party, today, profile),
            "cancellable": cancellable,
            "cancel_hint": hint,
            "cancellation_sent": sent if contract.status == "active" else None,
        }
    )


def contracts_with_computations(store: Store, contracts: list[Contract], today: date) -> list[Contract]:
    """Contracts with fresh computations (parties looked up once each) and the cancellations marked as
    sent (:func:`ordnung.secretary.triggers.cancellations_sent`)."""
    profile = store.get_profile()
    parties: dict[str, Party | None] = {}
    sent = cancellations_sent(store.list_drafts(status="sent"))
    result = []
    for contract in contracts:
        party_id = contract.party_id
        if party_id is not None and party_id not in parties:
            parties[party_id] = store.get_party(party_id)
        party = parties.get(party_id) if party_id else None
        result.append(with_computation(contract, party, today, profile, sent=sent.get(contract.id)))
    return result


def item_aside(ledger: Ledger, item: Item) -> ItemAside | None:
    """Why an open to-do is not one to act on (the same rules as Today), or ``None``: its letter shows
    scam signs, a payment reminder took over its invoice payment, an e-mail repeats the payment of the
    bill attached to it, or its date had long passed when the letter was read (a one-off; a schedule
    shows its next date)."""
    if item.status in ("done", "dismissed"):
        return None
    if ledger.is_suspicious_item(item):
        return ItemAside(item_id=item.id, reason="suspicious")
    if ledger.is_superseded_by_reminder(item):
        reminder = ledger.covering_reminders()[item.doc_id or ""]
        return ItemAside(item_id=item.id, reason="replaced", replaced_by=reminder.id)
    if ledger.is_covered_by_attachment(item):
        bill = ledger.covering_attachments()[item.id]
        return ItemAside(item_id=item.id, reason="attached", replaced_by=bill.id)
    if item.recurrence is None and was_history_when_filed(item):
        return ItemAside(item_id=item.id, reason="history")
    return None


def set_aside(store: Store, items: list[Item], today: date) -> list[ItemAside]:
    """The to-dos among ``items`` that are not one to act on, with why (:func:`item_aside`); the Ledger
    shares the rows every Ledger of this state of the database reads, so a page's calls load them once."""
    if not any(item.status not in ("done", "dismissed") for item in items):
        return []
    ledger = Ledger(store, today)
    return [aside for item in items if (aside := item_aside(ledger, item)) is not None]


def replay_only(ctx: AppContext) -> bool:
    """The model backend only replays recordings (the zero-token demo): nothing new can be asked."""
    backend = ctx.llm.backend
    return isinstance(backend, ReplayBackend) and backend.fallback is None


async def ledger_changed(ctx: AppContext, *, item_id: str | None = None, triggers: bool = True) -> None:
    """Tell the UI that to-dos changed and refresh the Ideas the deterministic triggers produce (in the
    background: :meth:`~ordnung.ingest.worker.IngestWorker.refresh_ideas`)."""
    if item_id is None:
        ctx.bus.publish("item.updated")
    else:
        ctx.bus.publish("item.updated", item_id=item_id)
    if triggers:
        ctx.worker.refresh_ideas()
