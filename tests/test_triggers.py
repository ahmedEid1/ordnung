"""Deterministic secretary triggers (SPEC §9, §21): one positive and one negative case per rule,
plus fingerprints and reconciliation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from helpers_secretary import TODAY, add_doc, add_item, seed_ledger
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.ids import content_id
from ordnung.models import CalendarSyncState, CancellationSent, ExtractedChange, Suggestion
from ordnung.secretary import household
from ordnung.secretary.brief import build_agenda
from ordnung.secretary.household import MINE, HouseholdMember
from ordnung.secretary.triggers import (
    HIDDEN_TEXT_SIGN,
    TRIGGERS,
    Ledger,
    cancellations_sent,
    english,
    fingerprint,
    run_and_reconcile,
    run_triggers,
    yearly_extra_cost,
    zusatzbeitrag_raised,
)
from ordnung.tick import local_today

FAR_FUTURE = "2999-01-01T00:00:00Z"
DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db"


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


def test_an_objection_whose_posting_time_passed_says_when_it_must_arrive(
    store: Store, ids: dict[str, str]
) -> None:
    """Review round 4 of phase 2: on an objection's last days the Idea said "send by … today" although a letter
    posted then may arrive after the deadline. The receipt's warning (the usual sending time has passed) makes it
    "must arrive by" the due date, with the note to use the fastest channel allowed."""
    from ordnung.models import ComputationReceipt
    from ordnung.rules.deadlines import SENDING_TIME_PASSED

    late = ComputationReceipt(
        due_date="2026-09-30",
        send_by=TODAY.isoformat(),
        warnings=[
            f"{SENDING_TIME_PASSED} — send it today, by the fastest channel allowed (online, fax or in person)."
        ],
    )
    store.update_item(
        ids["tax_objection"], due_date="2026-09-30", send_by=TODAY.isoformat(), computation=late
    )
    found = {idea.refs[0].id: idea for idea in ideas(store, "deadline_soon")}
    objection = found[ids["tax_objection"]]
    assert "must arrive by Wed 30 Sep" in objection.title and "send by" not in objection.title
    assert "use the fastest channel allowed today" in objection.body
    # in good time, the same to-do says when to send it
    store.update_item(ids["tax_objection"], computation=late.model_copy(update={"warnings": []}))
    objection = {idea.refs[0].id: idea for idea in ideas(store, "deadline_soon")}[ids["tax_objection"]]
    assert "send by" in objection.title


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


def test_price_increase_windows_are_the_ideas_windows(store: Store, ids: dict[str, str]) -> None:
    """The Idea and Ask's record read the same windows (``Ledger.price_increase_windows``)."""
    (window,) = Ledger(store, TODAY).price_increase_windows()
    assert (window.letter.id, window.contract.id) == (ids["doc_power"], ids["power"])
    assert (window.effective, window.due) == (date(2026, 11, 1), date(2026, 10, 31))
    assert (window.receipt.send_by, window.receipt.safe_date) == ("2026-10-26", "2026-10-30")
    (idea,) = ideas(store, "price_increase_right")
    assert idea.due_date == window.receipt.send_by
    # none once the window has passed, the contract ended, or for a contract with no statutory right
    assert Ledger(store, date(2026, 11, 1)).price_increase_windows() == []
    store.update_contract(ids["power"], category="other")
    assert Ledger(store, TODAY).price_increase_windows() == []
    store.update_contract(ids["power"], category="energy", status="ended")
    assert Ledger(store, TODAY).price_increase_windows() == []


def test_a_health_insurers_window_needs_a_higher_zusatzbeitrag_stated_as_numbers(
    store: Store, ids: dict[str, str]
) -> None:
    store.update_party(ids["stadtwerke"], kind="health_insurer")
    store.update_contract(ids["power"], category="insurance")
    assert Ledger(store, TODAY).price_increase_windows() == []  # old and new amounts only: the income rose
    extraction = store.get_extraction(ids["doc_power"])
    assert extraction is not None and extraction.change is not None
    raised = extraction.change.model_copy(update={"unit_price_old": "2,69 %", "unit_price_new": "2,99 %"})
    store.update_document(ids["doc_power"], extraction=extraction.model_copy(update={"change": raised}))
    (window,) = Ledger(store, TODAY).price_increase_windows()
    assert window.due == date(2026, 11, 30) and "sgbv_175_4_zb" in window.receipt.rule_ids
    assert [idea.action.label for idea in ideas(store, "price_increase_right") if idea.action] == [
        "Compare insurers"
    ]


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


