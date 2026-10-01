"""A reading that came back incomplete gets one "Please check" to-do written by code (``ingest/gaps.py``).

Every letter here is synthetic, written for these tests: a city's fee decision with its instructions on how to
object (Rechtsbehelfsbelehrung), and the ordinary letters that rightly have no to-do or no objection. The
overriding rule tested throughout: the code-made date is never later than the letter allows.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ordnung.db.store import Store
from ordnung.ingest.gaps import (
    CHECK_SLOT,
    DEADLINE_ACTION,
    DEADLINE_CONSEQUENCE,
    KLAGE_ACTION,
    KLAGE_CONSEQUENCE,
    KNOWN_ADDRESS,
    LAW_DATED_KINDS,
    PLACEHOLDER_ACTION,
    QUOTE_CAP,
    check_item,
    gap_warning,
    letter_date,
    reading_gap,
    remedy_notices,
    start_variants,
)
from ordnung.ingest.link import LinkResult
from ordnung.ingest.plan import (
    ComputedDate,
    VerifiedItem,
    checked_evidence,
    compute_item,
    needs_check,
    remedy_warnings,
    verify_extraction,
    write_items,
)
from ordnung.ingest.verify import (
    DATE_NOT_IN_QUOTE,
    PERIOD_NOT_IN_QUOTE,
    READING_INCOMPLETE,
    REASON_TEXT,
    PageInput,
)
from ordnung.models import (
    LETTER_KINDS,
    DateSpec,
    DocumentExtraction,
    ExtractedChange,
    ExtractedContract,
    ExtractedFact,
    ExtractedItem,
    ExtractedParty,
    Identifier,
    Page,
    PaymentDetails,
    Remedy,
)
from ordnung.rules import RuleContext, compute_due
from ordnung.rules.delivery import shows_administrative_act
from ordnung.rules.routing import derived_deadlines

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.metrics import INJECTION_RE, SCAM_RE, UNCERTAINTY_RE  # noqa: E402

# --------------------------------------------------------------------------------------------------
# A synthetic decision of a city (dated Fri 6 Nov 2026) and the readings of it
# --------------------------------------------------------------------------------------------------

LETTERHEAD = "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen"
HEAD = (
    LETTERHEAD,
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 06.11.2026",
    "Aktenzeichen: OA-2026-0815",
    "Gebührenbescheid über die Sondernutzung einer Gehwegfläche",
    "Sehr geehrte Frau Probe,",
    "mit diesem Bescheid setzen wir für die Nutzung der Gehwegfläche eine Gebühr von 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
)
NOTIFIED = "Gegen diesen Gebührenbescheid können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch einlegen."
SERVED = "Gegen diesen Bescheid kann innerhalb von zwei Wochen nach Zustellung Einspruch eingelegt werden."
WHERE = "Der Widerspruch ist schriftlich oder zur Niederschrift bei der Stadt Beispielhausen einzulegen."
PAY = "Bitte überweisen Sie die Gebühr von 85,00 EUR bis zum 30.11.2026."
TODAY = date(2026, 11, 10)
#: One month after notification of a letter dated Fri 6 Nov 2026, the Land unknown: delivered on the 3rd day
#: (Mon 9 Nov), due Wed 9 Dec; counted from the letter's date itself: Sun 6 Dec → Mon 7 Dec.
NOTIFIED_DUE, FROM_LETTER_DUE = "2026-12-09", "2026-12-07"


def page(*lines: str, source: str = "text", number: int = 1) -> PageInput:
    return (number, "\n".join(lines), [], source)


DECISION = page(*HEAD, NOTIFIED, WHERE)


def head(day: str) -> tuple[str, ...]:
    """The decision's header with another date."""
    return (*HEAD[:4], f"Datum: {day}", *HEAD[5:])


def blank(**fields: Any) -> DocumentExtraction:
    """A reading with only the four fields the schema requires (and any ``fields`` given)."""
    return DocumentExtraction.model_validate(
        {"kind": "other", "title": "Letter", "summary": "A letter.", "explanation": "Read it.", **fields}
    )


def objection(
    spec: dict[str, Any] | None = None, *, quote: str = NOTIFIED, nature: str = "objection"
) -> ExtractedItem:
    date_spec = spec or {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "deemed_delivery",
        "delivery_rule": "de_admin_post",
    }
    return ExtractedItem.model_validate(
        {"kind": "deadline", "title": "Objection", "date": {**date_spec, "nature": nature}, "quote": quote}
    )


def payment(quote: str = PAY, **spec: Any) -> ExtractedItem:
    date_spec = spec or {"type": "fixed", "date": "2026-11-30", "nature": "payment"}
    return ExtractedItem.model_validate(
        {"kind": "payment", "title": "Pay the fee", "date": date_spec, "amount": 85.0, "quote": quote}
    )


SENDER = ExtractedParty(name="Stadt Beispielhausen", kind="authority")


def checked(extraction: DocumentExtraction, pages: Sequence[PageInput], **kw: Any) -> VerifiedItem:
    """The to-do the reading check filed (the last item of the verification)."""
    verification = verify_extraction("doc_x", extraction, pages, check_reading=True, **kw)
    verified = verification.items[-1]
    assert verified.slot_key == CHECK_SLOT
    return verified


def ctx_for(reading: DocumentExtraction, **fields: Any) -> RuleContext:
    written = date.fromisoformat(reading.document_date) if reading.document_date else None
    return replace(RuleContext(today=TODAY, document_date=written), **fields)


def due(
    pages: Sequence[PageInput],
    *,
    region: str | None = None,
    reading: DocumentExtraction | None = None,
    **ctx: Any,
) -> str | None:
    """The code-made to-do's date (``None`` when it has none)."""
    read = reading or blank()
    computed = compute_item(checked(read, pages), ctx_for(read, region=region, **ctx), postal_buffer_days=3)
    return computed.due_date


def notice(text: str) -> Any:
    [found] = remedy_notices([page(*HEAD, text)])
    return found


# --------------------------------------------------------------------------------------------------
# What an incomplete reading gets
# --------------------------------------------------------------------------------------------------


def test_an_empty_reading_gets_the_objection_deadline_its_notice_states() -> None:
    pages = [DECISION]
    found = check_item(blank(), pages)
    assert found is not None
    assert (found.gap, found.kind, found.remedy) == ("empty", "dated", "widerspruch")
    item = found.item
    assert (
        item.kind == "deadline"
        and item.priority == "high"
        and item.title == "Deadline to object (Widerspruch)"
    )
    # an almost blank reading of a letter with a notice is itself a warning sign: the known address too
    assert (item.action, item.consequence) == (f"{DEADLINE_ACTION} {KNOWN_ADDRESS}", DEADLINE_CONSEQUENCE)
    spec = item.date
    assert (spec.type, spec.amount, spec.unit, spec.nature) == ("relative", 1, "months", "objection")
    # the start travels in the spec; deemed delivery only as the delivery rule (a private sender keeps the start)
    assert (spec.anchor, spec.anchor_date, spec.delivery_rule) == (
        "explicit_date",
        "2026-11-06",
        "de_admin_post",
    )
    assert item.quote == NOTIFIED and spec.text == item.quote

    verification = verify_extraction("doc_x", blank(), pages, check_reading=True)
    [verified] = verification.items
    assert verified.slot_key == CHECK_SLOT and verified.reasons == (READING_INCOMPLETE,)
    assert verified.evidence.grounding == "verified" and not verified.evidence.value_consistent
    assert verified.needs_check and verification.needs_review
    assert verification.warnings == [gap_warning("empty", "dated")]

    for region, expected in ((None, NOTIFIED_DUE), ("HH", "2026-12-10")):
        computed = compute_item(verified, RuleContext(today=TODAY, region=region), postal_buffer_days=3)
        assert computed.due_date == expected
        assert computed.receipt is not None and computed.receipt.confidence == "low"
        assert REASON_TEXT[READING_INCOMPLETE] in computed.receipt.warnings


def test_a_period_from_formal_service_counts_from_the_letter_s_date_and_is_low_although_the_engine_is_sure() -> (
    None
):
    pages = [page(*HEAD, SERVED)]
    found = check_item(blank(), pages)
    assert (
        found is not None and found.kind == "dated" and found.item.title == "Deadline to object (Einspruch)"
    )
    spec = found.item.date
    assert (spec.anchor, spec.anchor_date, spec.delivery_rule, spec.amount, spec.unit) == (
        "explicit_date",
        "2026-11-06",
        "none",
        2,
        "weeks",
    )
    ctx = RuleContext(today=TODAY, region="NW")
    assert compute_due(spec, ctx, postal_buffer_days=3).confidence == "high"  # the engine alone
    verified = checked(blank(), pages)
    # Ordnung took the start from the header, not from the notice: no "date not in the quote" note
    assert verified.reasons == (READING_INCOMPLETE,)
    computed = compute_item(verified, ctx, postal_buffer_days=3)
    assert computed.due_date == "2026-11-20"
    assert computed.receipt is not None and computed.receipt.confidence == "low"
    assert REASON_TEXT[DATE_NOT_IN_QUOTE] not in computed.receipt.warnings


def add_doc(store: Store) -> str:
    return store.add_document(
        sha256="c" * 64, filename="letter.pdf", mime="application/pdf", file_path="l.pdf"
    ).id


