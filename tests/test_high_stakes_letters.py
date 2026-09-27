"""High-stakes letters end to end: reading → the kind code files → routed dates → the deadlines the
law adds → the "get advice" card, corrections of the kind and the arrival day, and re-reading.

The letters are SPECIMEN texts with the extraction a model would return; the extraction prompt is
unchanged, so every high-stakes signal comes from the model's ordinary reading (ADR 0002).
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter, Router
from ordnung import clock
from ordnung.api.routes import documents
from ordnung.ingest import pipeline
from ordnung.ingest.plan import (
    KIND_CHOSEN,
    corrections,
    filed_kind,
    is_statement,
    late_statement_warning,
    needs_check,
    with_corrections,
)
from ordnung.models import DocumentExtraction, Item
from ordnung.rules import RuleContext
from ordnung.rules.advice import LATE_STATEMENT_WARNING, RENT_INCREASE_PAYMENT_WARNING
from test_api_support import TODAY, Api, ApiRouter, api_for

MB_QUOTE = "Sie können binnen zwei Wochen seit der Zustellung dieses Bescheids Widerspruch erheben."
#: The warning every Mahnbescheid carries (§ 692 Abs. 1 Nr. 4 ZPO); a reading quotes it as a matter of course.
MB_WARNING = (
    "Nach Ablauf dieser Frist kann der Antragsteller einen Vollstreckungsbescheid erwirken und aus diesem "
    "die Zwangsvollstreckung betreiben."
)
MAHNBESCHEID = Letter(
    marker="Mahnbescheid",
    pages=(
        (
            "Amtsgericht Hagen - Zentrales Mahngericht - 58084 Hagen",
            "SPECIMEN",
            "Mahnbescheid vom 21.09.2026",
            "Geschäftsnummer: 26-1234567-0-8",
            "Antragsteller: Inkasso Nord GmbH, Hauptforderung 480,00 EUR",
            MB_QUOTE,
            MB_WARNING,
        ),
    ),
    payload={
        "kind": "authority_letter",
        "area": "money",
        "title": "Mahnbescheid (court payment order)",
        "sender": {"name": "Amtsgericht Hagen - Zentrales Mahngericht", "kind": "authority"},
        "document_date": "2026-09-21",
        "references": [{"label": "Geschäftsnummer", "value": "26-1234567-0-8"}],
        "summary": (
            "A court payment order for 480 EUR claimed by Inkasso Nord GmbH; without an objection the claimant "
            "can apply for an enforcement order (Vollstreckungsbescheid)."
        ),
        "key_facts": [{"label": "If you don't object", "value": "Enforcement order", "quote": MB_WARNING}],
        "explanation": "Pay or object within two weeks.",
        "items": [
            {
                "kind": "deadline",
                "title": "Object or pay",
                "date": {
                    "type": "relative",
                    "anchor": "receipt",
                    "amount": 2,
                    "unit": "weeks",
                    "nature": "objection",
                    "text": "binnen zwei Wochen seit der Zustellung dieses Bescheids",
                },
                "quote": MB_QUOTE,
            }
        ],
        "remedy": {"type": "widerspruch", "addressee": "Amtsgericht Hagen", "quote": MB_QUOTE},
        "urgency": "critical",
    },
)

LABOUR_QUOTE = "Sie können binnen einer Woche seit der Zustellung dieses Bescheids Widerspruch erheben."
#: A labour court's Mahnbescheid (an employer reclaiming pay): one week, § 46a Abs. 3 ArbGG.
LABOUR_MAHNBESCHEID = Letter(
    marker="Arbeitsgericht Berlin",
    pages=(
        (
            "Arbeitsgericht Berlin - Magdeburger Platz 1 - 10785 Berlin",
            "SPECIMEN",
            "Mahnbescheid vom 21.09.2026",
            "Antragsteller: Café Kranz GmbH, Rückzahlung Lohnvorschuss 900,00 EUR",
            LABOUR_QUOTE,
        ),
    ),
    payload={
        "kind": "authority_letter",
        "area": "work",
        "title": "Mahnbescheid (court payment order)",
        "sender": {"name": "Arbeitsgericht Berlin", "kind": "authority"},
        "document_date": "2026-09-21",
        "summary": "A labour court payment order for 900 EUR claimed by your former employer.",
        "explanation": "Pay or object.",
        "items": [
            {
                "kind": "deadline",
                "title": "Object or pay",
                "date": {
                    "type": "relative",
                    "anchor": "receipt",
                    "amount": 1,
                    "unit": "weeks",
                    "nature": "objection",
                    "text": "binnen einer Woche seit der Zustellung dieses Bescheids",
                },
                "quote": LABOUR_QUOTE,
            }
        ],
        "remedy": {"type": "widerspruch", "addressee": "Arbeitsgericht Berlin", "quote": LABOUR_QUOTE},
        "urgency": "critical",
    },
)

DISMISSAL_QUOTE = "hiermit kündigen wir das Arbeitsverhältnis fristgerecht zum 31.12.2026."
DISMISSAL = Letter(
    marker="Kündigung Arbeitsverhältnis",
    pages=(
        (
            "Café Kranz GmbH · Marktplatz 3 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 24.09.2026",
            "Kündigung Arbeitsverhältnis",
            "Sehr geehrte Frau Rivera,",
            DISMISSAL_QUOTE,
        ),
    ),
    payload={
        "kind": "employment",
        "area": "work",
        "title": "Dismissal by Café Kranz",
        "sender": {"name": "Café Kranz GmbH", "kind": "employer"},
        "document_date": "2026-09-24",
        "summary": "Your employer ends your job on 31 Dec 2026.",
        "explanation": "Your job ends.",
        "items": [],
        "change": {
            "type": "termination_by_provider",
            "effective_date": "2026-12-31",
            "quote": DISMISSAL_QUOTE,
        },
        "urgency": "high",
    },
)

STATEMENT_QUOTE = "Abrechnungszeitraum: 01.01.2025 - 31.12.2025"
STATEMENT = Letter(
    marker="Betriebskostenabrechnung",
    pages=(
        (
            "Wohnbau Muster GmbH",
            "SPECIMEN",
            "Betriebskostenabrechnung",
            STATEMENT_QUOTE,
            "Nachzahlung 120,00 EUR",
        ),
    ),
    payload={
        "kind": "utility_bill",
        "area": "home",
        "title": "Operating-cost statement 2025",
        "sender": {"name": "Wohnbau Muster GmbH", "kind": "landlord"},
        "document_date": "2026-09-10",
        "summary": "Betriebskostenabrechnung 2025 with a back-payment of 120 EUR.",
        "explanation": "Check it.",
        "items": [],
        "key_facts": [{"label": "Billing period", "value": "2025", "quote": STATEMENT_QUOTE}],
    },
)

LATE_PERIOD = "Abrechnungszeitraum: 01.01.2024 - 31.12.2024"
LATE_PAY = "Bitte überweisen Sie die Nachzahlung von 120,00 EUR bis zum 30.09.2026."
#: A statement for 2024 dated 10 Sep 2026: after the twelve months (31 Dec 2025), with a back-payment.
LATE_STATEMENT = Letter(
    marker="Abrechnungszeitraum: 01.01.2024",
    pages=(("Wohnbau Muster GmbH", "SPECIMEN", "Betriebskostenabrechnung", LATE_PERIOD, LATE_PAY),),
    payload={
        **STATEMENT.payload,
        "title": "Operating-cost statement 2024",
        "summary": "Betriebskostenabrechnung 2024 with a back-payment of 120 EUR.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the back-payment",
                "amount": 120.0,
                "date": {
                    "type": "fixed",
                    "date": "2026-09-30",
                    "nature": "payment",
                    "text": "bis zum 30.09.2026",
                },
                "quote": LATE_PAY,
            }
        ],
        "key_facts": [{"label": "Billing period", "value": "2024", "quote": LATE_PERIOD}],
    },
)

BAILIFF_QUOTE = (
    "Aus dem Vollstreckungsbescheid des Amtsgerichts Hünfeld vom 01.03.2026 fordere ich Sie auf, 612,34 EUR "
    "zu zahlen."
)
#: A bailiff's payment demand under the letterhead every bailiff uses: named after the court (§ 154 GVG).
BAILIFF = Letter(
    marker="DR II 1234/26",
    pages=(
        (
            "Gerichtsvollzieher bei dem Amtsgericht Frankfurt am Main",
            "SPECIMEN",
            "DR II 1234/26",
            BAILIFF_QUOTE,
        ),
    ),
    payload={
        "kind": "authority_letter",
        "area": "money",
        "title": "Payment demand from the bailiff",
        "sender": {"name": "Gerichtsvollzieher bei dem Amtsgericht Frankfurt am Main", "kind": "authority"},
        "document_date": "2026-09-22",
        "summary": "The bailiff demands 612.34 EUR based on an enforcement order (Vollstreckungsbescheid).",
        "key_facts": [
            {"label": "Title", "value": "Vollstreckungsbescheid AG Hünfeld", "quote": BAILIFF_QUOTE}
        ],
        "explanation": "Pay or contact the bailiff.",
        "items": [],
        "urgency": "high",
    },
)
CLAIMANT_QUOTE = "Der Antragsgegner hat gegen den Mahnbescheid vom 01.09.2026 Widerspruch erhoben."
#: The court's notice to the person as the claimant (a tenant chasing a deposit): the other side objected.
CLAIMANT = Letter(
    marker="Nachricht an den Antragsteller",
    pages=(
        (
            "Amtsgericht Coburg - Zentrales Mahngericht",
            "SPECIMEN",
            "Nachricht an den Antragsteller",
            CLAIMANT_QUOTE,
        ),
    ),
    payload={
        "kind": "authority_letter",
        "area": "money",
        "title": "Objection filed against your Mahnbescheid",
        "sender": {"name": "Amtsgericht Coburg - Zentrales Mahngericht", "kind": "authority"},
        "document_date": "2026-09-22",
        "summary": "The other side objected to the Mahnbescheid; pay the further fee to continue.",
        "key_facts": [{"label": "Objection", "value": "filed", "quote": CLAIMANT_QUOTE}],
        "explanation": "Decide whether to continue.",
        "items": [],
        "urgency": "normal",
    },
)
SEVERANCE_QUOTE = (
    "Lassen Sie die Frist für eine Kündigungsschutzklage verstreichen, zahlen wir Ihnen zum 31.12.2026 eine "
    "Abfindung."
)
#: A dismissal with a severance offer (§ 1a KSchG), which must mention the court action.
SEVERANCE = Letter(
    marker="Kündigung mit Abfindungsangebot",
    pages=(
        ("Café Kranz GmbH", "SPECIMEN", "Kündigung mit Abfindungsangebot", DISMISSAL_QUOTE, SEVERANCE_QUOTE),
    ),
    payload={
        **DISMISSAL.payload,
        "title": "Dismissal with a severance offer",
        "items": [
            {
                "kind": "payment",
                "title": "Severance payment (if you don't sue)",
                "date": {
                    "type": "fixed",
                    "date": "2026-12-31",
                    "nature": "payment",
                    "text": "zum 31.12.2026 eine Abfindung, wenn Sie keine Kündigungsschutzklage erheben",
                },
                "quote": SEVERANCE_QUOTE,
            }
        ],
    },
)


def _notice(marker: str, quote: str, end: str | None = "2027-03-31") -> Letter:
    """A landlord's notice ending the tenancy on ``end`` (31 Mar 2027), in the words of ``quote``."""
    return Letter(
        marker=marker,
        pages=(("Hausverwaltung Muster GmbH", "SPECIMEN", marker, quote),),
        payload={
            "kind": "rent_lease",
            "area": "home",
            "title": "Notice from your landlord",
            "sender": {"name": "Hausverwaltung Muster GmbH", "kind": "landlord"},
            "document_date": "2026-09-24",
            "summary": "Your landlord ends the tenancy.",
            "explanation": "Get advice.",
            "items": [],
            "change": {"type": "termination_by_provider", "effective_date": end, "quote": quote},
            "urgency": "high",
        },
    )


