"""Daily brief: deterministic agenda, code-generated text, model note with free-text check and fallback."""

from __future__ import annotations

from datetime import date

import pytest

from helpers_secretary import TODAY, add_doc, add_item, seed_ledger
from ordnung.db.store import Store
from ordnung.llm.base import LLMError, LLMRequest, LLMResponse
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import AppSettings, Profile, RefLink
from ordnung.secretary.brief import (
    Agenda,
    AgendaEntry,
    _model_payload,
    agenda_text,
    brief_cache_key,
    brief_request,
    brief_text,
    build_agenda,
    generate_brief,
    get_brief,
    grounded_note,
    mislabelled_dates,
)
from ordnung.secretary.review import Facts
from ordnung.secretary.triggers import run_and_reconcile

GOOD_NOTE = (
    "Good morning, Sam! Your library books were due on 20 Sep, and the TechMarkt reminder of €94.99 is "
    "due on Wed 30 Sep. Decide on FunkNetz mobile by 8 Oct."
)


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


class FailingBackend:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        raise LLMError("Claude is not signed in")

    async def stream(self, req: LLMRequest):  # pragma: no cover - not used
        raise LLMError("unused")
        yield


def test_build_agenda_is_deterministic(store: Store, ids: dict[str, str]) -> None:
    agenda = build_agenda(store, TODAY)
    assert [e.id for e in agenda.overdue] == [ids["library_task"]]
    assert agenda.today == []
    # the scam letter's "payment" and the incoming refund are no agenda entries
    assert [e.id for e in agenda.next_7_days] == [
        ids["parking_payment"],
        ids["dunning_payment"],
        ids["semester_fee"],
    ]
    assert [e.id for e in agenda.payments_this_month] == [ids["parking_payment"], ids["dunning_payment"]]
    assert agenda.payments_total == 119.99
    assert [e.id for e in agenda.decisions] == [ids["phone"]]
    assert agenda.decisions[0].date == "2026-10-08"
    assert build_agenda(store, TODAY) == agenda


def test_agenda_lists_new_ideas_and_a_missed_send_by_as_today(store: Store, ids: dict[str, str]) -> None:
    run_and_reconcile(store, TODAY)
    agenda = build_agenda(store, date(2026, 10, 16))  # objection send-by (15 Oct) passed, due 21 Oct
    assert ids["tax_objection"] in [e.id for e in agenda.today]
    assert len(build_agenda(store, TODAY).new_ideas) == 3


def test_agenda_text_is_plain_and_complete(store: Store, ids: dict[str, str]) -> None:
    text = agenda_text(build_agenda(store, TODAY))
    assert text.startswith("Overdue: Return library books (Sun 20 Sep).")
    assert (
        "Next 7 days: Pay parking fine (Tue 29 Sep, €25); Pay TechMarkt reminder (Wed 30 Sep, €94.99); "
        in text
    )
    assert "Payments this month: €119.99 in 2 payments." in text
    assert "Decide on your FunkNetz mobile: send a cancellation by Thu 8 Oct if you want to leave." in text


def test_agenda_text_all_clear() -> None:
    assert agenda_text(Agenda(date="2026-09-28")) == "All clear — nothing is due in the next 7 days."


def test_agenda_text_is_never_all_clear_while_letters_wait() -> None:
    """Letters from the watched folder that wait unread may ask for anything: only what was read is
    clear (the count stays out of what the model sees and of the facts its note is checked against)."""
    agenda = Agenda(date="2026-09-28", waiting=2)
    assert agenda_text(agenda) == "Nothing is due in the next 7 days from the letters that were read."
    unread = Agenda(date="2026-09-28")
    assert brief_request(agenda, Profile(), AppSettings()) == brief_request(unread, Profile(), AppSettings())


def test_grounded_note_rejects_invented_facts(store: Store, ids: dict[str, str]) -> None:
    agenda = build_agenda(store, TODAY)
    assert grounded_note(GOOD_NOTE, agenda)
    assert not grounded_note("Pay €95 by Wed 30 Sep.", agenda)
    assert not grounded_note("Your appointment is on 12 Nov.", agenda)
    assert not grounded_note("Remember § 193 BGB.", agenda)
    assert not grounded_note("", agenda)


