"""Round 4 of the review of the check for incomplete readings (``ingest/gaps.py``): the letter's own date in a
header whose columns the text layer ran together (dates R4D-1, R4D-2, V4-1), periods that belong to a payment or
to something else than lodging (false positives R4FP-1, -2, -3, -4, -5, -7), and a restated notice, the court
action's tie, a heading word inside a sentence and an appointment's time line (security R4ADV-1..7, V4-1). The rule
over all of them: the code's own date, and the date it sets beside a reading's, is never later than the letter
allows — at worst undated.

All letters are invented ("Stadt Beispielhausen", dated Fri 6 Nov 2026 unless said otherwise); no benchmark or
prompt text."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TODAY, Letter, Router, fake_backend
from helpers_docs import Line, make_pdf
from ordnung import clock
from ordnung.app_context import build_context
from ordnung.ingest.gaps import CHECK_SLOT, _own_start, check_item, letter_date, remedy_notices
from ordnung.ingest.pipeline import add_file
from ordnung.ingest.plan import needs_check
from test_reading_gaps import FROM_LETTER_DUE, NOTIFIED_DUE, SENDER, blank, page, payment
from test_reading_gaps_round2 import BODY, COMPLETE, TOP, check_due, fires, objection_due
from test_reading_gaps_round3 import NOTICE, ONE_MONTH

G = "   "  # the gap the text layer leaves between two columns run into one line
LETTERHEAD_LINE = "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen"
SALUTED = (
    "",
    "Gebührenbescheid",
    "",
    "Sehr geehrte Frau Probe,",
    "wir setzen die Abfallgebühr für 2027 auf 185,00 EUR fest.",
    "",
    "Rechtsbehelfsbelehrung",
    NOTICE,
)
UNSALUTED = (
    "",
    "Bescheid über Abfallgebühren 2027",
    "Die Abfallgebühr wird auf 185,00 EUR festgesetzt.",
    "",
    "Rechtsbehelfsbelehrung",
    NOTICE,
)
INFO = ("Steuernummer: 123/456/78901", "Datum: 06.11.2026")


# --------------------------------------------------------------------------------------------------
# The letter's own date in a header the text layer ran together (dates R4D-1, R4D-2, V4-1)
# --------------------------------------------------------------------------------------------------

RUN_TOGETHER = {
    "a street named 'Am …' beside 'Datum'": (
        LETTERHEAD_LINE, "", "Frau", "Mara Probe", f"Am Lindenhof 2{G}Datum 06.11.2026", "12345 Beispielhausen"
    ),
    "a place and date beside the postcode line": (
        LETTERHEAD_LINE, "", "Frau", "Mara Probe", "Probeweg 2", f"12345 Beispielhausen{G}Beispielhausen, 06.11.2026"
    ),
    "an abbreviated street beside 'Datum'": (
        LETTERHEAD_LINE, "", "Frau", "Mara Probe", f"Freiherr-vom-Stein-Str. 2{G}Datum 06.11.2026",
        "12345 Beispielhausen",
    ),
    "'Bescheiddatum' beside a street named 'Zum …'": (
        LETTERHEAD_LINE, "", "Frau", "Mara Probe", f"Zum Wald 3{G}Bescheiddatum: 06.11.2026", "12345 Beispielhausen"
    ),
    "an info block whose labels and values stand in columns": (
        LETTERHEAD_LINE,
        f"Herrn{G}Steuernummer{G}123/456/78901",
        f"Max Probe{G}Bitte bei allen Rückfragen angeben",
        f"Probeweg 2{G}Datum{G}06.11.2026",
        f"12345 Beispielhausen{G}Telefon{G}0123 456-0",
    ),
    "a doctor's title in the address, the info block under it": (
        LETTERHEAD_LINE, "", "Herrn", "Dr. Max Probe", "Probeweg 2", "12345 Beispielhausen", "", *INFO
    ),
    "a department's abbreviation in the letterhead": (
        "Stadt Beispielhausen · Abt. Steuern · Am Markt 1 · 12345 Beispielhausen",
        *INFO, "", "Herrn", "Max Probe", "Probeweg 2", "12345 Beispielhausen",
    ),
    "a town named 'St. …'": (
        LETTERHEAD_LINE, "", "Herrn", "Max Probe", "Probeweg 2", "53757 St. Augustin", "", *INFO
    ),
}  # fmt: skip


@pytest.mark.parametrize("body", [SALUTED, UNSALUTED], ids=["salutation", "no salutation"])
@pytest.mark.parametrize("head", list(RUN_TOGETHER.values()), ids=list(RUN_TOGETHER))
def test_the_letter_s_own_date_in_a_header_run_together_starts_the_notice(
    head: tuple[str, ...], body: tuple[str, ...]
) -> None:
    """R4D-1, R4D-2, V4-1: a "Datum" or a place and date beside an address line ("Am Lindenhof 2", a postcode
    line), an info block whose label and value the text layer set apart, and an abbreviation's period before it
    ("Dr.", "Abt.", "St.") — the letter's own date all the same: an empty reading gets the notice's date
    (2026-12-09), never undated, and nothing later."""
    pages = [page(*head, *body)]
    assert _own_start(pages) == date(2026, 11, 6)
    assert letter_date(blank(), pages) == date(2026, 11, 6)
    assert check_due(pages) == NOTIFIED_DUE


@pytest.fixture
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def test_a_two_column_pdf_header_with_a_doctor_s_title_dates_the_check(
    data_dir: Path, pinned_today: None
) -> None:
    """R4D-2 and V4-1 through the real text layer: the address in the left column ("Dr. Max Probe"), the info
    block in the right, no salutation. Posted Tue 15 Sep 2026, delivered on the 3rd day (Fri 18 Sep): one month
    is Sun 18 Oct → Mon 19 Oct."""
    marker = "Abfallgebührenbescheid"
    left = (
        "Stadt Beispielhausen, Rathausplatz 1, 12345 Beispielhausen",
        "Herrn",
        "Dr. Max Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
        "",
        marker,
        "Die Abfallgebühr für 2027 wird auf 185,00 EUR festgesetzt.",
        "Rechtsbehelfsbelehrung",
        NOTICE,
    )
    right = {1: "Steuernummer: 123/456/78901", 3: "Datum: 15.09.2026"}
    lines = [Line(72, 90 + 20 * row, text, size=11) for row, text in enumerate(left) if text]
    lines += [Line(330, 90 + 20 * row, text, size=11) for row, text in right.items()]
    letter = Letter(
        marker=marker,
        pages=(left,),
        payload={"kind": "other", "title": "Letter", "summary": "s", "explanation": "e"},
    )
    ctx = build_context(data_dir, backend_obj=fake_backend(Router(letters=(letter,))))
    try:
        document = await add_file(ctx, make_pdf([lines]), "bescheid.pdf")
        await ctx.worker.run_until_idle()
        [check] = ctx.store.list_items(doc_id=document.id)
        assert check.slot_key == CHECK_SLOT and check.due_date == "2026-10-19" and needs_check(check)
    finally:
        ctx.close()


# --------------------------------------------------------------------------------------------------
# Periods that are no period for lodging, and notices that are none (false positives R4FP-1..5, 7)
# --------------------------------------------------------------------------------------------------

FEE_DECISION = (*TOP, "Datum: 06.11.2026", *BODY, NOTICE)


@pytest.mark.parametrize(
    "hint",
    [
        "Widerspruch und Anfechtungsklage haben keine aufschiebende Wirkung (§ 80 Abs. 2 Satz 1 Nr. 1 VwGO), d. h. "
        "der Betrag ist auch bei Einlegung eines Widerspruchs innerhalb von zwei Wochen nach Bekanntgabe zu zahlen.",
        "Der Betrag ist innerhalb von zwei Wochen nach Bekanntgabe zu zahlen, auch wenn Sie Widerspruch einlegen.",
        "Bitte zahlen Sie den Betrag innerhalb von zwei Wochen, auch wenn Sie Widerspruch erheben.",
        "Die Gebühr wird zwei Wochen nach Bekanntgabe dieses Bescheides fällig; die Einlegung eines Widerspruchs "
        "ändert daran nichts.",
        "Sie müssen den Betrag auch dann innerhalb von zwei Wochen zahlen, wenn Sie Widerspruch einlegen.",
        "Der Betrag ist auch dann innerhalb von zwei Wochen zu zahlen, wenn Widerspruch erhoben wird.",
        "Wenn Sie Widerspruch einlegen, hat dieser keine aufschiebende Wirkung; der Betrag ist trotzdem innerhalb von "
        "zwei Wochen nach Bekanntgabe zu zahlen.",
    ],
)
def test_a_payment_s_period_beside_a_remedy_word_is_never_the_notice_s(hint: str) -> None:
    """R4FP-1, R4ADV-4: the period a payment verb governs ("… innerhalb von zwei Wochen … zu zahlen, auch wenn Sie
    Widerspruch einlegen") is the payment's: a correct reading stays unflagged (it was 2026-11-20 or -23, low,
    "Please check") and an empty one gets the notice's month (2026-12-09), never the two weeks."""
    pages = [page(*FEE_DECISION, "Hinweis", hint)]
    got, computed = objection_due(pages, ONE_MONTH, quote=NOTICE)
    assert got == NOTIFIED_DUE and not computed.conflict
    assert check_due(pages) == NOTIFIED_DUE