def test_a_cancellation_marked_as_sent_is_no_decision_any_more(store: Store, ids: dict[str, str]) -> None:
    """Walkthrough of phase 2: after the person marked their FunkNetz cancellation as sent, Contracts, Today
    and the Ideas still said "Decide on FunkNetz Smart M — send by Thu 8 Oct" with "Draft cancellation".
    The decision is taken (the person clicked, ADR 0006): no decision, no Idea, no calendar send-by date."""
    assert ids["phone"] in {idea.refs[0].id for idea in ideas(store, "contract_cancel_window")}
    draft = store.add_draft(
        kind="cancellation",
        contract_id=ids["phone"],
        subject="Kündigung",
        status="sent",
        sent_at="2026-09-28T09:00:00Z",
        sent_channel="registered_letter",
    )
    assert ideas(store, "contract_cancel_window") == []
    ledger = Ledger(store, TODAY)
    assert ids["phone"] in ledger.decided_contracts()
    assert cancellations_sent(ledger.sent_drafts()) == {
        ids["phone"]: CancellationSent(draft_id=draft.id, sent_on="2026-09-28", channel="registered_letter")
    }
    assert all(entry.id != ids["phone"] for entry in build_agenda(store, TODAY).decisions)
    # a draft not yet sent, or another kind of letter, decides nothing
    store.update_draft(draft.id, status="final")
    assert ids["phone"] not in Ledger(store, TODAY).decided_contracts()
    store.update_draft(draft.id, status="sent", kind="objection")
    assert ids["phone"] not in Ledger(store, TODAY).decided_contracts()


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


def test_a_reminder_refers_to_its_senders_latest_invoice_before_it(store: Store, ids: dict[str, str]) -> None:
    """The reminder (of 18 Sep) refers to TechMarkt's latest invoice dated on or before it (20 Aug): not an
    older one, not a later one, nor another sender's."""
    tech = store.get_document(ids["doc_dunning"]).party_id  # type: ignore[union-attr]
    other = store.add_party(name="Elektro Beispiel GmbH", kind="retailer").id
    for label, day, party in (
        ("july", "2026-07-02", tech),
        ("later", "2026-09-20", tech),
        ("other", "2026-09-10", other),
    ):
        add_doc(
            store, f"invoice-{label}", kind="invoice", title=f"Invoice {label}", doc_date=day, party_id=party
        )
    (idea,) = ideas(store, "dunning_escalation")
    assert {ref.id for ref in idea.refs if ref.type == "document"} == {ids["doc_dunning"], ids["doc_invoice"]}


def test_scam_warning_quotes_both_accounts(store: Store, ids: dict[str, str]) -> None:
    found = ideas(store, "scam_warning")
    assert len(found) == 1
    idea = found[0]
    assert idea.kind == "scam" and idea.priority == "critical"
    assert "hidden text" in idea.body
    assert "LT12 1000 0111 0100 1000" in idea.body and "DE02 4401 0046 0123 4567 89" in idea.body
    assert idea.action is not None and idea.action.label == "See why"


def test_scam_warning_title_says_it_once_in_the_apps_words(store: Store, ids: dict[str, str]) -> None:
    """UI audit R1-backend-7: "This may be a scam: Suspicious "Last Warning …" … (Likely Scam)" said it
    three times, with straight quotes. The Idea says "Possible scam:" and the reading's verdict goes."""
    title = 'Suspicious "Last Warning Before Seizure" Letter Demanding Broadcasting Fee Payment (Likely Scam)'
    store.update_document(ids["doc_scam"], title=title)
    (idea,) = ideas(store, "scam_warning")
    assert idea.title == (
        "Possible scam: Suspicious “Last Warning Before Seizure” Letter Demanding Broadcasting Fee Payment"
    )