def write(store: Store, doc_id: str, extraction: DocumentExtraction, pages: Sequence[PageInput]) -> list[Any]:
    verification = verify_extraction(doc_id, extraction, pages, check_reading=True)
    ctx = RuleContext(today=TODAY)
    computed: list[ComputedDate] = [compute_item(v, ctx, postal_buffer_days=3) for v in verification.items]
    return write_items(
        store,
        doc_id,
        verification,
        computed,
        extraction,
        LinkResult(),
        today=TODAY,
        ctx=ctx,
        postal_buffer_days=3,
    )


def test_an_empty_reading_without_a_notice_gets_an_undated_task_that_is_please_check(store: Store) -> None:
    pages = [
        page(LETTERHEAD, "Datum: 06.11.2026", "Sehr geehrte Frau Probe,", "wir bestätigen Ihre Anmeldung.")
    ]
    found = check_item(blank(), pages)
    assert found is not None and (found.gap, found.kind, found.remedy) == ("empty", "read_yourself", "")
    item = found.item
    assert item.kind == "task" and item.title == "Read this letter yourself" and item.date.type == "none"
    assert item.priority == "high" and item.quote == "" and item.action == PLACEHOLDER_ACTION
    verification = verify_extraction("doc_x", blank(), pages, check_reading=True)
    assert verification.warnings == [gap_warning("empty", "read_yourself")]
    verified = verification.items[-1]
    assert not verified.dated and verified.needs_check
    [stored] = write(store, add_doc(store), blank(), pages)
    assert stored.slot_key == CHECK_SLOT and stored.due_date is None
    assert needs_check(stored)
    assert not needs_check(stored.model_copy(update={"status": "done"}))
    assert not needs_check(stored.model_copy(update={"grounding": "user"}))


def test_a_notice_without_a_readable_letter_date_counts_from_the_letter_s_date_once_it_is_known() -> None:
    pages = [page(LETTERHEAD, "Sehr geehrte Frau Probe,", NOTIFIED)]
    assert letter_date(blank(), pages) is None
    found = check_item(blank(), pages)
    assert found is not None and found.kind == "undated" and found.item.kind == "deadline"
    spec = found.item.date
    # no dead end: the engine counts from the letter's date as soon as the person enters it
    assert (spec.anchor, spec.anchor_date, spec.delivery_rule) == ("document_date", None, "de_admin_post")
    verification = verify_extraction("doc_x", blank(), pages, check_reading=True)
    assert verification.warnings == [gap_warning("empty", "undated")]
    assert verification.items[0].needs_check
    assert due(pages) is None
    assert due(pages, document_date=date(2026, 11, 6)) == NOTIFIED_DUE


# --------------------------------------------------------------------------------------------------
# Which readings are incomplete
# --------------------------------------------------------------------------------------------------


def test_a_reading_that_copies_the_remedy_but_leaves_out_its_deadline_is_caught() -> None:
    reading = DocumentExtraction(
        kind="authority_letter",
        title="Fee decision",
        summary="s",
        explanation="e",
        sender=SENDER,
        document_date="2026-11-06",
        items=[payment()],
        remedy=Remedy(type="widerspruch", quote=NOTIFIED),
    )
    pages = [page(*HEAD, PAY, NOTIFIED, WHERE)]
    assert reading_gap(reading, pages, remedy_notices(pages)) == "remedy_left_out"
    verification = verify_extraction("doc_x", reading, pages, check_reading=True)
    assert [verified.slot_key == CHECK_SLOT for verified in verification.items] == [False, True]
    assert verification.warnings[-1] == gap_warning("remedy_left_out", "dated")
    assert due(pages, reading=reading) == NOTIFIED_DUE


def test_a_dated_objection_satisfies_the_check_and_one_that_doesn_t_compute_does_not() -> None:
    pages = [page(*HEAD, PAY, NOTIFIED)]
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[payment(), objection()])
    assert check_item(reading, pages) is None
    assert verify_extraction("doc_x", reading, pages, check_reading=True).warnings == []
    for spec in (
        {"type": "none"},
        {"type": "relative", "unit": "months"},  # no amount
        {"type": "fixed"},  # no date
        {"type": "fixed", "date": "nicht lesbar"},
        {"type": "relative", "amount": 1, "unit": "months", "anchor": "explicit_date"},  # no start
    ):
        undated = blank(sender=SENDER, document_date="2026-11-06", items=[payment(), objection(spec)])
        found = check_item(undated, pages)
        assert found is not None and found.gap == "remedy_left_out", spec


def test_an_objection_filed_under_another_nature_counts_only_when_its_quote_is_the_notice() -> None:
    pages = [page(*HEAD, NOTIFIED, "Ein Widerspruch hat keine aufschiebende Wirkung.", PAY)]
    spec = {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "deemed_delivery",
        "delivery_rule": "de_admin_post",
    }
    for nature in ("declaration", "other", "notice"):
        reading = blank(sender=SENDER, document_date="2026-11-06", items=[objection(spec, nature=nature)])
        assert check_item(reading, pages) is None, nature
    # a dated payment beside a remedy word is no objection
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[payment()])
    found = check_item(reading, pages)
    assert found is not None and found.gap == "remedy_left_out"


@pytest.mark.parametrize(
    ("reading", "lines"),
    [
        pytest.param(
            blank(
                kind="price_increase",
                sender=ExtractedParty(name="Stadtwerke Beispielhausen", kind="utility"),
                document_date="2026-11-02",
                key_facts=[
                    ExtractedFact(label="New price", value="0,34 EUR/kWh", quote="Arbeitspreis 0,34 EUR/kWh")
                ],
                change=ExtractedChange(
                    type="price_increase", effective_date="2027-01-01", quote="ab dem 01.01.2027"
                ),
            ),
            (
                "Stadtwerke Beispielhausen · Kundenservice",
                "Datum: 02.11.2026",
                "Sehr geehrte Kundin,",
                "ab dem 01.01.2027 gilt ein Arbeitspreis 0,34 EUR/kWh.",
                "Sie können der Preisänderung innerhalb von sechs Wochen widersprechen und den Vertrag kündigen.",
            ),
            id="price increase",
        ),
        pytest.param(
            blank(
                kind="payslip",
                sender=ExtractedParty(name="Probelager Spedition GmbH", kind="employer"),
                document_date="2026-10-30",
                key_facts=[
                    ExtractedFact(label="Net pay", value="2.104,17 EUR", quote="Auszahlung 2.104,17 EUR")
                ],
            ),
            ("Probelager Spedition GmbH", "Entgeltabrechnung Oktober 2026", "Auszahlung 2.104,17 EUR"),
            id="payslip",
        ),
        pytest.param(
            blank(
                kind="university",
                sender=ExtractedParty(name="Hochschule Beispielhausen", kind="university"),
                document_date="2026-10-01",
                references=[Identifier(label="Matrikelnummer", value="4711")],
            ),
            ("Hochschule Beispielhausen", "Immatrikulationsbescheinigung", "Matrikelnummer 4711"),
            id="enrolment certificate",
        ),
        pytest.param(
            blank(
                kind="contract",
                sender=ExtractedParty(name="Fitness Beispiel", kind="gym"),
                document_date="2026-10-12",
                contract=ExtractedContract(name="Mitgliedschaft", start_date="2026-11-01"),
            ),
            (
                "Fitness Beispiel",
                "Ihre Mitgliedschaft beginnt am 01.11.2026.",
                "Sie können Ihre Vertragserklärung innerhalb von 14 Tagen widerrufen.",
            ),
            id="contract confirmation",
        ),
    ],
)
def test_readings_that_rightly_have_no_to_do_are_complete(
    reading: DocumentExtraction, lines: tuple[str, ...]
) -> None:
    pages = [page(*lines)]
    assert reading_gap(reading, pages, remedy_notices(pages)) is None
    assert check_item(reading, pages) is None
    assert verify_extraction("doc_x", reading, pages, check_reading=True).items == []


def test_a_reading_of_a_letter_without_a_date_that_names_its_sender_is_complete() -> None:
    reading = blank(
        sender=ExtractedParty(name="Inkasso Beispiel", kind="company"),
        items=[
            payment(
                "Bitte zahlen Sie den offenen Betrag von 85,00 EUR umgehend.", type="none", nature="payment"
            )
        ],
    )
    pages = [
        page(
            "Inkasso Beispiel",
            "Sehr geehrte Frau Probe,",
            "Bitte zahlen Sie den offenen Betrag von 85,00 EUR umgehend.",
        )
    ]
    assert check_item(reading, pages) is None


def test_a_right_to_object_outside_an_administrative_act_is_no_gap() -> None:
    reading = blank(sender=ExtractedParty(name="Beispielbank", kind="bank"), document_date="2026-11-02")
    debit = [
        page(
            "Beispielbank",
            "Einer Lastschrift können Sie innerhalb von acht Wochen nach der Belastung widersprechen.",
        )
    ]
    assert remedy_notices(debit) and not shows_administrative_act(debit[0][1])
    assert check_item(reading, debit) is None
    # a right to object without a period is no notice, even on a decision
    privacy = [
        page(
            *HEAD,
            "Sie haben das Recht, der Verarbeitung Ihrer Daten zu diesem Bescheid jederzeit zu widersprechen.",
        )
    ]
    assert remedy_notices(privacy) == []
    assert check_item(reading, privacy) is None


