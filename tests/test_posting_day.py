"""The posting day a letter's page states (``ingest.posting``, ADR 0026), and its way from a letter to the to-do.

Every letter here is made up (Musterstadt, Beispielhausen, fictional people and file numbers): the cues come from
how German authorities write the posting day — the statutes' "Aufgabe zur Post" (§ 122 Abs. 2 AO, § 41 Abs. 2
VwVfG, § 37 Abs. 2 SGB X), a header or footer field, a sentence that the decision was posted —, and the never-list
from the module's docstring.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from fixtures_llm import Letter
from helpers_tables import check_rows
from ordnung import clock
from ordnung.ingest.plan import compute_item, needs_check, verify_extraction
from ordnung.ingest.posting import posting_statement
from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem
from ordnung.rules.deadlines import POSTED_ON_LETTER, TWO_POSTING_DAYS, PostingStatement, RuleContext
from test_api_support import ApiRouter, api_for

D = date.fromisoformat
LETTER = D("2026-10-16")
HEADER = (
    "Finanzamt Musterstadt · Postfach 10 20 30 · 12345 Musterstadt\n"
    "Frau Erika Beispiel   Ihr Zeichen   Bitte bei Antwort angeben\n"
    "Lindenweg 4   -   Steuernummer 123/456/78901\n"
    "12345 Musterstadt   Datum 16.10.2026\n"
)


def found(text: str, source: str = "text") -> PostingStatement | None:
    return posting_statement([(1, text, [], source)], LETTER)


#: (id, page text, the posting day it states). Each a way an authority writes it.
CUES = [
    (
        "field-in-the-header",
        f"{HEADER}Tag der Aufgabe zur Post: 19.10.2026\n\nSehr geehrte Frau Beispiel,",
        "2026-10-19",
    ),
    (
        "field-in-a-column",
        "Steuernummer 123/456   Datum 16.10.2026   Aufgabe zur Post: 19.10.2026",
        "2026-10-19",
    ),
    (
        "field-on-a-single-spaced-line",
        "Steuernummer 123/456/78901 Tag der Aufgabe zur Post 19.10.2026",
        "2026-10-19",
    ),
    ("field-datum-der-aufgabe", "Datum der Aufgabe zur Post: Montag, 19. Oktober 2026", "2026-10-19"),
    ("field-under-its-label", "Tag der Aufgabe zur Post\n19.10.2026\n", "2026-10-19"),
    (
        "field-in-the-footer",
        "Seite 1 von 2 · Absendedatum: 19.10.2026 · Bankverbindung siehe Rückseite",
        "2026-10-19",
    ),
    ("field-versandt-am", "Bescheid über Grundbesitzabgaben\nVersandt am: 19.10.2026", "2026-10-19"),
    ("field-tag-der-absendung", "Tag der Absendung: 19.10.2026", "2026-10-19"),
    ("field-datum-des-versands", "Datum des Versands: 19.10.2026", "2026-10-19"),
    ("field-short-weekday", "Tag der Aufgabe zur Post: Mo., 19.10.2026", "2026-10-19"),
    ("sentence-erfolgt", "Die Aufgabe zur Post erfolgt am Mo 19.10.2026.", "2026-10-19"),
    ("field-with-a-note", "Aufgabe zur Post (Absendevermerk): 19.10.2026", "2026-10-19"),
    ("field-ist-der", "Bitte beachten Sie: Tag der Aufgabe zur Post ist der 19.10.2026.", "2026-10-19"),
    (
        "sentence-zur-post-gegeben",
        "Sehr geehrter Herr Muster,\nDieser Bescheid wurde am 19.10.2026 zur Post gegeben. Er ergeht unter Vorbehalt.",
        "2026-10-19",
    ),
    (
        "sentence-zur-post-gegeben-worden",
        "Der Bescheid ist am Montag, den 19.10.2026 zur Post gegeben worden.",
        "2026-10-19",
    ),
    ("sentence-wrapped", "Dieser Bescheid wurde am 19.10.2026 zur\nPost gegeben.", "2026-10-19"),
    ("sentence-aufgabe-am", "Die Aufgabe zur Post erfolgte am 19.10.2026.", "2026-10-19"),
    (
        "sentence-der-post-uebergeben",
        "Dieses Schreiben wurde am 19.10.2026 der Post übergeben.",
        "2026-10-19",
    ),
    ("sentence-versandt-this-letter", "Dieser Bescheid wurde am 19.10.2026 versandt.", "2026-10-19"),
    (
        "sentence-versandt-own-date",
        "Der Bescheid vom 16.10.2026 wurde am 19. Oktober 2026 abgesandt.",
        "2026-10-19",
    ),
    ("with-its-delivery-day", "Tag der Aufgabe zur Post: 19.10.2026 (Bekanntgabe: 23.10.2026)", "2026-10-19"),
    ("english-field", "Date of posting: 19 October 2026", "2026-10-19"),
    ("english-sentence", "This letter was posted on 19 October 2026.", "2026-10-19"),
]


def test_each_cue_states_the_posting_day() -> None:
    def check(_id: str, text: str, day: str) -> None:
        statement = found(text)
        assert statement is not None and statement.day == D(day) and statement.other is None, statement
        assert statement.grounding == "verified" and statement.quote
        assert "Sehr geehrte" not in statement.quote and "Ihr Zeichen" not in statement.quote

    check_rows(CUES, check)


#: (id, page text). Each states a date near posting words that is NOT the day this letter was posted.
NEVER = [
    ("an-earlier-decision", "Der Bescheid vom 01.09.2026 wurde am 03.09.2026 zur Post gegeben."),
    ("our-earlier-letter", "Unser Schreiben vom 01.09.2026 haben wir am 02.09.2026 versandt."),
    ("the-person-s-letter", "Ihr Widerspruch wurde am 12.10.2026 zur Post gegeben."),
    ("the-person-did-it", "Sie haben das Formular am 12.10.2026 zur Post gegeben."),
    ("the-person-s-field", "Ihr Schreiben, abgesandt am 12.10.2026, ist eingegangen."),
    ("an-enclosure", "Die Anlage wurde am 19.10.2026 gesondert zur Post gegeben."),
    ("a-copy", "Eine Abschrift dieses Bescheids wurde am 19.10.2026 an Ihren Steuerberater versandt."),
    ("a-payment", "Bitte überweisen Sie den Betrag bis zum 19.11.2026."),
    ("a-deadline", "Senden Sie die Unterlagen spätestens am 30.10.2026 zur Post."),
    (
        "a-deadline-to-post-by",
        "Der Antrag gilt als rechtzeitig, wenn er spätestens am 30.10.2026 zur Post gegeben wurde.",
    ),
    ("a-payment-s-due-day", "Der Betrag ist am 19.10.2026 fällig und wurde zur Post gegeben."),
    ("the-future", "Der Bescheid wird am 19.10.2026 zur Post gegeben."),
    ("a-request", "Bitte geben Sie Ihre Erklärung bis 30.10.2026 zur Post."),
    ("negated", "Der Bescheid wurde nicht vor dem 19.10.2026 zur Post gegeben."),
    (
        "the-delivery-day",
        "Dieser Bescheid gilt am 23.10.2026 als bekannt gegeben (vierter Tag nach Aufgabe zur Post).",
    ),
    ("the-delivery-formula", "Er gilt am vierten Tag nach Aufgabe zur Post: 23.10.2026 als bekannt gegeben."),
    ("a-letter-s-date", "Ihr Schreiben vom 12.10.2026 haben wir erhalten."),
    ("a-shop-s-dispatch", "Ihre Bestellung wurde am 19.10.2026 versandt. Sendungsnummer 00340434"),
    ("a-shop-s-field", "Versandt am: 19.10.2026   Paket 1 von 2"),
    ("versandt-without-the-letter", "Der Bescheid wurde am 19.10.2026 versandt."),
    ("reads-two-ways", "Tag der Aufgabe zur Post: 03/05/2026"),
    ("no-year", "Tag der Aufgabe zur Post: 19.10."),
    (
        "the-letter-s-own-date-only",
        f"{HEADER}\nSehr geehrte Frau Beispiel,\nhiermit setzen wir die Steuer fest.",
    ),
]


def test_what_never_counts_as_this_letter_s_posting_day() -> None:
    def check(_id: str, text: str) -> None:
        assert found(text) == PostingStatement()

    check_rows(NEVER, check)


def test_a_photo_s_transcription_is_model_read_unless_a_text_page_says_it_too() -> None:
    field = "Tag der Aufgabe zur Post: 19.10.2026"
    photo = found(field, "transcript")
    assert photo is not None and (photo.day, photo.grounding) == (D("2026-10-19"), "model_read")
    both = posting_statement([(1, field, [], "transcript"), (2, field, [], "text")], LETTER)
    assert both is not None and both.grounding == "verified"


def test_a_photo_s_doubt_counts_once_for_its_to_do() -> None:
    """A photo letter: the to-do's quote and the posting day both come from the transcript. The posting day keeps
    the date at most ``medium`` and the quote read from a transcript lowers it one level: counted once, ``medium``
    — not ``low`` for one photo (``ingest.plan.compute_item``)."""
    page = (
        1,
        "Tag der Aufgabe zur Post: 19.10.2026\nDer Einspruch ist innerhalb eines Monats einzulegen.",
        [],
        "transcript",
    )
    item = ExtractedItem(
        kind="deadline",
        title="Object",
        date=DateSpec(
            type="relative",
            anchor="deemed_delivery",
            amount=1,
            unit="months",
            delivery_rule="de_admin_post",
            nature="objection",
        ),
        quote="Der Einspruch ist innerhalb eines Monats einzulegen.",
    )
    extraction = DocumentExtraction(
        kind="tax_assessment",
        title="Tax",
        summary="Tax.",
        explanation="Object.",
        document_date="2026-10-16",
        items=[item],
    )
    [verified] = verify_extraction("doc", extraction, [page]).items
    assert verified.evidence.grounding == "model_read"
    context = RuleContext(
        today=D("2026-10-22"),
        region="NW",
        document_date=LETTER,
        delivery_scope="ao",
        posting=posting_statement([page], LETTER),
    )
    computed = compute_item(verified, context, postal_buffer_days=4)
    assert computed.due_date == "2026-11-23"
    assert computed.receipt is not None and computed.receipt.confidence == "medium"


def test_two_posting_days_that_differ_are_both_kept() -> None:
    statement = found(
        "Tag der Aufgabe zur Post: 21.10.2026\n\nDieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    )
    assert statement is not None
    assert (statement.day, statement.other) == (D("2026-10-19"), D("2026-10-21"))
    assert statement.quote == "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    assert statement.other_quote == "Tag der Aufgabe zur Post: 21.10.2026"
    agree = found(
        "Tag der Aufgabe zur Post: 19.10.2026\n\nDieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    )
    assert agree is not None and (agree.day, agree.other) == (D("2026-10-19"), None)


def test_without_pages_nothing_was_read() -> None:
    """No pages (a to-do added by hand, a context built without the letter): ``None``, so the engine keeps
    today's behaviour, as for the rules tools."""
    assert posting_statement([], LETTER) is None
    assert posting_statement([(1, "", [], "none")], LETTER) == PostingStatement()


