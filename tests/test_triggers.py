"""Deterministic secretary triggers (SPEC §9, §21): one positive and one negative case per rule,
plus fingerprints and reconciliation."""

from __future__ import annotations

from datetime import date

import pytest

from helpers_secretary import TODAY, add_doc, add_item, seed_ledger
from ordnung.db.store import Store
from ordnung.ids import content_id
from ordnung.models import ExtractedChange, Suggestion
from ordnung.secretary.triggers import (
    TRIGGERS,
    english,
    fingerprint,
    run_and_reconcile,
    run_triggers,
    yearly_extra_cost,
    zusatzbeitrag_raised,
)

FAR_FUTURE = "2999-01-01T00:00:00Z"


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


def ideas(store: Store, rule_id: str, today: date = TODAY) -> list[Suggestion]:
    return run_triggers(store, today)[rule_id]


def refs_of(idea: Suggestion) -> set[tuple[str, str]]:
    return {(ref.type, ref.id) for ref in idea.refs}


# --------------------------------------------------------------------------------------------------
# every rule
# --------------------------------------------------------------------------------------------------


def test_every_idea_is_well_formed_and_points_at_real_records(store: Store, ids: dict[str, str]) -> None:
    results = run_triggers(store, TODAY)
    assert set(results) == set(TRIGGERS)
    getters = {
        "document": store.get_document,
        "item": store.get_item,
        "contract": store.get_contract,
        "party": store.get_party,
        "draft": store.get_draft,
    }
    produced = [idea for batch in results.values() for idea in batch]
    assert len(produced) >= 12
    for idea in produced:
        assert idea.source == "rule" and idea.rule_id
        assert idea.fingerprint.startswith(f"{idea.rule_id}:")
        assert idea.id == content_id("sug", idea.fingerprint)
        assert idea.action is not None and idea.action.label
        assert idea.title and idea.body
        for ref in idea.refs:
            assert getters[ref.type](ref.id) is not None, (idea.rule_id, ref)
        if idea.action.target_type in getters and idea.action.target_id:
            assert getters[idea.action.target_type](idea.action.target_id) is not None


def test_triggers_are_deterministic(store: Store, ids: dict[str, str]) -> None:
    first = {rule: [i.fingerprint for i in batch] for rule, batch in run_triggers(store, TODAY).items()}
    second = {rule: [i.fingerprint for i in batch] for rule, batch in run_triggers(store, TODAY).items()}
    assert first == second


def test_fingerprint_hashes_the_triggering_values() -> None:
    assert fingerprint("overdue", "itm_1", "2026-09-20") == fingerprint("overdue", "itm_1", "2026-09-20")
    assert fingerprint("overdue", "itm_1", "2026-09-20") != fingerprint("overdue", "itm_1", "2026-09-21")
    assert fingerprint("overdue", "itm_1", "x").startswith("overdue:itm_1:")


# --------------------------------------------------------------------------------------------------
# deadline_soon / overdue
# --------------------------------------------------------------------------------------------------


def test_deadline_soon_reports_items_within_their_reminder_window(store: Store, ids: dict[str, str]) -> None:
    found = {idea.refs[0].id: idea for idea in ideas(store, "deadline_soon")}
    assert set(found) == {ids["parking_payment"], ids["semester_fee"]}
    parking = found[ids["parking_payment"]]
    assert parking.due_date == "2026-09-29"
    assert parking.priority == "critical"
    assert parking.action is not None and parking.action.label == "Pay"
    assert "tomorrow" in parking.body


def test_deadline_soon_leaves_out_far_refunds_dunning_and_scam_items(
    store: Store, ids: dict[str, str]
) -> None:
    reported = {idea.refs[0].id for idea in ideas(store, "deadline_soon")}
    # objection: send-by 15 Oct is 17 days away (> 14); refund is incoming money; the reminder has its
    # own rule; the scam letter's "payment" must never be suggested
    for label in ("tax_objection", "tax_refund", "dunning_payment", "scam_payment", "abh_appointment"):
        assert ids[label] not in reported


