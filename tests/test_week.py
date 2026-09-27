"""The weekly session (``ordnung.secretary.week``): the prompt policy, each step over a seeded ledger, the
"since your last session" window, the two stored moments and ``/api/week``."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import TODAY, add_doc, add_item, seed_ledger
from ordnung import clock
from ordnung.db.store import Store
from ordnung.models import DateSpec, Evidence, WeeklySession, WeekStep
from ordnung.secretary.week import (
    AT_APPOINTMENT_NOTE,
    DISMISSED_KEY,
    MAX_ROWS,
    MISSED_POST_NOTE,
    MISSED_TRANSFER_NOTE,
    OVERDUE_NOTE,
    PROOF_BY_CHANNEL,
    SESSION_KEY,
    Moment,
    SessionState,
    next_prompt_day,
    prompt_due,
    session_state,
)
from ordnung.views import weekly_session
from test_api_support import api_for

SUNDAY = date(2026, 10, 4)
assert TODAY.weekday() == 0 and SUNDAY.weekday() == 6


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


def _stamp(day: date, time: str = "10:00:00") -> str:
    return f"{day.isoformat()}T{time}Z"


def _moment(day: date, time: str = "10:00:00") -> Moment:
    return Moment(day, datetime.fromisoformat(_stamp(day, time)))


def _stored(day: date, time: str = "10:00:00") -> str:
    """A moment as the week module stores it in meta."""
    return f"{day.isoformat()}|{_stamp(day, time)}"


def _created(store: Store, doc_id: str, stamp: str) -> None:
    """Date a letter's arrival in Ordnung (the store stamps it with the real clock)."""
    with store.tx() as conn:
        conn.execute("UPDATE documents SET created_at = ? WHERE id = ?", (stamp, doc_id))


def _all_created(store: Store, stamp: str) -> None:
    for doc in store.list_documents(include_deleted=True):
        _created(store, doc.id, stamp)


def _step(week: WeeklySession, step_id: str) -> WeekStep:
    return next(step for step in week.steps if step.id == step_id)


def _refs(step: WeekStep) -> list[str]:
    return [entry.ref.id for entry in step.entries]


# --------------------------------------------------------------------------------------------------
# the prompt: one gentle suggestion, never nagging
# --------------------------------------------------------------------------------------------------


def _ago(days: int, today: date = TODAY) -> Moment:
    return _moment(today - timedelta(days=days))


@pytest.mark.parametrize(
    ("state", "today", "due"),
    [
        (SessionState(), TODAY, True),  # never done
        (SessionState(last_session=_ago(6)), TODAY, False),
        (SessionState(last_session=_ago(7)), TODAY, True),  # a week on
        (SessionState(last_session=_ago(30)), TODAY, True),
        (SessionState(last_session=_ago(4, SUNDAY)), SUNDAY, True),  # Sundays: 4 days after
        (SessionState(last_session=_ago(3, SUNDAY)), SUNDAY, False),
        (SessionState(last_session=_ago(0, SUNDAY)), SUNDAY, False),
        (SessionState(last_session=_ago(10), dismissed=_ago(2)), TODAY, False),  # "Not now" counts
        (SessionState(dismissed=_ago(7)), TODAY, True),
        (SessionState(last_session=_moment(TODAY + timedelta(days=3))), TODAY, False),  # the clock went back
    ],
)
def test_prompt_policy(state: SessionState, today: date, due: bool) -> None:
    assert prompt_due(state, today) is due


@pytest.mark.parametrize(
    ("state", "today", "upcoming"),
    [
        (SessionState(), TODAY, None),  # due now
        (SessionState(last_session=_moment(TODAY)), TODAY, SUNDAY),  # Monday → the Sunday after (6 days)
        (SessionState(last_session=_moment(date(2026, 9, 30))), date(2026, 9, 30), SUNDAY),  # Wed → Sun (4)
        (SessionState(last_session=_moment(date(2026, 10, 1))), date(2026, 10, 1), date(2026, 10, 8)),
        (SessionState(dismissed=_moment(TODAY)), date(2026, 9, 29), SUNDAY),
    ],
)
def test_the_session_says_when_today_suggests_it_next(
    state: SessionState, today: date, upcoming: date | None
) -> None:
    """ "Session saved — Today suggests the next one on …": the day the policy names, not "in a week"."""
    assert next_prompt_day(state, today) == upcoming
    if upcoming is not None:
        assert prompt_due(state, upcoming) and not prompt_due(state, upcoming - timedelta(days=1))