@pytest.mark.parametrize(
    "notice",
    [
        "Die Einlegung eines Widerspruchs muss innerhalb eines Monats nach Bekanntgabe erfolgen; der Betrag ist "
        "trotzdem bis zum 15.12.2026 zu zahlen.",
        "Die Erhebung des Widerspruchs ist binnen eines Monats nach Bekanntgabe bei der Stadt Beispielhausen "
        "vorzunehmen; der Betrag ist dennoch zu zahlen.",
        "Zur Einlegung eines Widerspruchs haben Sie einen Monat nach Bekanntgabe Zeit; die Gebühr ist gleichwohl "
        "fällig.",
    ],
)
def test_a_notice_followed_by_a_payment_clause_keeps_its_period(notice: str) -> None:
    """R4FP-1's counter-cases: a lodging period with a payment clause after it is still the notice's."""
    pages = [page(*TOP, "Datum: 06.11.2026", *BODY, notice)]
    assert fires(pages)
    assert check_due(pages) == NOTIFIED_DUE


def test_a_plain_language_notice_whose_period_follows_in_the_next_sentence_is_dated() -> None:
    """R4FP-5: "Sie können … Widerspruch einlegen. Das müssen Sie innerhalb eines Monats nach Erhalt dieses
    Briefes tun." — one notice, counted from the letter's date (receipt, no delivery days): 2026-12-07."""
    lines = (
        "Sie können gegen diesen Bescheid Widerspruch einlegen.",
        "Das müssen Sie innerhalb eines Monats nach Erhalt dieses Briefes tun.",
    )
    pages = [page(*TOP, "Datum: 06.11.2026", *BODY, *lines)]
    assert fires(pages)
    assert check_due(pages) == FROM_LETTER_DUE


