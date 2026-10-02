"""Verification, confidence grading and writing items by slot (SPEC § 8 stages 5–7, § 21)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest

from ordnung.db.store import Store
from ordnung.ingest.gaps import CHECK_SLOT
from ordnung.ingest.link import LinkResult
from ordnung.ingest.plan import (
    ComputedDate,
    activity_message,
    compute_item,
    consistency_reasons,
    end_date_grounding,
    for_item,
    grade_receipt,
    needs_check,
    payment_details,
    remedy_text,
    remedy_warnings,
    rent_increase_note,
    rule_context,
    slot_key,
    slot_keys,
    square_iban_claims,
    verify_extraction,
    write_items,
)
from ordnung.ingest.text import Word
from ordnung.ingest.verify import (
    DATE_NOT_IN_QUOTE,
    DAY_OF_MONTH_NOT_IN_QUOTE,
    MODEL_READ_NOTE,
    REASON_TEXT,
    UNVERIFIED_NOTE,
    WORKING_DAY_NOT_IN_QUOTE,
    PageInput,
)
from ordnung.models import (
    ComputationReceipt,
    Document,
    DocumentExtraction,
    Evidence,
    ExtractedChange,
    ExtractedItem,
    Item,
    PaymentDetails,
    Profile,
    Recurrence,
    Remedy,
)
from ordnung.rules import RuleContext
from ordnung.rules.advice import RENT_INCREASE_PAYMENT_WARNING
from ordnung.secretary.scam import invalid_iban_message

PAGE_TEXT = (
    "Musterstadt, 15.09.2026\n"
    "Bitte zahlen Sie 49,99 EUR bis zum 15.10.2026.\n"
    "Der Einspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen."
)
TEXT_PAGE = (1, PAGE_TEXT, [], "text")
TRANSCRIPT_PAGE = (1, PAGE_TEXT, [], "transcript")


def item(quote: str, *, kind: str = "payment", money: float | None = None, **date_spec: Any) -> ExtractedItem:
    spec = date_spec or {"type": "none"}
    return ExtractedItem.model_validate(
        {"kind": kind, "title": "t", "date": spec, "amount": money, "quote": quote}
    )


PAYMENT = item(
    "Bitte zahlen Sie 49,99 EUR bis zum 15.10.2026.",
    money=49.99,
    type="fixed",
    date="2026-10-15",
    nature="payment",
)
OBJECTION = item(
    "Der Einspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen.",
    kind="deadline",
    type="relative",
    amount=1,
    unit="months",
    anchor="deemed_delivery",
    delivery_rule="de_admin_post",
    nature="objection",
)


def extraction(items: list[ExtractedItem], **fields: Any) -> DocumentExtraction:
    return DocumentExtraction(
        kind="invoice", title="Bill", summary="s", explanation="e", items=items, **fields
    )


# --------------------------------------------------------------------------------------------------
# Slot keys
# --------------------------------------------------------------------------------------------------


def test_slot_key_ignores_case_and_spacing_but_not_kind() -> None:
    assert slot_key("payment", "Bitte  zahlen\nSie") == slot_key("payment", "bitte zahlen sie")
    assert slot_key("payment", "x") != slot_key("deadline", "x")


def test_repeated_items_get_distinct_slots() -> None:
    keys = slot_keys([PAYMENT, PAYMENT, OBJECTION])
    assert keys[1] == f"{keys[0]}#2"
    assert len(set(keys)) == 3


# --------------------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------------------


def test_items_found_on_a_text_page_are_verified() -> None:
    result = verify_extraction("doc_x", extraction([PAYMENT, OBJECTION]), [TEXT_PAGE])
    assert [v.evidence.grounding for v in result.items] == ["verified", "verified"]
    assert all(v.evidence.value_consistent for v in result.items)
    assert not result.needs_review
    assert result.warnings == []


def test_transcript_pages_give_model_read() -> None:
    result = verify_extraction("doc_x", extraction([PAYMENT]), [TRANSCRIPT_PAGE])
    assert result.items[0].evidence.grounding == "model_read"
    assert not result.needs_review


def test_unfound_or_inconsistent_dated_items_need_review() -> None:
    wrong_amount = PAYMENT.model_copy(update={"amount": 59.99})
    result = verify_extraction("doc_x", extraction([wrong_amount]), [TEXT_PAGE])
    assert result.items[0].reasons == ("amount_not_in_quote",)
    assert not result.items[0].evidence.value_consistent
    assert result.needs_review

    missing = item("Zahlen Sie 10,00 EUR bis zum 01.11.2026.", type="fixed", date="2026-11-01")
    result = verify_extraction("doc_x", extraction([missing]), [TEXT_PAGE])
    assert result.items[0].evidence.grounding == "unverified"
    assert result.needs_review
    # no "Please check:" before it: the letter's page shows it under that heading (UI audit R1-backend-7)
    assert result.warnings == ["1 date could not be confirmed against the letter's text."]


def test_undated_items_never_need_review() -> None:
    task = item("Ein Satz, der nicht im Brief steht.", kind="task")
    assert not verify_extraction("doc_x", extraction([task]), [TEXT_PAGE]).needs_review


RENT_BY_WORKING_DAY = "Die Miete ist spätestens am dritten Werktag eines jeden Monats zu zahlen."
RENT_IN_ADVANCE = "Die Miete ist monatlich im Voraus zu zahlen."
LEASE_PAGE = (1, f"Monatliche Miete: 640,00 EUR\n{RENT_BY_WORKING_DAY}\n{RENT_IN_ADVANCE}", [], "text")


def rent(quote: str, working_day: int | None) -> ExtractedItem:
    """A lease's monthly rent as a reading gives it: no date of its own, its amount on the line above."""
    reading = item(quote, money=640.0, type="none", nature="payment")
    return reading.model_copy(update={"recurrence": Recurrence(working_day=working_day)})


def test_a_working_day_its_quote_names_is_consistent() -> None:
    """The reviewer's check: "spätestens am dritten Werktag" names the working day the reading gives (3)."""
    [verified] = verify_extraction("doc_x", extraction([rent(RENT_BY_WORKING_DAY, 3)]), [LEASE_PAGE]).items
    assert verified.reasons == () and verified.evidence.value_consistent
    assert verified.dated and not verified.needs_check  # dated by its working day, and it checks out
    assert consistency_reasons(rent(RENT_BY_WORKING_DAY, None), [LEASE_PAGE]) == ()  # no working day read


NO_DAY_LEASE_PAGE = (1, f"Monatliche Miete: 640,00 EUR\n{RENT_IN_ADVANCE}", [], "text")


@pytest.mark.parametrize(
    ("quote", "working_day", "page"),
    [
        (RENT_IN_ADVANCE, 3, NO_DAY_LEASE_PAGE),  # the letter names no working day at all
        (RENT_IN_ADVANCE, 1, LEASE_PAGE),  # the letter names another working day (the 3rd)
        (RENT_BY_WORKING_DAY, 1, LEASE_PAGE),  # the quote names another working day
    ],
)
def test_a_working_day_its_quote_does_not_name_needs_a_check(
    quote: str, working_day: int, page: tuple[int, str, list[Any], str]
) -> None:
    """The working day is the reading's claim about the item's sentence: one the sentence doesn't name — nor
    the letter's sentence about when the rent is due (:func:`test_a_due_day_the_letter_states_elsewhere_is_
    grounded_on_that_sentence`) — is ``working_day_not_in_quote``, so the value is not consistent with its
    quote and the letter says a date could not be confirmed ("Please check"); its receipt is graded one level
    lower, with the reason's note."""
    result = verify_extraction("doc_x", extraction([rent(quote, working_day)]), [page])
    [verified] = result.items
    assert verified.reasons == (WORKING_DAY_NOT_IN_QUOTE,)
    assert not verified.evidence.value_consistent and verified.evidence.grounding == "verified"
    assert result.needs_review
    assert result.warnings == ["1 date could not be confirmed against the letter's text."]
    receipt = grade_receipt(ComputationReceipt(due_date="2026-10-05", confidence="high"), verified)
    assert receipt.confidence == "medium" and receipt.warnings == [REASON_TEXT[WORKING_DAY_NOT_IN_QUOTE]]


RENT_ON_THE_FIRST = "Die Miete ist monatlich im Voraus, spätestens zum 1. eines Monats zu zahlen."
DAY_PAGE = (1, f"Monatliche Miete: 640,00 EUR\n{RENT_ON_THE_FIRST}\n{RENT_IN_ADVANCE}", [], "text")


