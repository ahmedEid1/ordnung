"""Verification: normalisation with offsets, quote location + boxes, grounding, spec consistency."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image
from rapidfuzz import fuzz

from helpers_docs import (
    LETTER_LEFT,
    LETTER_PAGES,
    Line,
    expected_point,
    letter_line_y,
    letter_pdf,
    make_pdf,
    set_page_boxes,
    text_width,
)
from ordnung.ingest.intake import RenderedPage, render_pages
from ordnung.ingest.normalize import digit_tokens, digits_in, fold_punctuation, normalise_with_map
from ordnung.ingest.text import PageText, Word, extract_pdf_pages
from ordnung.ingest.verify import (
    AMBIGUOUS_DATE,
    AMOUNT_NOT_IN_QUOTE,
    DATE_NOT_IN_QUOTE,
    DATE_WITHOUT_YEAR,
    INCOMPLETE_SPEC,
    MIN_SCORE,
    PERIOD_NOT_IN_QUOTE,
    DateMention,
    Located,
    PageInput,
    amount_matches,
    ground_evidence,
    locate_quote,
    parse_amounts,
    parse_dates,
    parse_periods,
    spec_consistency,
)
from ordnung.models import Box, DateSpec, Page


def _extract(directory: Path, data: bytes) -> tuple[list[RenderedPage], list[PageText]]:
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "doc.pdf"
    source.write_bytes(data)
    rendered = render_pages(source, "application/pdf", directory / "derived", "doc_v")
    return rendered, extract_pdf_pages(source, rendered)


@pytest.fixture(scope="module")
def letter(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[RenderedPage], list[PageText]]:
    return _extract(tmp_path_factory.mktemp("letter"), letter_pdf())


def _ink(image_path: Path, box: Box) -> float:
    image = Image.open(image_path).convert("L")
    region = image.crop(
        (
            int(box.x0 * image.width),
            int(box.y0 * image.height),
            int(box.x1 * image.width),
            int(box.y1 * image.height),
        )
    )
    return sum(region.histogram()[:128]) / (region.width * region.height)


def _inside(box: Box, point: tuple[float, float], tolerance: float = 0.01) -> bool:
    return (
        box.x0 - tolerance <= point[0] <= box.x1 + tolerance
        and box.y0 - tolerance <= point[1] <= box.y1 + tolerance
    )


# --------------------------------------------------------------------------------------------------
# normalise_with_map / digits
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Hello \t  World \n", "hello world"),
        ("„Bescheid“ ‚vom‘ Amt – heute — morgen − 3 ‐ ‑", "\"bescheid\" 'vom' amt - heute - morgen - 3 - -"),
        ("Sam’s «Brief» ″x″ `y´", 'sam\'s "brief" "x" \'y\''),
        ("Einkommen-\nsteuer", "einkommensteuer"),
        ("Einkommen-  \n   steuer", "einkommensteuer"),
        ("Einkommen­\nsteuer", "einkommensteuer"),
        ("Kranken- und Pflegeversicherung", "kranken- und pflegeversicherung"),
        ("Seite 1-\n2", "seite 1- 2"),
        ("Muster-\nGmbH", "muster- gmbh"),
        ("Straße", "strasse"),
        ("ofﬁziell", "offiziell"),
        ("12 EUR", "12 eur"),
        ("１２３", "123"),
        ("Müller", "müller"),
        ("Ein­kom​men﻿", "einkommen"),
        ("", ""),
        (" \n ", ""),
    ],
)
def test_normalise_with_map(text: str, expected: str) -> None:
    norm, offsets = normalise_with_map(text)
    assert norm == expected
    assert len(offsets) == len(norm)
    assert offsets == sorted(offsets)
    assert all(0 <= o < len(text) for o in offsets)


def test_offsets_point_at_the_source_characters() -> None:
    text = "Der  Einspruch ist inner-\nhalb eines Monats"
    norm, offsets = normalise_with_map(text)
    assert norm == "der einspruch ist innerhalb eines monats"
    for index, char in enumerate(norm):
        source = text[offsets[index]]
        assert source.casefold() == char or (char == " " and source.isspace())
    start = norm.index("innerhalb")
    assert text[offsets[start] : offsets[start + len("innerhalb") - 1] + 1] == "inner-\nhalb"


def test_expanding_characters_map_to_their_source() -> None:
    norm, offsets = normalise_with_map("Maße ﬁx")
    assert norm == "masse fix"
    assert offsets == [0, 1, 2, 2, 3, 4, 5, 5, 6]


def test_digits_in() -> None:
    text = "am 15.10.2026 zahlen Sie 1.234,56 € (StNr 123/456/78901, 10:30 Uhr, 2026–10–15), bis 15.01."
    assert digits_in(text) == ["15.10.2026", "1.234,56", "123/456/78901", "10:30", "2026-10-15", "15.01"]
    assert digits_in("keine Ziffern") == []
    assert digits_in("IBAN DE89 3704 0044") == ["89", "3704", "0044"]


def test_digit_tokens_spans_and_fold_punctuation() -> None:
    assert digit_tokens("ab 1.200,00 am 3.4.") == [("1.200,00", 3, 11), ("3.4", 15, 18)]
    assert fold_punctuation("„A“ – B") == '"A" - B'


# --------------------------------------------------------------------------------------------------
# locate_quote
# --------------------------------------------------------------------------------------------------


def test_locate_quote_on_the_right_page_with_boxes(letter: tuple[list[RenderedPage], list[PageText]]) -> None:
    rendered, pages = letter
    located = locate_quote("die festgesetzte Steuer beträgt 1.234,56 EUR", pages)
    assert isinstance(located, Located)
    assert located.page == 1
    assert located.score >= MIN_SCORE
    assert located.source == "text"
    assert (
        pages[0].text[located.start : located.end].startswith("die festgesetzte Steuer beträgt 1.234,56 EUR")
    )
    [box] = located.boxes
    assert box.page == 1
    assert 0 <= box.x0 < box.x1 <= 1 and 0 <= box.y0 < box.y1 <= 1
    left, baseline = expected_point(LETTER_LEFT, letter_line_y(3))
    assert box.x0 == pytest.approx(left, abs=0.005)
    assert box.y0 < baseline < box.y1
    right = expected_point(LETTER_LEFT + text_width(LETTER_PAGES[0][3]), 0)[0]
    assert box.x1 == pytest.approx(right, abs=0.01)
    assert _ink(rendered[0].image_path, box) > 0.1


def test_quote_across_lines_gets_one_box_per_line(letter: tuple[list[RenderedPage], list[PageText]]) -> None:
    rendered, pages = letter
    located = locate_quote("Der Einspruch ist innerhalb eines Monats nach Bekanntgabe", pages)
    assert located is not None and located.page == 2
    first, second = located.boxes
    assert first.x0 > expected_point(LETTER_LEFT + 100, 0)[0]  # starts mid-line at "Der"
    assert second.x0 == pytest.approx(expected_point(LETTER_LEFT, 0)[0], abs=0.005)
    assert first.y1 <= second.y0 + 0.002
    for box in (first, second):
        assert _ink(rendered[1].image_path, box) > 0.1


def test_quote_tolerates_case_quotes_and_whitespace(
    letter: tuple[list[RenderedPage], list[PageText]],
) -> None:
    _, pages = letter
    located = locate_quote("  STEUERNUMMER   123/456/78901 ", pages)
    assert located is not None and located.page == 3


def test_hyphenated_line_break_matches_the_joined_word(tmp_path: Path) -> None:
    _, pages = _extract(
        tmp_path, make_pdf([[Line(72, 100, "Ihre Einkommen-"), Line(72, 116, "steuer für 2025")]])
    )
    located = locate_quote("Ihre Einkommensteuer für 2025", pages)
    assert located is not None
    assert len(located.boxes) == 2


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_located_boxes_on_rotated_cropped_pages(tmp_path: Path, rotation: int) -> None:
    cropbox = (30.0, 120.0, 580.0, 810.0)
    rendered, pages = _extract(tmp_path, set_page_boxes(letter_pdf(), 0, rotation=rotation, cropbox=cropbox))
    located = locate_quote("Bitte zahlen Sie den Betrag bis zum 15.09.2026", pages)
    assert located is not None
    [box] = located.boxes
    assert 0 <= box.x0 < box.x1 <= 1 and 0 <= box.y0 < box.y1 <= 1
    start = expected_point(LETTER_LEFT + 3, letter_line_y(4) - 4, rotation=rotation, cropbox=cropbox)
    end = expected_point(
        LETTER_LEFT + text_width("Bitte zahlen Sie den Betrag bis zum 15.09.2026") - 3,
        letter_line_y(4) - 4,
        rotation=rotation,
        cropbox=cropbox,
    )
    assert _inside(box, start)
    assert _inside(box, end)
    assert _ink(rendered[0].image_path, box) > 0.1


def test_exact_digit_rule_rejects_a_near_match(letter: tuple[list[RenderedPage], list[PageText]]) -> None:
    _, pages = letter
    quote = "Bitte zahlen Sie den Betrag bis zum 16.09.2026 auf das unten genannte Konto."
    norm_quote = normalise_with_map(quote)[0]
    assert fuzz.partial_ratio(norm_quote, normalise_with_map(pages[0].text)[0]) > MIN_SCORE
    assert locate_quote(quote, pages) is None
    assert locate_quote(quote.replace("16.09", "15.09"), pages) is not None


def test_amount_digits_must_match_exactly(letter: tuple[list[RenderedPage], list[PageText]]) -> None:
    _, pages = letter
    assert locate_quote("die festgesetzte Steuer beträgt 1.234,57 EUR", pages) is None
    assert locate_quote("die festgesetzte Steuer beträgt 1234,56 EUR", pages) is None


def test_falls_back_to_a_lower_scoring_page_with_matching_digits() -> None:
    quote = "Die Zahlung ist fällig am 15.10.2026, bitte überweisen Sie rechtzeitig."
    wrong = PageText(
        1, "Die Zahlung ist fällig am 15.09.2026, bitte überweisen Sie rechtzeitig.", has_text_layer=True
    )
    right = PageText(
        2, "Die Zahlung ist fällig am 15.10.2026. Bitte überweisen Sie rechtzeitig!", has_text_layer=True
    )
    norm_quote = normalise_with_map(quote)[0]
    scores = [fuzz.partial_ratio(norm_quote, normalise_with_map(p.text)[0]) for p in (wrong, right)]
    assert scores[0] > scores[1] >= MIN_SCORE
    located = locate_quote(quote, [wrong, right])
    assert located is not None and located.page == 2


def test_quote_not_on_any_page(letter: tuple[list[RenderedPage], list[PageText]]) -> None:
    _, pages = letter
    assert locate_quote("Ihr Mietvertrag endet am 31.12.2026", pages) is None
    assert locate_quote("", pages) is None
    assert locate_quote("   ", pages) is None
    assert locate_quote("x" * 5000, pages) is None  # longer than every page
    assert locate_quote("Bescheid", []) is None


def test_database_rows_and_transcript_tuples_are_accepted(
    letter: tuple[list[RenderedPage], list[PageText]],
) -> None:
    _, pages = letter
    rows = [(p.page, p.text, [w.to_row() for w in p.words], "text") for p in pages]
    from_rows = locate_quote("innerhalb eines Monats nach Bekanntgabe", rows)
    from_pages = locate_quote("innerhalb eines Monats nach Bekanntgabe", pages)
    assert from_rows is not None and from_pages is not None
    assert from_rows.page == from_pages.page == 2
    assert [b.x0 for b in from_rows.boxes] == pytest.approx([b.x0 for b in from_pages.boxes], abs=1e-4)


def test_stored_pages_are_accepted(letter: tuple[list[RenderedPage], list[PageText]]) -> None:
    rendered, pages = letter
    stored = [
        Page.model_validate(
            {
                "doc_id": "doc_1",
                "page": r.page,
                "width": r.width,
                "height": r.height,
                "image_path": str(r.image_path),
                "text": p.text,
                "text_source": p.source,
                "words": [w.to_row() for w in p.words],
            }
        )
        for r, p in zip(rendered, pages, strict=True)
    ]
    evidence = ground_evidence("doc_1", "Steuernummer 123/456/78901", stored)
    assert evidence.grounding == "verified"
    assert evidence.page == 3
    assert len(evidence.boxes) == 1
    stored[2].text_source = "transcript"
    assert ground_evidence("doc_1", "Steuernummer 123/456/78901", stored).grounding == "model_read"


def test_words_that_do_not_match_the_text_are_skipped() -> None:
    page = (
        1,
        "Zahlbar bis 15.10.2026",
        [Word("fremd", 0, 0, 0.1, 0.1), Word("15.10.2026", 0.5, 0.5, 0.6, 0.55)],
        "text",
    )
    located = locate_quote("Zahlbar bis 15.10.2026", [page])
    assert located is not None
    assert located.boxes == [Box(page=1, x0=0.5, y0=0.5, x1=0.6, y1=0.55)]


# --------------------------------------------------------------------------------------------------
# ground_evidence
# --------------------------------------------------------------------------------------------------


def test_ground_evidence_verified_on_text_pages(letter: tuple[list[RenderedPage], list[PageText]]) -> None:
    _, pages = letter
    evidence = ground_evidence("doc_1", "bis zum 15.09.2026", pages)
    assert evidence.grounding == "verified"
    assert evidence.verified
    assert evidence.doc_id == "doc_1"
    assert evidence.page == 1
    assert evidence.quote == "bis zum 15.09.2026"
    assert evidence.score >= MIN_SCORE
    assert len(evidence.boxes) == 1


def test_ground_evidence_model_read_on_transcripts() -> None:
    transcript: PageInput = (1, "Bitte zahlen Sie 49,99 EUR bis zum 01.10.2026.", [], "transcript")
    evidence = ground_evidence("doc_2", "zahlen Sie 49,99 EUR bis zum 01.10.2026", [transcript])
    assert evidence.grounding == "model_read"
    assert not evidence.verified
    assert evidence.page == 1
    assert evidence.boxes == []


def test_ground_evidence_unverified_when_missing_or_digits_differ(
    letter: tuple[list[RenderedPage], list[PageText]],
) -> None:
    _, pages = letter
    missing = ground_evidence("doc_1", "Kündigung zum 31.12.2026", pages)
    assert missing.grounding == "unverified"
    assert missing.page is None and missing.boxes == []
    assert 0 < missing.score < MIN_SCORE
    wrong_digits = ground_evidence("doc_1", "bis zum 16.09.2026", pages)
    assert wrong_digits.grounding == "unverified"
    assert wrong_digits.score > MIN_SCORE  # recorded: fuzzy match was close, digits were not


def test_ground_evidence_on_a_page_without_text_layer_is_unverified() -> None:
    sparse = PageText(1, "Zahlbar bis 15.10.2026", has_text_layer=False)
    evidence = ground_evidence("doc_3", "Zahlbar bis 15.10.2026", [sparse])
    assert evidence.grounding == "unverified"
    assert evidence.page == 1


# --------------------------------------------------------------------------------------------------
# parse_dates / parse_amounts / parse_periods
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Frist: 15.10.2026", (15, 10, 2026)),
        ("am 15.10.26", (15, 10, 2026)),
        ("geboren 01.01.85", (1, 1, 1985)),
        ("ab 1.2.2026", (1, 2, 2026)),
        ("am 15. 10. 2026", (15, 10, 2026)),
        ("bis 15.01.", (15, 1, None)),
        ("am 03.11. 14 Uhr", (3, 11, None)),
        ("bis zum 15. Oktober 2026", (15, 10, 2026)),
        ("by 15 October 2026", (15, 10, 2026)),
        ("by October 15, 2026", (15, 10, 2026)),
        ("by Oct. 15 2026", (15, 10, 2026)),
        ("on the 15th of October 2026", (15, 10, 2026)),
        ("October 15th, 2026", (15, 10, 2026)),
        ("2026-10-15", (15, 10, 2026)),
        ("3. März 2026", (3, 3, 2026)),
        ("3. Maerz 2026", (3, 3, 2026)),
        ("3. MÄRZ 2026", (3, 3, 2026)),
        ("1. Mai", (1, 5, None)),
        ("Stichtag 29.02.", (29, 2, None)),
        ("25/12/2026", (25, 12, 2026)),
        ("12/25/2026", (25, 12, 2026)),
        ("05/05/2026", (5, 5, 2026)),
    ],
)
def test_parse_dates_formats(text: str, expected: tuple[int, int, int | None]) -> None:
    [mention] = parse_dates(text)
    assert (mention.day, mention.month, mention.year) == expected
    assert not mention.ambiguous


def test_parse_dates_ambiguous_numeric_date() -> None:
    mentions = parse_dates("Payment due 03/05/2026")
    assert [m.as_date() for m in mentions] == [date(2026, 5, 3), date(2026, 3, 5)]
    assert all(m.ambiguous and m.text == "03/05/2026" for m in mentions)


@pytest.mark.parametrize(
    "text",
    [
        "Betrag 1.234,56 EUR",
        "Version 1.2.3",
        "am 31.02.2026",
        "Server 192.168.1.1",
        "Rechnung 2026-0042",
        "Kundennummer 123456",
        "Summe: 12.50.",
        "you may pay later",
    ],
)
def test_parse_dates_ignores_non_dates(text: str) -> None:
    assert parse_dates(text) == []


def test_parse_dates_several_and_as_date() -> None:
    mentions = parse_dates("Bescheid vom 15.09.2026, Einspruch bis 15. Oktober 2026 oder 2026-10-16.")
    assert [m.as_date() for m in mentions] == [date(2026, 9, 15), date(2026, 10, 15), date(2026, 10, 16)]
    assert DateMention("15.01.", 15, 1, None).as_date() is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Betrag: 1.234,56 EUR", [1234.56]),
        ("Total: 1,234.56 USD", [1234.56]),
        ("nur 12,50 €", [12.5]),
        ("EUR 12.50", [12.5]),
        ("€ 99", [99.0]),
        ("99 Euro", [99.0]),
        ("99,- €", [99.0]),
        ("Preis 99,-", [99.0]),
        ("1.200 €", [1200.0]),
        ("USD 1,000", [1000.0]),
        ("Gutschrift -49,99 EUR", [49.99]),
        ("1.234.567,89 EUR", [1234567.89]),
        ("Summe: 12,50.", [12.5]),
        ("2.000,00 EUR und 150,00 EUR", [2000.0, 150.0]),
        ("am 15.10.2026", []),
        ("Kundennummer 123456", []),
        ("30 Tage", []),
        ("1.234", []),
        ("12,5 %", []),
        ("Steuernummer 123/456/78901", []),
        ("Wert 1,234.5", []),
        ("1.2,34 EUR", []),
        # malformed groups (an OCR slip, a typo) are not amounts — and never raise
        ("Ref 12,34..56", []),
        ("94.99,,31", []),
        ("Ihre Zahlung vom 15,.09.26 ist eingegangen.", []),
        ("x 31,.10.30 €", []),
        ("5,.10.20", []),
    ],
)
def test_parse_amounts(text: str, expected: list[float]) -> None:
    assert parse_amounts(text) == pytest.approx(expected)


@settings(max_examples=400, deadline=None)
@given(st.text(alphabet="0123456789.,-€ EURSD$£x", max_size=40))
def test_amount_matches_never_raises(text: str) -> None:
    """A letter's text can hold any run of digits and separators: reading it never raises."""
    for match in amount_matches(text):
        assert match.value >= 0


