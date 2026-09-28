"""What the person waits for (``secretary.waiting``), call notes (``secretary.calls``) and the triggers
that use a letter's proof state (``proof_missing``, ``followup_due``, ``confirm_cancellation``)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

import helpers_proof
from helpers_docs import photo
from helpers_proof import DRAFT_ANSWER, SENT, TODAY, TRACKING, TRACKING_SHOWN, Gym, incoming, money_in
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.drafts import sent
from ordnung.drafts.compose import compose, mark_sent
from ordnung.drafts.proof import followup_item_id
from ordnung.llm.fake import FakeBackend
from ordnung.models import LetterDetails, Recurrence, Suggestion, WaitingEntry
from ordnung.secretary import calls
from ordnung.secretary.triggers import Ledger, run_and_reconcile, run_triggers
from ordnung.secretary.waiting import waiting_for
from ordnung.views import waiting


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    clock.set_today(TODAY)
    context = build_context(data_dir, backend_obj=FakeBackend({"draft": DRAFT_ANSWER}))
    yield context
    context.close()
    clock.set_today(None)


@pytest.fixture
def gym(ctx: AppContext) -> Gym:
    return helpers_proof.gym(ctx)


def _entries(ctx: AppContext, today: date = TODAY, **kwargs: bool) -> list[WaitingEntry]:
    return waiting_for(Ledger(ctx.store, today), **kwargs)


def _only(ctx: AppContext, today: date = TODAY) -> WaitingEntry:
    entries = _entries(ctx, today)
    assert len(entries) == 1, entries
    return entries[0]


def _ideas(ctx: AppContext, rule: str, today: date = TODAY) -> list[Suggestion]:
    return run_triggers(ctx.store, today)[rule]


# --------------------------------------------------------------------------------------------------
# sent letters
# --------------------------------------------------------------------------------------------------


async def test_a_sent_letter_is_waited_for_until_its_follow_up_day(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym, day=date(2026, 9, 20))
    entry = _only(ctx)
    assert (entry.source, entry.status, entry.title) == (
        "letter",
        "waiting",
        "A written confirmation of the end date",
    )
    assert entry.about == letter.subject and entry.party_name == "FitWell Studios GmbH"
    assert (entry.since, entry.expected_by) == ("2026-09-20", "2026-10-11")
    assert entry.followup_item_id == followup_item_id(letter.id)
    assert entry.ref.type == "draft" and entry.ref.id == letter.id
    assert entry.case_id == letter.case_id == gym.case  # a call noted about it goes to its thread
    assert "Ordnung reminds you on Sun 11 Oct" in entry.note


async def test_after_the_follow_up_day_it_is_overdue_and_names_the_proof(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym, tracking_number=TRACKING)
    await sent.add_proof(
        ctx, letter.id, photo("JPEG"), "d.jpg", kind="delivery_record", on_date="2026-09-03", today=TODAY
    )
    entry = _only(ctx)
    assert entry.status == "overdue" and entry.expected_by == "2026-09-22"
    assert "delivered on Thu 3 Sep" in entry.note and TRACKING_SHOWN in entry.note
    assert "Send a short reminder" in entry.note


async def test_a_letter_in_the_same_thread_answers_it_and_says_so(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    answer = incoming(
        ctx,
        "reply",
        kind="other",
        title="Ihr Schreiben vom 01.09.",
        doc_date="2026-09-08",
        party_id=gym.party,
        case_id=gym.case,
        direction="incoming",
    )
    entry = _only(ctx)
    assert entry.status == "answered" and entry.answered_on == "2026-09-08"
    assert entry.answered_by is not None and entry.answered_by.id == answer
    assert "“Ihr Schreiben vom 01.09.” of Tue 8 Sep is in the same thread" in entry.note
    # nothing is closed for the person (ADR 0006): the follow-up to-do is still open
    assert ctx.store.get_item(followup_item_id(letter.id)).status == "open"  # type: ignore[union-attr]


async def test_a_confirmation_of_the_contract_answers_a_cancellation_from_another_thread(
    ctx: AppContext, gym: Gym
) -> None:
    await helpers_proof.sent_letter(ctx, gym)
    other_case = ctx.store.add_case(title="Kündigung", party_id=gym.party).id
    incoming(
        ctx,
        "confirmation",
        kind="cancellation_confirmation",
        title="Kündigungsbestätigung",
        doc_date="2026-09-05",
        party_id=gym.party,
        case_id=other_case,
        direction="incoming",
    )
    entry = _only(ctx)
    assert entry.status == "answered" and "confirms the cancellation" in entry.note


@pytest.mark.parametrize(
    "fields",
    [
        {"doc_date": "2026-08-20"},  # written before the letter went out
        {"doc_date": "2026-09-08", "case_id": None},  # not in the thread
        {"doc_date": "2026-09-08", "direction": "outgoing"},  # the person's own copy
    ],
)
async def test_letters_that_are_no_answer(ctx: AppContext, gym: Gym, fields: dict[str, object]) -> None:
    await helpers_proof.sent_letter(ctx, gym)
    base: dict[str, object] = {
        "kind": "other",
        "title": "Letter",
        "party_id": gym.party,
        "case_id": gym.case,
        "direction": "incoming",
    }
    incoming(ctx, "other", **(base | fields))
    assert _only(ctx).status == "overdue"


async def test_a_trashed_or_scam_letter_answers_nothing(ctx: AppContext, gym: Gym) -> None:
    await helpers_proof.sent_letter(ctx, gym)
    doc = incoming(
        ctx, "reply", kind="other", title="Reply", doc_date="2026-09-08", party_id=gym.party, case_id=gym.case
    )
    ctx.store.trash_document(doc)
    assert _only(ctx).status == "overdue"
    ctx.store.restore_document(doc)
    ctx.store.update_document(
        doc, warnings=["Possible scam: the IBAN doesn't match the one they used before"]
    )
    assert _only(ctx).status == "overdue"


async def test_the_letter_it_answered_is_never_its_answer(ctx: AppContext, gym: Gym) -> None:
    source = incoming(
        ctx,
        "price",
        kind="price_increase",
        title="Preiserhöhung",
        doc_date="2026-09-12",  # the same day the reply went out
        party_id=gym.party,
        case_id=gym.case,
    )
    draft = await compose(ctx, "general_reply", doc_id=source)
    mark_sent(ctx, draft.id, "email", date(2026, 9, 12))
    assert _only(ctx, date(2026, 10, 30)).status == "overdue"


async def test_closing_the_follow_up_closes_the_entry(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    ctx.store.update_item(followup_item_id(letter.id), status="done")
    assert _entries(ctx) == []
    closed = _entries(ctx, include_closed=True)
    assert [entry.status for entry in closed] == ["closed"] and "You closed the follow-up" in closed[0].note
    ctx.store.delete_item(followup_item_id(letter.id))
    assert _entries(ctx) == []


async def test_answered_in_the_persons_words_closes_the_entry_and_undo_reopens_it(
    ctx: AppContext, gym: Gym
) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    assert _only(ctx).status == "overdue"
    sent.mark_answered(ctx.store, letter.id, TODAY)
    assert _entries(ctx) == []
    (closed,) = _entries(ctx, include_closed=True)
    assert "You marked it as answered on Mon 28 Sep" in closed.note
    assert ctx.store.get_item(followup_item_id(letter.id)).status == "done"  # type: ignore[union-attr]
    sent.unmark_answered(ctx.store, letter.id)
    assert _only(ctx).status == "overdue"
    assert ctx.store.get_item(followup_item_id(letter.id)).status == "open"  # type: ignore[union-attr]


async def test_marking_again_keeps_a_closed_follow_up_closed(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    sent.mark_answered(ctx.store, letter.id, TODAY)
    mark_sent(ctx, letter.id, "registered_letter", date(2026, 9, 2))  # correcting the day
    assert ctx.store.get_item(followup_item_id(letter.id)).status == "done"  # type: ignore[union-attr]


async def test_a_deposit_letter_waits_for_when_not_for_the_money(ctx: AppContext, gym: Gym) -> None:
    """The landlord may take months to settle a deposit: three weeks on, the answer on when is due."""
    details = LetterDetails(moved_out_on="2026-08-31", old_address="Alt 1, 12345 Musterstadt", amount=900.0)
    draft = await compose(ctx, "deposit_return", party_id=gym.party, details=details)
    mark_sent(ctx, draft.id, "letter", SENT)
    entry = _only(ctx)
    assert entry.status == "overdue" and entry.title == "An answer on when your deposit will be settled"
    assert "VIII ZR 71/05" in entry.note and "more than six months" in entry.note
    assert "Your deposit back" not in entry.note


@pytest.mark.parametrize(
    ("answers", "context"),
    [("tax_assessment", True), (None, True), ("court_payment_order", False), ("landlord_notice", False)],
)
async def test_an_objection_waits_for_its_acknowledgement_not_the_decision(
    ctx: AppContext, gym: Gym, answers: str | None, context: bool
) -> None:
    """A decision takes months (an action for failure to act only after 3 or 6 months): three weeks on,
    what is due is the acknowledgement — and only an authority's decision gets the paragraphs."""
    letter = await helpers_proof.sent_letter(ctx, gym)
    doc_id = (
        incoming(ctx, "decision", kind=answers, title="Bescheid", doc_date="2026-08-20") if answers else None
    )
    ctx.store.update_draft(letter.id, kind="objection", doc_id=doc_id)
    entry = _only(ctx)
    assert entry.status == "overdue" and entry.title == "An acknowledgement of your objection"
    said = ("§ 75 VwGO" in entry.note, "§ 88 Abs. 2 SGG" in entry.note, "§ 46 Abs. 1 FGO" in entry.note)
    assert said == (context, context, context)
    assert ("often takes months" in entry.note) is context


