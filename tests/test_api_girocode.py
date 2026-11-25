"""GiroCodes over HTTP: the document detail carries one per payment, a photo letter waits for the
person to compare it with the paper (``POST /api/items/{id}/girocode/confirm``), so does the first
payment to an account however its values were found, and a confirmation never covers other values,
another to-do or a refused code."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import DUNNING_LETTER, INVOICE_LETTER, TELECOM_IBAN, iban, record_events
from helpers_docs import Fill, Line, make_pdf, photo
from ordnung import clock
from test_api_support import FINE_LETTER, TODAY, Api, ApiRouter, api_for

INVOICE_PAYLOAD = f"BCD\n002\n1\nSCT\n\nMuster Telecom GmbH\n{TELECOM_IBAN}\nEUR49.99\n\n\nR-2026-0815"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _read(api: Api, name: str, data: bytes) -> dict[str, Any]:
    body = await api.upload((name, data))
    await api.read_all()
    detail: dict[str, Any] = (await api.client.get(f"/api/documents/{body['documents'][0]['id']}")).json()
    return detail


def _payment(detail: dict[str, Any]) -> dict[str, Any]:
    (item,) = [item for item in detail["items"] if item["kind"] == "payment"]
    return dict(item)


INVOICE_VALUES = {
    "payee": "Muster Telecom GmbH",
    "iban": TELECOM_IBAN,
    "reference": "R-2026-0815",
    "amount": 49.99,
}
FIRST_PAYMENT = (
    "No code yet: this is the first payment to this IBAN. Compare the payee, IBAN, amount and reference "
    "with the letter, then confirm."
)


async def test_a_text_letter_carries_its_code_in_the_detail(data_dir: Path) -> None:
    """The first payment to the account waits for the comparison, even with every value in the text layer;
    no route hands out its payload before. The next letter to the account gets its code at once."""
    async with api_for(data_dir) as api:
        detail = await _read(api, "rechnung.pdf", INVOICE_LETTER.pdf())
        item = _payment(detail)
        assert detail["girocodes"] == [
            {
                "status": "blocked",
                "item_id": item["id"],
                "reason": "check_letter",
                "message": FIRST_PAYMENT,
                "to_check": [],
                "values": INVOICE_VALUES,
                "first_payment": True,
            }
        ]
        url = f"/api/items/{item['id']}/girocode/confirm"
        changed = await api.client.post(url, json={**INVOICE_VALUES, "amount": 4.99})
        assert changed.status_code == 409 and "BCD" not in changed.text
        confirmed = await api.client.post(url, json=INVOICE_VALUES)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json() == {
            "status": "ready",
            "item_id": item["id"],
            "payload": INVOICE_PAYLOAD,
            "checked": True,
        }
        # UTF-8 bytes as the QR code stores them
        assert len(INVOICE_PAYLOAD.encode()) == 80

        reminder = await _read(api, "mahnung.pdf", DUNNING_LETTER.pdf())
        (code,) = reminder["girocodes"]
        assert code["status"] == "ready" and not code["checked"] and "\nEUR54.99\n" in code["payload"]


async def test_a_photo_letter_is_compared_with_the_paper_before_it_gets_a_code(data_dir: Path) -> None:
    router = ApiRouter()
    router.transcript = INVOICE_LETTER.transcript()
    async with api_for(data_dir, router=router) as api:
        detail = await _read(api, "rechnung.jpg", photo("JPEG"))
        item = _payment(detail)
        (code,) = detail["girocodes"]
        assert code["status"] == "blocked" and code["reason"] == "check_letter"
        assert code["to_check"] == ["amount", "iban", "reference"]
        assert code["first_payment"] is True
        assert code["message"] == (
            "No code yet: this is the first payment to this IBAN, and the amount, the IBAN and the reference "
            "were read by AI from a photo. Compare the payee, IBAN, amount and reference with the paper letter, "
            "then confirm."
        )
        values = code["values"]
        assert values == {
            "payee": "Muster Telecom GmbH",
            "iban": TELECOM_IBAN,
            "reference": "R-2026-0815",
            "amount": 49.99,
        }
        url = f"/api/items/{item['id']}/girocode/confirm"

        changed = await api.client.post(url, json={**values, "iban": TELECOM_IBAN[:-2] + "00"})
        assert changed.status_code == 409
        assert (
            changed.json()["detail"]
            == "The payment details changed since you looked at them. Please compare them again."
        )
        assert (await api.client.post(url, json={**values, "bic": "MUSTDEXX"})).status_code == 422
        assert (await api.client.post("/api/items/itm_nope/girocode/confirm", json=values)).status_code == 404

        events = record_events(api.ctx.bus)
        confirmed = await api.client.post(url, json=values)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json() == {
            "status": "ready",
            "item_id": item["id"],
            "payload": INVOICE_PAYLOAD,
            "checked": True,
        }
        assert ("document.updated", {"doc_id": detail["document"]["id"]}) in events

        again = (await api.client.get(f"/api/documents/{detail['document']['id']}")).json()
        assert again["girocodes"] == [confirmed.json()]
        activity = (await api.client.get("/api/activity")).json()
        assert activity[0]["kind"] == "payment.checked" and activity[0]["ref_id"] == item["id"]

        twice = await api.client.post(url, json=values)
        assert (
            twice.status_code == 409
            and twice.json()["detail"] == "There is nothing to compare for this payment."
        )

        # deleting the letter deletes what the person compared (docs/privacy.md)
        deleted = await api.client.delete(
            f"/api/documents/{detail['document']['id']}", params={"purge": "true"}
        )
        assert deleted.status_code == 200, deleted.text
        kinds = [entry["kind"] for entry in (await api.client.get("/api/activity")).json()]
        assert "payment.checked" not in kinds


async def test_a_reminder_takes_the_code_over_from_its_invoice(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        invoice = await _read(api, "rechnung.pdf", INVOICE_LETTER.pdf())
        reminder = await _read(api, "mahnung.pdf", DUNNING_LETTER.pdf())
        invoice = (await api.client.get(f"/api/documents/{invoice['document']['id']}")).json()
        (old,) = invoice["girocodes"]
        assert old["status"] == "blocked" and old["reason"] == "replaced"
        (new,) = reminder["girocodes"]
        assert new["status"] == "blocked" and new["first_payment"]  # nobody compared the account yet
        refused = await api.client.post(
            f"/api/items/{old['item_id']}/girocode/confirm",
            json={
                "payee": "Muster Telecom GmbH",
                "iban": TELECOM_IBAN,
                "reference": "R-2026-0815",
                "amount": 49.99,
            },
        )
        assert refused.status_code == 409 and refused.json()["detail"].startswith(
            "No code: the payment reminder"
        )


async def test_a_covered_iban_never_gets_a_code(data_dir: Path) -> None:
    """Adversarial: the invoice's IBAN line is in the text layer but painted over with a white box, so
    the printed letter shows no IBAN at all. It is hidden text, a scam sign: no code, never one carrying
    an IBAN nobody can see on the page."""
    lines: list[Line | Fill] = [
        Line(72, 90 + 20 * row, text, size=11) for row, text in enumerate(INVOICE_LETTER.pages[0])
    ]
    iban_row = INVOICE_LETTER.pages[0].index(f"IBAN: {TELECOM_IBAN}")
    lines.append(Fill(60, 90 + 20 * iban_row - 14, 470, 20, (255, 255, 255)))  # drawn after the text: over it
    async with api_for(data_dir) as api:
        detail = await _read(api, "rechnung.pdf", make_pdf([lines]))
        assert detail["document"]["hidden_text"] is True
        (code,) = detail["girocodes"]
        assert code["status"] != "ready" and code["reason"] == "scam"
        assert TELECOM_IBAN.replace(" ", "") not in str(detail["girocodes"])


async def test_a_letter_with_hidden_text_never_gets_a_code(data_dir: Path) -> None:
    """The fine's PDF carries invisible text: a scam sign, whatever else the letter lacks."""
    async with api_for(data_dir) as api:
        detail = await _read(api, "verwarnung.pdf", FINE_LETTER.pdf())
        assert detail["document"]["hidden_text"] is True
        (code,) = detail["girocodes"]
        assert code["reason"] == "scam"
        assert code["message"].startswith("No code: this letter shows signs of a scam.")


