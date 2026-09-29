"""Calendar export: events per open dated item and contract decision, alarms, stable UIDs, time zones."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from icalendar import Calendar

from ordnung import clock
from ordnung.calendar.ics import CHECK_PREFIX, build_ics, mark_exported, needs_check
from ordnung.db.store import NotFoundError, Store
from ordnung.models import ComputationReceipt, Evidence, Item

TODAY = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def _doc(store: Store, label: str, **fields: Any) -> str:
    doc = store.add_document(
        sha256=hashlib.sha256(label.encode()).hexdigest(),
        filename=f"{label}.pdf",
        mime="application/pdf",
        file_path=f"files/{label}.pdf",
    )
    store.update_document(doc.id, status="processed", **fields)
    return doc.id


def _item(store: Store, **fields: Any) -> str:
    fields.setdefault("grounding", "verified")
    fields.setdefault("created_at", "2026-09-01T08:00:00Z")
    fields.setdefault("updated_at", "2026-09-01T08:00:00Z")
    return store.add_item(**fields).id


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    store.save_profile({"name": "Sam Rivera", "timezone": "Europe/Berlin"})
    fa = store.add_party(name="Finanzamt Musterstadt", kind="tax_office", region="NW").id
    funk = store.add_party(name="FunkNetz Mobile", kind="telecom").id
    fake = store.add_party(name="Beitrags Zahlungszentrale", kind="public_broadcaster").id
    tax = _doc(store, "tax", kind="tax_assessment", title="Tax assessment 2025", party_id=fa)
    scam = _doc(store, "scam", kind="other", party_id=fake, warnings=["Foreign IBAN — possible scam."])
    ids = {
        "deadline": _item(
            store,
            kind="deadline",
            title="Objection deadline",
            action="Send your objection (Einspruch)",
            consequence="The assessment becomes final.",
            due_date="2026-10-19",
            send_by="2026-10-13",
            doc_id=tax,
            computation=ComputationReceipt(due_date="2026-10-19", summary="One month after delivery."),
        ),
        "appointment": _item(
            store,
            kind="appointment",
            title="Ausländerbehörde appointment",
            due_date="2026-10-07",
            due_time="10:30",
            location="Rathaus, Raum 3",
        ),
        "payment": _item(
            store,
            kind="payment",
            title="Pay TechMarkt reminder",
            due_date="2026-10-01",
            amount=94.99,
            currency="EUR",
            grounding="unverified",
            evidence=[Evidence(doc_id=tax, quote="94,99 €")],
        ),
        "manual": _item(
            store,
            kind="task",
            title="Buy stamps",
            due_date="2026-10-02",
            origin="manual",
            grounding="unverified",
        ),
        "done": _item(store, kind="task", title="Old task", due_date="2026-10-10", status="done"),
        "undated": _item(store, kind="task", title="Sometime"),
        "scam": _item(
            store, kind="payment", title="Pay broadcasting fee", due_date="2026-10-05", doc_id=scam
        ),
    }
    ids["contract"] = store.add_contract(
        name="FunkNetz Mobil",
        category="mobile",
        party_id=funk,
        concluded_date="2025-01-10",
        start_date="2025-01-15",
        initial_term_months=24,
        notice_value=1,
        notice_unit="months",
        cost_amount=29.99,
        cost_interval="monthly",
    ).id
    store.add_contract(name="Mietvertrag", category="rent", party_id=funk, start_date="2024-03-01")
    return ids


def _events(data: bytes) -> dict[str, Any]:
    calendar = Calendar.from_ical(data)
    return {str(event["uid"]): event for event in calendar.walk("VEVENT")}


def _triggers(event: Any) -> list[timedelta]:
    return sorted(alarm.decoded("trigger") for alarm in event.walk("VALARM"))


def test_calendar_has_one_event_per_open_dated_item_and_contract_decision(
    store: Store, ids: dict[str, str]
) -> None:
    data = build_ics(store)
    calendar = Calendar.from_ical(data)
    assert str(calendar["x-wr-calname"]) == "Ordnung"
    events = _events(data)
    contract = ids["contract"]
    assert set(events) == {
        f"{ids['deadline']}@ordnung.local",
        f"{ids['appointment']}@ordnung.local",
        f"{ids['payment']}@ordnung.local",
        f"{ids['manual']}@ordnung.local",
        f"{contract}-send-by@ordnung.local",
        f"{contract}-cancel-by@ordnung.local",
    }
    send = events[f"{contract}-send-by@ordnung.local"]
    cancel = events[f"{contract}-cancel-by@ordnung.local"]
    assert send.decoded("dtstart") == date(2026, 12, 8) and "FunkNetz Mobil" in str(send["summary"])
    assert cancel.decoded("dtstart") == date(2026, 12, 14)
    assert "€29.99 a month" in str(cancel["description"])


def test_all_day_event_with_description_and_alarms(store: Store, ids: dict[str, str]) -> None:
    event = _events(build_ics(store))[f"{ids['deadline']}@ordnung.local"]
    assert str(event["summary"]) == "⚑ Objection deadline"
    assert event.decoded("dtstart") == date(2026, 10, 19)
    assert event.decoded("dtend") == date(2026, 10, 20)
    description = str(event["description"])
    for expected in (
        "What to do: Send your objection (Einspruch)",
        "Post it by Tue 13 Oct 2026 so it arrives by Mon 19 Oct 2026.",
        "If ignored: The assessment becomes final.",
        "Why this date: One month after delivery.",
        "With: Finanzamt Musterstadt",
        "Not legal advice.",
    ):
        assert expected in description
    # deadline reminders 14/7/3/1 days before at 09:00, plus the send-by day (6 days before) at 09:00
    assert _triggers(event) == sorted(timedelta(days=-days, hours=9) for days in (14, 7, 6, 3, 1))


def test_timed_event_is_timezone_correct(store: Store, ids: dict[str, str]) -> None:
    data = build_ics(store)
    event = _events(data)[f"{ids['appointment']}@ordnung.local"]
    start = event.decoded("dtstart")
    assert isinstance(start, datetime)
    assert start.utcoffset() == timedelta(hours=2)  # CEST
    assert (start.hour, start.minute) == (10, 30)
    assert event["dtstart"].params["TZID"] == "Europe/Berlin"
    assert event.decoded("dtend") - start == timedelta(hours=1)
    assert str(event["location"]) == "Rathaus, Raum 3"
    assert _triggers(event) == [timedelta(days=-2), timedelta(hours=-1)]
    assert [tz["tzid"] for tz in Calendar.from_ical(data).walk("VTIMEZONE")] == ["Europe/Berlin"]


def test_alarms_follow_the_profile(store: Store, ids: dict[str, str]) -> None:
    store.save_profile({"name": "Sam", "reminder_days": {"payment": [3], "deadline": []}})
    events = _events(build_ics(store))
    assert _triggers(events[f"{ids['payment']}@ordnung.local"]) == [timedelta(days=-3, hours=9)]
    assert _triggers(events[f"{ids['deadline']}@ordnung.local"]) == [timedelta(days=-6, hours=9)]
    assert _triggers(events[f"{ids['manual']}@ordnung.local"]) == []


def test_unconfirmed_dates_are_marked_for_checking(store: Store, ids: dict[str, str]) -> None:
    events = _events(build_ics(store))
    payment = events[f"{ids['payment']}@ordnung.local"]
    assert str(payment["summary"]) == f"{CHECK_PREFIX}€ Pay TechMarkt reminder"
    assert "Please check this date" in str(payment["description"])
    assert "Amount: €94.99" in str(payment["description"])
    assert not str(events[f"{ids['manual']}@ordnung.local"]["summary"]).startswith(CHECK_PREFIX)


def test_needs_check_rules() -> None:
    base = Item(id="itm_x", kind="deadline", title="x", created_at="t", updated_at="t", grounding="verified")
    assert not needs_check(base)
    assert needs_check(base.model_copy(update={"grounding": "unverified"}))
    assert needs_check(
        base.model_copy(update={"computation": ComputationReceipt(due_date=None, confidence="low")})
    )
    assert needs_check(
        base.model_copy(update={"evidence": [Evidence(doc_id="d", quote="q", value_consistent=False)]})
    )
    assert not needs_check(base.model_copy(update={"grounding": "user", "computation": None}))
    assert not needs_check(base.model_copy(update={"grounding": "unverified", "origin": "manual"}))


def test_export_is_stable(store: Store, ids: dict[str, str]) -> None:
    assert build_ics(store) == build_ics(store)


def test_include_done_and_single_item(store: Store, ids: dict[str, str]) -> None:
    events = _events(build_ics(store, include_done=True))
    done = events[f"{ids['done']}@ordnung.local"]
    assert str(done["summary"]).startswith("✓ ")
    assert _triggers(done) == []
    assert f"{ids['scam']}@ordnung.local" not in events
    single = _events(build_ics(store, only_item_id=ids["appointment"]))
    assert list(single) == [f"{ids['appointment']}@ordnung.local"]
    with pytest.raises(NotFoundError):
        build_ics(store, only_item_id="itm_missing0000")
    with pytest.raises(ValueError, match="no date"):
        build_ics(store, only_item_id=ids["undated"])


def test_mark_exported(store: Store) -> None:
    stamp = mark_exported(store)
    assert store.get_meta("last_calendar_export_at") == stamp
    assert datetime.fromisoformat(stamp).tzinfo is not None


def test_an_open_one_off_that_was_history_when_filed_is_left_out(store: Store) -> None:
    """Walkthrough of phase 2: the export carried a 2025 security deposit and a 2025 meter reading as open
    dates — both long past when their letters were read (a backfilled archive), so no dates to keep."""
    deposit = _item(
        store,
        kind="payment",
        title="Security deposit",
        due_date="2025-10-01",
        direction="out",
        filed_on="2026-09-20",
    )
    current = _item(
        store, kind="payment", title="Rent", due_date="2026-10-01", direction="out", filed_on="2026-09-20"
    )
    uids = set(_events(build_ics(store)))
    assert f"{deposit}@ordnung.local" not in uids and f"{current}@ordnung.local" in uids
    store.update_item(deposit, status="done")  # a done one stays in an export that includes done dates
    assert f"{deposit}@ordnung.local" in set(_events(build_ics(store, include_done=True)))


def test_an_invoice_payment_a_payment_reminder_took_over_is_left_out(store: Store) -> None:
    """As on the agenda: pay the reminder, not both — so the calendar (and calendar sync) gets one."""
    party = store.add_party(name="TechMarkt Online", kind="retailer").id
    case = store.add_case(title="Invoice TM-2026-0048213", party_id=party).id
    number = [{"label": "Rechnungsnummer", "value": "TM-2026-0048213"}]
    invoice = _doc(
        store,
        "invoice",
        kind="invoice",
        doc_date="2026-08-20",
        party_id=party,
        case_id=case,
        references=number,
    )
    reminder = _doc(
        store,
        "dunning",
        kind="dunning",
        doc_date="2026-09-18",
        party_id=party,
        case_id=case,
        references=number,
    )
    paid_by_invoice = _item(
        store,
        kind="payment",
        title="Pay TechMarkt invoice",
        due_date="2026-10-03",
        amount=89.99,
        doc_id=invoice,
        direction="out",
    )
    by_reminder = _item(
        store,
        kind="payment",
        title="Pay the reminder",
        due_date="2026-10-06",
        amount=94.99,
        doc_id=reminder,
        direction="out",
    )
    uids = set(_events(build_ics(store)))
    assert f"{by_reminder}@ordnung.local" in uids
    assert f"{paid_by_invoice}@ordnung.local" not in uids
    store.trash_document(reminder)  # the reminder goes to the trash: the invoice's payment is back
    assert f"{paid_by_invoice}@ordnung.local" in set(_events(build_ics(store)))


def test_an_emailed_bill_is_one_event_and_leaves_with_the_bill_paid(store: Store) -> None:
    """An e-mail repeating its attached bill's payment: the bill is the one to pay, so the calendar (and
    calendar sync, which sends these events) carries one "Pay" event — and the e-mail's copy doesn't stay
    behind, reminding of a bill already paid, once the bill's to-do is done."""
    from helpers_secretary import add_emailed_bill

    bill = add_emailed_bill(store, due="2026-10-15")
    uids = set(_events(build_ics(store)))
    assert f"{bill['bill_payment']}@ordnung.local" in uids
    assert f"{bill['email_payment']}@ordnung.local" not in uids
    store.update_item(bill["bill_payment"], status="done")
    uids = set(_events(build_ics(store)))
    assert f"{bill['email_payment']}@ordnung.local" not in uids
    assert f"{bill['bill_payment']}@ordnung.local" not in uids
    store.trash_document(bill["bill"])  # the bill goes: the e-mail's payment is the one to pay again
    assert f"{bill['email_payment']}@ordnung.local" in set(_events(build_ics(store)))