def test_an_unreadable_stored_moment_counts_as_never(store: Store) -> None:
    store.set_meta(SESSION_KEY, "last Tuesday")
    store.set_meta(DISMISSED_KEY, _stored(TODAY))
    assert session_state(store) == SessionState(last_session=None, dismissed=_moment(TODAY))
    for broken in (
        "2026-09-28",
        "2026-09-28|soon",
        "Monday|2026-09-28T10:00:00Z",
        "2026-9-8|2026-09-28T10:00:00Z",
    ):
        store.set_meta(SESSION_KEY, broken)
        assert session_state(store).last_session is None, broken


def test_no_prompt_when_there_is_nothing_to_review(store: Store) -> None:
    week = weekly_session(store, TODAY)
    assert week.last_session is None and not any(step.entries for step in week.steps)
    assert week.due is False and week.next_deadline is None and week.overdue == 0
    # nothing overdue or due today: no "Act now" step; the first session looks at the last 7 days
    assert week.steps[0].title == "New in the last 7 days"
    assert [step.summary for step in week.steps] == [
        "No new letters since Mon 21 Sep",
        "Nothing to check",
        "Nothing to pay this week",
        "Nothing to post",
        "Not waiting for any reply",
        "No decisions due in the next 30 days",
        "Nothing to file this week",
    ]


# --------------------------------------------------------------------------------------------------
# the steps over the seeded ledger
# --------------------------------------------------------------------------------------------------


def test_the_steps_over_the_seeded_ledger(store: Store, ids: dict[str, str]) -> None:
    _all_created(store, _stamp(TODAY - timedelta(days=1)))
    week = weekly_session(store, TODAY)
    # an overdue task opens the session ("Act now"); then the seven steps
    assert [step.id for step in week.steps] == [
        "now",
        "new",
        "check",
        "pay",
        "post",
        "waiting",
        "decide",
        "file",
    ]
    assert (week.today, week.since, week.last_session, week.due, week.minutes) == (
        "2026-09-28",
        "2026-09-21",
        None,
        True,
        10,
    )
    now = _step(week, "now")
    assert _refs(now) == [ids["library_task"]] and now.summary == "1 overdue"
    assert (now.entries[0].date, now.entries[0].date_role, now.entries[0].overdue) == (
        "2026-09-20",
        "by",
        True,
    )
    assert now.entries[0].note == OVERDUE_NOTE and now.entries[0].tone == "danger"
    assert week.overdue == 1

    new = _step(week, "new")
    assert new.summary == "12 letters since Mon 21 Sep" and len(new.entries) == MAX_ROWS and new.more == 4
    # letters that need the person come first: the one to check, the scam, those with open to-dos
    notes = {entry.ref.id: (entry.note, entry.tone) for entry in new.entries}
    assert notes[ids["doc_parking"]] == ("Please check what Ordnung read.", "warn")
    assert notes[ids["doc_scam"]] == ("Shows signs of a scam — don't pay or reply yet.", "danger")
    assert notes[ids["doc_tax"]] == ("2 open to-dos", "neutral")
    assert all(entry.date_role == "added" for entry in new.entries)

    check = _step(week, "check")
    assert _refs(check) == [ids["parking_payment"]]
    assert check.entries[0].note == "Not found in the letter — compare it with the letter."

    pay = _step(week, "pay")
    # no scam demand, no invoice payment the reminder took over, no money coming in
    assert _refs(pay) == [ids["parking_payment"], ids["dunning_payment"], ids["semester_fee"]]
    assert pay.total == 440.49 and pay.total_other_currencies == {}
    assert pay.entries[0].note == "The amount wasn't confirmed against the letter — check it before paying."
    assert pay.entries[1].item is not None and pay.entries[1].item.id == ids["dunning_payment"]
    assert pay.summary == "3 transfers to make · 1 more payment in the next 30 days"

    waiting = _step(week, "waiting")
    assert _refs(waiting) == [ids["followup"]]
    assert waiting.entries[0].note == "No reply yet? Call them or send a short reminder."

    decide = _step(week, "decide")
    assert _refs(decide) == [ids["phone"], ids["tax_objection"]]
    assert [entry.date_role for entry in decide.entries] == ["decide_by", "send_by"]
    # the day to post it, with the deadline itself beside it
    assert (decide.entries[1].date, decide.entries[1].due_date) == ("2026-10-15", "2026-10-21")
    assert _step(week, "post").entries == [] and _step(week, "file").entries == []

    # all clear until the next day to act
    assert week.next_deadline is not None
    assert (week.next_deadline.ref.id, week.next_deadline.date) == (ids["parking_payment"], "2026-09-29")


