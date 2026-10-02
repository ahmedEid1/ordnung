"""Round 3 of the review of the check for incomplete readings (``ingest/gaps.py``): the tests lens's guards
(R3T-1..11, V3T-1), the dates, false-positives and security findings as synthetic regression tests, and a bounded
fuzz of the letter's own date. The rule over all of them: the code's own date, and the date it sets beside a
reading's (P5), is never later than the letter allows — at worst undated.

All letters are invented ("Stadt Beispielhausen", dated Fri 6 Nov 2026 unless said otherwise); no benchmark or
prompt text."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from ordnung.ingest.conflicts import letter_statements
from ordnung.ingest.gaps import (
    LETTER_DATE_SPAN,
    _own_start,
    check_item,
    letter_date,
    notice_rival,
    reading_gap,
    remedy_notices,
)
from ordnung.ingest.plan import compute_item, verify_extraction
from ordnung.models import ExtractedParty
from test_reading_gaps import (
    FROM_LETTER_DUE,
    HEAD,
    LETTERHEAD,
    NOTIFIED,
    NOTIFIED_DUE,
    SENDER,
    SERVED,
    THREE_MONTHS,
    WHERE,
    blank,
    ctx_for,
    objection,
    page,
    payment,
)
from test_reading_gaps_round2 import BODY, COMPLETE, REMINDER, TOP, check_due, fires, objection_due

ONE_MONTH = {
    "type": "relative",
    "amount": 1,
    "unit": "months",
    "anchor": "deemed_delivery",
    "delivery_rule": "de_admin_post",
}
LATE = {"type": "fixed", "date": "2027-03-01"}


def reading_with(*items: Any, **fields: Any) -> Any:
    return blank(**{**COMPLETE, **fields}, items=list(items))


# --------------------------------------------------------------------------------------------------
# The tests lens: guards no test held (R3T-1..11, V3T-1)
# --------------------------------------------------------------------------------------------------

REFERENCE = "Ihr Zeichen   Ihre Nachricht vom   Unser Zeichen   Datum"


def test_the_reference_line_s_own_date_is_its_last_never_the_person_s_letter_s() -> None:
    """R3T-2: DIN 5008's reference line names the person's own letter first ("Ihre Nachricht vom"): the letter's
    date is the last — never the person's letter's, ten days earlier (a false "Please check")."""
    lines = (*TOP, REFERENCE, "AB-1   27.10.2026   OA-2026-0815   06.11.2026", *BODY, NOTIFIED)
    rival = notice_rival(blank(**COMPLETE), [page(*lines)])
    assert rival is not None and rival.spec.anchor_date == "2026-11-06"
    got, computed = objection_due([page(*lines)], ONE_MONTH)
    assert got == NOTIFIED_DUE and not computed.conflict


def test_a_date_column_in_the_letter_s_body_is_no_reference_line() -> None:
    """R3T-2: a table in the body ("Rate  Betrag  Datum") never sets the notice's start."""
    table = ("Rate   Betrag   Datum", "1   42,50 EUR   15.12.2026")
    lines = (*TOP, "Datum: 06.11.2026", *BODY[:3], *table, BODY[3], NOTIFIED)
    got, computed = objection_due([page(*lines)], THREE_MONTHS)
    assert got == NOTIFIED_DUE and computed.notice


def test_a_place_and_date_in_the_body_is_weak() -> None:
    """R3T-2: only a place and date among the header's lines is the letter's own."""
    lines = (*TOP, "Datum: 06.11.2026", *BODY[:3], "Beispielhausen, 15.12.2026", BODY[3], NOTIFIED)
    assert letter_date(blank(), [page(*lines)]) == date(2026, 11, 6)
    got, computed = objection_due([page(*lines)], THREE_MONTHS)
    assert got == NOTIFIED_DUE and computed.notice


def test_a_strong_date_long_before_with_a_weak_one_beside_it_keeps_its_start() -> None:
    """R3T-8: the stale rule is for one date alone."""
    lines = (*TOP, "Bescheiddatum: 01.07.2026", "Buchungsdatum: 30.06.2026", *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*lines)], today=date(2026, 11, 10)) == date(2026, 6, 30)


def test_a_single_date_is_stale_only_after_sixty_days() -> None:
    """R3T-8."""
    only = (*TOP, "Bescheiddatum: 01.09.2026", *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*only)], today=date(2026, 10, 31)) == date(2026, 9, 1)  # 60 days
    assert letter_date(blank(), [page(*only)], today=date(2026, 11, 1)) is None  # 61 days


def test_a_letter_the_notice_names_lowers_the_start() -> None:
    """R3T-6: "Gegen unser Schreiben vom 02.11.2026" in a letter printed 06.11: the earlier date counts."""
    notice = (
        "Gegen unser Schreiben vom 02.11.2026 können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch "
        "einlegen."
    )
    pages = [page(*TOP, "Datum: 06.11.2026", *BODY, notice)]
    assert letter_date(blank(), pages) == date(2026, 11, 2)
    assert check_due(pages) == "2026-12-07"


def test_the_decision_a_notice_names_alone_sets_the_start() -> None:
    """R3T-6."""
    notice = (
        "Gegen den Bescheid vom 06.11.2026 können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch "
        "einlegen."
    )
    pages = [page(LETTERHEAD, "Frau Mara Probe", "Gebührenbescheid", "Sehr geehrte Frau Probe,", notice)]
    assert letter_date(blank(), pages) == date(2026, 11, 6)
    found = check_item(blank(), pages)
    assert found is not None and found.kind == "dated"


@pytest.mark.parametrize(
    "notice",
    [
        "Den Bescheid der Stadt Beispielhausen über die Abfallgebühr vom 01.10.2026 können Sie innerhalb eines "
        "Monats nach Bekanntgabe mit dem Widerspruch anfechten.",
        "Gegen den Verwaltungsakt vom 01.10.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch "
        "einlegen.",
    ],
)
def test_an_older_decision_a_reminder_s_notice_names_is_never_dated_from_the_reminder(notice: str) -> None:
    """R3T-6: never dated from the reminder's 20.10 (2026-11-24), at worst undated."""
    reading = blank(sender=SENDER, document_date="2026-10-20", items=[payment()])
    found = check_item(reading, [page(*REMINDER, notice)])
    assert found is not None
    assert found.kind == "undated" or found.item.date.anchor_date == "2026-10-01"


