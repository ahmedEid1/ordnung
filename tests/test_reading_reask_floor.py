"""The completeness re-ask never leaves a letter worse off than its first reading with the code's check behind it
(ADR 0016): reproductions, each run through the pipeline twice — once with the re-ask's answer, once
with a re-ask whose answer is unusable (the *baseline*: the first reading kept, the check's to-do filed) — and the
two compared. A rejected answer must give exactly the baseline; the good answers must still be used.

Every letter here is synthetic and written in this file; nothing calls a model.
"""

from __future__ import annotations

import copy
import itertools
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TODAY, Letter
from helpers_tables import check_rows_async
from ordnung import clock
from ordnung.app_context import build_context
from ordnung.ingest.extract import reask_warning
from ordnung.ingest.gaps import CHECK_SLOT
from ordnung.ingest.pipeline import add_file
from ordnung.ingest.plan import needs_check
from ordnung.llm.base import (
    ClaudeAuthError,
    ClaudeBadOutput,
    ClaudeNotInstalled,
    ClaudeRateLimited,
    ClaudeTimeout,
    LLMError,
    LLMRequest,
)
from ordnung.llm.fake import FakeBackend
from ordnung.trace.view import document_trace


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


# --------------------------------------------------------------------------------------------------
# Letters (synthetic) and readings
# --------------------------------------------------------------------------------------------------

HEAD = "Stadt Musterhausen · Bauordnungsamt · Marktplatz 3 · 54321 Musterhausen"
NOTICE = "Gegen diesen Gebührenbescheid können Sie innerhalb eines Monats nach seiner Bekanntgabe Widerspruch erheben."
#: The notice as printed: wrapped onto a second line, as letters do.
NOTICE_LINES = (
    "Rechtsbehelfsbelehrung",
    "Gegen diesen Gebührenbescheid können Sie innerhalb eines Monats",
    "nach seiner Bekanntgabe Widerspruch erheben.",
)
PAYLINE = "Bitte zahlen Sie den Betrag von 85,00 EUR bis zum 05.10.2026."
PLANLINE = "Bitte reichen Sie den Lageplan bis zum 01.10.2026 ein."
PLANTED = "Die Widerspruchsfrist endet am 26.10.2026."
PLANTED_LATE = "Die Widerspruchsfrist endet am 30.11.2026."


def letter(marker: str, *lines: str, date_line: str = "Datum: 15.09.2026", notice: bool = True) -> Letter:
    body = (
        HEAD,
        "SPECIMEN",
        date_line,
        f"Bescheid über eine Verwaltungsgebühr {marker}",
        "Sehr geehrte Frau Probe,",
    )
    tail = NOTICE_LINES if notice else ()
    return Letter(marker=marker, pages=((*body, *lines, *tail),), payload={})


