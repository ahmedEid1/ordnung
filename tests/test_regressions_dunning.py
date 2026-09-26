"""Which payments a payment reminder (Mahnung) takes over (round 2, R2-DUN-1).

This is worked out on read (``link.reminder_covers`` via ``Ledger.covering_reminders``). A reminder
used to cover *every* non-reminder letter of its thread that mentions its invoice number, with no date
check: a letter written *after* the reminder that refers to the invoice (a corrected invoice,
"Korrektur zur Rechnung RE-4711") was treated as superseded, and its payment left Today, To-pay and
the Ideas — even when the reminder itself was already paid.
"""

from __future__ import annotations

from datetime import date

from helpers_secretary import add_doc
from ordnung.db.store import Store
from ordnung.models import DateSpec, Recurrence
from ordnung.secretary.triggers import Ledger, run_triggers
from ordnung.views import dashboard

TODAY = date(2026, 9, 28)


def test_a_later_invoice_that_mentions_the_reminded_number_stays_on_today(store: Store) -> None:
    """A corrected invoice dated after the (already paid) reminder is a new demand, not an invoice the
    reminder took over: its payment stays on Today."""
    party = store.add_party(name="Stadtwerke Musterstadt", kind="utility")
    case = store.add_case(title="Invoice RE-4711", party_id=party.id)
    reminder = add_doc(
        store,
        "reminder",
        kind="dunning",
        title="Payment reminder RE-4711",
        doc_date="2026-08-20",
        party_id=party.id,
        case_id=case.id,
        references=[{"label": "Rechnungsnummer", "value": "RE-4711"}],
    )
    corrected = add_doc(
        store,
        "corrected",
        kind="invoice",
        title="Corrected invoice for RE-4711",
        doc_date="2026-09-20",
        party_id=party.id,
        case_id=case.id,
        references=[
            {"label": "Rechnungsnummer", "value": "RE-4711-K"},
            {"label": "Bezug", "value": "RE-4711"},
        ],
    )
    store.add_item(
        kind="payment",
        title="Pay the reminder",
        doc_id=reminder,
        party_id=party.id,
        due_date="2026-08-30",
        amount=120.0,
        direction="out",
        status="done",  # the reminder was paid
    )
    bill = store.add_item(
        kind="payment",
        title="Pay the corrected invoice",
        doc_id=corrected,
        party_id=party.id,
        due_date="2026-10-05",
        amount=80.0,
        direction="out",
    )

    ledger = Ledger(store, TODAY)
    assert not ledger.is_superseded_by_reminder(bill)
    shown = dashboard(store, TODAY)
    assert bill.id in {item.id for item in [*shown.attention, *shown.upcoming]}


def test_a_reminder_about_arrears_does_not_hide_the_bills_recurring_payments(store: Store) -> None:
    """An annual electricity bill asks for a back payment (one-off) and sets the new monthly advance
    payment (recurring). A payment reminder about the bill takes over the back payment — pay the
    reminder, not both — but not the advance payments still to come: they stay on Today and in the
    Ideas."""
    party = store.add_party(name="Stadtwerke Musterstadt", kind="utility")
    case = store.add_case(title="Annual bill RE-4711", party_id=party.id)
    references = [{"label": "Rechnungsnummer", "value": "RE-4711"}]
    bill = add_doc(
        store,
        "annual-bill",
        kind="utility_bill",
        title="Annual electricity bill 2025/26",
        doc_date="2026-08-20",
        party_id=party.id,
        case_id=case.id,
        references=references,
    )
    reminder = add_doc(
        store,
        "bill-reminder",
        kind="dunning",
        title="Payment reminder RE-4711",
        doc_date="2026-09-15",
        party_id=party.id,
        case_id=case.id,
        references=references,
    )
    back_payment = store.add_item(
        kind="payment",
        title="Back payment",
        doc_id=bill,
        party_id=party.id,
        due_date="2026-09-05",
        amount=120.0,
    )
    advance = store.add_item(
        kind="payment",
        title="Monthly advance payment",
        doc_id=bill,
        party_id=party.id,
        due_date="2026-10-01",
        date_spec=DateSpec(type="fixed", date="2026-10-01", nature="payment"),
        recurrence=Recurrence(interval=1, unit="months"),
        amount=55.0,
        direction="out",
    )
    reminded = store.add_item(
        kind="payment",
        title="Pay the reminder",
        doc_id=reminder,
        party_id=party.id,
        due_date="2026-09-30",
        amount=125.0,
    )

    ledger = Ledger(store, TODAY)
    assert ledger.is_superseded_by_reminder(back_payment)
    assert not ledger.is_superseded_by_reminder(advance)
    shown = {item.id for item in [*dashboard(store, TODAY).attention, *dashboard(store, TODAY).upcoming]}
    assert advance.id in shown and reminded.id in shown
    assert back_payment.id not in shown
    soon = {idea.refs[0].id for idea in run_triggers(store, TODAY)["deadline_soon"]}
    assert advance.id in soon