def test_a_place_and_date_header_starts_the_notice() -> None:
    """R3T-1: the commonest German header ("Beispielhausen, 06.11.2026") starts the notice."""
    got, computed = objection_due([page(*TOP, "Beispielhausen, 06.11.2026", *BODY, NOTIFIED)], THREE_MONTHS)
    assert got == NOTIFIED_DUE and computed.notice


OWN_BODY = "mit diesem Bescheid vom {} setzen wir eine Gebühr von 85,00 EUR fest."


def test_this_decision_s_own_date_in_its_body_starts_the_notice() -> None:
    """R3T-1."""
    body = (BODY[0], BODY[1], OWN_BODY.format("06.11.2026"), BODY[3])
    got, computed = objection_due([page(*TOP, *body, NOTIFIED)], THREE_MONTHS)
    assert got == NOTIFIED_DUE and computed.notice


def test_two_own_dates_near_each_other_start_the_notice_at_the_earlier() -> None:
    """R3T-1."""
    body = (BODY[0], BODY[1], OWN_BODY.format("02.11.2026"), BODY[3])
    rival = notice_rival(blank(**COMPLETE), [page(*TOP, "Datum: 06.11.2026", *body, NOTIFIED)])
    assert rival is not None and rival.spec.anchor_date == "2026-11-02"


def test_two_own_dates_weeks_apart_start_the_notice_at_the_later_never_a_passed_one() -> None:
    """R3T-1."""
    body = (BODY[0], BODY[1], OWN_BODY.format("01.06.2026"), BODY[3])
    pages = [page(*TOP, "Datum: 06.11.2026", *body, NOTIFIED)]
    rival = notice_rival(blank(**COMPLETE), pages)
    assert rival is not None and rival.spec.anchor_date == "2026-11-06"
    got, computed = objection_due(pages, THREE_MONTHS)
    assert got == NOTIFIED_DUE and computed.notice


def test_a_formally_served_notice_from_notification_gets_no_delivery_days_beside_a_reading() -> None:
    """R3T-3."""
    pages = [page(*HEAD[:4], "Per Postzustellungsurkunde", *HEAD[4:], NOTIFIED, WHERE)]
    got, computed = objection_due(pages, THREE_MONTHS)
    assert got == FROM_LETTER_DUE and computed.notice


def test_a_portal_notice_is_never_given_the_post_s_days_beside_a_reading() -> None:
    """R3T-3."""
    portal = [page(*HEAD, NOTIFIED, "Dieser Bescheid wurde Ihnen zum Abruf bereitgestellt.")]
    got, computed = objection_due(portal, THREE_MONTHS)
    assert computed.notice and got is not None and got < NOTIFIED_DUE
    assert objection_due([page(*HEAD, NOTIFIED, WHERE)], THREE_MONTHS)[0] == NOTIFIED_DUE


ZWEITWOHNUNG = (
    "Stadt Beispielhausen · Steueramt · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Datum: 06.11.2026",
    "Zweitwohnungsteuerbescheid 2026",
    "Sehr geehrte Frau Probe,",
    "mit diesem Bescheid setzen wir die Zweitwohnungsteuer für Ihre Wohnung auf 480,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
    SERVED,
)


def test_a_word_of_a_law_kind_alone_never_bears_it_out() -> None:
    """R3T-5: a tax decision on a "Wohnung" read as a landlord's notice is no letter of that kind."""
    pages = [page(*ZWEITWOHNUNG)]
    reading = blank(
        kind="authority_letter",
        high_stakes_kind="landlord_notice",
        **COMPLETE,
        items=[objection(THREE_MONTHS, quote=SERVED)],
    )
    assert notice_rival(reading, pages) is not None
    empty = blank(
        kind="authority_letter", high_stakes_kind="landlord_notice", sender=SENDER, document_date="2026-11-06"
    )
    assert reading_gap(empty, pages, remedy_notices(pages)) == "remedy_left_out"


def test_a_dismissal_needs_both_its_words() -> None:
    """R3T-5."""
    fee = (
        "Die Kündigung Ihres Stellplatzes nehmen wir zur Kenntnis; die Gebühr setzen wir auf 85,00 EUR fest."
    )
    pages = [page(*ZWEITWOHNUNG[:5], fee, "Rechtsbehelfsbelehrung", SERVED)]
    empty = blank(
        kind="authority_letter", high_stakes_kind="dismissal", sender=SENDER, document_date="2026-11-06"
    )
    assert reading_gap(empty, pages, remedy_notices(pages)) == "remedy_left_out"


def test_a_reading_with_the_notice_s_period_from_a_later_arrival_stays_unflagged() -> None:
    """R3T-4: the notice's own period from a later confirmed arrival, five days after the notice's date."""
    spec = {"type": "relative", "amount": 1, "unit": "months", "anchor": "receipt"}
    reading = reading_with(objection(spec))
    [verified] = verify_extraction("doc_x", reading, [page(*HEAD, NOTIFIED, WHERE)], check_reading=True).items
    ctx = replace(ctx_for(reading), received_date=date(2026, 11, 12), received_confirmed=True)
    computed = compute_item(verified, ctx, postal_buffer_days=3)
    assert computed.due_date == "2026-12-14" and not computed.conflict and not computed.notice


def test_a_month_read_for_four_weeks_is_set_beside_it_within_the_reach() -> None:
    """R3T-4: "vier Wochen" read as a month ends three days later — a longer period, set beside it."""
    four = "Gegen diesen Bescheid kann innerhalb von vier Wochen nach Zustellung Einspruch eingelegt werden."
    spec = {"type": "relative", "amount": 1, "unit": "months", "anchor": "receipt", "delivery_rule": "none"}
    got, computed = objection_due([page(*HEAD, four, WHERE)], spec, quote=four)
    assert got == "2026-12-04" and computed.notice