def test_a_day_of_the_month_is_graded_like_a_working_day() -> None:
    """Point 10 of ``ordnung.recurrence``: a reading's day of the month dates the rent, so the item is dated
    and its quote must name that day ("zum 1. eines Monats"); another day, or a sentence without one (when the
    letter states another day), is ``day_of_month_not_in_quote`` ("Please check", one level lower). A day beside
    a working day is not the rule's (the working day wins), so it is not graded."""
    on_the_first = rent(RENT_ON_THE_FIRST, None).model_copy(update={"recurrence": Recurrence(day_of_month=1)})
    [verified] = verify_extraction("doc_x", extraction([on_the_first]), [DAY_PAGE]).items
    assert verified.reasons == () and verified.dated and not verified.needs_check
    for quote, day in ((RENT_ON_THE_FIRST, 15), (RENT_IN_ADVANCE, 15)):
        misread = rent(quote, None).model_copy(update={"recurrence": Recurrence(day_of_month=day)})
        result = verify_extraction("doc_x", extraction([misread]), [DAY_PAGE])
        assert result.items[0].reasons == (DAY_OF_MONTH_NOT_IN_QUOTE,) and result.needs_review
        receipt = grade_receipt(ComputationReceipt(due_date="2026-10-01", confidence="high"), result.items[0])
        assert receipt.confidence == "medium" and receipt.warnings == [REASON_TEXT[DAY_OF_MONTH_NOT_IN_QUOTE]]
    both = rent(RENT_BY_WORKING_DAY, None).model_copy(
        update={"recurrence": Recurrence(working_day=3, day_of_month=1)}
    )
    assert consistency_reasons(both, [LEASE_PAGE]) == ()


TICKET_PRICE = "Preis   63,00 € pro Monat"
TICKET_DEBIT = "Zahlungsweise   SEPA-Lastschrift, Abbuchung zum Monatsanfang, Gläubiger-ID"
TICKET_NOTICE = "Die Kündigung muss bis zum 10. eines Monats zum Ende dieses Monats bei uns eingehen."


def ticket_page(*lines: str, source: str = "text") -> tuple[int, str, list[Word], str]:
    """A page with a box per word (one text line per line), as the text layer gives it."""
    words = [
        Word(word, 0.1 * column, 0.05 * row, 0.1 * column + 0.08, 0.05 * row + 0.03)
        for row, line in enumerate(lines)
        for column, word in enumerate(line.split())
    ]
    return (1, "\n".join(lines), words, source)


def ticket(day: int | None = 1, *, working_day: int | None = None) -> ExtractedItem:
    """The demo's Deutschlandticket as its reading gives it: the price line quoted, the debit's day not."""
    reading = item(TICKET_PRICE, money=63.0, type="none", nature="payment")
    return reading.model_copy(update={"recurrence": Recurrence(day_of_month=day, working_day=working_day)})


@pytest.mark.parametrize("source", ["text", "transcript"])
def test_a_due_day_the_letter_states_elsewhere_is_grounded_on_that_sentence(source: str) -> None:
    """A monthly debit whose quote (the price line) doesn't name its day, while the letter's payment terms do
    ("Abbuchung zum Monatsanfang": the 1st, the reading's day): the day counts as stated, and that sentence
    is the to-do's evidence too, grounded as any quote is (boxes on a text page, ``model_read`` on a
    transcript) — no "Please check", no unconfirmed date, the receipt keeps its grade. The notice period's
    "bis zum 10. eines Monats" is no payment's day."""
    page = ticket_page(TICKET_PRICE, TICKET_DEBIT, TICKET_NOTICE, source=source)
    result = verify_extraction("doc_x", extraction([ticket()]), [page])
    [verified] = result.items
    assert verified.reasons == () and verified.evidence.value_consistent
    assert verified.dated and not verified.needs_check and not result.needs_review
    assert result.warnings == []
    day = verified.day_evidence
    assert day is not None and day.quote == " ".join(TICKET_DEBIT.split()) and day.value_consistent
    grounding = "verified" if source == "text" else "model_read"
    assert day.grounding == grounding and day.page == 1 and bool(day.boxes) == (source == "text")
    assert verified.all_evidence == [verified.evidence, day]
    receipt = grade_receipt(ComputationReceipt(due_date="2026-10-01", confidence="high"), verified)
    assert receipt.warnings == ([] if source == "text" else [MODEL_READ_NOTE])
    assert consistency_reasons(ticket(), [page]) == ()  # recomputing its dates grades it the same way


def test_a_working_day_the_letter_states_elsewhere_is_grounded_on_that_sentence() -> None:
    [verified] = verify_extraction("doc_x", extraction([rent(RENT_IN_ADVANCE, 3)]), [LEASE_PAGE]).items
    assert verified.reasons == () and not verified.needs_check
    assert verified.day_evidence is not None and verified.day_evidence.quote == RENT_BY_WORKING_DAY
    assert verified.day_evidence.grounding == "verified"