async def test_brief_text_uses_a_grounded_model_note_and_caches_it(store: Store, ids: dict[str, str]) -> None:
    backend = FakeBackend({"brief": {"text": GOOD_NOTE}})
    llm = LLMService(backend, sink=store)
    agenda = build_agenda(store, TODAY)
    profile = store.get_profile()
    brief = await brief_text(llm, agenda, profile, settings=store.get_settings())
    assert (brief.source, brief.text, brief.date) == ("llm", GOOD_NOTE, "2026-09-28")
    again = await brief_text(llm, agenda, profile, settings=store.get_settings())
    assert again.text == GOOD_NOTE and len(backend.calls) == 1  # cached per day + agenda hash
    request = backend.calls[0]
    assert request.purpose == "brief" and request.model == "haiku"
    assert request.cache_key == brief_cache_key(agenda, profile)
    assert request.cache_key.startswith("brief:2026-09-28:")
    assert "<untrusted_document>" in request.prompt and "Sam" in request.prompt
    assert "English" in request.system


async def test_brief_text_falls_back_when_the_note_invents_a_date(store: Store, ids: dict[str, str]) -> None:
    backend = FakeBackend({"brief": {"text": "Your tax objection is due on 12 Nov. Relax!"}})
    agenda = build_agenda(store, TODAY)
    brief = await brief_text(LLMService(backend), agenda, store.get_profile())
    assert brief.source == "template"
    assert brief.text == agenda_text(agenda)


async def test_brief_text_falls_back_when_the_model_fails(store: Store, ids: dict[str, str]) -> None:
    backend = FailingBackend()
    agenda = build_agenda(store, TODAY)
    brief = await brief_text(LLMService(backend), agenda, store.get_profile())
    assert brief.source == "template" and len(backend.calls) == 1


async def test_brief_text_needs_no_model_for_an_empty_agenda() -> None:
    backend = FakeBackend({})
    brief = await brief_text(LLMService(backend), Agenda(date="2026-09-28"), Profile())
    assert brief.source == "template" and backend.calls == []


async def test_private_letters_never_reach_the_model(store: Store, ids: dict[str, str]) -> None:
    store.update_item(ids["private_item"], due_date="2026-10-01")
    agenda = build_agenda(store, TODAY)
    assert any(entry.private for entry in agenda.next_7_days)
    backend = FakeBackend({"brief": {"text": GOOD_NOTE}})
    await brief_text(LLMService(backend), agenda, store.get_profile())
    assert "Therapy invoice" not in backend.calls[0].prompt
    assert ids["doc_private"] not in backend.calls[0].doc_ids


def test_cache_key_depends_on_language(store: Store, ids: dict[str, str]) -> None:
    agenda = build_agenda(store, TODAY)
    english = brief_cache_key(agenda, Profile(name="Sam", language="en"))
    german = brief_cache_key(agenda, Profile(name="Sam", language="de"))
    assert english != german and english == brief_cache_key(agenda, Profile(name="Sam", language="en"))


async def test_generate_brief_stores_the_brief_of_the_day(store: Store, ids: dict[str, str]) -> None:
    assert get_brief(store, TODAY) is None
    stored = await generate_brief(store, None, TODAY)
    assert stored.source == "template"
    assert get_brief(store, TODAY) == stored
    llm = LLMService(FakeBackend({"brief": {"text": GOOD_NOTE}}), sink=store)
    updated = await generate_brief(store, llm, TODAY)
    assert updated.source == "llm"
    loaded = get_brief(store, TODAY)
    assert loaded is not None and loaded.text == GOOD_NOTE


# --------------------------------------------------------------------------------------------------
# send-by days are never called due dates
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def rent(store: Store, ids: dict[str, str]) -> str:
    """A rent due Mon 5 Oct to transfer by Fri 2 Oct — the day the semester fee (€320.50) is due."""
    return add_item(
        store,
        kind="payment",
        title="Pay monthly rent (Miete)",
        due_date="2026-10-05",
        send_by="2026-10-02",
        amount=640.0,
        currency="EUR",
        direction="out",
    )


def _rows(payload: dict[str, object], section: str) -> list[dict[str, object]]:
    rows = payload[section]
    assert isinstance(rows, list)
    return rows