FRISTLOS = _notice(
    "Fristlose Kündigung",
    "hiermit kündigen wir das Mietverhältnis fristlos wegen Zahlungsverzugs.",
    end=None,
)
ARREARS_QUOTE = "Den Mietrückstand von 1.920,00 EUR zahlen Sie bitte bis zum 10.10.2026."
#: A notice without notice period that also asks for the arrears — paying them doesn't deal with the notice.
FRISTLOS_ARREARS = _notice(
    "Fristlose Kuendigung Rueckstand",
    f"hiermit kündigen wir das Mietverhältnis fristlos wegen Zahlungsverzugs. {ARREARS_QUOTE}",
    end=None,
)
FRISTLOS_ARREARS.payload["items"] = [
    {
        "kind": "payment",
        "title": "Pay the rent arrears",
        "amount": 1920.0,
        "direction": "out",
        "date": {"type": "fixed", "date": "2026-10-10", "nature": "payment", "text": "bis zum 10.10.2026"},
        "quote": ARREARS_QUOTE,
    }
]
HILFSWEISE = _notice(
    "Kündigung fristlos, hilfsweise fristgerecht",
    "hiermit kündigen wir das Mietverhältnis fristlos, hilfsweise fristgerecht zum 31.03.2027.",
)

HILFSWEISE_NEXT = _notice(
    "Kündigung fristlos, hilfsweise zum nächstmöglichen Termin",
    "hiermit kündigen wir das Mietverhältnis fristlos, hilfsweise fristgerecht zum nächstmöglichen Termin.",
    end="2026-09-30",
)
#: Review round 2 of phase 2: an ordinary notice to the next possible date writes no end, and one only
#: called "außerordentlich" may have the statutory period (§ 573d BGB) — both keep the objection.
NEXT_POSSIBLE = _notice(
    "Kuendigung Eigenbedarf naechstmoeglich",
    "Hiermit kündigen wir das Mietverhältnis wegen Eigenbedarfs fristgerecht zum nächstmöglichen Termin.",
    end=None,
)
ONLY_EXTRAORDINARY = _notice(
    "Ausserordentliche Kuendigung",
    "Hiermit kündigen wir das Mietverhältnis außerordentlich.",
    end=None,
)
HILFSWEISE_NO_END = _notice(
    "Kuendigung nach 543 und 573",
    "hiermit kündigen wir das Mietverhältnis nach § 543 BGB, hilfsweise ordentlich nach § 573 BGB.",
    end=None,
)
#: A notice whose end date the model misread (the letter says 31.03.2027), and one that states it
#: only in the letter's heading, not in the sentence that gives notice.
MISREAD_END = _notice(
    "Kuendigung Wohnung Musterweg",
    "hiermit kündigen wir das Mietverhältnis fristgerecht zum 31.03.2027.",
    end="2027-05-31",
)
END_IN_HEADING = Letter(
    marker="Kuendigung zum Quartalsende",
    pages=(
        (
            "Hausverwaltung Muster GmbH",
            "SPECIMEN",
            "Kuendigung zum Quartalsende - Mietende 31.03.2027",
            "hiermit kündigen wir das Mietverhältnis fristgerecht zum nächstmöglichen Zeitpunkt.",
        ),
    ),
    payload={
        **MISREAD_END.payload,
        "change": {
            "type": "termination_by_provider",
            "effective_date": "2027-03-31",
            "quote": "hiermit kündigen wir das Mietverhältnis fristgerecht zum nächstmöglichen Zeitpunkt.",
        },
    },
)
ON_TIME_NOTICE = _notice(
    "Ordentliche Kuendigung Eigenbedarf",
    "hiermit kündigen wir das Mietverhältnis wegen Eigenbedarfs fristgerecht zum 31.03.2027.",
)

MB_PAY_QUOTE = (
    "Es fordert Sie hiermit auf, innerhalb von zwei Wochen seit der Zustellung dieses Bescheids die behauptete "
    "Schuld zu begleichen oder dem Gericht mitzuteilen, ob Sie dem Anspruch widersprechen."
)
#: A Mahnbescheid whose reading has only a payment item: the official wording read as "pay".
MB_PAYMENT_ONLY = Letter(
    marker="Mahnbescheid Zahlungsaufforderung",
    pages=((*MAHNBESCHEID.pages[0], MB_PAY_QUOTE, "Mahnbescheid Zahlungsaufforderung"),),
    payload={
        **MAHNBESCHEID.payload,
        "items": [
            {
                "kind": "payment",
                "title": "Pay 480 EUR",
                "amount": 480.0,
                "date": {
                    "type": "relative",
                    "anchor": "receipt",
                    "amount": 2,
                    "unit": "weeks",
                    "nature": "payment",
                    "text": "innerhalb von zwei Wochen seit der Zustellung dieses Bescheids",
                },
                "quote": MB_PAY_QUOTE,
            }
        ],
    },
)

REMINDER_QUOTE = (
    "aus unserer Betriebskostenabrechnung 2023 vom 15.11.2024 ist noch eine Nachzahlung von 312,40 EUR offen."
)
REMINDER_PAY = "Bitte überweisen Sie den Betrag bis zum 05.10.2026."
#: Final review 1: a landlord's payment reminder about an old statement that arrived on time.
REMINDER = Letter(
    marker="Zahlungserinnerung Nachzahlung",
    pages=(
        (
            "Hausverwaltung Muster GmbH",
            "SPECIMEN",
            "Zahlungserinnerung Nachzahlung",
            REMINDER_QUOTE,
            REMINDER_PAY,
        ),
    ),
    payload={
        "kind": "dunning",
        "area": "home",
        "title": "Payment reminder: back-payment from the operating-cost statement 2023",
        "sender": {"name": "Hausverwaltung Muster GmbH", "kind": "landlord"},
        "document_date": "2026-09-20",
        "summary": "The Betriebskostenabrechnung 2023 of 15.11.2024 left a back-payment of 312.40 EUR unpaid.",
        "explanation": "Pay it.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the back-payment",
                "amount": 312.4,
                "date": {
                    "type": "fixed",
                    "date": "2026-10-05",
                    "nature": "payment",
                    "text": "bis zum 05.10.2026",
                },
                "quote": REMINDER_PAY,
            }
        ],
        "key_facts": [{"label": "Statement", "value": "2023, of 15.11.2024", "quote": REMINDER_QUOTE}],
    },
)