ACKNOWLEDGEMENT = (
    "Stadt Beispielhausen · Wohngeldstelle · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau",
    "Erika Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 06.11.2026",
    "Eingangsbestätigung Ihres Wohngeldantrags",
    "Sehr geehrte Frau Probe,",
    "Ihr Antrag ist bei uns eingegangen. Wir prüfen ihn und senden Ihnen anschließend einen Bescheid.",
)


@pytest.mark.parametrize(
    "line",
    [
        "Gegen einen ablehnenden Bescheid können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch erheben.",
        "Gegen eine ablehnende Entscheidung können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch erheben.",
        "Gegen den dann ergehenden Bescheid können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch erheben.",
        "Sie können der Verarbeitung Ihrer Daten jederzeit widersprechen (Art. 21 DSGVO). Wir beantworten Ihre "
        "Anfrage innerhalb eines Monats nach Eingang.",
        "Der Abbuchung können Sie innerhalb von acht Wochen bei Ihrer Bank widersprechen.",
    ],
)
def test_a_decision_still_to_come_a_data_right_or_a_debit_s_refund_is_no_notice(line: str) -> None:
    """R4FP-2, -3, -4, -7: a remedy against a decision not yet made ("einen ablehnenden Bescheid", "den dann
    ergehenden"), the data-protection right to object, and a debit's refund are no notice."""
    pages = [page(*ACKNOWLEDGEMENT, line, "Mit freundlichen Grüßen")]
    assert not any(found.live for found in remedy_notices(pages))
    assert not fires(pages)