@pytest.mark.parametrize(
    "text", ["Gebühr: " + "9" * 400 + " €", "EUR " + "1" * 320 + ",00", "9" * 330 + ",- €"]
)
def test_a_number_too_long_to_be_an_amount_is_none(text: str) -> None:
    """Final review: about 310 digits read as ``inf``, and every caller that took its cents raised (a
    hostile letter stopped every Ask answer that read it). Such a number is no amount."""
    assert amount_matches(text) == [] and parse_amounts(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("innerhalb von zwei Wochen", [(2, "weeks")]),
        ("innerhalb eines Monats nach Bekanntgabe", [(1, "months")]),
        ("innerhalb einer Woche", [(1, "weeks")]),
        ("binnen 14 Tagen", [(14, "days")]),
        ("innerhalb von dreißig Tagen", [(30, "days")]),
        ("innerhalb von drei Werktagen", [(3, "werktage")]),
        ("innerhalb von 5 Bankarbeitstagen", [(5, "business_days")]),
        ("Kündigungsfrist: 3 Monate zum Monatsende", [(3, "months")]),
        ("zwölf Monate Laufzeit", [(12, "months")]),
        ("within 5 business days", [(5, "business_days")]),
        ("within ten working days", [(10, "business_days")]),
        ("within thirty (30) calendar days", [(30, "days")]),
        ("within a month", [(1, "months")]),
        ("for one year", [(1, "years")]),
        ("eine 30-Tage-Frist", [(30, "days")]),
        ("Tage und Wochen", []),
    ],
)
def test_parse_periods(text: str, expected: list[tuple[int, str]]) -> None:
    assert parse_periods(text) == expected


