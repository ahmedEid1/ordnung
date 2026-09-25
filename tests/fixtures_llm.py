"""Canned SPECIMEN letters and the ``DocumentExtraction`` payloads a model would return for them.

Each :class:`Letter` holds its printed lines (to build a text PDF or a "photo" transcript) and the
extraction payload whose quotes are copied verbatim from those lines. :func:`fake_backend` routes
extract calls to the letter whose ``marker`` appears in the prompt, and answers transcribe calls
with the transcript of the letter being photographed.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from helpers_docs import Line, make_pdf
from ordnung.llm.base import LLMRequest
from ordnung.llm.fake import FakeBackend

TODAY = "2026-09-25"
_PDF_CACHE: dict[str, bytes] = {}  # fpdf stamps the creation time: build each letter once


def iban(country: str, bban: str) -> str:
    """A valid IBAN (correct ISO 13616 check digits) for ``bban``."""
    digits = "".join(str(int(char, 36)) for char in f"{bban}{country}00")
    return f"{country}{98 - int(digits) % 97:02d}{bban}"


TAX_IBAN = iban("DE", "370400440532013000")
TELECOM_IBAN = iban("DE", "100100100123456789")
BEITRAG_IBAN = iban("DE", "200200200987654321")
SCAM_IBAN = iban("DE", "300300300111222333")


@dataclass(frozen=True)
class Letter:
    """A SPECIMEN letter: printed pages and the extraction payload for it."""

    marker: str
    pages: tuple[tuple[str, ...], ...]
    payload: dict[str, Any] = field(repr=False)

    def pdf(self) -> bytes:
        """A text PDF with one page per entry of :attr:`pages` (the same bytes on every call)."""
        if self.marker not in _PDF_CACHE:
            _PDF_CACHE[self.marker] = make_pdf(
                [
                    [Line(72, 90 + 20 * row, text, size=11) for row, text in enumerate(page)]
                    for page in self.pages
                ]
            )
        return _PDF_CACHE[self.marker]

    def extraction(self) -> dict[str, Any]:
        """A fresh copy of the payload (safe to modify)."""
        return copy.deepcopy(self.payload)

    def transcript(self) -> str:
        """The letter's text as a transcription of a photo would return it."""
        return "\n\n".join("\n".join(page) for page in self.pages)


def _relative(amount: int, unit: str, anchor: str, nature: str, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "relative",
        "amount": amount,
        "unit": unit,
        "anchor": anchor,
        "nature": nature,
        "text": text,
        **extra,
    }


def _fixed(date: str, nature: str, text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "fixed", "date": date, "nature": nature, "text": text, **extra}


# --------------------------------------------------------------------------------------------------
# Tax assessment (the hero case)
# --------------------------------------------------------------------------------------------------

TAX_OBJECTION_QUOTE = (
    "Der Einspruch ist innerhalb eines Monats nach Bekanntgabe dieses Bescheides schriftlich "
    "beim Finanzamt Musterstadt einzulegen."
)
TAX_PAYMENT_QUOTE = "Bitte zahlen Sie den Betrag von 1.234,56 EUR bis zum 15.10.2026."

TAX_LETTER = Letter(
    marker="Einkommensteuer",
    pages=(
        (
            "Finanzamt Musterstadt · Steuerstraße 1 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 15.09.2026",
            "Steuernummer: 123/456/78901",
            "Bescheid für 2025 über Einkommensteuer",
            "Sehr geehrte Frau Rivera,",
            "die festgesetzte Einkommensteuer beträgt 1.234,56 EUR.",
            TAX_PAYMENT_QUOTE,
            f"IBAN: {TAX_IBAN}",
        ),
        (
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Bescheid ist der Einspruch gegeben. Der Einspruch ist",
            "innerhalb eines Monats nach Bekanntgabe dieses Bescheides schriftlich",
            "beim Finanzamt Musterstadt einzulegen.",
        ),
    ),
    payload={
        "kind": "tax_assessment",
        "area": "tax",
        "title": "Income tax assessment 2025",
        "language": "de",
        "sender": {
            "name": "Finanzamt Musterstadt",
            "kind": "tax_office",
            "address": "Steuerstraße 1, 12345 Musterstadt",
        },
        "document_date": "2026-09-15",
        "references": [{"label": "Steuernummer", "value": "123/456/78901"}],
        "summary": "The tax office assessed your 2025 income tax at 1,234.56 EUR.",
        "explanation": "You must pay the amount; you can object (Einspruch) by the deadline shown.",
        "key_facts": [
            {
                "label": "Income tax",
                "value": "1,234.56 EUR",
                "quote": "die festgesetzte Einkommensteuer beträgt 1.234,56 EUR.",
            }
        ],
        "items": [
            {
                "kind": "deadline",
                "title": "Objection deadline (Einspruch)",
                "action": "Object in writing if the assessment is wrong",
                "date": _relative(
                    1,
                    "months",
                    "deemed_delivery",
                    "objection",
                    "innerhalb eines Monats nach Bekanntgabe",
                    delivery_rule="de_admin_post",
                    legal_basis="§ 355 AO",
                ),
                "priority": "high",
                "quote": TAX_OBJECTION_QUOTE,
            },
            {
                "kind": "payment",
                "title": "Pay the income tax",
                "date": _fixed("2026-10-15", "payment", "bis zum 15.10.2026"),
                "amount": 1234.56,
                "currency": "EUR",
                "direction": "out",
                "quote": TAX_PAYMENT_QUOTE,
            },
        ],
        "remedy": {
            "type": "einspruch",
            "addressee": "Finanzamt Musterstadt",
            "period_text": "innerhalb eines Monats nach Bekanntgabe",
            "quote": "Gegen diesen Bescheid ist der Einspruch gegeben.",
        },
        "payment": {"iban": TAX_IBAN, "payee": "Finanzamt Musterstadt", "reference": "123/456/78901"},
        "urgency": "high",
        "tax_relevant": True,
        "case_title": "Income tax 2025",
    },
)