# ------------------------------------------------------------------------------- from a letter to the to-do

TODAY = "2026-10-22"

#: A made-up tax assessment dated Fri 16 Oct 2026 that states it was posted Mon 19 Oct, with a reading that
#: names the objection period from deemed delivery (and leaves the posting day out, as a reading may).
POSTED_LATER = Letter(
    marker="Aufgabeprobe",
    pages=(
        (
            "Finanzamt Musterstadt · Postfach 10 20 30 · 12345 Musterstadt",
            "SPECIMEN Aufgabeprobe",
            "Steuernummer 123/456/78901   Datum 16.10.2026",
            "Tag der Aufgabe zur Post: 19.10.2026",
            "Bescheid für 2025 über Einkommensteuer",
            "Sehr geehrte Frau Beispiel,",
            "die Einkommensteuer wird auf 1.234,00 EUR festgesetzt.",
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Bescheid ist der Einspruch gegeben. Der Einspruch ist innerhalb eines Monats nach",
            "Bekanntgabe dieses Bescheides beim Finanzamt Musterstadt einzulegen.",
        ),
    ),
    payload={
        "kind": "tax_assessment",
        "title": "Income tax 2025",
        "summary": "Income tax assessment.",
        "explanation": "You may object within a month.",
        "sender": {"name": "Finanzamt Musterstadt", "kind": "tax_office"},
        "document_date": "2026-10-16",
        "remedy": {"type": "einspruch", "quote": "Gegen diesen Bescheid ist der Einspruch gegeben."},
        "items": [
            {
                "kind": "deadline",
                "title": "Object to the assessment",
                "date": {
                    "type": "relative",
                    "anchor": "deemed_delivery",
                    "amount": 1,
                    "unit": "months",
                    "delivery_rule": "de_admin_post",
                    "nature": "objection",
                    "legal_basis": "§ 355 AO",
                },
                "quote": "Der Einspruch ist innerhalb eines Monats nach",
            }
        ],
    },
)