@pytest.mark.parametrize(
    ("lines", "reading", "reason"),
    [
        # the letter states no day
        ((TICKET_PRICE, TICKET_NOTICE), ticket(), DAY_OF_MONTH_NOT_IN_QUOTE),
        # the letter states another day than the reading's
        ((TICKET_PRICE, TICKET_DEBIT, TICKET_NOTICE), ticket(15), DAY_OF_MONTH_NOT_IN_QUOTE),
        # the letter states a day of the month, the reading a working day
        ((TICKET_PRICE, TICKET_DEBIT), ticket(None, working_day=1), WORKING_DAY_NOT_IN_QUOTE),
        # the letter states two different days: which one is the reading's?
        (
            (TICKET_PRICE, TICKET_DEBIT, "Die Servicegebühr wird jeweils zum 15. eines Monats abgebucht."),
            ticket(),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
        # the reading's day, but in a sentence that is not about paying: a tenant's duty, a count, moving in,
        # an installation, late fees from that day on, a contract's end
        (
            (TICKET_PRICE, "Der Mieter hat den Zählerstand bis zum 15. eines Monats zu melden."),
            ticket(15),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
        (
            (TICKET_PRICE, "Die Anzahl der Fahrten ist bis zum 15. eines Monats zu melden."),
            ticket(15),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
        (
            (TICKET_PRICE, "Der Einzug in die Wohnung erfolgt zum 15. des Monats."),
            ticket(15),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
        (
            (TICKET_PRICE, "Die Installation erfolgt am 3. Werktag."),
            ticket(None, working_day=3),
            WORKING_DAY_NOT_IN_QUOTE,
        ),
        (
            (TICKET_PRICE, "Mahngebühren werden ab dem 15. eines Monats fällig."),
            ticket(15),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
        (
            (TICKET_PRICE, "Ihr Vertrag endet zum Monatsende, der Beitrag wird monatlich abgebucht."),
            ticket(31),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
        # the reading's day in a sentence that names a sum but pays nothing (reviewer repro), or after a word
        # that makes it a bound ("nach der Monatsmitte")
        (
            (TICKET_PRICE, "Den neuen Rechnungsbetrag teilen wir Ihnen jeweils zur Monatsmitte mit."),
            ticket(15),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
        (
            (TICKET_PRICE, "Der Abschlag wird nach der Monatsmitte abgebucht."),
            ticket(15),
            DAY_OF_MONTH_NOT_IN_QUOTE,
        ),
    ],
)
def test_a_due_day_the_letter_does_not_state_alone_still_needs_a_check(
    lines: tuple[str, ...], reading: ExtractedItem, reason: str
) -> None:
    result = verify_extraction("doc_x", extraction([reading]), [ticket_page(*lines)])
    [verified] = result.items
    assert verified.reasons == (reason,) and verified.day_evidence is None and verified.needs_check
    assert result.warnings == ["1 date could not be confirmed against the letter's text."]
    assert consistency_reasons(reading, [ticket_page(*lines)]) == (reason,)


PREMIUM_DEBIT = "Der nächste Jahresbeitrag in Höhe von 59,90 € wird am 01.12.2026 von Ihrem Konto abgebucht."
PREMIUM_DUE = "Hauptfälligkeit   01.12. eines jeden Jahres"


def premium(quote: str = PREMIUM_DEBIT, day: int = 1) -> ExtractedItem:
    """A yearly premium as its reading gives it: the next debit's date, due on that day every year."""
    reading = item(quote, money=59.9, type="fixed", date="2026-12-01", nature="payment")
    return reading.model_copy(update={"recurrence": Recurrence(interval=1, unit="years", day_of_month=day)})


def test_a_day_the_letter_states_as_a_schedule_of_dates_is_confirmed() -> None:
    """A day of the month the letter states as a schedule of dates counts as stated: in the quote (quarterly
    dates on the 10th), or in the letter's sentence about when a yearly premium is due ("01.12. eines jeden
    Jahres", then the to-do's evidence too); the quote's single debit date alone never is."""
    quarterly = "Die Vorauszahlungen betragen 300,00 € (fällig jeweils am 10.03., 10.06., 10.09. und 10.12.)."
    advance = item(quarterly, money=300.0, type="fixed", date="2026-03-10", nature="payment").model_copy(
        update={"recurrence": Recurrence(interval=3, unit="months", day_of_month=10)}
    )
    [verified] = verify_extraction("doc_x", extraction([advance]), [ticket_page(quarterly)]).items
    assert verified.reasons == () and not verified.needs_check and verified.day_evidence is None
    page = ticket_page(PREMIUM_DUE, PREMIUM_DEBIT)
    result = verify_extraction("doc_x", extraction([premium()]), [page])
    [verified] = result.items
    assert verified.reasons == () and not verified.needs_check and not result.needs_review
    assert verified.day_evidence is not None and verified.day_evidence.grounding == "verified"
    assert verified.day_evidence.quote == " ".join(PREMIUM_DUE.split())
    assert consistency_reasons(premium(), [page]) == ()
    for lines, reading in (
        ((PREMIUM_DEBIT,), premium()),  # the letter states the date of one debit only
        ((PREMIUM_DUE, PREMIUM_DEBIT), premium(day=15)),  # another day than the letter's
    ):
        [verified] = verify_extraction("doc_x", extraction([reading]), [ticket_page(*lines)]).items
        assert verified.reasons == (DAY_OF_MONTH_NOT_IN_QUOTE,) and verified.needs_check


MONTHLY_ON_1ST = Recurrence(day_of_month=1)
YEARLY_ON_1ST = Recurrence(interval=1, unit="years", day_of_month=1)


@pytest.mark.parametrize(
    ("quote", "rule"),
    [
        ("Ihre Gesamtmiete beträgt ab dem 01.11.2026 somit 670,00 € monatlich.", MONTHLY_ON_1ST),
        ("Your new monthly rent of 670.00 EUR is payable from 1 November 2026.", MONTHLY_ON_1ST),
        (
            "Die Miete von 670,00 € ist ab dem 01.11.2026 monatlich zu zahlen, erstmals am 01.12.2026.",
            MONTHLY_ON_1ST,
        ),
        # beside a clause number, which reads like a date without a year
        (
            "Gemäß Ziffer 1.3. der AVB ist der Jahresbeitrag von 670,00 € ab dem 01.11.2026 fällig.",
            YEARLY_ON_1ST,
        ),
        # a start in other words, with yearly wording after it or a recurring one before it
        ("Versicherungsbeginn 01.11.2026 jährlich 670,00 EUR", YEARLY_ON_1ST),
        ("Der Beitrag von 670,00 € ist erstmals jeweils am 01.11.2026 fällig.", MONTHLY_ON_1ST),
        # beside the contract's end, or the invoice's date, on the same day of the month
        (
            "Der Vertrag beginnt am 01.11.2026 und endet am 01.11.2028; Beitrag monatlich 670,00 €.",
            MONTHLY_ON_1ST,
        ),
        ("Rechnungsdatum 01.10.2026, Monatsbeitrag 670,00 € fällig am 01.11.2026.", MONTHLY_ON_1ST),
        # a one-off deadline in "each … by" wording
        ("Please return each form by 1 November 2026; the monthly fee is 670.00 EUR.", MONTHLY_ON_1ST),
    ],
)
def test_a_single_start_date_is_never_the_recurring_day(quote: str, rule: Recurrence) -> None:
    """A day of the month read from the date a schedule starts on (the extraction prompt forbids it) stays
    unconfirmed ("Please check"), even beside another date on that day or a clause number."""
    reading = item(quote, money=670.0, type="fixed", date="2026-11-01", nature="payment").model_copy(
        update={"recurrence": rule}
    )
    result = verify_extraction("doc_x", extraction([reading]), [ticket_page(quote)])
    [verified] = result.items
    assert verified.reasons == (DAY_OF_MONTH_NOT_IN_QUOTE,) and verified.needs_check and result.needs_review


@pytest.mark.parametrize(
    "stated",
    [
        "Die Beitragszahlung richtet sich nach Ziffer 1.4. der Allgemeinen Bedingungen.",
        "Versicherungsbeginn 01.11. / Jahresbeitrag 670,00 €",
    ],
)
def test_a_start_date_or_clause_number_elsewhere_is_no_due_day(stated: str) -> None:
    """A yearly premium's day read from its start date is not confirmed by another payment sentence of the
    letter citing a clause number or giving the start without a year: no day evidence, "Please check"."""
    quote = "Der Jahresbeitrag beträgt ab dem 01.11.2026 670,00 €."
    reading = item(quote, money=670.0, type="fixed", date="2026-11-01", nature="payment").model_copy(
        update={"recurrence": YEARLY_ON_1ST}
    )
    result = verify_extraction("doc_x", extraction([reading]), [ticket_page(quote, stated)])
    [verified] = result.items
    assert verified.reasons == (DAY_OF_MONTH_NOT_IN_QUOTE,) and verified.day_evidence is None
    assert verified.needs_check and result.needs_review


FEE_TERMS = (
    "Der Rundfunkbeitrag ist monatlich geschuldet und jeweils in der Mitte eines Dreimonatszeitraums für drei "
    "Monate zu zahlen (§ 7 Abs. 3 Rundfunkbeitragsstaatsvertrag)."
)
FEE_DUE = "Der Betrag von 55,08 € für den Zeitraum 10.2026 bis 12.2026 ist fällig am 15.11.2026."
EVERY_QUARTER_ON_15TH = Recurrence(interval=3, unit="months", day_of_month=15)


def fee(*, rule: Recurrence = EVERY_QUARTER_ON_15TH, quote: str = FEE_DUE, **date_spec: Any) -> ExtractedItem:
    """The demo's broadcasting fee as its reading gives it: the due date's sentence quoted, every three months
    on the 15th."""
    spec = date_spec or {"type": "fixed", "date": "2026-11-15", "nature": "payment"}
    return item(quote, money=55.08, **spec).model_copy(update={"recurrence": rule})


def test_the_middle_of_each_three_month_period_confirms_a_quarterly_15th() -> None:
    """§ 7 Abs. 3 RBStV's "in der Mitte eines Dreimonatszeitraums" states the 15th of each period's middle month
    (§§ 189, 192 BGB): the letter's terms vouch for the reading's day — every three months from 15.11.2026 —
    and become the to-do's evidence; no "Please check" (the demo's letter 16)."""
    page = ticket_page(FEE_TERMS, FEE_DUE)
    result = verify_extraction("doc_x", extraction([fee()]), [page])
    [verified] = result.items
    assert verified.reasons == () and not verified.needs_check and not result.needs_review
    assert verified.day_evidence is not None and verified.day_evidence.quote == FEE_TERMS
    assert verified.day_evidence.grounding == "verified"
    assert consistency_reasons(fee(), [page]) == ()  # recomputing its dates grades it the same way


@pytest.mark.parametrize(
    "reading",
    [
        # every month: no quarter's middle
        fee(rule=Recurrence(interval=1, unit="months", day_of_month=15)),
        # a first date off the middle
        fee(type="fixed", date="2026-11-01", nature="payment"),
        # no first date
        fee(type="relative", amount=2, unit="weeks", anchor="document_date", nature="payment"),
    ],
)
def test_the_middle_of_each_quarter_confirms_no_other_reading(reading: ExtractedItem) -> None:
    page = ticket_page(FEE_TERMS, FEE_DUE)
    [verified] = verify_extraction("doc_x", extraction([reading]), [page]).items
    assert DAY_OF_MONTH_NOT_IN_QUOTE in verified.reasons and verified.day_evidence is None
    assert verified.needs_check


FEE_TABLE = "10.2026 – 12.2026   18,36 €   55,08 €   15.11.2026"


@pytest.mark.parametrize("quote", [FEE_DUE, FEE_TERMS])
@pytest.mark.parametrize("first", ["2026-10-15", "2026-12-15", "2027-01-15"])
def test_the_middle_of_a_period_is_anchored_on_the_letters_own_due_date(quote: str, first: str) -> None:
    """Reviewer repro: a reading a month or two off the letter's due date (15.11.2026) is a 15th too, but no
    middle the letter states — the phrase says nothing of which months make the periods, so only a first
    date the letter writes anchors them (``first_date_written``). "Please check", whichever sentence it
    quotes."""
    page = ticket_page(FEE_TERMS, FEE_TABLE, FEE_DUE)
    reading = fee(quote=quote, type="fixed", date=first, nature="payment")
    [verified] = verify_extraction("doc_x", extraction([reading]), [page]).items
    assert DAY_OF_MONTH_NOT_IN_QUOTE in verified.reasons and verified.day_evidence is None
    assert verified.needs_check
    [written] = verify_extraction("doc_x", extraction([fee(quote=quote)]), [page]).items
    assert written.reasons == () and not written.needs_check


QUARTER_MIDDLE = "Der Abschlag von 55,08 € ist jeweils zur Quartalsmitte fällig, erstmals am 15.02.2027."


@pytest.mark.parametrize(
    ("first", "confirmed"), [("2027-02-15", True), ("2027-05-15", False), ("2027-08-15", False)]
)
def test_the_middle_of_each_quarter_is_anchored_on_the_date_the_letter_writes(
    first: str, confirmed: bool
) -> None:
    """Reviewer repro: "zur Quartalsmitte …, erstmals am 15.02.2027" vouches for a quarterly 15th from
    15.02.2027 only, not for one read from 15.05.2027 or 15.08.2027 (each a quarter's middle, too)."""
    reading = fee(quote=QUARTER_MIDDLE, type="fixed", date=first, nature="payment")
    [verified] = verify_extraction("doc_x", extraction([reading]), [ticket_page(QUARTER_MIDDLE)]).items
    assert verified.needs_check is not confirmed
    assert (DAY_OF_MONTH_NOT_IN_QUOTE in verified.reasons) is not confirmed


def test_a_recurring_date_counts_as_stated_only_on_its_quotes_schedule() -> None:
    """A recurring item's date its quote doesn't write is excused as an occurrence of the schedule from a date
    the quote writes (15.02.2027, three months after "fällig am 15.11.2026"), never one off it (15.12.2026, a
    month after it); a quote without a date leaves the month to the reading
    (``test_fixed_date_stated_elsewhere_and_recurring_schedules_are_not_flagged``)."""
    page = ticket_page(FEE_TERMS, FEE_DUE)
    on = fee(type="fixed", date="2027-02-15", nature="payment")
    off = fee(type="fixed", date="2026-12-15", nature="payment")
    assert DATE_NOT_IN_QUOTE not in consistency_reasons(on, [page])
    assert DATE_NOT_IN_QUOTE in consistency_reasons(off, [page])
    monthly = fee(
        rule=Recurrence(interval=1, unit="months", day_of_month=15), type="fixed", date="2026-12-15"
    )
    assert DATE_NOT_IN_QUOTE not in consistency_reasons(monthly, [page])  # a month on, every month


def test_quarter_ends_one_may_cancel_by_are_no_due_days() -> None:
    """Reviewer repro: notice dates on the quarter ends are no schedule of the 31st (no due wording)."""
    quote = "Der Vertrag ist zum 31.03., 30.06., 30.09. oder 31.12. kündbar; der Abschlag beträgt 300,00 €."
    reading = item(quote, money=300.0, type="fixed", date="2026-12-31", nature="payment").model_copy(
        update={"recurrence": Recurrence(interval=3, unit="months", day_of_month=31)}
    )
    [verified] = verify_extraction("doc_x", extraction([reading]), [ticket_page(quote)]).items
    assert DAY_OF_MONTH_NOT_IN_QUOTE in verified.reasons and verified.needs_check


QUARTER_ENDS = "Die Abschläge von 300,00 € sind am 31.03., 30.06., 30.09. und 31.12. fällig."


@pytest.mark.parametrize(("day", "first", "confirmed"), [(31, "2026-12-31", True), (30, "2026-12-30", False)])
def test_quarter_ends_state_the_last_day_of_the_month(day: int, first: str, confirmed: bool) -> None:
    """Quarter ends confirm a reading of the 31st (each month's last day), and no longer the 30th, which
    two of them share (30.06., 30.09.): it would date March and December on the 30th."""
    advance = item(QUARTER_ENDS, money=300.0, type="fixed", date=first, nature="payment").model_copy(
        update={"recurrence": Recurrence(interval=3, unit="months", day_of_month=day)}
    )
    [verified] = verify_extraction("doc_x", extraction([advance]), [ticket_page(QUARTER_ENDS)]).items
    assert verified.needs_check is not confirmed
    assert verified.reasons == (() if confirmed else (DAY_OF_MONTH_NOT_IN_QUOTE,))


def test_a_list_with_a_date_on_another_day_confirms_no_day() -> None:
    """A list of quarterly dates with one on another day (14.07. among the 15ths) states no schedule on the
    15th: the reading's 15th would be a day late in July, so it stays "Please check"."""
    quote = "Die Raten von 300,00 € sind jeweils am 15.01., 15.04., 14.07. und 15.10. fällig."
    reading = item(quote, money=300.0, type="fixed", date="2027-01-15", nature="payment").model_copy(
        update={"recurrence": EVERY_QUARTER_ON_15TH}
    )
    [verified] = verify_extraction("doc_x", extraction([reading]), [ticket_page(quote)]).items
    assert verified.reasons == (DAY_OF_MONTH_NOT_IN_QUOTE,) and verified.needs_check


def test_the_middle_of_the_month_confirms_the_15th() -> None:
    quote = "Die Miete von 640,00 € ist monatlich bis zur Monatsmitte zu zahlen."
    reading = rent(quote, None).model_copy(update={"recurrence": Recurrence(day_of_month=15)})
    [verified] = verify_extraction("doc_x", extraction([reading]), [ticket_page(quote)]).items
    assert verified.reasons == () and not verified.needs_check


def test_key_facts_contract_and_remedy_quotes_are_grounded() -> None:
    data = extraction(
        [],
        key_facts=[{"label": "Amount", "value": "49.99", "quote": "Bitte zahlen Sie 49,99 EUR"}],
        remedy={"type": "einspruch", "quote": "Das steht nirgends im Brief."},
        contract={"name": "c", "quotes": ["Der Einspruch ist innerhalb eines Monats"]},
    )
    result = verify_extraction("doc_x", data, [TEXT_PAGE])
    assert result.key_facts[0].evidence is not None and result.key_facts[0].evidence.grounding == "verified"
    assert result.contract_evidence[0].grounding == "verified"
    assert result.remedy_evidence is not None and result.remedy_evidence.grounding == "unverified"
    assert any("Rechtsbehelfsbelehrung" in warning for warning in result.warnings)


# --------------------------------------------------------------------------------------------------
# Compute & grading
# --------------------------------------------------------------------------------------------------


def verified_item(extracted: ExtractedItem, page: tuple[int, str, list[Any], str] = TEXT_PAGE) -> Any:
    return verify_extraction("doc_x", extraction([extracted]), [page]).items[0]


def test_grading_keeps_high_for_verified_consistent_items() -> None:
    receipt = ComputationReceipt(due_date="2026-10-15", confidence="high")
    graded = grade_receipt(receipt, verified_item(PAYMENT))
    assert graded.confidence == "high" and graded.warnings == []


def test_grading_lowers_for_model_read_and_unverified() -> None:
    receipt = ComputationReceipt(due_date="2026-10-15", confidence="high")
    photo = grade_receipt(receipt, verified_item(PAYMENT, TRANSCRIPT_PAGE))
    assert photo.confidence == "medium" and photo.warnings == [MODEL_READ_NOTE]
    lost = item("Nicht im Brief: 01.11.2026", type="fixed", date="2026-11-01")
    unverified = grade_receipt(receipt.model_copy(update={"confidence": "medium"}), verified_item(lost))
    assert unverified.confidence == "low"
    assert UNVERIFIED_NOTE in unverified.warnings


def test_ambiguous_dates_are_always_low() -> None:
    page = (1, "Please pay by 03/05/2027.", [], "text")
    ambiguous = item("Please pay by 03/05/2027.", type="fixed", date="2027-05-03")
    graded = grade_receipt(ComputationReceipt(due_date="2027-05-03"), verified_item(ambiguous, page))
    assert graded.confidence == "low"
    assert any("two ways" in warning for warning in graded.warnings)


def test_compute_item_sources() -> None:
    ctx = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 15), delivery_scope="ao")
    fixed = compute_item(verified_item(PAYMENT), ctx, postal_buffer_days=4)
    assert (fixed.due_date, fixed.source) == ("2026-10-15", "fixed")
    computed = compute_item(verified_item(OBJECTION), ctx, postal_buffer_days=4)
    assert (computed.due_date, computed.source) == ("2026-10-21", "computed")
    undated = compute_item(
        verified_item(item("Bitte zahlen Sie 49,99 EUR", kind="task")), ctx, postal_buffer_days=4
    )
    assert undated == ComputedDate(receipt=None, due_date=None, send_by=None, source="none")


def test_a_payment_made_in_person_is_stored_without_a_send_by_day() -> None:
    """UI audit R1-backend-8: the residence permit's 100 € fee, paid by girocard at the appointment, was
    stored with a bank transfer's send-by day ("transfer by 13 Oct"). Its words say it is paid on site
    (``pays_on_site``), so its date is computed without one; a transfer keeps its day."""
    ctx = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 15))
    on_site = PAYMENT.model_copy(
        update={"action": "Pay the €100 fee on site at the appointment by girocard."}
    )
    computed = compute_item(verified_item(on_site), for_item(ctx, on_site, None), postal_buffer_days=4)
    assert (computed.due_date, computed.send_by) == ("2026-10-15", None)
    assert computed.receipt is not None and "bgb_675s" not in computed.receipt.rule_ids
    transfer = PAYMENT.model_copy(update={"action": "Transfer 49,99 EUR to the account below."})
    kept = compute_item(verified_item(transfer), for_item(ctx, transfer, None), postal_buffer_days=4)
    assert (kept.due_date, kept.send_by) == ("2026-10-15", "2026-10-14")


def test_a_collected_or_incoming_payment_is_stored_without_a_send_by_day() -> None:
    """Walkthrough of phase 2: the Deutschlandticket's direct debit (due Thu 1 Oct) was stored with a bank
    transfer's send-by day, Wed 30 Sep, which the daily note then called its date. Nobody transfers money the
    sender collects or money that comes in (``is_collected_or_incoming``): the due day is the day."""
    ctx = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 15))
    debit = PAYMENT.model_copy(
        update={"title": "Monatliche Abbuchung Deutschlandticket", "action": "Keep €63 in your account."}
    )
    computed = compute_item(verified_item(debit), for_item(ctx, debit, None), postal_buffer_days=4)
    assert (computed.due_date, computed.send_by) == ("2026-10-15", None)
    assert computed.receipt is not None and "bgb_675s" not in computed.receipt.rule_ids
    incoming = PAYMENT.model_copy(update={"direction": "in", "title": "Salary"})
    paid_in = compute_item(verified_item(incoming), for_item(ctx, incoming, None), postal_buffer_days=4)
    assert (paid_in.due_date, paid_in.send_by) == ("2026-10-15", None)
    # a direct debit that failed is paid by transfer again: it keeps its day
    failed = debit.model_copy(update={"action": "Die Lastschrift wurde zurückgegeben: bitte überweisen."})
    kept = compute_item(verified_item(failed), for_item(ctx, failed, None), postal_buffer_days=4)
    assert kept.send_by == "2026-10-14"


def test_a_payment_by_standing_order_keeps_its_send_by_day() -> None:
    """The demo's €670 rent: "Adjust your standing order to the new total rent unless you use direct debit".
    The standing order is the person's own transfer (``ordnung.payments.asks_for_transfer``), so the rent
    keeps a transfer's send-by day; "direct debit" named as the alternative once made it collected, without
    one. A standing order the person is told to cancel, because the payee now collects, gets none."""
    ctx = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 15))
    rent = PAYMENT.model_copy(
        update={
            "title": "New monthly total rent €670",
            "action": "Adjust your standing order to the new total rent unless you use direct debit.",
        }
    )
    kept = compute_item(verified_item(rent), for_item(ctx, rent, None), postal_buffer_days=4)
    assert (kept.due_date, kept.send_by) == ("2026-10-15", "2026-10-14")
    collected = rent.model_copy(update={"action": "Cancel your standing order: the rent is now debited."})
    computed = compute_item(verified_item(collected), for_item(ctx, collected, None), postal_buffer_days=4)
    assert (computed.due_date, computed.send_by) == ("2026-10-15", None)