# --------------------------------------------------------------------------------------------------
# spec_consistency
# --------------------------------------------------------------------------------------------------


def _relative(amount: int | None, unit: str | None, **extra: str) -> DateSpec:
    return DateSpec.model_validate({"type": "relative", "amount": amount, "unit": unit, **extra})


def _fixed(value: str | None) -> DateSpec:
    return DateSpec(type="fixed", date=value)


def test_relative_period_in_words_is_consistent() -> None:
    quote = "Der Einspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen."
    assert spec_consistency(quote, _relative(1, "months"), None) == (True, [])


def test_relative_period_mismatch_is_caught() -> None:
    assert spec_consistency("innerhalb von zwei Wochen", _relative(1, "months"), None) == (
        False,
        [PERIOD_NOT_IN_QUOTE],
    )
    assert spec_consistency("innerhalb von zwei Wochen", _relative(3, "weeks"), None)[0] is False


def test_equivalent_periods_are_consistent() -> None:
    assert spec_consistency("innerhalb von zwei Wochen", _relative(14, "days"), None) == (True, [])
    assert spec_consistency("binnen 14 Tagen", _relative(2, "weeks"), None) == (True, [])
    assert spec_consistency("innerhalb eines Jahres", _relative(12, "months"), None) == (True, [])