def test_the_payload_labels_due_dates_and_send_by_days(store: Store, ids: dict[str, str], rent: str) -> None:
    """The model sees each to-do's due date and, before it, its send-by day under their own names —
    never the unlabelled day the agenda lists it by (the rent is listed on Fri 2 Oct, due Mon 5 Oct)."""
    run_and_reconcile(store, TODAY)
    agenda = build_agenda(store, TODAY)
    listed = next(entry for entry in agenda.next_7_days if entry.id == rent)
    assert (listed.date, listed.due, listed.send_by) == ("2026-10-02", "2026-10-05", "2026-10-02")
    payload = _model_payload(agenda)
    by_id = {row["id"]: row for row in _rows(payload, "next_7_days")}
    assert by_id[rent]["due"] == "2026-10-05" and by_id[rent]["send_by"] == "2026-10-02"
    assert by_id[ids["semester_fee"]]["due"] == "2026-10-02" and "send_by" not in by_id[ids["semester_fee"]]
    decision = _rows(payload, "decisions_send_by")[0]
    assert decision["send_by"] == "2026-10-08" and "due" not in decision
    assert _rows(payload, "new_ideas") and all("act_by" in row for row in _rows(payload, "new_ideas"))
    sections = ("overdue", "today", "next_7_days", "payments_this_month", "decisions_send_by", "new_ideas")
    assert not any("date" in row for section in sections for row in _rows(payload, section))
    request = brief_request(agenda, store.get_profile(), AppSettings())
    assert '"send_by": "2026-10-02"' in request.prompt and '"due": "2026-10-05"' in request.prompt
    assert "never a due date" in request.system
    assert request.prompt_version == "2+1"


def test_a_missed_or_in_person_send_by_day_is_not_named(store: Store, ids: dict[str, str], rent: str) -> None:
    """A send-by day that has passed means "act today" (the rent is then listed today, with its due date
    only); a payment made in person at an appointment is paid on the day, never transferred ahead."""
    late = build_agenda(store, date(2026, 10, 3))
    entry = next(entry for entry in late.today if entry.id == rent)
    assert (entry.due, entry.send_by) == ("2026-10-05", None)
    row = next(row for row in _rows(_model_payload(late), "today") if row["id"] == rent)
    assert row["due"] == "2026-10-05" and "send_by" not in row

    fee = _visa_fee(store)
    paid_there = next(entry for entry in build_agenda(store, TODAY).next_7_days if entry.id == fee)
    assert (paid_there.due, paid_there.send_by) == ("2026-10-01", None)


def _visa_fee(store: Store) -> str:
    """A visa fee of €93 paid at the appointment on Thu 1 Oct 09:00 (its letter's transfer day: Tue 29 Sep)."""
    doc = add_doc(store, "visa-fee")
    add_item(
        store,
        kind="appointment",
        title="Visa appointment",
        doc_id=doc,
        due_date="2026-10-01",
        due_time="09:00",
    )
    return add_item(
        store,
        kind="payment",
        title="Visa fee",
        doc_id=doc,
        due_date="2026-10-01",
        due_time="09:00",
        send_by="2026-09-29",
        amount=93.0,
        currency="EUR",
        direction="out",
    )


def test_a_fee_paid_at_an_appointment_is_listed_on_its_day(store: Store, ids: dict[str, str]) -> None:
    """A fee paid in person is listed (and the code-written note dates it) on the appointment's day, not
    on the transfer day its letter's deadline gives — which the note would otherwise show unlabelled."""
    fee = _visa_fee(store)
    agenda = build_agenda(store, TODAY)
    entry = next(entry for entry in agenda.next_7_days if entry.id == fee)
    assert (entry.date, entry.due, entry.send_by) == ("2026-10-01", "2026-10-01", None)
    assert (
        agenda_text(Agenda(date=agenda.date, next_7_days=[entry]))
        == "Next 7 days: Visa fee (Thu 1 Oct, €93)."
    )
    # on the transfer day it is not yet today's
    assert all(entry.id != fee for entry in build_agenda(store, date(2026, 9, 29)).today)


def test_agenda_text_says_a_send_by_day_is_one() -> None:
    """The code-written note names a to-do's send-by day as such, with its due date."""
    agenda = Agenda(
        date="2026-09-28",
        next_7_days=[
            AgendaEntry(
                id="itm_rent",
                ref=RefLink(type="item", id="itm_rent"),
                title="Pay monthly rent",
                kind="payment",
                date="2026-10-02",
                due="2026-10-05",
                send_by="2026-10-02",
                amount=640.0,
            ),
            AgendaEntry(
                id="itm_fee",
                ref=RefLink(type="item", id="itm_fee"),
                title="Semester fee",
                kind="payment",
                date="2026-10-02",
                due="2026-10-02",
                amount=320.5,
            ),
        ],
    )
    assert agenda_text(agenda) == (
        "Next 7 days: Pay monthly rent (send by Fri 2 Oct, due Mon 5 Oct, €640); Semester fee (Fri 2 Oct, €320.50)."
    )