async def test_an_address_change_waits_for_nothing(ctx: AppContext, gym: Gym) -> None:
    details = LetterDetails(
        old_address="Alt 1, 12345 Musterstadt", new_address="Neu 2, 12345 Musterstadt", moved_on="2026-09-01"
    )
    draft = await compose(ctx, "address_change", contract_id=gym.contract, details=details)
    mark_sent(ctx, draft.id, "letter", SENT)
    assert _entries(ctx) == []


# --------------------------------------------------------------------------------------------------
# money
# --------------------------------------------------------------------------------------------------


def test_money_a_letter_promised_is_waited_for_until_marked_received(ctx: AppContext, gym: Gym) -> None:
    doc = incoming(
        ctx,
        "statement",
        kind="utility_bill",
        title="Betriebskostenabrechnung 2025",
        doc_date="2026-09-08",
        party_id=gym.party,
    )
    credit = money_in(
        ctx,
        "Service-charge credit",
        amount=85.2,
        due_date="2026-10-08",
        doc_id=doc,
        party_id=gym.party,
        area="home",
    )
    entry = _only(ctx)
    assert (entry.source, entry.status, entry.amount, entry.expected_by) == (
        "money",
        "waiting",
        85.2,
        "2026-10-08",
    )
    assert entry.about == "Betriebskostenabrechnung 2025" and entry.since == "2026-09-08"
    assert "€85.20 by Thu 8 Oct" in entry.note and "can't see your bank account" in entry.note
    assert entry.followup_item_id == credit.id and entry.area == "home" and entry.doc_id == doc
    late = _only(ctx, date(2026, 10, 12))
    assert late.status == "overdue" and "ask FitWell Studios GmbH about it" in late.note
    ctx.store.update_item(credit.id, status="done")
    assert _entries(ctx) == []