def test_an_arrival_the_person_did_not_confirm_never_moves_a_served_notice_later() -> None:
    """R3T-4 (defensive: every context the app builds confirms an arrival it has)."""
    spec = {"type": "relative", "amount": 3, "unit": "months", "anchor": "receipt"}
    reading = reading_with(objection(spec, quote=SERVED))
    [verified] = verify_extraction("doc_x", reading, [page(*HEAD, SERVED, WHERE)], check_reading=True).items
    ctx = replace(ctx_for(reading), received_date=date(2026, 11, 20), received_confirmed=False)
    computed = compute_item(verified, ctx, postal_buffer_days=3)
    assert computed.due_date == "2026-11-20" and computed.notice


def test_a_notice_addressed_to_your_objection_with_how_to_lodge_it_is_live() -> None:
    """R3T-7."""
    line = (
        "Ihren Widerspruch können Sie binnen eines Monats schriftlich bei der Stadt Beispielhausen einlegen."
    )
    assert fires([page(*HEAD, line)])


@pytest.mark.parametrize(
    "line",
    [
        "Der Widerspruch der Nachbarin ist am 05.10.2026 bei uns eingegangen; wir entscheiden innerhalb von vier Wochen.",
        "Da dieses Schreiben keinen Bescheid enthält, kann ein Widerspruch innerhalb eines Monats nicht erhoben werden.",
        "Wird über Ihren Antrag nicht binnen drei Monaten entschieden, ist eine Klage (Untätigkeitsklage) zulässig.",
        "Sollten wir Ihrem Antrag nicht folgen, können Sie gegen den dann ergehenden Bescheid innerhalb eines Monats Widerspruch erheben.",
        "Die Angaben sind widersprüchlich; bitte erläutern Sie sie innerhalb von zwei Wochen.",
    ],
)
def test_no_live_notice(line: str) -> None:
    """R3T-9 (the court action for inaction as the verifier wrote it: "Untätigkeitsklage" alone names no remedy)."""
    assert not fires([page(*HEAD[:-1], line)])


@pytest.mark.parametrize(
    "line",
    [
        "Der Widerspruch ist nach Zugang dieses Schreibens, spätestens 10 Tage vor dem Termin am 20.11.2026, einzulegen.",
        "An objection must be lodged after receipt of this letter and up to two weeks before the hearing.",
    ],
)
def test_a_notice_with_a_forward_start_and_a_backward_period_still_fires(line: str) -> None:
    """V3T-1: live (counted from this letter), though undated (counted back from a hearing)."""
    assert fires([page(*HEAD, line)])


# --------------------------------------------------------------------------------------------------
# The letter's own date (dates D3-1, D3-2, D3-7, M1; security R3ADV-1, -2, -3, -7, -8)
# --------------------------------------------------------------------------------------------------

ADDRESS = ("Frau Mara Probe", "Probeweg 2", "12345 Beispielhausen")
FEE = (
    "Gebührenbescheid",
    "Sehr geehrte Frau Probe,",
    "wir setzen die Gebühr auf 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
)
NOTICE = "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
#: That notice from a letter dated Fri 6 Nov 2026: delivered Mon 9 Nov, due Wed 9 Dec.
NOTICE_DUE = "2026-12-09"


@pytest.mark.parametrize(
    "own",
    [
        ("06.11.2026",),
        ("Beispielhausen, 06.11.2026",),
        ("Beispielhausen, Freitag, 06.11.2026",),
        ("Ihr Zeichen   Unser Zeichen   Datum", "", "AB-1   ST-22   06.11.2026"),
    ],
)
def test_the_date_line_after_the_address_is_the_letter_s_own(own: tuple[str, ...]) -> None:
    """Dates review 3, D3-2: DIN 5008's date line under the recipient's address (a date alone, a place and date,
    the reference line with a blank line between) is the letter's own — so the notice is set beside a reading's
    planted three months (it wasn't for 18 of 95 recorded letters)."""
    pages = [page(LETTERHEAD, *ADDRESS, "", *own, *FEE, NOTICE)]
    assert _own_start(pages) == date(2026, 11, 6)
    got, computed = objection_due(pages, THREE_MONTHS, quote=NOTICE)
    assert got == NOTICE_DUE and computed.notice


def test_a_town_on_a_river_is_no_due_word() -> None:
    """D3-2: "Frankfurt am Main, den 06.11.2026" is a place and date ("am" is no appointment's)."""
    lines = (LETTERHEAD, "Frau Mara Probe", "Probeweg 2", "60311 Frankfurt am Main", "")
    assert _own_start([page(*lines, "Frankfurt am Main, den 06.11.2026", *FEE, NOTICE)]) == date(2026, 11, 6)


def test_a_print_date_never_sets_a_later_start_when_the_own_date_is_unread() -> None:
    """D3-1: the letter's own date joined to the street line (as a two-column PDF reads) is unread; a later
    "Druckdatum" then gave 2026-12-16 for 12-09 — now it only lowers a start, at worst undated."""
    lines = (
        LETTERHEAD,
        "Frau Mara Probe",
        "Probeweg 2   06.11.2026",
        "12345 Beispielhausen",
        "Druckdatum: 13.11.2026",
    )
    got = check_due([page(*lines, *FEE, NOTICE)])
    assert got is None or got <= NOTICE_DUE


@pytest.mark.parametrize(
    "notice",
    [
        "Gegen den Bescheid über Wohngeld für die Zeit vom 01.12.2026 bis 30.11.2027 kann innerhalb eines Monats "
        "nach Bekanntgabe Widerspruch erhoben werden.",
        "Gegen diesen Bescheid über den Bewilligungszeitraum vom 01.12.2026 bis 30.11.2027 kann innerhalb eines "
        "Monats nach Bekanntgabe Widerspruch erhoben werden.",
        "Gegen den Bescheid über die Bewilligung von Leistungen vom 01.12.2026 an kann innerhalb eines Monats nach "
        "Bekanntgabe Widerspruch erhoben werden.",
    ],
)
def test_a_period_the_notice_names_is_never_the_decision_s_date(notice: str) -> None:
    """D3-7, security R3ADV-2: "für die Zeit vom 01.12.2026", "Bewilligungszeitraum vom", "vom 01.12.2026 an"
    start a benefit period, not the decision — never a strong date (2027-01-04 for 12-09)."""
    [found] = remedy_notices([page(*HEAD, notice)])
    assert date(2026, 12, 1) not in found.issued
    for lines in ((*HEAD, notice), (LETTERHEAD, "Frau Mara Probe", "Probeweg 2   06.11.2026", *FEE, notice)):
        got = check_due([page(*lines)])
        assert got is None or got <= NOTICE_DUE


