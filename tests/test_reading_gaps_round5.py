"""Tightening the known limits of the check for incomplete readings (``ingest/gaps.py``, ADR 0015 "Review and known
limits"): a letter served with a Postzustellungsurkunde asks for the date on the yellow envelope and counts from it
(later audit R4L-1, fix F2); a reminder's "Hiergegen …" and a notice's bare "des Bescheides" (security V4-2, false
positives R4FP-6); a Widerspruchsbescheid's reasoning (R4FP-8); own-date forms read weakly or not at all (R4D-3); a
planted line or an appointment's block while the letter's own date is unread; and a fixed date the letter sets
(pay by, send by) that the reading left out (``check:deadline``). The rule over all of them: no code path gives a
date later than the letter allows — when in doubt, no date.

All letters are invented ("Stadt Beispielhausen", dated Fri 6 Nov 2026 unless said otherwise); no benchmark or
prompt text."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter, Router
from ordnung import clock
from ordnung.ingest.gaps import (
    CHECK_SLOT,
    DEADLINE_SLOT,
    _own_start,
    deadline_items,
    deadline_warning,
    formally_served,
    is_check_slot,
    letter_date,
    remedy_notices,
    square_gap_warnings,
)
from ordnung.ingest.plan import compute_item, needs_check, rule_context, verify_extraction
from ordnung.ingest.verify import DEADLINE_LEFT_OUT, REASON_TEXT, PageInput
from ordnung.models import DateSpec, Document, DocumentExtraction, ExtractedItem
from ordnung.rules import RuleContext, compute_due
from ordnung.rules.deadlines import ASSUMED_DELIVERY_WARNING, ASSUMED_RECEIPT_WARNING
from test_api_support import api_for
from test_reading_gaps import FROM_LETTER_DUE, NOTIFIED_DUE, ROOT, SENDER, _web_regex, blank, page, payment
from test_reading_gaps_round2 import check_due

G = "   "  # the gap the text layer leaves between two columns run into one line
LETTERHEAD = "Landratsamt Beispielkreis · Ausländerbehörde · Rathausplatz 1 · 12345 Beispielhausen"
ADDRESS = ("Frau Mara Probe", "Probeweg 2", "12345 Beispielhausen")
BEKANNTGABE = "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
ZUSTELLUNG = "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung Widerspruch erhoben werden."
NO_START = "Gegen diesen Bescheid kann innerhalb eines Monats Widerspruch erhoben werden."
DECISION = (
    "Datum: 06.11.2026",
    "Ablehnung Ihres Antrags",
    "Sehr geehrte Frau Probe,",
    "Ihr Antrag vom 12.05.2026 wird abgelehnt.",
    "Rechtsbehelfsbelehrung",
)


def served(*notice: str, marker: str = "Mit Postzustellungsurkunde") -> PageInput:
    """The authority's decision of Fri 6 Nov 2026 with ``marker`` above the recipient's address."""
    return page(LETTERHEAD, marker, *ADDRESS, *DECISION, *notice)


def plain(*notice: str) -> PageInput:
    return page(LETTERHEAD, *ADDRESS, *DECISION, *notice)


def from_receipt(quote: str, amount: int = 1) -> DocumentExtraction:
    """A complete reading that counts the objection from the letter's arrival (as readings of served letters do)."""
    return blank(
        kind="residence_permit",
        sender={"name": "Landratsamt Beispielkreis Ausländerbehörde", "kind": "immigration_office"},
        document_date="2026-11-06",
        items=[
            {
                "kind": "deadline",
                "title": "Objection",
                "quote": quote,
                "date": {
                    "type": "relative",
                    "amount": amount,
                    "unit": "months",
                    "anchor": "receipt",
                    "delivery_rule": "none",
                    "nature": "objection",
                },
            }
        ],
    )


def in_app(reading: DocumentExtraction, pages: Sequence[PageInput], arrived: str | None) -> RuleContext:
    """The app's context of the letter (Land unknown), with the arrival the person entered."""
    document = Document(
        id="doc_x",
        filename="x.pdf",
        mime="application/pdf",
        sha256="0" * 64,
        received_date=arrived,
        created_at="2026-11-25T09:00:00Z",
        updated_at="2026-11-25T09:00:00Z",
    )
    return rule_context(None, document, reading, date(2026, 11, 25), pages=pages)


def computed(reading: DocumentExtraction, pages: Sequence[PageInput], arrived: str | None) -> list[Any]:
    """Each to-do of the verified reading (the check's too), computed in the app's context."""
    verification = verify_extraction("doc_x", reading, pages, check_reading=True)
    ctx = in_app(reading, pages, arrived)
    return [(verified, compute_item(verified, ctx, postal_buffer_days=3)) for verified in verification.items]


