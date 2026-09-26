"""Read models: dashboard, timeline and life lanes over the seeded ledger."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.db.store import Store
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
    assert areas["money"].status == "urgent"
    assert areas["home"].status == "attention"
    assert areas["home"].headline == "Decide on FunkNetz mobile — Thu 8 Oct"
    assert areas["home"].next_date == "2026-10-08"
    assert areas["residence"].status == "ok" and areas["residence"].count == 3
    assert areas["work"].headline == "1 active contract"
    assert areas["leisure"].label == "Leisure"


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
    assert lane_ids == ["residence", "contracts", "tax", "study", "work", "money"]
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


def test_tax_work_and_money_lanes(store: Store, ids: dict[str, str]) -> None:
    by_id = {lane.id: lane for lane in lanes(store, date(2026, 9, 1), date(2027, 8, 31))}
    objection = by_id["tax"].bars[0]
    assert (objection.start, objection.end, objection.kind) == ("2026-09-15", "2026-10-21", "period")
    assert [m.kind for m in objection.markers] == ["send_by", "deadline"]
    assert by_id["work"].bars[0].end == "2027-03-31"
    money = [m.label for m in by_id["money"].markers]
    assert "Pay TechMarkt reminder" in money and "Therapy invoice" in money
    assert "Pay broadcasting fee" not in money  # scam letter
    assert "Pay parking fine" not in money  # small payments (< €50) stay off the lanes


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
    knows of and does not object to makes it open-ended (§ 15 Abs. 6 TzBfG). And (review round 4) "no
    cancellation is needed" is wrong for exactly these two: a fixed-term job can be ended with agreed
    ordinary notice (§ 15 Abs. 4 TzBfG), and a flat let without a written reason for its term counts as
    open-ended (§ 575 Abs. 1 S. 2 BGB) — so Ask's record says to check the contract instead."""
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
    if notice:
        assert text.startswith("Its fixed term ends on Wed 31 Mar 2027.")
        assert notice in text and "check the contract" in text and text.endswith(caveat)
        assert "no cancellation" not in text
        assert summary is not None and "may still need notice" in summary
    else:
        assert text == "It ends by itself on Wed 31 Mar 2027; no cancellation is needed."
        assert summary is None
    assert continuation(contract, comp, today=date(2027, 4, 2)) == "Its fixed term ended on Wed 31 Mar 2027."
    assert fixed_term_summary(comp, today=date(2027, 4, 2)) is None
