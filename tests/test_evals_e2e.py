"""evals/e2e: the benchmark's letters through the real app, from the letter file to the reminder.

The checker (``evals.e2e.check``) is tested on hand-made observations — every verdict once right and once
broken (the mutation tests: take one element away from a correct reminder or draft and the check must fail)
— and the harness (``evals.e2e.harness``) on three recorded letters (a PDF, a photo, an objection letter):
no reading misses its recording, two runs give the same bytes, and no letter text reaches the results."""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from icalendar import Alarm, Calendar, Event

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.e2e import check, metrics, observe, report  # noqa: E402
from evals.e2e.check import DRAFT_ELEMENTS, check_letter, draft_elements  # noqa: E402
from evals.e2e.observe import (  # noqa: E402
    AgendaProbe,
    CalendarEvent,
    DraftSeen,
    IdeaSeen,
    LetterObservation,
    StoredItem,
)
from evals.records import Entry, load_manifest  # noqa: E402
from evals.run import MANIFEST_PATH  # noqa: E402

READ_ON = "2026-03-09"
GOLD = "2026-03-20"
SIGNER = "Sam Rivera"


def _entry(
    *,
    entry_id: str = "test-tax_assessment-Z1",
    split: str = "test",
    remedy: str = "einspruch",
    warnings: tuple[str, ...] = (),
    items: tuple[dict[str, Any], ...] | None = None,
    photo: bool = False,
    source_id: str | None = None,
) -> Entry:
    """A made-up benchmark entry (no letter of the dataset)."""
    truth_items = (
        items
        if items is not None
        else (
            {
                "kind": "deadline",
                "nature": "objection",
                "title": "Object to the decision",
                "expected_due": GOLD,
                "spec": {"type": "relative", "amount": 1, "unit": "months"},
            },
        )
    )
    return Entry.model_validate(
        {
            "id": entry_id,
            "split": split,
            "family": entry_id.split("-")[1],
            "variant": "Z1",
            "file": f"{split}/{entry_id}.pdf",
            "sha256": "0" * 64,
            "photo": photo,
            "source_id": source_id,
            "today": READ_ON,
            "truth": {
                "kind": "tax_assessment",
                "sender_name": "Finanzamt Musterstadt",
                "document_date": "2026-02-16",
                "references": [{"label": "Steuernummer", "value": "123/456/78901"}],
                "remedy_type": remedy,
                "items": list(truth_items),
                "expected_warnings": list(warnings),
            },
        }
    )


def _item(**changes: Any) -> StoredItem:
    base: dict[str, Any] = {
        "id": "itm_1",
        "kind": "deadline",
        "title": "Object to the decision",
        "quote": "innerhalb eines Monats",
        "due_date": GOLD,
        "status": "open",
    }
    return StoredItem.model_validate(base | changes)


def _alarm_days(due: str, before: tuple[int, ...] = (14, 7, 3, 1)) -> list[str]:
    day = date.fromisoformat(due)
    return [(day - timedelta(days=days)).isoformat() for days in before]


def _observation(**changes: Any) -> LetterObservation:
    """What the app showed for :func:`_entry`: the to-do on its day, alarms 14/7/3/1 days before, on the
    morning note the day before, a deadline Idea, no scam signs."""
    base: dict[str, Any] = {
        "entry_id": "test-tax_assessment-Z1",
        "status": "processed",
        "items": [_item()],
        "events": [
            {"uid": "itm_1@ordnung.local", "item_id": "itm_1", "start": GOLD, "alarm_days": _alarm_days(GOLD)}
        ],
        "agenda": [{"day": "2026-03-19", "item_ids": ["itm_1"]}],
        "ideas": [
            {"rule_id": "deadline_soon", "kind": "deadline", "due_date": GOLD, "item_ids": ["itm_1"]},
        ],
        "reminder_windows": {"deadline": 14, "payment": 7},
    }
    return LetterObservation.model_validate(base | changes)


# --------------------------------------------------------------------------------------------------
# what the calendar file says
# --------------------------------------------------------------------------------------------------