def test_deadline_soon_leaves_out_direct_debits(store: Store, ids: dict[str, str]) -> None:
    debit = add_item(
        store,
        kind="payment",
        title="Monthly Deutschlandticket",
        action="Ensure sufficient funds for the monthly SEPA direct debit.",
        area="mobility",
        due_date="2026-10-01",
        amount=63.0,
        currency="EUR",
        direction="out",
    )
    assert not any(("item", debit) in refs_of(idea) for idea in ideas(store, "deadline_soon"))
    store.update_item(debit, action="Transfer 63 € or set up a SEPA direct debit.")
    assert any(("item", debit) in refs_of(idea) for idea in ideas(store, "deadline_soon"))


@pytest.mark.parametrize(
    ("title", "action"),
    [
        ("Rundfunkbeitrag nachzahlen – konnte nicht eingezogen werden", "Pay 49.99 € by 01.10.2026"),
        ("Pay Rundfunkbeitrag (amount could not be debited)", "Pay 49.99 € by 01.10.2026"),
        ("Mitgliedsbeitrag nach Rücklastschrift", None),
        ("Die erste Miete von 640 € zahlen, sobald Sie eingezogen sind", None),
    ],
)
def test_a_returned_debit_or_a_first_rent_keeps_its_reminders(
    store: Store, ids: dict[str, str], title: str, action: str | None
) -> None:
    """Its words name a debit that failed, or moving in: the person pays it, so it is reminded of
    before its day and when it is overdue — not left out as money the sender collects."""
    payment = add_item(
        store,
        kind="payment",
        title=title,
        action=action,
        due_date="2026-10-01",
        amount=49.99,
        currency="EUR",
        direction="out",
    )
    assert any(("item", payment) in refs_of(idea) for idea in ideas(store, "deadline_soon"))
    assert any(("item", payment) in refs_of(idea) for idea in ideas(store, "overdue", date(2026, 10, 5)))


def test_deadline_soon_offers_an_objection_draft_when_the_window_opens(
    store: Store, ids: dict[str, str]
) -> None:
    found = {idea.refs[0].id: idea for idea in ideas(store, "deadline_soon", date(2026, 10, 5))}
    objection = found[ids["tax_objection"]]
    assert objection.due_date == "2026-10-15"  # the send-by day, not the legal deadline
    assert objection.title == "Objection deadline (Einspruch): send by Thu 15 Oct"
    assert objection.action is not None
    assert (objection.action.type, objection.action.draft_kind, objection.action.label) == (
        "draft",
        "objection",
        "Draft objection",
    )
    assert "Wed 21 Oct" in objection.body
    assert objection.rationale and objection.rationale.startswith("Letter dated 15 Sep")


def test_overdue_is_computed_on_read_and_never_changes_the_item(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "overdue")
    assert [idea.refs[0].id for idea in found] == [ids["library_task"]]
    assert found[0].priority == "high"
    assert found[0].title == "Overdue: Return library books"
    item = store.get_item(ids["library_task"])
    assert item is not None and item.status == "open"


def test_overdue_ignores_done_items(store: Store, ids: dict[str, str]) -> None:
    store.update_item(ids["library_task"], status="done")
    assert ideas(store, "overdue") == []  # the done invoice and the reminder-kind follow-up never count


# --------------------------------------------------------------------------------------------------
# contracts
# --------------------------------------------------------------------------------------------------


def test_contract_cancel_window_uses_the_rules_engine(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "contract_cancel_window")
    assert [idea.refs[0].id for idea in found] == [ids["phone"]]
    phone = found[0]
    assert phone.due_date == "2026-10-08"
    assert phone.title == "Decide on your FunkNetz mobile — send by Thu 8 Oct"
    assert "€359.88 a year" in phone.body
    assert phone.rationale and "TKG" in phone.rationale
    assert phone.action is not None
    assert (phone.action.type, phone.action.draft_kind, phone.action.target_id, phone.action.label) == (
        "draft",
        "cancellation",
        ids["phone"],
        "Draft cancellation",
    )


def test_contract_cancel_window_is_quiet_outside_60_days(store: Store, ids: dict[str, str]) -> None:
    # 1 Aug: the phone's send-by (8 Oct) is 68 days away; any-time and fixed-term contracts never count
    assert ideas(store, "contract_cancel_window", date(2026, 8, 1)) == []