def test_money_that_is_no_promise(ctx: AppContext, gym: Gym) -> None:
    money_in(
        ctx, "Salary", amount=1200.0, due_date="2026-09-30", recurrence=Recurrence(interval=1, unit="months")
    )
    money_in(
        ctx, "Old refund", amount=10.0, due_date="2026-01-01", filed_on="2026-09-01"
    )  # history when filed
    ctx.store.add_item(kind="payment", title="Rent", direction="out", amount=640.0, due_date="2026-10-01")
    assert _entries(ctx) == []
    typed = money_in(ctx, "Deposit back", amount=900.0)
    entry = _only(ctx)
    assert entry.about == "Added by you" and entry.expected_by is None and entry.status == "waiting"
    assert entry.ref.id == typed.id


# --------------------------------------------------------------------------------------------------
# calls
# --------------------------------------------------------------------------------------------------


def test_a_dated_promise_on_the_phone_is_waited_for(ctx: AppContext, gym: Gym) -> None:
    note = calls.add_call_note(
        ctx.store,
        today=TODAY,
        called_on="2026-09-20",
        summary="  Asked about the refund.  ",
        party_id=gym.party,
        contact="  Frau   Weber ",
        promise="Call back about the refund",
        promise_due="2026-09-25",
    )
    assert (note.summary, note.contact, note.case_id) == ("Asked about the refund.", "Frau Weber", None)
    entry = _only(ctx)
    assert (entry.source, entry.status, entry.title) == ("call", "overdue", "Call back about the refund")
    assert entry.about == "Call with Frau Weber" and "Call them again" in entry.note
    assert entry.note.startswith("On the phone on Sun 20 Sep, they promised this by Fri 25 Sep.")
    calls.mark_kept(ctx.store, note.id, True, TODAY)
    assert _entries(ctx) == [] and _entries(ctx, include_closed=True)[0].note == "Kept on Mon 28 Sep."
    calls.mark_kept(ctx.store, note.id, False, TODAY)
    assert _only(ctx).status == "overdue"