#: A dated decision with a payment line and a site-plan line.
PAY = letter(
    "Prüfweg",
    "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
    PAYLINE,
    PLANLINE,
)
#: The same, dated only by a bare date on its header line (no "Datum" label).
BARE = letter(
    "Barweg",
    "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
    date_line="15.09.2026",
)
#: A planted end date a week after the real deadline.
PLANT = letter(
    "Pappelweg", "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.", PLANTED
)
#: Another date of the letter's: an application's.
APPLIED = letter(
    "Antragsweg", "Ihr Antrag vom 01.08.2026 wurde geprüft.", "Wir setzen eine Gebühr von 85,00 EUR fest."
)
#: A utility that shows its decision only through "Gegen diese Festsetzung".
FEST = Letter(
    marker="Festsetzung Anschluss",
    pages=(
        (
            "Stadtwerke Musterhausen · Marktplatz 3 · 54321 Musterhausen",
            "SPECIMEN",
            "Datum: 15.09.2026",
            "Festsetzung Anschluss",
            "Sehr geehrte Frau Probe,",
            "für den Anschluss setzen wir eine Gebühr von 85,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            "Gegen diese Festsetzung können Sie innerhalb eines Monats",
            "schriftlich Widerspruch erheben.",
        ),
    ),
    payload={},
)
#: A decision whose notice speaks of a "decision" and "receipt" only.
STUDY = Letter(
    marker="Förderung Ringstraße",
    pages=(
        (
            "Studierendenwerk Musterstadt · Amt für Ausbildungsförderung",
            "Ringstraße 4 · 54321 Musterstadt",
            "SPECIMEN",
            "Datum: 15.09.2026",
            "Ihr Antrag auf Förderung Ringstraße",
            "Sehr geehrte Frau Probe,",
            "Ihrem Antrag können wir leider nicht entsprechen.",
            "Rechtsbehelfsbelehrung",
            "Gegen diese Entscheidung können Sie innerhalb eines Monats",
            "nach Zugang schriftlich Widerspruch einlegen.",
        ),
    ),
    payload={},
)
#: A letter without instructions on how to object: the check asks the person to read it.
PLAIN = letter("Rückmeldung Lindenweg", "Bitte melden Sie sich binnen zwei Wochen bei uns.", notice=False)
#: A cover page, then the decision on page 2 with a planted end date (no own date on page 1).
COVER = Letter(
    marker="Ahornweg Anlage",
    pages=(
        (
            HEAD,
            "SPECIMEN",
            "Frau Sam Probe",
            "Ahornweg 4",
            "54321 Musterhausen",
            "Anlage: Gebührenbescheid Ahornweg",
        ),
        (
            HEAD,
            "Datum: 15.09.2026",
            "Bescheid über eine Gebühr Ahornweg",
            "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
            *NOTICE_LINES,
            PLANTED_LATE,
        ),
    ),
    payload={},
)

BLANK: dict[str, Any] = {
    "kind": "other",
    "title": "Fee decision",
    "summary": "A fee.",
    "explanation": "Read it.",
}
SENDER = {"name": "Stadt Musterhausen", "kind": "authority"}
OBJ_DATE = {
    "type": "relative",
    "amount": 1,
    "unit": "months",
    "anchor": "deemed_delivery",
    "delivery_rule": "de_admin_post",
    "nature": "objection",
    "text": "innerhalb eines Monats nach seiner Bekanntgabe",
}
OBJECTION = {"kind": "deadline", "title": "Objection (Widerspruch)", "date": OBJ_DATE, "quote": NOTICE}
PAYMENT = {
    "kind": "payment",
    "title": "Pay the fee",
    "amount": 85.0,
    "currency": "EUR",
    "direction": "out",
    "date": {"type": "fixed", "date": "2026-10-05", "nature": "payment", "text": "bis zum 05.10.2026"},
    "quote": PAYLINE,
}
PLAN = {
    "kind": "task",
    "title": "Send the site plan",
    "date": {"type": "fixed", "date": "2026-10-01", "nature": "other", "text": "bis zum 01.10.2026"},
    "quote": PLANLINE,
}
HALF: dict[str, Any] = {
    **BLANK,
    "kind": "authority_letter",
    "sender": SENDER,
    "document_date": "2026-09-15",
    "remedy": {"type": "widerspruch", "quote": NOTICE},
}
COMPLETE: dict[str, Any] = {**HALF, "items": [OBJECTION]}


def objection(date: dict[str, Any], quote: str = NOTICE) -> dict[str, Any]:
    return {**OBJECTION, "date": {**OBJ_DATE, **date}, "quote": quote}


def fixed(day: str, quote: str = NOTICE) -> dict[str, Any]:
    return {
        **OBJECTION,
        "date": {"type": "fixed", "date": day, "nature": "objection", "text": "bis"},
        "quote": quote,
    }


# --------------------------------------------------------------------------------------------------
# Running a letter: the re-ask's answer, and the baseline
# --------------------------------------------------------------------------------------------------