@pytest.mark.parametrize(
    "lines",
    [
        ("Unser Zeichen   Datum", "Zahlbar bis 04.12.2026"),
        ("Unser Zeichen   Datum", "ST-22   Fällig am 04.12.2026"),
    ],
)
def test_a_due_day_under_the_reference_labels_is_no_letter_date(lines: tuple[str, ...]) -> None:
    """Dates M1: the reference line's date counts only without a due word before it on its line."""
    assert letter_date(blank(), [page(LETTERHEAD, *ADDRESS, "", *lines, *FEE, NOTICE)]) is None


@pytest.mark.parametrize(
    "layout",
    [
        ("Probeweg 2   06.11.2026", "Einladung", "Ihr Termin:", "Datum: 01.12.2026", "Uhrzeit: 09:00 Uhr"),
        ("Probeweg 2   06.11.2026", "12345 Beispielhausen", "Meldeaufforderung"),
    ],
)
def test_an_appointment_s_date_is_never_the_letter_s(layout: tuple[str, ...]) -> None:
    """Security R3ADV-1: an appointment's "Datum:" line — in the header's block ("Ihr Termin:" / "Uhrzeit") or in
    the body — gave a start weeks after the letter's (2027-01-04, 2026-11-16 for 12-09)."""
    body = (
        "Sehr geehrte Frau Probe,",
        "bitte kommen Sie zu folgendem Termin:",
        "Datum: 01.12.2026",
        "Uhrzeit: 09:00 Uhr",
        "mit diesem Bescheid fordern wir Sie dazu auf.",
        "Rechtsbehelfsbelehrung",
        NOTICE,
    )
    pages = [
        page(
            "Jobcenter Beispielhausen · Musterstraße 1 · 12345 Beispielhausen",
            "Frau Erika Probe",
            *layout,
            *body,
        )
    ]
    assert check_due(pages) is None
    assert not [
        statement for statement in letter_statements(pages) if statement.letter_date == date(2026, 12, 1)
    ]


def test_the_letter_s_own_datum_beside_an_appointment_block_is_its_date() -> None:
    """R3ADV-1: the letter's own "Datum:" above an appointment block still dates it."""
    lines = (
        "Jobcenter Beispielhausen · Musterstraße 1 · 12345 Beispielhausen",
        "Frau Erika Probe",
        "Datum: 06.11.2026",
        "Einladung",
        "Ihr Termin:",
        "Datum: 01.12.2026",
        "Uhrzeit: 09:00 Uhr",
        "Sehr geehrte Frau Probe,",
        "mit diesem Bescheid fordern wir Sie auf, zu dem Termin zu erscheinen.",
        "Rechtsbehelfsbelehrung",
        NOTICE,
    )
    assert check_due([page(*lines)]) == NOTICE_DUE


OBJECTION_DECISION = (
    "Landkreis Beispielkreis · Rechtsamt · Kreisweg 2 · 12345 Beispielhausen",
    *ADDRESS,
)
OLD_DECISION = (
    "Gegen den Bescheid vom 20.09.2026 in der Gestalt, die er durch diesen Widerspruchsbescheid gefunden hat, kann "
    "innerhalb eines Monats nach Zustellung Klage beim Verwaltungsgericht Beispielhausen erhoben werden."
)


def test_the_decision_an_objection_decision_reshapes_never_dates_its_court_action() -> None:
    """Security R3ADV-3: a Widerspruchsbescheid dated only by a bare date gave a court deadline from the old
    decision's 20.09 (2026-10-20, already past): now no start."""
    body = (
        "Widerspruchsbescheid",
        "Sehr geehrte Frau Probe,",
        "Ihr Widerspruch wird zurückgewiesen.",
        "Rechtsbehelfsbelehrung",
    )
    assert check_due([page(*OBJECTION_DECISION, "06.11.2026", *body, OLD_DECISION)]) in (None, "2026-12-07")


def test_a_start_after_the_letter_arrived_is_none() -> None:
    """Security R3ADV-7: a letter dated after the day it arrived (a misprint, a post-dated letter)."""
    lines = (*TOP, "Datum: 20.11.2026", *BODY, NOTIFIED)
    assert letter_date(blank(), [page(*lines)], today=date(2026, 11, 10)) is None
    assert letter_date(blank(), [page(*lines)], today=date(2026, 11, 20)) == date(2026, 11, 20)


def test_an_english_date_label_counts_only_as_the_whole_label() -> None:
    """Security R3ADV-8: "Effective date: 01.01.2027" is no letter's date ("Date:" is)."""
    assert letter_date(blank(), [page(*TOP, "Effective date: 01.01.2027", *BODY, NOTIFIED)]) is None
    assert letter_date(blank(), [page(*TOP, "Date: 06.11.2026", *BODY, NOTIFIED)]) == date(2026, 11, 6)


# --------------------------------------------------------------------------------------------------
# Which notices count, and how (dates D3-3..D3-6; security R3ADV-4, -5, -6, -9, M1)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "notice",
    [
        "Gegen diesen Bescheid kann innerhalb eines Monats schriftlich vor dem Bayerischen Verwaltungsgericht "
        "München Klage erhoben werden.",
        "Gegen diesen Bescheid kann Klage innerhalb eines Monats vor dem örtlich zuständigen Sozialgericht erhoben "
        "werden.",
    ],
)
def test_before_a_court_named_with_its_adjectives_stays_forward(notice: str) -> None:
    """D3-3: "vor dem Bayerischen Verwaltungsgericht" is where the action is brought, not a period counted back."""
    assert check_due([page(*HEAD, notice)]) == FROM_LETTER_DUE