# --------------------------------------------------------------------------------------------------
# 1. A letter served with a Postzustellungsurkunde (later audit R4L-1, fix F2)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        ([served(BEKANNTGABE)], True),
        ([served(ZUSTELLUNG, marker="Zustellung gegen PZU")], True),
        ([served(BEKANNTGABE, marker=f"Mit Postzustellungsurkunde{G}Aktenzeichen: 32.1-123")], True),
        (
            [
                plain(
                    "Dieser Bescheid wird Ihnen mit Postzustellungsurkunde zugestellt.",
                    BEKANNTGABE,
                )
            ],
            True,
        ),
        # a notice that names no start keeps the letter unmarked: the envelope's date never moves that period
        ([served(NO_START)], False),
        # another decision's service, or a tip on how to send the objection, is no service of this letter
        (
            [
                plain(
                    "Der Bescheid vom 03.09.2026 wurde Ihnen mit Postzustellungsurkunde zugestellt.",
                    BEKANNTGABE,
                )
            ],
            False,
        ),
        (
            [plain(BEKANNTGABE, "Senden Sie den Widerspruch am besten per Einschreiben mit Rückschein.")],
            False,
        ),
        ([plain(BEKANNTGABE)], False),
    ],
    ids=[
        "header",
        "pzu",
        "header-column",
        "sentence",
        "no-start",
        "other-decision",
        "rueckschein-tip",
        "plain",
    ],
)
def test_a_letter_is_served_formally_only_by_its_own_words(pages: list[PageInput], expected: bool) -> None:
    assert formally_served(pages) is expected


def test_a_period_from_arrival_on_a_formally_served_letter_cites_the_envelope() -> None:
    """The engine cites ``pzu`` on a to-do counted from arrival, so the app asks "When was it delivered?" for the
    date on the yellow envelope (no Today prefilled), and its warnings name that envelope."""
    spec = DateSpec(type="relative", amount=1, unit="months", anchor="receipt", nature="objection")
    served_ctx = RuleContext(today=date(2026, 11, 25), document_date=date(2026, 11, 6), formal_service=True)
    receipt = compute_due(spec, served_ctx)
    assert "pzu" in receipt.rule_ids and ASSUMED_DELIVERY_WARNING in receipt.warnings
    assert receipt.due_date == FROM_LETTER_DUE  # from the letter's date until the envelope's is entered
    entered = compute_due(
        spec, replace(served_ctx, received_date=date(2026, 11, 10), received_confirmed=True)
    )
    assert entered.due_date == "2026-12-10" and "the day it was delivered" in entered.summary
    ordinary = compute_due(spec, replace(served_ctx, formal_service=False))
    assert "pzu" not in ordinary.rule_ids and ASSUMED_RECEIPT_WARNING in ordinary.warnings


@pytest.mark.parametrize(
    ("arrived", "due", "conflict"),
    [
        (None, FROM_LETTER_DUE, False),
        ("2026-11-10", "2026-12-10", False),
        # the envelope's date 10 days and more after the letter's: R4L-1's false early "Please check" is gone
        ("2026-11-16", "2026-12-16", False),
        ("2026-11-20", "2026-12-21", False),  # Sun 20 Dec → Mon 21 Dec
        # more than two weeks after the letter's date: no envelope of this letter's — the notice's date is kept
        ("2026-11-21", FROM_LETTER_DUE, True),
    ],
)
def test_a_formally_served_letter_counts_the_notice_from_the_envelope_s_date(
    arrived: str | None, due: str, conflict: bool
) -> None:
    pages = [served(BEKANNTGABE)]
    [(_verified, result)] = computed(from_receipt(BEKANNTGABE), pages, arrived)
    assert result.due_date == due and result.conflict is conflict
    if not conflict:
        assert result.receipt is not None and "pzu" in result.receipt.rule_ids


@pytest.mark.parametrize("pages", [[plain(BEKANNTGABE)], [served(NO_START)]], ids=["plain", "no-start"])
def test_without_the_envelope_question_a_late_arrival_still_gets_the_notice_beside_it(
    pages: list[PageInput],
) -> None:
    """R4L-1's F1 guard stays for letters not marked formally served: an arrival entered 14 days after the letter's
    date may be a pickup or a Today saved later — the notice's own date is set beside it, the earlier."""
    notice = BEKANNTGABE if formally_served(pages) or "Bekanntgabe" in pages[0][1] else NO_START
    [(_verified, result)] = computed(from_receipt(notice), pages, "2026-11-20")
    assert result.conflict and result.due_date is not None and result.due_date <= NOTIFIED_DUE


@pytest.mark.parametrize(
    ("arrived", "due"),
    [
        (None, FROM_LETTER_DUE),
        ("2026-11-10", "2026-12-10"),
        ("2026-11-16", "2026-12-16"),
        ("2026-11-21", FROM_LETTER_DUE),
    ],
)
def test_the_check_on_a_formally_served_letter_asks_for_and_counts_from_the_envelope(
    arrived: str | None, due: str
) -> None:
    """An empty reading of a served letter: the check cites ``pzu`` (the app asks for the envelope's date) and counts
    from that date once entered, within two weeks of the letter's own; never from a later one."""
    pages = [served(BEKANNTGABE)]
    [(verified, result)] = computed(blank(), pages, arrived)
    assert verified.slot_key == CHECK_SLOT
    assert result.due_date == due
    assert result.receipt is not None and "pzu" in result.receipt.rule_ids
    assert any("yellow envelope" in warning for warning in result.receipt.warnings)