def test_werktage_are_not_business_days() -> None:
    quote = "innerhalb von 3 Werktagen"
    assert spec_consistency(quote, _relative(3, "werktage"), None) == (True, [])
    assert spec_consistency(quote, _relative(3, "business_days"), None) == (False, [PERIOD_NOT_IN_QUOTE])
    assert spec_consistency("within 3 business days", _relative(3, "business_days"), None) == (True, [])


def test_relative_spec_without_amount_is_incomplete() -> None:
    assert spec_consistency("innerhalb eines Monats", _relative(None, "months"), None) == (
        False,
        [INCOMPLETE_SPEC],
    )


def test_explicit_anchor_date_must_be_in_the_quote() -> None:
    quote = "Die Frist von zwei Wochen beginnt am 01.10.2026."
    ok = _relative(2, "weeks", anchor="explicit_date", anchor_date="2026-10-01")
    assert spec_consistency(quote, ok, None) == (True, [])
    wrong = _relative(2, "weeks", anchor="explicit_date", anchor_date="2026-10-02")
    assert spec_consistency(quote, wrong, None) == (False, [DATE_NOT_IN_QUOTE])
    other_anchor = _relative(2, "weeks", anchor="document_date", anchor_date="2026-09-01")
    assert spec_consistency(quote, other_anchor, None) == (True, [])