async def outcome(
    data_dir: Path, case: Letter, first: dict[str, Any], again: Any, *, received: str | None = None
) -> dict[str, Any]:
    """What the letter ends with when the re-ask answers ``again`` (an exception: raised by the re-ask)."""

    def respond(request: LLMRequest) -> Any:
        if request.prompt_name == "reading_gaps":
            if isinstance(again, Exception):
                raise again
            return copy.deepcopy(again)
        return copy.deepcopy(first)

    ctx = build_context(data_dir, backend_obj=FakeBackend(respond))
    try:
        document = await add_file(ctx, case.pdf(), "bescheid.pdf", received_date=received)
        await ctx.worker.run_until_idle()
        stored = ctx.store.get_document(document.id)
        items = ctx.store.list_items(doc_id=document.id)
        trace = document_trace(ctx.store, document.id)
    finally:
        ctx.close()
    assert stored is not None
    step = {span.key: span for span in trace.spans}.get("run/model:extract_complete")
    return {
        "status": stored.status,
        "items": sorted(
            (
                item.slot_key == CHECK_SLOT,
                item.kind,
                item.due_date or "",
                needs_check(item),
                item.computation.confidence if item.computation else "",
            )
            for item in items
        ),
        "warnings": sorted(stored.warnings),
        "accepted": step.attributes.get("accepted") if step is not None else None,
        "kept_because": step.attributes.get("kept_because") if step is not None else None,
    }


#: Each baseline already run, by letter, first answer and received date: the same baseline is the comparison
#: standard of many rows and only ever read, so it runs once per module (each caller gets its own copy).
_BASELINES: dict[tuple[Any, ...], dict[str, Any]] = {}


async def baseline(
    data_dir: Path, case: Letter, first: dict[str, Any], *, received: str | None = None
) -> dict[str, Any]:
    """The first reading with the check behind it: the re-ask's answer unusable."""
    key = (case.marker, case.pages, json.dumps(first, sort_keys=True), received)
    if key not in _BASELINES:
        unusable = ClaudeBadOutput("no structured output")
        _BASELINES[key] = await outcome(data_dir, case, first, unusable, received=received)
    return copy.deepcopy(_BASELINES[key])


def same(result: dict[str, Any], base: dict[str, Any]) -> bool:
    return all(result[key] == base[key] for key in ("status", "items", "warnings"))


async def assert_baseline(
    tmp_path: Path,
    case: Letter,
    first: dict[str, Any],
    again: Any,
    reason: str,
    *,
    received: str | None = None,
) -> None:
    base = await baseline(tmp_path / "base", case, first, received=received)
    result = await outcome(tmp_path / "again", case, first, again, received=received)
    assert (result["accepted"], result["kept_because"]) == (False, reason)
    assert same(result, base), (result, base)


# --------------------------------------------------------------------------------------------------
# A dated to-do of the first answer left out or moved later
# --------------------------------------------------------------------------------------------------


DROPPED_OR_LATER_ANSWERS = [
    pytest.param({**HALF, "items": [OBJECTION]}, id="dropped"),  # the payment left out
    # later
    pytest.param(
        {
            **HALF,
            "items": [OBJECTION, {**PAYMENT, "date": {**PAYMENT["date"], "date": "2026-11-15"}}],
        },
        id="later",
    ),
    # unreadable
    pytest.param(
        {
            **HALF,
            "items": [OBJECTION, {**PAYMENT, "date": {**PAYMENT["date"], "date": "15.11.2026"}}],
        },
        id="unreadable",
    ),
    pytest.param(
        {**HALF, "items": [OBJECTION, PAYMENT, {**PLAN, "date": {**PLAN["date"], "date": "2026-10-08"}}]},
        id="plan-later",
    ),
]


async def test_a_dated_to_do_of_the_first_answer_is_never_lost_or_moved_later(tmp_path: Path) -> None:
    async def check(where: Path, again: dict[str, Any]) -> None:
        first = {**HALF, "items": [PAYMENT, PLAN]}
        await assert_baseline(where, PAY, first, again, "dropped")

    folders = (tmp_path / str(number) for number in itertools.count())
    await check_rows_async(DROPPED_OR_LATER_ANSWERS, lambda *row: check(next(folders), *row))


# --------------------------------------------------------------------------------------------------
# An objection date later than the check's
# --------------------------------------------------------------------------------------------------