def _ics(*events: Event) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//test//")
    calendar.add("version", "2.0")
    for event in events:
        calendar.add_component(event)
    return bytes(calendar.to_ical())


def _event(uid: str, start: date | datetime, *triggers: timedelta) -> Event:
    event = Event()
    event.add("uid", uid)
    event.add("dtstart", start)
    for trigger in triggers:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", "x")
        alarm.add("trigger", trigger)
        event.add_component(alarm)
    return event


def test_an_all_day_event_s_alarms_fire_on_the_days_before_it() -> None:
    ics = _ics(_event("a@ordnung.local", date(2026, 3, 20), timedelta(days=-14, hours=9), timedelta(hours=9)))
    (event,) = observe.calendar_events(ics)
    assert event.uid == "a@ordnung.local"
    assert event.start == "2026-03-20"
    assert event.alarm_days == ["2026-03-06", "2026-03-20"]


def test_a_timed_event_s_alarm_fires_on_its_own_local_day() -> None:
    start = datetime(2026, 3, 20, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    ics = _ics(_event("b@ordnung.local", start, timedelta(hours=-1), timedelta(days=-2)))
    (event,) = observe.calendar_events(ics)
    assert event.start == "2026-03-20"
    assert event.alarm_days == ["2026-03-18", "2026-03-19"]


def test_an_event_without_alarms_has_none() -> None:
    (event,) = observe.calendar_events(_ics(_event("c@ordnung.local", date(2026, 3, 20))))
    assert event.alarm_days == []


# --------------------------------------------------------------------------------------------------
# reminders: the check, then each part taken away
# --------------------------------------------------------------------------------------------------


def _only(entry: Entry, obs: LetterObservation, bench: dict[int, str | None] | None = None) -> Any:
    verdict = check_letter(entry, obs, bench=bench)
    (obligation,) = verdict.obligations
    return obligation


def test_an_obligation_with_an_alarm_on_or_before_its_day_is_reminded_in_time() -> None:
    obligation = _only(_entry(), _observation(), {0: GOLD})
    assert obligation.stored == GOLD
    assert obligation.exact
    assert obligation.parity is True
    assert obligation.reminded
    assert obligation.lead_days == 7  # the 14-day alarm fell before the reading day
    assert not obligation.late_reminder
    assert obligation.morning_note
    assert obligation.idea_due
    assert obligation.idea_right is True
    assert obligation.not_reminded is None


def test_an_alarm_on_the_day_itself_still_counts_but_one_before_the_reading_day_does_not() -> None:
    on_the_day = _observation(
        events=[{"uid": "u", "item_id": "itm_1", "start": GOLD, "alarm_days": ["2026-02-20", GOLD]}]
    )
    obligation = _only(_entry(), on_the_day)
    assert obligation.reminded
    assert obligation.lead_days == 0
    gone = _observation(
        events=[{"uid": "u", "item_id": "itm_1", "start": GOLD, "alarm_days": ["2026-02-20"]}]
    )
    obligation = _only(_entry(), gone)
    assert not obligation.reminded
    assert obligation.not_reminded == "no_alarm_from_the_reading_day"


def test_alarms_only_after_the_day_are_a_late_reminder() -> None:
    late = "2026-03-27"
    obs = _observation(
        items=[_item(due_date=late)],
        events=[{"uid": "u", "item_id": "itm_1", "start": late, "alarm_days": _alarm_days(late, (3, 1))}],
    )
    obligation = _only(_entry(), obs, {0: late})
    assert not obligation.exact
    assert obligation.parity is True  # the benchmark's date is the same late one
    assert not obligation.reminded
    assert obligation.late_reminder
    assert obligation.not_reminded == "only_after_the_day"


def test_an_obligation_the_app_did_not_store_is_not_reminded() -> None:
    obs = _observation(items=[], events=[], agenda=[], ideas=[])
    obligation = _only(_entry(), obs, {0: None})
    assert obligation.stored is None
    assert obligation.parity is True
    assert not obligation.reminded
    assert obligation.not_reminded == "not_stored"
    assert not obligation.morning_note
    assert obligation.idea_right is False


def test_a_stored_to_do_without_a_date_is_not_reminded() -> None:
    obs = _observation(items=[_item(due_date=None)], events=[], agenda=[], ideas=[])
    obligation = _only(_entry(), obs)
    assert obligation.not_reminded == "no_date"


def test_a_set_aside_to_do_is_not_reminded_and_says_why() -> None:
    obs = _observation(
        items=[_item(set_aside=["scam_signs"])],
        events=[],
        agenda=[],
        ideas=[{"rule_id": "scam_warning", "kind": "scam", "due_date": None, "doc_ids": ["doc_1"]}],
        scam_reasons=["hidden_text", "reading_warning:prompt injection"],
    )
    verdict = check_letter(_entry(warnings=("hidden_text", "injection")), obs, bench={0: GOLD})
    (obligation,) = verdict.obligations
    assert obligation.exact  # the date was right ...
    assert not obligation.reminded  # ... and still nothing reminds the person of it
    assert obligation.not_reminded == "set_aside:scam_signs"
    assert verdict.scam_idea
    assert verdict.scam_reasons == ["hidden_text", "reading_warning:prompt injection"]


def test_a_dated_to_do_missing_from_the_calendar_is_not_reminded() -> None:
    obligation = _only(_entry(), _observation(events=[]))
    assert obligation.not_reminded == "not_in_calendar"


def test_the_morning_note_must_list_the_obligation_s_own_to_do() -> None:
    other = _observation(agenda=[AgendaProbe(day="2026-03-19", item_ids=["itm_2"]).model_dump()])
    assert not _only(_entry(), other).morning_note
    wrong_day = _observation(agenda=[{"day": "2026-03-18", "item_ids": ["itm_1"]}])
    assert not _only(_entry(), wrong_day).morning_note


def test_the_morning_note_is_looked_at_on_the_reading_day_when_the_day_before_has_passed() -> None:
    entry = _entry(
        items=(
            {"kind": "deadline", "nature": "objection", "expected_due": READ_ON, "spec": {"type": "fixed"}},
        )
    )
    obs = _observation(
        items=[_item(due_date=READ_ON)],
        events=[{"uid": "u", "item_id": "itm_1", "start": READ_ON, "alarm_days": [READ_ON]}],
        agenda=[{"day": READ_ON, "item_ids": ["itm_1"]}],
    )
    assert check.probe_day(entry, date.fromisoformat(READ_ON)) == date.fromisoformat(READ_ON)
    assert _only(entry, obs).morning_note


def test_the_deadline_idea_must_name_the_to_do_and_act_by_the_day() -> None:
    late_idea = _observation(
        ideas=[
            {"rule_id": "deadline_soon", "kind": "deadline", "due_date": "2026-03-21", "item_ids": ["itm_1"]}
        ]
    )
    assert _only(_entry(), late_idea).idea_right is False
    other_rule = _observation(
        ideas=[{"rule_id": "overdue", "kind": "deadline", "due_date": GOLD, "item_ids": ["itm_1"]}]
    )
    assert _only(_entry(), other_rule).idea_right is False


def test_a_deadline_beyond_the_idea_window_expects_no_idea() -> None:
    far = "2026-04-30"
    entry = _entry(
        items=({"kind": "deadline", "nature": "objection", "expected_due": far, "spec": {"type": "fixed"}},)
    )
    obs = _observation(
        items=[_item(due_date=far)],
        events=[{"uid": "u", "item_id": "itm_1", "start": far, "alarm_days": _alarm_days(far)}],
        agenda=[{"day": "2026-04-29", "item_ids": ["itm_1"]}],
        ideas=[],
    )
    obligation = _only(entry, obs)
    assert not obligation.idea_due
    assert obligation.idea_right is None


def test_parity_compares_the_stored_date_with_the_benchmark_s_and_is_unknown_without_it() -> None:
    assert _only(_entry(), _observation(), {0: "2026-03-19"}).parity is False
    assert _only(_entry(), _observation(), None).parity is None


def test_the_stored_to_do_is_found_by_the_benchmark_s_own_matching() -> None:
    """A payment of the letter never stands in for its objection deadline."""
    obs = _observation(
        items=[
            _item(
                id="itm_pay",
                kind="payment",
                title="Pay the tax",
                quote="zahlen Sie",
                due_date="2026-03-05",
                amount=120.0,
            ),
            _item(),
        ],
    )
    obligation = _only(_entry(), obs)
    assert obligation.item_id == "itm_1"


def test_a_scam_letter_s_items_are_no_genuine_obligations_and_its_events_are_counted() -> None:
    entry = _entry(
        entry_id="test-adversarial-scam-9",
        remedy="none",
        warnings=("scam",),
        items=(
            {
                "kind": "payment",
                "nature": "payment",
                "expected_due": GOLD,
                "spec": {"type": "fixed"},
                "amount": 99.0,
            },
        ),
    )
    obs = _observation(
        entry_id=entry.id,
        items=[_item(kind="payment")],
        ideas=[],
    )
    verdict = check_letter(entry, obs)
    assert verdict.scam_gold
    assert not verdict.scam_idea
    assert verdict.calendar_events == 1
    assert verdict.obligations == []


def test_a_letter_that_failed_to_read_says_so() -> None:
    obs = _observation(status="failed", items=[], events=[], agenda=[], ideas=[])
    obligation = _only(_entry(), obs)
    assert obligation.not_reminded == "reading_failed"


# --------------------------------------------------------------------------------------------------
# the objection letter: complete, then each element taken away
# --------------------------------------------------------------------------------------------------


def _pdf_lines() -> list[str]:
    return [
        "Sam Rivera · Musterweg 1 · 50667 Köln",
        "Finanzamt Musterstadt",
        "Postfach 1",
        "12345 Musterstadt",
        "Köln, 9. März 2026",
        "Einspruch gegen den Bescheid vom 16.02.2026, Steuernummer 123/456/78901",
        "Sehr geehrte Damen und Herren,",
        "hiermit lege ich Einspruch gegen den Bescheid vom 16.02.2026 ein.",
        "Mit freundlichen Grüßen",
        "Sam Rivera",
    ]


def _draft(**changes: Any) -> DraftSeen:
    base: dict[str, Any] = {
        "recipient_block": "Finanzamt Musterstadt\nPostfach 1\n12345 Musterstadt",
        "must_arrive_by": GOLD,
        "send_by": "2026-03-16",
        "pdf_lines": _pdf_lines(),
        "signer": SIGNER,
        "own_checks_failed": [],
    }
    return DraftSeen.model_validate(base | changes)


def _elements(draft: DraftSeen, entry: Entry | None = None) -> dict[str, bool | None]:
    entry = entry or _entry()
    return draft_elements(entry.truth, draft, objection_due=date.fromisoformat(GOLD), signer=SIGNER)


def _replace_lines(old: str, new: str) -> Callable[[DraftSeen], DraftSeen]:
    def mutate(draft: DraftSeen) -> DraftSeen:
        return draft.model_copy(update={"pdf_lines": [line.replace(old, new) for line in draft.pdf_lines]})

    return mutate


#: For every element of a complete objection letter, one way to take it away.
MUTATIONS: dict[str, Callable[[DraftSeen], DraftSeen]] = {
    "remedy_word": _replace_lines("Einspruch", "Schreiben"),
    "reference": _replace_lines("123/456/78901", "123/456/78999"),
    "decision_date": _replace_lines("16.02.2026", "17.02.2026"),
    "addressee": lambda d: d.model_copy(update={"recipient_block": "Stadtwerke Beispielhausen\nPostfach 9"}),
    "deadline": lambda d: d.model_copy(update={"must_arrive_by": "2026-03-19"}),
    "send_by": lambda d: d.model_copy(update={"send_by": "2026-03-21"}),
    "signature": lambda d: d.model_copy(update={"pdf_lines": d.pdf_lines[:-1]}),
    "no_placeholder": lambda d: d.model_copy(
        update={"pdf_lines": [*d.pdf_lines[:-2], "[Ihr Name]", *d.pdf_lines[-2:]]}
    ),
}


def test_a_complete_objection_letter_passes_every_element() -> None:
    elements = _elements(_draft())
    assert set(elements) == set(DRAFT_ELEMENTS)
    assert all(elements.values()), elements
    assert check.draft_complete(elements)


def test_every_element_has_a_mutation() -> None:
    assert set(MUTATIONS) == set(DRAFT_ELEMENTS)


@pytest.mark.parametrize("element", DRAFT_ELEMENTS)
def test_taking_any_element_away_fails_that_element_and_the_letter(element: str) -> None:
    elements = _elements(MUTATIONS[element](_draft()))
    assert elements[element] is False, elements
    assert [name for name, ok in elements.items() if ok is False] == [element]
    assert not check.draft_complete(elements)


def test_the_remedy_word_must_be_the_letter_s_own() -> None:
    elements = _elements(_draft(), _entry(remedy="widerspruch"))
    assert elements["remedy_word"] is False


def test_a_letter_that_also_names_the_other_remedy_fails_the_remedy_word() -> None:
    lines = [*_pdf_lines()[:-2], "Hilfsweise lege ich Widerspruch ein.", *_pdf_lines()[-2:]]
    assert _elements(_draft(pdf_lines=lines))["remedy_word"] is False


def test_an_element_the_labels_cannot_judge_is_left_out_not_failed() -> None:
    entry = _entry()
    truth = entry.truth.model_copy(update={"references": [], "document_date": None})
    elements = draft_elements(truth, _draft(), objection_due=None, signer=SIGNER)
    assert elements["reference"] is None
    assert elements["decision_date"] is None
    assert elements["deadline"] is None
    assert elements["send_by"] is None
    assert check.draft_complete(elements)


def test_the_decision_date_is_found_written_out_in_german() -> None:
    lines = [line.replace("16.02.2026", "16. Februar 2026") for line in _pdf_lines()]
    assert _elements(_draft(pdf_lines=lines))["decision_date"] is True


def test_a_refused_objection_letter_is_no_draft() -> None:
    verdict = check_letter(
        _entry(), _observation(draft=DraftSeen(refused=True, error="DraftError").model_dump())
    )
    assert verdict.draft is not None
    assert verdict.draft.refused
    assert not verdict.draft.complete


def test_the_check_of_a_draft_uses_the_letter_s_objection_day() -> None:
    verdict = check_letter(_entry(), _observation(draft=_draft().model_dump()))
    assert verdict.draft is not None
    assert verdict.draft.complete


# --------------------------------------------------------------------------------------------------
# the checker is independent of what it checks
# --------------------------------------------------------------------------------------------------


def test_the_checker_imports_nothing_of_the_app() -> None:
    """The verdicts come from the labels and what the person gets, never from the rules engine, the draft's own
    checks or Ask's check: importing the checker, the metrics and the observation types loads no ``ordnung``."""
    code = (
        "import sys; import evals.e2e.check, evals.e2e.metrics, evals.e2e.observe; "
        "print(sorted(m for m in sys.modules if m == 'ordnung' or m.startswith('ordnung.')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True, env=_pythonpath()
    )
    assert done.stdout.strip() == "[]"


def _pythonpath() -> dict[str, str]:
    import os

    return {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}


# --------------------------------------------------------------------------------------------------
# the numbers
# --------------------------------------------------------------------------------------------------


def _verdict(
    entry_id: str, *, reminded: bool, split: str = "test", source_id: str | None = None
) -> check.LetterVerdict:
    entry = _entry(entry_id=entry_id, split=split, source_id=source_id, photo=source_id is not None)
    obs = _observation(entry_id=entry_id) if reminded else _observation(entry_id=entry_id, events=[])
    return check_letter(entry, obs, bench={0: GOLD})


def test_the_rates_count_obligations_and_resample_a_photo_with_its_pdf() -> None:
    verdicts = [
        _verdict("test-tax_assessment-A1", reminded=True),
        _verdict("test-tax_assessment-A1-photo", reminded=False, source_id="test-tax_assessment-A1"),
        _verdict("holdout-tax_assessment-B1", reminded=True, split="holdout"),
        _verdict("dev-tax_assessment-C1", reminded=False, split="dev"),
    ]
    summary = metrics.summarise(verdicts, seed=1, resamples=200)
    pooled = summary["pooled"]
    assert pooled["obligations"] == 3  # dev is reported apart
    assert pooled["reminded_in_time"]["k"] == 2
    assert pooled["reminded_in_time"]["n"] == 3
    assert pooled["reminded_in_time"]["docs"] == 3
    assert pooled["parity"] == {"k": 3, "n": 3, "differ": []}
    assert pooled["not_reminded"] == {"not_in_calendar": 1}
    assert summary["by_split"]["dev"]["reminded_in_time"]["k"] == 0
    assert summary["by_modality"]["photo"]["reminded_in_time"]["n"] == 1
    assert summary["by_family"]["tax_assessment"]["reminded_in_time"]["n"] == 3


def test_the_lead_days_are_summarised_over_the_reminded_obligations() -> None:
    summary = metrics.summarise([_verdict("test-tax_assessment-A1", reminded=True)], seed=1, resamples=50)
    assert summary["pooled"]["lead_days"] == {"min": 7, "median": 7.0, "max": 7}


def test_set_aside_obligations_are_listed_by_id_with_their_cause() -> None:
    obs = _observation(items=[_item(set_aside=["scam_signs"])], events=[], scam_reasons=["hidden_text"])
    entry = _entry(entry_id="test-adversarial-hidden_text-9", warnings=("hidden_text", "injection"))
    rows = metrics.set_aside([check_letter(entry, obs, bench={0: GOLD})])
    assert rows == [
        {
            "entry_id": "test-adversarial-hidden_text-9",
            "split": "test",
            "family": "adversarial",
            "variant": "Z1",
            "modality": "text",
            "index": 0,
            "kind": "deadline",
            "nature": "objection",
            "date_right": True,
            "cause": "set_aside:scam_signs",
            "scam_reasons": ["hidden_text"],
            "scam_idea": False,
        }
    ]


# --------------------------------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------------------------------


def _results(**pooled: Any) -> dict[str, Any]:
    block: dict[str, Any] = {
        "parity": {"k": 2, "n": 2, "differ": []},
        "late_reminders": [],
        "reminded_in_time": {"value": 0.5, "ci": [0.1, 0.9], "k": 1, "n": 2, "docs": 2},
    }
    return {
        "metrics": {"all": block | pooled, "pooled": block | pooled, "by_split": {}},
        "set_aside": [],
        "errors": [],
    }


def test_gates_pass_on_good_results() -> None:
    assert (
        report.gate_failures(_results(), exact_parity=True, max_late_reminders=0, known_set_aside=None) == []
    )


def test_a_parity_difference_fails_the_exact_parity_gate_by_id() -> None:
    results = _results(parity={"k": 1, "n": 2, "differ": ["test-x-1#0"]})
    failures = report.gate_failures(results, exact_parity=True)
    assert len(failures) == 1 and "test-x-1#0" in failures[0]
    assert report.gate_failures(results, exact_parity=False) == []


def test_a_late_reminder_fails_its_gate() -> None:
    failures = report.gate_failures(_results(late_reminders=["test-x-1#0"]), max_late_reminders=0)
    assert len(failures) == 1 and "test-x-1#0" in failures[0]


def test_a_newly_set_aside_obligation_fails_by_id_and_a_known_one_does_not() -> None:
    results = _results()
    results["set_aside"] = [{"entry_id": "test-adversarial-hidden_text-1", "index": 0}]
    assert report.gate_failures(results, known_set_aside=["test-adversarial-hidden_text-1"]) == []
    failures = report.gate_failures(results, known_set_aside=[])
    assert len(failures) == 1 and "test-adversarial-hidden_text-1" in failures[0]


def test_a_known_set_aside_letter_that_is_now_reminded_is_said_too() -> None:
    failures = report.gate_failures(_results(), known_set_aside=["test-adversarial-hidden_text-1"])
    assert len(failures) == 1 and "no longer" in failures[0]


def test_the_minimum_share_reminded_is_a_gate() -> None:
    assert report.gate_failures(_results(), min_reminded=0.5) == []
    assert len(report.gate_failures(_results(), min_reminded=0.6)) == 1


def test_a_published_file_equals_a_fresh_run_whatever_its_date_and_commit() -> None:
    fresh = _results()
    fresh["meta"] = {"date": "2026-10-29", "commit": "abc1234", "checker_sha256": "1"}
    published = copy.deepcopy(fresh)
    published["meta"] |= {"date": "2026-10-01", "commit": "def5678"}
    assert report.differences(fresh, published) == []
    published["meta"]["checker_sha256"] = "2"
    published["metrics"]["pooled"]["parity"] = {"k": 1, "n": 2, "differ": ["test-x-1#0"]}
    assert report.differences(fresh, published) == ["meta.checker_sha256", "metrics"]


def test_a_letter_the_harness_could_not_run_always_fails() -> None:
    results = _results()
    results["errors"] = [{"entry_id": "test-x-1", "error": "ReplayMiss"}]
    assert report.gate_failures(results) == ["test-x-1: ReplayMiss"]


# --------------------------------------------------------------------------------------------------
# the harness on three recorded letters
# --------------------------------------------------------------------------------------------------

#: A PDF without a remedy (an objection is refused), a phone photo, and an objection letter.
THREE = ("test-invoice_relative-C1", "test-appointment-C2-photo", "test-tax_assessment-C1")


@pytest.fixture(scope="module")
def three_runs(tmp_path_factory: pytest.TempPathFactory) -> Iterator[list[bytes]]:
    from evals.e2e import __main__ as cli

    outs = []
    for run in ("first", "second"):
        folder = tmp_path_factory.mktemp(f"e2e-{run}")
        code = cli.main(
            [
                "--splits",
                "test",
                "--ids",
                *THREE,
                "--date",
                "2026-10-29",
                "--out",
                str(folder),
                "--exact-parity",
            ]
        )
        assert code == 0
        (written,) = folder.glob("*.json")
        assert written.name == "2026-10-29-claude-sonnet-5-e2e-test-partial.json"
        outs.append(written.read_bytes())
    yield outs


def test_three_letters_replay_every_reading_and_need_no_model(three_runs: list[bytes]) -> None:
    results = json.loads(three_runs[0])
    replay = results["meta"]["replay"]
    assert replay["misses"] == {}
    assert replay["hits"]["extract"] >= 3
    assert replay["hits"]["transcribe"] >= 1  # the photo
    assert replay["draft_without_recording"] == 1  # the objection letter; the refused one asks no model
    assert results["errors"] == []
    assert [row["entry_id"] for row in results["letters"]] == sorted(THREE)


def test_three_letters_reach_the_person(three_runs: list[bytes]) -> None:
    results = json.loads(three_runs[0])
    pooled = results["metrics"]["pooled"]
    assert pooled["parity"]["differ"] == []
    assert pooled["reminded_in_time"]["n"] == 3
    letters = {row["entry_id"]: row for row in results["letters"]}
    assert letters["test-invoice_relative-C1"]["objection_on_none"] == "refused"
    draft = letters["test-tax_assessment-C1"]["draft"]
    assert draft["refused"] is False
    assert set(draft["elements"]) == set(DRAFT_ELEMENTS)


def test_two_runs_give_the_same_bytes(three_runs: list[bytes]) -> None:
    assert three_runs[0] == three_runs[1]


def test_no_letter_text_reaches_the_results(three_runs: list[bytes]) -> None:
    """Ids, dates, kinds, counts and verdicts only: no title, quote, sender, reference or phrase of a letter."""
    text = three_runs[0].decode("utf-8")
    manifest = {entry.id: entry for entry in load_manifest(MANIFEST_PATH)}
    for entry_id in THREE:
        truth = manifest[entry_id].truth
        strings = [
            truth.sender_name,
            *(ref.value for ref in truth.references),
            *(item.title for item in truth.items),
            *manifest[entry_id].key_phrases,
        ]
        for value in strings:
            if len(value) >= 6:
                assert value not in text, f"letter text of {entry_id} in the results"


def test_the_results_name_the_checker_s_hash(three_runs: list[bytes]) -> None:
    import hashlib

    results = json.loads(three_runs[0])
    expected = hashlib.sha256((ROOT / "evals" / "e2e" / "check.py").read_bytes()).hexdigest()
    assert results["meta"]["checker_sha256"] == expected


def test_the_partial_run_says_which_letters(three_runs: list[bytes]) -> None:
    results = json.loads(three_runs[0])
    assert results["meta"]["partial"] is True
    assert results["meta"]["ids"] == sorted(THREE)


def test_the_set_aside_check_reads_the_scam_verdict_by_cause() -> None:
    """The app's reasons for a letter with scam signs become causes without their words: a reason the app
    gives in a letter's own text never reaches the results."""
    from evals.e2e.harness import reason_codes

    hidden = "The letter contains hidden text that you can't see on the page."
    codes = reason_codes(
        [
            hidden,
            "Possible prompt injection: the letter asks the reader to ignore its deadline",
            "This document contains text addressed to an AI (“a phrase of the letter”). Ordnung treated it as ordinary "
            "content and ignored it — be careful with this document.",
            "The IBAN DE00 1234 fails its checksum, so it can't be a real account number.",
            "The payee differs from the one the sender used before.",
        ],
        warnings=["Possible prompt injection: the letter asks the reader to ignore its deadline"],
    )
    assert codes == [
        "hidden_text",
        "iban_checksum",
        "injection_warning",
        "payment_check",
        "reading_warning:prompt injection",
    ]


def test_a_reason_names_every_scam_word_in_it_and_other_when_none() -> None:
    from evals.e2e.harness import reason_codes

    quoted = "This document contains text addressed to an AI (“a fake notice”). Ordnung treated it as ordinary content."
    phishing = "This looks like phishing and the sender may be impersonating the tax office."
    codes = reason_codes([quoted, phishing, "Something odd."], warnings=[phishing, "Something odd."])
    assert codes == ["injection_warning:fake", "reading_warning:other", "reading_warning:phish+impersonat"]


def test_a_copy_of_an_observation_round_trips_through_json() -> None:
    obs = _observation(draft=_draft().model_dump())
    again = LetterObservation.model_validate(json.loads(obs.model_dump_json()))
    assert again == obs
    assert copy.deepcopy(obs) == obs
    assert IdeaSeen(rule_id="x", kind="deadline").item_ids == []
    assert CalendarEvent(uid="u", start=GOLD).item_id is None


def test_the_file_name_says_which_splits_unless_they_are_the_usual_ones(tmp_path: Path) -> None:
    """A run of the final split never overwrites the run of the earlier ones made on the same day."""
    usual = ["test", "holdout", "holdout2", "holdout3", "dev"]
    assert report.results_path("2026-10-29", "claude-sonnet-5", tmp_path, splits=usual).name == (
        "2026-10-29-claude-sonnet-5-e2e.json"
    )
    assert report.results_path(
        "2026-10-29", "claude-sonnet-5", tmp_path, splits=["holdout3", "dev"]
    ).name == ("2026-10-29-claude-sonnet-5-e2e-holdout3-dev.json")
    assert report.results_path("2026-10-29", "m", tmp_path, splits=usual, partial=True).name == (
        "2026-10-29-m-e2e-partial.json"
    )


def test_the_cli_writes_nothing_with_no_write(tmp_path: Path) -> None:
    from evals.e2e import __main__ as cli

    code = cli.main(["--splits", "test", "--ids", THREE[0], "--out", str(tmp_path), "--no-write"])
    assert code == 0
    assert list(tmp_path.iterdir()) == []


def test_the_harness_leaves_the_clock_as_it_found_it() -> None:
    from evals.e2e import harness

    from ordnung import clock

    entries = [e for e in load_manifest(MANIFEST_PATH) if e.id == THREE[0]]
    asyncio.run(harness.observe_all(entries))
    assert not clock.simulated()