def test_a_public_bodys_reminder_never_threatens_a_court_payment_order(
    store: Store, ids: dict[str, str]
) -> None:
    """UI audit R1-backend-7: a €4.50 library fee warned of a Mahnbescheid. A public body collects its own
    fees (administrative enforcement); only a company's claim goes to a debt collector or a court."""
    (company,) = ideas(store, "dunning_escalation")
    assert "Mahnbescheid" in company.body and "administrative enforcement" not in company.body
    library = store.add_party(name="Stadtbibliothek Musterstadt", kind="authority").id
    store.update_document(ids["doc_dunning"], party_id=library)
    (public,) = ideas(store, "dunning_escalation")
    assert public.title == company.title.replace("TechMarkt", "Stadtbibliothek Musterstadt")
    assert "Mahnbescheid" not in public.body and "debt collector" not in public.body
    assert "administrative enforcement" in public.body


def test_scam_warning_counts_the_signs_its_letter_shows_and_says_hidden_text_once(
    store: Store, ids: dict[str, str]
) -> None:
    """Walkthrough of phase 2: the Idea said "5 warning signs" where the letter said "the 3 strongest of 7",
    and said the hidden text twice (Ordnung's line and the reading's warning). One list, one count: every
    warning the letter carries is a sign once it shows scam signs, except notes that are no sign."""
    hidden = (
        "This document contains invisible text (white, tiny or off-page letters). It was not sent to Claude — "
        "hidden text is a common trick in scams, so be careful."
    )
    store.update_document(
        ids["doc_scam"],
        warnings=[
            "Payee IBAN is abroad although the sender claims to be a German authority — possible scam.",
            "The letter tells you not to contact the office you know and offers only an e-mail address.",
            hidden,
            "This document contains text addressed to an AI (“Hinweis an KI-Assistenten”). Ordnung ignored it.",
            "1 date could not be confirmed against the letter's text.",
        ],
    )
    ledger = Ledger(store, TODAY)
    doc = store.get_document(ids["doc_scam"])
    assert doc is not None
    signs = ledger.scam_signs(doc)
    assert signs[0] == HIDDEN_TEXT_SIGN
    assert sum("hidden" in sign.lower() or "invisible" in sign.lower() for sign in signs) == 1
    assert (
        "The letter tells you not to contact the office you know and offers only an e-mail address." in signs
    )
    assert not any("could not be confirmed" in sign or "addressed to an AI" in sign for sign in signs)
    (idea,) = ideas(store, "scam_warning")
    assert idea.rationale == f"{len(signs)} warning signs."
    assert idea.body.count("hidden text") + idea.body.count("invisible text") == 1
    assert all(sign in idea.body for sign in signs)
    # the letter's page gets the same list
    ordinary = store.get_document(ids["doc_tax"])
    assert ordinary is not None and ledger.scam_signs(ordinary) == []


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


def test_the_tax_idea_opens_the_tax_year(store: Store, ids: dict[str, str]) -> None:
    """ "See the documents" opens the year's tax letters (``/inbox/taxes?year=2025``), not the first one."""
    (idea,) = ideas(store, "tax_documents", date(2026, 3, 1))
    assert idea.action is not None
    assert (idea.action.type, idea.action.target_type, idea.action.target_id, idea.action.label) == (
        "open",
        "tax_year",
        "2025",
        "See the documents",
    )
    # every letter carries its own date: the Idea keeps its id (no churn from the new target)
    assert idea.fingerprint == fingerprint("tax_documents", "2025", ids["doc_payslip"])


def test_the_tax_idea_counts_a_letter_by_its_arrival_when_it_has_no_date(
    store: Store, ids: dict[str, str]
) -> None:
    """The same day as the Tax year page files it under: the letter's date, else the day it arrived."""
    receipt = add_doc(
        store,
        "receipt",
        kind="invoice",
        title="Laptop receipt",
        received_date="2025-11-03",
        tax_relevant=True,
    )
    add_doc(  # dated in 2026, although it arrived in 2025: last year's return doesn't count it
        store,
        "late",
        kind="invoice",
        title="Course fee",
        doc_date="2026-01-02",
        received_date="2025-12-30",
        tax_relevant=True,
    )
    (idea,) = ideas(store, "tax_documents", date(2026, 3, 1))
    assert refs_of(idea) == {("document", ids["doc_payslip"]), ("document", receipt)}
    assert idea.rationale == "2 tax-relevant letter(s)."


