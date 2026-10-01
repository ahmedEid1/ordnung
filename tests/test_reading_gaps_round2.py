"""Round 2 of the review of the check for incomplete readings (``ingest/gaps.py``): every probe the reviewers
and their verifiers wrote, as synthetic regression tests. The rule over all of them: the code's own date, and
the date it sets beside a reading's (P5), is never later than the letter allows — at worst undated.

All letters are invented ("Stadt Beispielhausen", dated Fri 6 Nov 2026 unless said otherwise); no benchmark or
prompt text."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from ordnung.ingest.gaps import (
    KNOWN_ADDRESS,
    LAW_DATED_KINDS,
    check_item,
    dates_the_objection,
    letter_date,
    notice_rival,
    reading_gap,
    remedy_notices,
    start_variants,
)
from ordnung.ingest.plan import compute_item, verify_extraction
from ordnung.ingest.verify import MODEL_READ_NOTE, READING_INCOMPLETE, REASON_TEXT, regrade
from ordnung.models import ComputationReceipt, DateSpec, ExtractedItem, ExtractedParty
from ordnung.rules import RuleContext
from ordnung.rules.routing import letter_kind
from test_reading_gaps import (
    FROM_LETTER_DUE,
    HEAD,
    LETTERHEAD,
    NOTIFIED,
    NOTIFIED_DUE,
    SENDER,
    SERVED,
    THREE_MONTHS,
    TODAY,
    WHERE,
    blank,
    ctx_for,
    due,
    objection,
    page,
    payment,
)

#: The decision's header without its "Datum:" line (the date is put in by each test).
TOP = (LETTERHEAD, "Frau Mara Probe", "Probeweg 2", "12345 Beispielhausen")
BODY = (
    "Gebührenbescheid über die Sondernutzung einer Gehwegfläche",
    "Sehr geehrte Frau Probe,",
    "mit diesem Bescheid setzen wir für die Nutzung der Gehwegfläche eine Gebühr von 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
)
COMPLETE = {"sender": SENDER, "document_date": "2026-11-06"}


def check_due(pages: list[Any], reading: Any = None, **ctx: Any) -> str | None:
    """The check to-do's date (``None``: undated); fails when the check doesn't fire."""
    read = reading or blank()
    verification = verify_extraction("doc_x", read, pages, check_reading=True)
    verified = verification.items[-1]
    assert verified.slot_key == "check:reading"
    return compute_item(verified, ctx_for(read, **ctx), postal_buffer_days=3).due_date


def objection_due(pages: list[Any], spec: dict[str, Any], quote: str = NOTIFIED, **fields: Any) -> Any:
    """The reading's own objection to-do (``spec``), verified and computed: (due, computed)."""
    reading = blank(**{**COMPLETE, **fields}, items=[objection(spec, quote=quote)])
    [verified] = [v for v in verify_extraction("doc_x", reading, pages, check_reading=True).items]
    computed = compute_item(verified, ctx_for(reading), postal_buffer_days=3)
    return computed.due_date, computed


def fires(pages: list[Any], **fields: Any) -> bool:
    reading = blank(**{**COMPLETE, **fields}, items=[payment()])
    return reading_gap(reading, pages, remedy_notices(pages)) == "remedy_left_out"


# --------------------------------------------------------------------------------------------------
# The letter's own date: strong and weak (dates 3, security F1, dates 10)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "later",
    [
        "Einzugsdatum: 01.12.2026",
        "Buchungsdatum: 20.11.2026",
        "Wirksamkeitsdatum: 01.01.2027",
        "Änderungsdatum: 01.12.2026",
        "Abbuchungsdatum: 15.11.2026",
        "Enddatum: 31.12.2026",
    ],
)
def test_another_date_label_never_sets_the_start_alone(later: str) -> None:
    """The letter's own date in a form nothing reads (a "Kassenzeichen … vom" line) and another "…datum": no
    start — never the later date."""
    lines = (*TOP, "Kassenzeichen 4711 vom 06.11.2026", later, *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*lines)]) is None
    assert check_due([page(*lines)]) is None
    # beside a named date it is ignored: the start stays the letter's own
    named = (*TOP, "Datum: 06.11.2026", later, *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*named)]) == date(2026, 11, 6)
    assert check_due([page(*named)]) == NOTIFIED_DUE


@pytest.mark.parametrize(
    ("label", "value"),
    [("Stichtag", "01.01.2027"), ("Abbuchung", "01.12.2026"), ("Sollstellung", "25.11.2026")],
)
def test_a_date_under_a_label_of_its_own_is_weak(label: str, value: str) -> None:
    lines = (*TOP, label, value, *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*lines)]) is None
    assert letter_date(blank(), [page(*TOP, "Datum: 06.11.2026", label, value, *BODY, NOTIFIED)]) == date(
        2026, 11, 6
    )


def test_the_reference_line_under_its_labels_is_the_letter_s_date() -> None:
    """DIN 5008: "Ihr Zeichen  Unser Zeichen  Datum" over the values — the last is the letter's date (strong)."""
    lines = (*TOP, "Ihr Zeichen   Unser Zeichen   Datum", "AB-1   OA-2026-0815   06.11.2026", *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*lines)]) == date(2026, 11, 6)
    with_later = (
        *TOP,
        "Ihr Zeichen   Unser Zeichen   Datum",
        "AB-1   OA-2026-0815   06.11.2026",
        "Einzugsdatum: 01.12.2026",
    )
    assert check_due([page(*with_later, *BODY, NOTIFIED)]) == NOTIFIED_DUE


