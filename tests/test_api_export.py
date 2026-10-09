"""Export letters over HTTP (``GET /api/documents.zip``): the choice is checked before anything is read,
and the export changes nothing."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from helpers_secretary import add_doc
from ordnung import clock
from test_api_support import TODAY, api_for

ZIP = "/api/documents.zip"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.mark.parametrize(
    "params",
    [
        {"year": "1899"},
        {"year": "2101"},
        {"year": "last"},
        {"until": "2026-05-31"},  # "until" goes with a year
        {"year": "2025", "until": "2025-12-31"},  # … and is a day of the next year
        {"year": "2025", "until": "2027-01-01"},
        {"year": "2025", "until": "2026-02-30"},
        {"tax": "maybe"},
    ],
)
async def test_a_choice_outside_the_rules_is_refused(data_dir: Path, params: dict[str, str]) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get(ZIP, params=params)
        assert response.status_code == 422, response.text


async def test_until_says_what_it_needs(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get(ZIP, params={"until": "2026-05-31"})
        assert response.json()["detail"] == "“until” goes with “year” and must be a day of the next year."


async def test_an_unknown_sender_is_not_found(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get(ZIP, params={"party_id": "pty_gone"})
        assert response.status_code == 404
        assert response.json()["detail"] == "This sender doesn't exist (any more)."


async def test_a_good_choice_is_answered_without_a_change(data_dir: Path) -> None:
    """Until the ZIP writer lands, a good choice is answered 501 — and, like the export, writes nothing."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        party = store.add_party(name="Finanzamt Musterstadt", kind="tax_office")
        add_doc(
            store, "tax", title="Tax assessment", doc_date="2026-03-14", party_id=party.id, tax_relevant=True
        )
        before = (store.counts(), store.list_activity(limit=50))
        response = await api.client.get(
            ZIP, params={"year": "2025", "until": "2026-05-31", "tax": "true", "party_id": party.id}
        )
        assert response.status_code == 501, response.text
        assert (store.counts(), store.list_activity(limit=50)) == before