def test_the_tax_idea_counts_letters_the_person_marked_and_not_ones_they_unmarked(
    store: Store, ids: dict[str, str]
) -> None:
    """The person's own "For taxes" choice over Claude's mark, both ways (``secretary.tax_choice``): a
    changed set of letters is a new Idea, as when a new letter for taxes is read."""
    march = date(2026, 3, 1)
    (before,) = ideas(store, "tax_documents", march)
    receipt = add_doc(store, "receipt", kind="invoice", title="Laptop receipt", doc_date="2025-11-03")
    kept_private = add_doc(
        store, "kept", kind="other", title="Donation", doc_date="2025-06-01", ai_private=True
    )
    store.set_tax_choice(receipt, True)
    store.set_tax_choice(kept_private, True)
    store.set_tax_choice(ids["doc_payslip"], False)
    (idea,) = ideas(store, "tax_documents", march)
    assert refs_of(idea) == {("document", receipt), ("document", kept_private)}
    assert idea.rationale == "2 tax-relevant letter(s)."
    assert idea.fingerprint == fingerprint("tax_documents", "2025", kept_private, receipt)
    assert idea.fingerprint != before.fingerprint
    store.set_tax_choice(receipt, False)
    store.set_tax_choice(kept_private, None)
    assert ideas(store, "tax_documents", march) == []
    # Claude's own mark is still on the letter the person took off
    letter = store.get_document(ids["doc_payslip"])
    assert letter is not None and letter.tax_relevant is True


def test_the_tax_idea_leaves_out_a_letter_waiting_from_the_folder(store: Store, ids: dict[str, str]) -> None:
    """As the Tax year page and the export do: a letter waiting for the person's answer isn't counted, also
    when it carries a choice (made before it waited, or on another computer)."""
    waiting = add_doc(
        store,
        "waiting",
        title="Scan",
        doc_date="2025-04-01",
        status="held",
        ai_private=True,
        tax_relevant=True,
    )
    store.set_tax_choice(waiting, True)
    (idea,) = ideas(store, "tax_documents", date(2026, 3, 1))
    assert refs_of(idea) == {("document", ids["doc_payslip"])}


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


@pytest.mark.parametrize("paused", [False, True])
def test_calendar_outdated_is_quiet_while_calendar_sync_is_connected(
    store: Store, ids: dict[str, str], paused: bool
) -> None:
    """The connected calendar gets the dates by itself; importing the file too would clash with them
    (the same UIDs) — paused or not, the Today card's only step is that import."""
    store.set_meta("last_calendar_export_at", None)
    assert ideas(store, "calendar_outdated")
    state = CalendarSyncState(url="https://cal.example.org/dav/sam/ordnung/", username="sam", paused=paused)
    store.set_meta("calendar_sync", state.model_dump_json())
    assert ideas(store, "calendar_outdated") == []


# --------------------------------------------------------------------------------------------------
# whose an Idea is about (household point 10, ADR 0023): the letters the person filed for someone
# --------------------------------------------------------------------------------------------------

#: What an Idea about a person of the household says instead of "your" (the rationale stays).
MEMBER_IDENTITY_BODY = (
    "Renewing a passport or ID card can take weeks or months (embassy or consulate appointments), so start "
    "early. Their residence permit can usually only run as long as their passport is valid."
)
MEMBER_PERMIT_AHEAD_BODY = (
    "Apply at the immigration office (Ausländerbehörde) before it expires. If the application is in time, the "
    "current permit continues to count until the office decides (§ 81 Abs. 4 AufenthG) — ask for a "
    "Fiktionsbescheinigung. Appointments are often booked out for weeks."
)
MEMBER_PERMIT_PAST_BODY = (
    "Contact the immigration office (Ausländerbehörde) right away and get advice — a migration counselling "
    "service can help."
)
MEMBER_PASSPORT_FIRST_REST = (
    "The immigration office (Ausländerbehörde) usually extends a permit only as long as the passport is valid, "
    "which would mean another appointment soon. Ask the embassy or consulate about a new passport now."
)