MIXED_CREDIT = "Ihr Guthaben aus der Heizkostenabrechnung von 85,00 EUR überweisen wir bis zum 30.09.2026."
MIXED_PREPAYMENT = "Vorauszahlung ab 01.10.2026 monatlich 210,00 EUR."
#: Final review 1: a late 2024 statement with a back-payment, a credit and the new monthly prepayment.
LATE_MIXED = Letter(
    marker="Abrechnung 2024 mit Guthaben",
    pages=(
        (
            "Wohnbau Muster GmbH",
            "SPECIMEN",
            "Abrechnung 2024 mit Guthaben",
            LATE_PERIOD,
            LATE_PAY,
            MIXED_CREDIT,
            MIXED_PREPAYMENT,
        ),
    ),
    payload={
        **LATE_STATEMENT.payload,
        "items": [
            *LATE_STATEMENT.payload["items"],
            {
                "kind": "payment",
                "title": "Credit from the heating statement",
                "amount": 85.0,
                "direction": "in",
                "date": {
                    "type": "fixed",
                    "date": "2026-09-30",
                    "nature": "payment",
                    "text": "bis zum 30.09.2026",
                },
                "quote": MIXED_CREDIT,
            },
            {
                "kind": "payment",
                "title": "New monthly prepayment",
                "amount": 210.0,
                "recurrence": {"interval": 1, "unit": "months"},
                "date": {"type": "fixed", "date": "2026-10-01", "nature": "payment", "text": "ab 01.10.2026"},
                "quote": MIXED_PREPAYMENT,
            },
        ],
    },
)

INCREASE_QUOTE = "Wir bitten Sie um Zustimmung zur Erhöhung der Miete auf die ortsübliche Vergleichsmiete."
INCREASE_PAY = "Neue monatliche Miete 670,00 EUR ab dem 01.12.2026."
#: Final review 1: a § 558 request whose reading has the new total as a recurring payment.
RENT_INCREASE = Letter(
    marker="Mieterhoehungsverlangen Musterweg",
    pages=(
        (
            "Hausverwaltung Muster GmbH",
            "SPECIMEN",
            "Mieterhoehungsverlangen Musterweg",
            INCREASE_QUOTE,
            INCREASE_PAY,
        ),
    ),
    payload={
        "kind": "rent_lease",
        "area": "home",
        "title": "Rent increase request",
        "sender": {"name": "Hausverwaltung Muster GmbH", "kind": "landlord"},
        "document_date": "2026-09-24",
        "summary": "Your landlord asks you to agree to a rent of 670 EUR.",
        "explanation": "Decide.",
        "items": [
            {
                "kind": "payment",
                "title": "New monthly rent",
                "amount": 670.0,
                "recurrence": {"interval": 1, "unit": "months"},
                "date": {
                    "type": "fixed",
                    "date": "2026-12-01",
                    "nature": "payment",
                    "text": "ab dem 01.12.2026",
                },
                "quote": INCREASE_PAY,
            }
        ],
        "change": {
            "type": "price_increase",
            "old_amount": 640.0,
            "new_amount": 670.0,
            "quote": INCREASE_QUOTE,
        },
    },
)

CURRENT_PAY = "Ihre derzeitige Miete von 640,00 EUR ist weiterhin zum 01.10.2026 fällig."
NEW_RENT_UNDATED = "Die neue Miete beträgt 670,00 EUR."
#: Review round 2 of phase 2: a § 558 request whose reading has the current rent as a payment next to an
#: undated new rent — only the new rent is "decide before you pay".
RENT_INCREASE_CURRENT = Letter(
    marker="Mieterhoehung mit laufender Miete",
    pages=(
        (
            "Hausverwaltung Muster GmbH",
            "SPECIMEN",
            "Mieterhoehung mit laufender Miete",
            INCREASE_QUOTE,
            CURRENT_PAY,
            NEW_RENT_UNDATED,
        ),
    ),
    payload={
        **RENT_INCREASE.payload,
        "items": [
            {
                "kind": "payment",
                "title": "Rent for October",
                "amount": 640.0,
                "date": {
                    "type": "fixed",
                    "date": "2026-10-01",
                    "nature": "payment",
                    "text": "zum 01.10.2026",
                },
                "quote": CURRENT_PAY,
            },
            {
                "kind": "payment",
                "title": "New monthly rent",
                "amount": 670.0,
                "date": {"type": "none", "nature": "payment", "text": ""},
                "quote": NEW_RENT_UNDATED,
            },
        ],
        "change": {**RENT_INCREASE.payload["change"], "effective_date": "2026-12-01"},
    },
)

#: Final review 1: an ordinary notice ending the tenancy five weeks after its date — the objection date
#: (31 Aug 2026) had passed when it was written.
SHORT_NOTICE = _notice(
    "Kuendigung zum Oktober",
    "hiermit kündigen wir das Mietverhältnis fristgerecht zum 31.10.2026.",
    end="2026-10-31",
)
OBJECTION_BY = "Ein Widerspruch muss uns bis spätestens 31.01.2027 in Textform zugehen."
#: Final review 1: a notice whose end the reading missed, but whose own objection date it read.
OBJECTION_DATE_ONLY = Letter(
    marker="Kuendigung mit Widerspruchsfrist",
    pages=(("Hausverwaltung Muster GmbH", "SPECIMEN", "Kuendigung mit Widerspruchsfrist", OBJECTION_BY),),
    payload={
        **_notice("x", "hiermit kündigen wir das Mietverhältnis fristgerecht.", end=None).payload,
        "items": [
            {
                "kind": "deadline",
                "title": "Object to the notice",
                "date": {
                    "type": "fixed",
                    "date": "2027-01-31",
                    "nature": "objection",
                    "text": "bis spätestens 31.01.2027",
                },
                "quote": OBJECTION_BY,
            }
        ],
    },
)
COURT_ASKS = "Sie erhalten Gelegenheit, binnen zwei Wochen nach Zustellung Stellung zu nehmen."
#: Final review 1: a court's letter that isn't an order: its period still runs from delivery (§ 180 ZPO).
COURT_REQUEST = Letter(
    marker="Aufforderung zur Stellungnahme",
    pages=(("Amtsgericht Musterstadt", "SPECIMEN", "Aufforderung zur Stellungnahme", COURT_ASKS),),
    payload={
        "kind": "authority_letter",
        "area": "money",
        "title": "Request for your comment",
        "sender": {"name": "Amtsgericht Musterstadt", "kind": "authority"},
        "document_date": "2026-09-21",
        "summary": "The court asks for your comment.",
        "explanation": "Answer in time.",
        "items": [
            {
                "kind": "deadline",
                "title": "Comment",
                "date": {
                    "type": "relative",
                    "anchor": "receipt",
                    "amount": 2,
                    "unit": "weeks",
                    "nature": "declaration",
                    "text": "binnen zwei Wochen nach Zustellung",
                },
                "quote": COURT_ASKS,
            }
        ],
    },
)

PUBLIC_DISMISSAL_QUOTE = "hiermit kündigen wir das Arbeitsverhältnis fristgerecht zum 31.03.2027."
PUBLIC_ACTION_QUOTE = "Klage muss innerhalb von drei Wochen nach Zugang der Kündigung erhoben werden."


def _public_dismissal(marker: str, date_spec: dict[str, Any]) -> Letter:
    """A city's dismissal of its employee, read as an authority's letter (review round 1: § 4 KSchG)."""
    return Letter(
        marker=marker,
        pages=(
            (
                "Stadt Musterstadt - Personalamt",
                "SPECIMEN",
                marker,
                PUBLIC_DISMISSAL_QUOTE,
                PUBLIC_ACTION_QUOTE,
            ),
        ),
        payload={
            "kind": "employment",
            "area": "work",
            "title": "Dismissal by the city",
            "sender": {"name": "Stadt Musterstadt - Personalamt", "kind": "authority"},
            "document_date": "2026-09-21",
            "summary": "The city ends your job on 31 Mar 2027.",
            "explanation": "Get advice.",
            "contract": {"name": "Arbeitsvertrag", "category": "employment"},
            "items": [
                {
                    "kind": "deadline",
                    "title": "Kündigungsschutzklage",
                    "date": {"nature": "objection", "legal_basis": "§ 4 KSchG", **date_spec},
                    "quote": PUBLIC_ACTION_QUOTE,
                }
            ],
            "change": {
                "type": "termination_by_provider",
                "effective_date": "2027-03-31",
                "quote": PUBLIC_DISMISSAL_QUOTE,
            },
            "urgency": "high",
        },
    )