# --------------------------------------------------------------------------------------------------
# A text layer that says another IBAN than the page shows (security review, docv1)
# --------------------------------------------------------------------------------------------------

#: The account the page shows the person; the text layer says TELECOM_IBAN in its place.
SHOWN_IBAN = iban("DE", "700700700555444333")
_GLYPHS = {
    **{str(n): name for n, name in enumerate("zero one two three four five six seven eight nine".split())}
}


def _pdf_string(text: str) -> bytes:
    raw = text.encode("cp1252")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _two_faced_invoice() -> bytes:
    """INVOICE_LETTER as a PDF whose IBAN line draws SHOWN_IBAN while its text layer reads TELECOM_IBAN:
    each character of the IBAN has a code of its own, whose glyph (the font's /Differences) is the shown
    character and whose text (its /ToUnicode map) is the other one. Ink in every glyph's box: the check
    for text without ink has nothing to find."""
    assert len(SHOWN_IBAN) == len(TELECOM_IBAN)
    codes = range(0x80, 0x80 + len(TELECOM_IBAN))
    glyphs = b" ".join(b"/" + (_GLYPHS.get(char) or char).encode() for char in SHOWN_IBAN)
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /TwoFaced def 1"
        b" begincodespacerange <00> <FF> endcodespacerange %d beginbfchar "
        % len(TELECOM_IBAN)
        + b" ".join(
            b"<%02X> <%04X>" % (code, ord(char)) for code, char in zip(codes, TELECOM_IBAN, strict=True)
        )
        + b" endbfchar endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    content = bytearray()
    for row, text in enumerate(INVOICE_LETTER.pages[0]):
        y = 842 - (90 + 20 * row)
        if text == f"IBAN: {TELECOM_IBAN}":
            content += b"BT /F1 11 Tf 72 %d Td (IBAN: ) Tj /F2 11 Tf <%s> Tj ET\n" % (
                y,
                "".join(f"{code:02X}" for code in codes).encode(),
            )
        else:
            content += b"BT /F1 11 Tf 72 %d Td %s Tj ET\n" % (y, _pdf_string(text))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + bytes(content) + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding /Differences [128 "
        + glyphs
        + b"] >> /ToUnicode 7 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


async def test_an_iban_whose_glyphs_show_another_iban_waits_for_the_comparison(data_dir: Path) -> None:
    """Adversarial (security review, docv1): the page shows one account, the text layer and so the reading
    and the grounding say another, and nothing on the page is without ink. The first code to that account
    is never handed out ready: the person compares the IBAN Ordnung read with the letter first, and there
    it differs from the one the page shows."""
    async with api_for(data_dir) as api:
        detail = await _read(api, "rechnung.pdf", _two_faced_invoice())
        assert detail["document"]["hidden_text"] is False  # the trick is not found as hidden text
        (code,) = detail["girocodes"]
        assert code["status"] == "blocked" and code["reason"] == "check_letter" and code["first_payment"]
        assert code["to_check"] == []  # the text layer grounds every value: only the first payment asks
        assert code["values"]["iban"] == TELECOM_IBAN
        assert "payload" not in code