@pytest.mark.parametrize(
    "quote",
    [
        "Zahlbar bis zum 15.10.2026.",
        "bis 15.10.26",
        "bis zum 15. Oktober 2026",
        "due October 15, 2026",
        "2026-10-15",
    ],
)
def test_fixed_date_written_in_the_quote(quote: str) -> None:
    assert spec_consistency(quote, _fixed("2026-10-15"), None) == (True, [])


def test_fixed_date_not_in_the_quote() -> None:
    assert spec_consistency("Zahlbar bis zum 15.10.2026.", _fixed("2026-10-16"), None) == (
        False,
        [DATE_NOT_IN_QUOTE],
    )
    assert spec_consistency("Zahlbar sofort.", _fixed("2026-10-16"), None) == (False, [DATE_NOT_IN_QUOTE])


def test_fixed_date_without_year_is_flagged() -> None:
    assert spec_consistency("Bitte zahlen Sie bis 15.01.", _fixed("2027-01-15"), None) == (
        False,
        [DATE_WITHOUT_YEAR],
    )
    assert spec_consistency("bis 15.01.", _fixed("2027-02-15"), None) == (
        False,
        [DATE_WITHOUT_YEAR, DATE_NOT_IN_QUOTE],
    )


def test_fixed_spec_without_valid_date_is_incomplete() -> None:
    assert spec_consistency("bis 15.10.2026", _fixed(None), None) == (False, [INCOMPLETE_SPEC])
    assert spec_consistency("bis 15.10.2026", _fixed("2026-13-40"), None) == (False, [INCOMPLETE_SPEC])