# --------------------------------------------------------------------------------------------------
# Appointment letter (photographed)
# --------------------------------------------------------------------------------------------------

APPOINTMENT_QUOTE = "Ihr Termin ist am 12.10.2026 um 10:30 Uhr im Bürgeramt, Raum 4."

APPOINTMENT_LETTER = Letter(
    marker="Terminbestätigung",
    pages=(
        (
            "Stadt Musterstadt - Bürgeramt",
            "SPECIMEN",
            "Musterstadt, 20.09.2026",
            "Terminbestätigung",
            APPOINTMENT_QUOTE,
            "Bitte bringen Sie Ihren Reisepass mit.",
        ),
    ),
    payload={
        "kind": "appointment",
        "area": "residence",
        "title": "Appointment at the citizens' office",
        "sender": {"name": "Stadt Musterstadt - Bürgeramt", "kind": "authority"},
        "document_date": "2026-09-20",
        "summary": "Your appointment at the Bürgeramt is confirmed.",
        "explanation": "Go to the appointment and bring your passport.",
        "items": [
            {
                "kind": "appointment",
                "title": "Bürgeramt appointment",
                "date": _fixed(
                    "2026-10-12", "appointment", "am 12.10.2026 um 10:30 Uhr", time="10:30", shift_rule="none"
                ),
                "location": "Bürgeramt, Raum 4",
                "quote": APPOINTMENT_QUOTE,
            }
        ],
        "case_title": "Bürgeramt appointment",
    },
)

# --------------------------------------------------------------------------------------------------
# Invoice and dunning letter
# --------------------------------------------------------------------------------------------------

INVOICE_PAY_QUOTE = "Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026."
DUNNING_PAY_QUOTE = "Bitte zahlen Sie jetzt 54,99 EUR bis zum 30.09.2026."

INVOICE_LETTER = Letter(
    marker="Ihre Rechnung",
    pages=(
        (
            "Muster Telecom GmbH · Funkweg 5 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 01.09.2026",
            "Ihre Rechnung Nr. R-2026-0815",
            "Kundennummer: K-778899",
            INVOICE_PAY_QUOTE,
            f"IBAN: {TELECOM_IBAN}",
        ),
    ),
    payload={
        "kind": "invoice",
        "area": "money",
        "title": "Phone bill September 2026",
        "sender": {"name": "Muster Telecom GmbH", "kind": "telecom"},
        "document_date": "2026-09-01",
        "references": [
            {"label": "Rechnungsnummer", "value": "R-2026-0815"},
            {"label": "Kundennummer", "value": "K-778899"},
        ],
        "summary": "Muster Telecom bills 49.99 EUR.",
        "explanation": "Pay the bill by the date shown.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the phone bill",
                "date": _fixed("2026-09-15", "payment", "bis zum 15.09.2026"),
                "amount": 49.99,
                "currency": "EUR",
                "direction": "out",
                "quote": INVOICE_PAY_QUOTE,
            }
        ],
        "payment": {"iban": TELECOM_IBAN, "payee": "Muster Telecom GmbH", "reference": "R-2026-0815"},
        "case_title": "Phone bill September",
    },
)