PUBLIC_DISMISSAL = _public_dismissal(
    "Kuendigung Personalamt",
    {
        "type": "relative",
        "anchor": "deemed_delivery",
        "delivery_rule": "de_admin_post",
        "amount": 3,
        "unit": "weeks",
        "text": "innerhalb von drei Wochen nach Zugang der Kündigung",
    },
)
#: The same, read as counting from a later start the reading names: the law's own date must still show.
PUBLIC_DISMISSAL_LATER = _public_dismissal(
    "Kuendigung Personalamt zugestellt",
    {
        "type": "relative",
        "anchor": "explicit_date",
        "anchor_date": "2026-09-28",
        "amount": 3,
        "unit": "weeks",
        "text": "innerhalb von drei Wochen nach Zugang der Kündigung",
    },
)

EARLY_PAY = "Neue monatliche Miete 670,00 EUR ab dem 01.11.2026."
#: Review round 1: a § 558 request that names an earlier start than the law allows (1 Dec).
RENT_INCREASE_EARLY = Letter(
    marker="Mieterhoehungsverlangen Lindenweg",
    pages=(
        (
            "Hausverwaltung Muster GmbH",
            "SPECIMEN",
            "Mieterhoehungsverlangen Lindenweg",
            INCREASE_QUOTE,
            EARLY_PAY,
        ),
    ),
    payload={
        **RENT_INCREASE.payload,
        "items": [
            {
                **RENT_INCREASE.payload["items"][0],
                "date": {
                    "type": "fixed",
                    "date": "2026-11-01",
                    "nature": "payment",
                    "text": "ab dem 01.11.2026",
                },
                "quote": EARLY_PAY,
            }
        ],
    },
)

#: Routed by the first marker found: the letters that quote another's marker come first.
LETTERS = (
    RENT_INCREASE_EARLY,
    PUBLIC_DISMISSAL_LATER,
    PUBLIC_DISMISSAL,
    FRISTLOS_ARREARS,
    REMINDER,
    LATE_MIXED,
    RENT_INCREASE,
    RENT_INCREASE_CURRENT,
    SHORT_NOTICE,
    OBJECTION_DATE_ONLY,
    COURT_REQUEST,
    LATE_STATEMENT,
    MB_PAYMENT_ONLY,
    MISREAD_END,
    END_IN_HEADING,
    ON_TIME_NOTICE,
    BAILIFF,
    CLAIMANT,
    SEVERANCE,
    LABOUR_MAHNBESCHEID,
    MAHNBESCHEID,
    DISMISSAL,
    STATEMENT,
    HILFSWEISE_NEXT,
    HILFSWEISE_NO_END,
    HILFSWEISE,
    FRISTLOS,
    NEXT_POSSIBLE,
    ONLY_EXTRAORDINARY,
)


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def _router() -> ApiRouter:
    router = ApiRouter()
    Router.__init__(router, letters=LETTERS)
    return router


async def _read(api: Api, letter: Letter) -> str:
    body = await api.upload((f"{letter.marker}.pdf", letter.pdf()))
    await api.read_all()
    return str(body["documents"][0]["id"])


def _by_origin(api: Api, doc_id: str) -> dict[str, list[Item]]:
    found: dict[str, list[Item]] = {}
    for item in api.ctx.store.list_items(doc_id=doc_id):
        found.setdefault(item.origin, []).append(item)
    return found


async def test_a_court_payment_order_is_filed_routed_and_carries_the_advice_card(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "court_payment_order"
        [objection] = detail["items"]  # the letter's own deadline follows the court rule: no duplicate
        assert objection["origin"] == "extracted"
        assert (
            objection["due_date"] == "2026-10-05"
        )  # from the letter's date until the envelope date is known
        assert "zpo_692" in objection["computation"]["rule_ids"]
        assert objection["computation"]["confidence"] == "low"
        advice = detail["advice"]
        assert advice["kind"] == "court_payment_order" and advice["urgent"] is True
        assert advice["help"][0]["name"].startswith("Rechtsantragstelle")
        assert any(
            "may be time-barred" in fact["title"].lower() or "may be time-barred" in fact["text"]
            for fact in advice["facts"]
        )

        # the envelope date: two weeks from Thu 24 Sep
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-24"})
        assert response.status_code == 200
        [objection_item] = api.ctx.store.list_items(doc_id=doc_id)
        assert objection_item.due_date == "2026-10-08"
        assert objection_item.computation is not None and objection_item.computation.confidence == "medium"

        filtered = (await api.client.get("/api/documents", params={"kind": "court_payment_order"})).json()
        assert [doc["id"] for doc in filtered] == [doc_id]


async def test_a_labour_courts_payment_order_gives_one_week(data_dir: Path) -> None:
    """§ 46a Abs. 3 ArbGG: one week, not the two weeks of § 692 ZPO — in the dates, the card and the
    sending advice."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, LABOUR_MAHNBESCHEID)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "court_payment_order"
        [objection] = detail["items"]  # counted under the labour court's rule: no second to-do
        assert objection["due_date"] == "2026-09-28" and objection["computation"]["confidence"] == "low"
        assert "arbgg_46a" in objection["computation"]["rule_ids"]
        assert not any("two weeks" in w for w in objection["computation"]["warnings"])
        advice = detail["advice"]
        assert advice["urgent"] and "one week" in advice["title"]
        assert all("online-mahnantrag" not in link["url"] for link in advice["help"])
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-23"})
        [item] = api.ctx.store.list_items(doc_id=doc_id)
        assert item.due_date == "2026-09-30"


async def test_correcting_the_kind_reroutes_the_dates(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "authority_letter"})
        assert response.status_code == 200
        [item] = api.ctx.store.list_items(doc_id=doc_id)
        assert item.computation is not None and "zpo_692" not in item.computation.rule_ids
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["advice"] is None

        activity = (await api.client.get("/api/activity")).json()
        assert any(
            entry["kind"] == "document.kind" and entry["data"]["kind"] == "authority_letter"
            for entry in activity
        )

        # re-reading keeps the person's correction, although it is the model's own kind
        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()
        assert (api.ctx.store.get_document(doc_id) or pytest.fail()).kind == "authority_letter"


async def test_a_kind_chosen_while_the_letter_is_read_again_is_kept(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 4: the person files the letter as another kind after a re-read took its snapshot of
    the letter and before it commits. The commit reads the letter again (under the ledger lock), sees the
    chosen kind and its "kind chosen" entry, and keeps both."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        real_commit = pipeline.commit_ledger

        def patched_in_between(store: Any, data: Any) -> Any:
            assert data.document.kind == "court_payment_order"  # the re-read's snapshot
            documents._patch(store, doc_id, {"kind": "authority_letter"}, None, date.fromisoformat(TODAY))
            return real_commit(store, data)

        monkeypatch.setattr(pipeline, "commit_ledger", patched_in_between)
        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()
        assert (api.ctx.store.get_document(doc_id) or pytest.fail()).kind == "authority_letter"
        assert all(item.origin != "rule" for item in api.ctx.store.list_items(doc_id=doc_id))


async def test_choosing_a_kind_writes_it_and_its_entry_together_under_the_ledger_lock(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kind and the "kind chosen" entry are written in one transaction under the ledger lock, before
    the dates are recomputed: no re-read can commit in between and file the letter under code's kind."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        lock = pipeline.ledger_lock()
        real_apply, real_recompute = documents._apply_patch, documents.recompute_document_items
        seen: list[str] = []

        def apply_patch(store: Any, doc: str, changes: dict[str, object]) -> Any:
            assert lock.locked()
            seen.append("patch")
            return real_apply(store, doc, changes)

        def recompute(store: Any, document: Any, today: Any, **kw: Any) -> Any:
            chosen = store.last_activity("document", doc_id, [KIND_CHOSEN])
            assert chosen is not None and chosen.data["kind"] == "authority_letter"
            seen.append("recompute")
            return real_recompute(store, document, today, **kw)

        monkeypatch.setattr(documents, "_apply_patch", apply_patch)
        monkeypatch.setattr(documents, "recompute_document_items", recompute)
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "authority_letter"})
        assert response.status_code == 200 and seen == ["patch", "recompute"]


async def test_a_letter_filed_before_ordnung_knew_its_kind_gets_it_when_read_again(data_dir: Path) -> None:
    """An older Ordnung filed a Mahnbescheid under the model's kind. That is no correction by the
    person, so "Read again" files it as a court order with its card and its rule to-do."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        api.ctx.store.update_document(doc_id, kind="authority_letter")  # as an older version stored it
        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "court_payment_order"
        assert detail["advice"] is not None and detail["advice"]["urgent"]


async def test_a_dismissal_gets_the_deadlines_the_law_adds(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, DISMISSAL)
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and document.kind == "dismissal"
        assert document.status == "processed"  # a deadline set by law has no quote to check
        rules = {item.slot_key: item for item in _by_origin(api, doc_id)["rule"]}
        court, register = rules["rule:kschg_4"], rules["rule:sgb3_38"]
        assert (
            court.due_date == "2026-10-15" and court.priority == "critical"
        )  # 3 weeks from the letter's date
        assert court.computation is not None and court.computation.confidence == "low"
        assert register.due_date == "2026-09-30"  # three months before 31 Dec
        assert not needs_check(court) and court.grounding == "model_read" and court.evidence == []
        assert court.date_spec is not None and court.date_spec.anchor == "receipt"

        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["advice"]["kind"] == "dismissal" and detail["advice"]["urgent"]

        # the person confirms the arrival: the rule to-dos follow
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-25"})
        court_after = api.ctx.store.get_item(court.id)
        assert court_after is not None and court_after.due_date == "2026-10-16"
        assert court_after.computation is not None and court_after.computation.confidence == "medium"


async def test_a_public_employers_dismissal_counts_from_its_arrival(data_dir: Path) -> None:
    """Review round 1: a dismissal is a private-law declaration that takes effect on receipt (§ 130 BGB, § 4
    S. 1 KSchG), from a city as from a company — never with the VwVfG's delivery fiction (15 Oct, and the
    law's to-do suppressed behind it), but three weeks from the letter's date until it arrived: 12 Oct."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, PUBLIC_DISMISSAL)
        assert api.ctx.store.get_document(doc_id).kind == "dismissal"  # type: ignore[union-attr]
        found = _by_origin(api, doc_id)
        [action] = found["extracted"]
        assert action.due_date == "2026-10-12"
        assert action.computation is not None and "posting_day" not in action.computation.rule_ids
        assert {item.slot_key for item in found["rule"]} == {"rule:sgb3_38"}  # the letter's own to-do is it


async def test_the_laws_date_is_filed_when_the_letters_own_date_is_later(data_dir: Path) -> None:
    """Review round 1: a letter's own date computed under the rule no longer hides the law's to-do when it
    is later (here read from a later start): the earlier, law's date is filed next to it."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, PUBLIC_DISMISSAL_LATER)
        found = _by_origin(api, doc_id)
        [action] = found["extracted"]
        assert action.due_date == "2026-10-19"
        rules = {item.slot_key: item for item in found["rule"]}
        assert rules["rule:kschg_4"].due_date == "2026-10-12"


async def test_rule_to_dos_survive_re_reading_and_leave_when_the_kind_is_corrected(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, DISMISSAL)
        rules = {item.slot_key: item for item in _by_origin(api, doc_id)["rule"]}
        api.ctx.store.update_item(rules["rule:sgb3_38"].id, status="done")

        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()
        again = {item.slot_key: item for item in _by_origin(api, doc_id)["rule"]}
        assert {item.id for item in again.values()} == {item.id for item in rules.values()}
        assert again["rule:sgb3_38"].status == "done"

        await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "employment"})
        left = _by_origin(api, doc_id).get("rule", [])
        assert [item.slot_key for item in left] == ["rule:sgb3_38"]  # done: kept; open: removed