def test_merging_two_parties_keeps_their_call_notes(ctx: AppContext, gym: Gym) -> None:
    duplicate = ctx.store.add_party(name="FitWell", kind="company").id
    note = calls.add_call_note(
        ctx.store,
        today=TODAY,
        called_on="2026-09-20",
        summary="They said it's cancelled.",
        party_id=duplicate,
    )
    ctx.store.merge_parties(gym.party, duplicate)
    assert ctx.store.get_call_note(note.id).party_id == gym.party  # type: ignore[union-attr]
    assert [call.id for call in ctx.store.list_call_notes(party_id=gym.party)] == [note.id]


def test_a_letter_in_the_calls_thread_answers_its_promise(ctx: AppContext, gym: Gym) -> None:
    calls.add_call_note(
        ctx.store,
        today=TODAY,
        called_on="2026-09-20",
        summary="Refund promised",
        case_id=gym.case,
        promise="Refund in writing",
        promise_due="2026-10-10",
    )
    assert _only(ctx).status == "waiting" and _only(ctx).party_id == gym.party  # the thread brings its sender
    assert _only(ctx).case_id == gym.case
    incoming(
        ctx,
        "refund",
        kind="other",
        title="Gutschrift",
        doc_date="2026-09-24",
        party_id=gym.party,
        case_id=gym.case,
    )
    entry = _only(ctx)
    assert entry.status == "answered" and "arrived after the call" in entry.note


