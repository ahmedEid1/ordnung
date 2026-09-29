"""Contracts carry ``cancellable`` and ``cancel_hint`` (worked out on read, never stored): the
broadcasting fee, obligations towards authorities and a job are no consumer cancellation, so the web
app hides "Draft cancellation" and says why instead."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from ordnung import clock
from ordnung.api.routes.common import (
    BROADCASTING_FEE_HINT,
    EMPLOYMENT_HINT,
    STATUTORY_HINT,
    cancellability,
)
from ordnung.models import Contract, Party
from test_api_support import TODAY, api_for

NOW = "2026-09-01T00:00:00Z"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def _contract(name: str, category: str = "other") -> Contract:
    return Contract.model_validate(
        {"id": "ctr_x", "name": name, "category": category, "created_at": NOW, "updated_at": NOW}
    )


def _party(kind: str, name: str = "Someone") -> Party:
    return Party.model_validate(
        {"id": "pty_x", "name": name, "kind": kind, "created_at": NOW, "updated_at": NOW}
    )


@pytest.mark.parametrize(
    ("contract", "party", "expected"),
    [
        (_contract("FunkNetz Allnet L", "mobile"), _party("telecom"), (True, None)),
        (_contract("Gym", "gym"), None, (True, None)),
        (_contract("Krankenkasse", "insurance"), _party("health_insurer"), (True, None)),
        (_contract("Beitrag"), _party("public_broadcaster"), (False, BROADCASTING_FEE_HINT)),
        (_contract("Rundfunkbeitrag"), None, (False, BROADCASTING_FEE_HINT)),
        (
            _contract("Household fee"),
            _party("other", "ARD ZDF Deutschlandradio Beitragsservice"),
            (False, BROADCASTING_FEE_HINT),
        ),
        (_contract("Dog tax"), _party("authority"), (False, STATUTORY_HINT)),
        (_contract("Church tax"), _party("tax_office"), (False, STATUTORY_HINT)),
        (_contract("Werkstudent", "employment"), _party("employer"), (False, EMPLOYMENT_HINT)),
    ],
)
def test_cancellability(contract: Contract, party: Party | None, expected: tuple[bool, str | None]) -> None:
    assert cancellability(contract, party) == expected


def test_hints_say_why_in_plain_words() -> None:
    assert "Rundfunkbeitrag" in BROADCASTING_FEE_HINT and "de-register" in BROADCASTING_FEE_HINT
    assert "§ 623 BGB" in EMPLOYMENT_HINT and "sign" in EMPLOYMENT_HINT
    assert "object" in STATUTORY_HINT


async def test_contract_responses_say_whether_it_can_be_cancelled(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        store = api.ctx.store
        broadcaster = store.add_party(
            name="ARD ZDF Deutschlandradio Beitragsservice", kind="public_broadcaster"
        )
        employer = store.add_party(name="Muster Tech", kind="employer")
        gym = store.add_party(name="FitWell", kind="gym")
        fee = store.add_contract(
            name="Rundfunkbeitrag", party_id=broadcaster.id, cost_amount=55.08, cost_interval="quarterly"
        )
        job = store.add_contract(
            name="Werkstudent", category="employment", party_id=employer.id, is_consumer=False
        )
        membership = store.add_contract(
            name="FitWell Flex",
            category="gym",
            party_id=gym.id,
            start_date="2025-01-01",
            initial_term_months=12,
        )

        listed = {c["id"]: c for c in (await api.client.get("/api/contracts")).json()}
        assert (listed[fee.id]["cancellable"], listed[fee.id]["cancel_hint"]) == (
            False,
            BROADCASTING_FEE_HINT,
        )
        assert (listed[job.id]["cancellable"], listed[job.id]["cancel_hint"]) == (False, EMPLOYMENT_HINT)
        assert (listed[membership.id]["cancellable"], listed[membership.id]["cancel_hint"]) == (True, None)
        assert listed[membership.id]["computed"] is not None

        patched = await api.client.patch(f"/api/contracts/{fee.id}", json={"cost_amount": 55.08})
        assert patched.status_code == 200
        assert (patched.json()["cancellable"], patched.json()["cancel_hint"]) == (
            False,
            BROADCASTING_FEE_HINT,
        )

        party = (await api.client.get(f"/api/parties/{broadcaster.id}")).json()
        assert [(c["id"], c["cancellable"]) for c in party["contracts"]] == [(fee.id, False)]

        # worked out on read: never stored, never writable
        columns = {row[1] for row in store._conn().execute("PRAGMA table_info(contracts)")}
        assert not {"cancellable", "cancel_hint"} & columns
        with pytest.raises(ValueError, match="cancellable"):
            store.update_contract(fee.id, cancellable=True)
        refused = await api.client.patch(f"/api/contracts/{fee.id}", json={"cancellable": True})
        assert refused.status_code == 422


def test_the_store_decodes_contracts_with_the_defaults(data_dir: Path) -> None:
    from ordnung.config import Paths
    from ordnung.db.store import Store

    with Store.open(Paths(data_dir)) as store:
        stored = store.add_contract(name="Rundfunkbeitrag")
        assert (stored.cancellable, stored.cancel_hint) == (True, None)
        assert store.get_contract(stored.id) == stored


async def test_a_contract_says_when_its_cancellation_was_sent(data_dir: Path) -> None:
    """Walkthrough of phase 2: after the FunkNetz cancellation was marked as sent, its card still asked the
    person to decide and offered "Draft cancellation". The contract carries the sent letter (worked out on
    read, never stored): the latest cancellation that names it and was marked as sent."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        phone = store.add_contract(name="FunkNetz Smart M", category="mobile")
        store.add_draft(kind="cancellation", contract_id=phone.id, status="final")
        listed = {c["id"]: c for c in (await api.client.get("/api/contracts")).json()}
        assert listed[phone.id]["cancellation_sent"] is None
        sent = store.add_draft(
            kind="cancellation",
            contract_id=phone.id,
            status="sent",
            sent_at="2026-09-28T09:00:00Z",
            sent_channel="registered_letter",
        )
        listed = {c["id"]: c for c in (await api.client.get("/api/contracts")).json()}
        assert listed[phone.id]["cancellation_sent"] == {
            "draft_id": sent.id,
            "sent_on": "2026-09-28",
            "channel": "registered_letter",
        }
        # once the contract is closed, nothing waits any more
        store.update_contract(phone.id, status="cancelled")
        listed = {c["id"]: c for c in (await api.client.get("/api/contracts")).json()}
        assert listed[phone.id]["cancellation_sent"] is None
        columns = {row[1] for row in store._conn().execute("PRAGMA table_info(contracts)")}
        assert "cancellation_sent" not in columns