@pytest.mark.parametrize("letter", [BAILIFF, CLAIMANT], ids=["bailiff", "claimant"])
async def test_letters_that_only_name_a_court_order_are_not_one(data_dir: Path, letter: Letter) -> None:
    """A bailiff's letter (headed with the court's name) and the court's notice to the claimant name an
    order without asking the person to answer it: no court order, no two-week to-do, no urgent card."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, letter)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "authority_letter"
        assert detail["items"] == [] and detail["advice"] is None


async def test_an_item_that_only_mentions_the_court_action_leaves_its_to_do(data_dir: Path) -> None:
    """The severance a § 1a KSchG dismissal offers names the court action; it is a payment, not the
    three-week deadline, so the law's to-do for the court action is still filed."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, SEVERANCE)
        found = _by_origin(api, doc_id)
        assert {item.slot_key for item in found["rule"]} == {"rule:kschg_4", "rule:sgb3_38"}
        [severance] = found["extracted"]
        assert severance.computation is not None and "kschg_4" not in severance.computation.rule_ids
        assert not any("court action" in warning for warning in severance.computation.warnings)


async def test_a_deleted_rule_to_do_stays_deleted_until_the_kind_is_chosen(data_dir: Path) -> None:
    """The person already registered as job-seeking and deleted that to-do: a changed region, postal
    buffer or arrival day recomputes the rule to-dos that are left, and never files it again."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, DISMISSAL)
        rules = {item.slot_key: item for item in _by_origin(api, doc_id)["rule"]}
        register, court = rules["rule:sgb3_38"], rules["rule:kschg_4"]
        assert (await api.client.delete(f"/api/items/{register.id}")).status_code == 204

        assert (await api.client.put("/api/profile", json={"region": "BE"})).status_code == 200
        assert (await api.client.put("/api/profile", json={"postal_buffer_days": 2})).status_code == 200
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-25"})
        assert api.ctx.store.get_item(register.id) is None
        court_after = api.ctx.store.get_item(court.id)
        assert court_after is not None and court_after.due_date == "2026-10-16"  # still recomputed

        # choosing the kind is an explicit request to file the letter's deadlines again
        await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "employment"})
        await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "dismissal"})
        assert api.ctx.store.get_item(register.id) is not None


async def test_a_chosen_kind_reroutes_even_with_an_unconfirmed_arrival_day(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        response = await api.client.patch(
            f"/api/documents/{doc_id}", json={"kind": "authority_letter", "received_confirmed": False}
        )
        assert response.status_code == 200
        [item] = api.ctx.store.list_items(doc_id=doc_id)
        assert item.computation is not None and "zpo_692" not in item.computation.rule_ids
        activity = (await api.client.get("/api/activity")).json()
        assert any(entry["kind"] == "document.kind" for entry in activity)


@pytest.mark.parametrize(
    ("letter", "objection"), [(FRISTLOS, False), (HILFSWEISE, True)], ids=["fristlos", "hilfsweise"]
)
async def test_a_notice_without_notice_period_gets_no_hardship_objection(
    data_dir: Path, letter: Letter, objection: bool
) -> None:
    """The hardship objection doesn't apply to a notice without notice period (§ 574 Abs. 1 S. 2 BGB):
    no to-do and no letter to draft — unless it also gives notice with a notice period (hilfsweise)."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, letter)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "landlord_notice"
        advice = detail["advice"]
        assert advice["facts"][0]["title"].startswith("This reads as a notice without notice period")
        assert advice["draft"] == ("objection" if objection else None)
        rules = [item["due_date"] for item in detail["items"] if item["origin"] == "rule"]
        assert rules == (["2027-01-31"] if objection else [])  # two months before 31 Mar 2027
        if not objection:
            # the composer refuses the hardship objection the card doesn't offer (§ 574 Abs. 1 S. 2 BGB)
            refused = await api.client.post("/api/drafts", json={"kind": "objection", "doc_id": doc_id})
            assert refused.status_code == 422
            assert (
                "doesn't apply" in refused.json()["detail"]
                and "§ 569 Abs. 3 Nr. 2" in refused.json()["detail"]
            )