LATER_OBJECTION_LETTERS = [pytest.param(PAY, id="dated"), pytest.param(BARE, id="bare")]
LATER_OBJECTIONS = [
    pytest.param(fixed("2026-10-25"), id="fixed+6"),
    pytest.param(fixed("2026-10-26"), id="fixed+7"),
    pytest.param(fixed("2026-11-18"), id="fixed+30"),
    pytest.param(objection({"anchor": "receipt", "delivery_rule": "none"}), id="receipt"),
    pytest.param(objection({"anchor": "today", "delivery_rule": "none"}), id="today"),
    pytest.param(objection({"anchor": "explicit_date", "anchor_date": "2026-09-21"}), id="explicit"),
    pytest.param(
        objection({"anchor": "explicit_date", "anchor_date": "2026-09-21", "delivery_rule": "none"}),
        id="explicit-nodelivery",
    ),
    pytest.param(objection({"amount": 5, "unit": "weeks"}), id="5weeks"),
    pytest.param(objection({"amount": 2}), id="2months"),
]


async def test_an_objection_date_later_than_the_check_s_is_never_used(tmp_path: Path) -> None:
    async def check(where: Path, case: Letter, item: dict[str, Any]) -> None:
        await assert_baseline(where, case, HALF, {**HALF, "items": [item]}, "later", received="2026-09-25")

    rows = [
        pytest.param(*case.values, *item.values, id=f"{item.id}-{case.id}")
        for case, item in itertools.product(LATER_OBJECTION_LETTERS, LATER_OBJECTIONS)
    ]
    folders = (tmp_path / str(number) for number in itertools.count())
    await check_rows_async(rows, lambda *row: check(next(folders), *row))


async def test_a_planted_end_date_a_week_late_is_never_used(tmp_path: Path) -> None:
    await assert_baseline(tmp_path, PLANT, BLANK, {**HALF, "items": [fixed("2026-10-26", PLANTED)]}, "later")


async def test_an_objection_quote_not_on_the_letter_with_a_longer_period_is_never_used(
    tmp_path: Path,
) -> None:
    off = "Ein Widerspruch ist binnen sechs Wochen möglich."
    first = {
        **HALF,
        "remedy": {"type": "widerspruch", "quote": "Ein Widerspruch ist binnen zwei Monaten möglich."},
    }
    again = {**first, "items": [objection({"amount": 6, "unit": "weeks"}, quote=off)]}
    await assert_baseline(tmp_path, PAY, first, again, "later", received="2026-09-25")


# --------------------------------------------------------------------------------------------------
# The letter's date read later or from another date
# --------------------------------------------------------------------------------------------------


LETTER_DATES_NOT_GIVEN = [
    # later than the first answer's
    pytest.param(PAY, HALF, {**COMPLETE, "document_date": "2026-09-20"}, id="later-5"),
    pytest.param(PAY, HALF, {**COMPLETE, "document_date": "2026-09-21"}, id="later-6"),
    # 20 days late
    pytest.param(
        PAY, BLANK, {**HALF, "document_date": "2026-10-05", "items": [PAYMENT, PLAN]}, id="voids-start"
    ),
    # not the letter's own date
    pytest.param(PAY, BLANK, {**COMPLETE, "document_date": "2026-09-21"}, id="not-own"),
    # the application's date
    pytest.param(APPLIED, BLANK, {**COMPLETE, "document_date": "2026-08-01"}, id="application"),
    pytest.param(
        APPLIED, BLANK, {**BLANK, "sender": SENDER, "document_date": "2026-08-01"}, id="application-only"
    ),
    pytest.param(
        BARE,
        BLANK,
        {
            **BLANK,
            "sender": {"name": "Landesamt Irgendwo", "kind": "authority"},
            "document_date": "2026-09-22",
        },
        id="made-up",
    ),
    pytest.param(PAY, BLANK, {**BLANK, "document_date": "2026-09-24"}, id="date-only"),
]


async def test_a_letter_date_the_letter_doesn_t_give_is_never_used(tmp_path: Path) -> None:
    async def check(where: Path, case: Letter, first: dict[str, Any], again: dict[str, Any]) -> None:
        await assert_baseline(where, case, first, again, "date", received="2026-09-25")

    folders = (tmp_path / str(number) for number in itertools.count())
    await check_rows_async(LETTER_DATES_NOT_GIVEN, lambda *row: check(next(folders), *row))