# --------------------------------------------------------------------------------------------------
# A restated notice, the court action's tie, a heading word inside a sentence (security R4ADV-1..7, V4-1)
# --------------------------------------------------------------------------------------------------

MUSTER = (
    "Stadt Musterstadt · Stadtkasse · Rathausplatz 1 · 12345 Musterstadt",
    "Herrn",
    "Max Mustermann",
    "Lindenweg 7",
    "12345 Musterstadt",
    "Kassenzeichen 4711.0817.01",
    "Datum: 25.09.2026",
    "Zahlungserinnerung",
    "Sehr geehrter Herr Mustermann,",
    "mit Gebührenbescheid vom 03.09.2026 haben wir eine Gebühr von 85,00 EUR festgesetzt, die noch offen ist.",
    "Bitte zahlen Sie die Gebühr von 85,00 EUR bis zum 09.10.2026.",
    "Hinweis: Gegen den Gebührenbescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
)


@pytest.mark.parametrize(
    "closing",
    [
        "Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift gültig.",
        "Sollten Sie inzwischen gezahlt haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.",
    ],
)
def test_a_closing_line_after_a_restated_notice_never_dates_it_from_the_reminder(closing: str) -> None:
    """R4ADV-1: a closing sentence folded into another decision's restated notice ("Dieses Schreiben …") never
    makes it this letter's: the decision of 03.09 allows 2026-10-07; counted from the reminder's 25.09 it was
    2026-10-28 — now undated or earlier."""
    pages = [page(*MUSTER, closing)]
    for reading in (blank(), blank(sender=SENDER, document_date="2026-09-25", items=[payment()])):
        got = check_due(pages, reading)
        assert got is None or got <= "2026-10-07"


def _cover(body: str) -> list[Any]:
    """A tax adviser's cover letter of 30.09 restating the notice of the tax decision it encloses."""
    return [
        page(
            "Lohnsteuerhilfe Musterstadt e.V. · Beratungsstelle · Marktplatz 2 · 12345 Musterstadt",
            "Herrn",
            "Max Mustermann",
            "Lindenweg 7",
            "12345 Musterstadt",
            "Musterstadt, 30.09.2026",
            "Ihr Steuerbescheid 2025",
            "Sehr geehrter Herr Mustermann,",
            body,
            "Der Bescheid entspricht Ihrer Erklärung.",
            "Gegen den Steuerbescheid können Sie innerhalb eines Monats nach Bekanntgabe Einspruch einlegen.",
            "Mit freundlichen Grüßen",
        )
    ]


def test_a_cover_letter_dates_the_enclosed_decision_s_notice_from_that_decision_or_not_at_all() -> None:
    """R4ADV-1: the decision of 21.09 allows 2026-10-26 (it was 2026-11-03, from the cover letter's own date);
    when the letter names no date for it, undated."""
    named = _cover(
        "anbei erhalten Sie Ihren Einkommensteuerbescheid 2025 vom 21.09.2026, den wir geprüft haben."
    )
    assert check_due(named) == "2026-10-26"
    unnamed = _cover("anbei erhalten Sie Ihren Einkommensteuerbescheid 2025, den wir geprüft haben.")
    assert check_due(unnamed) is None


FIRST_INSTANCE = (
    "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau",
    "Erika Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Beispielhausen, 06.11.2026",
    "Bescheid über die Erhebung einer Verwaltungsgebühr",
    "Sehr geehrte Frau Probe,",
    "für die Ausstellung der Genehmigung setzen wir eine Gebühr von 120,00 EUR fest.",
)


@pytest.mark.parametrize(
    ("tail", "remedy"),
    [
        (
            (
                NOTICE,
                "Über den Widerspruch entscheidet die Widerspruchsbehörde durch Widerspruchsbescheid.",
                "Gegen den Widerspruchsbescheid kann innerhalb eines Monats nach seiner Zustellung Klage erhoben "
                "werden.",
            ),
            "widerspruch",
        ),
        (
            (
                "Gegen diesen Bescheid ist der Einspruch gegeben. Der Einspruch ist innerhalb eines Monats nach "
                "Bekanntgabe dieses Bescheides einzulegen.",
                "Gegen die Einspruchsentscheidung kann innerhalb eines Monats nach Bekanntgabe Klage beim "
                "Finanzgericht erhoben werden.",
            ),
            "einspruch",
        ),
    ],
)
def test_a_first_decision_explaining_the_later_court_action_names_the_objection(
    tail: tuple[str, ...], remedy: str
) -> None:
    """R4ADV-2: a first decision whose notice also explains the court action against the later decision on the
    objection is no decision on an objection: the to-do is the objection's, dated no later than 2026-12-09."""
    pages = [page(*FIRST_INSTANCE, *tail, "Mit freundlichen Grüßen")]
    reading = blank(**COMPLETE, items=[payment(quote="setzen wir eine Gebühr von 120,00 EUR fest")])
    found = check_item(reading, pages)
    assert found is not None and found.remedy == remedy
    got = check_due(pages, reading)
    assert got is not None and got <= NOTIFIED_DUE