def test_decisions_are_listed_once_and_only_within_30_days(store: Store, ids: dict[str, str]) -> None:
    notice = DateSpec(type="fixed", date="2026-10-10", nature="notice")
    same_contract = add_item(
        store,
        kind="deadline",
        title="Cancel the phone contract if you want to switch",
        due_date="2026-10-10",
        send_by="2026-10-08",
        contract_id=ids["phone"],
        date_spec=notice,
    )
    consent = add_item(
        store,
        kind="deadline",
        title="Agree to the new account fees",
        due_date="2026-10-20",
        date_spec=DateSpec(type="fixed", date="2026-10-20", nature="declaration"),
    )
    later = add_item(
        store,
        kind="deadline",
        title="Object to the statement",
        due_date="2026-11-20",
        date_spec=DateSpec(type="fixed", date="2026-11-20", nature="objection"),
    )
    payment_deadline = add_item(
        store,
        kind="deadline",
        title="Pay by",
        due_date="2026-10-03",
        date_spec=DateSpec(type="fixed", date="2026-10-03", nature="payment"),
    )
    decide = _step(weekly_session(store, TODAY), "decide")
    refs = _refs(decide)
    assert same_contract not in refs  # the contract's own row is the decision
    assert consent in refs and later not in refs and payment_deadline not in refs
    rows = {entry.ref.id: entry for entry in decide.entries}
    assert rows[consent].note == "Decide and answer before then."
    assert rows[ids["tax_objection"]].note == "Decide whether to object before then."
    assert decide.summary == "3 decisions in the next 30 days"


def test_a_direct_debit_is_to_cover_and_other_currencies_add_up_apart(
    store: Store, ids: dict[str, str]
) -> None:
    debit = add_item(
        store,
        kind="payment",
        title="Monatliche Abbuchung Deutschlandticket",
        due_date="2026-10-01",
        amount=63.0,
        direction="out",
    )
    dollars = add_item(
        store,
        kind="payment",
        title="Pay the conference fee",
        due_date="2026-10-02",
        amount=50.0,
        currency="USD",
        direction="out",
        grounding="verified",
    )
    pay = _step(weekly_session(store, TODAY), "pay")
    rows = {entry.ref.id: entry for entry in pay.entries}
    assert (
        rows[debit].date_role == "collected"
        and rows[debit].note == "Collected by direct debit: keep it covered."
    )
    assert _refs(pay)[-1] == debit  # transfers first
    assert pay.total == 440.49 and pay.total_other_currencies == {"USD": 50.0}
    assert rows[dollars].currency == "USD"
    assert pay.summary.startswith("4 transfers to make, 1 direct debit to cover")


# --------------------------------------------------------------------------------------------------
# the day to act: a missed send-by day, overdue rows and how the session ends
# --------------------------------------------------------------------------------------------------


def _authority(store: Store) -> tuple[str, str]:
    store.save_profile({"name": "Sam", "onboarded": True, "region": "NW"})
    party = store.add_party(name="Jobcenter", kind="authority").id
    doc = add_doc(
        store, "bescheid", kind="authority_letter", party_id=party, doc_date="2026-09-01", title="Bescheid"
    )
    return party, doc