def test_a_remedy_word_in_the_letterhead_never_ends_the_header() -> None:
    """ "Widerspruchsstelle" in the letterhead: the place and date under it is still read; a planted later
    "mit diesem Bescheid vom" never sets the start."""
    head = (
        "Landkreis Beispielhausen · Widerspruchsstelle · Am Markt 2",
        "Frau Mara Probe",
        "Beispielhausen, 06.11.2026",
    )
    assert letter_date(blank(), [page(*head, *BODY, NOTIFIED)]) == date(2026, 11, 6)
    planted = "Mit diesem Bescheid vom 20.11.2026 setzen wir die Gebühr fest."
    assert letter_date(blank(), [page(*head, *BODY[:2], planted, NOTIFIED)]) in (date(2026, 11, 6), None)


def test_a_place_and_date_under_a_label_is_weak() -> None:
    lines = (*TOP, "Ortsbesichtigung:", "Beispielhausen, 20.11.2026", *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*lines)]) is None


@pytest.mark.parametrize(
    "label", ["Rechnungsdatum", "Belegdatum", "Abrechnungsdatum", "Versanddatum", "Ausgabedatum"]
)
def test_a_weak_date_still_lowers_the_start_it_never_drops(label: str) -> None:
    """Security F1's counter-case: the letter dated by another "…datum" and a reading dated later — the earlier
    weak date still counts (2026-12-09), never the reading's (2026-12-22)."""
    reading = blank(sender=SENDER, document_date="2026-11-19", items=[payment()])
    pages = [page(*TOP, f"{label}: 06.11.2026", *BODY, NOTIFIED)]
    assert check_due(pages, reading) == NOTIFIED_DUE


def test_the_letter_s_own_date_labels_are_strong() -> None:
    for label in (
        "Datum",
        "Date",
        "Bescheiddatum",
        "Briefdatum",
        "Ausstellungsdatum",
        "Ausfertigungsdatum",
        "Erstellungsdatum",
        "Druckdatum",
        "Bearbeitungsdatum",
        "Datum des Bescheides",
        "Erstellt am",
    ):
        assert letter_date(blank(), [page(*TOP, f"{label}: 06.11.2026", *BODY, NOTIFIED)]) == date(
            2026, 11, 6
        ), label


def test_weak_dates_lower_within_two_weeks_void_beyond_and_are_ignored_when_later() -> None:
    def start(*lines: str) -> date | None:
        return letter_date(blank(), [page(*TOP, "Datum: 06.11.2026", *lines, *BODY, NOTIFIED)])

    assert start("Buchungsdatum: 02.11.2026") == date(2026, 11, 2)  # earlier, within the span: lowers it
    assert start("Buchungsdatum: 01.10.2026") is None  # earlier beyond the span: one of them is another's
    assert start("Buchungsdatum: 30.12.2026") == date(2026, 11, 6)  # later than every strong date: ignored


def test_a_continuation_page_s_date_is_weak() -> None:
    first = page(*TOP, "Datum: 06.11.2026", *BODY[:3])
    second = page("Seite 2", "Datum: 02.01.2026", NOTIFIED, number=2)
    # far earlier than the first page's: no start (a planted or an old decision's date)
    assert letter_date(blank(), [first, second]) is None
    later = page("Seite 2", "Datum: 30.11.2026", NOTIFIED, number=2)
    assert letter_date(blank(), [first, later]) == date(2026, 11, 6)


def test_a_single_date_long_before_the_letter_arrived_gives_no_start() -> None:
    """dates 10: a stray "Hauptveranlagung auf den 01.01.2025" alone would give an overdue to-do."""
    lines = (*TOP, "Hauptveranlagung auf den", "01.01.2025", "Bescheiddatum: 06.11.2026", *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*lines)]) is None  # 22 months apart: no start
    only = (*TOP, "Bescheiddatum: 01.01.2025", *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*only)], today=date(2026, 11, 10)) is None
    assert letter_date(blank(), [page(*only)], today=date(2025, 1, 10)) == date(2025, 1, 1)
    found = check_item(blank(), [page(*only)], today=date(2026, 11, 10))
    assert found is not None and found.kind == "undated"


# --------------------------------------------------------------------------------------------------
# The decision a notice names (dates 4, R2UX-1)
# --------------------------------------------------------------------------------------------------

REMINDER = (
    LETTERHEAD,
    "Frau Mara Probe",
    "Datum: 20.10.2026",
    "Zahlungserinnerung",
    "Sehr geehrte Frau Probe,",
)


@pytest.mark.parametrize(
    "named",
    [
        "Gegen den Bescheid vom 01.10.2026",
        "Gegen den Bescheid der Stadt Beispielhausen vom 01.10.2026",
        "Gegen die Festsetzung vom 01.10.2026",
        "Gegen den Grundsteuerbescheid 2026 vom 01.10.2026",
        "Gegen den Bescheid über die Abfallgebühr vom 01.10.2026",
        "Gegen den Bescheid (Az. 12-3) vom 01.10.2026",
        "Gegen die Entscheidung vom 01.10.2026",
    ],
)
def test_a_reminder_repeating_an_older_decision_s_notice_is_never_dated_from_the_reminder(named: str) -> None:
    """The decision of 01.10 allows 2026-11-04; counted from the reminder's 20.10 it would be 19 days later."""
    notice = f"{named} können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen."
    reading = blank(sender=SENDER, document_date="2026-10-20", items=[payment()])
    found = check_item(reading, [page(*REMINDER, notice)])
    assert found is not None
    assert found.kind == "undated" or found.item.date.anchor_date == "2026-10-01"