def test_price_increase_right_shows_the_yearly_extra_cost_and_window(
    store: Store, ids: dict[str, str]
) -> None:
    found = ideas(store, "price_increase_right")
    assert len(found) == 1
    idea = found[0]
    assert (
        idea.title
        == "Stadtwerke Musterstadt raises prices: +€84/year extra cost — you may cancel until Sat 31 Oct"
    )
    assert "saving" not in idea.title.lower()
    assert idea.savings_estimate is None
    assert idea.due_date == "2026-10-26"
    assert refs_of(idea) == {("document", ids["doc_power"]), ("contract", ids["power"])}
    assert idea.rationale and "§ 41 Abs. 5 EnWG" in idea.rationale


def test_price_increase_right_expires_with_the_window_or_the_contract(
    store: Store, ids: dict[str, str]
) -> None:
    assert ideas(store, "price_increase_right", date(2026, 11, 2)) == []
    store.update_contract(ids["power"], status="cancelled")
    assert ideas(store, "price_increase_right") == []


def test_ideas_leave_out_german_sentences_copied_from_the_letter() -> None:
    assert english("Ausreichende Kontodeckung für die monatliche SEPA-Lastschrift sicherstellen.") is None
    assert english("Geht der Betrag nicht fristgerecht ein, müssen wir die Forderung übergeben.") is None
    assert english("Transfer 30 € to the Stadtkasse, quoting the Kassenzeichen.") is not None
    assert english(None) is None


def test_zusatzbeitrag_raised_needs_a_higher_rate_not_a_higher_income() -> None:
    def change(old: str | None, new: str | None, **amounts: float) -> ExtractedChange:
        return ExtractedChange(type="price_increase", unit_price_old=old, unit_price_new=new, **amounts)

    assert zusatzbeitrag_raised(change("2,69 %", "2,99 %"))
    assert not zusatzbeitrag_raised(change("2,69 %", "2,69 %"))  # the rate stays
    assert not zusatzbeitrag_raised(change("2,99 %", "2,69 %"))  # the rate falls
    assert not zusatzbeitrag_raised(change(None, None, old_amount=146.29, new_amount=156.55))  # income rose
    assert not zusatzbeitrag_raised(change(None, "2,99 %"))  # no old rate to compare with


def test_yearly_extra_cost_is_interval_normalised() -> None:
    assert yearly_extra_cost(48.0, 55.0, "monthly") == 84.0
    assert yearly_extra_cost(30.0, 36.0, "quarterly") == 24.0
    assert yearly_extra_cost(100.0, 120.0, "yearly") == 20.0
    assert yearly_extra_cost(None, 55.0, "monthly") is None
    assert yearly_extra_cost(48.0, 55.0, "once") is None


def test_confirm_cancellation_asks_before_closing_the_contract(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "confirm_cancellation")
    assert len(found) == 1
    idea = found[0]
    assert idea.title == "Confirm cancellation of FitMuster membership effective Thu 31 Dec?"
    assert idea.action is not None and (idea.action.type, idea.action.label) == (
        "mark_done",
        "Confirm cancellation",
    )
    contract = store.get_contract(ids["gym_contract"])
    assert contract is not None and contract.status == "active"  # nothing is closed without a click
    # a confirmed cancellation is no renewal decision
    assert ids["gym_contract"] not in {
        i.refs[0].id for i in ideas(store, "contract_cancel_window", date(2026, 10, 30))
    }


def test_confirm_cancellation_is_quiet_once_the_contract_is_cancelled(
    store: Store, ids: dict[str, str]
) -> None:
    store.update_contract(ids["gym_contract"], status="cancelled")
    assert ideas(store, "confirm_cancellation") == []


# --------------------------------------------------------------------------------------------------
# residence
# --------------------------------------------------------------------------------------------------


def test_expiry_soon_flags_permit_at_90_days_and_passport_at_180(store: Store, ids: dict[str, str]) -> None:
    found = {idea.refs[0].id: idea for idea in ideas(store, "expiry_soon")}
    assert set(found) == {ids["permit_expiry"], ids["passport_expiry"]}
    permit = found[ids["permit_expiry"]]
    assert "§ 81 Abs. 4 AufenthG" in permit.body
    assert permit.priority == "high"
    assert permit.action is not None and permit.action.label == "Check the permit"
    passport = found[ids["passport_expiry"]]
    assert passport.title == "Your passport expires Wed 10 Feb 2027"


