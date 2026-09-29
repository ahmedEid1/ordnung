"""Read models: dashboard, timeline and life lanes over the seeded ledger."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from helpers_secretary import TODAY, add_doc, add_item, seed_ledger
from ordnung import clock
from ordnung.db.store import Store
from ordnung.models import RefLink
from ordnung.secretary.triggers import run_and_reconcile
from ordnung.views import LANE_ORDER, dashboard, grounding_ratio, lanes, timeline


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ORDNUNG_TODAY", raising=False)
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


# --------------------------------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------------------------------


def test_dashboard_attention_and_upcoming(store: Store, ids: dict[str, str]) -> None:
    board = dashboard(store, TODAY)
    assert (board.today, board.greeting_name, board.simulated) == ("2026-09-28", "Sam", True)
    # overdue first, then by the day to act; the scam letter's payment is never a to-do
    assert [i.id for i in board.attention] == [
        ids["library_task"],
        ids["parking_payment"],
        ids["dunning_payment"],
        ids["semester_fee"],
    ]
    assert [i.id for i in board.upcoming] == [
        ids["tax_refund"],
        ids["abh_appointment"],
        ids["tax_objection"],
        ids["private_item"],
    ]


def test_a_sent_cancellation_leaves_the_decisions_and_life_areas(store: Store, ids: dict[str, str]) -> None:
    """Walkthrough of phase 2: Today still said "Decide on FunkNetz Smart M" after its cancellation was sent."""
    board = dashboard(store, TODAY)
    assert [c.id for c in board.decisions] == [ids["phone"]]
    store.add_draft(
        kind="cancellation", contract_id=ids["phone"], status="sent", sent_at="2026-09-28T09:00:00Z"
    )
    board = dashboard(store, TODAY)
    assert board.decisions == []
    assert not any("Decide on" in area.headline for area in board.areas)


def test_dashboard_decisions_money_and_stats(store: Store, ids: dict[str, str]) -> None:
    board = dashboard(store, TODAY)
    assert [c.id for c in board.decisions] == [ids["phone"]]  # the gym's cancellation is confirmed
    phone = board.decisions[0]
    assert phone.computed is not None and phone.computed.send_by == "2026-10-08"
    money = board.money
    assert money.due_this_month == 119.99
    assert money.fixed_costs_monthly == 165.89
    assert money.by_category == {"energy": 48.0, "gym": 24.9, "mobile": 29.99, "transport": 63.0}
    assert [i.id for i in money.upcoming_payments] == [
        ids["parking_payment"],
        ids["dunning_payment"],
        ids["semester_fee"],
        ids["private_item"],
    ]
    assert (board.stats.documents, board.stats.contracts, board.stats.open_items) == (12, 5, 12)
    assert board.stats.verified_ratio == 0.5  # objection found in the letter, parking fine not
    assert [d.doc_date for d in board.recent_documents][:2] == ["2026-09-25", "2026-09-24"]
    assert len(board.recent_documents) == 6


def test_recent_letters_are_ordered_by_the_day_they_are_listed_under(store: Store) -> None:
    """UI audit R1-backend-1: the Today page lists a letter under the day it arrived (else its own date,
    else when it was added), so the newest six are picked and ordered by that day too."""
    arrived_later = add_doc(store, "a", received_date="2026-09-21", doc_date="2026-09-01", title="A")
    dated_later = add_doc(store, "b", received_date="2026-09-20", doc_date="2026-09-20", title="B")
    undated = add_doc(store, "c", title="C")  # listed under the day it was added
    only_dated = add_doc(store, "d", doc_date="2026-09-22", title="D")
    board = dashboard(store, TODAY)
    added = board.recent_documents[[d.id for d in board.recent_documents].index(undated)].created_at[:10]
    assert added > "2026-09-22"
    assert [d.id for d in board.recent_documents] == [undated, only_dated, arrived_later, dated_later]


def test_dashboard_areas(store: Store, ids: dict[str, str]) -> None:
    areas = {area.area: area for area in dashboard(store, TODAY).areas}
    assert list(areas) == [
        "residence",
        "tax",
        "study",
        "work",
        "home",
        "money",
        "health",
        "mobility",
        "leisure",
    ]
    assert areas["study"].status == "urgent" and areas["study"].headline == "Overdue: Return library books"
    # the app's one urgency scale: tomorrow is urgent, two days out needs attention (UI audit R1-backend-3)
    assert areas["mobility"].status == "urgent"  # the parking fine, due tomorrow
    assert areas["money"].status == "attention"  # the reminder, due in two days
    assert areas["home"].status == "ok"  # the phone's send-by, ten days out
    assert areas["home"].headline == "Decide on FunkNetz mobile — Thu 8 Oct"
    assert areas["home"].next_date == "2026-10-08"
    assert areas["residence"].status == "ok" and areas["residence"].count == 3
    assert areas["work"].headline == "1 active contract"
    assert areas["leisure"].label == "Leisure"
    assert (areas["residence"].label, areas["mobility"].label) == ("Residence permit", "Getting around")


def test_area_dates_follow_the_one_urgency_scale(store: Store) -> None:
    """UI audit R1-backend-3: a direct debit is listed by the day the money moves (not a "send by" a
    day earlier) and never turns urgent; a deadline tomorrow does. An appointment tomorrow needs attention,
    a direct debit none (walkthrough of phase 2: "Getting around · Needs attention" for the Deutschlandticket)."""
    ticket = add_doc(store, "ticket", area="mobility", kind="contract")
    add_item(
        store,
        kind="payment",
        title="Monatliche Abbuchung Deutschlandticket",
        action="Ensure sufficient funds for the direct debit",
        doc_id=ticket,
        area="mobility",
        due_date="2026-09-29",
        send_by="2026-09-28",
        amount=63.0,
        direction="out",
    )
    dentist = add_doc(store, "dentist", area="health", kind="appointment")
    add_item(store, kind="appointment", title="Dentist", doc_id=dentist, area="health", due_date="2026-09-28")
    tax = add_doc(store, "tax", area="tax", kind="tax_assessment")
    add_item(store, kind="deadline", title="Object", doc_id=tax, area="tax", due_date="2026-09-29")
    areas = {area.area: area for area in dashboard(store, TODAY).areas}
    ticket_area = areas["mobility"]
    assert ticket_area.headline == "Monatliche Abbuchung Deutschlandticket — Tue 29 Sep"
    assert (ticket_area.next_date, ticket_area.status) == ("2026-09-29", "ok")
    assert areas["health"].status == "attention"  # an appointment today: nothing to send
    assert areas["tax"].status == "urgent"


def test_a_fee_paid_on_site_has_no_day_to_transfer_by(store: Store) -> None:
    """UI audit R1-backend-8: the €100 residence fee, paid by girocard at the appointment, was listed under
    a bank transfer's send-by day ("transfer by 13 Oct"). Its day is the appointment's, it never turns
    urgent (nothing to send) and the timeline says how to pay instead of "Send by"."""
    permit = add_doc(store, "permit", area="residence", kind="residence_permit", title="Appointment")
    fee = add_item(
        store,
        kind="payment",
        title="Fee for residence permit extension application",
        action="Pay the €100 fee on site at the appointment by girocard (cash is not accepted).",
        doc_id=permit,
        area="residence",
        due_date="2026-09-29",
        due_time="10:30",
        send_by="2026-09-28",
        amount=100.0,
        direction="out",
    )
    area = {a.area: a for a in dashboard(store, TODAY).areas}["residence"]
    assert (area.next_date, area.status) == ("2026-09-29", "attention")
    assert area.headline == "Fee for residence permit extension application — Tue 29 Sep"
    entry = next(e for e in timeline(store, date(2026, 9, 1), date(2026, 12, 31)) if e.id == fee)
    assert entry.subtitle == "Pay the €100 fee on site at the appointment by girocard (cash is not accepted)."


def test_timeline_says_transfer_by_for_transfers_and_nothing_to_send_for_a_direct_debit(store: Store) -> None:
    """UI audit R2-inbox-timeline-contracts-3: every dated to-do with a send-by day read "Send by …" on the
    timeline — a bank transfer too (Today, the verdict and the receipt say "Transfer by …"), and even a
    direct debit, which the sender collects itself. A posted objection keeps "Send by"."""
    invoice = add_doc(store, "reminder", kind="dunning", title="1st payment reminder")
    transfer = add_item(
        store,
        kind="payment",
        title="Pay outstanding invoice plus reminder fee",
        doc_id=invoice,
        due_date="2026-10-01",
        send_by="2026-09-29",
        amount=94.99,
        direction="out",
    )
    ticket = add_doc(store, "ticket", kind="contract", title="Deutschlandticket")
    debit = add_item(
        store,
        kind="payment",
        title="Monatliche Abbuchung Deutschlandticket €63.00",
        doc_id=ticket,
        due_date="2026-09-30",
        send_by="2026-09-28",
        amount=63.0,
        direction="out",
    )
    tax = add_doc(store, "tax", kind="tax_assessment", title="Tax assessment")
    objection = add_item(
        store, kind="deadline", title="Objection", doc_id=tax, due_date="2026-10-21", send_by="2026-10-15"
    )
    refund = add_item(
        store,
        kind="payment",
        title="Tax refund",
        doc_id=tax,
        due_date="2026-10-20",
        amount=310.0,
        direction="in",
    )
    entries = {e.id: e for e in timeline(store, date(2026, 9, 1), date(2026, 12, 31))}
    assert entries[transfer].subtitle == "Transfer by Tue 29 Sep"
    assert entries[debit].subtitle == "Collected by direct debit"
    assert entries[objection].subtitle == "Send by Thu 15 Oct"
    assert entries[refund].subtitle is None  # money coming in: nobody sends it


def test_letters_about_the_home_are_never_under_the_residence_permit(store: Store) -> None:
    """UI audit R1-backend-2: the model may read a running-costs statement under "residence" (the
    residence-permit area); Today, the timeline and the lanes show it and its to-dos under Home."""
    statement = add_doc(store, "statement", area="residence", kind="utility_bill", title="Running costs 2025")
    back_payment = add_item(
        store,
        kind="payment",
        title="Back payment",
        doc_id=statement,
        area="residence",
        due_date="2026-10-09",
        send_by="2026-10-08",
        amount=18.4,
        direction="out",
    )
    permit = add_doc(store, "permit", area="residence", kind="residence_permit", title="Appointment")
    add_item(
        store, kind="appointment", title="Appointment", doc_id=permit, area="residence", due_date="2026-10-14"
    )
    areas = {area.area: area for area in dashboard(store, TODAY).areas}
    assert areas["home"].headline == "Back payment — Thu 8 Oct" and areas["home"].count == 1
    assert areas["residence"].headline == "Appointment — Wed 14 Oct" and areas["residence"].count == 1
    entries = {e.id: e for e in timeline(store, date(2026, 9, 1), date(2026, 12, 31))}
    assert (entries[statement].area, entries[back_payment].area, entries[permit].area) == (
        "home",
        "home",
        "residence",
    )
    year = {lane.id: lane for lane in lanes(store, date(2026, 9, 1), date(2027, 8, 31))}
    assert [m.label for m in year["home"].markers] == ["Back payment"]  # under €50, and not in Money
    assert [m.label for m in year["residence"].markers] == ["Appointment"]


def test_dashboard_suggestions_are_new_ideas_by_priority(store: Store, ids: dict[str, str]) -> None:
    run_and_reconcile(store, TODAY)
    ideas = dashboard(store, TODAY).suggestions
    assert ideas and ideas[0].priority == "critical"
    ranks = ["critical", "high", "normal", "low"]
    assert [ranks.index(i.priority) for i in ideas] == sorted(ranks.index(i.priority) for i in ideas)
    store.update_suggestion(ideas[0].id, status="dismissed")
    assert ideas[0].id not in {i.id for i in dashboard(store, TODAY).suggestions}


def test_dashboard_of_an_empty_store(store: Store) -> None:
    board = dashboard(store, TODAY)
    assert board.attention == [] and board.areas == [] and board.stats.verified_ratio == 0.0
    assert board.greeting_name == ""


def test_grounding_ratio_counts_user_confirmations(store: Store, ids: dict[str, str]) -> None:
    store.update_item(ids["parking_payment"], grounding="user")
    assert grounding_ratio(store.list_items()) == 1.0


# --------------------------------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------------------------------


def test_timeline_merges_letters_items_contracts_and_sent_letters(store: Store, ids: dict[str, str]) -> None:
    entries = timeline(store, date(2026, 9, 1), date(2026, 10, 31))
    by_id = {entry.id: entry for entry in entries}
    assert [e.date for e in entries] == sorted(e.date for e in entries)
    assert by_id[ids["doc_tax"]].type == "document" and by_id[ids["doc_tax"]].past
    assert by_id[ids["doc_tax"]].party_name == "Finanzamt Musterstadt"
    library = by_id[ids["library_task"]]
    assert (library.type, library.status, library.past) == ("task", "overdue", True)
    objection = by_id[ids["tax_objection"]]
    assert (objection.date, objection.subtitle, objection.past) == ("2026-10-21", "Send by Thu 15 Oct", False)
    assert by_id[f"{ids['phone']}:send_by"].date == "2026-10-08"
    assert by_id[f"{ids['phone']}:cancel_by"].title == "Cancellation of FunkNetz mobile must arrive"
    sent = by_id[ids["draft_uni"]]
    assert (sent.type, sent.date, sent.title) == ("draft", "2026-09-05", "Sent: Question about my enrolment")
    assert ids["permit_expiry"] not in by_id  # 15 Dec is outside the range
    assert by_id[ids["invoice_payment"]].status == "done"  # done items stay on the timeline
    appointment = by_id[ids["abh_appointment"]]
    assert appointment.time == "10:00"


def test_timeline_says_money_in_and_set_aside_payments_are_never_overdue(
    store: Store, ids: dict[str, str]
) -> None:
    """Walkthrough of phase 2: "Salary payment received … Overdue" (money that came in) and an invoice its
    payment reminder replaced showed as overdue on the timeline. Money in is never overdue and says so
    (``direction``); a to-do that is not one to act on says why (``aside``)."""
    salary = add_item(
        store,
        kind="payment",
        title="Salary payment received (August 2026)",
        due_date="2026-09-20",
        amount=1285.2,
        currency="EUR",
        direction="in",
    )
    old = add_item(
        store,
        kind="payment",
        title="Security deposit (Kaution)",
        due_date="2025-10-01",
        amount=1280.0,
        currency="EUR",
        direction="out",
        filed_on="2026-09-20",
    )
    entries = {e.id: e for e in timeline(store, date(2025, 9, 1), date(2026, 10, 31))}
    assert (entries[salary].status, entries[salary].direction, entries[salary].aside) == ("open", "in", None)
    assert (entries[old].status, entries[old].aside) == ("open", "history")
    assert (
        entries[ids["parking_payment"]].direction == "out" and entries[ids["parking_payment"]].aside is None
    )
    assert entries[ids["library_task"]].direction is None


def test_timeline_past_flag_follows_today(store: Store, ids: dict[str, str]) -> None:
    entries = timeline(store, date(2026, 12, 1), date(2026, 12, 31), today=date(2027, 1, 1))
    permit = next(e for e in entries if e.id == ids["permit_expiry"])
    assert permit.past and permit.type == "expiry"


# --------------------------------------------------------------------------------------------------
# lanes
# --------------------------------------------------------------------------------------------------


def test_lanes_only_areas_with_data_in_fixed_order(store: Store, ids: dict[str, str]) -> None:
    result = lanes(store, date(2026, 9, 1), date(2027, 8, 31))
    lane_ids = [lane.id for lane in result]
    assert lane_ids == ["residence", "contracts", "tax", "study", "work", "money", "health", "mobility"]
    assert lane_ids == [lane for lane in LANE_ORDER if lane in lane_ids]


def test_residence_lane_shows_validity_and_apply_before(store: Store, ids: dict[str, str]) -> None:
    residence = next(
        lane for lane in lanes(store, date(2026, 9, 1), date(2027, 8, 31)) if lane.id == "residence"
    )
    bars = {bar.id: bar for bar in residence.bars}
    permit = bars[ids["permit_expiry"]]
    assert (permit.label, permit.kind, permit.start, permit.end) == (
        "Residence permit",
        "validity",
        "2026-09-01",
        "2026-12-15",
    )
    assert permit.markers[0].kind == "deadline" and "Apply before" in permit.markers[0].label
    assert permit.status == "attention"
    assert bars[ids["passport_expiry"]].end == "2027-02-10"
    assert [m.label for m in residence.markers] == ["Appointment at the Ausländerbehörde"]


def test_contracts_lane_has_notice_windows(store: Store, ids: dict[str, str]) -> None:
    contracts = next(
        lane for lane in lanes(store, date(2026, 9, 1), date(2027, 8, 31)) if lane.id == "contracts"
    )
    bars = {bar.id: bar for bar in contracts.bars}
    assert set(bars) >= {ids["phone"], ids["power"], ids["ticket"], f"{ids['phone']}:notice"}
    assert ids["job"] not in bars  # employment lives in the Work lane
    phone = bars[ids["phone"]]
    assert (phone.start, phone.end, phone.kind) == ("2026-09-01", "2026-11-14", "contract")
    notice = bars[f"{ids['phone']}:notice"]
    assert (notice.kind, notice.start, notice.end, notice.status) == (
        "notice_window",
        "2026-09-08",
        "2026-10-14",
        "urgent",  # send-by within 14 days
    )
    assert [(m.kind, m.date) for m in notice.markers] == [
        ("send_by", "2026-10-08"),
        ("cancel_by", "2026-10-14"),
    ]
    assert bars[ids["power"]].end == "2027-08-31"  # any-time contract: runs to the end of the range


def test_a_sent_cancellation_has_no_notice_window_left(store: Store, ids: dict[str, str]) -> None:
    """Final review: the Timeline still drew the phone's "Send by" window after its cancellation was sent."""
    store.add_draft(
        kind="cancellation", contract_id=ids["phone"], status="sent", sent_at="2026-09-28T09:00:00Z"
    )
    contracts = next(
        lane for lane in lanes(store, date(2026, 9, 1), date(2027, 8, 31)) if lane.id == "contracts"
    )
    bars = {bar.id: bar for bar in contracts.bars}
    assert f"{ids['phone']}:notice" not in bars
    assert (bars[ids["phone"]].end, bars[ids["phone"]].status) == ("2026-11-14", "ok")