@pytest.mark.parametrize(
    ("first", "rest"),
    [
        (
            "Gegen den Bescheid vom 08.10.2026 können Sie innerhalb",
            "eines Monats nach Bekanntgabe Widerspruch einlegen.",
        ),
        (
            "Gegen den Bescheid vom 01.10.2026 können Sie innerhalb",
            "eines Monats nach Bekanntgabe Widerspruch einlegen.",
        ),
        (
            "Gegen den Bescheid vom",
            "01.10.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
        ),
        (
            "Gegen den Bescheid",
            "vom 01.10.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
        ),
    ],
)
def test_a_wrapped_notice_keeps_the_decision_it_names_and_its_whole_sentence(first: str, rest: str) -> None:
    """UX review 2, R2UX-1: wrapped after "innerhalb", the decision's date was lost — never later than the
    decision's own date allows (08.10: 2026-11-11; 01.10: undated, two dates weeks apart)."""
    reading = blank(sender=SENDER, document_date="2026-10-20", items=[payment()])
    pages = [page(*REMINDER, first, rest)]
    [found_notice] = remedy_notices(pages)
    assert found_notice.quote.startswith("Gegen den Bescheid")
    allowed = "2026-11-11" if "08.10" in first else "2026-11-04"
    got = check_due(pages, reading)
    assert got is None or got <= allowed


@pytest.mark.parametrize("reference", ["(Az. 12-3)", "Nr. 4711", "Kassenzeichen 12-3"])
def test_a_decision_named_over_three_lines_keeps_its_date(reference: str) -> None:
    """Dates 4: "Gegen den Bescheid" / "(Az. 12-3)" / "vom 01.10.2026 können Sie …" — the notice's own lines
    start at its last line, so the decision's date is read from the whole sentence ("gegen … Bescheid … vom"):
    never counted from the reminder's 20.10 (2026-11-23), at most from the decision's (2026-11-04)."""
    lines = (
        "Gegen den Bescheid",
        reference,
        "vom 01.10.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
    )
    pages = [page(*REMINDER, *lines)]
    [found] = remedy_notices(pages)
    assert date(2026, 10, 1) in found.issued
    reading = blank(sender=SENDER, document_date="2026-10-20", items=[payment()])
    got = check_due(pages, reading)
    assert got is None or got <= "2026-11-04"


@pytest.mark.parametrize(
    "line",
    [
        "Gegen diesen Bescheid, mit dem Ihr Antrag vom 15.08.2026 abgelehnt wird, können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
        "Gegen den Bescheid über Ihren Antrag vom 15.08.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
        "Gegen die Entscheidung zu Ihrem Schreiben vom 15.08.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
        "Gegen den Bescheid nach der Anhörung vom 15.08.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
    ],
)
def test_an_application_s_or_a_letter_s_date_is_no_decision_s(line: str) -> None:
    """dates 4: "Antrag vom", "(Ihr) Schreiben vom", "Anhörung vom" date something else — counted as the
    decision's they would leave the check undated and switch the letter's notice (P5) off."""
    [found] = remedy_notices([page(*HEAD, line)])
    assert found.issued == ()
    assert check_due([page(*HEAD, line)]) == NOTIFIED_DUE
    late, computed = objection_due([page(*HEAD, line)], {"type": "fixed", "date": "2027-03-01"}, quote=line)
    assert late == NOTIFIED_DUE and computed.notice


@pytest.mark.parametrize("word", ["Fassung", "Form", "Gestalt"])
def test_the_decision_a_ruling_reshapes_is_never_its_date(word: str) -> None:
    """False positives F7: "in der Fassung/Form/Gestalt dieses Widerspruchsbescheides" — the court action runs
    from this letter."""
    notice = (
        f"Gegen den Bescheid vom 15.08.2026 in der {word} dieses Widerspruchsbescheides kann innerhalb eines Monats "
        "nach Zustellung Klage beim Verwaltungsgericht Beispielstadt erhoben werden."
    )
    [found] = remedy_notices([page(*HEAD, notice)])
    assert found.issued == () and found.remedy == "klage"
    assert check_due([page(*HEAD, notice)]) == FROM_LETTER_DUE


# --------------------------------------------------------------------------------------------------
# Counted back from an event (dates 5), service and download (dates 7, R2T-3), arrival (dates 8)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "notice",
    [
        "Ihr Widerspruch muss uns spätestens zwei Wochen vor dem Erörterungstermin am 20.11.2026 zugegangen sein.",
        "Der Widerspruch ist nach Zugang dieses Schreibens, spätestens 10 Tage vor dem Termin am 20.11.2026, einzulegen.",
        "Einen Widerspruch reichen Sie bitte zwei Wochen vorher ein.",
        "Der Widerspruch ist 14 Tage vor dem Termin einzulegen; die Ladung wurde Ihnen zugestellt.",
        "An objection must be lodged after receipt of this letter and up to two weeks before the hearing.",
        "Ein Widerspruch ist spätestens zwei Wochen, bevor die Verhandlung beginnt, zu begründen.",
    ],
)
def test_a_period_counted_back_is_never_dated_forward_whatever_start_it_names(notice: str) -> None:
    found = check_item(blank(), [page(*HEAD, notice)])
    assert found is not None and found.item.date.type == "none"


@pytest.mark.parametrize(
    "notice",
    [
        "You may lodge an objection within one month of service before the authority that issued this decision.",
        "An appeal against this decision may be lodged within one month after notification before the Administrative Court.",
        "Gegen diesen Bescheid kann innerhalb eines Monats schriftlich vor Ort im Rathaus Widerspruch eingelegt werden.",
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung vor dem Sozialgericht Beispielstadt Klage erhoben werden.",
        # a start between the period and "vor" / "before": never counted back, whoever it is lodged before
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe vor dem Stadtrechtsausschuss Widerspruch erhoben werden.",
        "Gegen diesen Bescheid kann innerhalb eines Monats ab Bekanntgabe vor dem Stadtrechtsausschuss Widerspruch erhoben werden.",
        "You may lodge an objection within one month after notification before the city's appeals committee.",
        "You may lodge an objection within one month following notification before the city's appeals committee.",
    ],
)
def test_before_a_court_or_an_authority_stays_a_forward_notice(notice: str) -> None:
    got = check_due([page(*HEAD, notice)])
    assert got is not None and got <= NOTIFIED_DUE