def test_rule_context_from_party_and_document(store: Store) -> None:
    party = store.add_party(name="Finanzamt", kind="tax_office", region="BY")
    document = store.add_document(
        sha256="d" * 64, filename="x", mime="application/pdf", file_path="x", received_date="2026-09-20"
    )
    ctx = rule_context(
        party, document, extraction([], document_date="2026-09-15"), date(2026, 9, 25), recipient_region="NW"
    )
    assert ctx.region == "BY" and ctx.recipient_region == "NW" and ctx.delivery_scope == "ao"
    assert ctx.document_date == date(2026, 9, 15)
    assert ctx.received_date == date(2026, 9, 20) and ctx.received_confirmed
    fallback = rule_context(
        None,
        document.model_copy(update={"received_date": None}),
        extraction([], sender={"name": "AOK", "kind": "health_insurer"}),
        date(2026, 9, 25),
    )
    assert fallback.delivery_scope == "sgbx" and fallback.region is None and not fallback.received_confirmed


def test_rule_context_marks_a_private_sender_but_not_an_unknown_one(store: Store) -> None:
    """A company's letter has no deemed delivery (the engine counts it from arrival); a party of kind
    ``other`` is the app's "don't know" and keeps the earliest plausible deemed delivery; a sender filed
    as an insurer whose remedy notice names a Widerspruch against a Bescheid is an authority's decision,
    an employer's letter naming the Kündigungsschutzklage is not."""
    document = store.add_document(sha256="f" * 64, filename="x", mime="application/pdf", file_path="x")
    company = store.add_party(name="Muster GmbH", kind="company")
    assert rule_context(company, document, extraction([]), date(2026, 9, 25)).private_sender is True
    unknown = store.add_party(name="Stadt Musterstadt")  # kind "other" by default
    assert rule_context(unknown, document, extraction([]), date(2026, 9, 25)).private_sender is False
    bescheid = {
        "type": "widerspruch",
        "quote": "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
    }
    misfiled = rule_context(
        None,
        document,
        extraction([], sender={"name": "AOK Nordost", "kind": "insurer"}, remedy=bescheid),
        date(2026, 9, 25),
    )
    assert misfiled.private_sender is False and misfiled.delivery_scope == "sgbx"  # a statutory insurer
    muster = rule_context(
        None,
        document,
        extraction([], sender={"name": "Muster Versicherung", "kind": "insurer"}, remedy=bescheid),
        date(2026, 9, 25),
    )
    assert muster.private_sender is False and muster.delivery_scope is None
    dismissal = {
        "type": "klage",
        "quote": "Eine Kündigungsschutzklage muss innerhalb von drei Wochen nach Zugang erhoben werden.",
        "addressee": "Arbeitsgericht Berlin",
    }
    employer = rule_context(
        None,
        document,
        extraction([], sender={"name": "Land Berlin", "kind": "employer"}, remedy=dismissal),
        date(2026, 9, 25),
    )
    assert employer.private_sender is True and employer.delivery_scope is None