HEARING = (
    "Stadt Beispielhausen · Bauamt · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau",
    "Erika Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 06.11.2026",
    "Anhörung",
    "Sehr geehrte Frau Probe,",
    "wir beabsichtigen, Ihnen die Nutzung des Gartenhauses zu untersagen.",
    "Sie haben Gelegenheit, sich bis zum 27.11.2026 zu äußern.",
)


@pytest.mark.parametrize(
    "lines",
    [
        (
            "Sollten wir danach einen Bescheid erlassen, erhalten Sie mit diesem eine",
            "Rechtsbehelfsbelehrung; danach können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch erheben.",
        ),
        (
            "Gegen einen späteren Bescheid können Sie nach der dort enthaltenen",
            "Rechtsbehelfsbelehrung innerhalb eines Monats nach Bekanntgabe Widerspruch erheben.",
        ),
        (
            "Erst nach Erlass des Bescheides könnten Sie gemäß der beigefügten",
            "Rechtsbehelfsbelehrung innerhalb eines Monats nach Bekanntgabe Widerspruch erheben.",
        ),
    ],
)
def test_a_heading_word_wrapped_inside_a_hearing_s_sentence_is_no_notice(lines: tuple[str, ...]) -> None:
    """R4ADV-3: "Rechtsbehelfsbelehrung" at the start of a wrapped line inside a sentence is no heading that
    cuts off the sentence's condition ("Sollten wir …", "Gegen einen späteren Bescheid …")."""
    pages = [page(*HEARING, *lines, "Mit freundlichen Grüßen")]
    assert not any(found.live for found in remedy_notices(pages))
    assert not fires(pages)


@pytest.mark.parametrize(
    "notice",
    [
        "Sie können diesem Bescheid innerhalb eines Monats nach Bekanntgabe widersprechen, auch wenn Sie am "
        "Lastschriftverfahren teilnehmen.",
        "Auch bei erteiltem SEPA-Lastschriftmandat können Sie diesem Bescheid innerhalb eines Monats nach "
        "Bekanntgabe widersprechen.",
    ],
)
def test_a_notice_naming_the_direct_debit_still_fires(notice: str) -> None:
    """R4ADV-6's must-fire side: a real notice that also names the direct debit is no debit's refund."""
    pages = [page(*TOP, "Datum: 06.11.2026", *BODY, notice)]
    assert fires(pages)
    assert check_due(pages) == NOTIFIED_DUE


def test_the_own_date_line_with_a_print_time_under_it_starts_the_notice() -> None:
    """Security V4-1: "Uhrzeit: 10:15 Uhr" under the info block's "Datum:" is no appointment's block: the letter of
    15.09 allows 2026-10-19, and a reading that dates it 25.09 (2026-10-28) gets that date beside it."""
    pages = [
        page(
            "Landratsamt Beispielkreis · Kfz-Zulassungsstelle · Am Markt 3 · 12345 Beispielhausen",
            "Frau Erika Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "Kassenzeichen: 123-45",
            "Datum: 15.09.2026",
            "Uhrzeit: 10:15 Uhr",
            "Sachbearbeiter: Herr Muster",
            "Gebührenbescheid",
            "Sehr geehrte Frau Probe,",
            "mit diesem Bescheid setzen wir eine Gebühr von 30,70 EUR fest.",
            "Rechtsbehelfsbelehrung",
            NOTICE,
            "Mit freundlichen Grüßen",
        )
    ]
    got, computed = objection_due(pages, ONE_MONTH, quote=NOTICE, document_date="2026-09-25")
    assert got == "2026-10-19" and computed.conflict