MISLABELLED = [
    "Good morning, Sam! Your rent of €640.00 is due Fri 2 Oct.",
    "Then on Fri 2 Oct, the rent of €640.00 and the semester fee of €320.50 are due.",
    "Your rent (Miete) is due on 2 October, so plan ahead.",
    "Your FunkNetz decision is due Thu 8 Oct.",
    "Guten Morgen, Sam! Die Miete von 640,00 € ist am Freitag, 2. Oktober fällig.",
    "Am 2. Oktober sind die Miete (640,00 €) und die Semestergebühr (320,50 €) fällig.",
]


@pytest.mark.parametrize("note", MISLABELLED)
def test_a_note_that_calls_a_send_by_day_due_is_rejected(
    store: Store, ids: dict[str, str], rent: str, note: str
) -> None:
    agenda = build_agenda(store, TODAY)
    assert not Facts.from_data(agenda.model_dump()).unsupported(note)  # every date and amount is there
    assert mislabelled_dates(note, agenda)
    assert not grounded_note(note, agenda)


CORRECT = [
    "Your rent of €640.00 is due Mon 5 Oct, so transfer it by Fri 2 Oct.",
    "Transfer the rent of €640.00 by Fri 2 Oct (it is due Mon 5 Oct).",
    "Send the rent of €640.00 by Fri 2 Oct as it is due Mon 5 Oct.",
    "The semester fee of €320.50 is due Fri 2 Oct.",
    "On Fri 2 Oct the semester fee of €320.50 is due and the rent of €640.00 should go out.",
    "A few things are due on Fri 2 Oct.",
    "Due to the weekend, send the rent of €640.00 by Fri 2 Oct.",
    "Decide on FunkNetz mobile by Thu 8 Oct.",
    GOOD_NOTE,
    "Die Miete von 640,00 € ist am Montag, 5. Oktober fällig; überweise sie bis Freitag, 2. Oktober.",
    "Überweise die Miete (640,00 €) bis 2. Oktober, fällig ist sie am 5. Oktober.",
    "Die Semestergebühr von 320,50 € ist am 2. Oktober fällig.",
]


@pytest.mark.parametrize("note", CORRECT)
def test_a_note_that_labels_its_dates_right_is_accepted(
    store: Store, ids: dict[str, str], rent: str, note: str
) -> None:
    agenda = build_agenda(store, TODAY)
    assert mislabelled_dates(note, agenda) == []
    assert grounded_note(note, agenda)


async def test_brief_text_falls_back_when_the_note_calls_a_send_by_day_due(
    store: Store, ids: dict[str, str], rent: str
) -> None:
    backend = FakeBackend({"brief": {"text": MISLABELLED[0]}})
    agenda = build_agenda(store, TODAY)
    brief = await brief_text(LLMService(backend), agenda, store.get_profile())
    assert (brief.source, brief.text) == ("template", agenda_text(agenda))
    assert "Pay monthly rent (Miete) (send by Fri 2 Oct, due Mon 5 Oct, €640)" in brief.text


# the week of the demo: a transfer that must go out a day or more before its due date, next to to-dos
# due on those days
MON_28, TUE_29 = date(2026, 9, 28), date(2026, 9, 29)
WEEK = [
    # (id, kind, title, party, due, send_by, amount)
    (
        "techmarkt",
        "payment",
        "Pay the reminder amount for invoice TM-4711",
        "TechMarkt Online GmbH",
        "2026-09-30",
        "2026-09-29",
        94.99,
    ),
    ("gym", "payment", "Monthly gym membership fee", "FitWell Studios GmbH", "2026-10-01", None, 29.9),
    (
        "fine",
        "payment",
        "Pay the traffic warning fine (Verwarnungsgeld)",
        "Stadt Musterstadt",
        "2026-10-02",
        "2026-10-01",
        30.0,
    ),
    (
        "rent",
        "payment",
        "Pay monthly rent (Miete)",
        "Wohnbau Musterstadt eG",
        "2026-10-05",
        "2026-10-02",
        640.0,
    ),
    ("fee", "payment", "Pay the accrued library fee", "Stadtbibliothek Musterstadt", "2026-10-02", None, 4.5),
    (
        "books",
        "deadline",
        "Return the overdue library books",
        "Stadtbibliothek Musterstadt",
        "2026-10-02",
        None,
        None,
    ),
]


