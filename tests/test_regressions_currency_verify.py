"""Money totals keep currencies apart: regression tests from the review rounds."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from helpers_secretary import TODAY, add_item
from ordnung import clock
from ordnung.db.store import Store
from ordnung.models import Recurrence
from ordnung.secretary.brief import agenda_text, build_agenda
from ordnung.views import dashboard, timeline

MONTHLY = Recurrence(interval=1, unit="months")


# --------------------------------------------------------------------------------------------------
# R2-MAIL-1: rules inside an at-rule no longer count at all
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ORDNUNG_TODAY", raising=False)
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def test_the_agenda_payment_total_counts_only_euros(store: Store, pinned_today: None) -> None:
    """R2-WEB-1 fixed the web totals and views.money_summary.due_this_month, but the secretary's agenda
    (brief.build_agenda) still summed "payments this month" over every currency and showed it as
    euros: Today's secretary note read "Payments this month: €169.99" for €119.99 + $50."""
    add_item(
        store, kind="payment", title="Pay the rent", due_date="2026-09-30", amount=119.99, direction="out"
    )
    add_item(
        store,
        kind="payment",
        title="Pay the hosting invoice",
        due_date="2026-09-30",
        amount=50.0,
        currency="USD",
        direction="out",
    )
    agenda = build_agenda(store, TODAY)
    assert len(agenda.payments_this_month) == 2
    assert agenda.payments_total == pytest.approx(119.99)
    assert agenda.payments_total_other_currencies == {"USD": 50.0}
    text = agenda_text(agenda)
    assert "€169.99" not in text and "€50" not in text
    assert "€119.99 and 50.00 USD in 2 payments" in text


def test_the_timeline_keeps_each_payments_currency(store: Store, pinned_today: None) -> None:
    """R2-WEB-1 fixed "To pay · next 30 days" on Today, which links to the Timeline; there every entry's
    amount is shown with formatMoney (euros) and each month's "· To pay" sums all amounts, because the
    API's timeline entries carry no currency. A $50 invoice is "€50.00" and adds €50 to the month."""
    usd = add_item(
        store,
        kind="payment",
        title="Pay the hosting invoice",
        due_date="2026-09-30",
        amount=50.0,
        currency="USD",
        direction="out",
    )
    entries = {
        entry.id: entry for entry in timeline(store, date(2026, 9, 1), date(2026, 10, 31), today=TODAY)
    }
    assert entries[usd].model_dump().get("currency") == "USD"


def test_fixed_costs_per_month_count_only_euros(store: Store, pinned_today: None) -> None:
    """The Greeting's second stat, "Fixed costs €…/month", is money_summary.fixed_costs_monthly: the
    monthly cost of every active contract added up whatever its cost_currency, so a $20 subscription
    is €20 of it (and of by_category). R2-WEB-1 made due_this_month euros-only right above it."""
    store.add_contract(name="Mobile phone", category="mobile", cost_amount=10.0, cost_interval="monthly")
    store.add_contract(name="Cloud storage", cost_amount=20.0, cost_currency="USD", cost_interval="monthly")
    money = dashboard(store, TODAY).money
    assert money.fixed_costs_monthly == pytest.approx(10.0)
    assert money.fixed_costs_monthly_other_currencies == {"USD": 20.0}
    assert money.by_category == {"mobile": 10.0}