@pytest.mark.parametrize(
    "service",
    [
        "Per Postzustellungsurkunde",
        "Per PZU",
        "Förmliche Zustellung",
        "Zustellung durch die Post mit ZU",
        "Gegen Empfangsbekenntnis",
        "Einschreiben mit Rückschein",
        "Persönlich ausgehändigt am 06.11.2026",
    ],
)
def test_formal_service_never_gets_delivery_days(service: str) -> None:
    lines = (*HEAD[:4], service, *HEAD[4:], NOTIFIED, WHERE)
    assert due([page(*lines)]) == FROM_LETTER_DUE


@pytest.mark.parametrize(
    "portal",
    [
        "Dieser Bescheid wurde Ihnen zum Abruf bereitgestellt.",
        "Dieser Bescheid steht zum Download bereit.",
        "Sie finden ihn in Ihrem Bürgerportal.",
        "Sie finden ihn in Ihrem Nutzerkonto.",
        "Er wurde in Ihr elektronisches Postfach eingestellt.",
        "Er liegt in Ihrem Online-Postfach.",
    ],
)
def test_a_portal_letter_counts_from_the_day_after_download_never_the_post_s_days(portal: str) -> None:
    assert due([page(*HEAD[:4], portal, *HEAD[4:], NOTIFIED, WHERE)]) == FROM_LETTER_DUE


def test_bundid_is_a_fourth_day_fiction_never_a_download_portal() -> None:
    """§ 9 OZG: a decision in a Nutzerkonto's Postfach counts as notified on the fourth day — as by post."""
    assert (
        due([page(*HEAD[:4], "Er wurde in Ihr BundID-Konto übermittelt.", *HEAD[4:], NOTIFIED, WHERE)])
        == NOTIFIED_DUE
    )


def test_a_private_sender_s_early_arrival_is_a_start_too() -> None:
    """dates 8: a private sender counts from the arrival (§ 130 BGB) — an arrival before the letter's date is a
    start whatever delivery rule the spec carries."""
    arrived = RuleContext(
        today=TODAY,
        document_date=date(2026, 11, 6),
        received_date=date(2026, 11, 4),
        received_confirmed=True,
        private_sender=True,
    )
    spec = DateSpec(
        type="relative",
        amount=1,
        unit="months",
        anchor="explicit_date",
        anchor_date="2026-11-06",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    assert {variant.anchor_date for variant, _ in start_variants(spec, arrived)} == {
        "2026-11-06",
        "2026-11-04",
    }


# --------------------------------------------------------------------------------------------------
# Readings that date the objection: what counts (M3, R2T-4, F4)
# --------------------------------------------------------------------------------------------------


def test_an_objection_that_can_t_compute_without_the_reading_s_date_never_silences_the_check() -> None:
    """dates M3: the reading left its own date out and counts the objection from it — the letter's "Datum"
    still dates the check (2026-12-09)."""
    for anchor in ("document_date", "deemed_delivery", "receipt", None):
        spec = {"type": "relative", "amount": 1, "unit": "months", "anchor": anchor}
        reading = blank(sender=SENDER, items=[objection(spec)])
        assert (
            reading_gap(reading, [page(*HEAD, NOTIFIED)], remedy_notices([page(*HEAD, NOTIFIED)]))
            == "remedy_left_out"
        )
        assert check_due([page(*HEAD, NOTIFIED)], reading) == NOTIFIED_DUE
    # a letter without any date: the reading's undated objection stands, no second undated to-do
    undated = (LETTERHEAD, "Frau Mara Probe", "Gebührenbescheid", "Sehr geehrte Frau Probe,", NOTIFIED)
    reading = blank(
        sender=SENDER,
        items=[objection({"type": "relative", "amount": 1, "unit": "months", "anchor": "document_date"})],
    )
    assert reading_gap(reading, [page(*undated)], remedy_notices([page(*undated)])) is None


def test_a_dated_to_do_without_a_quote_never_counts_as_dating_the_objection() -> None:
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[payment("")])
    assert (
        reading_gap(reading, [page(*HEAD, NOTIFIED)], remedy_notices([page(*HEAD, NOTIFIED)]))
        == "remedy_left_out"
    )
    other = ExtractedItem.model_validate(
        {
            "kind": "deadline",
            "title": "Object",
            "date": {"type": "fixed", "date": "2026-12-01", "nature": "other"},
            "quote": "",
        }
    )
    assert not dates_the_objection(other, remedy_notices([page(*HEAD, NOTIFIED)]))


def test_a_payment_quoting_the_notice_s_words_never_dates_the_objection() -> None:
    """False positives F4: a payment item quoting "innerhalb eines Monats nach Bekanntgabe" left the objection
    out all the same."""
    pages = [page(*HEAD, NOTIFIED)]
    words = "binnen eines Monats nach seiner Bekanntgabe"  # the notice's own words
    pay = payment(words, type="fixed", date="2026-12-09", nature="payment")
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[pay])
    assert reading_gap(reading, pages, remedy_notices(pages)) == "remedy_left_out"
    # a payment by its kind or by its date's nature alone; a to-do of another kind quoting them dates it
    as_other = pay.model_copy(update={"date": pay.date.model_copy(update={"nature": "other"})})
    as_deadline = pay.model_copy(update={"kind": "deadline"})
    task = as_deadline.model_copy(update={"date": as_other.date})
    notices = remedy_notices(pages)
    assert [dates_the_objection(item, notices) for item in (as_other, as_deadline, task)] == [
        False,
        False,
        True,
    ]


@pytest.mark.parametrize(
    "odd", ["binnen 14-tägiger Frist", "binnen der Zweiwochenfrist", "binnen eines Kalendermonats"]
)
def test_a_period_the_parser_can_t_count_beside_a_month_s_court_action_stays_undated(odd: str) -> None:
    """R2T-4: never one month (2026-12-09) when one notice gives a period that may be two weeks."""
    widerspruch = f"Gegen diesen Bescheid kann {odd} nach Bekanntgabe Widerspruch erhoben werden."
    klage = "Gegen den Widerspruchsbescheid kann innerhalb eines Monats nach Zustellung Klage erhoben werden."
    found = check_item(blank(), [page(*HEAD, widerspruch, klage)])
    assert found is not None and found.kind == "undated" and found.item.date.type == "none"