def _week(today: date) -> Agenda:
    entries = [
        AgendaEntry(
            id=key,
            ref=RefLink(type="item", id=key),
            title=title,
            kind=kind,
            date=send_by or due,
            due=due,
            send_by=send_by,
            amount=amount,
            party=party,
        )
        for key, kind, title, party, due, send_by, amount in WEEK
    ]
    return Agenda(date=today.isoformat(), next_7_days=entries)


MISLABELLED_IN_WEEK = [
    # a day word is the date it names: the reminder is transferred on Tue 29 Sep and due Wed 30 Sep
    (TUE_29, "Good morning Sam! The TechMarkt reminder of €94.99 is due today."),
    (MON_28, "The TechMarkt reminder of €94.99 is due tomorrow."),
    (MON_28, "Die TechMarkt-Mahnung über 94,99 € ist morgen fällig."),
    (MON_28, "The rent of €640.00 is due Friday."),
    (MON_28, "Die Miete (640,00 €) ist am Freitag fällig."),
    # "due by" a send-by day is still calling it due
    (MON_28, "Your rent of €640.00 is due by Fri 2 Oct."),
    (MON_28, "Die Miete von 640,00 € ist bis zum 2. Oktober fällig."),
]


@pytest.mark.parametrize(("today", "note"), MISLABELLED_IN_WEEK)
def test_a_day_word_or_by_date_called_due_is_checked(today: date, note: str) -> None:
    agenda = _week(today)
    assert not Facts.from_data(agenda.model_dump()).unsupported(note)
    assert mislabelled_dates(note, agenda)
    assert not grounded_note(note, agenda)


CORRECT_IN_WEEK = [
    # today's date stated on a send-by day, and a due word with its own day word
    (
        TUE_29,
        "Good morning Sam! Today is Tue 29 Sep; the TechMarkt reminder of €94.99 is due tomorrow, Wed 30 Sep.",
    ),
    (
        TUE_29,
        "Good morning Sam! Today, Tue 29 Sep, transfer the TechMarkt reminder of €94.99, which is due tomorrow.",
    ),
    (
        TUE_29,
        "Good morning Sam! It's Tue 29 Sep, and the TechMarkt reminder of €94.99 is due tomorrow - transfer it today.",
    ),
    (TUE_29, "Tuesday 29 September: pay the TechMarkt reminder of €94.99, due Wednesday."),
    # "amount due … by" names the day to pay by
    (TUE_29, "Settle the TechMarkt amount due of €94.99 by Tue 29 Sep."),
    # an amount in brackets stays in its clause
    (MON_28, "The gym fee (€29.90) is due Thu 1 Oct and the traffic fine (€30.00) is due Fri 2 Oct."),
    (
        MON_28,
        "Das Fitnessstudio (29,90 €) ist am 1. Oktober fällig und das Verwarnungsgeld (30,00 €) am 2. Oktober.",
    ),
    # a to-do named where the note speaks of sending is not what the due word is about
    (
        MON_28,
        "Fri 2 Oct is busy: return the library books and pay the €4.50 fee, both due that day, and transfer "
        "the rent of €640.00.",
    ),
    (
        MON_28,
        "Am 2. Oktober sind die Bibliotheksgebühr von 4,50 € fällig und die Miete von 640,00 € zu überweisen.",
    ),
    # day words for due dates; "Guten Morgen" and "heute Morgen" are no dates
    (
        MON_28,
        "Guten Morgen, Sam! Die Miete von 640,00 € ist am 5. Oktober fällig; überweise sie bis Freitag.",
    ),
    (MON_28, "Good morning, Sam! Transfer the rent of €640.00 by Friday; it is due Monday."),
    (MON_28, "The TechMarkt reminder of €94.99 is due Wednesday; transfer it tomorrow."),
    (MON_28, "Heute Morgen: Die Miete von 640,00 € ist am Montag fällig."),
]


@pytest.mark.parametrize(("today", "note"), CORRECT_IN_WEEK)
def test_a_correct_note_about_the_week_is_accepted(today: date, note: str) -> None:
    agenda = _week(today)
    assert mislabelled_dates(note, agenda) == []
    assert grounded_note(note, agenda)
