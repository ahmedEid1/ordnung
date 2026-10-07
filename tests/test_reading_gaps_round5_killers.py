"""Mutation killers of the round-5 limits review (tests and docs lens, RL-T6): each test fails on a mutant of the
check for incomplete readings that the earlier tests let survive. Invented letters only; one benchmark id, none of its
text."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from fixtures_llm import Letter, Router
from ordnung import clock
from ordnung.ingest.gaps import envelope_start, formally_served, is_check_slot
from ordnung.models import DateSpec
from ordnung.rules import RuleContext
from test_api_support import api_for
from test_reading_gaps import blank, page
from test_reading_gaps_round5 import (
    ADDRESS,
    BEKANNTGABE,
    DECISION,
    DROPPED_LETTER,
    DROPPED_LINE,
    DROPPED_MARKER,
    INVOICE_HEAD,
    LETTERHEAD,
    NO_START,
    WITH_SENDER,
    computed,
    plain,
    served,
)


def header(line: str, *notices: str):
    return [page(LETTERHEAD, line, *ADDRESS, *DECISION, *(notices or (BEKANNTGABE,)))]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Zustellung mit Postzustellungsurkunde gemäß § 3 VwZG", True),  # 7 words: still a service line
        ("Hinweis bitte senden Sie Widersprüche nicht mit Postzustellungsurkunde an uns", False),  # > 8 words
        ("Widersprüche bitte nicht per PZU.", False),  # a sentence
        ("Bezug: Bescheid vom 03.09.2026 mit PZU", False),  # another decision's service
        ("Zustellung gegen Empfangsbekenntnis", False),  # formal service, but no yellow envelope
        ("Zustellung mit ZU", True),  # the abbreviation
    ],
)
def test_header_service_lines(line: str, expected: bool) -> None:
    assert formally_served(header(line)) is expected


def test_one_notice_without_a_start_keeps_the_letter_unmarked() -> None:
    assert formally_served([served(BEKANNTGABE, NO_START)]) is False


def test_another_decision_served_undated_is_not_this_letter() -> None:
    assert (
        formally_served(
            [plain("Der Bußgeldbescheid wurde Ihnen mit Postzustellungsurkunde zugestellt.", BEKANNTGABE)]
        )
        is False
    )


def test_a_short_body_line_naming_pzu_is_no_service_of_this_letter() -> None:
    assert formally_served([plain(BEKANNTGABE, "Rücksendung bitte nicht per PZU")]) is False


def test_a_self_naming_sentence_ends_at_its_period() -> None:
    pages = [
        plain(
            "Dieser Bescheid ergeht unter Vorbehalt.",
            "Ein späterer Bescheid wird Ihnen mit Postzustellungsurkunde zugestellt.",
            BEKANNTGABE,
        )
    ]
    assert formally_served(pages) is False


SPEC = DateSpec(
    type="relative",
    anchor="explicit_date",
    anchor_date="2026-11-06",
    amount=1,
    unit="months",
    delivery_rule="none",
    nature="objection",
)


@pytest.mark.parametrize(
    ("stored", "arrived"), [(date(2026, 11, 1), date(2026, 11, 18)), (date(2026, 11, 9), date(2026, 11, 22))]
)
def test_the_cap_counts_from_the_earliest_own_date(stored: date, arrived: date) -> None:
    ctx = RuleContext(
        today=date(2026, 11, 25),
        document_date=stored,
        formal_service=True,
        received_date=arrived,
        received_confirmed=True,
    )
    assert envelope_start(SPEC, ctx) is None


def test_no_earlier_letter_date_note_once_the_envelope_starts_it() -> None:
    reading = blank(
        sender={"name": "Landratsamt Beispielkreis", "kind": "immigration_office"}, document_date="2026-11-09"
    )
    pages = [
        page(
            LETTERHEAD,
            "Mit Postzustellungsurkunde",
            *ADDRESS,
            "Beispielhausen, 06.11.2026",
            *DECISION[1:],
            BEKANNTGABE,
        )
    ]
    [(_verified, result)] = computed(reading, pages, "2026-11-10")
    assert result.due_date == "2026-12-10"
    assert not any("to be safe" in warning for warning in result.receipt.warnings)


def test_a_period_counted_from_the_letter_s_date_never_cites_the_envelope() -> None:
    from ordnung.rules import compute_due

    spec = DateSpec(type="relative", amount=1, unit="months", anchor="document_date", nature="objection")
    receipt = compute_due(
        spec, RuleContext(today=date(2026, 11, 25), document_date=date(2026, 11, 6), formal_service=True)
    )
    assert "pzu" not in receipt.rule_ids


def test_the_pipeline_never_files_a_dropped_date_already_past() -> None:
    from ordnung.ingest.plan import verify_extraction

    pages = [
        page(
            *INVOICE_HEAD,
            "Rechnung",
            "Sehr geehrte Frau Probe,",
            "Bitte überweisen Sie den Betrag bis zum 15.10.2026.",
        )
    ]
    verification = verify_extraction(
        "doc_x", blank(**WITH_SENDER), pages, check_reading=True, today=date(2026, 10, 16)
    )
    assert not any(is_check_slot(verified.slot_key) for verified in verification.items)


async def test_the_benchmark_marks_a_dropped_date_as_code_s(tmp_path: Path) -> None:
    """Positive control for the census's `dropped == set()`: the signal and origin are emitted at all."""
    from ordnung.llm.fake import FakeBackend
    from test_evals_run import _ordnung_on

    reading = {
        "kind": "invoice",
        "title": "Letter",
        "summary": "s",
        "explanation": "e",
        "sender": {"name": "Sender", "kind": "company"},
    }
    _, prediction = await _ordnung_on("dev-dunning_fixed-A1", FakeBackend(lambda req: reading), tmp_path)
    assert "deadline_left_out" in prediction.signals
    assert [item.origin for item in prediction.items] == ["code"]