def test_an_administrative_act_only_in_hidden_text_is_none() -> None:
    """A live right to object of a contract: only the hidden text names a decision — never read."""
    change = "Sie können dieser Vertragsänderung innerhalb von sechs Wochen widersprechen."
    hidden = Page(
        doc_id="d",
        page=1,
        width=10,
        height=10,
        image_path="p.jpg",
        text=f"Beispielbank\n{change}",
        text_source="text",
        hidden="Gebührenbescheid. Mit diesem Bescheid setzen wir fest.",
    )
    reading = blank(sender=ExtractedParty(name="Beispielbank", kind="bank"), document_date="2026-11-02")
    [found] = remedy_notices([hidden])
    assert found.live and not shows_administrative_act(hidden.text)
    assert reading_gap(reading, [hidden], [found]) is None


ORDER_TEXT = "Gegen diesen Bescheid können Sie innerhalb von zwei Wochen ab Zustellung Widerspruch erheben."


def court_order(kind: str = "court_payment_order") -> DocumentExtraction:
    return DocumentExtraction(
        kind="dunning",
        title="Payment order",
        summary="s",
        explanation="e",
        high_stakes_kind=kind,  # type: ignore[arg-type]
        sender=ExtractedParty(name="Amtsgericht Beispielhausen", kind="authority"),
        document_date="2026-11-06",
        items=[payment("Zahlen Sie 85,00 EUR an die Antragstellerin.", type="none", nature="payment")],
    )


def test_a_letter_whose_deadline_the_law_files_is_no_gap() -> None:
    pages = [page("Amtsgericht Beispielhausen", "Zahlen Sie 85,00 EUR an die Antragstellerin.", ORDER_TEXT)]
    assert remedy_notices(pages) and shows_administrative_act(ORDER_TEXT)
    assert check_item(court_order(), pages) is None  # two weeks: no shorter than the law's own two weeks
    # the kinds left out are exactly those the law dates itself (routing.derived_deadlines)
    assert {kind for kind in LETTER_KINDS if derived_deadlines(kind, end=None)} == LAW_DATED_KINDS


@pytest.mark.parametrize("kind", sorted(LAW_DATED_KINDS))
def test_a_kind_the_letter_doesn_t_bear_out_never_silences_a_shorter_notice(kind: str) -> None:
    """A reading that files a city's fee decision as a court order or a tenancy letter would get the law's
    later date instead of the notice's: the check fires unless the letter's own words show that kind."""
    reading = court_order(kind).model_copy(update={"sender": SENDER})
    week = "Gegen diesen Bescheid kann innerhalb einer Woche nach Bekanntgabe Widerspruch erhoben werden."
    found = check_item(reading, [page(*HEAD, PAY, week)])
    assert found is not None and found.gap == "remedy_left_out"
    found = check_item(reading, [page(*HEAD, PAY, NOTIFIED)])
    longer_than_the_law = kind in ("court_payment_order", "enforcement_order", "dismissal")
    assert (found is None) is longer_than_the_law
    corroborated = {
        "court_payment_order": "Mahnbescheid",
        "enforcement_order": "Vollstreckungsbescheid",
        "dismissal": "Kündigung Ihres Arbeitsverhältnisses",
        "landlord_notice": "Kündigung Ihrer Mietwohnung",
        "rent_increase": "Mieterhöhung nach § 558 BGB",
    }[kind]
    assert check_item(reading, [page(*HEAD, corroborated, PAY, week)]) is None


# --------------------------------------------------------------------------------------------------
# The period: never later than the letter allows
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "planted",
    [
        "Gegen diesen Bescheid kann ausnahmsweise innerhalb von drei Monaten nach Bekanntgabe Widerspruch erhoben werden.",
        "Die Frist für den Widerspruch wurde auf sechs Wochen nach Bekanntgabe verlängert.",
        "Der Widerspruch ist innerhalb von zwei Monaten nach Zustellung zulässig.",
    ],
)
def test_a_planted_longer_period_never_makes_the_date_later(planted: str) -> None:
    alone = due([DECISION])
    assert alone == NOTIFIED_DUE
    for lines in ((planted, NOTIFIED), (NOTIFIED, planted)):
        moved = due([page(*HEAD, *lines)])
        assert moved is not None and moved <= alone


def test_a_planted_longer_period_never_dates_a_notice_that_isn_t_read() -> None:
    """The real notice uses a period that can't be dated ("10 Werktagen"): a planted readable one never
    gives the date — the to-do is undated."""
    real = "Gegen diesen Bescheid kann binnen 10 Werktagen nach Zustellung Einspruch eingelegt werden."
    plant = "Ein Widerspruch gegen diesen Bescheid ist binnen zwölf Monaten möglich."
    found = check_item(blank(), [page(*HEAD, real, plant)])
    assert found is not None and found.kind == "undated" and found.item.date.type == "none"


def test_a_notice_whose_period_can_t_be_read_undates_the_to_do_whatever_the_others_say() -> None:
    """The real notice counts Werktage: a readable shorter period elsewhere never gives the date either."""
    real = "Gegen diesen Bescheid kann binnen 10 Werktagen nach Zustellung Einspruch eingelegt werden."
    other = "Der Widerspruch ist innerhalb von zwei Wochen nach Bekanntgabe einzulegen."
    for lines in ((real, other), (other, real)):
        found = check_item(blank(), [page(*HEAD, *lines)])
        assert found is not None and found.kind == "undated" and found.item.date.type == "none"


#: A decision without a date anywhere (the reading has none either).
UNDATED_HEAD = (LETTERHEAD, "Frau Mara Probe", "Gebührenbescheid", "Sehr geehrte Frau Probe,")


def test_without_a_start_a_month_and_thirty_days_can_t_be_ranked() -> None:
    """Which ends first depends on the start (February or not): with none known, no date at all."""
    month = "Der Widerspruch ist innerhalb eines Monats nach Zustellung einzulegen."
    days = "Gegen diesen Bescheid kann innerhalb von 30 Tagen nach Zustellung Widerspruch erhoben werden."
    found = check_item(blank(), [page(*UNDATED_HEAD, month, days)])
    assert found is not None and found.kind == "undated" and found.item.date.type == "none"


def test_without_a_start_four_weeks_end_before_a_month() -> None:
    """A month is never shorter than four weeks: the four weeks count, whichever notice counts from what."""
    weeks = "Der Widerspruch ist innerhalb von vier Wochen nach Bekanntgabe einzulegen."
    month = "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung Widerspruch erhoben werden."
    for lines in ((weeks, month), (month, weeks)):
        found = check_item(blank(), [page(*UNDATED_HEAD, *lines)])
        assert found is not None and (found.item.date.amount, found.item.date.unit) == (4, "weeks")
        assert found.item.date.anchor == "document_date" and found.item.date.delivery_rule == "none"


@pytest.mark.parametrize("region", [None, "NW"])
def test_delivery_days_only_when_the_period_ends_first_from_any_start_they_give(region: str | None) -> None:
    """From Thu 28 Jan 2027 thirty days end before a month, but from the day the letter counts as delivered a
    month ends first: with delivery days the thirty would end on Wed 3 Mar, after the month alone (Mon 1 Mar).
    So no delivery days: never later than either notice alone."""
    notices = (
        "Gegen diesen Bescheid kann innerhalb von 30 Tagen nach Bekanntgabe Widerspruch erhoben werden.",
        "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen.",
    )
    pages = [page(*head("28.01.2027"), *notices)]
    found = check_item(blank(), pages)
    assert found is not None and found.item.date.delivery_rule == "none"
    both = due(pages, region=region)
    singles = [due([page(*head("28.01.2027"), notice)], region=region) for notice in notices]
    assert both is not None and all(single is not None and both <= single for single in singles)


def test_a_planted_shorter_period_only_makes_the_date_earlier() -> None:
    shorter = "Der Widerspruch ist innerhalb von zwei Wochen nach Bekanntgabe einzulegen."
    assert due([page(*HEAD, NOTIFIED, shorter)]) == "2026-11-23" < NOTIFIED_DUE


@pytest.mark.parametrize(
    "text",
    [
        "Der Widerspruch ist innerhalb von zwei Monaten, spätestens aber innerhalb eines Monats nach Bekanntgabe einzulegen.",
        "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe, bei Bekanntgabe im Ausland innerhalb von drei Monaten einzulegen.",
    ],
)
def test_of_two_periods_in_one_sentence_the_one_ending_first_counts(text: str) -> None:
    assert due([page(*HEAD, text)]) == NOTIFIED_DUE


def test_periods_are_ranked_by_the_day_they_end() -> None:
    """From 01.02.2027 one month ends on 01.03, thirty days on 03.03: the month counts."""
    month = "Der Widerspruch ist innerhalb eines Monats nach Zustellung einzulegen."
    days = "Gegen diesen Bescheid kann innerhalb von 30 Tagen nach Zustellung Widerspruch erhoben werden."
    pages = [page(*head("01.02.2027"), days, month)]
    found = check_item(blank(), pages)
    assert found is not None and (found.item.date.amount, found.item.date.unit) == (1, "months")
    assert due(pages) == "2027-03-01"