def test_expiry_soon_is_quiet_when_expiries_are_far(store: Store, ids: dict[str, str]) -> None:
    # 1 Jun: permit in 197 days (> 90), passport in 254 days (> 180)
    assert ideas(store, "expiry_soon", date(2026, 6, 1)) == []


def test_expiry_soon_escalates_an_expired_permit(store: Store, ids: dict[str, str]) -> None:
    found = {idea.refs[0].id: idea for idea in ideas(store, "expiry_soon", date(2026, 12, 20))}
    permit = found[ids["permit_expiry"]]
    assert permit.priority == "critical"
    assert permit.title == "Your residence permit expired on Tue 15 Dec"


def test_passport_before_permit(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "passport_before_permit")
    assert len(found) == 1
    assert refs_of(found[0]) >= {("item", ids["passport_expiry"]), ("item", ids["permit_expiry"])}
    assert found[0].due_date == "2026-12-15"


def test_passport_before_permit_is_quiet_for_a_long_valid_passport(store: Store, ids: dict[str, str]) -> None:
    store.update_item(ids["passport_expiry"], due_date="2030-01-01")
    assert ideas(store, "passport_before_permit") == []


def test_student_permit_info_card(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "student_permit_info")
    assert len(found) == 1
    assert found[0].kind == "info" and found[0].priority == "low"
    assert "§ 16b Abs. 3 AufenthG" in found[0].body
    assert refs_of(found[0]) == {("document", ids["doc_permit"])}
    store.save_profile(store.get_profile().model_copy(update={"is_student_visa": False}))
    assert ideas(store, "student_permit_info") == []


# --------------------------------------------------------------------------------------------------
# letters
# --------------------------------------------------------------------------------------------------


def test_followup_due_after_a_sent_letter(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "followup_due")
    assert len(found) == 1
    assert refs_of(found[0]) == {("item", ids["followup"]), ("draft", ids["draft_uni"])}
    assert "Question about my enrolment" in found[0].body


def test_followup_due_waits_for_the_follow_up_date(store: Store, ids: dict[str, str]) -> None:
    assert ideas(store, "followup_due", date(2026, 9, 25)) == []


def test_please_check_lists_the_unconfirmed_facts(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "please_check")
    assert len(found) == 1
    assert found[0].title == "Please check: Parking fine"
    assert refs_of(found[0]) == {("document", ids["doc_parking"]), ("item", ids["parking_payment"])}
    assert found[0].action is not None and found[0].action.label == "Check the letter"
    store.update_document(ids["doc_parking"], status="processed")
    assert ideas(store, "please_check") == []


def test_dunning_escalation(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "dunning_escalation")
    assert len(found) == 1
    idea = found[0]
    assert idea.title == "Pay TechMarkt reminder €94.99 by Wed 30 Sep"
    assert idea.priority == "critical"
    assert ("document", ids["doc_invoice"]) in refs_of(idea)
    store.update_item(ids["dunning_payment"], status="done")
    assert ideas(store, "dunning_escalation") == []


def test_scam_warning_quotes_both_accounts(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "scam_warning")
    assert len(found) == 1
    idea = found[0]
    assert idea.kind == "scam" and idea.priority == "critical"
    assert "hidden text" in idea.body
    assert "LT12 1000 0111 0100 1000" in idea.body and "DE02 4401 0046 0123 4567 89" in idea.body
    assert idea.action is not None and idea.action.label == "See why"


def test_scam_warning_is_quiet_for_ordinary_letters(store: Store, ids: dict[str, str]) -> None:
    store.update_document(ids["doc_scam"], hidden_text=False, warnings=[], payment=None)
    assert ideas(store, "scam_warning") == []


def test_an_invalid_iban_alone_is_a_misprint_not_a_scam(store: Store, ids: dict[str, str]) -> None:
    # a scammer needs an account that works: bad check digits are almost always a typo or a misread photo
    store.update_document(ids["doc_scam"], hidden_text=False, warnings=[], party_id=None)
    store.update_document(ids["doc_scam"], payment={"iban": "LT717300010000000000", "iban_valid": False})
    assert ideas(store, "scam_warning") == []
    found = ideas(store, "iban_misprint")
    assert len(found) == 1
    idea = found[0]
    assert idea.kind == "info" and idea.priority == "normal"
    assert "misprinted" in idea.title and "LT71 7300 0100 0000 0000" in idea.body
    assert idea.action is not None and idea.action.label == "Check the letter"
    assert idea.due_date == "2026-10-01"