@pytest.fixture
def pinned() -> Iterator[None]:
    clock.set_today("2026-09-25")
    yield
    clock.set_today(None)


async def _read_pay_reread(data_dir: Path, items: list, letter: Letter = DROPPED_LETTER, extra=None):
    router = Router(letters=(letter,))
    payload = router.payloads[DROPPED_MARKER]
    payload["items"] = items
    api_cm = api_for(data_dir, router=router)
    api = await api_cm.__aenter__()
    body = await api.upload((f"{DROPPED_MARKER}.pdf", letter.pdf()))
    await api.read_all()
    doc_id = str(body["documents"][0]["id"])
    first = api.ctx.store.list_items(doc_id=doc_id)
    for item in first:
        assert (await api.client.patch(f"/api/items/{item.id}", json={"status": "done"})).status_code == 200
    if extra:
        extra(api, doc_id)
    payload["items"] = []
    assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
    await api.read_all()
    after = api.ctx.store.list_items(doc_id=doc_id)
    await api_cm.__aexit__(None, None, None)
    return first, after


async def test_a_paid_to_do_two_days_off_still_covers_the_dropped_date(data_dir: Path, pinned: None) -> None:
    _, after = await _read_pay_reread(
        data_dir,
        [
            {
                "kind": "payment",
                "title": "Pay",
                "quote": DROPPED_LINE,
                "amount": 85.0,
                "date": {"type": "fixed", "date": "2026-10-11", "nature": "payment"},
            }
        ],
    )
    assert not any(is_check_slot(item.slot_key) for item in after)


async def test_a_paid_to_do_is_never_carried_into_code_s_slot(data_dir: Path, pinned: None) -> None:
    first, after = await _read_pay_reread(
        data_dir,
        [
            {
                "kind": "payment",
                "title": "Pay the water bill",
                "quote": DROPPED_LINE,
                "date": {"type": "fixed", "date": "2026-10-09", "nature": "payment", "shift_rule": "none"},
            }
        ],
    )
    [paid], [kept] = first, after
    assert kept.id == paid.id and kept.slot_key == paid.slot_key and kept.title == "Pay the water bill"


SECOND = "Bitte reichen Sie den Zählerstand bis zum 23.10.2026 ein."


async def test_a_second_dropped_date_the_person_dealt_with_is_never_filed_again(
    data_dir: Path, pinned: None
) -> None:
    letter = Letter(
        marker=DROPPED_MARKER,
        pages=((*DROPPED_LETTER.pages[0], SECOND),),
        payload=dict(DROPPED_LETTER.payload),
    )
    items = [
        {
            "kind": "payment",
            "title": "Pay",
            "quote": DROPPED_LINE,
            "amount": 85.0,
            "date": {"type": "fixed", "date": "2026-10-09", "nature": "payment"},
        },
        {
            "kind": "deadline",
            "title": "Send the meter reading",
            "quote": SECOND,
            "date": {"type": "fixed", "date": "2026-10-23", "nature": "declaration"},
        },
    ]
    _, after = await _read_pay_reread(data_dir, items, letter)
    assert not any(is_check_slot(item.slot_key) for item in after)


