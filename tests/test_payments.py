"""How a payment is made (:mod:`ordnung.payments`): the same cases as the web app's mirror
(``web/src/lib/payments.ts``, ``paysOnSite`` in ``web/src/features/document/item-meta.ts``)."""

from __future__ import annotations

from typing import Any

import pytest

from ordnung.models import Item
from ordnung.payments import is_collected_or_incoming, is_direct_debit, pays_on_site

STAMPS = {"created_at": "2026-09-28T08:00:00Z", "updated_at": "2026-09-28T08:00:00Z"}


def payment(**fields: Any) -> Item:
    return Item.model_validate({"id": "itm_x", "kind": "payment", "title": "Fee", **STAMPS, **fields})


@pytest.mark.parametrize(
    ("action", "on_site"),
    [
        ("Pay the 4,50 € in fees at the service desk or the payment machine.", True),
        ("Pay the €100 fee on site at the appointment by girocard (cash is not accepted).", True),
        ("Gebühr vor Ort mit EC-Karte bezahlen.", True),
        ("Transfer 55.08 € to the Beitragsservice, or pay in cash.", False),  # a transfer first
        ("Transfer the amount by the deadline.", False),
        (None, False),
    ],
)
def test_pays_on_site(action: str | None, on_site: bool) -> None:
    """UI audit R1-backend-8: a fee paid by card at the appointment has no bank "send by"."""
    assert pays_on_site(payment(action=action)) is on_site


def test_nothing_else_is_paid_on_site() -> None:
    at_desk = "Pay at the service desk."
    assert not pays_on_site(payment(action=at_desk, direction="in"))  # money coming in
    assert not pays_on_site(payment(title="SEPA-Lastschrift", action=at_desk))  # collected by the sender
    assert not pays_on_site(payment(kind="task", action=at_desk))
    debit = payment(action="Ensure sufficient funds for the direct debit.")
    assert is_direct_debit(debit) and is_collected_or_incoming(debit) and not pays_on_site(debit)