def test_notes_without_a_dated_promise_are_only_notes(ctx: AppContext, gym: Gym) -> None:
    calls.add_call_note(
        ctx.store, today=TODAY, called_on="2026-09-20", summary="Just asked", party_id=gym.party
    )
    calls.add_call_note(
        ctx.store,
        today=TODAY,
        called_on="2026-09-21",
        summary="Vague",
        party_id=gym.party,
        promise="Will look into it",
    )
    assert _entries(ctx) == []
    assert [n.called_on for n in ctx.store.list_call_notes(party_id=gym.party)] == [
        "2026-09-21",
        "2026-09-20",
    ]


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({}, "Choose who you spoke to"),
        ({"party_id": "pty_missing"}, "isn't in Ordnung"),
        ({"case_id": "cas_missing"}, "thread isn't in Ordnung"),
        ({"party": True, "called_on": "2026-10-01"}, "future"),
        ({"party": True, "called_on": "someday"}, "not a date"),
        ({"party": True, "summary": "   "}, "what was said"),
        ({"party": True, "promise_due": "2026-10-01"}, "what they promised"),
        ({"party": True, "promise_amount": 20.0}, "what they promised"),
        ({"party": True, "promise": "Call back", "promise_due": "2026-09-01"}, "before the call"),
    ],
)
def test_call_note_refusals(ctx: AppContext, gym: Gym, fields: dict[str, object], message: str) -> None:
    args: dict[str, object] = {"called_on": "2026-09-20", "summary": "Called them"}
    if fields.pop("party", False):
        args["party_id"] = gym.party
    with pytest.raises(calls.CallNoteError, match=message):
        calls.add_call_note(ctx.store, today=TODAY, **(args | fields))  # type: ignore[arg-type]


def test_keeping_needs_a_promise(ctx: AppContext, gym: Gym) -> None:
    note = calls.add_call_note(
        ctx.store, today=TODAY, called_on="2026-09-20", summary="Hello", party_id=gym.party
    )
    with pytest.raises(calls.CallNoteError, match="no promise"):
        calls.mark_kept(ctx.store, note.id, True, TODAY)
    with pytest.raises(LookupError):
        calls.mark_kept(ctx.store, "cal_missing", True, TODAY)


# --------------------------------------------------------------------------------------------------
# order and the view
# --------------------------------------------------------------------------------------------------


async def test_overdue_first_then_answered_then_by_day(ctx: AppContext, gym: Gym) -> None:
    """By what each asks of the person: chase it, check the letter that may have answered it, wait."""
    await helpers_proof.sent_letter(ctx, gym)  # overdue since 22 Sep
    money_in(ctx, "Refund later", amount=5.0, due_date="2026-12-01")
    money_in(ctx, "Refund sooner", amount=5.0, due_date="2026-10-15")
    money_in(ctx, "Refund someday", amount=5.0)
    calls.add_call_note(
        ctx.store,
        today=TODAY,
        called_on="2026-09-20",
        summary="x",
        case_id=gym.case,
        promise="Letter",
        promise_due="2026-10-30",
    )
    incoming(
        ctx, "reply", kind="other", title="Reply", doc_date="2026-09-25", party_id=gym.party, case_id=gym.case
    )
    entries = waiting(ctx.store, TODAY)
    assert [(e.status, e.title) for e in entries] == [
        ("answered", "A written confirmation of the end date"),
        ("answered", "Letter"),
        ("waiting", "Refund sooner"),
        ("waiting", "Refund later"),
        ("waiting", "Refund someday"),
    ]


# --------------------------------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------------------------------


async def test_proof_missing_two_days_after_a_registered_cancellation(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym, day=date(2026, 9, 26))
    assert _ideas(ctx, "proof_missing", date(2026, 9, 27)) == []
    ideas = _ideas(ctx, "proof_missing", date(2026, 9, 28))
    assert len(ideas) == 1
    idea = ideas[0]
    assert idea.title == "Keep the proof of your cancellation to FitWell Studios GmbH"
    assert "Einlieferungsbeleg" in idea.body and "Auslieferungsbeleg" in idea.body
    assert idea.rationale and "BAG 2 AZR 68/24" in idea.rationale
    assert idea.action is not None and (idea.action.type, idea.action.target_type, idea.action.target_id) == (
        "open",
        "draft",
        letter.id,
    )
    assert {(ref.type, ref.id) for ref in idea.refs} >= {("draft", letter.id), ("contract", gym.contract)}