@pytest.mark.parametrize(
    ("kind", "quote"),
    [
        ("gym", "Sie können innerhalb von zwei Wochen nach Bekanntgabe der Preiserhöhung kündigen."),
        ("bank", "Bitte legen Sie uns Ihren Rentenbescheid innerhalb von zwei Wochen vor."),
    ],
)
def test_a_quote_naming_a_bescheid_never_brings_deemed_delivery_back(
    store: Store, kind: str, quote: str
) -> None:
    """Reviewer repro: a gym's "nach Bekanntgabe der Preiserhöhung", a bank asking for "Ihren
    Rentenbescheid". The item's quote may name an administrative act, but a private sender's period still
    runs from the day it arrived (Fri 16 Oct) — deemed delivery would give Sun 18 Oct — and the app keeps
    asking for that day while it is missing (``private_sender_arrival``)."""
    party = store.add_party(name="FitWell GmbH", kind=kind)
    spec = {
        "type": "relative",
        "amount": 2,
        "unit": "weeks",
        "anchor": "deemed_delivery",
        "nature": "notice",
        "text": "innerhalb von zwei Wochen",
    }
    extracted = item(quote, kind="deadline", **spec)
    page = (1, "Musterstadt, 01.10.2026\n" + quote, [], "text")
    for digit, received, due in (("1", "2026-10-02", "2026-10-16"), ("2", None, "2026-10-15")):
        document = store.add_document(
            sha256=digit * 64,
            filename="x",
            mime="application/pdf",
            file_path="x",
            received_date=received,
        )
        ctx = rule_context(
            party, document, extraction([extracted], document_date="2026-10-01"), date(2026, 10, 5)
        )
        computed = compute_item(verified_item(extracted, page), ctx, postal_buffer_days=4)
        assert computed.due_date == due and computed.receipt is not None
        assert "private_sender_arrival" in computed.receipt.rule_ids
        assert "posting_day" not in computed.receipt.rule_ids


@pytest.mark.parametrize(
    "words",
    ["innerhalb eines Monats nach Bekanntgabe dieses Bescheides", "innerhalb eines Monats"],
)
def test_a_late_arrival_of_a_letter_naming_a_bescheid_keeps_the_earlier_date(
    store: Store, words: str
) -> None:
    """A municipal office's Gebührenbescheid filed under a kind no public body goes by (a ``landlord``),
    without a remedy notice read. It counts from the day it arrived, but its sentence names the
    Bescheid — in the spec's words, or only in the item's quote around them — so an arrival after the day
    it would usually count as delivered does not make the date later: Mon 5 Oct, not Wed 14 Oct."""
    document = store.add_document(
        sha256="d" * 64, filename="x", mime="application/pdf", file_path="x", received_date="2026-09-14"
    )
    office = store.add_party(name="Stadt Musterstadt Wohnungsamt", kind="landlord")
    fee = item(
        "Die Gebühr ist innerhalb eines Monats nach Bekanntgabe dieses Bescheides zu zahlen.",
        type="relative",
        amount=1,
        unit="months",
        anchor="deemed_delivery",
        delivery_rule="de_admin_post",
        nature="payment",
        text=words,
    )
    page = (1, "Musterstadt, 01.09.2026\n" + fee.quote, [], "text")
    ctx = rule_context(
        office,
        document,
        extraction([fee], document_date="2026-09-01"),
        date(2026, 9, 26),
        recipient_region="NW",
    )
    assert ctx.private_sender is True and ctx.sender_kind == "landlord" and ctx.region is None
    computed = compute_item(verified_item(fee, page), ctx, postal_buffer_days=4)
    assert computed.due_date == "2026-10-05" and computed.receipt is not None
    assert "private_sender_late_arrival" in computed.receipt.rule_ids
    assert "posting_day" not in computed.receipt.rule_ids and computed.receipt.confidence == "medium"
    # a sentence without one runs from the day it arrived, however late (§ 130 BGB)
    firm = item(
        "Bitte zahlen Sie innerhalb eines Monats.",
        **{**fee.date.model_dump(), "text": "innerhalb eines Monats"},
    )
    firm_page = (1, "Musterstadt, 01.09.2026\n" + firm.quote, [], "text")
    private = compute_item(verified_item(firm, firm_page), ctx, postal_buffer_days=4)
    assert private.due_date == "2026-10-14" and private.receipt is not None
    assert "private_sender_arrival" in private.receipt.rule_ids