DUNNING_LETTER = Letter(
    marker="Zahlungserinnerung",
    pages=(
        (
            "Muster Telecom · Funkweg 5 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 20.09.2026",
            "Zahlungserinnerung zu Rechnung Nr. R-2026-0815",
            "Kundennummer: K-778899",
            DUNNING_PAY_QUOTE,
            f"IBAN: {TELECOM_IBAN}",
        ),
    ),
    payload={
        "kind": "dunning",
        "area": "money",
        "title": "Payment reminder for the September bill",
        "sender": {"name": "Muster Telecom", "kind": "telecom"},
        "document_date": "2026-09-20",
        "references": [
            {"label": "Rechnungsnummer", "value": "R-2026-0815"},
            {"label": "Kundennummer", "value": "K778899"},
        ],
        "summary": "Muster Telecom reminds you to pay 54.99 EUR.",
        "explanation": "Pay the reminder amount.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the reminder",
                "date": _fixed("2026-09-30", "payment", "bis zum 30.09.2026"),
                "amount": 54.99,
                "currency": "EUR",
                "direction": "out",
                "priority": "high",
                "quote": DUNNING_PAY_QUOTE,
            }
        ],
        "payment": {"iban": TELECOM_IBAN, "payee": "Muster Telecom", "reference": "R-2026-0815"},
        "urgency": "critical",
        "case_title": "Reminder",
    },
)

# --------------------------------------------------------------------------------------------------
# Broadcasting fee: genuine and fake collector
# --------------------------------------------------------------------------------------------------

BEITRAG_LETTER = Letter(
    marker="Festsetzungsbescheid Rundfunkbeitrag",
    pages=(
        (
            "Beitragsservice Musterstadt",
            "SPECIMEN",
            "Festsetzungsbescheid Rundfunkbeitrag",
            "Beitragsnummer: 123 456 789",
            "Bitte zahlen Sie 55,08 EUR bis zum 15.10.2026.",
            f"IBAN: {BEITRAG_IBAN}",
        ),
    ),
    payload={
        "kind": "broadcasting_fee",
        "area": "home",
        "title": "Broadcasting fee",
        "sender": {"name": "Beitragsservice Musterstadt", "kind": "public_broadcaster"},
        "references": [{"label": "Beitragsnummer", "value": "123 456 789"}],
        "summary": "The broadcasting fee is due.",
        "explanation": "Pay the fee.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the broadcasting fee",
                "date": _fixed("2026-10-15", "payment", "bis zum 15.10.2026"),
                "amount": 55.08,
                "quote": "Bitte zahlen Sie 55,08 EUR bis zum 15.10.2026.",
            }
        ],
        "payment": {"iban": BEITRAG_IBAN, "payee": "Beitragsservice Musterstadt"},
        "case_title": "Broadcasting fee",
    },
)

SCAM_LETTER = Letter(
    marker="Letzte Mahnung Rundfunkgebühren",
    pages=(
        (
            "Rundfunk-Beitragsservice – Zahlungszentrale",
            "SPECIMEN",
            "Letzte Mahnung Rundfunkgebühren",
            "Zahlen Sie 210,00 EUR sofort, spätestens bis zum 01.10.2026.",
            f"IBAN: {SCAM_IBAN}",
        ),
    ),
    payload={
        "kind": "dunning",
        "area": "money",
        "title": "Final reminder for broadcasting fees",
        "sender": {"name": "Rundfunk-Beitragsservice – Zahlungszentrale", "kind": "company"},
        "summary": "Demands 210 EUR immediately.",
        "explanation": "Be careful: check this demand.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay 210 EUR",
                "date": _fixed("2026-10-01", "payment", "bis zum 01.10.2026"),
                "amount": 210.0,
                "quote": "Zahlen Sie 210,00 EUR sofort, spätestens bis zum 01.10.2026.",
            }
        ],
        "payment": {"iban": SCAM_IBAN, "payee": "Rundfunk-Beitragsservice"},
        "case_title": "Broadcasting fee demand",
    },
)

# --------------------------------------------------------------------------------------------------
# Contracts: new contract, price increase, cancellation confirmation
# --------------------------------------------------------------------------------------------------

GYM_CONTRACT_LETTER = Letter(
    marker="Mitgliedsvertrag",
    pages=(
        (
            "Muster Fitness GmbH",
            "SPECIMEN",
            "Mitgliedsvertrag",
            "Vertragsnummer: FIT-2024-001",
            "Vertragsbeginn: 01.03.2024, Mindestlaufzeit 24 Monate.",
            "Kündigungsfrist: 1 Monat. Monatsbeitrag 29,90 EUR.",
        ),
    ),
    payload={
        "kind": "contract",
        "area": "leisure",
        "title": "Gym membership contract",
        "sender": {"name": "Muster Fitness GmbH", "kind": "gym"},
        "document_date": "2024-02-20",
        "references": [{"label": "Vertragsnummer", "value": "FIT-2024-001"}],
        "summary": "Gym membership from March 2024.",
        "explanation": "A 24-month gym contract.",
        "contract": {
            "name": "Muster Fitness membership",
            "category": "gym",
            "concluded_date": "2024-02-20",
            "start_date": "2024-03-01",
            "initial_term_months": 24,
            "renewal_term_months": 0,
            "notice_value": 1,
            "notice_unit": "months",
            "notice_basis": "any_time",
            "cost_amount": 29.9,
            "cost_interval": "monthly",
            "quotes": ["Vertragsbeginn: 01.03.2024, Mindestlaufzeit 24 Monate."],
        },
        "case_title": "Gym membership",
    },
)