def test_ambiguous_numeric_date_is_flagged() -> None:
    quote = "Payment is due on 03/05/2026."
    assert spec_consistency(quote, _fixed("2026-05-03"), None) == (False, [AMBIGUOUS_DATE])
    assert spec_consistency(quote, _fixed("2026-03-05"), None) == (False, [AMBIGUOUS_DATE])
    assert spec_consistency("due on 25/12/2026", _fixed("2026-12-25"), None) == (True, [])


@pytest.mark.parametrize("quote", ["Betrag: 1.234,56 EUR", "Amount: 1,234.56 EUR", "EUR 1234.56"])
def test_amount_must_appear_in_the_quote(quote: str) -> None:
    spec = DateSpec(type="none")
    assert spec_consistency(quote, spec, 1234.56) == (True, [])
    assert spec_consistency(quote, spec, 1234.65) == (False, [AMOUNT_NOT_IN_QUOTE])


def test_amount_and_date_reasons_combine() -> None:
    ok, reasons = spec_consistency("Zahlung von 49,99 EUR bis 01.10.2026", _fixed("2026-10-02"), 50.0)
    assert not ok
    assert reasons == [DATE_NOT_IN_QUOTE, AMOUNT_NOT_IN_QUOTE]
    assert spec_consistency("Zahlung von 49,99 EUR bis 01.10.2026", _fixed("2026-10-01"), 49.99) == (True, [])


def test_none_spec_without_amount_is_always_consistent() -> None:
    assert spec_consistency("Irgendein Satz.", DateSpec(type="none"), None) == (True, [])