def test_rule_context_recognises_social_law_senders_filed_as_authority(store: Store) -> None:
    """Benchmark finding: job centres and pension insurers are read as a plain ``authority``, which
    applied the VwVfG (and a Land's 3-day rule) instead of § 37 SGB X."""
    document = store.add_document(sha256="e" * 64, filename="x", mime="application/pdf", file_path="x")
    jobcenter = store.add_party(name="Jobcenter Beispielkreis", kind="authority")
    ctx = rule_context(jobcenter, document, extraction([]), date(2026, 5, 1))
    assert ctx.delivery_scope == "sgbx"
    by_remedy = rule_context(
        None,
        document,
        extraction(
            [],
            sender={"name": "Kreis Beispiel", "kind": "authority"},
            remedy={
                "type": "widerspruch",
                "quote": "Gegen die Entscheidung des Widerspruchs ist Klage beim Sozialgericht möglich.",
            },
        ),
        date(2026, 5, 1),
    )
    assert by_remedy.delivery_scope == "sgbx"
    child_benefit = rule_context(
        None,
        document,
        extraction(
            [], sender={"name": "Familienkasse Nord", "kind": "authority"}, remedy={"type": "einspruch"}
        ),
        date(2026, 5, 1),
    )
    assert child_benefit.delivery_scope == "ao"
    assert remedy_text(None) == ""
    assert (
        remedy_text(Remedy(type="widerspruch", addressee="Jobcenter", period_text="ein Monat"))
        == "Jobcenter ein Monat"
    )


def test_rule_context_marks_a_courts_letter_whatever_kind_it_was_filed_as(store: Store) -> None:
    """A court's letter never gets an authority's delivery fiction, even when it isn't filed as a court
    order (the policy missed it, or it is another kind of court letter); a labour court's orders give one
    week."""
    document = store.add_document(sha256="f" * 64, filename="x", mime="application/pdf", file_path="x")
    court = rule_context(
        None,
        document,
        extraction([], sender={"name": "AG Coburg – Mahngericht", "kind": "authority"}),
        date(2026, 9, 25),
    )
    assert court.court and not court.labour_court and court.letter_kind != "court_payment_order"
    labour = store.add_party(name="Arbeitsgericht Berlin", kind="authority")
    assert rule_context(labour, document, extraction([]), date(2026, 9, 25)).labour_court
    bailiff = rule_context(
        None,
        document,
        extraction([], sender={"name": "Gerichtsvollzieher beim Amtsgericht Köln", "kind": "authority"}),
        date(2026, 9, 25),
    )
    assert not bailiff.court


def _notice(quote: str, end: str) -> DocumentExtraction:
    return extraction([], change={"type": "termination_by_provider", "effective_date": end, "quote": quote})


def test_a_dismissal_without_notice_period_ends_the_job_on_arrival() -> None:
    """Review round 4 of phase 2: "außerordentlich fristlos, hilfsweise fristgerecht zum 31.12.2026" counted the
    § 38 SGB III registration from the end given in the alternative (Wed 30 Sep, high) — the job ends when a
    notice without notice period arrives, so the three days count from then (Mon 28 Sep)."""
    from ordnung.ingest.plan import law_deadlines
    from ordnung.rules import compute_due

    quote = "Hiermit kündigen wir das Arbeitsverhältnis außerordentlich fristlos, hilfsweise fristgerecht zum 31.12.2026."
    reading = extraction(
        [],
        document_date="2026-09-24",
        sender={"name": "Muster GmbH", "kind": "employer"},
        change={"type": "termination_by_provider", "effective_date": "2026-12-31", "quote": quote},
    ).model_copy(update={"kind": "employment"})
    document = Document(
        id="doc_x", sha256="a" * 64, filename="x.pdf", mime="application/pdf", file_path="x",
        received_date="2026-09-25", doc_date="2026-09-24", created_at="2026-09-25T00:00:00",
        updated_at="2026-09-25T00:00:00",
    )  # fmt: skip
    ctx = rule_context(None, document, reading, date(2026, 9, 26), pages=[(1, quote, [], "text")])
    assert ctx.letter_kind == "dismissal" and ctx.ends_on_arrival
    dates = {
        entry.rule_id: compute_due(entry.spec, ctx).due_date
        for entry in law_deadlines("dismissal", reading, ctx)
    }
    assert dates == {"kschg_4": "2026-10-16", "sgb3_38": "2026-09-28"}
    ordinary = reading.model_copy(
        update={
            "change": reading.change.model_copy(update={"quote": "Wir kündigen fristgerecht zum 31.12.2026."})
        }
    )
    assert not rule_context(None, document, ordinary, date(2026, 9, 26)).ends_on_arrival
    # only a dismissal: a landlord's notice without notice period keeps its end (the objection counts from it)
    notice = reading.model_copy(update={"kind": "rent_lease", "sender": None})
    assert not rule_context(None, document, notice, date(2026, 9, 26)).ends_on_arrival


def test_a_notice_too_short_for_its_period_counts_its_objection_from_the_earliest_end() -> None:
    """Review round 4 of phase 2: a notice dated 25 Aug "zum 31.10.2026" that arrived on 28 Aug can end the
    tenancy on 30 Nov at the earliest (§ 573c Abs. 1 BGB): the law's objection counts back from that end."""
    from ordnung.ingest.plan import law_deadlines

    quote = "Hiermit kündigen wir das Mietverhältnis zum 31.10.2026."
    reading = extraction(
        [],
        document_date="2026-08-25",
        change={"type": "termination_by_provider", "effective_date": "2026-10-31", "quote": quote},
    ).model_copy(update={"kind": "rent_lease"})
    ctx = RuleContext(
        today=date(2026, 9, 2),
        document_date=date(2026, 8, 25),
        received_date=date(2026, 8, 28),
        received_confirmed=True,
        end_date=date(2026, 10, 31),
    )
    [objection] = law_deadlines("landlord_notice", reading, ctx)
    assert objection.spec.legal_basis == "§ 574b Abs. 2, § 573c Abs. 1 BGB"
    early = RuleContext(today=date(2026, 8, 5), document_date=date(2026, 8, 3), end_date=date(2026, 10, 31))
    [stated] = law_deadlines("landlord_notice", reading, early)
    assert stated.spec.anchor_date == "2026-10-31"


def test_the_end_a_termination_announces_is_grounded_like_an_items_date() -> None:
    quote = "hiermit kündigen wir das Mietverhältnis fristgerecht zum 31.03.2027."
    page = (1, f"Hausverwaltung\nMietende: 31.03.2027\n{quote}", [], "text")
    assert end_date_grounding(_notice(quote, "2027-03-31"), [page]) == "quote"
    assert end_date_grounding(_notice(quote, "2027-05-31"), [page]) == "none"  # misread
    vague = "hiermit kündigen wir das Mietverhältnis fristgerecht zum nächstmöglichen Zeitpunkt."
    heading = (1, f"Mietende: 31.03.2027\n{vague}", [], "text")
    assert end_date_grounding(_notice(vague, "2027-03-31"), [heading]) == "letter"
    # a quote that states the end but isn't on the page: only the page counts
    assert (
        end_date_grounding(_notice(quote, "2027-03-31"), [(1, "Mietende: 31.03.2027", [], "text")])
        == "letter"
    )
    assert end_date_grounding(_notice(quote, "2027-03-31"), []) == "none"  # no letter text to check
    assert end_date_grounding(extraction([]), []) == "quote"  # no end: nothing to ground


def test_a_rule_to_do_needs_checking_only_when_its_end_date_isnt_written(store: Store) -> None:
    document = store.add_document(sha256="e" * 64, filename="x", mime="application/pdf", file_path="x")
    fields: dict[str, Any] = {
        "kind": "deadline",
        "title": "Decide whether to object",
        "due_date": "2027-01-29",
        "origin": "rule",
        "grounding": "model_read",
    }
    plain = store.add_item(doc_id=document.id, **fields)
    assert not needs_check(plain)  # the law's date: nothing quoted, nothing to check
    unwritten = Evidence(doc_id=document.id, quote="zum 31.03.2027", value_consistent=False)
    flagged = store.add_item(doc_id=document.id, evidence=[unwritten], **fields)
    assert needs_check(flagged)
    confirmed = store.update_item(flagged.id, grounding="user")
    assert not needs_check(confirmed)