# --------------------------------------------------------------------------------------------------
# The gap closed by reading the letter differently
# --------------------------------------------------------------------------------------------------

FEST_NOTICE = "Gegen diese Festsetzung können Sie innerhalb eines Monats schriftlich Widerspruch erheben."
FEST_FIRST = {**HALF, "remedy": {"type": "widerspruch", "quote": FEST_NOTICE}}


OTHER_READINGS_OF_THE_LETTER = [
    pytest.param(
        FEST,
        FEST_FIRST,
        {**FEST_FIRST, "sender": {"name": "Stadtwerke Musterhausen", "kind": "company"}},
        id="company",
    ),
    pytest.param(
        FEST,
        FEST_FIRST,
        {**FEST_FIRST, "sender": {"name": "Stadtwerke Musterhausen", "kind": "other"}},
        id="other",
    ),
    pytest.param(
        FEST,
        FEST_FIRST,
        {**FEST_FIRST, "sender": {"name": "Stadtwerke Musterhausen", "kind": "utility"}},
        id="utility",
    ),
    pytest.param(FEST, FEST_FIRST, {**FEST_FIRST, "sender": None}, id="no-sender"),
    pytest.param(PAY, HALF, {**HALF, "high_stakes_kind": "dismissal"}, id="dismissal"),
    pytest.param(PAY, HALF, {**HALF, "high_stakes_kind": "court_payment_order"}, id="court-order"),
    pytest.param(PAY, HALF, {**HALF, "high_stakes_kind": "enforcement_order"}, id="enforcement"),
    pytest.param(FEST, FEST_FIRST, {**FEST_FIRST, "high_stakes_kind": "dismissal"}, id="fest-dismissal"),
    pytest.param(PAY, HALF, {**HALF, "remedy": {"type": "none"}}, id="remedy-none"),
    pytest.param(PAY, HALF, {**HALF, "kind": "invoice"}, id="invoice"),
]


async def test_a_gap_closed_by_reading_the_letter_differently_is_no_gap_closed(tmp_path: Path) -> None:
    async def check(where: Path, case: Letter, first: dict[str, Any], again: dict[str, Any]) -> None:
        await assert_baseline(where, case, first, again, "not_better", received="2026-09-25")

    folders = (tmp_path / str(number) for number in itertools.count())
    await check_rows_async(OTHER_READINGS_OF_THE_LETTER, lambda *row: check(next(folders), *row))


STUDY_SENDER = {"name": "Studierendenwerk Musterstadt", "kind": "authority"}


ANSWERS_WITHOUT_A_COUNTERPART = [
    # blank, then the sender read as a firm, a date, no to-do: the check's deadline would vanish
    pytest.param(
        STUDY,
        BLANK,
        {**BLANK, "sender": {**STUDY_SENDER, "kind": "company"}, "document_date": "2026-09-15"},
        "uncovered",
        id="firm",
    ),
    # the first reads an authority, the second a firm
    pytest.param(
        STUDY,
        {**BLANK, "sender": STUDY_SENDER, "document_date": "2026-09-15"},
        {**BLANK, "sender": {**STUDY_SENDER, "kind": "company"}, "document_date": "2026-09-15"},
        "not_better",
        id="authority-to-firm",
    ),
    # no notice: "read this letter yourself" is not lifted by a sender and a date
    pytest.param(
        PLAIN,
        BLANK,
        {**BLANK, "sender": SENDER, "document_date": "2026-09-15"},
        "uncovered",
        id="read-yourself",
    ),
    # an undated to-do is no dated one found on the letter
    pytest.param(
        PLAIN,
        BLANK,
        {
            **BLANK,
            "sender": SENDER,
            "document_date": "2026-09-15",
            "items": [{**PLAN, "date": {"type": "none"}}],
        },
        "uncovered",
        id="read-yourself-undated",
    ),
]