def test_a_week_before_a_hearing_at_a_court_stays_counted_back() -> None:
    """D3-3: "eine Woche vor dem Termin beim Amtsgericht" counts back from a hearing: never dated forward."""
    notice = (
        "Ein Einspruch ist spätestens eine Woche vor dem Termin beim Amtsgericht Beispielhausen einzulegen."
    )
    assert check_due([page(*HEAD, notice)]) is None


@pytest.mark.parametrize(
    ("tip", "due"),
    [
        ("Wir empfehlen, das Schreiben einige Tage vor Fristablauf abzusenden.", "2026-12-09"),
        ("Wir empfehlen, den Widerspruch spätestens eine Woche vor Fristablauf abzusenden.", None),
    ],
)
def test_a_tip_counted_back_from_the_deadline_is_never_folded_into_the_notice(
    tip: str, due: str | None
) -> None:
    """D3-4: a tip after a notice with its own period ("einige Tage vor Fristablauf absenden") left the notice
    undated; one naming the remedy and a number of its own stays a notice that can't be dated (never a week from
    the letter)."""
    assert check_due([page(*HEAD, NOTICE, tip)]) == due


def test_of_two_notices_the_earliest_counts_whatever_their_start() -> None:
    """D3-6: a month from notification (deemed delivery) and a month from service: the latter ends first."""
    klage = (
        "Alternativ kann innerhalb eines Monats nach Zustellung Klage beim Verwaltungsgericht erhoben werden."
    )
    got, computed = objection_due([page(*HEAD, NOTICE, klage)], LATE, quote=NOTICE)
    assert got == FROM_LETTER_DUE and computed.notice


def _served(arrived: date) -> Any:
    """A notice from notification on a letter served formally (Postzustellungsurkunde), a reading counting a
    month from the arrival, and the arrival the person entered."""
    pages = [page(*HEAD[:4], "Per Postzustellungsurkunde", *HEAD[4:], NOTICE, WHERE)]
    spec = {"type": "relative", "amount": 1, "unit": "months", "anchor": "receipt", "delivery_rule": "none"}
    reading = reading_with(objection(spec, quote=NOTICE))
    [verified] = verify_extraction("doc_x", reading, pages, check_reading=True).items
    ctx = replace(ctx_for(reading), received_date=arrived, received_confirmed=True)
    return compute_item(verified, ctx, postal_buffer_days=3)


def test_a_formally_served_notice_keeps_the_letter_s_date_beside_a_late_arrival() -> None:
    """Later audit, round 4, R4L-1 (round 3's D3-5 undone): an arrival 10 days after the letter's date may be the
    pickup after a deposit at the post office, or "today" saved weeks later, while the yellow envelope's date is
    earlier — the notice counted from the letter's date is kept, the earlier, and the to-do is "Please check"
    (2026-12-07, never 2026-12-16)."""
    computed = _served(date(2026, 11, 16))
    assert computed.due_date == "2026-12-07" and computed.conflict and computed.notice


def test_a_formally_served_notice_within_reach_of_the_letter_s_date_keeps_the_arrival() -> None:
    """R4L-1: an arrival within the reach of the notice's date stands (2026-12-10, no second date)."""
    computed = _served(date(2026, 11, 10))
    assert computed.due_date == "2026-12-10" and not computed.conflict


LIST_ABOVE = (
    "Bitte beachten Sie:",
    "- Sollten wir Rückfragen haben, melden wir uns bei Ihnen",
    "- Gegen einen späteren Änderungsbescheid ist gesondert Widerspruch möglich",
)


def test_list_lines_without_a_full_stop_above_the_notice_heading_never_switch_it_off() -> None:
    """Security R3ADV-4: list lines above "Rechtsbehelfsbelehrung" ran into the notice's sentence and their words
    ("sollten wir", "späteren …bescheid") made it not live — a silent miss."""
    pages = [page(*HEAD[:-1], *LIST_ABOVE, "Rechtsbehelfsbelehrung", NOTICE)]
    assert fires(pages)
    assert check_due(pages, blank(**COMPLETE, items=[payment()])) == "2026-12-09"


def test_a_list_line_s_period_above_the_heading_never_moves_a_correct_reading_earlier() -> None:
    """Security R3ADV-5: a list line's "innerhalb von zwei Wochen" above the heading is no period of the notice's
    beside a correct reading (a false "Please check" two weeks early)."""
    lines = ("Bitte beachten Sie:", "- Wenn Sie umziehen, teilen Sie uns dies innerhalb von zwei Wochen mit")
    pages = [page(*HEAD[:-1], *lines, "Rechtsbehelfsbelehrung", NOTICE)]
    got, computed = objection_due(pages, ONE_MONTH, quote=NOTICE)
    assert got == "2026-12-09" and not computed.conflict


@pytest.mark.parametrize(
    "line",
    [
        "Telefonisch können Sie keinen Widerspruch einlegen; er muss innerhalb eines Monats nach Bekanntgabe "
        "schriftlich erhoben werden.",
        "Per E-Mail können Sie keinen Widerspruch einlegen; der Widerspruch ist innerhalb eines Monats nach "
        "Bekanntgabe schriftlich einzulegen.",
    ],
)
def test_a_way_of_sending_ruled_out_before_the_verb_leaves_the_notice_live(line: str) -> None:
    """Security R3ADV-6."""
    assert fires([page(*HEAD[:-1], "Rechtsbehelfsbelehrung", line)])


def test_a_hearing_sent_by_post_that_rules_the_objection_out_stays_silent() -> None:
    """R3ADV-6: the way the hearing was sent is no way of lodging an objection."""
    line = (
        "Gegen diese per Post versandte Anhörung können Sie keinen Widerspruch einlegen, Sie können sich aber "
        "innerhalb von zwei Wochen äußern."
    )
    hearing = (
        LETTERHEAD,
        "Frau Mara Probe",
        "Datum: 09.11.2026",
        "Anhörung nach § 28 VwVfG",
        "Sehr geehrte Frau Probe,",
    )
    assert not fires([page(*hearing, line)])