PRICE_INCREASE_LETTER = Letter(
    marker="Preisanpassung",
    pages=(
        (
            "Muster Fitness GmbH",
            "SPECIMEN",
            "Preisanpassung",
            "Vertragsnummer: FIT-2024-001",
            "Ab dem 01.11.2026 beträgt Ihr Monatsbeitrag 34,90 EUR statt 29,90 EUR.",
        ),
    ),
    payload={
        "kind": "price_increase",
        "area": "leisure",
        "title": "Gym price increase",
        "sender": {"name": "Muster Fitness GmbH", "kind": "gym"},
        "document_date": "2026-09-20",
        "references": [{"label": "Vertragsnummer", "value": "FIT-2024-001"}],
        "summary": "The monthly fee rises to 34.90 EUR.",
        "explanation": "Your gym fee goes up.",
        "change": {
            "type": "price_increase",
            "effective_date": "2026-11-01",
            "old_amount": 29.9,
            "new_amount": 34.9,
            "cost_interval": "monthly",
            "quote": "Ab dem 01.11.2026 beträgt Ihr Monatsbeitrag 34,90 EUR statt 29,90 EUR.",
        },
        "case_title": "Gym membership",
    },
)

CANCELLATION_LETTER = Letter(
    marker="Kündigungsbestätigung",
    pages=(
        (
            "Muster Fitness GmbH",
            "SPECIMEN",
            "Kündigungsbestätigung",
            "Vertragsnummer: FIT-2024-001",
            "Ihre Mitgliedschaft endet zum 28.02.2027.",
        ),
    ),
    payload={
        "kind": "cancellation_confirmation",
        "area": "leisure",
        "title": "Gym cancellation confirmed",
        "sender": {"name": "Muster Fitness GmbH", "kind": "gym"},
        "references": [{"label": "Vertragsnummer", "value": "FIT-2024-001"}],
        "summary": "The gym confirms the end of the membership.",
        "explanation": "Your membership ends on 28 Feb 2027.",
        "change": {
            "type": "cancellation_confirmation",
            "effective_date": "2027-02-28",
            "quote": "Ihre Mitgliedschaft endet zum 28.02.2027.",
        },
        "case_title": "Gym membership",
    },
)

ALL_LETTERS: tuple[Letter, ...] = (
    TAX_LETTER,
    APPOINTMENT_LETTER,
    INVOICE_LETTER,
    DUNNING_LETTER,
    BEITRAG_LETTER,
    SCAM_LETTER,
    GYM_CONTRACT_LETTER,
    PRICE_INCREASE_LETTER,
    CANCELLATION_LETTER,
)


# --------------------------------------------------------------------------------------------------
# Fake model
# --------------------------------------------------------------------------------------------------


class Router:
    """Answers requests like a model would for the canned letters.

    ``payloads`` (by marker) can be replaced to simulate a different answer on reprocessing;
    ``errors`` (by purpose) makes a purpose raise instead.
    """

    def __init__(self, letters: tuple[Letter, ...] = ALL_LETTERS, transcript: str = "") -> None:
        self.letters = letters
        self.transcript = transcript
        self.payloads: dict[str, dict[str, Any]] = {letter.marker: letter.extraction() for letter in letters}
        self.errors: dict[str, Callable[[], Exception]] = {}

    def __call__(self, req: LLMRequest) -> dict[str, Any]:
        if req.purpose in self.errors:
            raise self.errors[req.purpose]()
        if req.purpose == "transcribe":
            return {"text": self.transcript, "language": "de", "legible": True}
        if req.purpose == "extract":
            for letter in self.letters:
                if letter.marker in req.prompt:
                    return copy.deepcopy(self.payloads[letter.marker])
        raise KeyError(f"no canned answer for {req.purpose}")


def fake_backend(router: Router | None = None) -> FakeBackend:
    """A :class:`FakeBackend` answering through ``router`` (default: all canned letters)."""
    return FakeBackend(router or Router())


def record_events(bus: Any) -> list[tuple[str, dict[str, Any]]]:
    """Record every event published on ``bus`` (still delivering it) as ``(type, data)``."""
    events: list[tuple[str, dict[str, Any]]] = []
    publish = bus.publish

    def recording(type: str, **data: Any) -> None:
        events.append((type, data))
        publish(type, **data)

    bus.publish = recording
    return events