def _objection(store: Store, doc: str, due: str, send_by: str) -> str:
    return add_item(
        store,
        kind="deadline",
        title="Widerspruch einlegen",
        due_date=due,
        send_by=send_by,
        doc_id=doc,
        date_spec=DateSpec(type="fixed", date=due, nature="objection"),
    )


def test_a_missed_send_by_day_means_act_today_not_overdue(store: Store) -> None:
    """An objection due Wed 30 Sep whose day to post it was Fri 25 Sep: on Mon 28 Sep it is still open —
    act today, with the due date beside it; never "3 days overdue", never left out of the ending."""
    _, doc = _authority(store)
    objection = _objection(store, doc, "2026-09-30", "2026-09-25")
    later = add_item(store, kind="deadline", title="Hand in Anlage", due_date="2026-10-20", doc_id=doc)
    week = weekly_session(store, TODAY)
    (row,) = _step(week, "now").entries
    assert (row.ref.id, row.date, row.date_role, row.due_date, row.overdue) == (
        objection,
        "2026-09-28",
        "act_today",
        "2026-09-30",
        False,
    )
    assert row.note == MISSED_POST_NOTE
    assert objection not in _refs(_step(week, "decide"))  # Act now lists it, once
    assert week.overdue == 0
    assert week.next_deadline is not None
    assert (week.next_deadline.ref.id, week.next_deadline.date) == (objection, "2026-09-28")
    assert later != week.next_deadline.ref.id


def test_the_decide_step_shows_the_day_to_post_and_the_deadline(store: Store) -> None:
    _, doc = _authority(store)
    objection = _objection(store, doc, "2026-10-14", "2026-10-08")
    (row,) = _step(weekly_session(store, TODAY), "decide").entries
    assert (row.ref.id, row.date, row.date_role, row.due_date) == (
        objection,
        "2026-10-08",
        "send_by",
        "2026-10-14",
    )
    # on 12 Oct the day to post it has passed, the deadline has not: act today, not "4 days overdue"
    later = date(2026, 10, 12)
    clock.set_today(later)
    week = weekly_session(store, later)
    (row,) = _step(week, "now").entries
    assert (row.date, row.date_role, row.due_date, row.overdue) == (
        "2026-10-12",
        "act_today",
        "2026-10-14",
        False,
    )
    assert _step(week, "decide").entries == []


def test_overdue_to_dos_are_listed_and_the_session_never_ends_all_clear(store: Store) -> None:
    _, doc = _authority(store)
    task = add_item(
        store, kind="task", title="Send documents to the Jobcenter", due_date="2026-09-25", doc_id=doc
    )
    deadline = add_item(store, kind="deadline", title="Hand in Anlage", due_date="2026-09-26", doc_id=doc)
    add_item(store, kind="deadline", title="Next form", due_date="2026-10-20", doc_id=doc)
    add_item(
        store, kind="payment", title="Refund", due_date="2026-09-20", amount=50.0, direction="in", doc_id=doc
    )
    week = weekly_session(store, TODAY)
    now = _step(week, "now")
    assert _refs(now) == [task, deadline] and now.summary == "2 overdue"
    assert all(row.overdue and row.tone == "danger" for row in now.entries)
    assert week.overdue == 2  # money coming in is never overdue
    assert week.next_deadline is not None and week.next_deadline.date == "2026-10-20"
    assert week.due is True and "now" in {step.id for step in week.steps}


def test_a_contract_decision_is_a_day_to_act(store: Store) -> None:
    """FunkNetz must be cancelled by 8 Oct or it renews: the session never says "All clear until 25 Oct"."""
    store.save_profile({"name": "Sam", "onboarded": True, "region": "NW"})
    funk = store.add_party(name="FunkNetz", kind="telecom").id
    contract = store.add_contract(
        name="FunkNetz mobile",
        category="mobile",
        party_id=funk,
        concluded_date="2024-11-15",
        start_date="2024-11-15",
        initial_term_months=24,
        notice_value=1,
        notice_unit="months",
        notice_basis="end_of_term",
        cost_amount=29.99,
        cost_interval="monthly",
    ).id
    doc = add_doc(store, "x", kind="authority_letter", title="Letter", doc_date="2026-09-01")
    add_item(store, kind="deadline", title="Hand in the form", due_date="2026-10-25", doc_id=doc)
    week = weekly_session(store, TODAY)
    assert _refs(_step(week, "decide")) == [contract]
    assert week.next_deadline is not None
    assert (week.next_deadline.ref.id, week.next_deadline.date_role) == (contract, "decide_by")
    assert week.next_deadline.date == _step(week, "decide").entries[0].date