def test_the_to_do_code_files_for_an_incomplete_reading_needs_checking_dated_or_not(store: Store) -> None:
    """``ingest/gaps.py``: an incomplete reading's to-do keeps the letter "Please check" until the person acts on
    it, even without a date; any other undated to-do of a reading still never does."""
    document = store.add_document(sha256="e" * 64, filename="x", mime="application/pdf", file_path="x")
    unfound = Evidence(doc_id=document.id, quote="", grounding="unverified", value_consistent=False)
    fields: dict[str, Any] = {"kind": "task", "title": "Read this letter yourself", "evidence": [unfound]}
    check = store.add_item(doc_id=document.id, slot_key=CHECK_SLOT, **fields)
    assert check.due_date is None and needs_check(check)
    assert not needs_check(store.update_item(check.id, grounding="user"))  # confirmed
    for status in ("done", "dismissed"):
        assert not needs_check(store.update_item(check.id, grounding="unverified", status=status))
    ordinary = store.add_item(doc_id=document.id, slot_key="a" * 40, **fields)
    assert not needs_check(ordinary)


def test_verifying_without_the_reading_check_adds_nothing() -> None:
    """Only the pipeline and the benchmark ask for the reading check (``check_reading``): an empty reading of a
    letter with a notice on how to object gets no to-do of its own here."""
    empty = DocumentExtraction(kind="other", title="Letter", summary="s", explanation="e")
    assert verify_extraction("doc_x", empty, [TEXT_PAGE]).items == []
    assert verify_extraction("doc_x", empty, [TEXT_PAGE]).warnings == []
    [check] = verify_extraction("doc_x", empty, [TEXT_PAGE], check_reading=True).items
    assert check.slot_key == CHECK_SLOT and check.needs_check


def test_remedy_warnings_and_payment_details() -> None:
    assert remedy_warnings(Remedy(type="klage"))[0].startswith(
        "This decision can only be challenged in court"
    )
    assert "one-year" in remedy_warnings(Remedy(type="unclear"))[0]
    assert remedy_warnings(Remedy(type="einspruch")) == remedy_warnings(None) == []
    details = payment_details(PaymentDetails(iban="de89 3704 0044 0532 0130 00"))
    assert details is not None and details.iban == "DE89370400440532013000" and details.iban_valid


def test_a_misread_iban_is_taken_from_the_page() -> None:
    """Demo finding: the model read "DE05 1234 5600 0004 4556 60" as DE05123456000044556660 (one zero
    too many), which failed the checksum and raised a false "misprinted IBAN" warning."""
    page = "Bankverbindung: Musterbank, IBAN DE05 1234 5600 0004 4556 60 · BIC MUSKDEM1XXX"
    fixed = payment_details(PaymentDetails(iban="DE05123456000044556660"), page)
    assert fixed is not None and fixed.iban == "DE05123456000004455660" and fixed.iban_valid
    # a page that really prints a broken IBAN stays flagged
    broken = payment_details(
        PaymentDetails(iban="DE05123456000044556660"), "IBAN DE05 1234 5600 0044 5566 60"
    )
    assert broken is not None and broken.iban == "DE05123456000044556660" and broken.iban_valid is False
    # an unrelated IBAN on the page is never swapped in
    other = payment_details(PaymentDetails(iban="DE05123456000044556660"), "IBAN DE89 3704 0044 0532 0130 00")
    assert other is not None and other.iban == "DE05123456000044556660" and not other.iban_valid


#: The demo fitness contract's reading (UI audit R1-backend-7): a false checksum claim about a valid IBAN.
FALSE_CLAIM = (
    "The studio's stated bank account IBAN (DE05 1234 6700 0029 9001 50) does not pass the standard IBAN "
    "checksum, and several details in this document (names, addresses) look like generic placeholder/sample "
    "data, so verify the account before relying on it."
)
VALID = PaymentDetails(iban="DE89370400440532013000", iban_valid=True)
BROKEN = PaymentDetails(iban="DE89370400440532013001", iban_valid=False)


def test_a_checksum_claim_the_check_contradicts_is_not_stored() -> None:
    """R1-backend-7: code checks the IBAN's digits (ADR 0002); the model's claim about them is squared with
    that check when the letter is read, sentence by sentence."""
    assert square_iban_claims([FALSE_CLAIM, "Payment is due monthly."], VALID) == ["Payment is due monthly."]
    mixed = "The IBAN fails its checksum. The contract renews automatically."
    assert square_iban_claims([mixed], VALID) == ["The contract renews automatically."]
    # a claim that agrees with the check stays, in German too
    agrees = "The IBAN's check digits are valid, but the payee differs from the sender."
    assert square_iban_claims([agrees], VALID) == [agrees]
    german = "Die Prüfziffer der IBAN ist ungültig."
    assert square_iban_claims([german], VALID) == []
    # warnings about something else are kept as read
    other = "The IBAN belongs to a bank in Lithuania, not Germany."
    assert square_iban_claims([other], VALID) == [other]


def test_a_failing_iban_is_said_in_ordnungs_words_once() -> None:
    claims = ["The IBAN does not pass its checksum.", "IBAN checksum wrong — maybe a typo. Pay soon."]
    squared = square_iban_claims(claims, BROKEN)
    assert squared[0] == "Pay soon."
    assert squared[1:] == [invalid_iban_message(BROKEN.iban or "")]
    assert "valid" in squared[1] and "IBAN" in squared[1]
    # a positive claim about a failing IBAN is wrong too
    assert square_iban_claims(["The IBAN's checksum is fine."], BROKEN) == [
        invalid_iban_message("DE89370400440532013001")
    ]


def test_without_an_iban_the_warnings_stay_as_read() -> None:
    assert square_iban_claims([FALSE_CLAIM], None) == [FALSE_CLAIM]
    assert square_iban_claims([FALSE_CLAIM], PaymentDetails(iban=None)) == [FALSE_CLAIM]
    assert square_iban_claims([FALSE_CLAIM], PaymentDetails(iban="DE89370400440532013000")) == [FALSE_CLAIM]


# --------------------------------------------------------------------------------------------------
# Writing items
# --------------------------------------------------------------------------------------------------


def add_doc(store: Store) -> Document:
    return store.add_document(sha256="e" * 64, filename="bill.pdf", mime="application/pdf", file_path="b.pdf")


def write(
    store: Store, doc_id: str, items: list[ExtractedItem], pages: Sequence[PageInput] = (TEXT_PAGE,)
) -> list[Item]:
    data = extraction(items)
    verification = verify_extraction(doc_id, data, pages)
    ctx = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 15))
    computed = [compute_item(v, ctx, postal_buffer_days=4) for v in verification.items]
    return write_items(
        store,
        doc_id,
        verification,
        computed,
        data,
        LinkResult(),
        today=ctx.today,
        ctx=ctx,
        postal_buffer_days=4,
    )


def test_write_items_upserts_by_slot_and_keeps_user_edits(store: Store) -> None:
    document = add_doc(store)
    payment, objection = write(store, document.id, [PAYMENT, OBJECTION])
    assert payment.evidence == [Evidence.model_validate(payment.evidence[0].model_dump())]
    assert payment.due_date_source == "fixed" and objection.due_date_source == "computed"
    store.update_item(objection.id, title="My own title", user_modified=True)
    store.update_item(payment.id, status="done")

    changed = PAYMENT.model_copy(update={"title": "Pay the bill"})
    rewritten = write(store, document.id, [changed])
    assert rewritten[0].id == payment.id
    assert rewritten[0].title == "Pay the bill"
    assert rewritten[0].status == "done"  # the person's status is never reset
    kept = store.get_item(objection.id)
    assert kept is not None and kept.title == "My own title"

    write(store, document.id, [])  # the edited and the paid to-do stay; nothing else was read
    assert {i.id for i in store.list_items(doc_id=document.id)} == {objection.id, payment.id}


def test_a_due_day_grounded_elsewhere_is_stored_as_the_to_dos_evidence(store: Store) -> None:
    """The to-do keeps its own sentence first and the one stating its day after it; neither needs a check."""
    document = add_doc(store)
    page = ticket_page(TICKET_PRICE, TICKET_DEBIT, TICKET_NOTICE)
    [stored] = write(store, document.id, [ticket()], [page])
    assert [e.quote for e in stored.evidence] == [TICKET_PRICE, " ".join(TICKET_DEBIT.split())]
    assert [e.grounding for e in stored.evidence] == ["verified", "verified"]
    assert all(e.value_consistent for e in stored.evidence) and stored.evidence[1].boxes
    assert stored.grounding == "verified" and not needs_check(stored)
    [unstated] = write(store, add_doc_named(store, "other.pdf").id, [ticket()], [ticket_page(TICKET_PRICE)])
    assert len(unstated.evidence) == 1 and needs_check(unstated)