@pytest.mark.parametrize("start", ["06.11.2026", "29.01.2027"])
@pytest.mark.parametrize("region", [None, "NW"])
def test_of_two_notices_with_different_starts_the_date_is_never_later_than_either_alone(
    start: str, region: str | None
) -> None:
    """Four weeks after notification is the shorter period, but with the days until the letter counts as
    delivered it can end after one month from service: then neither start's delivery days count."""
    notices = (
        "Der Widerspruch ist innerhalb von vier Wochen nach Bekanntgabe einzulegen.",
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung Widerspruch erhoben werden.",
    )
    both = due([page(*head(start), *notices)], region=region)
    singles = [due([page(*head(start), notice)], region=region) for notice in notices]
    assert both is not None and all(single is not None and both <= single for single in singles)
    found = check_item(blank(), [page(*head(start), *notices)])
    assert found is not None and (found.item.date.amount, found.item.date.unit) == (4, "weeks")
    assert found.item.date.delivery_rule == "none"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (
            "Gegen diesen Bescheid kann innerhalb von 31 Tagen nach Zustellung Widerspruch erhoben werden.",
            "dated",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb von vier Wochen nach Zustellung Widerspruch erhoben werden.",
            "dated",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb von sieben Tagen nach Zustellung Widerspruch erhoben werden.",
            "dated",
        ),
        # longer than a month, or shorter than a week: never a date of its own
        (
            "Gegen diesen Bescheid kann innerhalb von 32 Tagen nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb von fünf Wochen nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb von zwei Monaten nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb von sechs Tagen nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        (
            "Gegen diesen Bescheid kann binnen eines Tages nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        # a period the parser can't count, or one it rejects
        (
            "Gegen diesen Bescheid kann innerhalb von 0 Tagen nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        (
            "Gegen diesen Bescheid kann binnen 10 Werktagen nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        (
            "Gegen diesen Bescheid kann innerhalb eines Jahres nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        (
            "Gegen diesen Bescheid kann binnen eines Kalendermonats nach Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
        # one period read, one not: the one not read may be the shorter
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats, spätestens jedoch binnen 10 Werktagen nach "
            "Zustellung Widerspruch erhoben werden.",
            "undated",
        ),
    ],
)
def test_only_a_period_from_a_week_to_a_month_is_dated(text: str, kind: str) -> None:
    found = check_item(blank(), [page(*HEAD, text)])
    assert found is not None and found.kind == kind
    assert (found.item.date.type == "none") is (kind == "undated")


def test_a_period_of_nothing_is_no_period() -> None:
    found = notice(
        "Gegen diesen Bescheid kann innerhalb von 0 Tagen nach Zustellung Widerspruch erhoben werden."
    )
    assert found.periods == () and not found.datable


def test_a_monatsfrist_is_one_month() -> None:
    found = notice("Der Widerspruch ist binnen der Monatsfrist nach Bekanntgabe einzulegen.")
    assert found.periods == ((1, "months"),) and found.notified


# --------------------------------------------------------------------------------------------------
# The sentence after the notice
# --------------------------------------------------------------------------------------------------


def test_the_period_in_the_next_sentence_counts_and_its_start_too() -> None:
    text = "Gegen diesen Bescheid kann Widerspruch erhoben werden. Die Frist beträgt einen Monat nach Bekanntgabe."
    found = notice(text)
    assert (found.periods, found.notified, found.remedy, found.live) == (
        ((1, "months"),),
        True,
        "widerspruch",
        True,
    )
    assert found.quote.endswith(text)


def test_of_a_notice_and_the_sentence_after_it_the_shorter_period_counts() -> None:
    """The sentence after a notice may go on about its period: its period counts too (only ever earlier)."""
    text = (
        "Gegen diesen Bescheid über Ihre Sondernutzung für die nächsten sechs Monate ist der Widerspruch zulässig. "
        "Er ist innerhalb eines Monats nach Bekanntgabe schriftlich einzulegen."
    )
    assert due([page(*HEAD, text)]) == NOTIFIED_DUE


@pytest.mark.parametrize("start", ["Zustellung", "Zugang", "Erhalt"])
def test_a_start_from_service_in_the_next_sentence_counts_without_delivery_days(start: str) -> None:
    text = f"Nach Bekanntgabe dieses Bescheids kann Widerspruch erhoben werden. Die Frist beträgt einen Monat ab {start}."
    found = check_item(blank(), [page(*HEAD, text)])
    assert found is not None and (found.item.date.anchor, found.item.date.delivery_rule) == (
        "explicit_date",
        "none",
    )
    assert due([page(*HEAD, text)]) == FROM_LETTER_DUE


@pytest.mark.parametrize(
    "money",
    [
        "Bitte zahlen Sie die Gebühr innerhalb von zwei Wochen.",
        "Bitte überweisen Sie die Gebühr innerhalb von zwei Wochen.",
        "Die Gebühr wird innerhalb von zwei Wochen fällig.",
        "Der Betrag ist innerhalb von zwei Wochen auszugleichen.",
        "Please pay the fee within two weeks.",
        "The fee is due within two weeks.",
    ],
)
def test_a_payment_sentence_after_the_notice_is_no_part_of_it(money: str) -> None:
    assert (
        remedy_notices([page(*HEAD, f"Gegen diesen Bescheid kann Widerspruch erhoben werden. {money}")]) == []
    )


def test_a_remark_after_a_notice_with_its_own_period_never_silences_it() -> None:
    """The sentence after counts for the date, but whether the notice is live is read from its own words: a
    remark about a direct debit after it (folded, as it names neither a remedy nor a payment) is no reason."""
    text = f"{NOTIFIED} Ein bestehendes Lastschriftmandat bleibt davon unberührt."
    [found] = remedy_notices([page(*HEAD, text)])
    assert found.live and "Lastschriftmandat" in found.text
    reading = blank(sender=SENDER, document_date="2026-11-06")
    assert reading_gap(reading, [page(*HEAD, text)], [found]) == "remedy_left_out"


def test_a_next_sentence_naming_a_remedy_is_its_own_notice_never_folded() -> None:
    text = (
        "Gegen diesen Bescheid ist ein Widerspruch statthaft. "
        "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen."
    )
    assert len(remedy_notices([page(*HEAD, text)])) == 1


# --------------------------------------------------------------------------------------------------
# Direction and start words
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Ein Widerspruch ist spätestens zwei Wochen vor der Verhandlung zu begründen.",
        "Ein Widerspruch ist spätestens zwei Wochen vor dem Termin zu begründen.",
        "Ein Widerspruch ist spätestens zwei Monate vor Mietende einzulegen (§ 574b BGB).",
        "Ein Widerspruch ist zwei Wochen, spätestens vor Beendigung des Verfahrens, zu begründen.",
        "An objection must be lodged two months before your tenancy ends.",
        "An objection must be lodged two weeks prior to the hearing.",
        "An objection must be lodged two weeks before the hearing.",
        "Ein Widerspruch ist spätestens zwei Wochen, bevor die Verhandlung beginnt, zu begründen.",
        # the backward period in the folded sentence after the notice
        "Gegen diesen Bescheid kann Widerspruch erhoben werden. Die Begründung ist zwei Wochen vor der Anhörung einzureichen.",
    ],
)
def test_a_period_counted_back_from_an_event_is_never_dated_forward(text: str) -> None:
    found = check_item(blank(), [page(*HEAD, text)])
    assert found is not None and found.kind == "undated" and found.item.date.type == "none"


@pytest.mark.parametrize(
    "text",
    [
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung Klage vor dem Verwaltungsgericht Beispielstadt erhoben werden.",
        "Gegen diesen Bescheid kann innerhalb eines Monats Klage vor dem Sozialgericht Beispielstadt erhoben werden.",
        # "vor" right after the start: the start runs forward from this letter
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung vor dem Sozialgericht Beispielstadt Klage erhoben werden.",
        "Der Widerspruch ist vor Ablauf eines Monats nach Bekanntgabe einzulegen.",
        "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen; die Frist ist nur gewahrt, wenn er vor Ablauf der Frist eingeht.",
    ],
)
def test_vor_that_doesn_t_follow_a_period_keeps_the_notice_forward(text: str) -> None:
    found = check_item(blank(), [page(*HEAD, text)])
    assert (
        found is not None
        and found.kind == "dated"
        and (found.item.date.amount, found.item.date.unit) == (1, "months")
    )


@pytest.mark.parametrize(
    "text",
    [
        "Gegen diesen Bescheid kann innerhalb eines Monats, nachdem er Ihnen bekannt gegeben wurde, Widerspruch erhoben werden.",
        "Gegen diesen Bescheid kann innerhalb eines Monats, nachdem er Ihnen bekanntgegeben wurde, Widerspruch erhoben werden.",
        "You may object to this decision within one month of notification.",
        "You may object to this decision within one month after you were notified.",
    ],
)
def test_every_notification_wording_counts_with_delivery_days(text: str) -> None:
    assert notice(text).notified


@pytest.mark.parametrize(
    "start",
    [
        "nach Zustellung",
        "nachdem er zugestellt wurde",
        "nach Zugang",
        "nachdem er zugegangen ist",
        "nach Erhalt",
        "nach dem Zustellungsdatum",
    ],
)
def test_a_start_from_service_or_arrival_beats_notification_in_the_same_sentence(start: str) -> None:
    text = f"Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe, spätestens {start} des Bescheids, einzulegen."
    assert not notice(text).notified
    assert due([page(*HEAD, text)]) == FROM_LETTER_DUE


@pytest.mark.parametrize("start", ["receipt", "service", "being served"])
def test_english_service_or_arrival_beats_notification(start: str) -> None:
    assert not notice(
        f"You may object within one month of notification or {start} of this decision."
    ).notified


