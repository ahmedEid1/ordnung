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
from ordnung.models import DateSpec, WeeklySession, WeekStep
from ordnung.secretary.week import (
    DISMISSED_KEY,
    MAX_ROWS,
    PROOF_BY_CHANNEL,
    SESSION_KEY,
    Moment,
    SessionState,
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
    assert week.due is False and week.next_deadline is None
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
    assert [step.id for step in week.steps] == ["new", "check", "pay", "post", "waiting", "decide", "file"]
    assert (week.today, week.since, week.last_session, week.due, week.minutes) == (
        "2026-09-28",
        "2026-09-21",
        None,
        True,
        10,
    )

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