def test_a_snoozed_to_do_keeps_its_letter_open(store: Store) -> None:
    """The person put the form off, not away: the letter is not filed, and its date is still to come."""
    doc = add_doc(store, "x", kind="authority_letter", title="Anhörung", doc_date="2026-09-10")
    store.set_meta(SESSION_KEY, _stored(TODAY - timedelta(days=7)))
    add_item(
        store,
        kind="task",
        title="Call the office",
        due_date="2026-09-20",
        doc_id=doc,
        status="done",
        completed_at=_stamp(TODAY - timedelta(days=1)),
    )
    snoozed = add_item(
        store,
        kind="deadline",
        title="Return the Anhörungsbogen",
        due_date="2026-10-20",
        doc_id=doc,
        status="snoozed",
        snoozed_until="2026-10-10",
    )
    week = weekly_session(store, TODAY)
    file = _step(week, "file")
    assert doc not in _refs(file) and file.summary == "1 to-do done"
    assert week.next_deadline is not None and week.next_deadline.ref.id == snoozed


def test_payments_count_overdue_from_their_due_date_and_a_missed_transfer_day_is_today(
    store: Store,
) -> None:
    _, doc = _authority(store)
    missed = add_item(
        store,
        kind="payment",
        title="Pay the invoice",
        due_date="2026-09-29",
        send_by="2026-09-25",
        amount=20.0,
        doc_id=doc,
    )
    late = add_item(
        store,
        kind="payment",
        title="Pay the fine",
        due_date="2026-09-26",
        send_by="2026-09-24",
        amount=30.0,
        doc_id=doc,
    )
    week = weekly_session(store, TODAY)
    rows = {row.ref.id: row for row in _step(week, "pay").entries}
    assert (rows[missed].date, rows[missed].date_role, rows[missed].due_date, rows[missed].overdue) == (
        "2026-09-28",
        "act_today",
        "2026-09-29",
        False,
    )
    assert rows[missed].note == MISSED_TRANSFER_NOTE
    assert (rows[late].date, rows[late].date_role, rows[late].overdue, rows[late].tone) == (
        "2026-09-26",
        "pay_by",
        True,
        "danger",
    )
    assert week.overdue == 1 and _step(week, "pay").total == 50.0


def test_a_fee_paid_at_the_appointment_is_not_a_transfer(store: Store) -> None:
    """The Ausländerbehörde's fee is paid on site by card: no Pay button, not in the transfer total, and
    the session does not end at its bank-transfer day."""
    party, doc = _authority(store)
    appointment = add_item(
        store,
        kind="appointment",
        title="Appointment at the Ausländerbehörde",
        due_date="2026-10-02",
        due_time="10:30",
        doc_id=doc,
        party_id=party,
    )
    fee = add_item(
        store,
        kind="payment",
        title="Fee for the extension",
        due_date="2026-10-02",
        due_time="10:30",
        send_by="2026-10-01",
        amount=100.0,
        doc_id=doc,
        party_id=party,
    )
    transfer = add_item(
        store, kind="payment", title="Pay the invoice", due_date="2026-10-01", amount=20.0, doc_id=doc
    )
    week = weekly_session(store, TODAY)
    pay = _step(week, "pay")
    rows = {row.ref.id: row for row in pay.entries}
    assert _refs(pay) == [transfer, fee]
    assert (rows[fee].date, rows[fee].date_role, rows[fee].note) == (
        "2026-10-02",
        "at_appointment",
        AT_APPOINTMENT_NOTE,
    )
    assert pay.total == 20.0
    assert pay.summary == "1 transfer to make, 1 fee to pay at an appointment"
    assert week.next_deadline is not None and week.next_deadline.ref.id == transfer
    store.update_item(transfer, status="done")
    week = weekly_session(store, TODAY)
    assert week.next_deadline is not None
    # the appointment and the fee share the day: never the fee's transfer day (1 Oct)
    assert week.next_deadline.date == "2026-10-02" and week.next_deadline.ref.id in (appointment, fee)


