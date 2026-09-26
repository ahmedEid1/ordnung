"""DIN 5008 letter PDF: readable, marks drawn, address in the window, deterministic, no branding."""

from __future__ import annotations

import io
from typing import Any

import pdfplumber

from ordnung.drafts.pdf import render
from ordnung.models import Draft, Profile

MM = 72 / 25.4
PROFILE = Profile(
    name="Sam Rivera",
    address="Musterweg 5\n12345 Musterstadt",
    email="sam@example.org",
    phone="+49 170 1234567",
)
BODY = (
    "Sehr geehrte Damen und Herren,\n\nhiermit lege ich gegen den Steuerbescheid vom 15.09.2026, Steuernummer "
    "123/456/78901, Einspruch ein.\n\nEine Begründung reiche ich nach."
)


def _draft(**fields: Any) -> Draft:
    values: dict[str, Any] = {
        "id": "drf_pdf",
        "kind": "objection",
        "sender_block": "Sam Rivera\nMusterweg 5\n12345 Musterstadt",
        "recipient_block": "Finanzamt Musterstadt\nSteuerplatz 2\n12345 Musterstadt",
        "place_date": "Musterstadt, 28.09.2026",
        "subject": "Einspruch gegen den Steuerbescheid vom 15.09.2026 – Steuernummer 123/456/78901",
        "body": BODY,
        "enclosures": ["Kopie des Bescheids"],
        "created_at": "2026-09-28T08:00:00Z",
        "updated_at": "2026-09-28T08:00:00Z",
    }
    return Draft.model_validate(values | fields)


def _open(data: bytes) -> pdfplumber.PDF:
    return pdfplumber.open(io.BytesIO(data))


def test_pdf_is_a_readable_letter() -> None:
    data = render(_draft(), PROFILE)
    assert data.startswith(b"%PDF")
    with _open(data) as pdf:
        assert len(pdf.pages) == 1
        page = pdf.pages[0]
        assert round(page.width / MM) == 210 and round(page.height / MM) == 297
        text = page.extract_text()
        assert pdf.metadata["Title"] == _draft().subject
    flat = " ".join(text.split())
    assert "Einspruch gegen den Steuerbescheid vom 15.09.2026 – Steuernummer 123/456/78901" in flat
    for expected in ("Mit freundlichen Grüßen", "Sam Rivera", "Anlage", "Kopie des Bescheids"):
        assert expected in text
    assert "Musterstadt, 28.09.2026" in text
    assert "Seite" not in text  # no page numbers on a one-page letter
    assert "ordnung" not in text.casefold()  # no branding


def test_pdf_draws_fold_and_hole_marks() -> None:
    with _open(render(_draft(), PROFILE)) as pdf:
        lines = pdf.pages[0].lines
    marks = sorted(round(line["top"] / MM, 1) for line in lines if line["x0"] < 10 * MM)
    assert marks == [105.0, 148.5, 210.0]


def test_pdf_places_address_in_the_window() -> None:
    with _open(render(_draft(), PROFILE)) as pdf:
        words = pdf.pages[0].extract_words()
    recipient = next(word for word in words if word["text"] == "Finanzamt")
    assert 20 * MM <= recipient["x0"] <= 105 * MM
    assert 45 * MM + 17 * MM <= recipient["top"] <= 90 * MM
    sender_line = next(word for word in words if word["text"] == "Sam" and word["top"] < recipient["top"])
    assert 45 * MM <= sender_line["top"] < recipient["top"]
    info = [word for word in words if word["text"] == "Sam" and word["x0"] >= 125 * MM]
    assert info and 50 * MM <= info[0]["top"] < 90 * MM


def test_pdf_is_deterministic() -> None:
    assert render(_draft(), PROFILE) == render(_draft(), PROFILE)
    assert render(_draft(), PROFILE) != render(_draft(created_at="2026-09-29T08:00:00Z"), PROFILE)


def test_long_letter_gets_page_numbers() -> None:
    paragraph = "Dies ist ein längerer Absatz, der zeigt, wie ein mehrseitiger Brief umbricht. " * 3
    data = render(_draft(body=BODY + ("\n\n" + paragraph) * 12), PROFILE)
    with _open(data) as pdf:
        assert len(pdf.pages) == 2
        first, second = (page.extract_text() for page in pdf.pages)
        marks = [line for line in pdf.pages[1].lines if line["x0"] < 10 * MM]
    assert "Seite 1 von 2" in first and "Seite 2 von 2" in second
    assert "Mit freundlichen Grüßen" in second and "Sam Rivera" in second
    assert len(marks) == 3


def test_english_letter_and_missing_profile_name() -> None:
    draft = _draft(language="en", body="Dear Sir or Madam,\n\nI hereby object.", enclosures=["A", "B"])
    with _open(render(draft, Profile())) as pdf:
        text = pdf.pages[0].extract_text()
    assert "Yours faithfully" in text and "Enclosures" in text
    assert "Telefon" not in text