# --------------------------------------------------------------------------------------------------
# Which notices are live: false alarms and silent misses (false positives F2, F3, N1, N2; security F4, M1)
# --------------------------------------------------------------------------------------------------

ACK = (LETTERHEAD, "Frau Mara Probe", "Datum: 09.11.2026", "Ihr Widerspruch", "Sehr geehrte Frau Probe,")


@pytest.mark.parametrize(
    "line",
    [
        "Über Ihren Widerspruch entscheiden wir voraussichtlich innerhalb von drei Monaten.",
        "Die Bearbeitung Ihres Widerspruchs dauert erfahrungsgemäß etwa vier Wochen.",
        "Wir werden über Ihren Einspruch voraussichtlich innerhalb von sechs Wochen entscheiden.",
        "Ihr Widerspruch wird derzeit geprüft; mit einer Entscheidung ist in etwa vier Wochen zu rechnen.",
        "Ist über Ihren Widerspruch nach drei Monaten nicht entschieden, können Sie Untätigkeitsklage erheben.",
        "Gegen einen Aufhebungsbescheid könnten Sie dann innerhalb eines Monats nach Bekanntgabe Einspruch einlegen.",
        "Sollten wir danach einen Bescheid erlassen, können Sie dagegen innerhalb eines Monats Widerspruch erheben.",
        "Wenn Sie Widerspruch einlegen, reichen Sie Ihre Unterlagen bitte innerhalb von drei Wochen nach.",
        "Bitte begründen Sie Ihren Widerspruch innerhalb von zwei Wochen.",
        "Ihr Widerspruch vom 01.10.2026 ist am 05.10.2026 bei uns eingegangen; wir entscheiden innerhalb von vier Wochen.",
        "Da dieses Schreiben keinen Bescheid darstellt, ist ein Widerspruch innerhalb eines Monats nicht vorgesehen.",
        "Gegen den Bescheid vom 01.06.2026 hätten Sie innerhalb eines Monats nach Bekanntgabe Widerspruch erheben müssen.",
        "Da Ihre Angaben widersprüchlich sind, bitten wir Sie, sich innerhalb von zwei Wochen zu äußern.",
    ],
)
def test_a_letter_about_the_person_s_own_objection_or_a_decision_not_made_is_no_notice(line: str) -> None:
    assert not fires([page(*ACK, line)])


@pytest.mark.parametrize(
    "line",
    [
        "Über Ihren Widerspruch entscheiden wir voraussichtlich innerhalb von drei Monaten.",
        "Die Bearbeitung Ihres Widerspruchs dauert erfahrungsgemäß etwa vier Wochen.",
        "Wir werden über Ihren Einspruch voraussichtlich innerhalb von sechs Wochen entscheiden.",
    ],
)
def test_the_person_s_own_objection_being_handled_is_no_notice_on_a_letter_naming_the_decision(
    line: str,
) -> None:
    """False positives N2: an acknowledgement that names the decision objected to shows an administrative act;
    a period for handling the person's own objection is still no notice."""
    named = (
        LETTERHEAD,
        "Frau Mara Probe",
        "Datum: 09.11.2026",
        "Ihr Widerspruch gegen den Bescheid vom 01.10.2026",
        "Sehr geehrte Frau Probe,",
        "vielen Dank für Ihr Schreiben.",
    )
    assert not fires([page(*named, line)])


@pytest.mark.parametrize(
    "line",
    [
        "Gegen dieses Schreiben ist ein Widerspruch nicht möglich. Die Frist zur Stellungnahme beträgt zwei Wochen.",
        "Ein Widerspruch gegen dieses Schreiben ist nicht möglich. Die Frist zur Stellungnahme beträgt zwei Wochen.",
        "Ein Widerspruch ist gegen dieses Schreiben nicht möglich. Die Frist zur Stellungnahme beträgt zwei Wochen.",
        "Sie können gegen dieses Schreiben keinen Widerspruch einlegen. Die Frist zur Stellungnahme beträgt zwei Wochen.",
        "Dies ist kein Bescheid. Ein Widerspruch ist deshalb nicht möglich. Die Frist zur Stellungnahme beträgt zwei Wochen.",
        "Ein Widerspruch gegen dieses Schreiben ist nicht möglich, Sie können sich aber innerhalb von zwei Wochen dazu äußern.",
        "Ein Widerspruch ist gegen dieses Schreiben nicht zulässig, jedoch können Sie sich innerhalb von zwei Wochen äußern.",
    ],
)
def test_a_hearing_that_rules_the_objection_out_stays_silent(line: str) -> None:
    hearing = (
        LETTERHEAD,
        "Frau Mara Probe",
        "Datum: 09.11.2026",
        "Anhörung nach § 24 SGB X",
        "Sehr geehrte Frau Probe,",
    )
    assert not fires([page(*hearing, line)])


MUSTFIRE_HEAD = (*TOP, "Datum: 09.11.2026", *BODY)