def test_notify_is_the_person_s_own_act_not_a_notification() -> None:
    text = "If you wish to appeal against this decision, please notify us in writing within two weeks."
    assert not notice(text).notified
    assert due([page(*HEAD, text)]) == "2026-11-20"


def test_a_notice_naming_no_start_counts_from_the_letter_s_date() -> None:
    text = "Gegen diesen Bescheid kann innerhalb eines Monats Widerspruch eingelegt werden."
    found = check_item(blank(), [page(*HEAD, text)])
    assert found is not None and (found.item.date.anchor, found.item.date.delivery_rule) == (
        "explicit_date",
        "none",
    )
    assert due([page(*HEAD, text)]) == FROM_LETTER_DUE


def test_formal_service_counts_from_the_letter_s_date_and_a_portal_from_the_day_after() -> None:
    served = page(*HEAD[:6], "Mit Postzustellungsurkunde", *HEAD[6:], NOTIFIED)
    assert due([served]) == FROM_LETTER_DUE
    portal = page(*HEAD, "Dieser Bescheid wurde Ihnen im Bürgerportal zum Abruf bereitgestellt.", NOTIFIED)
    found = check_item(blank(), [portal])
    assert found is not None and found.item.date.delivery_rule == "de_admin_portal"
    assert due([portal]) == FROM_LETTER_DUE


def test_on_a_tie_the_notice_without_delivery_days_is_quoted() -> None:
    served = "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung Widerspruch erhoben werden."
    notified = "Der Widerspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen."
    found = check_item(blank(), [page(*HEAD, notified, served)])
    assert found is not None and found.item.quote == served


def test_on_a_tie_the_remedy_before_a_court_action_is_named() -> None:
    widerspruch = (
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
    )
    klage = "Alternativ kann innerhalb eines Monats Klage beim Verwaltungsgericht erhoben werden."
    found = check_item(blank(), [page(*HEAD, klage, widerspruch)])
    assert found is not None and found.remedy == "widerspruch"
    assert due([page(*HEAD, klage, widerspruch)]) == FROM_LETTER_DUE  # mixed starts: no delivery days


# --------------------------------------------------------------------------------------------------
# Remedy words, titles and the action
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "remedy", "title"),
    [
        (
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Klage beim Verwaltungsgericht erhoben werden.",
            "klage",
            "Deadline for a court action (Klage)",
        ),
        (
            "Gegen diesen Widerspruchsbescheid kann innerhalb eines Monats nach Bekanntgabe Klage beim Sozialgericht erhoben werden.",
            "klage",
            "Deadline for a court action (Klage)",
        ),
        (
            "Gegen diese Einspruchsentscheidung kann innerhalb eines Monats nach Bekanntgabe Klage beim Finanzgericht erhoben werden.",
            "klage",
            "Deadline for a court action (Klage)",
        ),
        (
            "You may lodge an objection to this decision within one month of notification.",
            "objection",
            "Deadline to object",
        ),
        (
            "You may object to this decision within one month of notification.",
            "objection",
            "Deadline to object",
        ),
        (
            "You may appeal against this decision within one month of notification.",
            "objection",
            "Deadline to object",
        ),
    ],
)
def test_every_remedy_word_gives_a_notice_and_its_title(text: str, remedy: str, title: str) -> None:
    found_notice = notice(text)
    assert (found_notice.periods, found_notice.notified, found_notice.remedy) == (
        ((1, "months"),),
        True,
        remedy,
    )
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[payment()])
    found = check_item(reading, [page(*HEAD, PAY, text)])
    assert found is not None and found.item.title == title
    court = remedy == "klage"
    assert (found.item.action, found.item.consequence) == (
        (KLAGE_ACTION, KLAGE_CONSEQUENCE) if court else (DEADLINE_ACTION, DEADLINE_CONSEQUENCE)
    )


def test_a_court_action_left_out_gets_its_own_warning_and_the_advice_note() -> None:
    text = "Gegen diesen Bescheid kann innerhalb eines Monats nach Zustellung Klage beim Verwaltungsgericht erhoben werden."
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[payment()])
    verification = verify_extraction("doc_x", reading, [page(*HEAD, PAY, text)], check_reading=True)
    assert verification.warnings[-2:] == [
        gap_warning("remedy_left_out", "dated", "klage"),
        *remedy_warnings(Remedy(type="klage")),
    ]
    assert gap_warning("remedy_left_out", "dated", "klage").startswith(
        "This letter explains how to challenge it in court"
    )
    # the reading named the court action already: its own advice warning comes with it, not twice
    named = reading.model_copy(update={"remedy": Remedy(type="klage")})
    verification = verify_extraction("doc_x", named, [page(*HEAD, PAY, text)], check_reading=True)
    assert remedy_warnings(Remedy(type="klage"))[0] not in verification.warnings


def test_a_letter_addressed_to_an_ai_gets_where_to_send_the_objection() -> None:
    """Detected text addressed to an AI, or an almost blank reading (security review 2, F5: a detector can miss
    the injection that blanked it): the action says where to send the objection. Not on a reading that only
    left the objection out, unless the injection was detected."""
    for injected in (True, False):
        found = check_item(blank(), [DECISION], injected=injected)
        assert found is not None and found.item.action == f"{DEADLINE_ACTION} {KNOWN_ADDRESS}"
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[payment()])
    found = check_item(reading, [page(*HEAD, PAY, NOTIFIED)], injected=True)
    assert found is not None and found.item.action == f"{DEADLINE_ACTION} {KNOWN_ADDRESS}"
    found = check_item(reading, [page(*HEAD, PAY, NOTIFIED)])
    assert found is not None and found.item.action == DEADLINE_ACTION


def test_the_check_item_quotes_the_notice_not_the_page() -> None:
    found = check_item(blank(), [page(*HEAD, NOTIFIED, "Der Widerspruch ist schriftlich einzulegen.")])
    assert found is not None
    assert found.item.quote == NOTIFIED and found.item.date.text == found.item.quote


def test_a_notice_written_across_lines_is_joined_as_quotes_are() -> None:
    lines = (
        "Gegen diesen Bescheid kann binnen eines Mo-",
        "nats nach Bekanntgabe Wider-",
        "spruch erhoben werden.",
    )
    found = check_item(blank(), [page(*HEAD, *lines)])
    assert found is not None and found.kind == "dated" and found.remedy == "widerspruch"
    verified = checked(blank(), [page(*HEAD, *lines)])
    assert verified.evidence.grounding == "verified"
    # a capital after the hyphen is no word split across lines (as normalize joins them)
    assert (
        remedy_notices(
            [page(*HEAD, "Gegen diesen Bescheid kann binnen eines Mo-", "Nats Widerspruch erhoben werden.")]
        )
        == []
    )


def test_a_run_on_page_gets_a_bounded_quote_located_at_once() -> None:
    """A page of text without full stops is one long "sentence": the quote keeps the notice's words only."""
    filler = " ".join(f"zeile {number} ohne satzende" for number in range(800))
    pages = [page(*HEAD[:7], filler + " " + NOTIFIED)]
    found = check_item(blank(), pages)
    assert found is not None and len(found.item.quote) <= QUOTE_CAP and "Widerspruch" in found.item.quote
    verified = checked(blank(), pages)
    assert verified.evidence.grounding == "verified"
    # the remedy word and the period further apart than a quote holds: no date from it
    far = " ".join(f"zeile {number} ohne satzende" for number in range(200))
    found = check_item(
        blank(), [page(*HEAD, f"Ein Widerspruch kann {far} binnen eines Monats eingelegt werden.")]
    )
    assert found is not None and found.kind == "undated" and len(found.item.quote) <= QUOTE_CAP


# --------------------------------------------------------------------------------------------------
# The letter's date
# --------------------------------------------------------------------------------------------------


def written(
    *lines: str, reading: DocumentExtraction | None = None, pages: tuple[Any, ...] = ()
) -> date | None:
    return letter_date(
        reading or blank(), [page(LETTERHEAD, *lines, "Sehr geehrte Frau Probe,", NOTIFIED), *pages]
    )


def test_the_letter_s_date_is_the_earliest_it_gives_for_itself() -> None:
    assert written("Beispielhausen, 06.11.2026") == date(2026, 11, 6)
    assert written("Beispielhausen, den 06.11.2026") == date(2026, 11, 6)
    # a date alone in the header is weak: it lowers a start, never sets one (dates review 2, finding 3)
    assert written("Frau Mara Probe", "06.11.2026") is None
    assert written("Frau Mara Probe", "06.11.2026", reading=blank(document_date="2026-11-10")) == date(
        2026, 11, 6
    )
    assert written("Datum 06.11.2026") == date(2026, 11, 6)
    assert written("Bescheiddatum: 06.11.2026") == date(2026, 11, 6)
    assert written("Erstellt am 06.11.2026") == date(2026, 11, 6)
    # every tier counts: the earliest, whatever its tier or order
    assert written("Datum: 06.11.2026", "Beispielhausen, 02.11.2026") == date(2026, 11, 2)
    assert written(
        "Datum: 20.11.2026", "Mit diesem Bescheid vom 06.11.2026 setzen wir eine Gebühr fest."
    ) == date(2026, 11, 6)
    assert written(
        "Mit diesem Bescheid vom 06.11.2026 setzen wir eine Gebühr fest.", "Datum: 20.11.2026"
    ) == date(2026, 11, 6)
    assert written("Datum: 06.11.2026", reading=blank(document_date="2026-11-04")) == date(2026, 11, 4)
    assert written("Datum: 06.11.2026", reading=blank(document_date="2026-11-04T09:00:00")) == date(
        2026, 11, 4
    )
    assert written("Datum: 06.11.2026", reading=blank(document_date="2026-11-20")) == date(2026, 11, 6)
    # a reading with a later date of its own: the remedy-left-out path, counted from the letter's date
    found = check_item(blank(document_date="2026-11-20"), [DECISION])
    assert (
        found is not None and found.gap == "remedy_left_out" and found.item.date.anchor_date == "2026-11-06"
    )