@pytest.fixture
def pinned_today() -> Iterator[None]:
    clock.set_today("2026-09-25")
    yield
    clock.set_today(None)


SERVED_MARKER = "Bescheid über die Ausweisung"
SERVED_NOTICE = (
    "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
)
SERVED_LETTER = Letter(
    marker=SERVED_MARKER,
    pages=(
        (
            "Landratsamt Beispielkreis, Rathausplatz 1, 12345 Beispielhausen",
            "Mit Postzustellungsurkunde",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "Datum: 15.09.2026",
            SERVED_MARKER,
            "Sehr geehrte Frau Probe,",
            "Ihr Antrag vom 12.05.2026 wird abgelehnt.",
            "Rechtsbehelfsbelehrung",
            SERVED_NOTICE,
        ),
    ),
    payload={
        "kind": "authority_letter",
        "title": "Decision",
        "summary": "s",
        "explanation": "e",
        "sender": {"name": "Landratsamt Beispielkreis", "kind": "authority"},
        "document_date": "2026-09-15",
        "items": [
            {
                "kind": "deadline",
                "title": "Object to the decision",
                "quote": SERVED_NOTICE,
                "date": {
                    "type": "relative",
                    "amount": 1,
                    "unit": "months",
                    "anchor": "receipt",
                    "delivery_rule": "none",
                    "nature": "objection",
                },
            }
        ],
    },
)


