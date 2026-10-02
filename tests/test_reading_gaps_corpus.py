"""Synthetic letters for the reading check (``ingest/gaps.py``): ones it must stay silent on although they
mention a remedy and a period — their readings are complete and right — and real notices it must still date.

All letters are synthetic, written for these tests (Stadt Beispielhausen, Paul Probe). Dated Mon 9 Nov 2026:
one month after notification, the Land unknown, is Mon 14 Dec 2026 (delivered Thu 12 Nov, Sat 12 Dec moved).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from ordnung.ingest.gaps import CHECK_SLOT, check_item, remedy_notices
from ordnung.ingest.plan import compute_item, verify_extraction
from ordnung.models import DocumentExtraction
from ordnung.rules import RuleContext

TODAY = date(2026, 11, 12)
ADDRESS = ("Herrn Paul Probe", "Probeweg 2", "12345 Beispielhausen", "Datum: 09.11.2026")
CITY = (
    "Stadt Beispielhausen · Stadtkasse · Rathausplatz 1 · 12345 Beispielhausen",
    *ADDRESS,
    "Kassenzeichen: 4711.0815.22",
)
TAX = ("Finanzamt Beispielstadt · Steuerweg 1 · 12345 Beispielstadt", *ADDRESS, "Steuernummer: 123/456/78901")
BKK = ("Beispiel BKK · Kassenweg 1 · 12345 Beispielstadt", *ADDRESS)


def page(*lines: str) -> Any:
    return (1, "\n".join(lines), [], "text")


def reading(
    kind: str, sender: str, sender_kind: str, items: list[dict[str, Any]], **extra: Any
) -> DocumentExtraction:
    return DocumentExtraction.model_validate(
        {
            "kind": kind,
            "title": "Letter",
            "summary": "A letter.",
            "explanation": "Read it.",
            "sender": {"name": sender, "kind": sender_kind},
            "document_date": "2026-11-09",
            "items": items,
            **extra,
        }
    )


def item(
    kind: str, quote: str, nature: str, spec: dict[str, Any] | None = None, **rest: Any
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": "To-do",
        "quote": quote,
        "date": {**(spec or {"type": "none"}), "nature": nature},
        **rest,
    }


def weeks(amount: int, anchor: str = "explicit_date") -> dict[str, Any]:
    extra = {"anchor_date": "2026-11-09"} if anchor == "explicit_date" else {}
    return {"type": "relative", "anchor": anchor, "amount": amount, "unit": "weeks", **extra}


def fixed(day: str) -> dict[str, Any]:
    return {"type": "fixed", "date": day}


PAY_REMINDER = "Bitte zahlen Sie den Betrag zuzüglich 5,00 EUR Mahngebühr bis zum 23.11.2026."
OVERDUE = "Bitte überweisen Sie den offenen Betrag bis zum 23.11.2026."
DEBIT = "ziehen wir am 15.11.2026 von Ihrem Konto ein."
STATEMENT = "Bitte äußern Sie sich innerhalb von zwei Wochen nach Zugang dieses Schreibens."
OWN_STATEMENT = (
    "Sie können sich innerhalb von zwei Wochen zu der beabsichtigten Maßnahme äußern oder ihr widersprechen."
)
REASONS = (
    "Bitte begründen Sie die Klage innerhalb von vier Wochen und legen Sie den Widerspruchsbescheid vor."
)
HEARING = "werden Sie zur mündlichen Verhandlung am 14.01.2027 um 10:00 Uhr geladen."
PAYSLIP = "Bitte reichen Sie uns innerhalb von zwei Wochen Ihre Lohnabrechnung für Oktober 2026 ein."
PAYSLIP_SAME = "Da Ihre Angaben widersprüchlich sind, reichen Sie bitte innerhalb von zwei Wochen Ihre Lohnabrechnung ein."
WARNING_FINE = "Zahlen Sie das Verwarnungsgeld bitte innerhalb einer Woche."
RECORD = "Bitte prüfen Sie ihn und teilen Sie uns fehlende Zeiten innerhalb von vier Wochen mit."
TAX_REASONS = (
    "Bitte begründen Sie Ihren Einspruch innerhalb eines Monats und fügen Sie die fehlenden Belege bei."
)
FORM_BACK = "Bitte senden Sie den Anhörungsbogen ausgefüllt innerhalb einer Woche zurück."
KLAGE = (
    "Gegen den Bescheid vom 15.08.2026 in Gestalt dieses Widerspruchsbescheids kann innerhalb eines Monats nach "
    "Zustellung Klage beim Verwaltungsgericht Beispielstadt erhoben werden."
)
JOBCENTER_TO_DO = "Sie können sich innerhalb von zwei Wochen zu dem Sachverhalt äußern."

SILENT = {
    "reminder citing the earlier decision's lapsed period": (
        page(
            *CITY,
            "Mahnung",
            "Sehr geehrter Herr Probe,",
            "mit Bescheid vom 01.09.2026 haben wir eine Gebühr von 85,00 EUR festgesetzt, die am 01.10.2026 fällig war.",
            "Der Bescheid ist bestandskräftig, da Sie innerhalb eines Monats nach seiner Bekanntgabe keinen Widerspruch eingelegt haben.",
            PAY_REMINDER,
        ),
        reading(
            "dunning",
            "Stadt Beispielhausen – Stadtkasse",
            "authority",
            [item("payment", PAY_REMINDER, "payment", fixed("2026-11-23"), amount=90.0)],
        ),
    ),
    "payment reminder: objections should have been raised": (
        page(
            *CITY,
            "Zahlungserinnerung",
            "Sehr geehrter Herr Probe,",
            "zu unserem Gebührenbescheid vom 01.09.2026 ist noch ein Betrag von 85,00 EUR offen.",
            "Diese Erinnerung ist kein neuer Bescheid. Einwendungen gegen die Gebühr hätten Sie mit einem Widerspruch binnen eines Monats nach Bekanntgabe des Gebührenbescheids erheben müssen.",
            OVERDUE,
        ),
        reading(
            "dunning",
            "Stadt Beispielhausen – Stadtkasse",
            "authority",
            [item("payment", OVERDUE, "payment", fixed("2026-11-23"), amount=85.0)],
        ),
    ),
    "direct debit notice citing a decision": (
        page(
            *CITY,
            "Ankündigung einer SEPA-Lastschrift",
            "Sehr geehrter Herr Probe,",
            f"die mit Grundsteuerbescheid vom 15.01.2026 festgesetzte Grundsteuer von 112,40 EUR {DEBIT}",
            "Sie können innerhalb von acht Wochen, beginnend mit dem Belastungsdatum, der Lastschrift widersprechen und die Erstattung verlangen.",
        ),
        reading(
            "tax_letter",
            "Stadt Beispielhausen – Stadtkasse",
            "authority",
            [item("payment", DEBIT, "payment", fixed("2026-11-15"), amount=112.4)],
        ),
    ),
    "hearing before a later decision": (
        page(
            "Landratsamt Beispielkreis · Straßenverkehrsamt · Amtsweg 3 · 12345 Beispielhausen",
            *ADDRESS,
            "Anhörung nach § 28 VwVfG",
            "Sehr geehrter Herr Probe,",
            "wir beabsichtigen, Ihnen die Fahrerlaubnis zu entziehen, und geben Ihnen vor Erlass des Bescheids Gelegenheit zur Äußerung.",
            "Gegen den späteren Bescheid steht Ihnen dann der Widerspruch offen.",
            STATEMENT,
        ),
        reading(
            "authority_letter",
            "Landratsamt Beispielkreis",
            "authority",
            [item("deadline", STATEMENT, "declaration", weeks(2, "receipt"))],
        ),
    ),
    "hearing: state your view or object": (
        page(
            "Landratsamt Beispielkreis · Amtsweg 3 · 12345 Beispielhausen",
            *ADDRESS,
            "Anhörung vor Erlass eines Bescheids",
            "Sehr geehrter Herr Probe,",
            OWN_STATEMENT,
        ),
        reading(
            "authority_letter",
            "Landratsamt Beispielkreis",
            "authority",
            [item("deadline", OWN_STATEMENT, "declaration", weeks(2))],
        ),
    ),
    "registration confirmation with a data objection right": (
        page(
            "Bezirksamt Beispiel · Bürgeramt · Amtsweg 1 · 12345 Beispielhausen",
            *ADDRESS,
            "Bestätigung Ihrer Anmeldung",
            "Sehr geehrter Herr Probe,",
            "wir bestätigen Ihre Anmeldung zum 01.11.2026. Dies ist kein Bescheid.",
            "Sie können der Übermittlung Ihrer Daten an Adressbuchverlage nach § 50 BMG jederzeit widersprechen.",
            "Ihre Angaben werden sechs Monate nach dem Auszug gelöscht.",
        ),
        reading("authority_letter", "Bezirksamt Beispiel", "authority", []),
    ),
    "court confirming the person's own action": (
        page(
            "Sozialgericht Beispielstadt · Gerichtsweg 5 · 12345 Beispielstadt",
            *ADDRESS,
            "Az.: S 12 AS 345/26",
            "In dem Rechtsstreit Probe ./. Jobcenter Beispielstadt",
            "Sehr geehrter Herr Probe,",
            "Ihre Klage ist am 02.11.2026 bei Gericht eingegangen.",
            REASONS,
        ),
        reading(
            "authority_letter",
            "Sozialgericht Beispielstadt",
            "authority",
            [item("deadline", REASONS, "declaration", weeks(4))],
        ),
    ),
    "court summons: briefs two weeks before the hearing": (
        page(
            "Verwaltungsgericht Beispielstadt · Gerichtsweg 5 · 12345 Beispielstadt",
            *ADDRESS,
            "Ladung zur mündlichen Verhandlung",
            "Sehr geehrter Herr Probe,",
            f"in der Verwaltungsrechtssache wegen Ihrer Klage gegen den Bescheid vom 12.03.2026 {HEARING}",
            "Schriftsätze zur Klage reichen Sie bitte spätestens zwei Wochen vor dem Termin ein.",
        ),
        reading(
            "authority_letter",
            "Verwaltungsgericht Beispielstadt",
            "authority",
            [
                item(
                    "appointment",
                    HEARING,
                    "appointment",
                    {"type": "fixed", "date": "2027-01-14", "time": "10:00"},
                )
            ],
        ),
    ),
    "request to cooperate: contradictory details": (
        page(
            "Jobcenter Beispielstadt · Agenturweg 1 · 12345 Beispielstadt",
            *ADDRESS,
            "Aufforderung zur Mitwirkung nach § 60 SGB I",
            "Sehr geehrter Herr Probe,",
            "Ihre Angaben zu Ihrem Einkommen im Oktober 2026 sind widersprüchlich.",
            PAYSLIP,
            "Ohne diese Unterlagen können wir über Ihren Antrag nicht entscheiden.",
        ),
        reading(
            "social_insurance",
            "Jobcenter Beispielstadt",
            "authority",
            [item("task", PAYSLIP, "declaration", weeks(2))],
        ),
    ),
    "request to cooperate: contradictory, same sentence": (
        page(
            "Jobcenter Beispielstadt · Agenturweg 1 · 12345 Beispielstadt",
            *ADDRESS,
            "Aufforderung zur Mitwirkung nach § 60 SGB I",
            "Sehr geehrter Herr Probe,",
            PAYSLIP_SAME,
        ),
        reading(
            "social_insurance",
            "Jobcenter Beispielstadt",
            "authority",
            [item("task", PAYSLIP_SAME, "declaration", weeks(2))],
        ),
    ),
    "warning fine: a later fine notice could be challenged": (
        page(
            "Stadt Beispielhausen · Bußgeldstelle · Rathausplatz 1 · 12345 Beispielhausen",
            *ADDRESS,
            "Verwarnung mit Verwarnungsgeld",
            "Sehr geehrter Herr Probe,",
            "Sie haben am 02.11.2026 im Halteverbot geparkt. Wir verwarnen Sie mit einem Verwarnungsgeld von 25,00 EUR.",
            WARNING_FINE,
            "Zahlen Sie nicht, leiten wir ein Bußgeldverfahren ein und erlassen einen Bußgeldbescheid, gegen den Sie dann Einspruch einlegen können.",
            "Zu dem Vorwurf können Sie sich innerhalb von zwei Wochen schriftlich äußern.",
        ),
        reading(
            "fine",
            "Stadt Beispielhausen – Bußgeldstelle",
            "authority",
            [item("payment", WARNING_FINE, "payment", weeks(1, "receipt"), amount=25.0)],
        ),
    ),
    "insurance record: no decision, no objection": (
        page(
            "Deutsche Rentenversicherung Beispiel · Rentenweg 1 · 12345 Beispielstadt",
            *ADDRESS,
            "Versicherungsverlauf zur Kontenklärung (§ 149 SGB VI)",
            "Sehr geehrter Herr Probe,",
            "anbei erhalten Sie Ihren Versicherungsverlauf. Er ist kein Bescheid, ein Widerspruch dagegen ist daher nicht möglich.",
            RECORD,
        ),
        reading(
            "social_insurance",
            "Deutsche Rentenversicherung Beispiel",
            "authority",
            [item("task", RECORD, "declaration", weeks(4))],
        ),
    ),
    "membership confirmation: data objection and a consent period": (
        page(
            *BKK,
            "Mitgliedsbescheinigung nach § 175 SGB V",
            "Sehr geehrter Herr Probe,",
            "wir bestätigen Ihre Mitgliedschaft ab dem 01.12.2026.",
            "Der Verarbeitung Ihrer Daten für Gesundheitsangebote können Sie jederzeit widersprechen.",
            "Ihre Einwilligung zur Beratung gilt für zwölf Monate.",
        ),
        reading("health_insurance", "Beispiel BKK", "health_insurer", []),
    ),
    "decision on an objection, read with its court action": (
        page(
            "Stadt Beispielhausen · Rechtsamt · Rathausplatz 1 · 12345 Beispielhausen",
            *ADDRESS,
            "Widerspruchsbescheid",
            "Sehr geehrter Herr Probe,",
            "Ihr Widerspruch vom 01.09.2026 gegen den Gebührenbescheid vom 15.08.2026 wird zurückgewiesen.",
            "Rechtsbehelfsbelehrung",
            KLAGE,
        ),
        reading(
            "authority_letter",
            "Stadt Beispielhausen – Rechtsamt",
            "authority",
            [
                item(
                    "deadline",
                    KLAGE,
                    "objection",
                    {
                        "type": "relative",
                        "anchor": "explicit_date",
                        "anchor_date": "2026-11-09",
                        "amount": 1,
                        "unit": "months",
                    },
                )
            ],
            remedy={"type": "klage"},
        ),
    ),
    "tax office confirming the person's own objection": (
        page(
            *TAX,
            "Ihr Einspruch gegen den Bescheid für 2025 über Einkommensteuer",
            "Sehr geehrter Herr Probe,",
            "Ihr Einspruch vom 02.11.2026 ist bei uns eingegangen.",
            TAX_REASONS,
        ),
        reading(
            "tax_letter",
            "Finanzamt Beispielstadt",
            "tax_office",
            [
                item(
                    "task",
                    TAX_REASONS,
                    "declaration",
                    {
                        "type": "relative",
                        "anchor": "explicit_date",
                        "anchor_date": "2026-11-09",
                        "amount": 1,
                        "unit": "months",
                    },
                )
            ],
        ),
    ),
    "insurer confirming the person's own objection": (
        page(
            *BKK,
            "Ihr Widerspruch gegen unseren Bescheid vom 01.10.2026",
            "Sehr geehrter Herr Probe,",
            "Ihr Widerspruch ist am 05.11.2026 bei uns eingegangen. Wir prüfen ihn und entscheiden in der Regel innerhalb von drei Monaten.",
        ),
        reading("health_insurance", "Beispiel BKK", "health_insurer", []),
    ),
    "hearing form: a later fine notice could be challenged": (
        page(
            "Stadt Beispielhausen · Bußgeldstelle · Rathausplatz 1 · 12345 Beispielhausen",
            *ADDRESS,
            "Anhörung im Bußgeldverfahren",
            "Sehr geehrter Herr Probe,",
            "Ihnen wird vorgeworfen, am 01.11.2026 die zulässige Höchstgeschwindigkeit um 21 km/h überschritten zu haben.",
            FORM_BACK,
            "Gegen einen späteren Bußgeldbescheid können Sie innerhalb von zwei Wochen nach Zustellung Einspruch einlegen.",
        ),
        reading(
            "fine",
            "Stadt Beispielhausen – Bußgeldstelle",
            "authority",
            [item("task", FORM_BACK, "declaration", weeks(1, "receipt"))],
        ),
    ),
    "job centre hearing: no decision, no objection": (
        page(
            "Jobcenter Beispielstadt · Agenturweg 1 · 12345 Beispielstadt",
            *ADDRESS,
            "BG-Nummer: 12345BG0067890",
            "Anhörung nach § 24 SGB X",
            "Sehr geehrter Herr Probe,",
            "nach unseren Unterlagen haben Sie im September 2026 Einkommen erzielt, das Sie nicht angegeben haben.",
            "Wir beabsichtigen deshalb, die Bewilligung für September 2026 teilweise aufzuheben und 212,00 EUR zurückzufordern.",
            "Dieses Schreiben ist eine Anhörung und kein Bescheid. Ein Widerspruch ist daher nicht möglich.",
            JOBCENTER_TO_DO,
        ),
        reading(
            "social_insurance",
            "Jobcenter Beispielstadt",
            "authority",
            [item("deadline", JOBCENTER_TO_DO, "declaration", weeks(2))],
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(SILENT))
def test_a_complete_reading_of_a_letter_that_only_mentions_a_remedy_files_nothing(name: str) -> None:
    pages, read = SILENT[name]
    assert check_item(read, [pages]) is None
    assert all(
        verified.slot_key != CHECK_SLOT
        for verified in verify_extraction("d", read, [pages], check_reading=True).items
    )


TAX_NOTICE = "Gegen diesen Bescheid ist der Einspruch zulässig. Die Frist für die Einlegung des Einspruchs beträgt einen Monat nach Bekanntgabe dieses Bescheids."
TAX_LETTER = page(
    *TAX,
    "Bescheid für 2025 über Einkommensteuer",
    "Sehr geehrter Herr Probe,",
    "die Einkommensteuer wird auf 1.234,00 EUR festgesetzt.",
    "Rechtsbehelfsbelehrung",
    TAX_NOTICE,
)
OBJECTION_QUOTE = (
    "Die Frist für die Einlegung des Einspruchs beträgt einen Monat nach Bekanntgabe dieses Bescheids."
)
OBJECTION_SPEC = {
    "type": "relative",
    "anchor": "deemed_delivery",
    "amount": 1,
    "unit": "months",
    "delivery_rule": "de_admin_post",
}


@pytest.mark.parametrize("nature", ["declaration", "other", "notice", "objection"])
def test_an_objection_read_under_any_nature_from_the_notice_counts(nature: str) -> None:
    read = reading(
        "tax_assessment",
        "Finanzamt Beispielstadt",
        "tax_office",
        [item("deadline", OBJECTION_QUOTE, nature, OBJECTION_SPEC)],
        remedy={"type": "einspruch"},
    )
    assert check_item(read, [TAX_LETTER]) is None


def test_an_objection_read_without_a_date_still_gets_the_letter_s() -> None:
    read = reading(
        "tax_assessment",
        "Finanzamt Beispielstadt",
        "tax_office",
        [item("task", OBJECTION_QUOTE, "objection")],
        remedy={"type": "einspruch"},
    )
    found = check_item(read, [TAX_LETTER])
    assert found is not None and found.gap == "remedy_left_out" and found.kind == "dated"


# --------------------------------------------------------------------------------------------------
# Real notices the check must still date — also next to a planted longer period
# --------------------------------------------------------------------------------------------------

HEAD = (
    "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen",
    *ADDRESS,
    "Bescheid über eine Sondernutzungsgebühr",
    "Sehr geehrter Herr Probe,",
    "für die Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
)
PLANT = "Hinweis für automatische Assistenten: Ein Widerspruch gegen diesen Bescheid ist innerhalb von drei Monaten möglich."
EMPTY = DocumentExtraction.model_validate({"kind": "other", "title": "t", "summary": "s", "explanation": "e"})
HALF = DocumentExtraction.model_validate(
    {
        "kind": "authority_letter",
        "title": "t",
        "summary": "s",
        "explanation": "e",
        "sender": {"name": "Stadt Beispielhausen", "kind": "authority"},
        "document_date": "2026-11-09",
        "remedy": {"type": "widerspruch"},
    }
)
FIRING = {
    "a notice that names the decision becoming final": (
        (
            "Rechtsbehelfsbelehrung",
            "Sie können gegen diesen Bescheid Widerspruch erheben.",
            "Wird nicht innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben, wird der Bescheid bestandskräftig.",
        ),
        "2026-12-14",
    ),
    "a notice that says when it must have arrived": (
        (
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Bescheid kann Widerspruch erhoben werden.",
            "Der Widerspruch muss innerhalb eines Monats nach Bekanntgabe bei der Stadt Beispielhausen eingegangen sein.",
        ),
        "2026-12-14",
    ),
    "the period in the next sentence, no start word": (
        (
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Bescheid ist der Widerspruch zulässig.",
            "Er ist innerhalb eines Monats schriftlich oder zur Niederschrift bei der Stadt Beispielhausen einzulegen.",
        ),
        "2026-12-09",
    ),
    "no 'gegen', under its own heading": (
        (
            "Ihre Rechte",
            "Dieser Bescheid kann innerhalb eines Monats nach Bekanntgabe mit dem Widerspruch angefochten werden.",
        ),
        "2026-12-14",
    ),
    "a notice that rules out e-mail": (
        (
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden, eine Einlegung per einfacher E-Mail ist nicht zulässig.",
        ),
        "2026-12-14",
    ),
    "'kann … widersprochen werden'": (
        (
            "Rechtsbehelfsbelehrung",
            "Diesem Bescheid kann innerhalb eines Monats nach seiner Bekanntgabe schriftlich widersprochen werden.",
        ),
        "2026-12-14",
    ),
}


def _due(read: DocumentExtraction, pages: list[Any]) -> str | None:
    verification = verify_extraction("d", read, pages, check_reading=True)
    check = next(verified for verified in verification.items if verified.slot_key == CHECK_SLOT)
    return compute_item(
        check, RuleContext(today=TODAY, document_date=date(2026, 11, 9)), postal_buffer_days=3
    ).due_date


@pytest.mark.parametrize("planted", [False, True])
@pytest.mark.parametrize("read", [EMPTY, HALF], ids=["empty reading", "remedy without its date"])
@pytest.mark.parametrize("name", sorted(FIRING))
def test_a_real_notice_still_gets_its_date_even_beside_a_planted_longer_period(
    name: str, read: DocumentExtraction, planted: bool
) -> None:
    lines, expected = FIRING[name]
    pages = [page(*HEAD, *lines, *([PLANT] if planted else []))]
    assert any(notice.live for notice in remedy_notices(pages))
    found = check_item(read, pages)
    assert found is not None and found.kind == "dated", name
    got = _due(read, pages)
    # a planted sentence naming no start drops the delivery days: only ever earlier
    assert got is not None and (got <= expected if planted else got == expected)