def test_tax_work_and_money_lanes(store: Store, ids: dict[str, str]) -> None:
    by_id = {lane.id: lane for lane in lanes(store, date(2026, 9, 1), date(2027, 8, 31))}
    objection = by_id["tax"].bars[0]
    assert (objection.start, objection.end, objection.kind) == ("2026-09-15", "2026-10-21", "period")
    assert [m.kind for m in objection.markers] == ["send_by", "deadline"]
    assert by_id["work"].bars[0].end == "2027-03-31"
    money = [m.label for m in by_id["money"].markers]
    assert "Pay TechMarkt reminder" in money
    assert "Pay broadcasting fee" not in money  # scam letter
    # every payment in its own area's lane, whatever the amount (UI audit R1-backend-4)
    assert [m.label for m in by_id["health"].markers] == ["Therapy invoice"]
    assert [m.label for m in by_id["mobility"].markers] == ["Pay parking fine"]  # €25
    assert by_id["mobility"].label == "Getting around"


def test_every_lane_mark_says_its_area_and_what_it_stands_for(store: Store, ids: dict[str, str]) -> None:
    """UI audit R1-backend-4 / R1-lanes-10: the timeline filters the lanes by area and opens a mark's
    to-do or contract; a contract with no end date says so (its end is only where the lanes stop)."""
    by_id = {lane.id: lane for lane in lanes(store, date(2026, 9, 1), date(2027, 8, 31))}
    for lane in by_id.values():
        for bar in lane.bars:
            assert bar.area is not None and bar.ref is not None, bar
            for marker in bar.markers:
                assert (marker.area, marker.ref) == (bar.area, bar.ref), marker
        for marker in lane.markers:
            assert marker.area is not None and marker.ref is not None, marker
    parking = next(m for m in by_id["mobility"].markers if m.label == "Pay parking fine")
    assert (parking.area, parking.ref) == ("mobility", RefLink(type="item", id=ids["parking_payment"]))
    contracts = {bar.id: bar for bar in by_id["contracts"].bars}
    assert (contracts[ids["phone"]].area, contracts[ids["ticket"]].area) == ("home", "mobility")
    assert contracts[f"{ids['phone']}:notice"].markers[0].ref == RefLink(type="contract", id=ids["phone"])
    assert not contracts[ids["phone"]].open_end  # its minimum term ends on 14 Nov
    assert contracts[ids["power"]].open_end  # cancellable any time: no end date
    assert not by_id["work"].bars[0].open_end  # the fixed-term job ends on 31 Mar