@pytest.mark.parametrize(
    "letter", [NEXT_POSSIBLE, ONLY_EXTRAORDINARY], ids=["next-possible", "außerordentlich"]
)
async def test_a_notice_without_an_end_or_only_extraordinary_keeps_its_objection(
    data_dir: Path, letter: Letter
) -> None:
    """Review round 2 of phase 2: a notice "zum nächstmöglichen Termin" got no objection to-do (its card asked
    for an end the notice doesn't write), and "außerordentlich" alone lost the to-do and the letter. The
    objection counts back from the earliest end (arrived 24 Sep 2026: 31 Dec 2026, objection by 31 Oct)."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, letter)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "landlord_notice"
        [rule] = [item for item in detail["items"] if item["origin"] == "rule"]
        assert rule["due_date"] == "2026-10-31" and "bgb_573c_landlord" in rule["computation"]["rule_ids"]
        advice = detail["advice"]
        assert advice["draft"] == "objection"
        assert not any("there is no to-do" in step for step in advice["steps"])
        if letter is ONLY_EXTRAORDINARY:
            assert advice["facts"][0]["title"] == "This may be a notice without notice period"
        else:
            assert advice["facts"] == [] and not advice["urgent"]
        drafted = await api.client.post("/api/drafts", json={"kind": "objection", "doc_id": doc_id})
        assert drafted.status_code != 422, drafted.text


async def test_a_statement_filed_by_the_person_as_its_stored_kind_loses_its_card(data_dir: Path) -> None:
    """Review round 2 of phase 2: a statement recognised on read (stored as a utility bill) kept its card and
    its "may not be owed" note when the person chose "Utility bill" — the kind it is stored as, so nothing
    was recorded or worked out again."""
    from ordnung.ingest.plan import KIND_CHOSEN

    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, LATE_STATEMENT)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "utility_bill" and detail["advice"]["kind"] == "operating_costs"
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "utility_bill"})
        assert response.status_code == 200
        after = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert after["advice"] is None
        [payment] = after["items"]
        assert LATE_STATEMENT_WARNING not in payment["computation"]["warnings"]
        assert api.ctx.store.last_activity("document", doc_id, [KIND_CHOSEN]) is not None
        # filing it as a statement brings both back
        await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "operating_costs"})
        again = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert again["advice"]["kind"] == "operating_costs"
        assert LATE_STATEMENT_WARNING in again["items"][0]["computation"]["warnings"]


async def test_a_payment_order_read_as_pay_still_gets_pay_or_object(data_dir: Path) -> None:
    """A court order's payment date is only half of what it asks: the law's "pay or object" to-do is
    filed next to it, so the to-do lists never frame it like a dunning letter."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MB_PAYMENT_ONLY)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "court_payment_order"
        by_origin = _by_origin(api, doc_id)
        [payment] = by_origin["extracted"]
        [objection] = by_origin["rule"]
        assert payment.kind == "payment" and payment.due_date == "2026-10-05"
        assert objection.title.startswith("Pay or object") and objection.due_date == "2026-10-05"


@pytest.mark.parametrize(
    ("letter", "due", "confidence", "check"),
    [
        (ON_TIME_NOTICE, "2027-01-31", "high", False),  # the end is written in the notice's sentence
        (END_IN_HEADING, "2027-01-31", "medium", False),  # only in the heading: worth a second look
        (MISREAD_END, "2027-03-31", "low", True),  # the letter says 31.03.2027: "Please check"
    ],
    ids=["stated", "elsewhere", "misread"],
)
async def test_the_objection_to_a_notice_is_only_as_sure_as_the_end_date_it_counts_from(
    data_dir: Path, letter: Letter, due: str, confidence: str, check: bool
) -> None:
    """§ 574b Abs. 2 BGB counts back from the end the model read; nothing else in the letter states the
    objection date, so the end date is checked against the letter like an item's date (SPEC § 21)."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, letter)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "landlord_notice"
        [objection] = _by_origin(api, doc_id)["rule"]
        assert objection.computation is not None
        assert objection.due_date == due and objection.computation.confidence == confidence
        assert needs_check(objection) is check
        assert (detail["document"]["status"] == "needs_review") is check
        if check:
            assert any("isn't written in the letter" in w for w in objection.computation.warnings)
            [evidence] = objection.evidence
            assert "31.03.2027" in evidence.quote and not evidence.value_consistent
            # confirming the date (or setting it by hand) settles it, as for any "Please check"
            response = await api.client.post(f"/api/items/{objection.id}/confirm")
            assert response.status_code == 200
            doc = (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]
            assert doc["status"] == "processed"


async def test_an_operating_cost_statement_keeps_its_kind_and_gets_its_card_on_read(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, STATEMENT)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "utility_bill"
        assert detail["items"] == []
        advice = detail["advice"]
        assert advice["kind"] == "operating_costs" and not advice["urgent"]
        assert advice["facts"][0]["title"] == "Probably on time"


async def test_a_late_statements_back_payment_says_it_may_not_be_owed(data_dir: Path) -> None:
    """Review round 4: the card says the statement came too late; its "Pay" to-do says so too (and the
    card comes first), but stays open — the landlord may not be responsible for the delay (ADR 0006)."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, LATE_STATEMENT)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        advice = detail["advice"]
        assert advice["kind"] == "operating_costs" and advice["urgent"]
        assert advice["facts"][0]["title"] == "This statement came too late"
        assert advice["steps"][0].startswith("Don't pay a back-payment before")
        [payment] = detail["items"]
        assert payment["status"] == "open" and payment["due_date"] == "2026-09-30"
        assert LATE_STATEMENT_WARNING in payment["computation"]["warnings"]
        assert "bgb_556_3" in payment["computation"]["rule_ids"]
        # a recompute (the arrival day entered) keeps the warning, once
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-12"})
        item = api.ctx.store.get_item(payment["id"])
        assert item is not None and item.computation is not None
        assert item.computation.warnings.count(LATE_STATEMENT_WARNING) == 1
        assert item.computation.rule_ids.count("bgb_556_3") == 1


def test_only_a_statement_the_card_calls_late_warns_its_payments() -> None:
    text = "Betriebskostenabrechnung\nAbrechnungszeitraum: 01.01.2025 - 31.12.2025"
    on_time = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 10))
    assert late_statement_warning(True, "Operating-cost statement", text, on_time) is None
    late = RuleContext(today=date(2027, 1, 20), document_date=date(2027, 1, 15))
    assert late_statement_warning(True, "Operating-cost statement", text, late) == LATE_STATEMENT_WARNING
    assert late_statement_warning(False, "Operating-cost statement", text, late) is None  # not a statement
    # an arrival the person entered counts, like on the card
    entered = RuleContext(
        today=date(2027, 1, 20),
        document_date=date(2026, 12, 20),
        received_date=date(2027, 1, 5),
        received_confirmed=True,
    )
    assert late_statement_warning(True, None, text, entered) == LATE_STATEMENT_WARNING
    assert late_statement_warning(True, None, text, replace(entered, received_confirmed=False)) is None
    # final review 2: an earlier date of another year's statement doesn't replace the arrival entered
    last_years = f"{text}\nDas Guthaben aus der Abrechnung 2024 vom 10.11.2025 wurde erstattet."
    assert late_statement_warning(True, None, last_years, entered) == LATE_STATEMENT_WARNING
    # final review 3: a date without its year may be the statement a later letter is about (a reply that
    # repeats the period) or an enclosure's: ambiguous, so the back-payment is never warned about when that
    # date would make the statement on time — the card says both readings
    enclosing = f"{text}\nAnlage: Heizkostenabrechnung der Techem vom 20.03.2026"
    assert late_statement_warning(True, None, enclosing, entered) is None
    reply = f"{text}\nzu Ihren Einwendungen gegen unsere Abrechnung vom 20.11.2026 nehmen wir Stellung."
    assert late_statement_warning(True, None, reply, entered) is None
    assert is_statement("operating_costs", None) and not is_statement("dismissal", _reading(STATEMENT))
    assert is_statement("utility_bill", _reading(STATEMENT)) and not is_statement("utility_bill", None)


# ------------------------------------------------------------------------------------ corrections


def _reading(letter: Letter, **update: Any) -> DocumentExtraction:
    payload = copy.deepcopy(letter.payload)
    payload.update(update)
    return DocumentExtraction.model_validate(payload)


def test_the_filed_kind_is_the_persons_correction_else_the_kind_code_reads() -> None:
    reading = _reading(MAHNBESCHEID)
    assert filed_kind(reading, {}) == "court_payment_order"
    assert filed_kind(reading, {"kind": "dunning"}) == "dunning"
    # a high-stakes correction stays out of the reading (which keeps the model's vocabulary)
    assert with_corrections(reading, {"kind": "enforcement_order"}).kind == "authority_letter"
    assert with_corrections(reading, {"kind": "dunning"}).kind == "dunning"
    assert with_corrections(reading, {}) is reading


def test_a_kind_the_person_chose_is_a_correction() -> None:
    from ordnung.models import Document

    reading = _reading(MAHNBESCHEID)
    base = {
        "id": "doc_x",
        "sha256": "x",
        "filename": "x.pdf",
        "mime": "application/pdf",
        "created_at": "",
        "updated_at": "",
    }
    filed = Document(
        **base, kind="court_payment_order", title=reading.title, area="money", doc_date="2026-09-21"
    )
    assert corrections(filed, reading) == {}
    # the person's choice wins, even when it is the model's own kind
    for chosen in ("dunning", "authority_letter"):
        kind_set = filed.model_copy(update={"kind": chosen})
        assert corrections(kind_set, reading, chosen_kind=chosen) == {"kind": chosen}
    # a kind that is neither Ordnung's nor the model's was set by the person (an older API call)
    assert corrections(filed.model_copy(update={"kind": "dunning"}), reading) == {"kind": "dunning"}
    # the model's own kind, filed by an older Ordnung, is no correction: reading again reclassifies
    old = filed.model_copy(update={"kind": "authority_letter"})
    assert corrections(old, reading) == {}
    assert corrections(old, reading, chosen_kind="dismissal") == {}  # an earlier choice, since changed
    # a high-stakes kind an older Ordnung filed, which the policy no longer gives the reading, isn't the
    # person's: reading again files the reading's kind (unless the person chose it)
    dunning = reading.model_copy(update={"kind": "dunning", "sender": None, "remedy": None})
    assert corrections(filed, dunning) == {}
    assert corrections(filed, dunning, chosen_kind="court_payment_order") == {"kind": "court_payment_order"}