@pytest.mark.parametrize(
    ("line", "remedy"),
    [
        (
            "Gegen diese Einspruchsentscheidung über Ihren Einspruch vom 01.09.2026 kann innerhalb eines Monats nach Bekanntgabe Klage beim Finanzgericht erhoben werden.",
            "klage",
        ),
        (
            "Gegen diese Entscheidung über Ihren Widerspruch können Sie innerhalb eines Monats nach Bekanntgabe Klage beim Sozialgericht erheben.",
            "klage",
        ),
        (
            "Belehrung über Ihr Widerspruchsrecht: Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
            "widerspruch",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden; über den Widerspruch entscheidet der Kreisrechtsausschuss.",
            "widerspruch",
        ),
        (
            "Ihren Widerspruch gegen diesen Bescheid müssen Sie vor Ablauf eines Monats nach Bekanntgabe schriftlich bei uns einlegen.",
            "widerspruch",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden; zur Bearbeitung Ihres Widerspruchs geben Sie bitte das Kassenzeichen an.",
            "widerspruch",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden; ein Widerspruch per E-Mail ist nicht zulässig.",
            "widerspruch",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden; ein Widerspruch per Email ist nicht zulässig.",
            "widerspruch",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden, ein Widerspruch am Telefon ist nicht möglich.",
            "widerspruch",
        ),
        (
            "Ein Widerspruch per Telefon ist nicht zulässig; er muss innerhalb eines Monats nach Bekanntgabe schriftlich erhoben werden.",
            "widerspruch",
        ),
        (
            "Ein Widerspruch ist telefonisch nicht möglich; er muss innerhalb eines Monats nach Bekanntgabe schriftlich erhoben werden.",
            "widerspruch",
        ),
        (
            "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen; die Frist ist gewahrt, wenn er rechtzeitig eingegangen ist.",
            "widerspruch",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden; der Widerspruch hält den Einzug per Lastschrift nicht auf.",
            "widerspruch",
        ),
        (
            "Gegen diesen Bescheid kann ohne Widerspruchsverfahren innerhalb eines Monats nach Bekanntgabe Klage beim Verwaltungsgericht erhoben werden.",
            "klage",
        ),
        (
            "Ein Widerspruch ist nicht statthaft, vielmehr kann innerhalb eines Monats nach Bekanntgabe Klage beim Verwaltungsgericht erhoben werden.",
            "klage",
        ),
        (
            "Wenn Sie Widerspruch einlegen wollen, müssen Sie dies innerhalb eines Monats nach Bekanntgabe tun.",
            "widerspruch",
        ),
        (
            "Wird nicht innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben, wird der Bescheid bestandskräftig.",
            "widerspruch",
        ),
    ],
)
def test_a_real_notice_still_fires_never_later_and_names_its_remedy(line: str, remedy: str) -> None:
    """Must still fire (false positives M1–M8, security F4, F3 B3/B3b/B4): the letter of 09.11 allows 14.12."""
    pages = [page(*MUSTFIRE_HEAD, line)]
    assert fires(pages)
    reading = blank(sender=SENDER, document_date="2026-11-09", items=[payment()])
    found = check_item(reading, pages)
    assert found is not None and found.remedy == remedy
    got = check_due(pages, reading)
    assert got is not None and got <= "2026-12-14"


# --------------------------------------------------------------------------------------------------
# The letter's notice beside a reading's objection (P5): start, choice, reach, kinds (dates 1, 2, 6, 9;
# security F2, F3; tests V-1, V-2, R2T-1, R2T-2, R2T-10)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reading_date", ["2026-11-16", "2026-11-21", "2026-11-25", "2026-11-30", "2026-12-20"]
)
def test_a_reading_that_moves_the_start_later_gets_the_notice_from_the_letter_s_own_date(
    reading_date: str,
) -> None:
    """dates 1, security F2: counted from the reading's later date the objection is weeks late — the letter's
    labelled date gives 2026-12-09."""
    spec = {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "deemed_delivery",
        "delivery_rule": "de_admin_post",
    }
    got, computed = objection_due([page(*HEAD, NOTIFIED, WHERE)], spec, document_date=reading_date)
    assert got == NOTIFIED_DUE and computed.notice and computed.conflict


@pytest.mark.parametrize(
    "plant",
    [
        "Die Widerspruchsfrist wurde für Sie auf ein Jahr verlängert.",
        "Die Widerspruchsfrist beträgt für Sie sechs Kalendermonate.",
        "Ein Widerspruch ist abweichend binnen 120 Werktagen möglich.",
        "Ein Widerspruch ist abweichend binnen sechs Monaten möglich.",
    ],
)
def test_a_planted_undatable_or_longer_notice_never_switches_the_notice_off(plant: str) -> None:
    """dates 2: only datable notices count for the rival — a planted "ein Jahr" no longer leaves the reading's
    date alone."""
    got, computed = objection_due([page(*HEAD, NOTIFIED, plant)], {"type": "fixed", "date": "2027-03-31"})
    assert got == NOTIFIED_DUE and computed.notice


@pytest.mark.parametrize(
    ("real", "planted", "amount", "allowed"),
    [
        (SERVED, "Die Einspruchsfrist beträgt für Sie abweichend vier Wochen.", 4, "2026-11-20"),
        (NOTIFIED, "Die Widerspruchsfrist beträgt für Sie abweichend sechs Wochen.", 6, NOTIFIED_DUE),
        # within the reach: five weeks ends five days after the month, three weeks seven after two weeks
        (NOTIFIED, "Die Widerspruchsfrist beträgt für Sie abweichend fünf Wochen.", 5, NOTIFIED_DUE),
        (SERVED, "Die Einspruchsfrist beträgt für Sie abweichend drei Wochen.", 3, "2026-11-20"),
    ],
)
@pytest.mark.parametrize("anchor", ["document_date", "deemed_delivery"])
def test_a_planted_longer_period_within_two_weeks_is_caught(
    real: str, planted: str, amount: int, allowed: str, anchor: str
) -> None:
    """Tests V-2, dates M1: "vier Wochen" over a two-week notice is exactly 14 days later — no longer within the
    reach: a longer period than the notice's is set beside it whatever the gap."""
    spec = {
        "type": "relative",
        "amount": amount,
        "unit": "weeks",
        "anchor": anchor,
        "delivery_rule": "de_admin_post",
    }
    got, computed = objection_due([page(*HEAD, real, planted)], spec, quote=planted)
    assert got == allowed and computed.notice