def test_an_action_for_annulment_is_a_court_action() -> None:
    """Security R3ADV-9: "Anfechtungsklage" is a Klage: the to-do says so (never "send your objection")."""
    notice = (
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung Anfechtungsklage beim Verwaltungsgericht "
        "Beispielhausen erhoben werden."
    )
    found = check_item(blank(), [page(*HEAD, notice)])
    assert found is not None and found.remedy == "klage" and found.item.date.type == "relative"


@pytest.mark.parametrize(
    "line",
    [
        "Sie können der Lastschrift innerhalb von acht Wochen nach der Belastung widersprechen.",
        "Sie haben das Recht, einer Lastschrift innerhalb von acht Wochen zu widersprechen.",
    ],
)
def test_the_account_holder_s_right_against_a_direct_debit_is_no_notice(line: str) -> None:
    """Security M1 (round 3): a cash office's direct-debit letter citing the tax decision, read completely, got a
    false "left out the deadline to object"."""
    lines = (
        LETTERHEAD,
        "Frau Mara Probe",
        "Datum: 06.11.2026",
        "Grundsteuer 2027 – Einzug per Lastschrift",
        "Sehr geehrte Frau Probe,",
        "die mit Grundsteuerbescheid vom 15.01.2026 festgesetzte Grundsteuer ziehen wir am 15.02.2027 ein.",
        line,
    )
    assert not fires([page(*lines)])


# --------------------------------------------------------------------------------------------------
# False alarms and silent misses (false positives R3FP-1..7, V-1)
# --------------------------------------------------------------------------------------------------

MUSTER = ("Herrn", "Max Mustermann", "Lindenweg 7", "12345 Musterstadt")


def _fee_reminder(*body: str) -> list[Any]:
    """A cash office's payment reminder of 25.09 restating, without a date, the notice of a decision of 03.09."""
    return [
        page(
            "Stadt Musterstadt · Stadtkasse · Rathausplatz 1 · 12345 Musterstadt",
            *MUSTER,
            "Datum: 25.09.2026",
            "Zahlungserinnerung",
            "Sehr geehrter Herr Mustermann,",
            *body,
            "Bitte zahlen Sie die Gebühr von 85,00 EUR bis zum 09.10.2026.",
            "Hinweis: Gegen den Gebührenbescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben "
            "werden.",
        )
    ]


@pytest.mark.parametrize(
    "body",
    [
        (
            "mit Gebührenbescheid vom 03.09.2026 haben wir eine Gebühr von 85,00 EUR festgesetzt, die noch offen ist.",
        ),
        ("mit Gebührenbescheid vom", "03.09.2026 haben wir eine Gebühr von 85,00 EUR festgesetzt."),
    ],
)
def test_a_reminder_restating_another_decision_s_notice_is_never_dated_from_the_reminder(
    body: tuple[str, ...],
) -> None:
    """False positives R3FP-1: the decision of 03.09 allows 2026-10-07; counted from the reminder's 25.09 it was
    2026-10-28 — now the decision's date the letter gives elsewhere (also wrapped) counts: undated or earlier."""
    for reading in (blank(), blank(sender=SENDER, document_date="2026-09-25", items=[payment()])):
        got = check_due(_fee_reminder(*body), reading)
        assert got is None or got <= "2026-10-07"


def test_this_decision_keeps_its_date_beside_another_decision_it_names() -> None:
    """R3FP-1: a notice on this letter ("Gegen diesen Bescheid") keeps the letter's date, whatever older decision
    its body names."""
    body = "mit diesem Bescheid heben wir den Bewilligungsbescheid vom 12.03.2026 auf."
    pages = [page(*TOP, "Datum: 06.11.2026", BODY[0], BODY[1], body, BODY[3], NOTICE)]
    assert check_due(pages) == "2026-12-09"


@pytest.mark.parametrize(
    "line",
    [
        "Trotz eines Widerspruchs ist der Betrag innerhalb von zwei Wochen zu zahlen.",
        "Die Gebühr für diesen Widerspruchsbescheid von 60,00 EUR ist innerhalb von zwei Wochen nach Zustellung zu "
        "zahlen.",
        "Bitte zahlen Sie die mit Widerspruchsbescheid vom 15.07.2026 festgesetzten Kosten von 50,00 EUR innerhalb "
        "von zwei Wochen.",
    ],
)
def test_a_payment_instruction_naming_a_remedy_is_no_notice(line: str) -> None:
    """R3FP-2: a sentence that only says when to pay is no notice: no false check, no two dates beside a correct
    reading (10-26 became 10-05, low, flagged)."""
    assert not [notice for notice in remedy_notices([page(*HEAD[:-1], line)]) if notice.live]
    got, computed = objection_due([page(*HEAD, NOTIFIED, line)], ONE_MONTH)
    assert got == "2026-12-09" and not computed.conflict


@pytest.mark.parametrize(
    "line",
    [
        "Gegen diesen Zahlungsbescheid ist innerhalb eines Monats nach Bekanntgabe der Widerspruch möglich.",
        "Ein Widerspruch gegen die Festsetzung des Betrages ist innerhalb eines Monats nach Bekanntgabe möglich.",
    ],
)
def test_a_notice_about_paying_still_fires(line: str) -> None:
    """R3FP-2: notices whose words speak of payment but say how to object ("möglich") still count."""
    assert fires([page(*HEAD[:-1], line)])


def test_a_public_body_s_decision_without_the_word_bescheid_still_fires() -> None:
    """R3FP-3: a health insurer's refusal names "diese Entscheidung" and "nach Erhalt", no "Bescheid" — the check
    fired on no reading that left the objection out."""
    lines = (
        "Beispiel BKK · Kassenweg 1 · 12345 Musterstadt",
        *MUSTER,
        "Datum: 24.09.2026",
        "Ihr Antrag auf Kostenübernahme für einen Elektrorollstuhl",
        "Sehr geehrter Herr Mustermann,",
        "leider können wir die Kosten für den beantragten Elektrorollstuhl nicht übernehmen.",
        "Ihr Widerspruchsrecht",
        "Gegen diese Entscheidung können Sie innerhalb eines Monats nach Erhalt dieses Schreibens Widerspruch "
        "einlegen.",
    )
    insurer = ExtractedParty(name="Beispiel BKK", kind="health_insurer")
    assert fires([page(*lines)], sender=insurer, document_date="2026-09-24")