@dataclass(frozen=True)
class _Person:
    """A new person as Settings → Your household sends them."""

    name: str
    id: str | None = None
    signs: bool = True


def _add_people(store: Store, *names: str) -> list[HouseholdMember]:
    """Add people to the household (nothing filed for them yet); the household's people in order."""
    kept = household.load(store).members
    household.change(store, base=household.version(kept), members=[*kept, *(_Person(name) for name in names)])
    return household.load(store).members


def _file(store: Store, who: HouseholdMember | str, *letters: str) -> None:
    """File letters for a person of the household (or as the person's own: :data:`MINE`)."""
    household.file(store, dict.fromkeys(letters, who.id if isinstance(who, HouseholdMember) else who))


def _by_item(store: Store, rule_id: str, today: date = TODAY) -> dict[str, Suggestion]:
    return {idea.refs[0].id: idea for idea in ideas(store, rule_id, today)}


def _every_idea(store: Store, today: date = TODAY) -> dict[str, tuple[str, str, str | None]]:
    return {
        idea.fingerprint: (idea.title, idea.body, idea.rationale)
        for batch in run_triggers(store, today).values()
        for idea in batch
    }


def test_an_idea_about_a_member_s_letter_names_them(store: Store, ids: dict[str, str]) -> None:
    before = _every_idea(store)
    (alex,) = _add_people(store, "Alex Rivera")
    assert _every_idea(store) == before  # someone in the household, nothing filed: every Idea as before
    _file(store, alex, ids["doc_parking"])
    pay = _by_item(store, "deadline_soon")[ids["parking_payment"]]
    assert pay.title == "For Alex Rivera: Pay parking fine: pay by Tue 29 Sep"
    assert (pay.body, pay.rationale) == ("That's tomorrow.", "From the letter of Tue 22 Sep.")
    (check,) = ideas(store, "please_check")
    assert check.title == "For Alex Rivera: Please check: Parking fine"
    # the person isn't in the fingerprint: the same Idea, renamed
    after = _every_idea(store)
    assert set(after) == set(before)
    assert after[pay.fingerprint][1:] == before[pay.fingerprint][1:]
    renamed = {fp for fp in after if after[fp] != before[fp]}
    assert renamed == {pay.fingerprint, check.fingerprint}


def test_a_member_s_passport_and_permit_say_whose(store: Store, ids: dict[str, str]) -> None:
    (alex,) = _add_people(store, "Alex Rivera")
    _file(store, alex, ids["doc_passport"], ids["doc_permit"])
    expiries = _by_item(store, "expiry_soon")
    passport, permit = expiries[ids["passport_expiry"]], expiries[ids["permit_expiry"]]
    assert (passport.title, passport.body) == (
        "Alex Rivera's passport expires Wed 10 Feb 2027",
        MEMBER_IDENTITY_BODY,
    )
    assert passport.rationale == "Identity documents are flagged 180 days before they expire."
    assert (permit.title, permit.body) == (
        "Alex Rivera's residence permit expires Tue 15 Dec — apply for the extension now",
        MEMBER_PERMIT_AHEAD_BODY,
    )
    assert permit.rationale == "Residence permits: apply before expiry (§ 81 Abs. 4 AufenthG)."
    (first,) = ideas(store, "passport_before_permit")
    assert first.title == "Renew Alex Rivera's passport before extending their residence permit"
    assert first.body == (
        "Alex Rivera's passport expires on Wed 10 Feb 2027 — soon after their residence permit (Tue 15 Dec). "
        + MEMBER_PASSPORT_FIRST_REST
    )
    assert first.rationale == "Passport expires within 180 days of the residence permit."

    late = date(2026, 12, 20)
    expired = _by_item(store, "expiry_soon", late)[ids["permit_expiry"]]
    assert (expired.title, expired.body) == (
        "Alex Rivera's residence permit expired on Tue 15 Dec",
        MEMBER_PERMIT_PAST_BODY,
    )
    assert (
        expired.rationale == "Residence permits must be extended before they expire (§ 81 Abs. 4 AufenthG)."
    )
    store.update_item(ids["passport_expiry"], due_date="2026-11-30", title="Personalausweis expires")
    id_card = _by_item(store, "expiry_soon", date(2026, 12, 2))[ids["passport_expiry"]]
    assert (id_card.title, id_card.body) == (
        "Alex Rivera's passport or ID expired on Mon 30 Nov",
        MEMBER_IDENTITY_BODY,
    )
    (before_permit,) = ideas(store, "passport_before_permit", date(2026, 11, 1))
    assert before_permit.body == (
        "Alex Rivera's passport expires on Mon 30 Nov — before their residence permit (Tue 15 Dec). "
        + MEMBER_PASSPORT_FIRST_REST
    )