def add_doc_named(store: Store, filename: str) -> Document:
    return store.add_document(sha256="f" * 64, filename=filename, mime="application/pdf", file_path=filename)


def test_a_to_do_the_person_acted_on_moves_to_a_reworded_reading(store: Store) -> None:
    """Reading the letter again with the sentence quoted differently must not bring back a paid bill."""
    document = add_doc(store)
    [payment] = write(store, document.id, [PAYMENT])
    store.update_item(payment.id, status="done")

    reworded = PAYMENT.model_copy(update={"quote": "Wir bitten Sie, 49,99 EUR bis zum 15.10.2026 zu zahlen."})
    fee = PAYMENT.model_copy(update={"quote": "Bitte zahlen Sie 5,00 EUR bis zum 15.10.2026.", "amount": 5.0})
    [again, new_fee] = write(store, document.id, [reworded, fee])
    assert again.id == payment.id and again.status == "done"  # same obligation: still paid
    assert new_fee.id != payment.id and new_fee.status == "open"  # another amount: a new to-do
    assert len(store.list_items(doc_id=document.id)) == 2


def test_a_recurring_to_do_moves_to_a_reading_that_corrects_its_amount(store: Store) -> None:
    """Two advance payments of one schedule (monthly from 15 Oct); electricity is paid ahead to
    December. Read again with both sentences quoted differently and electricity's amount corrected:
    each keeps its own to-do (a reading with the stored amount is matched first), and the corrected
    one keeps its paid-ahead occurrence (recurrence.py, point 6)."""
    monthly = {"type": "fixed", "date": "2026-10-15", "nature": "payment"}
    power = item("Abschlag Strom: 50,00 EUR monatlich ab 15.10.2026", money=50.0, **monthly)
    gas = item("Abschlag Gas: 30,00 EUR monatlich ab 15.10.2026", money=30.0, **monthly)
    power, gas = (reading.model_copy(update={"recurrence": Recurrence()}) for reading in (power, gas))
    document = add_doc(store)
    stored_power, stored_gas = write(store, document.id, [power, gas])
    store.update_item(stored_power.id, due_date="2026-12-15")  # paid ahead

    corrected = power.model_copy(
        update={"quote": "Strom: monatlich 55,00 EUR ab dem 15.10.2026", "amount": 55.0}
    )
    reworded = gas.model_copy(update={"quote": "Gas: monatlich 30,00 EUR ab dem 15.10.2026"})
    again_power, again_gas = write(store, document.id, [corrected, reworded])
    assert (again_power.id, again_power.amount, again_power.due_date) == (stored_power.id, 55.0, "2026-12-15")
    assert (again_gas.id, again_gas.due_date) == (stored_gas.id, "2026-10-15")
    assert len(store.list_items(doc_id=document.id)) == 2


def test_a_new_rent_dated_by_its_working_day_starts_when_the_law_allows_with_its_note(store: Store) -> None:
    """recurrence.py point 8 when the letter is read: a rent increase's new rent "ab dem 01.11.2026", paid by
    the 3rd working day (read with its working day, which its quote names), in a request of
    24 Sep. Its first rent is December's (Thu 3 Dec: § 558b Abs. 1 BGB allows no earlier month), and dated by
    its working day it is still only owed once the person agrees (the note and its rule stay)."""
    from ordnung.ingest.pipeline import compute_dates

    quote = "Neue monatliche Miete 670,00 EUR ab dem 01.11.2026, zahlbar bis zum 3. Werktag."
    reading = item(
        quote, money=670.0, type="fixed", date="2026-11-01", nature="payment", text="ab dem 01.11.2026"
    )
    new_rent = reading.model_copy(update={"recurrence": Recurrence(working_day=3)})
    change = ExtractedChange(type="price_increase", old_amount=640.0, new_amount=670.0)
    data = DocumentExtraction(
        kind="rent_lease",
        title="Rent increase",
        summary="s",
        explanation="e",
        items=[new_rent],
        change=change,
    )
    document = add_doc(store)
    verification = verify_extraction(document.id, data, [(1, quote, [], "text")])
    ctx = RuleContext(today=date(2026, 9, 29), document_date=date(2026, 9, 24), letter_kind="rent_increase")
    note = rent_increase_note("rent_increase", data)
    computed = compute_dates(verification.items, ctx, postal_buffer_days=4, note=note)
    [written] = write_items(
        store,
        document.id,
        verification,
        computed,
        data,
        LinkResult(),
        today=ctx.today,
        ctx=ctx,
        postal_buffer_days=4,
    )
    assert written.due_date == "2026-12-03" and written.computation is not None
    assert RENT_INCREASE_PAYMENT_WARNING in written.computation.warnings
    assert "bgb_558b" in written.computation.rule_ids


def test_activity_message() -> None:
    now = "2026-09-25T10:00:00Z"
    items = [
        Item(id=f"itm_{n}", kind=kind, title="t", created_at=now, updated_at=now)
        for n, kind in enumerate(["payment", "deadline", "deadline"])
    ]
    assert (
        activity_message("Tax", items, "Finanzamt")
        == "Read “Tax” · 2 deadlines, 1 payment · linked to Finanzamt"
    )
    assert activity_message("Note", [], None) == "Read “Note” · no dates"


def test_rule_context_carries_the_person_s_country_and_only_a_chosen_region(store: Store) -> None:
    """Audit B integration: letters honour ``Profile.country`` like contracts do, and the default region
    of a profile that never chose one is not "known" (it would move payments on the wrong holidays)."""
    document = store.add_document(sha256="e" * 64, filename="x", mime="application/pdf", file_path="x")
    ctx = rule_context(None, document, extraction([]), date(2026, 9, 25), country="AT")
    assert ctx.country == "AT" and ctx.recipient_region is None
    assert Profile().known_region is None
    assert Profile(region="BY", onboarded=True).known_region == "BY"


# --------------------------------------------------------------------------------------------------
# regressions from the recorded demo: values stated elsewhere in the letter are not "please check"
# --------------------------------------------------------------------------------------------------


def test_amount_stated_elsewhere_in_the_letter_is_not_flagged() -> None:
    from ordnung.ingest.plan import verify_extraction
    from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem

    page = (
        1,
        "Rechnungsbetrag 89,99 €\nZahlbar innerhalb von 14 Tagen nach Rechnungsdatum ohne Abzug.",
        [],
        "text",
    )
    item = ExtractedItem(
        kind="payment",
        title="Pay the invoice",
        date=DateSpec(type="relative", anchor="document_date", amount=14, unit="days", nature="payment"),
        amount=89.99,
        quote="Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum ohne Abzug.",
    )
    extraction = DocumentExtraction(
        kind="invoice", title="Invoice", summary="s", explanation="e", items=[item]
    )
    verification = verify_extraction("doc_x", extraction, [page])
    assert not verification.needs_review
    assert verification.items[0].evidence.value_consistent


def test_amount_missing_from_the_whole_letter_is_still_flagged() -> None:
    from ordnung.ingest.plan import verify_extraction
    from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem

    page = (1, "Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum.", [], "text")
    item = ExtractedItem(
        kind="payment",
        title="Pay",
        date=DateSpec(type="relative", anchor="document_date", amount=14, unit="days", nature="payment"),
        amount=120.0,
        quote="Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum.",
    )
    extraction = DocumentExtraction(
        kind="invoice", title="Invoice", summary="s", explanation="e", items=[item]
    )
    assert verify_extraction("doc_x", extraction, [page]).needs_review


def test_fixed_date_stated_elsewhere_and_recurring_schedules_are_not_flagged() -> None:
    from ordnung.ingest.plan import verify_extraction
    from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem, Recurrence

    text = "Termin: Mittwoch, 14.10.2026, 10:30 Uhr\nDie Gebühr in Höhe von 100,00 € zahlen Sie vor Ort.\nAbbuchung zum Monatsanfang."
    page = (1, text, [], "text")
    fee = ExtractedItem(
        kind="payment",
        title="Fee",
        date=DateSpec(type="fixed", date="2026-10-14", nature="payment"),
        amount=100.0,
        quote="Die Gebühr in Höhe von 100,00 € zahlen Sie vor Ort.",
    )
    monthly = ExtractedItem(
        kind="payment",
        title="Monthly ticket",
        date=DateSpec(type="fixed", date="2026-10-01", nature="payment"),
        recurrence=Recurrence(interval=1, unit="months"),
        quote="Abbuchung zum Monatsanfang.",
    )
    extraction = DocumentExtraction(
        kind="contract", title="Letter", summary="s", explanation="e", items=[fee, monthly]
    )
    assert not verify_extraction("doc_x", extraction, [page]).needs_review


def test_passport_bilingual_month_dates_parse() -> None:
    from datetime import date

    from ordnung.ingest.verify import parse_dates

    assert [m.as_date() for m in parse_dates("Date of expiry 10 FEB / FÉV 2027")] == [date(2027, 2, 10)]
