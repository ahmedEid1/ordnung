"""Helpers shared by the route modules: lookups that 404, ISO date fields, contract dates computed on
read, and announcing ledger changes (bus event + deterministic triggers)."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, TypeVar

from fastapi import HTTPException, status
from pydantic import AfterValidator

from ordnung.app_context import AppContext
from ordnung.db.store import Store
from ordnung.ingest.pipeline import run_triggers
from ordnung.llm.replay import ReplayBackend
from ordnung.models import Contract, Party, Profile
from ordnung.secretary.triggers import contract_computation

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


def with_computation(contract: Contract, party: Party | None, today: date, profile: Profile) -> Contract:
    """The contract with its cancellation dates recomputed by the rules engine for ``today`` and
    whether it can be cancelled (:func:`cancellability`)."""
    cancellable, hint = cancellability(contract, party)
    return contract.model_copy(
        update={
            "computed": contract_computation(contract, party, today, profile),
            "cancellable": cancellable,
            "cancel_hint": hint,
        }
    )


def contracts_with_computations(store: Store, contracts: list[Contract], today: date) -> list[Contract]:
    """Contracts with fresh computations (parties looked up once each)."""
    profile = store.get_profile()
    parties: dict[str, Party | None] = {}
    result = []
    for contract in contracts:
        party_id = contract.party_id
        if party_id is not None and party_id not in parties:
            parties[party_id] = store.get_party(party_id)
        party = parties.get(party_id) if party_id else None
        result.append(with_computation(contract, party, today, profile))
    return result


def replay_only(ctx: AppContext) -> bool:
    """The model backend only replays recordings (the zero-token demo): nothing new can be asked."""
    backend = ctx.llm.backend
    return isinstance(backend, ReplayBackend) and backend.fallback is None


async def ledger_changed(ctx: AppContext, *, item_id: str | None = None, triggers: bool = True) -> None:
    """Tell the UI that to-dos changed and refresh the Ideas the deterministic triggers produce."""
    if item_id is None:
        ctx.bus.publish("item.updated")
    else:
        ctx.bus.publish("item.updated", item_id=item_id)
    if triggers:
        await run_triggers(ctx)