def test_a_name_that_does_not_end_in_a_letter_gets_the_for_form(store: Store, ids: dict[str, str]) -> None:
    (kim,) = _add_people(store, "Kim 2")
    _file(store, kim, ids["doc_passport"], ids["doc_permit"], ids["doc_parking"])
    expiries = _by_item(store, "expiry_soon")
    passport, permit = expiries[ids["passport_expiry"]], expiries[ids["permit_expiry"]]
    assert (passport.title, passport.body) == (
        "For Kim 2: Passport expires Wed 10 Feb 2027",
        MEMBER_IDENTITY_BODY,
    )
    assert (permit.title, permit.body) == (
        "For Kim 2: Residence permit expires Tue 15 Dec — apply for the extension now",
        MEMBER_PERMIT_AHEAD_BODY,
    )
    expired = _by_item(store, "expiry_soon", date(2026, 12, 20))[ids["permit_expiry"]]
    assert expired.title == "For Kim 2: Residence permit expired on Tue 15 Dec"
    (first,) = ideas(store, "passport_before_permit")
    assert first.title == "For Kim 2: Renew the passport before extending the residence permit"
    assert first.body == (
        "The passport expires on Wed 10 Feb 2027 — soon after their residence permit (Tue 15 Dec). "
        + MEMBER_PASSPORT_FIRST_REST
    )
    pay = _by_item(store, "deadline_soon")[ids["parking_payment"]]
    assert pay.title == "For Kim 2: Pay parking fine: pay by Tue 29 Sep"


def test_another_expiry_of_a_member_s_letter_gets_the_for_form(store: Store, ids: dict[str, str]) -> None:
    (alex,) = _add_people(store, "Alex Rivera")
    card = add_doc(store, "card", kind="other", area="other", title="Library card", doc_date="2025-10-01")
    item = add_item(store, kind="expiry", title="Library card expires", doc_id=card, due_date="2026-10-05")
    plain = _by_item(store, "expiry_soon")[item]
    assert plain.title == "Library card expires: expires Mon 5 Oct"
    _file(store, alex, card)
    named = _by_item(store, "expiry_soon")[item]
    assert (named.title, named.body) == (
        "For Alex Rivera: Library card expires: expires Mon 5 Oct",
        plain.body,
    )
    assert named.fingerprint == plain.fingerprint


def test_passport_before_permit_pairs_one_person_s_documents(store: Store, ids: dict[str, str]) -> None:
    """A child's passport is never set against the person's own permit, nor the person's passport against a
    partner's permit."""
    (alex,) = _add_people(store, "Alex Rivera")
    _file(store, alex, ids["doc_passport"])
    assert ideas(store, "passport_before_permit") == []
    own = add_doc(store, "own passport", kind="identity_document", area="residence", title="Reisepass")
    mine = add_item(store, kind="expiry", title="Passport expires", doc_id=own, due_date="2027-01-20")
    (first,) = ideas(store, "passport_before_permit")
    assert first.title == "Renew your passport before extending your residence permit"
    assert refs_of(first) >= {("item", mine), ("item", ids["permit_expiry"])}
    assert ("item", ids["passport_expiry"]) not in refs_of(first)
    _file(store, alex, ids["doc_permit"])
    (theirs,) = ideas(store, "passport_before_permit")  # each person's pair; the person now has no permit
    assert theirs.title == "Renew Alex Rivera's passport before extending their residence permit"
    assert refs_of(theirs) >= {("item", ids["passport_expiry"]), ("item", ids["permit_expiry"])}
    _file(store, MINE, ids["doc_passport"], ids["doc_permit"])  # "No, it's mine": the person's own again
    assert {idea.title for idea in ideas(store, "passport_before_permit")} == {
        "Renew your passport before extending your residence permit"
    }