def test_a_letter_headed_bescheid_alone_still_fires() -> None:
    """R3FP-3: a bare heading "Bescheid" is an administrative act's."""
    lines = (
        *TOP,
        "Datum: 06.11.2026",
        "Bescheid",
        "Sehr geehrte Frau Probe,",
        "die Gebühr beträgt 85,00 EUR.",
    )
    notice = "Hiergegen kann innerhalb eines Monats nach Zustellung Widerspruch erhoben werden."
    assert fires([page(*lines, notice)])


@pytest.mark.parametrize(
    "notice",
    [
        "Wenn Sie Widerspruch erheben, muss dieser innerhalb eines Monats nach Bekanntgabe bei uns eingehen.",
        "Ihren Widerspruch senden Sie bitte innerhalb eines Monats an die Stadt Musterstadt, Rathausplatz 1.",
    ],
)
def test_a_notice_phrased_as_a_condition_or_an_instruction_still_fires(notice: str) -> None:
    """R3FP-4: "Wenn Sie Widerspruch erheben, muss dieser …" refers back to the remedy; "Ihren Widerspruch senden
    Sie …" says how to lodge it."""
    assert fires([page(*HEAD, notice)])


def test_documents_for_the_person_s_own_objection_are_no_notice() -> None:
    """R3FP-4: "senden Sie" alone is no way of lodging an objection."""
    line = "Zur Begründung Ihres Widerspruchs senden Sie uns bitte innerhalb von vier Wochen die ärztlichen Unterlagen."
    assert not fires([page(*HEAD, line)])


def test_a_condition_on_a_lodged_remedy_with_this_letter_s_start_never_moves_a_correct_reading() -> None:
    """R3FP-4 (security round 2, F3): its period is another's, even counted "nach Erhalt dieses Schreibens"."""
    line = (
        "Wenn Sie Widerspruch einlegen, reichen Sie die Unterlagen bitte innerhalb von drei Wochen nach Erhalt "
        "dieses Schreibens nach."
    )
    got, computed = objection_due([page(*HEAD, NOTIFIED, line)], ONE_MONTH)
    assert got == "2026-12-09" and not computed.conflict


@pytest.mark.parametrize(
    "line",
    [
        "Der Widerspruch sollte innerhalb von vier Wochen nach Bekanntgabe begründet werden.",
        "Der Widerspruch ist innerhalb von zwei Wochen nach seiner Einlegung zu begründen.",
    ],
)
def test_a_period_for_the_reasons_never_moves_a_correct_reading_earlier(line: str) -> None:
    """R3FP-5: a period for giving reasons is no period for lodging (10-26 became 10-22, low, flagged)."""
    got, computed = objection_due([page(*HEAD, NOTIFIED, line)], ONE_MONTH)
    assert got == "2026-12-09" and not computed.conflict


@pytest.mark.parametrize(
    "line",
    [
        "Gegen eine Ablehnung könnten Sie dann innerhalb eines Monats Widerspruch einlegen.",
        "Bitte äußern Sie sich innerhalb von zwei Wochen; ein Widerspruch ist erst gegen den Bescheid möglich.",
    ],
)
def test_a_hypothetical_remedy_is_no_notice(line: str) -> None:
    """R3FP-6."""
    assert not fires([page(*HEAD, line)])


def test_an_empty_reading_of_a_letter_without_a_live_notice_says_read_it_yourself() -> None:
    """R3FP-7: a pension information ruling the objection out got "Deadline to object" with a date."""
    lines = (
        "Deutsche Rentenversicherung Musterland · 12300 Musterstadt",
        *MUSTER,
        "Datum: 15.09.2026",
        "Renteninformation 2026",
        "Sehr geehrter Herr Mustermann,",
        "Diese Renteninformation ist kein Bescheid. Ein Widerspruch ist daher nicht möglich.",
        "Bitte melden Sie uns fehlende Zeiten innerhalb von vier Wochen.",
    )
    found = check_item(blank(), [page(*lines)])
    assert found is not None and found.kind == "read_yourself" and found.item.date.type == "none"


@pytest.mark.parametrize(
    "reasons",
    [
        "Der Widerspruch ist zulässig; er wurde insbesondere innerhalb der Monatsfrist des § 70 Abs. 1 VwGO erhoben.",
        "Ihr Widerspruch ist verfristet; er hätte innerhalb eines Monats nach Bekanntgabe erhoben werden müssen.",
    ],
)
def test_after_an_objection_decision_a_court_action_names_the_to_do(reasons: str) -> None:
    """False positives V-1: the reasons of a Widerspruchsbescheid speak of the objection's period; only a court
    action is left, so it names the to-do on a tie ("send your objection" would stop nothing)."""
    klage = (
        "Gegen den Bescheid vom 02.06.2026 in Gestalt dieses Widerspruchsbescheides kann innerhalb eines Monats "
        "nach Zustellung Klage beim Verwaltungsgericht Musterstadt erhoben werden."
    )
    lines = (
        "Landkreis Musterkreis · Kreisrechtsausschuss · Kreisweg 2 · 12345 Musterstadt",
        *MUSTER,
        "Datum: 22.09.2026",
        "Widerspruchsbescheid",
        "Sehr geehrter Herr Mustermann,",
        "Ihr Widerspruch vom 01.07.2026 wird zurückgewiesen.",
        "Gründe",
        reasons,
        "Rechtsbehelfsbelehrung",
        klage,
    )
    found = check_item(blank(), [page(*lines)])
    assert found is not None and found.remedy == "klage"


# --------------------------------------------------------------------------------------------------
# The letter's own date, fuzzed: never a start later than the letter's date (dates review 3)
# --------------------------------------------------------------------------------------------------


def _d(day: date) -> str:
    return day.strftime("%d.%m.%Y")