# ------------------------------------------------------------------------------------ final review 1


async def test_a_reminder_about_an_old_statement_is_no_late_statement(data_dir: Path) -> None:
    """Final review 1: a landlord's payment reminder dated 20 Sep 2026 names its 2023 statement of 15 Nov 2024.
    It stays a reminder: no statement card, and its back-payment is never "may not be owed". Filed as a
    statement by the person, the card counts from the statement's own date — on time."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, REMINDER)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "dunning" and detail["advice"] is None
        [payment] = detail["items"]
        assert LATE_STATEMENT_WARNING not in payment["computation"]["warnings"]
        assert "bgb_556_3" not in payment["computation"]["rule_ids"]

        await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "operating_costs"})
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-22"})
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        advice = detail["advice"]
        assert advice["kind"] == "operating_costs" and not advice["urgent"]
        assert advice["facts"][0]["title"] == "Probably on time"
        [payment] = detail["items"]
        assert LATE_STATEMENT_WARNING not in payment["computation"]["warnings"]


async def test_only_the_back_payment_of_a_late_statement_may_not_be_owed(data_dir: Path) -> None:
    """Final review 1: the credit comes back to the person and the new monthly prepayment is owed: neither
    carries the late-statement warning; the one-off back-payment does."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, LATE_MIXED)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["advice"]["kind"] == "operating_costs" and detail["advice"]["urgent"]
        by_title = {item["title"]: item["computation"] for item in detail["items"]}
        assert LATE_STATEMENT_WARNING in by_title["Pay the back-payment"]["warnings"]
        for title in ("Credit from the heating statement", "New monthly prepayment"):
            assert LATE_STATEMENT_WARNING not in by_title[title]["warnings"]
            assert "bgb_556_3" not in by_title[title]["rule_ids"]
        # a recompute keeps it that way
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-12"})
        for item in api.ctx.store.list_items(doc_id=doc_id):
            assert item.computation is not None
            warned = LATE_STATEMENT_WARNING in item.computation.warnings
            assert warned is (item.title == "Pay the back-payment")


async def test_a_rent_increases_new_rent_is_only_owed_once_agreed(data_dir: Path) -> None:
    """Final review 1: the model reads the new total as a recurring payment; its to-do says the higher rent
    is only owed after consent (§ 558b Abs. 1 BGB), next to the law's decision to-do."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, RENT_INCREASE)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "rent_increase"
        by_origin = _by_origin(api, doc_id)
        [payment] = by_origin["extracted"]
        assert payment.computation is not None
        assert RENT_INCREASE_PAYMENT_WARNING in payment.computation.warnings
        assert "bgb_558b" in payment.computation.rule_ids
        [decision] = by_origin["rule"]
        assert decision.title.startswith("Decide whether to agree")
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-25"})
        after = api.ctx.store.get_item(payment.id)
        assert after is not None and after.computation is not None
        assert after.computation.warnings.count(RENT_INCREASE_PAYMENT_WARNING) == 1


async def test_a_rent_increases_new_rent_is_never_due_before_the_law_allows(data_dir: Path) -> None:
    """Review round 1: "ab dem 01.11.2026" in a request of 24 Sep: by law the higher rent can only be owed from
    1 Dec (§ 558b Abs. 1 BGB) — and from 1 Jan once the person says it arrived on 2 Oct."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, RENT_INCREASE_EARLY)
        [payment] = _by_origin(api, doc_id)["extracted"]
        assert payment.due_date == "2026-12-01" and payment.computation is not None
        assert payment.computation.confidence != "high"
        assert any("The letter names Sun 1 Nov 2026" in w for w in payment.computation.warnings)
        assert RENT_INCREASE_PAYMENT_WARNING in payment.computation.warnings
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-10-02"})
        after = api.ctx.store.get_item(payment.id)
        assert after is not None and after.due_date == "2027-01-01"
        [decision] = _by_origin(api, doc_id)["rule"]
        assert decision.due_date == "2026-12-31"


async def test_a_notice_whose_objection_date_had_passed_is_urgent_and_says_why(data_dir: Path) -> None:
    """Final review 1: "fristgerecht zum 31.10.2026" in a letter of 24 Sep 2026 — the objection date had
    passed before it was written. Review round 1: a notice this short usually ends the tenancy at the next
    permissible date (31 Dec 2026 at the earliest, § 573c Abs. 1 BGB), so the objection may still be open:
    a low-confidence to-do counts back from it (31 Oct), and the card says both readings, urgently."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, SHORT_NOTICE)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "landlord_notice"
        [objection] = detail["items"]
        assert objection["origin"] == "rule" and objection["due_date"] == "2026-10-31"
        assert objection["computation"]["confidence"] == "low"
        assert "bgb_573c_landlord" in objection["computation"]["rule_ids"]
        advice = detail["advice"]
        assert advice["urgent"]
        assert advice["steps"][0].startswith("Your tenancy would end less than two months after this letter")
        assert "If that end is right" in advice["steps"][0] and "may still be open" in advice["steps"][0]
        # the person confirms the arrival: a notice received by the third working day ends a month earlier
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-10-02"})
        after = api.ctx.store.get_item(objection["id"])
        assert after is not None and after.due_date == "2026-10-31" and after.computation is not None
        assert after.computation.confidence == "medium"
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-10-06"})
        later = api.ctx.store.get_item(objection["id"])
        assert later is not None and later.due_date == "2026-11-30"


async def test_a_notice_without_period_given_hilfsweise_without_an_end_gets_an_objection_date(
    data_dir: Path,
) -> None:
    """Review round 1: "fristlos, hilfsweise fristgerecht zum nächstmöglichen Termin" read with the immediate
    end (or none): no objection to-do at all, and the card only said "object in time anyway". The objection
    to the notice given in the alternative counts back from the earliest end it can have (31 Dec: 31 Oct)."""
    async with api_for(data_dir, router=_router()) as api:
        for letter in (HILFSWEISE_NEXT, HILFSWEISE_NO_END):
            doc_id = await _read(api, letter)
            detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
            assert detail["document"]["kind"] == "landlord_notice"
            [objection] = detail["items"]
            assert objection["due_date"] == "2026-10-31" and objection["computation"]["confidence"] == "low"
            advice = detail["advice"]
            assert advice["urgent"] and advice["draft"] == "objection"
            assert "names no end of its own" in advice["facts"][0]["text"]


async def test_the_letters_own_objection_date_carries_the_notice(data_dir: Path) -> None:
    """Final review 1: the reading missed the end, but read the letter's own objection date: that to-do
    carries the notice, so the card neither claims there is none nor is urgent."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, OBJECTION_DATE_ONLY)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "landlord_notice"
        [objection] = detail["items"]
        assert objection["due_date"] == "2027-01-31" and "bgb_574b" in objection["computation"]["rule_ids"]
        advice = detail["advice"]
        assert not advice["urgent"]
        assert not any("there is no to-do" in step for step in advice["steps"])
        # once the person marks it done, it is still the objection's to-do: the card stays calm
        await api.client.patch(f"/api/items/{objection['id']}", json={"status": "done"})
        assert not (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]["urgent"]


@pytest.mark.parametrize("letter", [MAHNBESCHEID, DISMISSAL], ids=["mahnbescheid", "dismissal"])
async def test_a_card_settles_once_the_person_closed_every_to_do(data_dir: Path, letter: Letter) -> None:
    """Final review 1: after the person objected (or went to court and registered) and marked the to-dos
    done, the card is no longer urgent; it comes back when a to-do is reopened."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, letter)
        items = api.ctx.store.list_items(doc_id=doc_id)
        assert items and (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]["urgent"]
        for item in items:
            response = await api.client.patch(f"/api/items/{item.id}", json={"status": "done"})
            assert response.status_code == 200
        settled = (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]
        assert not settled["urgent"] and settled["handled"]
        # final review 2: it doesn't ask for the delivery day any more
        assert not any(
            step.startswith(("Find the delivery date", "Enter the day")) for step in settled["steps"]
        )
        await api.client.patch(f"/api/items/{items[0].id}", json={"status": "open"})
        reopened = (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]
        assert reopened["urgent"] and not reopened["handled"]


async def test_paying_the_arrears_doesnt_settle_a_notice_without_notice_period(data_dir: Path) -> None:
    """Final review 2: the arrears a notice without notice period demands are no to-do that carries the
    notice: paying them (§ 569 Abs. 3 Nr. 2 BGB can undo it, but not always) never files the letter away —
    its card stays urgent and the verdict keeps saying "get advice now"."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, FRISTLOS_ARREARS)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "landlord_notice" and detail["advice"]["urgent"]
        [arrears] = detail["items"]
        assert arrears["kind"] == "payment" and arrears["origin"] == "extracted"
        response = await api.client.patch(f"/api/items/{arrears['id']}", json={"status": "done"})
        assert response.status_code == 200
        advice = (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]
        assert advice["urgent"] and not advice["handled"]
        assert advice["facts"][0]["title"].startswith("This reads as a notice without notice period")
        # final review 3: only the person can close it ("I've dealt with this" on the card: a tag), and undo it
        assert advice["closable"]
        response = await api.client.patch(
            f"/api/documents/{doc_id}", json={"tags": [documents.DEALT_WITH_TAG]}
        )
        assert response.status_code == 200
        dealt = (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]
        assert dealt["handled"] and not dealt["urgent"] and dealt["closable"]
        await api.client.patch(f"/api/documents/{doc_id}", json={"tags": []})
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]["urgent"]