async def test_looks_right_takes_a_mismatched_value_off_please_check(data_dir: Path) -> None:
    """A quote that doesn't state its value asks to be checked — until the person says it looks right."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        _, doc = _authority(store)
        objection = _objection(store, doc, "2026-10-14", "2026-10-08")
        evidence = Evidence.model_validate(
            {"doc_id": doc, "page": 1, "quote": "innerhalb eines Monats", "value_consistent": False}
        )
        store.update_item(objection, evidence=[evidence])
        check = _step(weekly_session(store, TODAY), "check")
        assert _refs(check) == [objection]
        assert (
            check.entries[0].note == "Doesn't match its sentence in the letter — compare it with the letter."
        )
        confirmed = await api.client.post(f"/api/items/{objection}/confirm")
        assert confirmed.status_code == 200
        assert _step(weekly_session(store, TODAY), "check").entries == []


def test_rows_say_what_their_day_is(store: Store) -> None:
    """One wording for every step, as Today's: an appointment is on its day, an expiry expires, a
    transfer has its day to transfer (the same day in Please check as in Pay this week)."""
    _, doc = _authority(store)
    appointment = add_item(
        store,
        kind="appointment",
        title="Dental check-up",
        due_date="2026-10-08",
        doc_id=doc,
        grounding="model_read",
    )
    expiry = add_item(
        store,
        kind="expiry",
        title="Passport expires",
        due_date="2027-02-10",
        doc_id=doc,
        grounding="model_read",
    )
    fine = add_item(
        store,
        kind="payment",
        title="Pay the fine",
        due_date="2026-10-02",
        send_by="2026-10-01",
        amount=30.0,
        doc_id=doc,
        grounding="model_read",
    )
    week = weekly_session(store, TODAY)
    check = {row.ref.id: row for row in _step(week, "check").entries}
    assert (check[appointment].date_role, check[appointment].date) == ("on", "2026-10-08")
    assert (check[expiry].date_role, check[expiry].date) == ("expires", "2027-02-10")
    assert (check[fine].date_role, check[fine].date, check[fine].due_date) == (
        "transfer_by",
        "2026-10-01",
        "2026-10-02",
    )
    (paid,) = _step(week, "pay").entries
    assert (paid.date_role, paid.date) == (check[fine].date_role, check[fine].date)


# --------------------------------------------------------------------------------------------------
# "since your last session"
# --------------------------------------------------------------------------------------------------


def test_new_letters_are_those_since_the_last_session(store: Store, ids: dict[str, str]) -> None:
    _all_created(store, _stamp(TODAY - timedelta(days=5)))
    store.set_meta(SESSION_KEY, _stored(TODAY - timedelta(days=2), "18:30:00"))
    later = add_doc(store, "late-letter", kind="invoice", title="A letter after the session")
    _created(store, later, _stamp(TODAY - timedelta(days=2), "19:00:00"))
    same_day_before = add_doc(store, "early-letter", kind="invoice", title="A letter before the session")
    _created(store, same_day_before, _stamp(TODAY - timedelta(days=2), "08:00:00"))
    week = weekly_session(store, TODAY)
    assert (week.since, week.last_session) == ("2026-09-26", "2026-09-26")
    new = _step(week, "new")
    assert _refs(new) == [later]
    assert new.summary == "1 letter since Sat 26 Sep"
    assert new.entries[0].note == "Nothing to do — filed." and new.entries[0].tone == "ok"


def test_the_first_session_looks_back_a_week(store: Store, ids: dict[str, str]) -> None:
    _all_created(store, _stamp(TODAY - timedelta(days=8)))
    recent = add_doc(store, "recent", kind="invoice", title="Recent")
    _created(store, recent, _stamp(TODAY - timedelta(days=7), "00:00:01"))
    assert _refs(_step(weekly_session(store, TODAY), "new")) == [recent]


def test_letters_to_post_and_proof_to_keep(store: Store, ids: dict[str, str]) -> None:
    store.set_meta(SESSION_KEY, _stored(TODAY - timedelta(days=7)))
    unsent = store.add_draft(
        kind="cancellation",
        subject="Kündigung Mobilfunkvertrag",
        status="draft",
        send_guidance={"send_by": "2026-10-06", "channels": []},
    ).id
    late = store.add_draft(
        kind="objection",
        subject="Einspruch",
        status="final",
        send_guidance={"send_by": "2026-09-25", "channels": []},
    ).id
    registered = store.add_draft(
        kind="general_reply",
        subject="Widerspruch",
        status="sent",
        sent_at="2026-09-24",
        sent_channel="registered_letter",
    ).id
    unknown = store.add_draft(
        kind="general_reply", subject="Antwort", status="sent", sent_at="2026-09-27", sent_channel="pigeon"
    ).id
    post = _step(weekly_session(store, TODAY), "post")
    # drafts to send first (the earliest send-by day first), then what was sent since the last session
    assert _refs(post) == [late, unsent, unknown, registered]  # the enrolment letter was sent on 5 Sep
    rows = {entry.ref.id: entry for entry in post.entries}
    assert rows[late].overdue and rows[late].date_role == "send_by"
    assert rows[registered].note == PROOF_BY_CHANNEL["registered_letter"]
    assert rows[unknown].note == "Keep a copy and note how and when you sent it."
    assert post.summary == "2 letters to send · 2 sent — keep the proof"


def test_filing_what_was_done_and_archiving_year_old_letters(store: Store, ids: dict[str, str]) -> None:
    store.set_meta(SESSION_KEY, _stored(TODAY - timedelta(days=7)))
    store.update_item(ids["tax_objection"], status="done", completed_at=_stamp(TODAY - timedelta(days=1)))
    store.update_item(ids["tax_refund"], status="done", completed_at=_stamp(TODAY - timedelta(days=1)))
    store.update_item(ids["library_task"], status="done", completed_at=_stamp(TODAY - timedelta(days=9)))
    birthday = add_doc(store, "year-old", kind="receipt", title="Receipt", doc_date="2025-09-24")
    add_doc(store, "older", kind="receipt", title="Old receipt", doc_date="2025-09-20")
    week = weekly_session(store, TODAY)
    file = _step(week, "file")
    rows = {entry.ref.id: entry for entry in file.entries}
    assert set(rows) >= {ids["tax_objection"], ids["tax_refund"], ids["doc_tax"], birthday}
    assert ids["library_task"] not in rows  # done before the last session
    assert rows[ids["doc_tax"]].note == "Everything done — file the paper. Keep it with your tax papers."
    assert rows[birthday].note == "A year old with nothing open — move the paper to your archive."
    assert file.summary.startswith("2 to-dos done · ")


# --------------------------------------------------------------------------------------------------
# the endpoints
# --------------------------------------------------------------------------------------------------


async def test_week_endpoints(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        body: dict[str, Any] = (await api.client.get("/api/week")).json()
        assert body["due"] is True and body["last_session"] is None
        assert [step["id"] for step in body["steps"]] == [
            "now",
            "new",
            "check",
            "pay",
            "post",
            "waiting",
            "decide",
            "file",
        ]

        dismissed = (await api.client.post("/api/week/dismiss")).json()
        assert dismissed["due"] is False and dismissed["last_session"] is None
        assert api.ctx.store.get_meta(DISMISSED_KEY) is not None

        done = (await api.client.post("/api/week/done")).json()
        assert done["due"] is False and done["last_session"] == "2026-09-28"
        activity = (await api.client.get("/api/activity")).json()
        assert activity[0]["kind"] == "week.done" and activity[0]["message"] == "Weekly session done"
        # writes need the client header like every other change
        refused = await api.client.post("/api/week/done", headers={"X-Ordnung-Client": ""})
        assert refused.status_code in (400, 403)