@pytest.mark.parametrize("reading", ["complete", "empty"])
async def test_a_formally_served_letter_asks_for_the_envelope_and_then_counts_from_it(
    data_dir: Path, pinned_today: None, reading: str
) -> None:
    """Through the app: the letter's to-do cites ``pzu`` (the web asks "When was it delivered?" — the date on the
    yellow envelope, nothing prefilled) and counts from the letter's date, Tue 15 Sep: Thu 15 Oct. The person enters
    the envelope's Fri 18 Sep: one month is Sun 18 Oct → Mon 19 Oct, and no notice is set beside it."""
    letter = SERVED_LETTER
    if reading == "empty":
        payload = {key: SERVED_LETTER.payload[key] for key in ("kind", "title", "summary", "explanation")}
        letter = Letter(marker=SERVED_MARKER, pages=SERVED_LETTER.pages, payload=payload)
    async with api_for(data_dir, router=Router(letters=(letter,))) as api:
        body = await api.upload((f"{SERVED_MARKER}.pdf", letter.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        [item] = (await api.client.get(f"/api/documents/{doc_id}")).json()["items"]
        assert item["due_date"] == "2026-10-15" and "pzu" in item["computation"]["rule_ids"]
        assert (item["slot_key"] == CHECK_SLOT) is (reading == "empty")
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-18"})
        assert response.status_code == 200
        [stored] = api.ctx.store.list_items(doc_id=doc_id)
        assert stored.due_date == "2026-10-19"
        assert stored.computation is not None and "conflicting_dates" not in stored.computation.rule_ids


# --------------------------------------------------------------------------------------------------
# 2. A reminder that restates another decision's notice; a notice's bare "des Bescheides" (V4-2, R4FP-6)
# --------------------------------------------------------------------------------------------------

REMINDER = (
    "Stadt Musterstadt · Stadtkasse · Rathausplatz 1 · 12345 Musterstadt",
    "Herrn",
    "Max Mustermann",
    "Lindenweg 7",
    "12345 Musterstadt",
    "Datum: 25.09.2026",
    "Zahlungserinnerung",
    "Sehr geehrter Herr Mustermann,",
)


@pytest.mark.parametrize(
    "decision",
    [
        "mit Gebührenbescheid vom 03.09.2026 haben wir eine Gebühr von 85,00 EUR festgesetzt, die noch offen ist.",
        "mit unserem Gebührenbescheid haben wir eine Gebühr von 85,00 EUR festgesetzt, die noch offen ist.",
    ],
    ids=["dated", "undated"],
)
@pytest.mark.parametrize(
    "notice",
    [
        "Hinweis: Hiergegen kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        "Sie können dagegen innerhalb eines Monats nach Bekanntgabe Widerspruch erheben.",
    ],
    ids=["hiergegen", "dagegen"],
)
def test_a_reminder_s_hiergegen_is_never_dated_from_the_reminder(decision: str, notice: str) -> None:
    """Security V4-2: the reminder of 25.09 restates the notice of a decision of 03.09 (allowed: 2026-10-07): it was
    2026-10-28, counted from the reminder — now undated."""
    pages = [
        page(*REMINDER, decision, "Bitte zahlen Sie die Gebühr von 85,00 EUR bis zum 09.10.2026.", notice)
    ]
    for reading in (blank(), blank(sender=SENDER, document_date="2026-09-25", items=[payment()])):
        assert check_due(pages, reading) is None


def test_a_decision_s_own_hiergegen_keeps_its_date() -> None:
    """A decision that names itself one ("Gebührenbescheid", "mit diesem Bescheid") and says "Hiergegen": dated."""
    for body in (
        ("Gebührenbescheid", "Sehr geehrte Frau Probe,"),
        ("Sehr geehrte Frau Probe,", "mit diesem Bescheid …"),
    ):
        pages = [
            page(
                "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen",
                *ADDRESS,
                "Datum: 06.11.2026",
                *body,
                "wir setzen die Gebühr auf 85,00 EUR fest.",
                "Hiergegen kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
            )
        ]
        assert check_due(pages) == NOTIFIED_DUE


KASSEL = (
    "Stadt Kassel · Rathaus · Obere Königsstraße 8 · 34117 Kassel",
    "Herrn",
    "Paul Lehmann",
    "Gartenstraße 12",
    "34117 Kassel",
)
GIVEN = "Gegen diesen Bescheid ist der Widerspruch gegeben."
BARE = "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe des Bescheides schriftlich bei der Stadt Kassel einzulegen."


@pytest.mark.parametrize(
    "body",
    [
        (
            "Änderungsbescheid",
            "Sehr geehrter Herr Lehmann,",
            "dieser Bescheid ersetzt den Bescheid vom 03.03.2026.",
        ),
        (
            "Änderungsbescheid",
            "Sehr geehrter Herr Lehmann,",
            "dieser Bescheid ersetzt den Bescheid vom 11.09.2026.",
        ),
        (
            "Bescheid über besonderes Kirchgeld 2024",
            "Sehr geehrter Herr Lehmann,",
            "auf Grundlage des Einkommensteuerbescheids 2024 vom 12.06.2026 setzen wir das Kirchgeld auf 240,00 EUR fest.",
        ),
    ],
    ids=["replaced-long-ago", "replaced-recently", "based-on-another"],
)
def test_a_bare_des_bescheides_beside_gegen_diesen_bescheid_is_this_letter(body: tuple[str, ...]) -> None:
    """R4FP-6: "Gegen diesen Bescheid ist der Widerspruch gegeben." and "… nach Bekanntgabe des Bescheides …": the
    other decisions' dates are no weak dates of this one — it was undated or 2026-10-14 (12 days early), now the
    letter's own date gives 2026-10-26 (21.09: delivered Thu 24.09, one month Sat 24.10 → Mon 26.10)."""
    pages = [page(*KASSEL, "Datum: 21.09.2026", *body, "Rechtsbehelfsbelehrung", GIVEN, BARE)]
    assert check_due(pages) == "2026-10-26"


def test_a_compound_noun_still_names_another_decision() -> None:
    """The designed guard stays: "… des Steuerbescheides" beside "den Steuerbescheid vom 03.03.2026" is that one."""
    other = "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe des Steuerbescheides einzulegen."
    body = (
        "Änderungsbescheid",
        "Sehr geehrter Herr Lehmann,",
        "dieser Bescheid ersetzt den Steuerbescheid vom 03.03.2026.",
    )
    pages = [page(*KASSEL, "Datum: 21.09.2026", *body, "Rechtsbehelfsbelehrung", GIVEN, other)]
    assert check_due(pages) is None


# --------------------------------------------------------------------------------------------------
# 4. A Widerspruchsbescheid's reasoning (R4FP-8)
# --------------------------------------------------------------------------------------------------

COURT = (
    "Gegen den Bescheid vom 02.06.2026 in der Gestalt dieses Widerspruchsbescheides kann innerhalb eines Monats nach "
    "Zustellung Klage beim Verwaltungsgericht Kassel erhoben werden."
)


@pytest.mark.parametrize(
    "reason",
    [
        "Der Widerspruch ist unzulässig, weil er erst nach Ablauf der einmonatigen Widerspruchsfrist eingelegt wurde.",
        "Der Widerspruch ist unzulässig, da er nicht innerhalb eines Monats nach Bekanntgabe des Bescheides vom "
        "02.06.2026 erhoben wurde.",
        "Der Widerspruch ist zulässig, insbesondere wurde er fristgerecht innerhalb eines Monats nach Bekanntgabe des "
        "Kostenbescheides erhoben.",
    ],
    ids=["einmonatig", "bescheid-vom", "fristgerecht"],
)
def test_a_widerspruchsbescheid_s_reasoning_is_no_notice(reason: str) -> None:
    """R4FP-8: the remedy already lodged, reported in the reasoning, is no notice: it left the check undated (a
    period it can't read, a decision of 02.06 as a start) — now the court action's month from 21.09: 2026-10-21."""
    pages = [
        page(
            *KASSEL,
            "Datum: 21.09.2026",
            "Widerspruchsbescheid",
            "Ihr Widerspruch vom 30.07.2026 wird zurückgewiesen.",
            "Gründe",
            reason,
            "Rechtsbehelfsbelehrung",
            COURT,
        )
    ]
    assert [notice.remedy for notice in remedy_notices(pages)] == ["klage"]
    assert check_due(pages) == "2026-10-21"


def test_a_requirement_in_the_perfect_is_still_a_notice() -> None:
    """ "… muss innerhalb eines Monats … eingelegt worden sein" is a notice, never a report."""
    line = "Der Widerspruch muss innerhalb eines Monats nach Bekanntgabe bei uns eingelegt worden sein."
    pages = [
        page(
            *KASSEL,
            "Datum: 21.09.2026",
            "Bescheid",
            "Sehr geehrter Herr Lehmann,",
            "Die Gebühr beträgt 20 EUR.",
            line,
        )
    ]
    assert len(remedy_notices(pages)) == 1


# --------------------------------------------------------------------------------------------------
# 3. Own-date forms; 5. a planted line or an appointment's block while the own date is unread
# --------------------------------------------------------------------------------------------------

TOWN_HEAD = "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen"
FEE = (
    "",
    "Gebührenbescheid",
    "Sehr geehrte Frau Probe,",
    "wir setzen die Gebühr auf 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
    "Gegen diesen Bescheid können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
)


@pytest.mark.parametrize(
    "head",
    [
        ("06.11.2026", "STADT BEISPIELHAUSEN", "Sozialamt", *ADDRESS),  # a transcript's first line
        (TOWN_HEAD, *ADDRESS, "", "Ort, Datum: Beispielhausen, 06.11.2026"),
        (TOWN_HEAD, *ADDRESS, "", f"Ihr Zeichen:{G}Beispielhausen, 06.11.2026"),
        (TOWN_HEAD, *ADDRESS, "", f"Leistungsabteilung{G}Datum 06.11.2026"),
        ("Landkreis Beispielhausen · Am Markt 2", "Frau Mara Probe", "Beispielhausen, 06.11.2026"),
    ],
    ids=["first-line", "ort-datum", "ihr-zeichen", "leistungsabteilung", "town-of-letterhead"],
)
def test_the_letter_s_own_date_in_more_forms_starts_the_check(head: tuple[str, ...]) -> None:
    """R4D-3: forms that were read weakly or not at all now date an empty reading (2026-12-09), never later."""
    pages = [page(*head, *FEE)]
    assert letter_date(blank(), pages) == date(2026, 11, 6)
    assert check_due(pages) == NOTIFIED_DUE


def test_a_stand_label_only_lowers_the_start() -> None:
    """ "Stand: 06.11.2026" is weak: alone it starts nothing; beside a later bare date on the date line it lowers the
    start to its own day (that later date was the start: 2026-12-16)."""
    assert check_due([page(TOWN_HEAD, *ADDRESS, "", "Stand: 06.11.2026", *FEE)]) is None
    later = [page(TOWN_HEAD, *ADDRESS, "", "13.11.2026", "", "Stand: 06.11.2026", *FEE)]
    assert check_due(later) == NOTIFIED_DUE


@pytest.mark.parametrize(
    "planted",
    [
        ("Abholung am Schalter, 20.11.2026",),
        ("Sprechtag, Dienstag, 17.11.2026",),
        (f"Zustellung{G}Beispielhausen, 20.11.2026",),
        ("Ortstermin Frankfurt am Main, 20.11.2026",),
        ("20.11.2026", "09:00 Uhr, Raum 2.14"),
        ("Ihr Termin", "Datum: 20.11.2026", "Raum: 2.14"),
        ("Einladung zum Gespräch", "Datum: 20.11.2026", "Ort: Jobcenter, Raum 2.14"),
        (f"Datum{G}Betrag{G}Kassenzeichen", f"04.12.2026{G}85,00 EUR{G}1234-5678"),
        (f"Unser Zeichen{G}Datum{G}Stichtag", f"ST-22{G}01.12.2026"),
    ],
    ids=["abholung", "sprechtag", "zustellung-column", "ortstermin", "dateline-appointment", "termin-block",
         "einladung-block", "payments-table", "stichtag-column"],
)  # fmt: skip
@pytest.mark.parametrize("own", [(), ("", "Stand: 06.11.2026")], ids=["no-own-date", "stand"])
def test_a_planted_line_or_an_appointment_never_starts_the_check(
    planted: tuple[str, ...], own: tuple[str, ...]
) -> None:
    """While the letter's own date (06.11) is unread, a line named like it but of no own kind — a place the page
    names nowhere else, an appointment's block or time, a payments table — starts nothing: an empty reading is
    undated (it was 2026-12-16 to 2027-01-07); with the reading's own date, 2026-12-09."""
    pages = [page(TOWN_HEAD, *ADDRESS, "", *planted, *own, *FEE)]
    assert letter_date(blank(), pages, today=date(2026, 12, 20)) is None
    assert check_due(pages) is None
    assert check_due(pages, blank(sender=SENDER, document_date="2026-11-06")) == NOTIFIED_DUE


@pytest.mark.parametrize(("offset", "start"), [(1, date(2026, 11, 6)), (14, date(2026, 11, 6)), (15, None)])
def test_a_date_alone_under_a_sentence_still_lowers_the_start(offset: int, start: date | None) -> None:
    """A date alone on its line under a sentence that names another date ("Mit diesem Bescheid vom … setzen wir …
    fest.", planted above a transcript's first-line date) is weak, not dropped: it lowers the start that sentence
    sets, or leaves none when more than 14 days earlier (the extended fuzz's last late start)."""
    planted = date(2026, 11, 6) + timedelta(days=offset)
    lines = (f"Mit diesem Bescheid vom {planted:%d.%m.%Y} setzen wir die Gebühr fest.", "06.11.2026")
    pages = [page(*lines, TOWN_HEAD, *ADDRESS, "", *FEE)]
    assert letter_date(blank(), pages) == start


def test_the_rival_still_counts_a_place_named_nowhere_else() -> None:
    """P5 only ever lowers a reading's date: its start keeps a place-date whose place the page names nowhere else."""
    pages = [page(TOWN_HEAD, *ADDRESS, "", "Frankfurt am Main, 06.11.2026", *FEE)]
    assert _own_start(pages) == date(2026, 11, 6)
    assert letter_date(blank(), pages) is None


# --------------------------------------------------------------------------------------------------
# 6. A fixed date the letter sets for the person that the reading left out (check:deadline)
# --------------------------------------------------------------------------------------------------

INVOICE_HEAD = (
    "Stadtwerke Beispielhausen GmbH · Werkstraße 1 · 12345 Beispielhausen",
    *ADDRESS,
    "Datum: 01.10.2026",
)
WITH_SENDER = {
    "sender": {"name": "Stadtwerke Beispielhausen GmbH", "kind": "utility"},
    "document_date": "2026-10-01",
}


def dropped(*lines: str, **fields: Any) -> list[tuple[str | None, str]]:
    """The dates :func:`deadline_items` files for a reading with only the sender and the letter's date."""
    pages = [page(*INVOICE_HEAD, "Rechnung", "Sehr geehrte Frau Probe,", *lines)]
    items = deadline_items(blank(**{**WITH_SENDER, **fields}), pages, today=date(2026, 10, 3))
    return [(item.date.date, item.date.nature) for item in items]


@pytest.mark.parametrize(
    ("line", "nature"),
    [
        ("Zahlbar bis 15.10.2026", "payment"),
        ("Fällig am: 15.10.2026", "payment"),
        (
            "Bitte überweisen Sie den Betrag von 85,00 EUR bis zum 15.10.2026 auf das unten genannte Konto.",
            "payment",
        ),
        ("Der Betrag ist bis zum 15.10.2026 zu zahlen.", "payment"),
        ("Die Nachzahlung ist am 15.10.2026 fällig.", "payment"),
        ("Bitte reichen Sie die fehlenden Unterlagen bis zum 15.10.2026 ein.", "declaration"),
        ("Die Nachweise sind bis spätestens 15.10.2026 vorzulegen.", "declaration"),
        ("Please pay the amount of EUR 85.00 by 15.10.2026.", "payment"),
        ("Please return the signed form by 15.10.2026.", "declaration"),
    ],
)
def test_an_explicit_date_the_reading_left_out_gets_a_to_do(line: str, nature: str) -> None:
    assert dropped(line) == [("2026-10-15", nature)]


@pytest.mark.parametrize(
    "line",
    [
        "Der Betrag war bis zum 15.10.2026 fällig.",  # past
        "Ihre Zahlung vom 15.10.2026 haben wir bereits erhalten.",  # already done
        "Falls Sie nicht bis zum 15.10.2026 zahlen, erhalten Sie eine Mahnung.",  # a condition
        "Wir buchen den Betrag am 15.10.2026 von Ihrem Konto ab.",  # the sender's own act, a debit
        "Wir überweisen Ihnen das Guthaben bis zum 15.10.2026.",  # money coming in
        "Bitte erscheinen Sie am 15.10.2026 um 10:00 Uhr in Zimmer 2.",  # an appointment
        "Bei Zahlung bis zum 15.10.2026 gewähren wir 2 % Skonto.",  # a discount
        "Bitte zahlen Sie möglichst bis zum 15.10.2026.",  # a preference
        "Der Tarif gilt bis zum 15.10.2026.",  # a validity
        "Gegen diesen Bescheid kann bis zum 15.10.2026 Widerspruch eingelegt werden.",  # the remedy's own check
        "Ihr Vertrag läuft bis zum 15.10.2026.",  # a term
        "Bitte überweisen Sie den Betrag bis zum 30.09.2026.",  # before the letter's own date: history
        "Bitte überweisen Sie den Betrag bis zum 01.10.2026.",  # the letter's own date
        "Der Zählerstand vom 15.10.2026 wird geschätzt.",  # a date without a deadline's words
        "Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum.",  # a period, not a date
    ],
)
def test_a_date_that_is_no_deadline_of_the_person_s_gets_none(line: str) -> None:
    assert dropped(line) == []


def test_a_to_do_of_the_reading_within_three_days_covers_the_date() -> None:
    line = "Bitte überweisen Sie den Betrag bis zum 15.10.2026."
    near = payment(quote=line, type="fixed", date="2026-10-13", nature="payment")
    assert dropped(line, items=[near]) == []
    far = ExtractedItem.model_validate(
        {
            "kind": "deadline",
            "title": "Send the meter reading",
            "quote": "Bitte teilen Sie uns den Zählerstand mit.",
            "date": {"type": "fixed", "date": "2026-11-30", "nature": "declaration"},
        }
    )
    assert dropped(line, "Bitte teilen Sie uns den Zählerstand mit.", items=[far]) == [
        ("2026-10-15", "payment")
    ]


def test_a_date_past_when_the_letter_arrived_gets_none() -> None:
    """Never an overdue to-do from code: a date already past on the day the letter arrived or is read."""
    line = "Bitte überweisen Sie den Betrag bis zum 15.10.2026."
    pages = [page(*INVOICE_HEAD, "Rechnung", "Sehr geehrte Frau Probe,", line)]
    assert deadline_items(blank(**WITH_SENDER), pages, today=date(2026, 10, 16)) == []
    assert [
        item.date.date for item in deadline_items(blank(**WITH_SENDER), pages, today=date(2026, 10, 15))
    ] == ["2026-10-15"]


def test_a_date_in_a_sentence_the_reading_quotes_gets_none() -> None:
    """The reading read that sentence: a date it misread there is the quote check's to flag, not a second to-do."""
    line = "Bitte überweisen Sie den Betrag bis zum 15.10.2026."
    misread = payment(quote=line, type="fixed", date="2026-11-30", nature="payment")
    assert dropped(line, items=[misread]) == []
    undated = payment(quote=line, type="none", nature="payment")
    assert dropped(line, items=[undated]) == []


def test_a_payment_date_beside_the_reading_s_payment_is_named_there_not_filed() -> None:
    """A second payment date the letter gives beside the reading's payment is that to-do's rival
    (conflicts.find_rivals): its receipt names it and keeps the earlier — no to-do of its own."""
    line = "Bitte überweisen Sie den Betrag bis zum 15.10.2026."
    other = payment(quote="Die Gebühr beträgt 85,00 EUR.", type="fixed", date="2026-11-30", nature="payment")
    assert dropped(line, items=[other]) == []


def test_the_later_of_two_dates_the_letter_gives_one_payment_is_set_beside_it_not_filed() -> None:
    """A letter that contradicts itself ("bis zum 15.10." in the text, "Zahlbar bis 22.10." in its box): the
    reading's to-do keeps the earlier and names the later (conflicts.settle) — no second to-do for the later."""
    text = "Bitte überweisen Sie den Betrag von 85,00 EUR bis zum 15.10.2026."
    reading = payment(quote=text, type="fixed", date="2026-10-15", nature="payment")
    assert dropped(text, "Zahlbar bis 22.10.2026", items=[reading]) == []


def test_an_empty_reading_or_one_that_calls_the_letter_a_scam_gets_none() -> None:
    """An almost blank reading gets its own to-do ("Read this letter yourself"); a scam's payment a reading left out
    on purpose is never brought back."""
    pages = [page(*INVOICE_HEAD, "Bitte überweisen Sie den Betrag bis zum 15.10.2026.")]
    assert deadline_items(blank(), pages) == []
    scam = blank(
        **WITH_SENDER, warnings=["This letter shows signs of a scam: the IBAN does not match the sender."]
    )
    assert deadline_items(scam, pages) == []


def test_the_dropped_date_is_a_low_please_check_to_do_with_its_quote_located() -> None:
    line = "Bitte überweisen Sie den Betrag von 85,00 EUR bis zum 15.10.2026."
    pages = [page(*INVOICE_HEAD, "Rechnung", "Sehr geehrte Frau Probe,", line)]
    reading = blank(**WITH_SENDER, kind="invoice")
    verification = verify_extraction("doc_x", reading, pages, check_reading=True, today=date(2026, 10, 3))
    [verified] = verification.items
    assert verified.slot_key == DEADLINE_SLOT and is_check_slot(verified.slot_key)
    assert verified.evidence.grounding == "verified" and DEADLINE_LEFT_OUT in verified.reasons
    assert verified.needs_check
    result = compute_item(verified, RuleContext(today=date(2026, 10, 3)), postal_buffer_days=3)
    assert result.due_date == "2026-10-15"  # the letter's own date, never moved
    assert result.receipt is not None and result.receipt.confidence == "low"
    assert any(
        warning.startswith("Claude's reading of this letter left out a date")
        for warning in verification.warnings
    )
    assert not any("could not be confirmed" in warning for warning in verification.warnings)


def test_a_weekend_date_is_never_moved_later() -> None:
    """Sat 17 Oct 2026: the letter's own date stands (a later Monday is not what it says)."""
    line = "Bitte überweisen Sie den Betrag bis zum 17.10.2026."
    pages = [page(*INVOICE_HEAD, line)]
    [item] = deadline_items(blank(**WITH_SENDER), pages)
    [verified] = verify_extraction("doc_x", blank(**WITH_SENDER), pages, check_reading=True).items
    assert item.date.shift_rule == "none"
    assert (
        compute_item(verified, RuleContext(today=date(2026, 10, 3)), postal_buffer_days=3).due_date
        == "2026-10-17"
    )


def test_the_deadline_warning_goes_once_its_to_do_was_dealt_with() -> None:
    class Stored:
        def __init__(self, slot: str, status: str) -> None:
            self.slot_key, self.status, self.grounding, self.origin = slot, status, "verified", "extracted"
            self.due_date = "2026-10-15"
            self.date_spec = None
            self.evidence = [type("E", (), {"value_consistent": False})()]

    warning = "Claude's reading of this letter left out a date the letter sets for you. Ordnung added it …"
    assert square_gap_warnings([warning], [Stored(DEADLINE_SLOT, "open")]) == [warning]
    assert square_gap_warnings([warning], [Stored(DEADLINE_SLOT, "done")]) == []
    assert needs_check  # (imported for the stored check's rule)


DROPPED_MARKER = "Rechnung Wasser 2026"
DROPPED_LINE = "Bitte überweisen Sie den Betrag von 85,00 EUR bis zum 09.10.2026."
DROPPED_LETTER = Letter(
    marker=DROPPED_MARKER,
    pages=(
        (
            "Stadtwerke Beispielhausen GmbH, Werkstraße 1, 12345 Beispielhausen",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "Datum: 21.09.2026",
            DROPPED_MARKER,
            "Sehr geehrte Frau Probe,",
            DROPPED_LINE,
        ),
    ),
    payload={
        "kind": "invoice",
        "title": "Water bill",
        "summary": "s",
        "explanation": "e",
        "sender": {"name": "Stadtwerke Beispielhausen GmbH", "kind": "utility"},
        "document_date": "2026-09-21",
    },
)


async def test_a_dropped_payment_date_is_filed_and_a_later_complete_reading_replaces_it(
    data_dir: Path, pinned_today: None
) -> None:
    router = Router(letters=(DROPPED_LETTER,))
    async with api_for(data_dir, router=router) as api:
        body = await api.upload((f"{DROPPED_MARKER}.pdf", DROPPED_LETTER.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        [item] = detail["items"]
        assert item["slot_key"] == DEADLINE_SLOT and item["due_date"] == "2026-10-09"
        assert item["computation"]["confidence"] == "low"
        assert any(
            w.startswith("Claude's reading of this letter left out") for w in detail["document"]["warnings"]
        )
        [stored] = api.ctx.store.list_items(doc_id=doc_id)
        assert needs_check(stored)

        # read again, now with the payment: the reading's own to-do, and code's is gone (the person didn't act on it)
        payload = router.payloads[DROPPED_MARKER]
        payload["items"] = [
            {
                "kind": "payment",
                "title": "Pay the water bill",
                "quote": DROPPED_LINE,
                "amount": 85.0,
                "date": {"type": "fixed", "date": "2026-10-09", "nature": "payment"},
            }
        ]
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        [again] = api.ctx.store.list_items(doc_id=doc_id)
        assert not is_check_slot(again.slot_key) and again.due_date == "2026-10-09"
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert not any(
            w.startswith("Claude's reading of this letter left out") for w in detail["document"]["warnings"]
        )


async def test_a_payment_the_person_paid_is_never_filed_again_when_a_reading_leaves_it_out(
    data_dir: Path, pinned_today: None
) -> None:
    """Read again after the person marked the payment paid, by a reading that leaves it out: the paid to-do is kept
    and the letter's date for it gets no second to-do of Ordnung's (plan._covered_deadlines)."""
    router = Router(letters=(DROPPED_LETTER,))
    payload = router.payloads[DROPPED_MARKER]
    payload["items"] = [
        {
            "kind": "payment",
            "title": "Pay the water bill",
            "quote": DROPPED_LINE,
            "amount": 85.0,
            "date": {"type": "fixed", "date": "2026-10-09", "nature": "payment"},
        }
    ]
    async with api_for(data_dir, router=router) as api:
        body = await api.upload((f"{DROPPED_MARKER}.pdf", DROPPED_LETTER.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        [paid] = api.ctx.store.list_items(doc_id=doc_id)
        response = await api.client.patch(f"/api/items/{paid.id}", json={"status": "done"})
        assert response.status_code == 200, response.text

        payload["items"] = []
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        [kept] = api.ctx.store.list_items(doc_id=doc_id)
        assert kept.id == paid.id and kept.status == "done" and not is_check_slot(kept.slot_key)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert not any(
            w.startswith("Claude's reading of this letter left out") for w in detail["document"]["warnings"]
        )


def test_the_web_app_knows_the_deadline_check_its_warning_and_its_note() -> None:
    """The web app spells code's to-do for a dropped date out: its slot, the letter's warning (no scam sign) and the
    receipt's note (Today's reason)."""
    warnings = (ROOT / "web" / "src" / "features" / "document" / "Warnings.tsx").read_text(encoding="utf-8")
    assert f'export const DEADLINE_CHECK_SLOT = "{DEADLINE_SLOT}";' in warnings
    selection = (ROOT / "web" / "src" / "features" / "today" / "selection.ts").read_text(encoding="utf-8")
    assert f'"{DEADLINE_SLOT}"' in selection
    warning = _web_regex("features/document/Warnings.tsx", "DEADLINE_WARNING")
    assert warning.match(deadline_warning(1)) and warning.match(deadline_warning(2))
    note = _web_regex("features/today/selection.ts", "READING_INCOMPLETE_NOTE")
    assert note.match(REASON_TEXT[DEADLINE_LEFT_OUT])
