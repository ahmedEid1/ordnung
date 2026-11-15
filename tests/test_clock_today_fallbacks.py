"""A function that takes an optional "today" and is given none counts from the app's day (``ordnung.clock.today()``:
the pinned day, else ``ORDNUNG_TODAY``, else the computer's date), never from the computer's date alone.

Each test pins the clock to fixed days in the past and calls the function without a day: the answer is the one for
the pinned day, on whatever date the test runs. Invented letters only; nothing calls a model."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from ordnung import clock
from ordnung.ingest.extract import judge_completion, read_document
from ordnung.ingest.gaps import deadline_items
from ordnung.llm.runtime import LLMService
from ordnung.models import RefLink
from ordnung.secretary.brief import Agenda, AgendaEntry, agenda_text, mislabelled_dates
from test_brief import MON_28, TUE_29, _week
from test_reading_gaps import blank, page
from test_reading_reask import BLANK, COMPLETE, DECISION, answering, data_for, pages_of, reading

#: While the decision's objection period runs, and once it has ended.
RUNNING, ENDED = date(2026, 9, 25), date(2027, 3, 1)


def test_the_re_ask_s_judge_counts_from_the_app_s_day_when_given_none() -> None:
    """The re-ask's answer on the decision is used while the objection period runs, and kept out once it has ended
    (its date would be one the person can no longer keep)."""
    first, second, pages = reading(BLANK), reading(COMPLETE), pages_of(DECISION)
    verdicts = {}
    for day in (RUNNING, ENDED):
        clock.set_today(day)
        verdicts[day] = judge_completion("doc_x", first, second, pages, gap="empty")
    assert verdicts == {RUNNING: None, ENDED: "date"}


async def test_a_reading_without_its_day_judges_the_re_ask_on_the_app_s_day() -> None:
    """No arrival day and no readable ``today`` in the input: the re-ask is judged on the app's day."""
    data = replace(data_for(), today="")
    outcomes = {}
    for day in (RUNNING, ENDED):
        clock.set_today(day)
        result = await read_document(LLMService(answering(BLANK, COMPLETE)), data, model="m")
        assert result.completion is not None
        outcomes[day] = (result.completion.accepted, result.completion.kept_because)
    assert outcomes == {RUNNING: (True, None), ENDED: (False, "date")}


#: A bill with no date of its own, and a reading whose one to-do is due 20 days from today.
BILL = page(
    "Stadtwerke Beispielhausen GmbH · Werkstraße 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Zahlungsziel: 15.10.2026",
    "Rechnung Nr. 4711",
)
IN_20_DAYS = {
    "kind": "task",
    "title": "Send the meter reading",
    "date": {"type": "relative", "anchor": "today", "amount": 20, "unit": "days", "shift_rule": "none"},
    "quote": "Rechnung Nr. 4711",
}


def test_the_dropped_date_check_counts_the_reading_s_to_dos_from_the_app_s_day() -> None:
    reading_ = blank(sender={"name": "Stadtwerke Beispielhausen GmbH", "kind": "utility"}, items=[IN_20_DAYS])
    clock.set_today(RUNNING)  # 20 days on is 15 Oct, the bill's own date: the reading has it
    assert deadline_items(reading_, [BILL]) == []
    clock.set_today(date(2026, 6, 1))  # 20 days on is 21 Jun: the bill's 15 Oct is left out
    assert [item.date.date for item in deadline_items(reading_, [BILL])] == ["2026-10-15"]


def test_the_brief_without_its_day_writes_dates_for_the_app_s_day() -> None:
    """A date shows its year only when it isn't today's."""
    entry = AgendaEntry(
        id="it_1",
        ref=RefLink(type="item", id="it_1"),
        title="Pay the invoice",
        kind="payment",
        date="2026-01-05",
        due="2026-01-05",
        amount=12.0,
    )
    undated = Agenda(date="", next_7_days=[entry])
    clock.set_today(date(2025, 12, 29))
    assert "(Mon 5 Jan 2026," in agenda_text(undated)
    clock.set_today(date(2026, 1, 2))
    assert "(Mon 5 Jan," in agenda_text(undated)


def test_the_due_word_check_without_its_day_reads_day_words_on_the_app_s_day() -> None:
    note = "The TechMarkt reminder of €94.99 is due tomorrow."
    undated = _week(MON_28).model_copy(update={"date": ""})
    clock.set_today(MON_28)  # tomorrow is Tue 29 Sep, the day to transfer it by: not the day it is due
    assert mislabelled_dates(note, undated) == ["tomorrow"]
    clock.set_today(TUE_29)  # tomorrow is Wed 30 Sep, the day it is due
    assert mislabelled_dates(note, undated) == []