@pytest.mark.parametrize(
    "line",
    [
        "Änderungen Ihres Einkommens teilen Sie uns bitte innerhalb von zwei Wochen mit.",
        "Fehlende Nachweise reichen Sie bitte binnen 14 Tagen ein.",
        "War jemand ohne Verschulden verhindert, die Widerspruchsfrist einzuhalten, ist ihm auf Antrag Wiedereinsetzung in den vorigen Stand zu gewähren.",
        "Bitte begründen Sie Ihren Widerspruch innerhalb von zwei Wochen nach seiner Einlegung.",
        "Wenn Sie Widerspruch einlegen, reichen Sie Ihre Unterlagen bitte innerhalb von drei Wochen nach.",
    ],
)
def test_an_instruction_after_the_notice_never_pulls_a_correct_reading_earlier(line: str) -> None:
    """Security F3: the notice's own words decide, never an instruction folded in after it."""
    spec = {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "deemed_delivery",
        "delivery_rule": "de_admin_post",
    }
    got, computed = objection_due([page(*HEAD, NOTIFIED, line)], spec)
    assert got == NOTIFIED_DUE and not computed.notice and not computed.conflict


@pytest.mark.parametrize(
    "kind",
    ["dunning", "dismissal", "rent_increase", "landlord_notice", "court_payment_order", "enforcement_order"],
)
@pytest.mark.parametrize("spec", [{"type": "fixed", "date": "2027-03-01"}, THREE_MONTHS])
def test_a_laundered_kind_never_keeps_a_later_objection_date(kind: str, spec: dict[str, Any]) -> None:
    """Tests V-1, R2T-1, dates 6: a reading that files the fee decision as another kind (whose words the letter
    doesn't bear out) never gets the reading's later objection date, nor a letter rule's — the notice's, or the
    check's own to-do."""
    reading = blank(
        kind="authority_letter",
        high_stakes_kind=kind if kind in LAW_DATED_KINDS else None,
        **COMPLETE,
        items=[objection(spec)],
    )
    if kind == "dunning":
        reading = reading.model_copy(update={"kind": "dunning"})
    pages = [page(*HEAD, NOTIFIED, WHERE)]
    verification = verify_extraction("doc_x", reading, pages, check_reading=True)
    # counted as the pipeline counts: in the context of the kind the letter is filed as (§ 574b BGB for a
    # landlord's notice, a reminder's own rule for a dunning letter) — never the notice's date
    ctx = ctx_for(reading, letter_kind=letter_kind(reading))
    dues = [compute_item(v, ctx, postal_buffer_days=3).due_date for v in verification.items]
    dated = [d for d in dues if d is not None]
    assert dated and min(dated) <= NOTIFIED_DUE
    # every dated objection to-do is no later than the letter allows
    assert all(d <= NOTIFIED_DUE for d in dated), dues


def test_a_notice_counted_back_from_an_event_never_sets_its_period_beside_the_reading() -> None:
    """Dates 8: only datable notices give the rival — "spätestens 10 Tage vor dem Termin" counts back from a
    hearing, never ten days from this letter."""
    hearing = "Der Widerspruch gegen die Ladung ist nach Zugang dieses Schreibens, spätestens 10 Tage vor dem Termin, einzulegen."
    pages = [page(*HEAD, NOTIFIED, hearing)]
    got, computed = objection_due(pages, {"type": "fixed", "date": "2027-03-01"})
    assert got == NOTIFIED_DUE and computed.notice
    rival = notice_rival(blank(**COMPLETE), pages)
    assert rival is not None and (rival.spec.amount, rival.spec.unit) == (1, "months")


def test_a_kind_the_letter_bears_out_keeps_the_law_s_dates() -> None:
    lines = (
        "Stadt Beispielhausen · Personalamt · Rathausplatz 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Datum: 06.11.2026",
        "Kündigung Ihres Arbeitsverhältnisses",
        "Sehr geehrte Frau Probe,",
        "hiermit kündigen wir das Arbeitsverhältnis fristgerecht zum 31.12.2026.",
        "Gegen diese Kündigung können Sie innerhalb von drei Wochen nach ihrer Bekanntgabe Klage beim Arbeitsgericht erheben.",
    )
    reading = blank(
        kind="employment",
        high_stakes_kind="dismissal",
        sender=ExtractedParty(name="Stadt Beispielhausen", kind="employer"),
        document_date="2026-11-06",
        items=[objection(THREE_MONTHS, quote=lines[-1])],
    )
    assert notice_rival(reading, [page(*lines)]) is None


def test_a_notice_from_service_is_set_beside_without_delivery_days() -> None:
    """R2T-2: two weeks after Zustellung from Fri 6 Nov is Fri 20 Nov, never the post's 23 Nov."""
    got, computed = objection_due([page(*HEAD, SERVED, WHERE)], THREE_MONTHS, quote=SERVED)
    assert got == "2026-11-20" and computed.notice


def test_a_photo_s_notice_keeps_its_ai_read_note_when_kept() -> None:
    """R2T-10."""
    got, computed = objection_due([page(*HEAD, NOTIFIED, WHERE, source="transcript")], THREE_MONTHS)
    assert got == NOTIFIED_DUE and computed.notice
    assert computed.receipt is not None and MODEL_READ_NOTE in computed.receipt.warnings


@pytest.mark.parametrize(
    "lines",
    [
        # no labelled date on the first page: a date alone, a continuation page's, the reading's
        ((LETTERHEAD, "Frau Mara Probe", "06.11.2026", *BODY, NOTIFIED),),
        (
            (LETTERHEAD, "Frau Mara Probe", "Kassenzeichen 4711 vom 06.11.2026", *BODY[:3]),
            ("Seite 2", "Datum: 02.01.2026", NOTIFIED),
        ),
    ],
)
def test_the_notice_s_start_is_only_the_first_page_s_own_labelled_date(
    lines: tuple[tuple[str, ...], ...],
) -> None:
    """dates 1, security F2 counter-case: never a bare, a continuation page's or the reading's date — no rival
    rather than a passed date for a correct reading."""
    pages = [page(*part, number=index + 1) for index, part in enumerate(lines)]
    reading = blank(**COMPLETE, items=[objection()])
    assert notice_rival(reading, pages) is None