def test_an_invalid_iban_is_one_more_sign_next_to_others(store: Store, ids: dict[str, str]) -> None:
    store.update_document(ids["doc_scam"], party_id=None)
    store.update_document(ids["doc_scam"], payment={"iban": "LT717300010000000000", "iban_valid": False})
    found = ideas(store, "scam_warning")
    assert len(found) == 1 and "checksum" in found[0].body and "hidden text" in found[0].body
    assert found[0].rationale == "3 warning signs."
    assert ideas(store, "iban_misprint") == []


def test_iban_misprint_is_quiet_without_a_transfer_to_make(store: Store, ids: dict[str, str]) -> None:
    store.update_document(ids["doc_scam"], hidden_text=False, warnings=[], party_id=None)
    store.update_document(ids["doc_scam"], payment={"iban": "LT717300010000000000", "iban_valid": False})
    store.update_item(ids["scam_payment"], action="Ensure sufficient funds for the SEPA direct debit.")
    assert ideas(store, "iban_misprint") == []


def test_tax_documents_in_tax_season_only(store: Store, ids: dict[str, str]) -> None:
    assert ideas(store, "tax_documents") == []  # September
    found = ideas(store, "tax_documents", date(2026, 3, 1))
    assert len(found) == 1
    assert refs_of(found[0]) == {("document", ids["doc_payslip"])}
    assert found[0].due_date == "2026-07-31"


# --------------------------------------------------------------------------------------------------
# calendar
# --------------------------------------------------------------------------------------------------


def test_calendar_outdated_counts_dates_changed_since_the_export(store: Store, ids: dict[str, str]) -> None:
    assert ideas(store, "calendar_outdated") == []  # everything was exported
    new = add_item(
        store,
        kind="appointment",
        title="Dentist",
        area="health",
        due_date="2026-10-20",
        created_at=None,
        updated_at=None,
        origin="manual",
        grounding="user",
    )
    found = ideas(store, "calendar_outdated")
    assert len(found) == 1
    assert found[0].title == "1 new date since your last calendar update"
    assert refs_of(found[0]) == {("item", new)}
    assert found[0].action is not None and found[0].action.label == "Add to calendar"


def test_calendar_outdated_without_any_export(store: Store, ids: dict[str, str]) -> None:
    store.set_meta("last_calendar_export_at", None)
    found = ideas(store, "calendar_outdated")
    assert len(found) == 1 and found[0].title.startswith("Add your ")


# --------------------------------------------------------------------------------------------------
# reconciliation
# --------------------------------------------------------------------------------------------------


def test_run_and_reconcile_is_idempotent_and_keeps_the_persons_choice(
    store: Store, ids: dict[str, str]
) -> None:
    first = run_and_reconcile(store, TODAY)
    assert first.new == first.live > 0 and first.expired == 0
    stored = store.list_suggestions()
    assert len(stored) == first.live
    dismissed = stored[0]
    store.update_suggestion(dismissed.id, status="dismissed")
    second = run_and_reconcile(store, TODAY)
    assert (second.new, second.expired, second.live) == (0, 0, first.live)
    after = store.get_suggestion(dismissed.id)
    assert after is not None and after.status == "dismissed"


def test_reconcile_expires_ideas_whose_trigger_stopped_firing(store: Store, ids: dict[str, str]) -> None:
    store.set_meta("last_calendar_export_at", FAR_FUTURE)  # edits below must not trip calendar_outdated
    run_and_reconcile(store, TODAY)
    semester = next(s for s in store.list_suggestions() if ("item", ids["semester_fee"]) in refs_of(s))
    store.update_item(ids["semester_fee"], status="done")
    run = run_and_reconcile(store, TODAY)
    assert run.expired == 1
    expired = store.get_suggestion(semester.id)
    assert expired is not None and expired.status == "expired"
    store.update_item(ids["semester_fee"], status="open")
    again = run_and_reconcile(store, TODAY)
    assert again.new == 1
    revived = store.get_suggestion(semester.id)
    assert revived is not None and revived.status == "new"