def test_student_permit_info_uses_the_person_s_own_permit(store: Store, ids: dict[str, str]) -> None:
    (alex,) = _add_people(store, "Alex Rivera")
    _file(store, alex, ids["doc_permit"])
    (card,) = ideas(store, "student_permit_info")
    assert card.title == "Working on a student permit: know your limits"
    assert card.refs == [] and card.action is not None and card.action.type == "none"
    own = add_doc(
        store,
        "own permit",
        kind="residence_permit",
        area="residence",
        title="Aufenthaltstitel",
        doc_date="2024-03-01",
    )
    (card,) = ideas(store, "student_permit_info")
    assert refs_of(card) == {("document", own)}
    assert card.action is not None and card.action.target_id == own


def test_an_idea_over_letters_of_two_people_names_no_one(store: Store, ids: dict[str, str]) -> None:
    alex, mia = _add_people(store, "Alex Rivera", "Mia Rivera")
    title = "Pay TechMarkt reminder €94.99 by Wed 30 Sep"
    _file(store, alex, ids["doc_dunning"])  # its earlier invoice is still the person's
    (reminder,) = ideas(store, "dunning_escalation")
    assert reminder.title == title
    _file(store, mia, ids["doc_invoice"])
    assert ideas(store, "dunning_escalation")[0].title == title
    _file(store, alex, ids["doc_invoice"])
    assert ideas(store, "dunning_escalation")[0].title == f"For Alex Rivera: {title}"


def test_the_person_s_own_ideas_never_name_a_member(store: Store, ids: dict[str, str]) -> None:
    """Rules about the person's own affairs (their tax return, calendar, profile and move, a sender's Land) and a
    contract's decision never name anyone, even when every letter they refer to is filed for someone; nor does
    an Idea whose letters are the person's, or a to-do without a letter."""
    tax_season = date(2026, 3, 2)
    before = {day: _every_idea(store, day) for day in (TODAY, tax_season)}
    (alex,) = _add_people(store, "Alex Rivera")
    _file(store, alex, ids["doc_parking"])
    after = _every_idea(store)
    assert set(after) == set(before[TODAY])
    named = {fp.split(":")[0] for fp in after if after[fp] != before[TODAY][fp]}
    assert named == {"deadline_soon", "please_check"}  # only the two Ideas about the parking fine
    letters = [doc.id for doc in store.list_documents() if doc.source != "proof"]
    _file(store, alex, *letters)
    never = ("tax_documents", "calendar_outdated", "student_permit_info", "contract_cancel_window")
    seen: set[str] = set()
    for day in (TODAY, tax_season):
        results = run_triggers(store, day)
        for rule in never:
            for idea in results[rule]:
                assert before[day][idea.fingerprint][0] == idea.title, rule
                seen.add(rule)
    assert seen >= {"tax_documents", "student_permit_info", "contract_cancel_window"}
    (books,) = ideas(store, "overdue")  # a to-do without a letter
    assert books.title == "Overdue: Return library books"


def test_without_a_household_every_title_is_as_before(tmp_path: Path) -> None:
    """The demo's Ideas, refreshed by today's rules: every title, body and fingerprint as stored (so its weekly
    review and daily note are asked the same)."""
    shutil.copytree(DEMO_DB, tmp_path / "demo")
    store = Store.open(Paths(tmp_path / "demo"))
    try:
        stored = {s.fingerprint: (s.title, s.body, s.rationale, s.status) for s in store.list_suggestions()}
        assert len(stored) == 17
        run = run_and_reconcile(store, local_today(store))
        assert (run.new, run.expired) == (0, 0)
        assert {
            s.fingerprint: (s.title, s.body, s.rationale, s.status) for s in store.list_suggestions()
        } == stored
    finally:
        store.close()


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