FUZZ_SENDER = "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen"
FUZZ_ADDRESS = ["Frau Mara Probe", "Probeweg 2", "12345 Beispielhausen"]
#: Where a letter prints its own date (each a realistic header).
FUZZ_LAYOUTS = {
    "datum": lambda d: [FUZZ_SENDER, *FUZZ_ADDRESS, "", f"Datum: {_d(d)}"],
    "din": lambda d: [FUZZ_SENDER, *FUZZ_ADDRESS, "", _d(d)],
    "din2col": lambda d: [f"{FUZZ_SENDER}   Amtl. Kennzeichen", "BX-1", *FUZZ_ADDRESS, "", _d(d)],
    "bdatum2c": lambda d: [f"{FUZZ_SENDER}   Bescheiddatum", _d(d), *FUZZ_ADDRESS, ""],
    "ref3": lambda d: [
        FUZZ_SENDER,
        *FUZZ_ADDRESS,
        "",
        "Ihr Zeichen   Unser Zeichen   Datum",
        f"AB-1   ST-22   {_d(d)}",
    ],
    "place": lambda d: [FUZZ_SENDER, *FUZZ_ADDRESS, "", f"Beispielhausen, {_d(d)}"],
    "placeFfm": lambda d: [FUZZ_SENDER, *FUZZ_ADDRESS, "", f"Frankfurt am Main, den {_d(d)}"],
    "place2c": lambda d: [
        f"{FUZZ_SENDER}   Amtl. Kennzeichen",
        "BX-1",
        *FUZZ_ADDRESS,
        "",
        f"Beispielhausen, {_d(d)}",
    ],
    "weekday": lambda d: [FUZZ_SENDER, *FUZZ_ADDRESS, "", f"Beispielhausen, Freitag, {_d(d)}"],
    "refPDF": lambda d: [
        FUZZ_SENDER,
        *FUZZ_ADDRESS,
        "",
        "Ihr Zeichen Unser Zeichen Datum",
        "",
        f"AB-1 ST-22 {_d(d)}",
    ],
    "refnotlast": lambda d: [
        FUZZ_SENDER,
        *FUZZ_ADDRESS,
        "",
        "Unser Zeichen   Datum   Telefon",
        f"ST-22   {_d(d)}   0123-4567",
    ],
}
#: Another date the letter prints near its header: a due day, a print date, an appointment, an application's.
FUZZ_DISTRACTORS = {
    "stichtag": lambda x: ["Stichtag", _d(x)],
    "zahlbar": lambda x: [f"Zahlbar bis Freitag, {_d(x)}"],
    "bearb": lambda x: [f"Bearbeitungsdatum: {_d(x)}"],
    "druck": lambda x: [f"Druckdatum {_d(x)}"],
    "buchung": lambda x: [f"Buchungsdatum: {_d(x)}"],
    "antrag": lambda x: ["Ihr Antrag vom", _d(x)],
    "bareblank": lambda x: ["", _d(x)],
    "ortstermin": lambda x: ["Ortstermin:", f"Beispielhausen, {_d(x)}"],
    "zustellung": lambda x: [f"Datum der Zustellung: {_d(x)}"],
    "termin": lambda x: [f"Termin am Montag, {_d(x)}"],
    "gueltig": lambda x: [f"Gültig ab {_d(x)}"],
    "hauptv": lambda x: ["Hauptveranlagung auf den", _d(x)],
    "placeX": lambda x: [f"Musterdorf, {_d(x)}"],
    "postX": lambda x: ["54321 Anderstadt", "", _d(x)],
    "mitbesch": lambda x: [f"Mit diesem Bescheid vom {_d(x)} setzen wir die Gebühr fest."],
}
FUZZ_OFFSETS = [-40, -20, -15, -14, -7, -1, 1, 7, 14, 15, 30]
FUZZ_BODY = [
    "",
    "Gebührenbescheid",
    "",
    "Sehr geehrte Frau Probe,",
    "",
    "wir setzen die Gebühr auf 85,00 EUR fest.",
    "",
    "Rechtsbehelfsbelehrung",
    "Gegen diesen Bescheid können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
]


def test_a_fuzzed_header_never_gives_a_start_later_than_the_letter_s_date() -> None:
    """Dates review 3, D3-1: a letter dated ``d`` (any day of 2026–2027) in one of eleven header layouts, with a
    distracting date before or after its own (a due day, a print date, an appointment, an application's …),
    ``offset`` days from it: the check's start (:func:`letter_date`) is never later than ``d``. The notice's start
    (:func:`_own_start`) is later only by its documented rule — two dates the first page names as its own, more
    than :data:`LETTER_DATE_SPAN` days apart, give the later (never a passed one), and the notice then only ever
    lowers the reading's date. A bounded, seeded sample of the full fuzz (297,660 cases: 13,120 later check starts
    at 9f38220, none now)."""
    rng = random.Random(20261002)
    later: list[tuple[str, str, str, int, date, date | None, date | None]] = []
    for _ in range(3000):
        d = date(2026, 1, 1) + timedelta(days=rng.randrange(730))
        layout, distractor = rng.choice(list(FUZZ_LAYOUTS)), rng.choice(list(FUZZ_DISTRACTORS))
        offset, before = rng.choice(FUZZ_OFFSETS), rng.random() < 0.5
        head, other = FUZZ_LAYOUTS[layout](d), FUZZ_DISTRACTORS[distractor](d + timedelta(days=offset))
        lines = [*other, *head] if before else [*head, *other]
        pages = [page(*lines, *FUZZ_BODY)]
        start, own = letter_date(blank(), pages), _own_start(pages)
        if (start is not None and start > d) or (own is not None and own > d and offset <= LETTER_DATE_SPAN):
            later.append((layout, distractor, "before" if before else "after", offset, d, start, own))
    assert later == []


def test_the_notice_s_two_dates_say_which_is_the_reading_s() -> None:
    """UX review 3, R3UX-5: beside the letter's own notice the other date is Claude's reading's — never "the
    letter also gives" or "the date as read from the letter"."""
    got, computed = objection_due([page(*HEAD, NOTIFIED, WHERE)], THREE_MONTHS)
    assert got == "2026-12-09" and computed.notice and computed.receipt is not None
    assert "Claude's reading also gives" in computed.receipt.summary
    assert "The letter also gives" not in computed.receipt.summary
    labels = [step.label for step in computed.receipt.steps]
    assert any(label.startswith("Claude's reading gives") for label in labels)
    assert not any(label.startswith("The date as read from the letter") for label in labels)