async def test_proof_missing_goes_once_there_is_proof(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    first = run_and_reconcile(ctx.store, TODAY)
    assert first.by_rule["proof_missing"] == 1
    sent.set_tracking(ctx.store, letter.id, TRACKING)
    second = run_and_reconcile(ctx.store, TODAY)
    assert second.by_rule["proof_missing"] == 0 and second.expired >= 1
    sent.set_tracking(ctx.store, letter.id, None)
    await sent.add_proof(ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", today=TODAY)
    assert _ideas(ctx, "proof_missing") == []


@pytest.mark.parametrize(
    ("channel", "kind"),
    [("letter", "cancellation"), ("email", "cancellation"), ("registered_letter", "general_reply")],
)
async def test_proof_missing_only_for_registered_cancellations_and_objections(
    ctx: AppContext, gym: Gym, channel: str, kind: str
) -> None:
    await helpers_proof.sent_letter(ctx, gym, channel, kind=kind)
    assert _ideas(ctx, "proof_missing") == []


async def test_proof_missing_not_when_answered_or_closed(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    ctx.store.update_item(followup_item_id(letter.id), status="done")
    assert _ideas(ctx, "proof_missing") == []
    ctx.store.update_item(followup_item_id(letter.id), status="open")
    reply = incoming(
        ctx, "reply", kind="other", title="Reply", doc_date="2026-09-08", party_id=gym.party, case_id=gym.case
    )
    # a later letter of the thread is only a possible answer: the advice stays
    assert len(_ideas(ctx, "proof_missing")) == 1
    sent.mark_answered(ctx.store, letter.id, TODAY, doc_id=reply)
    assert _ideas(ctx, "proof_missing") == []


async def test_proof_missing_stays_when_the_person_only_says_it_was_answered(
    ctx: AppContext, gym: Gym
) -> None:
    """The person's "I got an answer" (by phone, or to tidy up) shows nothing about arrival: the delivery
    record is still worth asking for, and the Idea stays until Deutsche Post no longer issues it."""
    letter = await helpers_proof.sent_letter(ctx, gym)
    sent.mark_answered(ctx.store, letter.id, TODAY)
    assert ctx.store.get_item(followup_item_id(letter.id)).status == "done"  # type: ignore[union-attr]
    (idea,) = _ideas(ctx, "proof_missing")
    assert "courts have accepted as a sign" in idea.body and "that is what shows it did" not in idea.body
    assert _ideas(ctx, "proof_missing", today=date(2027, 12, 2)) == []
    overview = sent.overview(ctx.store, letter.id, TODAY)
    assert any("Auslieferungsbeleg" in line for line in overview.missing)
    assert overview.timeline[-1].label == "You marked it as answered"


async def test_proof_missing_not_after_a_confirmation_of_the_cancellation(ctx: AppContext, gym: Gym) -> None:
    await helpers_proof.sent_letter(ctx, gym)
    incoming(
        ctx,
        "confirmation",
        kind="cancellation_confirmation",
        title="Kündigungsbestätigung",
        doc_date="2026-09-05",
        party_id=gym.party,
        case_id=gym.case,
    )
    assert _ideas(ctx, "proof_missing") == []


async def test_proof_missing_not_once_the_delivery_record_can_no_longer_be_had(
    ctx: AppContext, gym: Gym
) -> None:
    """Sent 1 Sep 2026: Deutsche Post issues the delivery record until 1 Dec 2027 (15 months)."""
    await helpers_proof.sent_letter(ctx, gym)
    assert len(_ideas(ctx, "proof_missing", today=date(2027, 12, 1))) == 1
    assert _ideas(ctx, "proof_missing", today=date(2027, 12, 2)) == []


async def test_follow_up_names_the_delivery_and_the_tracking_number(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym, tracking_number=TRACKING)
    await sent.add_proof(
        ctx, letter.id, photo("JPEG"), "r.jpg", kind="return_receipt", on_date="2026-09-04", today=TODAY
    )
    (idea,) = _ideas(ctx, "followup_due")
    assert idea.title == "Follow-up due: Check for a reply from FitWell Studios GmbH"
    assert "delivered on Fri 4 Sep — say so when you remind them" in idea.body
    assert f"Quote the tracking number {TRACKING_SHOWN} if you call" in idea.body


async def test_follow_up_without_proof_keeps_the_plain_reminder(ctx: AppContext, gym: Gym) -> None:
    await helpers_proof.sent_letter(ctx, gym, "letter")
    (idea,) = _ideas(ctx, "followup_due")
    assert idea.body.endswith("send a short reminder or call them — and keep a note of it.")


async def test_follow_up_after_an_answer_asks_to_check_it(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    (before,) = _ideas(ctx, "followup_due")
    answer = incoming(
        ctx,
        "reply",
        kind="other",
        title="Antwort",
        doc_date="2026-09-09",
        party_id=gym.party,
        case_id=gym.case,
    )
    (idea,) = _ideas(ctx, "followup_due")
    # only in the same thread: it may be about something else, so Ordnung asks
    assert idea.title == "A letter from FitWell Studios GmbH came — is it the answer?"
    assert "“Antwort” of Wed 9 Sep came after yours" in idea.body
    assert idea.fingerprint != before.fingerprint  # a new Idea, not the old "send a reminder"
    assert idea.action is not None and idea.action.target_id == letter.id
    assert ("document", answer) in {(ref.type, ref.id) for ref in idea.refs}


async def test_confirm_cancellation_names_the_sent_letter(ctx: AppContext, gym: Gym) -> None:
    incoming(
        ctx,
        "confirmation",
        kind="cancellation_confirmation",
        title="Kündigungsbestätigung",
        doc_date="2026-09-05",
        party_id=gym.party,
        case_id=gym.case,
    )
    (plain,) = _ideas(ctx, "confirm_cancellation")
    assert "answers your cancellation" not in plain.body
    letter = await helpers_proof.sent_letter(ctx, gym, tracking_number=TRACKING)
    (idea,) = _ideas(ctx, "confirm_cancellation")
    assert (
        f"answers your cancellation sent on Tue 1 Sep by registered letter (Einschreiben) (tracking number {TRACKING_SHOWN})"
        in idea.body
    )
    assert ("draft", letter.id) in {(ref.type, ref.id) for ref in idea.refs}
    assert idea.fingerprint == plain.fingerprint  # the same facts: the person's choice on it is kept


async def test_reply_detection_is_cached_per_ledger(ctx: AppContext, gym: Gym) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym)
    ledger = Ledger(ctx.store, TODAY)
    assert ledger.reply_to(letter) is None
    incoming(
        ctx, "reply", kind="other", title="Reply", doc_date="2026-09-08", party_id=gym.party, case_id=gym.case
    )
    assert ledger.reply_to(letter) is None  # one snapshot per view
    assert Ledger(ctx.store, TODAY).reply_to(letter) is not None
    unsent = await compose(ctx, "cancellation", contract_id=gym.contract)
    assert Ledger(ctx.store, TODAY + timedelta(days=1)).reply_to(unsent) is None


async def test_its_answered_closes_a_snoozed_follow_up_and_undo_snoozes_it_again(
    ctx: AppContext, gym: Gym
) -> None:
    """A follow-up snoozed a few days, then "It's answered": nothing may still ask for the reply — Today,
    the weekly session and the Waiting for page agree — and Undo puts the snooze back as it was."""
    from ordnung.views import weekly_session

    letter = await helpers_proof.sent_letter(ctx, gym)
    followup = followup_item_id(letter.id)
    until = (TODAY + timedelta(days=3)).isoformat()
    ctx.store.update_item(followup, status="snoozed", snoozed_until=until)
    sent.mark_answered(ctx.store, letter.id, TODAY)
    assert ctx.store.get_item(followup).status == "done"  # type: ignore[union-attr]
    later = date(2026, 10, 22)
    assert waiting(ctx.store, later) == []
    week = weekly_session(ctx.store, later)
    waiting_step = next(step for step in week.steps if step.id == "waiting")
    assert waiting_step.entries == [] and week.overdue == 0
    sent.unmark_answered(ctx.store, letter.id)
    item = ctx.store.get_item(followup)
    assert item is not None and (item.status, item.snoozed_until) == ("snoozed", until)


# --------------------------------------------------------------------------------------------------
# the weekly session reads the same proof and waiting state
# --------------------------------------------------------------------------------------------------


def _week_step(ctx: AppContext, step_id: str, today: date = TODAY) -> tuple[object, object]:
    from ordnung.views import weekly_session

    week = weekly_session(ctx.store, today)
    return week, next(step for step in week.steps if step.id == step_id)


async def test_the_weekly_post_step_asks_for_the_proof_still_missing_whenever_it_was_sent(
    ctx: AppContext, gym: Gym
) -> None:
    """A registered letter sent four weeks ago without its proof is listed with what is missing first
    (``drafts.proof.missing``), not a generic note — and leaves the step once its proof is complete."""
    from ordnung.drafts.proof import MISSING_POSTING, MISSING_TRACKING

    letter = await helpers_proof.sent_letter(ctx, gym)
    _, post = _week_step(ctx, "post")
    (row,) = post.entries  # type: ignore[attr-defined]
    assert row.ref.id == letter.id and row.date_role == "sent" and row.tone == "warn"
    assert post.summary == "1 sent — 1 without all its proof"  # type: ignore[attr-defined]
    assert row.note.startswith(MISSING_TRACKING) and "2 things more" in row.note
    sent.set_tracking(ctx.store, letter.id, TRACKING)
    await sent.add_proof(ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", today=TODAY)
    (row,) = _week_step(ctx, "post")[1].entries  # type: ignore[attr-defined]
    assert "delivery record" in row.note and MISSING_POSTING not in row.note
    await sent.add_proof(
        ctx, letter.id, photo("PNG"), "d.png", kind="delivery_record", on_date="2026-09-03", today=TODAY
    )
    assert _week_step(ctx, "post")[1].entries == []  # type: ignore[attr-defined]


async def test_a_letter_sent_this_week_with_its_delivery_record_says_it_was_delivered(
    ctx: AppContext, gym: Gym
) -> None:
    letter = await helpers_proof.sent_letter(ctx, gym, day=date(2026, 9, 24))
    sent.set_tracking(ctx.store, letter.id, TRACKING)
    await sent.add_proof(ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", today=TODAY)
    await sent.add_proof(
        ctx, letter.id, photo("PNG"), "d.png", kind="delivery_record", on_date="2026-09-25", today=TODAY
    )
    (row,) = _week_step(ctx, "post")[1].entries  # type: ignore[attr-defined]
    assert row.note.startswith("Delivered on Fri 25 Sep") and row.tone == "ok"


async def test_the_weekly_waiting_step_is_the_waiting_for_page(ctx: AppContext, gym: Gym) -> None:
    """The step lists what the Waiting for page lists — an overdue phone promise and money owed too — and
    its overdue entries keep the session from ending "All clear"."""
    letter = await helpers_proof.sent_letter(ctx, gym)
    money_in(ctx, "Kaution zurück", amount=450.0, due_date="2026-09-20", party_id=gym.party)
    calls.add_call_note(
        ctx.store,
        party_id=gym.party,
        called_on="2026-09-10",
        summary="Asked about the cancellation",
        contact="Frau Weber",
        promise="Schriftliche Kündigungsbestätigung",
        promise_due="2026-09-20",
        today=TODAY,
    )
    page = waiting(ctx.store, TODAY)
    week, step = _week_step(ctx, "waiting")
    rows = step.entries  # type: ignore[attr-defined]
    assert [row.key for row in rows] == [f"waiting:{entry.id}" for entry in page]
    assert {row.ref.type for row in rows} == {"draft", "item", "call"}
    assert all(row.overdue and row.tone == "danger" for row in rows)
    assert week.overdue == len(page)  # type: ignore[attr-defined]
    by_type = {row.ref.type: row for row in rows}
    assert (
        by_type["call"].date_role == "promised_by"
        and by_type["call"].title == "Schriftliche Kündigungsbestätigung"
    )
    assert by_type["draft"].ref.id == letter.id and by_type["draft"].date_role == "reply_by"
    assert by_type["item"].amount == 450.0 and by_type["item"].date_role == "expected"
