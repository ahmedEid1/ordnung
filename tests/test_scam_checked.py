"""A letter the person checked: *I checked — it's genuine* dismisses its scam warning (SPEC §21, "Scam checks").

While the letter shows the signs the person checked, its to-dos count as genuine wherever the app lists, counts,
reminds or covers: Today, the calendar file, the notification, the Ideas, the weekly session, a payment reminder or
an attached bill that takes over another payment. The warning keeps its identity (a new sign warns again) and a
GiroCode stays refused (ADR 0012). The warning names the days the letter asks for, so a flagged letter's dates are
never lost. The letters and the warning's words are made up here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from helpers_secretary import add_doc, add_emailed_bill, add_item
from ordnung import clock, views
from ordnung.calendar.ics import build_ics
from ordnung.db.store import Store
from ordnung.models import GiroCodeBlocked, PaymentDetails, Suggestion
from ordnung.notify import desktop
from ordnung.secretary.girocode_gate import item_girocode
from ordnung.secretary.triggers import Ledger, run_and_reconcile, run_triggers
from test_api_support import api_for

TODAY = date(2026, 11, 2)  # a Monday
#: A caution a genuine office prints: it holds a scam word ("phish"), so the letter shows a scam sign.
CAUTION = (
    "The office says it never asks for bank details by e-mail and warns of phishing e-mails in its name."
)
IBAN = "DE89370400440532013000"
OTHER_IBAN = "DE02120300000000202051"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def seed(store: Store) -> dict[str, str]:
    """Two tax assessments from offices whose account Ordnung knows, each with an objection deadline (Mon 9 Nov,
    send by Thu 5 Nov) and a payment (Fri 6 Nov): the ``genuine`` one carries a caution with a scam word, the
    ``control`` one none."""
    store.save_profile({"name": "Test Person", "language": "en", "region": "BE", "onboarded": True})
    ids: dict[str, str] = {}
    for label, warnings in (("genuine", [CAUTION]), ("control", [])):
        name = f"Finanzamt {label.title()}"
        party = store.add_party(name=name, kind="tax_office", ibans=[IBAN]).id
        doc = add_doc(
            store,
            label,
            kind="tax_assessment",
            area="tax",
            direction="incoming",
            title=f"Tax assessment ({label})",
            doc_date="2026-10-28",
            received_date="2026-10-30",
            party_id=party,
            warnings=warnings,
            payment=PaymentDetails(iban=IBAN, payee=name, amount=412.0, currency="EUR"),
        )
        ids[label] = doc
        ids[f"{label}_deadline"] = add_item(
            store,
            kind="deadline",
            title=f"Object to the assessment ({label})",
            doc_id=doc,
            party_id=party,
            area="tax",
            due_date="2026-11-09",
            send_by="2026-11-05",
            priority="high",
        )
        ids[f"{label}_payment"] = add_item(
            store,
            kind="payment",
            title=f"Pay the tax ({label})",
            doc_id=doc,
            party_id=party,
            area="tax",
            due_date="2026-11-06",
            amount=412.0,
            currency="EUR",
            direction="out",
        )
    return ids


def scam_idea(store: Store, doc_id: str, status: str | None = None) -> Suggestion:
    (idea,) = [
        idea
        for idea in store.list_suggestions()
        if idea.rule_id == "scam_warning"
        and any(ref.id == doc_id for ref in idea.refs)
        and (status is None or idea.status == status)
    ]
    return idea


def check(store: Store, doc_id: str) -> Suggestion:
    """What *I checked — it's genuine* does: dismiss the letter's scam warning; then the Ideas are refreshed."""
    run_and_reconcile(store, TODAY)
    idea = store.update_suggestion(scam_idea(store, doc_id, "new").id, status="dismissed")
    run_and_reconcile(store, TODAY)
    return idea


def actionable(store: Store) -> set[str]:
    return {item.id for item in Ledger(store, TODAY).actionable_items()}


def calendar_uids(store: Store) -> set[str]:
    text = build_ics(store).decode()
    return {line.removeprefix("UID:").split("@")[0] for line in text.splitlines() if line.startswith("UID:")}


def soon_ideas(store: Store) -> set[str]:
    """The to-dos with an open "do this by" Idea."""
    return {
        ref.id
        for idea in store.list_suggestions(status="new")
        if idea.rule_id == "deadline_soon"
        for ref in idea.refs
        if ref.type == "item"
    }


def notification_lines(store: Store) -> str:
    return "\n".join(thing.text for thing in desktop.today_things(store, TODAY))


def test_a_flagged_letter_is_set_aside_and_its_warning_names_the_days_it_asks_for(store: Store) -> None:
    ids = seed(store)
    run_and_reconcile(store, TODAY)
    ledger = Ledger(store, TODAY)
    for label in ("genuine_deadline", "genuine_payment"):
        item = next(item for item in ledger.items if item.id == ids[label])
        assert ledger.is_set_aside(item)
    assert actionable(store) == {ids["control_deadline"], ids["control_payment"]}
    idea = scam_idea(store, ids["genuine"])
    assert "It asks you to act by Fri 6 Nov and Mon 9 Nov (send by Thu 5 Nov)." in idea.body
    # the morning note's agenda reads the title and the day: both as they were
    assert idea.title == "Possible scam: Tax assessment (genuine)"
    assert idea.due_date == "2026-11-06"


def test_a_warning_names_no_day_that_has_passed_and_none_without_dated_to_dos(store: Store) -> None:
    ids = seed(store)
    store.update_item(ids["genuine_payment"], due_date="2026-10-20")
    run_and_reconcile(store, TODAY)
    assert "It asks you to act by Mon 9 Nov (send by Thu 5 Nov)." in scam_idea(store, ids["genuine"]).body
    store.update_item(ids["genuine_deadline"], status="done")
    run_and_reconcile(store, TODAY)
    assert "It asks you to act by" not in scam_idea(store, ids["genuine"]).body


def test_i_checked_it_brings_the_letters_reminders_back(store: Store) -> None:
    ids = seed(store)
    run_and_reconcile(store, TODAY)
    genuine = {ids["genuine_deadline"], ids["genuine_payment"]}
    before = scam_idea(store, ids["genuine"])
    assert not genuine & calendar_uids(store)
    assert not genuine & soon_ideas(store)
    assert "Object to the assessment (genuine)" not in notification_lines(store)

    check(store, ids["genuine"])

    ledger = Ledger(store, TODAY)
    assert ledger.scam_checked == frozenset({ids["genuine"]})
    assert genuine <= actionable(store)
    assert genuine <= calendar_uids(store)
    assert genuine <= soon_ideas(store)
    lines = notification_lines(store)
    assert "Object to the assessment (genuine)" in lines and "Pay the tax (genuine)" in lines
    today_page = json.dumps(views.dashboard(store, TODAY).model_dump(mode="json"))
    assert ids["genuine_deadline"] in today_page and ids["genuine_payment"] in today_page
    # the warning keeps its identity and stays dismissed; the letter's record keeps its signs
    after = scam_idea(store, ids["genuine"])
    assert (after.id, after.fingerprint, after.status) == (before.id, before.fingerprint, "dismissed")
    document = ledger.document(ids["genuine"])
    assert document is not None and ledger.scam_signs(document) == [CAUTION]
    # a check never unlocks a GiroCode (ADR 0012)
    payment = store.get_item(ids["genuine_payment"])
    assert payment is not None
    code = item_girocode(store, payment, TODAY)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"


def test_a_new_sign_after_the_check_warns_again_and_sets_the_dates_aside(store: Store) -> None:
    ids = seed(store)
    checked = check(store, ids["genuine"])
    store.update_document(
        ids["genuine"], payment=PaymentDetails(iban=OTHER_IBAN, payee="Finanzamt Genuine", amount=412.0)
    )
    run_and_reconcile(store, TODAY)
    fresh = scam_idea(store, ids["genuine"], "new")
    assert fresh.fingerprint != checked.fingerprint
    assert scam_idea(store, ids["genuine"], "dismissed").id == checked.id
    assert Ledger(store, TODAY).scam_checked == frozenset()
    assert actionable(store) == {ids["control_deadline"], ids["control_payment"]}
    assert not {ids["genuine_deadline"], ids["genuine_payment"]} & calendar_uids(store)


def test_undoing_the_check_sets_the_dates_aside_again(store: Store) -> None:
    ids = seed(store)
    checked = check(store, ids["genuine"])
    store.update_suggestion(checked.id, status="new")
    run_and_reconcile(store, TODAY)
    assert actionable(store) == {ids["control_deadline"], ids["control_payment"]}
    assert not {ids["genuine_deadline"], ids["genuine_payment"]} & soon_ideas(store)


def test_a_checked_payment_reminder_takes_over_its_invoices_payment(store: Store) -> None:
    """The money is never asked for twice: before the check the invoice is the one to pay (the reminder with
    scam signs takes nothing over), after it the reminder is."""
    party = store.add_party(name="TechMarkt Online", kind="retailer").id
    case = store.add_case(title="Invoice TM-2026-0048213", party_id=party).id
    number = [{"label": "Rechnungsnummer", "value": "TM-2026-0048213"}]
    common = {"direction": "incoming", "party_id": party, "case_id": case, "references": number}
    invoice = add_doc(store, "invoice", kind="invoice", doc_date="2026-10-01", **common)
    reminder = add_doc(store, "reminder", kind="dunning", doc_date="2026-10-28", warnings=[CAUTION], **common)
    pays = {"kind": "payment", "party_id": party, "currency": "EUR", "direction": "out"}
    by_invoice = add_item(
        store, title="Pay the invoice", due_date="2026-11-04", amount=89.99, doc_id=invoice, **pays
    )
    by_reminder = add_item(
        store, title="Pay the reminder", due_date="2026-11-06", amount=94.99, doc_id=reminder, **pays
    )
    assert actionable(store) == {by_invoice}
    check(store, reminder)
    assert actionable(store) == {by_reminder}
    assert calendar_uids(store) == {by_reminder}


def test_a_checked_attached_bill_takes_over_its_e_mails_payment(store: Store) -> None:
    party = store.add_party(name="FunkNetz", kind="telecom").id
    ids = add_emailed_bill(store, due="2026-11-06", party_id=party)
    store.update_document(ids["bill"], direction="incoming", warnings=[CAUTION])
    store.update_document(ids["email"], direction="incoming")
    assert actionable(store) == {ids["email_payment"]}
    check(store, ids["bill"])
    assert actionable(store) == {ids["bill_payment"]}


def test_the_weekly_session_lists_a_checked_letter_with_its_to_dos(store: Store) -> None:
    ids = seed(store)

    def note() -> str | None:
        session = views.weekly_session(store, TODAY)
        (step,) = [step for step in session.steps if step.id == "new"]
        return next(entry.note for entry in step.entries if entry.doc_id == ids["genuine"])

    assert note() == "Shows signs of a scam — don't pay or reply yet."
    check(store, ids["genuine"])
    assert note() == "2 open to-dos"


def test_the_calendar_idea_counts_the_dates_the_calendar_file_holds(store: Store) -> None:
    """ "Add your 4 dates" while the file holds 2 made the person believe every date reached their phone."""
    ids = seed(store)

    def counted() -> tuple[str, int]:
        (idea,) = run_triggers(store, TODAY)["calendar_outdated"]
        return idea.title, len(calendar_uids(store))

    assert counted() == ("Add your 2 dates to your calendar", 2)
    check(store, ids["genuine"])
    assert counted() == ("Add your 4 dates to your calendar", 4)


async def test_answering_the_warning_refreshes_the_ideas(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The person's check reaches every page at once: the Ideas are refreshed (a "do this by" Idea for each of
    the letter's dates) and the pages that list to-dos are told to reload."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        ids = seed(store)
        run_and_reconcile(store, TODAY)
        published: list[str] = []
        publish = api.ctx.bus.publish

        def recorded(type: str, **data: object) -> None:
            published.append(type)
            publish(type, **data)

        monkeypatch.setattr(api.ctx.bus, "publish", recorded)
        url = f"/api/suggestions/{scam_idea(store, ids['genuine']).id}"
        assert (await api.client.patch(url, json={"status": "dismissed"})).status_code == 200
        assert {ids["genuine_deadline"], ids["genuine_payment"]} <= soon_ideas(store)
        assert "item.updated" in published
        assert (await api.client.patch(url, json={"status": "new"})).status_code == 200
        assert not {ids["genuine_deadline"], ids["genuine_payment"]} & soon_ideas(store)