@pytest.mark.parametrize(
    "plant",
    [
        "Mit diesem Bescheid vom 20.11.2026 setzen wir eine Gebühr fest.",
        "Beispielhausen, 20.11.2026",
        "Datum: 20.11.2026",
    ],
)
@pytest.mark.parametrize("real", ["Datum: 06.11.2026", "Beispielhausen, 06.11.2026", "06.11.2026"])
def test_a_later_date_planted_in_any_tier_never_moves_the_start_later(real: str, plant: str) -> None:
    assert written("Frau Mara Probe", real, plant) == date(2026, 11, 6)
    assert (
        due([page(LETTERHEAD, "Frau Mara Probe", real, plant, "Sehr geehrte Frau Probe,", NOTIFIED)])
        == NOTIFIED_DUE
    )


def test_a_reading_s_date_far_from_the_letter_s_gives_no_date_never_the_later_one() -> None:
    """The reading's date three weeks after the page's: counting from either could be wrong, and from the
    stored (reading's) date it would be later than the letter allows — so the to-do gets no date at all."""
    reading = blank(
        sender=ExtractedParty(name="Stadtwerke Beispielhausen", kind="utility"),
        document_date="2026-11-26",
        items=[payment()],
    )
    pages = [page(*HEAD, PAY, NOTIFIED)]
    found = check_item(reading, pages)
    assert found is not None and found.kind == "undated" and found.item.date.type == "none"
    for private in (False, True):
        assert due(pages, reading=reading, private_sender=private) is None


def test_dates_too_far_apart_give_no_start_never_a_wrong_one() -> None:
    # planted early, or the reading's early date: the deadline would lie in the past
    assert (
        written("Datum: 06.11.2026", "Die Angaben in diesem Schreiben vom 02.01.2026 gelten unverändert.")
        is None
    )
    assert written("Datum: 06.11.2026", reading=blank(document_date="2026-01-02")) is None
    # a later one more than two weeks after the real date
    assert written("Datum: 06.11.2026", "Beispielhausen, 21.11.2026") is None
    found = check_item(blank(document_date="2026-01-02", sender=SENDER), [DECISION])
    assert found is not None and found.kind == "undated"


def test_a_notice_about_an_earlier_decision_counts_from_that_decision() -> None:
    """A reminder repeating the notice of the decision of 01.10.2026: never 19 days late — its date is the
    earlier one, more than two weeks before the reminder's own, so the to-do gets no date."""
    reminder = page(
        LETTERHEAD,
        "Datum: 20.10.2026",
        "Zahlungserinnerung",
        "Sehr geehrte Frau Probe,",
        PAY,
        "Gegen den Bescheid vom 01.10.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
    )
    [found_notice] = remedy_notices([reminder])
    assert found_notice.issued == (date(2026, 10, 1),)
    reading = blank(sender=SENDER, document_date="2026-10-20", items=[payment()])
    found = check_item(reading, [reminder])
    assert found is not None and found.kind == "undated"
    close = page(
        LETTERHEAD,
        "Datum: 06.11.2026",
        "Sehr geehrte Frau Probe,",
        "Gegen den Bescheid vom 02.11.2026 können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
    )
    assert letter_date(blank(), [close]) == date(2026, 11, 2)


def test_the_decision_a_ruling_on_an_objection_reshapes_is_not_its_date() -> None:
    """ "Den Bescheid vom 01.08.2026 in Gestalt dieses Widerspruchsbescheids": the court action runs from this
    letter (06.11.2026), not from the old decision's date."""
    ruling = (
        "Gegen den Bescheid vom 01.08.2026 in Gestalt dieses Widerspruchsbescheids kann innerhalb eines Monats "
        "nach Zustellung Klage beim Verwaltungsgericht Beispielstadt erhoben werden."
    )
    pages = [page(*HEAD, ruling)]
    [found] = remedy_notices(pages)
    assert found.issued == () and found.remedy == "klage"
    assert letter_date(blank(), pages) == date(2026, 11, 6)
    assert due(pages) == FROM_LETTER_DUE


def test_the_page_with_the_notice_gives_its_own_date() -> None:
    first = page(LETTERHEAD, "Frau Mara Probe", "Sehr geehrte Frau Probe,", "anbei unser Bescheid.")
    second = page(
        "Stadt Beispielhausen",
        "Datum 06.11.2026",
        "Gebührenbescheid",
        "Sehr geehrte Frau Probe,",
        NOTIFIED,
        number=2,
    )
    # a continuation page's date is weak (dates review 2, finding 10): it never sets the start alone
    assert letter_date(blank(), [first, second]) is None
    assert letter_date(blank(document_date="2026-11-09"), [first, second]) == date(2026, 11, 6)
    # a covering letter dated three weeks after the decision: two dates for itself, so no start at all
    cover = page(LETTERHEAD, "Datum: 27.11.2026", "Sehr geehrte Frau Probe,", "anbei unser Bescheid.")
    assert letter_date(blank(), [cover, second]) is None


@pytest.mark.parametrize(
    "lines",
    [
        ("Frau Mara Probe", "Zahlbar bis Freitag, 04.12.2026"),
        ("Frau Mara Probe", "Fällig am Montag, 07.12.2026"),
        ("Frau Mara Probe", "Anhörung am Mittwoch, 18.11.2026"),
        ("Datum 06.11.2026", "Fälligkeit", "07.12.2026"),
        ("Bescheiddatum: 06.11.2026", "Zahlungsziel", "07.12.2026"),
        ("Datum 06.11.2026", "Leistungsbeginn", "01.12.2026"),
        ("Datum 06.11.2026", "Valid until", "31.12.2026"),
        ("Datum 06.11.2026", "Fälligkeitsdatum: 07.12.2026"),
        ("Datum 06.11.2026", "Termin:", "Mittwoch", "18.11.2026"),
    ],
)
def test_a_due_day_a_validity_or_an_appointment_is_not_the_letter_s_date(lines: tuple[str, ...]) -> None:
    got = written(*lines)
    assert got is None or got == date(2026, 11, 6)
    assert written("Frau Mara Probe", "Datum: 06.11.2026", *lines[1:]) == date(2026, 11, 6)


def test_a_place_and_date_after_the_notice_is_not_the_letter_s() -> None:
    lines = (
        "Stadt Beispielhausen",
        "Frau Mara Probe",
        "Datum: 06.11.2026",
        "Sehr geehrte Frau Probe,",
        NOTIFIED,
        "Beispielhausen, 30.11.2026",
    )
    assert letter_date(blank(), [page(*lines)]) == date(2026, 11, 6)


def test_a_bare_date_in_the_body_or_not_ending_its_line_is_not_the_letter_s() -> None:
    body = ("Stadt Beispielhausen", "Sehr geehrte Frau Probe,", "Ihr Termin:", "01.10.2026", NOTIFIED)
    assert letter_date(blank(), [page(*body)]) is None
    # under the salutation, a bare date is the body's, whatever the line above it says
    dated = (
        LETTERHEAD,
        "Frau Mara Probe",
        "Datum 06.11.2026",
        "Sehr geehrte Frau Probe,",
        "30.11.2026",
        NOTIFIED,
    )
    assert letter_date(blank(), [page(*dated)]) == date(2026, 11, 6)
    assert written("06.11.2026 (Eingang)") is None


@pytest.mark.parametrize(
    "label", ["vom", "seit", "bis", "ab", "am", "zum", "Antrag", "geboren", "Geburtsdatum"]
)
def test_a_date_under_a_label_of_another_date_is_not_the_letter_s(label: str) -> None:
    assert written(f"Gültig {label}", "01.10.2026") is None
    assert written(f"Ihr Schreiben {label}", "01.10.2026") is None


# --------------------------------------------------------------------------------------------------
# Recomputing: an earlier start moves it earlier, never later
# --------------------------------------------------------------------------------------------------


def test_a_private_sender_keeps_the_letter_s_date_as_the_start() -> None:
    """A Stadtwerk's decision filed as a utility: no deemed delivery, but the start stays the letter's date,
    not the reading's (later) one."""
    reading = blank(
        sender=ExtractedParty(name="Stadtwerke Beispielhausen", kind="utility"),
        document_date="2026-11-16",
        items=[payment()],
    )
    verified = checked(reading, [page(*HEAD, PAY, NOTIFIED)])
    authority = compute_item(verified, ctx_for(reading), postal_buffer_days=3)
    private = compute_item(
        verified, ctx_for(reading, private_sender=True, sender_kind="utility"), postal_buffer_days=3
    )
    assert authority.due_date == NOTIFIED_DUE and private.due_date == FROM_LETTER_DUE
    assert private.receipt is not None and any(
        "earlier than the date stored" in note for note in private.receipt.warnings
    )