def test_a_reading_s_date_weeks_early_never_gives_a_passed_date() -> None:
    got, computed = objection_due(
        [page(*HEAD, NOTIFIED, WHERE)], {"type": "fixed", "date": "2027-03-31"}, document_date="2026-01-02"
    )
    assert got == NOTIFIED_DUE and computed.notice


def test_a_person_s_earlier_letter_date_moves_the_notice_earlier() -> None:
    """dates 9: the notice's due is the earliest over its starts — a letter date the person corrected to two
    weeks earlier counts too."""
    reading = blank(**COMPLETE, items=[objection(THREE_MONTHS)])
    [verified] = verify_extraction("doc_x", reading, [page(*HEAD, NOTIFIED, WHERE)], check_reading=True).items
    corrected = replace(ctx_for(reading), document_date=date(2026, 10, 23))
    computed = compute_item(verified, corrected, postal_buffer_days=3)
    assert computed.notice and computed.due_date is not None and computed.due_date < NOTIFIED_DUE


def test_a_served_notice_starts_on_the_arrival_the_person_confirmed() -> None:
    """False positives F1: the person entered the yellow envelope's date (20.11): a two-week Zustellung notice
    then runs from it (Fri 4 Dec), never from the letter's date into the past — but a planted longer period is
    still pulled to it."""
    reading = blank(
        **COMPLETE,
        items=[
            objection({"type": "relative", "amount": 2, "unit": "weeks", "anchor": "receipt"}, quote=SERVED)
        ],
    )
    [verified] = verify_extraction("doc_x", reading, [page(*HEAD, SERVED, WHERE)], check_reading=True).items
    ctx = replace(ctx_for(reading), received_date=date(2026, 11, 20), received_confirmed=True)
    computed = compute_item(verified, ctx, postal_buffer_days=3)
    assert computed.due_date == "2026-12-04" and not computed.conflict
    planted = blank(
        **COMPLETE,
        items=[
            objection({"type": "relative", "amount": 3, "unit": "months", "anchor": "receipt"}, quote=SERVED)
        ],
    )
    [verified] = verify_extraction("doc_x", planted, [page(*HEAD, SERVED, WHERE)], check_reading=True).items
    computed = compute_item(verified, ctx, postal_buffer_days=3)
    assert computed.due_date == "2026-12-04" and computed.notice


def test_the_conflict_says_the_reading_s_date_is_the_reading_s() -> None:
    """UX review 2, M1: the later date comes from Claude's reading, not from the letter."""
    _, computed = objection_due([page(*HEAD, NOTIFIED, WHERE)], THREE_MONTHS)
    assert computed.receipt is not None
    [warning] = [w for w in computed.receipt.warnings if "two dates" in w]
    assert warning.startswith(
        "Claude's reading and the letter's own instructions on how to object give two dates"
    )


# --------------------------------------------------------------------------------------------------
# Copy (security F5, R2UX-5)
# --------------------------------------------------------------------------------------------------


def test_an_almost_blank_reading_says_where_to_send_the_objection() -> None:
    found = check_item(blank(), [page(*HEAD, NOTIFIED)])
    assert found is not None and found.item.action is not None and found.item.action.endswith(KNOWN_ADDRESS)


def test_the_copy_holds_with_or_without_a_date() -> None:
    """R2UX-5: an undated check to-do never says "by this date" or "worked this date out"."""
    found = check_item(
        blank(),
        [
            page(
                *HEAD,
                "Gegen diesen Bescheid kann binnen 10 Werktagen nach Zustellung Widerspruch erhoben werden.",
            )
        ],
    )
    assert found is not None and found.kind == "undated"
    words = f"{found.item.action} {found.item.consequence}"
    assert "this date" not in words and "worked" not in words


@pytest.mark.parametrize(
    ("kind", "line", "fires_check"),
    [
        # a laundered rent increase (law: 59 days at the least) and a two-month notice (56 days counted short)
        (
            "rent_increase",
            "Gegen diesen Bescheid können Sie binnen zwei Monaten nach Bekanntgabe Widerspruch einlegen.",
            True,
        ),
        # a laundered dismissal (law: 21 days) and a three-week notice: the law's date is never later
        (
            "dismissal",
            "Gegen diesen Bescheid können Sie binnen drei Wochen nach Bekanntgabe Widerspruch einlegen.",
            False,
        ),
    ],
)
def test_a_laundered_law_kind_counts_only_with_a_period_no_shorter_than_the_law(
    kind: str, line: str, fires_check: bool
) -> None:
    """R2T-4: the law files a kind's deadline itself only when the notice's period is no shorter than the law's."""
    pages = [page(*HEAD, line)]
    reading = blank(kind="authority_letter", high_stakes_kind=kind, sender=SENDER, document_date="2026-11-06")
    assert (reading_gap(reading, pages, remedy_notices(pages)) == "remedy_left_out") is fires_check


def test_a_receipt_stored_with_the_note_s_earlier_wording_still_grades_the_next_occurrence_low() -> None:
    """UX review 2, R2UX-5: the incomplete reading's note was reworded; a receipt stored with the earlier words
    still grades the next date of the same reading low, with the note as it reads now."""
    earlier = (
        "Ordnung worked this date out from the letter's own instructions on how to object, because Claude's "
        "reading left the deadline out — check it against the letter."
    )
    again = regrade(
        ComputationReceipt(due_date="2027-01-11"),
        ComputationReceipt(due_date="2026-12-09", warnings=[earlier]),
    )
    assert again.confidence == "low" and REASON_TEXT[READING_INCOMPLETE] in again.warnings