@pytest.fixture
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.mark.usefixtures("pinned_today")
async def test_a_letter_s_posting_day_reaches_the_stored_to_do(data_dir: Path) -> None:
    """Through the app's own path (upload, read, verify, compute, plan): the page's posting day starts the deemed
    delivery — posted Mon 19 Oct → Fri 23 Oct → Mon 23 Nov —, the receipt says where it was found and names the
    letter's date's deadline (Fri 20 Nov) as the safe date, and the to-do is as sure as any verified fact."""
    router = ApiRouter()
    router.letters = (POSTED_LATER, *router.letters)
    router.payloads[POSTED_LATER.marker] = POSTED_LATER.extraction()
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", POSTED_LATER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [objection] = [item for item in api.ctx.store.list_items(doc_id=doc_id) if item.kind == "deadline"]
        assert objection.due_date == "2026-11-23"
        receipt = objection.computation
        assert receipt is not None and receipt.safe_date == "2026-11-20"
        assert POSTED_ON_LETTER in receipt.rule_ids and receipt.confidence == "high"
        assert any("“Tag der Aufgabe zur Post: 19.10.2026”" in step.label for step in receipt.steps)
        assert not needs_check(objection)


@pytest.mark.usefixtures("pinned_today")
async def test_two_posting_days_on_a_letter_make_its_to_do_please_check(data_dir: Path) -> None:
    letter = Letter(
        marker="Zweiaufgabe",
        pages=(
            tuple(
                line.replace("Aufgabeprobe", "Zweiaufgabe")
                if "Aufgabeprobe" in line
                else line + "   Absendetag: 20.10.2026"
                if line.startswith("Tag der Aufgabe")
                else line
                for line in POSTED_LATER.pages[0]
            ),
        ),
        payload=POSTED_LATER.payload,
    )
    router = ApiRouter()
    router.letters = (letter, *router.letters)
    router.payloads[letter.marker] = letter.extraction()
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("zwei.pdf", letter.pdf())))["documents"][0]["id"]
        await api.read_all()
        [objection] = [item for item in api.ctx.store.list_items(doc_id=doc_id) if item.kind == "deadline"]
        assert objection.due_date == "2026-11-23"  # from the earlier, Mon 19 Oct
        assert objection.computation is not None and TWO_POSTING_DAYS in objection.computation.rule_ids
        assert objection.computation.confidence == "low" and needs_check(objection)