@pytest.mark.parametrize(
    "text",
    [NOTIFIED, "Gegen diesen Bescheid kann innerhalb eines Monats nach Erhalt Widerspruch erhoben werden."],
)
def test_an_earlier_stored_date_or_arrival_moves_it_earlier_never_later(text: str) -> None:
    verified = checked(blank(), [page(*HEAD, text)])
    plain = compute_item(verified, RuleContext(today=TODAY), postal_buffer_days=3).due_date
    for stored in (date(2026, 11, 2), date(2026, 11, 6), date(2026, 11, 20), date(2026, 12, 1)):
        for arrival in (None, date(2026, 11, 4), date(2026, 11, 9)):
            ctx = RuleContext(
                today=TODAY,
                document_date=stored,
                received_date=arrival,
                received_confirmed=arrival is not None,
            )
            moved = compute_item(verified, ctx, postal_buffer_days=3).due_date
            assert moved is not None and plain is not None and moved <= plain, (stored, arrival)
    arrived = RuleContext(
        today=TODAY, document_date=date(2026, 11, 6), received_date=date(2026, 11, 4), received_confirmed=True
    )
    assert compute_item(verified, arrived, postal_buffer_days=3).due_date == "2026-12-04"


def test_an_early_arrival_is_a_start_only_for_a_period_without_delivery_days() -> None:
    """A period from notification already counts the delivery days from the letter's date: an arrival before
    that date is no start of its own (it would add the delivery days to it)."""
    arrived = RuleContext(
        today=TODAY, document_date=date(2026, 11, 6), received_date=date(2026, 11, 4), received_confirmed=True
    )
    for rule, variants in (("de_admin_post", 1), ("de_admin_portal", 1), ("none", 2)):
        spec = DateSpec(
            type="relative",
            amount=1,
            unit="months",
            anchor="explicit_date",
            anchor_date="2026-11-06",
            delivery_rule=rule,
            nature="objection",
        )
        found = start_variants(spec, arrived)
        assert len(found) == variants, rule
        assert {variant.anchor_date for variant, _ in found} <= {"2026-11-06", "2026-11-04"}


def test_an_old_check_item_without_a_start_counts_from_the_stored_letter_date() -> None:
    spec = DateSpec(
        type="relative",
        amount=1,
        unit="months",
        anchor="explicit_date",
        delivery_rule="none",
        nature="objection",
    )
    item = ExtractedItem(kind="deadline", title="Deadline to object", date=spec, quote=NOTIFIED)
    verified = VerifiedItem(
        item=item,
        evidence=checked(blank(), [DECISION]).evidence,
        reasons=(READING_INCOMPLETE,),
        slot_key=CHECK_SLOT,
    )
    assert compute_item(verified, RuleContext(today=TODAY), postal_buffer_days=3).due_date is None
    stored = RuleContext(today=TODAY, document_date=date(2026, 11, 6))
    assert compute_item(verified, stored, postal_buffer_days=3).due_date == FROM_LETTER_DUE


def test_a_tenancy_rule_never_reads_the_check_item_s_start_as_the_tenancy_s_end() -> None:
    spec = DateSpec(
        type="relative",
        amount=1,
        unit="months",
        anchor="explicit_date",
        anchor_date="2026-11-06",
        delivery_rule="none",
        nature="objection",
        text="Widerspruch nach § 574b BGB binnen eines Monats",
    )
    ctx = RuleContext(today=TODAY, letter_kind="landlord_notice")
    [(plain, plain_ctx), *_] = start_variants(spec, ctx)
    assert plain_ctx.letter_kind is None and plain.text == ""
    item = ExtractedItem(kind="deadline", title="Deadline to object", date=spec, quote=NOTIFIED)
    verified = VerifiedItem(
        item=item,
        evidence=checked(blank(), [DECISION]).evidence,
        reasons=(READING_INCOMPLETE,),
        slot_key=CHECK_SLOT,
    )
    assert compute_item(verified, ctx, postal_buffer_days=3).due_date == FROM_LETTER_DUE


def test_the_check_item_is_graded_as_ordnung_s_own_date() -> None:
    monatsfrist = "Der Widerspruch ist binnen der Monatsfrist nach Bekanntgabe einzulegen."
    verified = checked(blank(), [page(*HEAD, monatsfrist)])
    assert verified.reasons == (READING_INCOMPLETE,)
    assert PERIOD_NOT_IN_QUOTE not in verified.reasons and DATE_NOT_IN_QUOTE not in verified.reasons


# --------------------------------------------------------------------------------------------------
# A reading that dates the objection weeks after the letter's own notice (spec 3.9(b))
# --------------------------------------------------------------------------------------------------


def _read_objection(
    spec: dict[str, Any], pages: Sequence[PageInput] = (DECISION,), **ctx: Any
) -> tuple[VerifiedItem, ComputedDate, DocumentExtraction]:
    """The reading's own objection to-do (``spec``, quoting the notice), verified and computed."""
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[objection(spec)])
    [verified] = verify_extraction("doc_x", reading, pages, check_reading=True).items
    return verified, compute_item(verified, ctx_for(reading, **ctx), postal_buffer_days=3), reading


THREE_MONTHS = {
    "type": "relative",
    "amount": 3,
    "unit": "months",
    "anchor": "deemed_delivery",
    "delivery_rule": "de_admin_post",
}


def test_an_objection_date_weeks_after_the_notice_gets_the_notice_s_date_and_please_check() -> None:
    """The reading's "three months" (a planted extension, say) ends on Tue 9 Feb 2027; the letter's own notice
    gives one month, Wed 9 Dec 2026: the earlier is kept, both are named, and the to-do is "Please check"."""
    verified, computed, _ = _read_objection(THREE_MONTHS)
    assert verified.notice is not None and verified.notice.statement in NOTIFIED
    assert computed.due_date == NOTIFIED_DUE and computed.conflict and computed.notice
    assert computed.receipt is not None and computed.receipt.confidence == "low"
    assert any("2027" in note and "We use the earlier one" in note for note in computed.receipt.warnings)
    assert not checked_evidence(verified, computed).value_consistent
    alone = compute_item(
        replace(verified, notice=None), ctx_for(blank(document_date="2026-11-06")), postal_buffer_days=3
    )
    assert alone.due_date == "2027-02-09" and not alone.conflict


@pytest.mark.parametrize(
    ("written", "kept"),
    [
        ("2026-12-01", "2026-12-01"),  # earlier than the notice: the reading's
        ("2026-12-14", "2026-12-14"),  # 5 days later: within reach (a start or delivery days), the reading's
        ("2026-12-16", "2026-12-16"),  # 7 days later: still the reading's
        ("2026-12-17", NOTIFIED_DUE),  # 8 days later: the notice's
        ("2026-12-24", NOTIFIED_DUE),
        ("2027-03-31", NOTIFIED_DUE),
    ],
)
def test_only_a_date_more_than_a_week_after_the_notice_gets_it(written: str, kept: str) -> None:
    _, computed, _ = _read_objection({"type": "fixed", "date": written})
    assert computed.due_date == kept
    assert computed.notice is (kept != written)


@pytest.mark.parametrize("amount", [1, 2, 3, 6, 12])
@pytest.mark.parametrize("unit", ["weeks", "months"])
@pytest.mark.parametrize("anchor", ["deemed_delivery", "document_date", "receipt"])
@pytest.mark.parametrize("region", [None, "NW"])
def test_the_notice_beside_an_objection_date_never_makes_it_later(
    amount: int, unit: str, anchor: str, region: str | None
) -> None:
    spec = {
        "type": "relative",
        "amount": amount,
        "unit": unit,
        "anchor": anchor,
        "delivery_rule": "de_admin_post",
    }
    verified, guarded, reading = _read_objection(spec, region=region)
    ctx = ctx_for(reading, region=region)
    plain = compute_item(replace(verified, notice=None), ctx, postal_buffer_days=3)
    assert guarded.due_date is not None and plain.due_date is not None
    assert guarded.due_date <= plain.due_date
    if guarded.notice:
        assert guarded.due_date < plain.due_date and guarded.receipt is not None
        assert guarded.receipt.confidence == "low"


@pytest.mark.parametrize(
    "notice_line",
    [
        # a period that can't be dated, one counted back from an event, a direct debit's
        "Gegen diesen Bescheid kann binnen 10 Werktagen nach Zustellung Widerspruch erhoben werden.",
        "Ein Widerspruch ist spätestens zwei Wochen vor der Verhandlung zu begründen.",
        "Einer Lastschrift können Sie innerhalb von acht Wochen nach der Belastung widersprechen.",
    ],
)
def test_no_notice_beside_it_when_the_check_couldn_t_date_one_itself(notice_line: str) -> None:
    verified, computed, _ = _read_objection(THREE_MONTHS, pages=[page(*HEAD, notice_line)])
    assert verified.notice is None and not computed.notice


def test_the_check_s_own_to_do_never_gets_the_notice_beside_it() -> None:
    verification = verify_extraction("doc_x", blank(), [DECISION], check_reading=True)
    assert [verified.notice for verified in verification.items] == [None]


# --------------------------------------------------------------------------------------------------
# Photos, the reading's parts, the words
# --------------------------------------------------------------------------------------------------


def test_on_a_photo_the_notice_is_read_from_the_transcript() -> None:
    pages = [page(*HEAD, NOTIFIED, source="transcript")]
    verified = checked(blank(), pages)
    assert verified.evidence.grounding == "model_read" and verified.needs_check
    computed = compute_item(verified, RuleContext(today=TODAY), postal_buffer_days=3)
    assert computed.due_date == NOTIFIED_DUE
    assert computed.receipt is not None and computed.receipt.confidence == "low"


