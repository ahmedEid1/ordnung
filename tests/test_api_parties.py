"""The People & organisations drawer's data: which open to-dos are set aside instead of listed as due."""

from __future__ import annotations

import pytest

from helpers_secretary import TODAY, add_doc, add_item
from ordnung.api.routes.parties import get_party
from ordnung.db.store import Store
from ordnung.secretary import triggers


def _party(store: Store) -> str:
    return store.add_party(name="TechMarkt Online GmbH", kind="retailer").id


def test_a_party_sets_aside_the_invoice_payment_its_reminder_took_over(store: Store) -> None:
    party = _party(store)
    case = store.add_case(title="Invoice TM-4711", party_id=party, reference="TM-4711")
    refs = [{"label": "Rechnungsnummer", "value": "TM-4711"}]
    invoice = add_doc(
        store,
        "invoice",
        kind="invoice",
        doc_date="2026-08-20",
        party_id=party,
        case_id=case.id,
        references=refs,
    )
    reminder = add_doc(
        store,
        "reminder",
        kind="dunning",
        doc_date="2026-09-10",
        party_id=party,
        case_id=case.id,
        references=refs,
    )
    old = add_item(
        store,
        kind="payment",
        title="Pay the invoice",
        due_date="2026-09-03",
        filed_on="2026-08-21",
        amount=89.99,
        direction="out",
        party_id=party,
        doc_id=invoice,
    )
    new = add_item(
        store,
        kind="payment",
        title="Pay the reminder",
        due_date="2026-09-30",
        filed_on="2026-09-11",
        amount=94.99,
        direction="out",
        party_id=party,
        doc_id=reminder,
    )

    detail = get_party(party, store, TODAY)

    assert {item.id for item in detail.items} == {old, new}  # the list stays complete
    assert [(a.item_id, a.reason, a.replaced_by) for a in detail.set_aside] == [(old, "replaced", reminder)]

    store.trash_document(reminder)  # the reminder is gone: the invoice payment is due again
    assert get_party(party, store, TODAY).set_aside == []


def test_dates_that_were_history_when_the_letter_was_read_are_set_aside(store: Store) -> None:
    party = _party(store)
    lease = add_doc(store, "lease", kind="rent_lease", doc_date="2025-09-15", party_id=party)
    deposit = add_item(
        store,
        kind="payment",
        title="Security deposit (Kaution)",
        due_date="2025-10-01",
        filed_on=TODAY.isoformat(),
        amount=1560.0,
        direction="out",
        party_id=party,
        doc_id=lease,
    )
    rent = add_item(
        store,
        kind="payment",
        title="Monthly rent",
        due_date="2025-10-01",
        filed_on=TODAY.isoformat(),
        amount=640.0,
        direction="out",
        recurrence={"interval": 1, "unit": "months"},
        party_id=party,
        doc_id=lease,
    )
    late = add_item(
        store,
        kind="deadline",
        title="Return the books",
        due_date="2026-09-25",
        filed_on="2026-09-20",
        party_id=party,
        doc_id=lease,
    )
    done = add_item(
        store,
        kind="task",
        title="Sign the lease",
        due_date="2025-09-01",
        filed_on=TODAY.isoformat(),
        status="done",
        party_id=party,
        doc_id=lease,
    )

    detail = get_party(party, store, TODAY)

    assert [(a.item_id, a.reason) for a in detail.set_aside] == [(deposit, "history")]
    shown = {item.id for item in detail.items}
    assert {rent, late, done} <= shown  # a schedule, a really overdue date and a done one stay as they are


def test_to_dos_of_a_letter_with_scam_signs_are_set_aside(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    party = _party(store)
    letter = add_doc(
        store, "fake", kind="invoice", doc_date="2026-09-20", party_id=party, direction="incoming"
    )
    pay = add_item(
        store,
        kind="payment",
        title="Pay now",
        due_date="2026-10-01",
        filed_on="2026-09-21",
        amount=499.0,
        direction="out",
        party_id=party,
        doc_id=letter,
    )
    monkeypatch.setattr(
        triggers, "_scam_reasons", lambda _store, doc, _party: ["new IBAN"] if doc.id == letter else []
    )

    assert [(a.item_id, a.reason) for a in get_party(party, store, TODAY).set_aside] == [(pay, "suspicious")]