def test_a_changed_due_date_replaces_the_idea(store: Store, ids: dict[str, str]) -> None:
    store.set_meta("last_calendar_export_at", FAR_FUTURE)
    run_and_reconcile(store, TODAY)
    old = next(s for s in store.list_suggestions() if ("item", ids["semester_fee"]) in refs_of(s))
    store.update_item(ids["semester_fee"], due_date="2026-10-03")
    run = run_and_reconcile(store, TODAY)
    assert (run.new, run.expired) == (1, 1)
    refreshed = store.get_suggestion(old.id)
    assert refreshed is not None and refreshed.status == "expired"


def test_review_ideas_are_never_expired_by_triggers(store: Store, ids: dict[str, str]) -> None:
    store.upsert_suggestion(
        {
            "kind": "saving",
            "title": "Compare phone tariffs",
            "body": "b",
            "fingerprint": "review:abc",
            "source": "review",
            "created_at": "x",
            "updated_at": "x",
        }
    )
    run_and_reconcile(store, TODAY)
    review = store.get_suggestion(content_id("sug", "review:abc"))
    assert review is not None and review.status == "new"


# --------------------------------------------------------------------------------------------------
# regressions found in the first live run
# --------------------------------------------------------------------------------------------------


def test_dunning_escalation_never_says_pay_to_a_letter_with_scam_signs(
    store: Store, ids: dict[str, str]
) -> None:
    store.update_document(ids["doc_scam"], kind="dunning")
    dunning = ideas(store, "dunning_escalation")
    assert all(idea.refs[0].id != ids["doc_scam"] for idea in dunning)
    assert any(ids["doc_scam"] in {ref.id for ref in idea.refs} for idea in ideas(store, "scam_warning"))


def test_overdue_skips_items_that_were_already_history_when_the_letter_was_filed(
    store: Store, ids: dict[str, str]
) -> None:
    old = add_item(
        store,
        kind="deadline",
        title="Submit first meter reading",
        due_date="2025-10-05",
        filed_on=TODAY.isoformat(),
        area="home",
    )
    recent = add_item(
        store,
        kind="deadline",
        title="Return the library books",
        due_date="2026-09-25",
        filed_on="2026-09-20",
        area="leisure",
    )
    overdue_ids = {idea.refs[0].id for idea in ideas(store, "overdue") if idea.refs}
    assert old not in overdue_ids
    assert recent in overdue_ids


def _invoice_and_reminder(store: Store, ids: dict[str, str]) -> tuple[str, str]:
    """An overdue invoice payment and the payment reminder about it, in one thread."""
    case = store.add_case(title="Invoice R-4711", party_id=ids["techmarkt"], reference="R-4711")
    refs = [{"label": "Rechnungsnummer", "value": "R-4711"}]
    invoice = add_doc(
        store, "invoice-4711", kind="invoice", party_id=ids["techmarkt"], case_id=case.id, references=refs
    )
    reminder = add_doc(
        store,
        "reminder-4711",
        kind="dunning",
        doc_date="2026-09-20",
        party_id=ids["techmarkt"],
        case_id=case.id,
        references=refs,
    )
    invoice_item = add_item(
        store,
        kind="payment",
        title="Pay the invoice",
        due_date="2026-09-03",
        filed_on="2026-09-01",
        amount=89.99,
        direction="out",
        area="money",
        doc_id=invoice,
    )
    return invoice_item, reminder


def test_an_invoice_covered_by_its_payment_reminder_is_not_a_second_to_do(
    store: Store, ids: dict[str, str]
) -> None:
    from ordnung.views import dashboard

    invoice_item, _ = _invoice_and_reminder(store, ids)
    overdue_ids = {idea.refs[0].id for idea in ideas(store, "overdue") if idea.refs}
    assert invoice_item not in overdue_ids
    assert invoice_item not in {item.id for item in dashboard(store, TODAY).attention}


def test_the_invoice_payment_is_back_once_its_reminder_is_in_the_trash(
    store: Store, ids: dict[str, str]
) -> None:
    from ordnung.views import dashboard

    invoice_item, reminder = _invoice_and_reminder(store, ids)
    store.trash_document(reminder)

    assert invoice_item in {idea.refs[0].id for idea in ideas(store, "overdue") if idea.refs}
    assert invoice_item in {item.id for item in dashboard(store, TODAY).attention}