@pytest.mark.parametrize(
    ("fields", "empty"),
    [
        ({"contract": ExtractedContract(name="Mitgliedschaft")}, False),
        ({"contract": ExtractedContract(name="")}, True),
        ({"contract": ExtractedContract(name="   ")}, True),
        ({"change": ExtractedChange(type="price_increase")}, False),
        ({"payment": PaymentDetails(iban="DE02120300000000202051")}, False),
        ({"payment": PaymentDetails()}, True),
        ({"remedy": Remedy(type="widerspruch")}, False),
        ({"remedy": Remedy(type="none")}, True),
        ({"sender": ExtractedParty(name="   ")}, True),
        ({"sender": ExtractedParty(name="Stadt")}, False),
        ({"document_date": "2026-11-06"}, False),
    ],
)
def test_every_part_of_the_reading_counts_for_r1(fields: dict[str, Any], empty: bool) -> None:
    pages = [page("Sehr geehrte Frau Probe,", "wir bestätigen Ihre Anmeldung.")]
    assert (reading_gap(blank(**fields), pages, []) == "empty") is empty


def test_no_warning_or_note_reads_as_a_doubtful_date_a_scam_or_an_injection() -> None:
    texts = [
        gap_warning(gap, kind, remedy)  # type: ignore[arg-type]
        for gap in ("empty", "remedy_left_out")
        for kind in ("dated", "undated", "read_yourself")
        for remedy in ("", "klage")
    ]
    texts += [
        REASON_TEXT[READING_INCOMPLETE],
        DEADLINE_ACTION,
        KLAGE_ACTION,
        KNOWN_ADDRESS,
        PLACEHOLDER_ACTION,
    ]
    texts += [DEADLINE_CONSEQUENCE, KLAGE_CONSEQUENCE, *remedy_warnings(Remedy(type="klage"))]
    for text in texts:
        assert not UNCERTAINTY_RE.search(text), text
        assert not SCAM_RE.search(text), text
        assert not INJECTION_RE.search(text), text


def test_the_warnings_say_what_the_spec_says() -> None:
    assert gap_warning("empty", "dated") == (
        "Claude's reading of this letter came back almost blank: the sender, the letter's date and its to-dos were "
        "all left out. Ordnung added the deadline from the letter's own instructions on how to object "
        "(Rechtsbehelfsbelehrung) — please check it against the letter before you rely on it."
    )
    assert gap_warning("remedy_left_out", "undated") == (
        "This letter explains how to object, but Claude's reading left out the deadline to object. Ordnung found the "
        "letter's instructions on how to object but couldn't work out the deadline from them — please find it in the "
        "letter and enter it with “Set a date”."
    )
    assert gap_warning("empty", "read_yourself").endswith(
        "give the to-do “Read this letter yourself” that date."
    )


def _web_regex(relative: str, name: str) -> re.Pattern[str]:
    """A JavaScript regex literal of the web app (``const NAME = /…/;``), as Python reads it."""
    source = (ROOT / "web" / "src" / relative).read_text(encoding="utf-8")
    found = re.search(rf"const {name} = /(.+)/;\n", source)
    assert found is not None, name
    return re.compile(found.group(1))


def test_the_web_app_knows_the_slot_the_warnings_and_the_note() -> None:
    """The web app spells the slot, the warnings and the receipt's note out (review tests 13): a rename here
    must be one there, or the card falls back to "doesn't match the sentence it came from", the warning reads
    as a scam sign and Today's reason as a delivery-day aside."""
    warnings = (ROOT / "web" / "src" / "features" / "document" / "Warnings.tsx").read_text(encoding="utf-8")
    assert f'export const READING_CHECK_SLOT = "{CHECK_SLOT}";' in warnings
    selection = (ROOT / "web" / "src" / "features" / "today" / "selection.ts").read_text(encoding="utf-8")
    assert f'item.slot_key === "{CHECK_SLOT}"' in selection
    gap = _web_regex("features/document/Warnings.tsx", "GAP_WARNING")
    for name in ("empty", "remedy_left_out"):
        for kind in ("dated", "undated", "read_yourself"):
            for remedy in ("", "klage"):
                assert gap.match(gap_warning(name, kind, remedy)), (name, kind, remedy)  # type: ignore[arg-type]
    assert not gap.match("This letter explains how to object.")
    note = _web_regex("features/today/selection.ts", "READING_INCOMPLETE_NOTE")
    assert note.match(REASON_TEXT[READING_INCOMPLETE])


# --------------------------------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------------------------------

_WORDS = st.text(alphabet=st.characters(categories=("L", "N")), min_size=1, max_size=12)
_FIELD = st.sampled_from(
    ("sender", "document_date", "key_fact", "reference", "item", "contract", "change", "payment", "remedy")
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(fields=st.sets(_FIELD, min_size=1), word=_WORDS)
def test_a_reading_with_anything_a_person_acts_on_is_never_empty(fields: set[str], word: str) -> None:
    values: dict[str, Any] = {}
    if "sender" in fields:
        values["sender"] = ExtractedParty(name=word)
    if "document_date" in fields:
        values["document_date"] = "2026-11-06"
    if "key_fact" in fields:
        values["key_facts"] = [ExtractedFact(label=word, value=word, quote=word)]
    if "reference" in fields:
        values["references"] = [Identifier(label="Aktenzeichen", value=word)]
    if "item" in fields:
        values["items"] = [ExtractedItem(kind="task", title=word, date=DateSpec(type="none"), quote=word)]
    if "contract" in fields:
        values["contract"] = ExtractedContract(name=word)
    if "change" in fields:
        values["change"] = ExtractedChange(type="other", quote=word)
    if "payment" in fields:
        values["payment"] = PaymentDetails(payee=word)
    if "remedy" in fields:
        values["remedy"] = Remedy(type="widerspruch")
    assert reading_gap(blank(**values), [DECISION], remedy_notices([DECISION])) != "empty"


_LETTER_WORDS = st.sampled_from(
    (
        "Bescheid",
        "innerhalb",
        "eines",
        "Monats",
        "von",
        "zwei",
        "Wochen",
        "14",
        "Tagen",
        "nach",
        "Bekanntgabe",
        "Zustellung",
        "Frist",
        "schriftlich",
        "einzulegen",
        "Gebühr",
        "Datum:",
        "06.11.2026",
        "Monatsfrist",
        ".",
        "\n",
        "Beschwerde",
        "Antrag",
        "Anhörung",
        "Stellungnahme",
    )
)


@settings(max_examples=80, deadline=None)
@given(words=st.lists(_LETTER_WORDS, max_size=40))
def test_a_letter_that_names_no_remedy_never_yields_a_notice(words: list[str]) -> None:
    assert remedy_notices([page(" ".join(words))]) == []


_UNIT_WORDS = {"days": "Tagen", "weeks": "Wochen", "months": "Monaten"}
_STARTS = {"notified": "nach Bekanntgabe", "served": "nach Zustellung", "none": ""}
_REMEDY_WORDS = {"widerspruch": "Widerspruch", "einspruch": "Einspruch", "klage": "Klage"}
_NOTICES = st.tuples(
    st.sampled_from(sorted(_REMEDY_WORDS)),
    st.integers(min_value=1, max_value=40),
    st.sampled_from(sorted(_UNIT_WORDS)),
    st.sampled_from(sorted(_STARTS)),
)


def _sentence(remedy: str, amount: int, unit: str, start: str) -> str:
    words = f"Gegen diesen Bescheid kann innerhalb von {amount} {_UNIT_WORDS[unit]} {_STARTS[start]} {_REMEDY_WORDS[remedy]} erhoben werden."
    return " ".join(words.split())


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(notice_=_NOTICES)
def test_every_generated_notice_is_read_as_written(notice_: tuple[str, int, str, str]) -> None:
    remedy, amount, unit, start = notice_
    found = notice(_sentence(*notice_))
    assert (found.remedy, found.periods, found.notified) == (remedy, ((amount, unit),), start == "notified")


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    real=_NOTICES,
    planted=_NOTICES,
    before=st.booleans(),
    day=st.dates(min_value=date(2026, 1, 1), max_value=date(2027, 12, 31)),
    region=st.sampled_from((None, "HH", "BY")),
)
def test_a_planted_notice_never_makes_the_date_later(
    real: tuple[str, int, str, str],
    planted: tuple[str, int, str, str],
    before: bool,
    day: date,
    region: str | None,
) -> None:
    lines = head(day.strftime("%d.%m.%Y"))
    alone = due([page(*lines, _sentence(*real))], region=region)
    both = due(
        [
            page(
                *lines,
                *(
                    (_sentence(*planted), _sentence(*real))
                    if before
                    else (_sentence(*real), _sentence(*planted))
                ),
            )
        ],
        region=region,
    )
    if both is not None:
        # a date from both notices is never later than the real one's alone — nor than its law: never later than
        # the real period counted from the letter's date plus the longest deemed delivery
        assert alone is None or both <= alone
        amount, unit = real[1], real[2]
        latest = (
            day + timedelta(days=12) + timedelta(days=amount * {"days": 1, "weeks": 7, "months": 31}[unit])
        )
        assert date.fromisoformat(both) <= latest + timedelta(days=4)