def test_lanes_clip_to_the_range(store: Store, ids: dict[str, str]) -> None:
    result = lanes(store, date(2027, 1, 1), date(2027, 1, 31))
    assert [lane.id for lane in result] == ["residence", "contracts", "work"]
    for lane in result:
        for bar in lane.bars:
            assert "2027-01-01" <= bar.start <= bar.end <= "2027-01-31"


def test_attention_skips_history_and_past_items_of_letters_that_need_checking(store: Store) -> None:
    from helpers_secretary import TODAY, add_doc, add_item
    from ordnung.models import Evidence
    from ordnung.views import dashboard

    doc = add_doc(store, "lease", kind="rent_lease", area="home", title="Lease", doc_date="2025-09-15")
    store.update_document(doc, status="needs_review")
    unsure = [Evidence(doc_id=doc, quote="…", grounding="unverified")]
    history = add_item(
        store,
        kind="payment",
        title="Deposit",
        due_date="2025-10-01",
        filed_on=TODAY.isoformat(),
        doc_id=doc,
        amount=1560.0,
        direction="out",
        evidence=unsure,
        grounding="unverified",
    )
    past_milestone = add_item(
        store,
        kind="milestone",
        title="Probation ends",
        due_date="2026-07-01",
        filed_on=TODAY.isoformat(),
        doc_id=doc,
        evidence=unsure,
        grounding="unverified",
    )
    to_check = add_item(
        store,
        kind="deadline",
        title="Return the form",
        due_date="2026-11-20",
        filed_on=TODAY.isoformat(),
        doc_id=doc,
        evidence=unsure,
        grounding="unverified",
    )
    attention = {item.id for item in dashboard(store, TODAY).attention}
    assert history not in attention
    assert past_milestone not in attention
    assert to_check in attention


