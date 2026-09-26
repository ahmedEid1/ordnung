"""Money sums never mix currencies (round 2, R2-WEB-1): the dashboard's "due this month" is a sum
in euros, so a dollar invoice must not be added to it as if it were euros."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from helpers_secretary import TODAY, add_item, seed_ledger
from ordnung import clock
from ordnung.db.store import Store
from ordnung.views import dashboard


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ORDNUNG_TODAY", raising=False)
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def test_due_this_month_counts_only_euros(store: Store) -> None:
    seed_ledger(store)
    before = dashboard(store, TODAY).money.due_this_month
    saas = add_item(
        store,
        kind="payment",
        title="Pay the hosting invoice",
        due_date="2026-09-30",
        amount=50.0,
        currency="USD",
        direction="out",
    )
    money = dashboard(store, TODAY).money
    assert money.due_this_month == before  # not before + 50
    assert saas in [item.id for item in money.upcoming_payments]  # still listed, with its currency