async def test_a_manual_to_do_never_covers_a_dropped_date(data_dir: Path, pinned: None) -> None:
    """Only a to-do of an earlier reading the person acted on covers it (plan._covered_deadlines)."""
    async with api_for(data_dir, router=Router(letters=(DROPPED_LETTER,))) as api:
        body = await api.upload((f"{DROPPED_MARKER}.pdf", DROPPED_LETTER.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        api.ctx.store.add_item(
            doc_id=doc_id,
            kind="payment",
            title="My own reminder",
            due_date="2026-10-09",
            origin="manual",
            status="done",
        )
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        assert any(is_check_slot(item.slot_key) for item in api.ctx.store.list_items(doc_id=doc_id))


async def test_a_dropped_date_stays_code_s_low_check_when_recomputed(data_dir: Path, pinned: None) -> None:
    from ordnung.ingest.verify import DEADLINE_LEFT_OUT, READING_INCOMPLETE, REASON_TEXT

    async with api_for(data_dir, router=Router(letters=(DROPPED_LETTER,))) as api:
        body = await api.upload((f"{DROPPED_MARKER}.pdf", DROPPED_LETTER.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        assert (
            await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-23"})
        ).status_code == 200
        [item] = api.ctx.store.list_items(doc_id=doc_id)
        assert item.computation is not None and item.computation.confidence == "low"
        assert REASON_TEXT[DEADLINE_LEFT_OUT] in item.computation.warnings
        assert REASON_TEXT[READING_INCOMPLETE] not in item.computation.warnings


TOWN_HEAD = ("Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen", *ADDRESS, "")
FEE = (
    "",
    "Gebührenbescheid",
    "Sehr geehrte Frau Probe,",
    "wir setzen die Gebühr auf 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
    "Gegen diesen Bescheid können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
)


@pytest.mark.parametrize(
    "planted",
    [
        (
            "Ihre Nachricht vom:   Beispielhausen, 20.11.2026",
        ),  # another date's empty label beside a place-date
        (
            "Datum   Kassenzeichen   Forderung",
            "20.11.2026   1234-5678   85,00 EUR",
        ),  # a payments row, no money label
        ("Rathaus, 20.11.2026",),  # a place only part of a word above ("Rathausplatz")
    ],
)
def test_a_line_of_no_own_kind_starts_nothing(planted: tuple[str, ...]) -> None:
    from ordnung.ingest.gaps import letter_date

    assert letter_date(blank(), [page(*TOWN_HEAD, *planted, *FEE)], today=date(2026, 12, 20)) is None


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        # "Frankfurt" for the footer's "Frankfurt am Main"
        (
            (
                "Ordnungsamt",
                *ADDRESS,
                "",
                "Frankfurt, 06.11.2026",
                *FEE,
                "Kleyerstraße 86 · 60326 Frankfurt am Main",
            ),
            date(2026, 11, 6),
        ),
        # "Berlin-Mitte" for the footer's "Berlin"
        (
            (
                "Bezirksamt",
                *ADDRESS,
                "",
                "Berlin-Mitte, 06.11.2026",
                *FEE,
                "Karl-Marx-Allee 31 · 10178 Berlin",
            ),
            date(2026, 11, 6),
        ),
        # the date's own column on an address line the text layer ran it into
        (
            (
                "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen",
                "Frau Mara Probe",
                "Probeweg 2   Beispielhausen, 06.11.2026",
                "12345 Beispielhausen",
                *FEE,
            ),
            date(2026, 11, 6),
        ),
        # only a prefix of the page's town: no own date
        ((*TOWN_HEAD, "Beispiel, 20.11.2026", *FEE), None),
    ],
    ids=["frankfurt-for-frankfurt-am-main", "berlin-mitte", "beside-address", "prefix-only"],
)
def test_the_forms_names_town_promises(lines: tuple[str, ...], expected: date | None) -> None:
    from ordnung.ingest.gaps import letter_date

    assert letter_date(blank(), [page(*lines)], today=date(2026, 12, 20)) == expected


@pytest.mark.parametrize(
    "lines",
    [
        (
            *TOWN_HEAD,
            "20.11.2026",
            "ab 9 Uhr im Rathaus",
            *FEE,
        ),  # an appointment's time in words under the date line
        ("20.11.2026", "Druckdatum 25.11.2026", *TOWN_HEAD, *FEE),  # first line beside another header date
        ("20.11.2026", "09:00 Uhr, Raum 2.14", *TOWN_HEAD, *FEE),  # first line with an appointment's time
    ],
    ids=["dateline-time-in-words", "first-line-beside-another", "first-line-appointment"],
)
def test_more_lines_of_no_own_kind_start_nothing(lines: tuple[str, ...]) -> None:
    from ordnung.ingest.gaps import letter_date

    assert letter_date(blank(), [page(*lines)], today=date(2026, 12, 20)) is None


def test_the_rival_never_takes_a_first_line_date_beside_the_letter_s_own() -> None:
    from ordnung.ingest.gaps import _own_start

    assert _own_start([page("01.12.2026", *TOWN_HEAD[:-1], "Datum: 06.11.2026", *FEE)]) == date(2026, 11, 6)


@pytest.mark.parametrize(
    "sentence",
    [
        "Der Widerspruch ist zulässig, wenn er innerhalb eines Monats nach Bekanntgabe eingelegt worden sein sollte.",
        "Da der Widerspruch verspätet erhoben wurde, ist innerhalb eines Monats Klage beim Verwaltungsgericht zu erheben.",
    ],
    ids=["perfect-requirement", "reported-but-offered"],
)
def test_a_notice_beside_a_report_of_a_lodged_remedy_stays(sentence: str) -> None:
    from ordnung.ingest.gaps import remedy_notices

    pages = [
        page(
            *TOWN_HEAD,
            "Datum: 06.11.2026",
            "Bescheid",
            "Sehr geehrte Frau Probe,",
            "Die Gebühr beträgt 20 EUR.",
            sentence,
        )
    ]
    assert len(remedy_notices(pages)) == 1


from ordnung.ingest.gaps import deadline_items  # noqa: E402
from test_reading_gaps import payment  # noqa: E402


def _dropped(*lines: str, today: date = date(2026, 10, 3), **fields):
    pages = [page(*INVOICE_HEAD, "Rechnung", "Sehr geehrte Frau Probe,", *lines)]
    return [
        (i.date.date, i.date.nature)
        for i in deadline_items(blank(**{**WITH_SENDER, **fields}), pages, today=today)
    ]


@pytest.mark.parametrize(
    "line",
    [
        "Der Betrag ist bis zum 15.10.2026 zu zahlen; ein Widerspruch hat keine aufschiebende Wirkung.",
        "Please pay by 04/05/2026.",
        "Wenn Sie die Ratenzahlung wünschen, überweisen Sie die erste Rate bis zum 15.10.2026.",
        "Fällig am 15.10.2026, Einzug per SEPA-Lastschrift.",
    ],
    ids=["remedy-in-clause", "ambiguous", "condition", "debit"],
)
def test_more_dates_that_are_no_deadline_of_the_person_s(line: str) -> None:
    assert _dropped(line) == []


def test_a_weekday_before_the_date_still_counts() -> None:
    assert _dropped("Bitte überweisen Sie den Betrag bis Freitag, 16.10.2026.") == [("2026-10-16", "payment")]


def test_the_letter_s_own_date_never_on_the_day_it_is_read() -> None:
    assert _dropped("Bitte überweisen Sie den Betrag bis zum 01.10.2026.", today=date(2026, 10, 1)) == []


def test_the_letter_s_own_date_counts_when_the_reading_has_none() -> None:
    fields = {"sender": WITH_SENDER["sender"]}  # no document_date in the reading
    assert (
        _dropped("Bitte überweisen Sie den Betrag bis zum 01.10.2026.", today=date(2026, 10, 1), **fields)
        == []
    )


@pytest.mark.parametrize("off", [3, -3])
def test_a_reading_s_to_do_three_days_off_covers_the_date(off: int) -> None:
    near = payment(
        quote="Die Gebühr beträgt 85,00 EUR.", type="fixed", date=f"2026-10-{15 + off}", nature="payment"
    )
    assert _dropped("Zahlbar bis 15.10.2026", items=[near]) == []


def test_a_relative_to_do_of_the_reading_covers_its_date() -> None:
    rel = payment(
        quote="Zahlbar innerhalb von 14 Tagen.",
        type="relative",
        amount=14,
        unit="days",
        anchor="document_date",
        nature="payment",
    )
    assert _dropped("Zahlbar innerhalb von 14 Tagen.", "Zahlbar bis 15.10.2026", items=[rel]) == []


def test_every_dropped_date_is_code_s_low_check() -> None:
    from ordnung.ingest.plan import verify_extraction

    pages = [
        page(
            *INVOICE_HEAD,
            "Rechnung",
            "Sehr geehrte Frau Probe,",
            "Bitte überweisen Sie den Betrag bis zum 15.10.2026.",
            "Bitte reichen Sie den Zählerstand bis zum 23.10.2026 ein.",
        )
    ]
    items = verify_extraction(
        "doc_x", blank(**WITH_SENDER), pages, check_reading=True, today=date(2026, 10, 3)
    ).items
    assert len(items) == 2 and all(is_check_slot(v.slot_key) and v.needs_check for v in items)


def test_a_date_without_its_year_is_the_first_such_day_after_the_letter_s_date() -> None:
    """Since 2026-10-07 (ADR 0015) a date without its year counts from the letter's date; on a letter whose date is
    read nowhere it still gets no to-do (``tests/test_reading_gaps_looser.py``)."""
    assert _dropped("Bitte überweisen Sie den Betrag bis zum 15.10.") == [("2026-10-15", "payment")]


# --------------------------------------------------------------------------------------------------
# check:deadline filters and remedy notices (reviewer's first pass)
# --------------------------------------------------------------------------------------------------

from ordnung.ingest.gaps import remedy_notices  # noqa: E402
from ordnung.models import ExtractedItem  # noqa: E402
from test_reading_gaps_round2 import check_due  # noqa: E402
from test_reading_gaps_round5 import KASSEL, dropped  # noqa: E402

LINE = "Bitte überweisen Sie den Betrag bis zum 15.10.2026."


def test_the_letter_s_own_date_is_never_a_deadline_even_without_today() -> None:
    pages = [
        page(
            *INVOICE_HEAD,
            "Rechnung",
            "Sehr geehrte Frau Probe,",
            "Bitte überweisen Sie den Betrag bis zum 01.10.2026.",
        )
    ]
    assert deadline_items(blank(**WITH_SENDER), pages) == []


def _other(day: str) -> ExtractedItem:
    return ExtractedItem.model_validate(
        {
            "kind": "deadline",
            "title": "Send the meter reading",
            "quote": "Bitte teilen Sie uns den Zählerstand mit.",
            "date": {"type": "fixed", "date": day, "nature": "declaration"},
        }
    )


def test_a_dated_to_do_three_days_off_covers_it_four_days_off_does_not() -> None:
    other = "Bitte teilen Sie uns den Zählerstand mit."
    assert dropped(LINE, other, items=[_other("2026-10-12")]) == []
    assert dropped(LINE, other, items=[_other("2026-10-11")]) == [("2026-10-15", "payment")]


def test_a_payment_sentence_that_names_a_remedy_is_left_to_the_remedy_check() -> None:
    assert dropped("Trotz eines Widerspruchs ist der Betrag bis zum 15.10.2026 zu zahlen.") == []


def test_two_dates_for_one_payment_file_the_earlier_only() -> None:
    assert dropped(LINE, "Zahlbar bis 22.10.2026") == [("2026-10-15", "payment")]


@pytest.mark.parametrize(
    "line",
    [
        "Falls Sie zustimmen, überweisen Sie den Betrag bis zum 15.10.2026.",  # a condition
        "Überweisen Sie nichts, wir zahlen Ihnen den Betrag bis zum 15.10.2026.",  # the sender's own act
        "Bitte überweisen Sie nichts bis zum 15.10.2026, der Betrag wird per Lastschrift eingezogen.",  # a debit
        "Bitte zahlen Sie die Gebühr bis zum 15.10.2026 bei Ihrem Termin um 10:00 Uhr.",  # an appointment
        "Bitte zahlen Sie bis zum 15.10.2026, dieses Angebot gilt nur bis dahin.",  # a validity
    ],
)
def test_each_exclusion_on_its_own_with_the_strict_wording_met(line: str) -> None:
    assert dropped(line) == []


def test_a_self_naming_decision_s_hiergegen_ignores_an_older_decision_s_date() -> None:  # N4
    pages = [
        page(
            *KASSEL,
            "Datum: 21.09.2026",
            "Änderungsbescheid",
            "Sehr geehrter Herr Lehmann,",
            "dieser Bescheid ersetzt den Bescheid vom 03.03.2026.",
            "Rechtsbehelfsbelehrung",
            "Hiergegen kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        )
    ]
    assert check_due(pages) == "2026-10-26"


def test_a_sentence_that_reports_and_offers_a_remedy_is_a_notice() -> None:  # N2
    line = (
        "Da der Widerspruch fristgerecht erhoben wurde, kann gegen diesen Widerspruchsbescheid innerhalb eines "
        "Monats nach Zustellung Klage erhoben werden."
    )
    pages = [page(*KASSEL, "Datum: 21.09.2026", "Widerspruchsbescheid", "Sehr geehrter Herr Lehmann,", line)]
    assert len(remedy_notices(pages)) == 1