async def test_the_check_s_to_do_is_never_lifted_without_a_counterpart(tmp_path: Path) -> None:
    async def check(
        where: Path, case: Letter, first: dict[str, Any], again: dict[str, Any], reason: str
    ) -> None:
        await assert_baseline(where, case, first, again, reason)

    folders = (tmp_path / str(number) for number in itertools.count())
    await check_rows_async(ANSWERS_WITHOUT_A_COUNTERPART, lambda *row: check(next(folders), *row))


async def test_a_sender_the_letter_doesn_t_name_is_never_used(tmp_path: Path) -> None:
    """Correctness R4: a made-up sender (a private firm, which drops the delivery days) where the first answer
    named none — the check's date would move with an invented sender."""
    again = {**BLANK, "sender": {"name": "Max Muster GmbH", "kind": "company"}}
    await assert_baseline(tmp_path, PAY, BLANK, again, "ungrounded")


async def test_an_objection_date_where_the_check_can_t_date_it_is_never_used(tmp_path: Path) -> None:
    """The letter's own date only on page 2 — the check files no date; a planted end date taken
    as the objection's would stand unchecked (the answer gives no letter date, so only the objection decides)."""
    again = {**HALF, "document_date": None, "items": [fixed("2026-11-30", PLANTED_LATE)]}
    await assert_baseline(tmp_path, COVER, BLANK, again, "unchecked")


# --------------------------------------------------------------------------------------------------
# No answer at all: the first reading and the check's to-do, never a failed letter
# --------------------------------------------------------------------------------------------------


UNANSWERED_ERRORS = [
    pytest.param(ClaudeTimeout("no answer"), id="timeout"),
    pytest.param(ClaudeRateLimited("Usage limit reached", reset_at=None), id="rate-limit"),
    pytest.param(ClaudeAuthError("not signed in"), id="auth"),
    pytest.param(ClaudeNotInstalled("not installed"), id="not-installed"),
    pytest.param(LLMError("the CLI broke"), id="generic"),
]


async def test_a_re_ask_without_an_answer_leaves_the_baseline(tmp_path: Path) -> None:
    async def check(where: Path, error: LLMError) -> None:
        base = await baseline(where / "base", PAY, BLANK)
        result = await outcome(where / "again", PAY, BLANK, error)
        assert (result["accepted"], result["kept_because"]) == (False, "unanswered")
        assert same(result, base) and result["status"] == "needs_review"

    folders = (tmp_path / str(number) for number in itertools.count())
    await check_rows_async(UNANSWERED_ERRORS, lambda *row: check(next(folders), *row))


# --------------------------------------------------------------------------------------------------
# The good answers are still used
# --------------------------------------------------------------------------------------------------


BETTER_ANSWERS = [
    pytest.param(BLANK, COMPLETE, id="blank-complete"),
    pytest.param(HALF, COMPLETE, id="half-complete"),
    pytest.param(
        {**HALF, "items": [PAYMENT, PLAN]}, {**HALF, "items": [PAYMENT, PLAN, OBJECTION]}, id="keeps-dated"
    ),
    pytest.param(BLANK, {**HALF, "items": [objection({"anchor": "document_date"})]}, id="from-letter-date"),
    # the objection still left out: the check files its to-do for the second reading
    pytest.param(BLANK, HALF, id="blank-half"),
    # a fixed date no later than the check's
    pytest.param(BLANK, {**HALF, "items": [fixed("2026-10-15")]}, id="fixed-earlier"),
]


async def test_a_better_answer_is_used(tmp_path: Path) -> None:
    async def check(where: Path, first: dict[str, Any], again: dict[str, Any]) -> None:
        base = await baseline(where / "base", PAY, first)
        result = await outcome(where / "again", PAY, first, again)
        assert (result["accepted"], result["kept_because"]) == (True, None)
        assert reask_warning("empty" if first is BLANK else "remedy_left_out") in result["warnings"]
        # never a later date than the baseline's on any to-do both have
        dates = {kind: due for _, kind, due, _, _ in base["items"] if due}
        assert all(not dates.get(kind) or due <= dates[kind] for _, kind, due, _, _ in result["items"] if due)

    folders = (tmp_path / str(number) for number in itertools.count())
    await check_rows_async(BETTER_ANSWERS, lambda *row: check(next(folders), *row))