async def test_another_to_do_of_a_dismissal_doesnt_settle_it(data_dir: Path) -> None:
    """Final review 2: only the to-dos that carry the letter's legal deadline settle it: closing another one
    (returning the keys) doesn't, closing those does even while the other stays open."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, DISMISSAL)
        other = api.ctx.store.add_item(
            kind="task", title="Return the keys", doc_id=doc_id, origin="manual", status="done"
        )
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]["urgent"]
        api.ctx.store.update_item(other.id, status="open")
        for item in _by_origin(api, doc_id)["rule"]:
            await api.client.patch(f"/api/items/{item.id}", json={"status": "done"})
        advice = (await api.client.get(f"/api/documents/{doc_id}")).json()["advice"]
        assert advice["handled"] and not advice["urgent"]


async def test_any_court_letter_asks_for_the_delivery_date(data_dir: Path) -> None:
    """Final review 1: a court's letter that isn't an order runs from delivery too: its receipt cites
    § 180 ZPO, so the page asks "when was it delivered?" with no date filled in."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, COURT_REQUEST)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "authority_letter"
        [request] = detail["items"]
        assert "zpo_180" in request["computation"]["rule_ids"]
        assert request["computation"]["confidence"] == "low"


@pytest.mark.parametrize("field", ["doc_date", "received_date"])
async def test_a_statement_dated_9999_is_saved_not_an_error(data_dir: Path, field: str) -> None:
    """Review round 1: filing a letter as an operating-cost statement with a date of 31 Dec 9999 made PATCH
    answer 500 (the statement's twelve months ran past the calendar)."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, LATE_STATEMENT)
        response = await api.client.patch(
            f"/api/documents/{doc_id}", json={"kind": "operating_costs", field: "9999-12-31"}
        )
        assert response.status_code == 200
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["advice"]["kind"] == "operating_costs"


async def test_ask_never_presents_a_rent_increases_new_rent_as_just_another_payment(data_dir: Path) -> None:
    """Review round 1: the new rent is only owed once the person agrees (§ 558b Abs. 1 BGB). Ask's
    money_summary listed it under upcoming_payments like any payment, counted it in due_this_month, and the
    check passed "Your next payment is the new rent …" as checked with no word of that. Now its record carries
    the app's note, money_summary lists it apart and leaves it out of the totals, and the check repeats the
    note under an answer that cites it."""
    from ordnung.assistant.ask import check_turn
    from ordnung.assistant.mcp_server import DECIDE_BEFORE_PAYING, LedgerTools, render_result

    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, RENT_INCREASE)
        [payment] = _by_origin(api, doc_id)["extracted"]
        tools = LedgerTools(api.ctx.store, today=date(2026, 12, 1))
        summary = tools.money_summary()
        record = summary.record
        assert all(row["id"] != payment.id for row in record["upcoming_payments"])
        [decide] = record[DECIDE_BEFORE_PAYING]
        assert decide["id"] == payment.id and decide["payment_note"] == RENT_INCREASE_PAYMENT_WARNING
        assert record["due_this_month"] == 0
        items = tools.list_items().record["items"]
        assert (
            next(row for row in items if row["id"] == payment.id)["payment_note"]
            == RENT_INCREASE_PAYMENT_WARNING
        )
        result = render_result(summary)
        answer = f"Your next payment is the new rent of 670.00 € on Tue 1 Dec 2026 [item:{payment.id}]."
        checked = check_turn(
            api.ctx.store, answer, [result], question="What do I have to pay next?", today=date(2026, 12, 1)
        )
        assert checked.body.startswith("Your next payment is the new rent of 670.00 €")  # the values hold
        assert checked.note is not None and "only owed once you agree to the increase" in checked.note
        assert "§ 558b Abs. 1 BGB" in checked.note
        german = check_turn(
            api.ctx.store,
            f"Ihre nächste Zahlung ist die neue Miete von 670,00 € am 01.12.2026 [item:{payment.id}].",
            [result],
            question="Was muss ich als Nächstes zahlen?",
            today=date(2026, 12, 1),
        )
        assert german.note is not None and "erst geschuldet, wenn Sie der Erhöhung zustimmen" in german.note
        # an answer about something else says nothing about it
        other = check_turn(
            api.ctx.store,
            "Nothing else is due.",
            [result],
            question="Anything else?",
            today=date(2026, 12, 1),
        )
        assert other.note is None


async def test_only_the_new_rent_carries_the_note_dated_or_not(data_dir: Path) -> None:
    """Review round 2 of phase 2: the current rent got the "decide before you pay" note (holding it back
    risks arrears, § 543 Abs. 2 Nr. 3 BGB), and an undated new rent got none, so Ask listed it as an ordinary
    payment without a due date."""
    from ordnung.assistant.mcp_server import DECIDE_BEFORE_PAYING, LedgerTools

    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, RENT_INCREASE_CURRENT)
        payments = {item.title: item for item in _by_origin(api, doc_id)["extracted"]}
        current, new = payments["Rent for October"], payments["New monthly rent"]
        assert current.computation is not None
        assert RENT_INCREASE_PAYMENT_WARNING not in current.computation.warnings
        assert new.due_date is None and new.computation is not None
        assert new.computation.warnings == [RENT_INCREASE_PAYMENT_WARNING]
        assert "bgb_558b" in new.computation.rule_ids
        record = LedgerTools(api.ctx.store, today=date(2026, 9, 26)).money_summary().record
        assert [row["id"] for row in record[DECIDE_BEFORE_PAYING]] == [new.id]
        assert all(row["id"] != new.id for row in record["payments_without_due_date"])
        # the current rent is owed on its own day, never re-dated to the new rent's (§ 558b Abs. 1 BGB)
        assert current.due_date == "2026-10-01" and "bgb_558b" not in current.computation.rule_ids
        assert any(row["id"] == current.id for row in record["upcoming_payments"])


async def test_a_hand_set_date_keeps_the_new_rents_note(data_dir: Path) -> None:
    """Review round 2 of phase 2: setting the new rent's due date by hand replaced its receipt, so Ask
    counted the not-yet-agreed rent as due this month, without the note."""
    from ordnung.assistant.mcp_server import DECIDE_BEFORE_PAYING, LedgerTools

    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, RENT_INCREASE)
        [payment] = _by_origin(api, doc_id)["extracted"]
        response = await api.client.patch(f"/api/items/{payment.id}", json={"due_date": "2026-10-05"})
        assert response.status_code == 200
        after = api.ctx.store.get_item(payment.id)
        assert after is not None and after.due_date_source == "manual" and after.computation is not None
        assert RENT_INCREASE_PAYMENT_WARNING in after.computation.warnings
        record = LedgerTools(api.ctx.store, today=date(2026, 10, 1)).money_summary().record
        assert record["due_this_month"] == 0
        assert [row["id"] for row in record[DECIDE_BEFORE_PAYING]] == [payment.id]
        # clearing the date keeps it too
        await api.client.patch(f"/api/items/{payment.id}", json={"due_date": None})
        cleared = api.ctx.store.get_item(payment.id)
        assert cleared is not None and cleared.computation is not None
        assert cleared.computation.warnings == [RENT_INCREASE_PAYMENT_WARNING]


async def test_a_late_statements_back_payment_is_listed_apart_with_its_note(data_dir: Path) -> None:
    from ordnung.assistant.mcp_server import DECIDE_BEFORE_PAYING, LedgerTools

    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, LATE_STATEMENT)
        [payment] = _by_origin(api, doc_id)["extracted"]
        record = LedgerTools(api.ctx.store, today=date(2026, 9, 25)).money_summary().record
        [decide] = record[DECIDE_BEFORE_PAYING]
        assert decide["id"] == payment.id and decide["payment_note"] == LATE_STATEMENT_WARNING
        assert all(row["id"] != payment.id for row in record["upcoming_payments"])
        assert record["due_this_month"] == 0