def test_continuation_says_whether_a_contract_renews_or_runs_on() -> None:
    """Demo finding: Ask told Sam the phone contract would "auto-renew for another term"; under § 56 TKG
    it runs on and can be cancelled any month."""
    from ordnung.models import Contract, ContractComputation
    from ordnung.views import continuation

    stamps = {"created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}
    phone = Contract(id="ctr_p", name="Phone", renewal_term_months=0, **stamps)
    assert "no fixed term" in continuation(phone, ContractComputation(regime="tkg56"))
    gym = Contract(id="ctr_g", name="Old gym", renewal_term_months=12, **stamps)
    assert (
        continuation(gym, ContractComputation(regime="bgb309_old"))
        == "It renews for 12 months unless it is cancelled in time."
    )
    assert "no fixed term" in continuation(gym, ContractComputation(regime="bgb309_new"))


@pytest.mark.parametrize(
    ("category", "notice", "caveat"),
    [
        ("employment", "(§ 15 Abs. 4 TzBfG)", "(§ 15 Abs. 6 TzBfG)."),
        (
            "rent",
            "(§ 575 Abs. 1 BGB)",
            "(§ 545 BGB) — unless the lease excludes that rule, as many leases do.",
        ),
        ("other", "", ""),
    ],
)
def test_a_fixed_term_contract_ends_by_itself(category: str, notice: str, caveat: str) -> None:
    """Review findings: the working-student contract "continues with no fixed term" if nothing is done —
    wrong under § 15 Abs. 1 TzBfG: it ends when its time runs out, and only continued work the employer
    knows of and does not object to makes it open-ended (§ 15 Abs. 6 TzBfG). A flat let without a written
    reason for its term counts as open-ended (§ 575 Abs. 1 S. 2 BGB), so Ask's record says to check the
    contract. Final review: round 4 said a fixed-term job "may still need notice to end then" — wrong: § 15
    Abs. 4 TzBfG only allows ending it *earlier* when agreed; an undated notice would end the job at the
    next possible date instead. And § 575 does not apply in a student hall (§ 549 Abs. 3 BGB)."""
    from ordnung.models import Contract, ContractTerms
    from ordnung.rules import RuleContext
    from ordnung.rules.contracts import compute_contract
    from ordnung.views import continuation, fixed_term_summary

    stamps = {"created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}
    contract = Contract(
        id="ctr_f", name="Working student", category=category, start_date="2026-04-01", end_date="2027-03-31",
        initial_term_months=12, **stamps,
    )  # fmt: skip
    terms = ContractTerms(
        category=category, start_date="2026-04-01", end_date="2027-03-31", initial_term_months=12
    )
    comp = compute_contract(terms, RuleContext(today=TODAY))
    assert "fixed_term" in comp.rule_ids
    text = continuation(contract, comp, today=TODAY)
    assert "continues with no fixed term and can then be cancelled" not in text
    summary = fixed_term_summary(comp, today=TODAY)
    if category == "employment":
        assert text.startswith(
            "Its fixed term ends on Wed 31 Mar 2027. A fixed-term job ends then by itself, with no notice "
            "(§ 15 Abs. 1 TzBfG). Ending it earlier by ordinary notice needs a notice clause"
        )
        assert notice in text and text.endswith(caveat) and "may still need notice" not in text
        # final review 2: never "possible only if …" — an agreement or notice for cause end it early too
        assert "possible only if" not in text
        assert "(§ 623 BGB)" in text and "(§ 626 BGB)" in text
        assert "register as job-seeking" in text and "(§ 38 Abs. 1 SGB III)" in text
        assert "job-seeking" in (summary or "")
        assert summary is not None and "ends then by itself" in summary and "(§ 15 Abs. 1 TzBfG)" in summary
        assert "may still need notice" not in summary
    elif notice:
        assert text.startswith("Its fixed term ends on Wed 31 Mar 2027.")
        assert notice in text and "check the contract" in text and text.endswith(caveat)
        assert "student or youth hall of residence" in text and "(§ 549 Abs. 2 and 3 BGB)" in text
        # final review 2: "then" read as the case the landlord gave a reason; the exceptions are examples
        assert "If it counts as open-ended, leaving needs notice" in text and "; then leaving" not in text
        assert "Exceptions include" in text and "people in urgent need" in text
        assert "not let for lasting use with a family or partner" in text
        assert "no cancellation" not in text
        assert summary is not None and "may still need notice" in summary
    else:
        assert text == "It ends by itself on Wed 31 Mar 2027; no cancellation is needed."
        assert summary is None
    later = date(2027, 4, 2)
    past = continuation(contract, comp, today=later)
    past_summary = fixed_term_summary(comp, today=later)
    if not notice:
        assert past == "Its fixed term ended on Wed 31 Mar 2027." and past_summary is None
        return
    # final review 3: an active job or flat let past its end date was recorded as "ended", with none of
    # the caveats — though it may never have ended (§ 575 Abs. 1 S. 2 BGB) or continue by conduct
    assert past.startswith("Its fixed term's end date, Wed 31 Mar 2027, has passed. If you still ")
    assert "ended on Wed 31 Mar 2027." not in past
    assert ("(§ 15 Abs. 6 TzBfG)" if category == "employment" else "(§ 545 BGB)") in past
    assert past_summary is not None and "has passed" in past_summary and "may" in past_summary
    assert "ended on" not in past_summary
    if category == "rent":
        assert "(§ 575 Abs. 1 S. 2 BGB)" in past and "Check the contract or get advice." in past
        # final review 3: a fixed term that fails § 575 is often read as a waiver of notice until its end
        assert "VIII ZR 388/12" in text and "may not be possible" in text
        assert summary is not None and "or earlier" not in summary
    # a contract that is no longer active keeps the engine's "ended"
    assert fixed_term_summary(comp, today=later, active=False) is None


def test_a_to_do_whose_posting_time_passed_says_when_it_must_arrive(
    store: Store, ids: dict[str, str]
) -> None:
    """Review round 4 of phase 2: the inbox and timeline said "Send by Mon 28 Sep · today" for an objection due
    that day — a letter posted then arrives too late. The receipt's warning (the usual sending time has passed)
    makes it "Must arrive by", here and in the web's Today and inbox rows, which read the same words."""
    from pathlib import Path

    from ordnung.models import ComputationReceipt
    from ordnung.rules.deadlines import SENDING_TIME_PASSED, sending_time_passed

    late = ComputationReceipt(
        due_date="2026-09-29",
        send_by="2026-09-28",
        warnings=[
            f"{SENDING_TIME_PASSED} — send it today, by the fastest channel allowed (online, fax or in person)."
        ],
    )
    store.update_item(ids["tax_objection"], due_date="2026-09-29", send_by="2026-09-28", computation=late)
    entries = {entry.id: entry for entry in timeline(store, date(2026, 9, 1), date(2026, 10, 31))}
    assert entries[ids["tax_objection"]].subtitle == "Must arrive by Tue 29 Sep"
    assert sending_time_passed(late) and not sending_time_passed(None)
    web = Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "today" / "selection.ts"
    assert f'SENDING_TIME_PASSED = "{SENDING_TIME_PASSED}"' in web.read_text(encoding="utf-8")
