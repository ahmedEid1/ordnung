"""A reading that came back incomplete gets one "Please check" to-do written by code (``ingest/gaps.py``).

Every letter here is synthetic, written for these tests: a city's fee decision with its instructions on how to
object (Rechtsbehelfsbelehrung), and the ordinary letters that rightly have no to-do or no objection.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ordnung.db.store import Store
from ordnung.ingest.gaps import (
    CHECK_SLOT,
    LAW_DATED_KINDS,
    check_item,
    gap_warning,
    letter_date,
    reading_gap,
    remedy_notices,
)
from ordnung.ingest.link import LinkResult
from ordnung.ingest.plan import (
    ComputedDate,
    VerifiedItem,
    compute_item,
    needs_check,
    verify_extraction,
    write_items,
)
from ordnung.ingest.verify import READING_INCOMPLETE, REASON_TEXT, PageInput
from ordnung.models import (
    DateSpec,
    DocumentExtraction,
    ExtractedChange,
    ExtractedContract,
    ExtractedFact,
    ExtractedItem,
    ExtractedParty,
    Identifier,
    Page,
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


def page(*lines: str, source: str = "text") -> PageInput:
    return (1, "\n".join(lines), [], source)


DECISION = page(*HEAD, NOTIFIED, WHERE)


def blank(**fields: Any) -> DocumentExtraction:
    """A reading with only the four fields the schema requires (and any ``fields`` given)."""
    return DocumentExtraction.model_validate(
        {"kind": "other", "title": "Letter", "summary": "A letter.", "explanation": "Read it.", **fields}
    )


def objection(spec: dict[str, Any] | None = None) -> ExtractedItem:
    date_spec = spec or {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "deemed_delivery",
        "delivery_rule": "de_admin_post",
        "nature": "objection",
    }
    return ExtractedItem.model_validate(
        {"kind": "deadline", "title": "Objection", "date": date_spec, "quote": NOTIFIED}
    )


def payment(quote: str = PAY, **spec: Any) -> ExtractedItem:
    date_spec = spec or {"type": "fixed", "date": "2026-11-30", "nature": "payment"}
    return ExtractedItem.model_validate(
        {"kind": "payment", "title": "Pay the fee", "date": date_spec, "amount": 85.0, "quote": quote}
    )


SENDER = ExtractedParty(name="Stadt Beispielhausen", kind="authority")


def checked(extraction: DocumentExtraction, pages: Sequence[PageInput]) -> VerifiedItem:
    """The to-do the reading check filed (the last item of the verification)."""
    verification = verify_extraction("doc_x", extraction, pages, check_reading=True)
    verified = verification.items[-1]
    assert verified.slot_key == CHECK_SLOT
    return verified


def due(
    pages: Sequence[PageInput], *, region: str | None = None, reading: DocumentExtraction | None = None
) -> str:
    verified = checked(reading or blank(), pages)
    computed = compute_item(verified, RuleContext(today=TODAY, region=region), postal_buffer_days=3)
    assert computed.due_date is not None
    return computed.due_date


# --------------------------------------------------------------------------------------------------
# 1–4: what an incomplete reading gets
# --------------------------------------------------------------------------------------------------


def test_an_empty_reading_gets_the_objection_deadline_its_notice_states() -> None:
    pages = [DECISION]
    found = check_item(blank(), pages)
    assert found is not None
    gap, item, kind = found
    assert (gap, kind) == ("empty", "dated")
    assert (
        item.kind == "deadline"
        and item.priority == "high"
        and item.title == "Deadline to object (Widerspruch)"
    )
    spec = item.date
    assert (spec.type, spec.amount, spec.unit, spec.nature) == ("relative", 1, "months", "objection")
    assert (spec.anchor, spec.anchor_date, spec.delivery_rule) == (
        "deemed_delivery",
        "2026-11-06",
        "de_admin_post",
    )

    verification = verify_extraction("doc_x", blank(), pages, check_reading=True)
    [verified] = verification.items
    assert verified.slot_key == CHECK_SLOT and READING_INCOMPLETE in verified.reasons
    assert verified.evidence.grounding == "verified" and not verified.evidence.value_consistent
    assert verified.needs_check and verification.needs_review
    assert verification.warnings == [gap_warning("empty", "dated")]
    # the code's own to-do is not counted again in "N dates could not be confirmed"
    assert not any("could not be confirmed" in warning for warning in verification.warnings)

    # posted Fri 6 Nov: the Land unknown, delivered on the 3rd day (Mon 9 Nov); in Hamburg the 4th (Tue 10 Nov)
    for region, expected in ((None, "2026-12-09"), ("HH", "2026-12-10")):
        computed = compute_item(verified, RuleContext(today=TODAY, region=region), postal_buffer_days=3)
        assert computed.due_date == expected
        assert computed.receipt is not None and computed.receipt.confidence == "low"
        assert REASON_TEXT[READING_INCOMPLETE] in computed.receipt.warnings


def test_a_period_from_formal_service_counts_from_the_letter_s_date_and_is_low_although_the_engine_is_sure() -> (
    None
):
    pages = [page(*HEAD, SERVED)]
    found = check_item(blank(), pages)
    assert found is not None
    _, item, kind = found
    assert kind == "dated" and item.title == "Deadline to object (Einspruch)"
    spec = item.date
    assert (spec.anchor, spec.anchor_date, spec.delivery_rule) == ("explicit_date", "2026-11-06", "none")
    assert (spec.amount, spec.unit) == (2, "weeks")
    ctx = RuleContext(today=TODAY, region="NW")
    assert compute_due(spec, ctx, postal_buffer_days=3).confidence == "high"  # the engine alone
    computed = compute_item(checked(blank(), pages), ctx, postal_buffer_days=3)
    assert computed.due_date == "2026-11-20"
    assert computed.receipt is not None and computed.receipt.confidence == "low"


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
    assert found is not None
    gap, item, kind = found
    assert (gap, kind) == ("empty", "read_yourself")
    assert item.kind == "task" and item.title == "Read this letter yourself" and item.date.type == "none"
    assert item.priority == "high" and item.quote == "" and item.action
    verified = checked(blank(), pages)
    assert not verified.dated and verified.needs_check
    [stored] = write(store, add_doc(store), blank(), pages)
    assert stored.slot_key == CHECK_SLOT and stored.due_date is None
    assert needs_check(stored)
    assert not needs_check(stored.model_copy(update={"status": "done"}))
    assert not needs_check(stored.model_copy(update={"grounding": "user"}))


def test_a_notice_without_a_readable_letter_date_gives_an_undated_deadline() -> None:
    pages = [page(LETTERHEAD, "Sehr geehrte Frau Probe,", NOTIFIED)]
    assert letter_date(blank(), pages) is None
    found = check_item(blank(), pages)
    assert found is not None
    _, item, kind = found
    assert kind == "undated" and item.kind == "deadline" and item.date.anchor_date is None
    verification = verify_extraction("doc_x", blank(), pages, check_reading=True)
    assert verification.warnings == [gap_warning("empty", "undated")]
    assert verification.items[0].needs_check


# --------------------------------------------------------------------------------------------------
# 5–10: which readings are incomplete
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
    assert due(pages, reading=reading) == "2026-12-09"


def test_a_dated_objection_satisfies_the_check_and_an_undated_one_does_not() -> None:
    pages = [page(*HEAD, PAY, NOTIFIED)]
    reading = blank(sender=SENDER, document_date="2026-11-06", items=[payment(), objection()])
    assert check_item(reading, pages) is None
    assert verify_extraction("doc_x", reading, pages, check_reading=True).warnings == []
    undated = blank(
        sender=SENDER,
        document_date="2026-11-06",
        items=[payment(), objection({"type": "none", "nature": "objection"})],
    )
    found = check_item(undated, pages)
    assert found is not None and found[0] == "remedy_left_out"


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


def test_a_letter_whose_deadline_the_law_files_is_no_gap() -> None:
    order = DocumentExtraction(
        kind="dunning",
        title="Payment order",
        summary="s",
        explanation="e",
        high_stakes_kind="court_payment_order",
        sender=ExtractedParty(name="Amtsgericht Beispielhausen", kind="authority"),
        document_date="2026-11-06",
        items=[payment("Zahlen Sie 85,00 EUR an die Antragstellerin.", type="none", nature="payment")],
    )
    text = "Gegen diesen Bescheid können Sie innerhalb von zwei Wochen ab Zustellung Widerspruch erheben."
    pages = [page("Amtsgericht Beispielhausen", "Zahlen Sie 85,00 EUR an die Antragstellerin.", text)]
    assert remedy_notices(pages) and shows_administrative_act(text)
    assert check_item(order, pages) is None
    # the kinds left out are exactly those the law dates itself (routing.derived_deadlines)
    assert all(derived_deadlines(kind, end=None) for kind in LAW_DATED_KINDS)


# --------------------------------------------------------------------------------------------------
# 11–14: never a later date, visible text only, the letter's own date, photos
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
    assert alone == "2026-12-09"
    assert due([page(*HEAD, planted, NOTIFIED)]) <= alone
    assert due([page(*HEAD, NOTIFIED, planted)]) <= alone
    # one that counts from notification as the real one does changes nothing
    if "Bekanntgabe" in planted:
        assert due([page(*HEAD, planted, NOTIFIED)]) == alone


def test_a_planted_shorter_period_only_makes_the_date_earlier() -> None:
    shorter = "Der Widerspruch ist innerhalb von zwei Wochen nach Bekanntgabe einzulegen."
    assert due([page(*HEAD, NOTIFIED, shorter)]) == "2026-11-23" < due([DECISION])


def test_a_later_date_planted_for_the_letter_never_moves_it_later() -> None:
    later = page(
        *HEAD[:4],
        "Datum: 06.11.2026",
        *HEAD[5:8],
        "Mit diesem Bescheid vom 20.11.2026 setzen wir eine Gebühr fest.",
        NOTIFIED,
    )
    assert due([later]) == due([DECISION]) == "2026-12-09"
    # nor does the reading's own later date
    assert due([DECISION], reading=blank(items=[], references=[])) == "2026-12-09"


@pytest.mark.parametrize("start", ["Datum: 06.11.2026", "Datum: 29.01.2027"])
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
    head = (*HEAD[:4], start, *HEAD[5:])
    both = due([page(*head, *notices)], region=region)
    singles = [due([page(*head, notice)], region=region) for notice in notices]
    assert both <= min(singles)
    found = check_item(blank(), [page(*head, *notices)])
    assert found is not None and (found[1].date.amount, found[1].date.unit) == (4, "weeks")
    assert (found[1].date.anchor, found[1].date.delivery_rule) == ("explicit_date", "none")


def test_a_period_counted_back_from_an_event_is_no_notice() -> None:
    backward = "Ein Widerspruch ist spätestens zwei Wochen vor Ablauf der Frist zu begründen."
    assert remedy_notices([page(*HEAD, backward)]) == []


def test_a_notice_only_in_hidden_text_is_ignored() -> None:
    visible = "\n".join((*HEAD[:8], "wir bestätigen den Eingang Ihres Antrags."))
    hidden = Page(
        doc_id="doc_x",
        page=1,
        width=10,
        height=10,
        image_path="p.jpg",
        text=visible,
        text_source="text",
        hidden=NOTIFIED,
    )
    assert remedy_notices([hidden]) == []
    found = check_item(blank(), [hidden])
    assert found is not None and found[2] == "read_yourself"


def test_the_letter_s_date_comes_from_its_own_text_in_tiers_and_is_the_earliest() -> None:
    def written(*lines: str, reading: DocumentExtraction | None = None) -> date | None:
        return letter_date(
            reading or blank(), [page(LETTERHEAD, *lines, "Sehr geehrte Frau Probe,", NOTIFIED)]
        )

    # "Place, date" on page 1
    assert written("Beispielhausen, 06.11.2026") == date(2026, 11, 6)
    assert written("Beispielhausen, den 06.11.2026") == date(2026, 11, 6)
    # a date alone on a header line — not under a line that labels another date
    assert written("Frau Mara Probe", "06.11.2026") == date(2026, 11, 6)
    assert written("Ihr Antrag vom", "01.10.2026") is None
    # a place's date before a bare one
    assert written("Beispielhausen, 06.11.2026", "05.11.2026") == date(2026, 11, 6)
    # the header's "Datum:" (or "mit diesem Bescheid vom …") wins: the other tiers are not read then
    assert written("Datum: 06.11.2026", "Beispielhausen, 02.11.2026") == date(2026, 11, 6)
    # the earliest of the letter's and the reading's
    assert written("Datum: 06.11.2026", reading=blank(document_date="2026-11-04")) == date(2026, 11, 4)
    assert written("Datum: 06.11.2026", reading=blank(document_date="2026-11-20")) == date(2026, 11, 6)


def test_on_a_photo_the_notice_is_read_from_the_transcript() -> None:
    pages = [page(*HEAD, NOTIFIED, source="transcript")]
    verified = checked(blank(), pages)
    assert verified.evidence.grounding == "model_read" and verified.needs_check
    computed = compute_item(verified, RuleContext(today=TODAY), postal_buffer_days=3)
    assert computed.due_date == "2026-12-09"
    assert computed.receipt is not None and computed.receipt.confidence == "low"


# --------------------------------------------------------------------------------------------------
# 15–16: the words, and the rules as properties
# --------------------------------------------------------------------------------------------------


def test_no_warning_or_note_reads_as_a_doubtful_date_a_scam_or_an_injection() -> None:
    texts = [
        gap_warning(gap, kind)  # type: ignore[arg-type]
        for gap, kind in (
            ("empty", "dated"),
            ("empty", "undated"),
            ("empty", "read_yourself"),
            ("remedy_left_out", "dated"),
            ("remedy_left_out", "undated"),
            ("remedy_left_out", "read_yourself"),
        )
    ]
    texts.append(REASON_TEXT[READING_INCOMPLETE])
    for text in texts:
        assert not UNCERTAINTY_RE.search(text), text
        assert not SCAM_RE.search(text), text
        assert not INJECTION_RE.search(text), text


_WORDS = st.text(alphabet=st.characters(categories=("L", "N")), min_size=1, max_size=12)
_FIELD = st.sampled_from(("sender", "document_date", "key_fact", "reference", "item"))


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
