"""Authorities and public bodies: health insurer, broadcasting fee, immigration office, library,
parking fine (phone photo) and the income-tax assessment (two phone photos, new-mail tray)."""

from __future__ import annotations

import math
from decimal import Decimal

from samplelife import datecheck as dc
from samplelife import persona as sam
from samplelife.common import SALUTE_DE, as_pdf, as_photos, letter_pdf
from samplelife.fmt import de_num, eur, money
from samplelife.letter import GREY, LEFT, WIDTH, Letter
from samplelife.orgs import (
    ACC_BEITRAGSSERVICE,
    ACC_BKK,
    ACC_STADTKASSE,
    BEITRAGSSERVICE,
    BIBLIOTHEK,
    BKK,
    FINANZAMT,
    STADT_ABH,
    STADT_ORDNUNGSAMT,
)
from samplelife.truth import Amount, Ref, Sample, Truth, TruthChange, TruthItem, TruthPayment, TruthRemedy

# --------------------------------------------------------------------------------------------------
# Muster BKK: Beitragsbescheid (10.09.2026)
# --------------------------------------------------------------------------------------------------

BASE_OLD, BASE_NEW = Decimal("855.00"), Decimal("915.00")
RATES = [
    ("Krankenversicherung (7/10 des allgemeinen Beitragssatzes von 14,6 %, § 245 SGB V)", Decimal("10.22")),
    ("Kassenindividueller Zusatzbeitrag der Muster BKK (§ 242 SGB V)", Decimal("2.69")),
    ("Pflegeversicherung (§ 55 Abs. 1 SGB XI)", Decimal("3.60")),
    ("Beitragszuschlag für Kinderlose (§ 55 Abs. 3 SGB XI)", Decimal("0.60")),
]
BKK_REMEDY_QUOTE = (
    "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
)
BKK_ADDRESSEE_QUOTE = (
    "Der Widerspruch ist schriftlich, in elektronischer Form nach § 36a Abs. 2 SGB I oder zur Niederschrift bei "
    "der Muster BKK, Kassenstraße 3, 12346 Musterstadt, einzulegen."
)
BKK_NEW_QUOTE = "Ab dem 01.10.2026 beträgt Ihr monatlicher Beitrag 156,55 € (bisher 146,29 €)."


def _contributions(base: Decimal) -> list[Decimal]:
    return [money(base * rate / 100) for _label, rate in RATES]


def _bkk(letter: Letter) -> None:
    new = _contributions(BASE_NEW)
    letter.address(sam.recipient())
    letter.info(
        [
            ("Versicherten-Nr.", sam.KVNR),
            ("Unser Zeichen", "BZ-S/2026/0917"),
            ("Ihr Kontakt", "Nadine Beispiel"),
            ("Telefon", "0123 6060-417"),
            ("Datum", "10.09.2026"),
        ]
    )
    letter.subject("Beitragsbescheid – Ihre Beiträge zur Kranken- und Pflegeversicherung ab 01.10.2026")
    letter.para(SALUTE_DE)
    letter.para(
        "Sie sind bei uns als Student nach § 5 Abs. 1 Nr. 9 SGB V kranken- und pflegeversichert. Als "
        "beitragspflichtige Einnahme gilt für Studierende der monatliche Bedarf nach dem "
        "BAföG (§ 236 SGB V); er beträgt ab dem Wintersemester 2026/27 915,00 € (bisher 855,00 €). "
        f"{BKK_NEW_QUOTE}"
    )
    rows = [("Beitragsart", "Satz", "Monatsbeitrag")]
    rows += [
        (label, f"{de_num(rate)} %", eur(value)) for (label, rate), value in zip(RATES, new, strict=True)
    ]
    rows.append(
        ("**Gesamtbeitrag ab 01.10.2026** (Bemessungsgrundlage 915,00 €)", "", f"**{eur(sum(new))}**")
    )
    letter.table(rows, (118, 17, 30), aligns=("LEFT", "RIGHT", "RIGHT"), head_fill=BKK.color, gap=2.5)
    letter.heading("Was ist der Zusatzbeitrag?")
    letter.para(
        "Jede Krankenkasse erhebt zusätzlich zum allgemeinen Beitragssatz einen eigenen Zusatzbeitrag. "
        "Anders als Arbeitnehmer tragen Studierende ihn – wie den gesamten Beitrag – allein. Der "
        "Zusatzbeitragssatz der Muster BKK ist unverändert und liegt mit 2,69 % unter dem Durchschnitt "
        "von 2,9 %. Wir buchen den Beitrag wie bisher zum 15. eines Monats ab, den neuen Betrag erstmals "
        "am 15.10.2026."
    )
    letter.heading("Rechtsbehelfsbelehrung")
    letter.para(f"{BKK_REMEDY_QUOTE} {BKK_ADDRESSEE_QUOTE}")
    letter.small(
        "Hinweis: Widerspruch und Klage haben keine aufschiebende Wirkung (§ 86a Abs. 2 Nr. 1 SGG); die "
        "Beiträge sind daher auch bei einem Widerspruch zunächst in der festgesetzten Höhe zu zahlen."
    )
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Ihre Muster BKK",
        signers=[("Nadine Beispiel", "Beitragsservice")],
        scribble=False,
    )


def bkk_beitragsbescheid() -> Sample:
    """Health-insurance contribution notice for students, Muster BKK, 10.09.2026."""
    new, old = _contributions(BASE_NEW), _contributions(BASE_OLD)
    dc.expect(sum(new) == money("156.55") and sum(old) == money("146.29"), "contribution totals")
    # § 37 Abs. 2 SGB X (posted from 2025): deemed notified on the 4th day after posting.
    # Posted Thu 10.09.2026 (document date, conservative) → Mon 14.09.2026, a business day.
    # Widerspruch within one month (§ 84 Abs. 1 SGG; § 64 SGG, §§ 187, 188 BGB) → Wed 14.10.2026.
    deemed = dc.checked(dc.plus_days("2026-09-10", 4), "Mon")
    dc.expect(dc.is_business_day(deemed), "deemed delivery on a business day")
    due = dc.checked(dc.plus_months(deemed, 1), "Wed")
    truth = Truth(
        kind="health_insurance",
        area="health",
        sender_name="Muster BKK",
        sender_kind="health_insurer",
        document_date="2026-09-10",
        references=[Ref("Versicherten-Nr.", sam.KVNR), Ref("Unser Zeichen", "BZ-S/2026/0917")],
        amounts=[
            Amount("Gesamtbeitrag ab 01.10.2026", float(sum(new))),
            Amount("bisheriger Gesamtbeitrag", float(sum(old))),
        ],
        items=[
            TruthItem(
                kind="deadline",
                title_hint="Last day to object (Widerspruch) to the contribution notice",
                expected_due=due,
                date_basis="relative",
                nature="objection",
                quote=BKK_REMEDY_QUOTE,
                reasoning="Dated Thu 10.09.2026; § 37 Abs. 2 SGB X: deemed notified 4 days after posting = Mon "
                "14.09.2026; + 1 month = Wed 14.10.2026 (business day).",
            ),
            TruthItem(
                kind="payment",
                title_hint="New monthly health insurance contribution",
                expected_due="2026-10-15",
                date_basis="fixed",
                nature="payment",
                recurrence="monthly",
                amount=float(sum(new)),
                direction="out",
                quote="den neuen Betrag erstmals am 15.10.2026",
                reasoning="Direct debit on the 15th; first debit at the new amount on 15.10.2026.",
                optional=True,
            ),
        ],
        change=TruthChange("price_increase", "2026-10-01", float(sum(old)), float(sum(new)), "monthly"),
        remedy=TruthRemedy("widerspruch", "Muster BKK"),
        payment=None,
        key_quotes=[BKK_REMEDY_QUOTE, BKK_ADDRESSEE_QUOTE, BKK_NEW_QUOTE],
        kind_alternatives=["social_insurance"],
        tax_relevant=True,
        notes="Base change only; the Zusatzbeitrag is unchanged, so there is no special cancellation right "
        "(§ 175 Abs. 4 SGB V). Contributions are deductible Vorsorgeaufwendungen. Account: " + ACC_BKK.iban,
    )
    return Sample(
        slug="krankenkasse_beitragsbescheid",
        title="Beitragsbescheid Kranken- und Pflegeversicherung",
        language="de",
        received_date=dc.checked("2026-09-12", "Sat"),
        render=lambda: as_pdf(letter_pdf(BKK, "2026-09-10", _bkk, follow_ref=f"Versicherten-Nr. {sam.KVNR}")),
        truth=truth,
        subject_hint="Beitragsbescheid Krankenkasse",
    )


# --------------------------------------------------------------------------------------------------
# Beitragsservice Musterstadt: Zahlungsaufforderung (15.09.2026)
# --------------------------------------------------------------------------------------------------

BEITRAGSNUMMER = "512 345 678"
RB_DUE_QUOTE = "Der Betrag von 55,08 € für den Zeitraum 10.2026 bis 12.2026 ist fällig am 15.11.2026."


def _rundfunk(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [("Beitragsnummer", BEITRAGSNUMMER), ("Service", BEITRAGSSERVICE.phone), ("Datum", "15.09.2026")],
        label_w=24,
    )
    letter.subject("Zahlungsaufforderung Rundfunkbeitrag", sub=f"Beitragsnummer {BEITRAGSNUMMER}")
    letter.para(SALUTE_DE)
    letter.para(
        "für Ihre Wohnung Beispielweg 5, 12345 Musterstadt, sind Sie unter der oben genannten "
        "Beitragsnummer angemeldet. Der Rundfunkbeitrag ist monatlich geschuldet und jeweils in der Mitte "
        "eines Dreimonatszeitraums für drei Monate zu zahlen (§ 7 Abs. 3 Rundfunkbeitragsstaatsvertrag)."
    )
    letter.table(
        [
            ("Zeitraum", "Monatsbeitrag", "Betrag", "fällig am"),
            ("10.2026 – 12.2026", eur("18.36"), f"**{eur('55.08')}**", "**15.11.2026**"),
        ],
        (55, 35, 35, 40),
        aligns=("LEFT", "RIGHT", "RIGHT", "RIGHT"),
        head_fill=BEITRAGSSERVICE.color,
        gap=2,
    )
    letter.para(RB_DUE_QUOTE, bold=True)
    letter.box(
        [
            "Empfänger: Beitragsservice Musterstadt",
            f"IBAN: {ACC_BEITRAGSSERVICE.iban_pretty} · BIC: {ACC_BEITRAGSSERVICE.bank.bic}",
            "Verwendungszweck: 512345678 (bitte nur die Beitragsnummer angeben)",
        ],
        title="So zahlen Sie per Überweisung",
    )
    letter.para(
        "Bequemer geht es mit dem SEPA-Lastschriftverfahren: Erteilen Sie uns ein Mandat unter "
        "rundfunkbeitrag-musterstadt.example – dann müssen Sie an keine Zahlung mehr denken. Wer bestimmte "
        "Sozialleistungen erhält, z. B. BAföG, kann sich auf Antrag von der Beitragspflicht befreien lassen."
    )
    letter.box(
        [
            "Wir fordern Sie niemals auf, Beiträge auf ein ausländisches Konto zu überweisen, und wir drohen "
            "nicht mit einer Pfändung innerhalb weniger Stunden. Unsere einzige Bankverbindung finden Sie in "
            "diesem Schreiben."
        ],
        title="Vorsicht vor betrügerischen Schreiben",
        fill=(253, 244, 230),
        border=(214, 140, 40),
        title_color=(160, 80, 0),
        size=8.4,
    )
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Ihr Beitragsservice Musterstadt",
        scribble=False,
        note="Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift gültig.",
    )


def rundfunkbeitrag() -> Sample:
    """Broadcasting-fee payment request for Oct–Dec 2026, dated 15.09.2026."""
    # Fixed due date as printed: Sun 15.11.2026. § 193 BGB would allow Mon 16.11., but fixed dates are shown as
    # written (earliest plausible date, SPEC §21).
    due = dc.checked("2026-11-15", "Sun")
    dc.expect(money("18.36") * 3 == money("55.08"), "3 × 18,36 €")
    truth = Truth(
        kind="broadcasting_fee",
        area="home",
        sender_name="Beitragsservice Musterstadt",
        sender_kind="public_broadcaster",
        document_date="2026-09-15",
        references=[Ref("Beitragsnummer", BEITRAGSNUMMER)],
        amounts=[Amount("Betrag 10.2026 – 12.2026", 55.08), Amount("Monatsbeitrag", 18.36)],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Broadcasting fee Oct–Dec 2026",
                expected_due=due,
                date_basis="fixed",
                nature="payment",
                amount=55.08,
                direction="out",
                quote=RB_DUE_QUOTE,
                reasoning="Explicit date 'fällig am 15.11.2026' (a Sunday); kept as written — § 193 BGB would allow "
                "Mon 16.11.2026, the earliest plausible date is shown.",
            ),
        ],
        payment=TruthPayment(ACC_BEITRAGSSERVICE.iban, "Beitragsservice Musterstadt", "512345678"),
        key_quotes=[RB_DUE_QUOTE, "Vorsicht vor betrügerischen Schreiben"],
        related=[("rundfunk_zahlungszentrale", "fake letter imitating this sender")],
    )
    return Sample(
        slug="rundfunkbeitrag_zahlungsaufforderung",
        title="Zahlungsaufforderung Rundfunkbeitrag",
        language="de",
        received_date=dc.checked("2026-09-17", "Thu"),
        render=lambda: as_pdf(
            letter_pdf(
                BEITRAGSSERVICE, "2026-09-15", _rundfunk, follow_ref=f"Beitragsnummer {BEITRAGSNUMMER}"
            )
        ),
        truth=truth,
        subject_hint="Rundfunkbeitrag 10–12/2026",
    )


# --------------------------------------------------------------------------------------------------
# Ausländerbehörde: Ablauf der Aufenthaltserlaubnis, Termin (16.09.2026)
# --------------------------------------------------------------------------------------------------

ABH_AZ = "32.2-AE-24-08815"
EXPIRY_QUOTE = (
    "Ihre Aufenthaltserlaubnis zum Zweck des Studiums nach § 16b Abs. 1 des Aufenthaltsgesetzes (AufenthG) ist bis "
    "zum 30.11.2026 gültig."
)
APPOINTMENT_QUOTE = "Termin: Mittwoch, 14.10.2026, 10:30 Uhr"
FIKTION_QUOTE = (
    "Wird der Antrag auf Verlängerung vor Ablauf der Aufenthaltserlaubnis gestellt, gilt diese bis zur Entscheidung "
    "der Ausländerbehörde als fortbestehend (§ 81 Abs. 4 AufenthG)."
)
FEE_QUOTE_ABH = "die Gebühr in Höhe von 100,00 € (Zahlung vor Ort mit girocard; Barzahlung ist nicht möglich)"


def _auslaenderbehoerde(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [
            ("Aktenzeichen", ABH_AZ),
            ("Auskunft erteilt", "Frau Kaya, Zimmer 2.14"),
            ("Telefon", "0123 400-3214"),
            ("E-Mail", "abh@musterstadt.example"),
            ("Datum", "16.09.2026"),
        ],
        stacked=True,
    )
    letter.subject("Ablauf Ihrer Aufenthaltserlaubnis am 30.11.2026 – Einladung zur Vorsprache")
    letter.para(SALUTE_DE)
    letter.para(
        f"{EXPIRY_QUOTE} Wenn Sie Ihren Aufenthalt über diesen Zeitpunkt hinaus fortsetzen möchten, müssen "
        "Sie vor Ablauf der Gültigkeit die Verlängerung beantragen. Für die Antragstellung haben wir für Sie "
        "folgenden Termin reserviert:"
    )
    letter.box(
        [
            f"**{APPOINTMENT_QUOTE}**",
            "Ort: Stadt Musterstadt, Ausländerbehörde, Musterplatz 1, 2. Obergeschoss, Raum 2.14",
        ],
        title="Ihr Termin",
        gap=2.5,
    )
    letter.para("Bitte bringen Sie zu dem Termin folgende Unterlagen im Original mit:", gap=1)
    letter.bullets(
        [
            "Ihren gültigen Reisepass",
            "die aktuelle Immatrikulationsbescheinigung für das Wintersemester 2026/27",
            "einen Nachweis über die Sicherung des Lebensunterhalts (Finanzierungsnachweis), z. B. Sperrkonto, "
            "Stipendienzusage oder Arbeitsvertrag mit den letzten drei Gehaltsabrechnungen",
            "einen Nachweis über ausreichenden Krankenversicherungsschutz",
            "ein aktuelles biometrisches Lichtbild (35 × 45 mm)",
            "Ihren Mietvertrag oder eine Wohnungsgeberbestätigung",
            FEE_QUOTE_ABH,
        ],
        size=8.6,
        gap=1.5,
    )
    letter.para(
        f"{FIKTION_QUOTE} Ein Aufenthaltstitel kann grundsätzlich nicht über die Gültigkeitsdauer Ihres "
        "Reisepasses hinaus erteilt werden; bitte prüfen Sie daher rechtzeitig Ihren Pass."
    )
    letter.para(
        "Können Sie den Termin nicht wahrnehmen, sagen Sie ihn bitte spätestens drei Werktage vorher ab."
    )
    letter.closing("Mit freundlichen Grüßen", ia="Im Auftrag", signers=[("Kaya", "")])


def auslaenderbehoerde() -> Sample:
    """Immigration office: permit expiry and appointment, dated 16.09.2026."""
    truth = Truth(
        kind="residence_permit",
        area="residence",
        sender_name="Stadt Musterstadt – Ausländerbehörde",
        sender_kind="immigration_office",
        document_date="2026-09-16",
        references=[Ref("Aktenzeichen", ABH_AZ)],
        amounts=[Amount("Gebühr Verlängerung", 100.0)],
        items=[
            TruthItem(
                kind="appointment",
                title_hint="Residence permit extension appointment",
                expected_due=dc.checked("2026-10-14", "Wed"),
                expected_time="10:30",
                date_basis="fixed",
                nature="appointment",
                quote=APPOINTMENT_QUOTE,
                location="Musterplatz 1, 2. OG, Raum 2.14, 12345 Musterstadt",
                reasoning="Fixed appointment; appointments never shift.",
            ),
            TruthItem(
                kind="expiry",
                title_hint="Residence permit (§ 16b AufenthG) expires",
                expected_due=dc.checked("2026-11-30", "Mon"),
                date_basis="fixed",
                nature="other",
                quote=EXPIRY_QUOTE,
                reasoning="Explicit validity end. Applying before it keeps the permit valid (§ 81 Abs. 4 AufenthG).",
            ),
            TruthItem(
                kind="payment",
                title_hint="Extension fee (pay at the appointment)",
                expected_due="2026-10-14",
                date_basis="fixed",
                nature="payment",
                amount=100.0,
                direction="out",
                quote=FEE_QUOTE_ABH,
                reasoning="Paid on site at the appointment on 14.10.2026.",
                optional=True,
            ),
            TruthItem(
                kind="task",
                title_hint="Gather the documents for the appointment",
                expected_due=None,
                date_basis="none",
                nature="declaration",
                quote="Bitte bringen Sie zu dem Termin folgende Unterlagen im Original mit:",
                reasoning="Preparation task for the appointment; no separate date.",
                optional=True,
            ),
        ],
        key_quotes=[EXPIRY_QUOTE, APPOINTMENT_QUOTE, FIKTION_QUOTE],
        kind_alternatives=["authority_letter"],
        related=[
            ("reisepass", "passport expires 10.02.2027 – before a renewed permit would"),
            ("immatrikulationsbescheinigung_wise_2026", "document to bring"),
            ("mietvertrag", "document to bring"),
        ],
        notes="Passport expires 10.02.2027 → the permit cannot be extended beyond it (passport_before_permit).",
    )
    return Sample(
        slug="auslaenderbehoerde_termin",
        title="Ablauf Aufenthaltserlaubnis – Einladung zur Vorsprache",
        language="de",
        received_date=dc.checked("2026-09-18", "Fri"),
        render=lambda: as_pdf(
            letter_pdf(STADT_ABH, "2026-09-16", _auslaenderbehoerde, follow_ref=f"Az. {ABH_AZ}")
        ),
        truth=truth,
        subject_hint="Aufenthaltserlaubnis – Termin",
    )


# --------------------------------------------------------------------------------------------------
# Stadtbibliothek: Mahnung (22.09.2026)
# --------------------------------------------------------------------------------------------------

RETURN_QUOTE = "Bitte geben Sie die Medien bis zum 02.10.2026 zurück."


def _bibliothek(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [
            ("Benutzer-Nr.", "0481 1123 5"),
            ("Ihr Kontakt", "Ausleihe / Service"),
            ("Telefon", BIBLIOTHEK.phone),
            ("Datum", "22.09.2026"),
        ]
    )
    letter.subject("Erinnerung: Leihfrist überschritten (1. Mahnung)")
    letter.para(SALUTE_DE)
    letter.para("die Leihfrist für die folgenden Medien ist abgelaufen:")
    letter.table(
        [
            ("Titel", "Mediennummer", "Leihfrist bis", "Gebühr"),
            ("Einführung in die Statistik mit R", "30031 004 812", "08.09.2026", eur("2.50")),
            ("Deutsch im Alltag B2 – Übungsbuch", "30031 017 455", "15.09.2026", eur("2.00")),
            ("**Summe der Gebühren**", "", "", f"**{eur('4.50')}**"),
        ],
        (78, 32, 30, 25),
        aligns=("LEFT", "LEFT", "CENTER", "RIGHT"),
        head_fill=BIBLIOTHEK.color,
        gap=3,
    )
    letter.para(
        f"**{RETURN_QUOTE}** Die bisher entstandenen Gebühren in Höhe von 4,50 € können Sie bei der Rückgabe an "
        "der Servicetheke oder am Kassenautomaten bezahlen."
    )
    letter.para(
        "Nach Ablauf dieser Frist erhöhen sich die Gebühren um 0,50 € pro Medium und Öffnungstag; ab einem "
        "Gebührenstand von 10,00 € wird Ihr Benutzerkonto für weitere Ausleihen gesperrt."
    )
    letter.para(
        "Die Rückgabe ist rund um die Uhr über die Rückgabebox am Eingang Bibliotheksplatz möglich. Sofern "
        "keine Vormerkung vorliegt, können Sie die Leihfrist auch online in Ihrem Bibliothekskonto "
        "verlängern."
    )
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Ihre Stadtbibliothek Musterstadt",
        scribble=False,
        note="Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift gültig.",
    )


def bibliothek_mahnung() -> Sample:
    """Library overdue notice, dated 22.09.2026."""
    due = dc.checked("2026-10-02", "Fri")
    truth = Truth(
        kind="dunning",
        area="leisure",
        sender_name="Stadtbibliothek Musterstadt",
        sender_kind="authority",
        document_date="2026-09-22",
        references=[Ref("Benutzer-Nr.", "0481 1123 5")],
        amounts=[Amount("Säumnisgebühren", 4.50)],
        items=[
            TruthItem(
                kind="task",
                title_hint="Return two overdue library books",
                expected_due=due,
                date_basis="fixed",
                nature="declaration",
                quote=RETURN_QUOTE,
                reasoning="Explicit date 02.10.2026 (Friday).",
            ),
            TruthItem(
                kind="payment",
                title_hint="Pay the library fees (4,50 €) when returning",
                expected_due=due,
                date_basis="fixed",
                nature="payment",
                amount=4.50,
                direction="out",
                quote="Die bisher entstandenen Gebühren in Höhe von 4,50 € können Sie bei der Rückgabe",
                reasoning="Payable on return; same date as the return deadline.",
                optional=True,
            ),
        ],
        key_quotes=[RETURN_QUOTE, "Leihfrist überschritten"],
        kind_alternatives=["fine", "other"],
    )
    return Sample(
        slug="stadtbibliothek_mahnung",
        title="Stadtbibliothek: Leihfrist überschritten",
        language="de",
        received_date=dc.checked("2026-09-24", "Thu"),
        render=lambda: as_pdf(letter_pdf(BIBLIOTHEK, "2026-09-22", _bibliothek)),
        truth=truth,
        subject_hint="Mahnung Stadtbibliothek",
    )


# --------------------------------------------------------------------------------------------------
# Ordnungsamt: Verwarnung mit Verwarnungsgeld (23.09.2026) — phone photo
# --------------------------------------------------------------------------------------------------

OA_AZ = "32.4-VW-2026-0184512"
KASSENZEICHEN = "5126 0184 5122"
FINE_QUOTE = (
    "Die Verwarnung wird nur wirksam, wenn Sie mit ihr einverstanden sind und das Verwarnungsgeld innerhalb einer "
    "Woche nach Zugang dieses Schreibens auf das unten genannte Konto der Stadtkasse Musterstadt überweisen."
)
ANHOERUNG_QUOTE = (
    "Wenn Sie mit der Verwarnung nicht einverstanden sind oder sich zu dem Vorwurf äußern möchten, verwenden Sie "
    "bitte den beigefügten Anhörungsbogen."
)


def _checkbox(letter: Letter, text: str) -> None:
    pdf = letter.pdf
    y = pdf.get_y()
    with pdf.local_context():
        pdf.set_draw_color(*GREY)
        pdf.set_line_width(0.3)
        pdf.rect(LEFT, y + 0.6, 3.4, 3.4)
    letter.para(text, indent=6, gap=1.6)


def _lines(letter: Letter, count: int) -> None:
    pdf = letter.pdf
    for _ in range(count):
        y = pdf.get_y() + 6
        with pdf.local_context():
            pdf.set_draw_color(*GREY)
            pdf.set_line_width(0.2)
            pdf.line(LEFT + 6, y, LEFT + WIDTH, y)
        pdf.set_y(y + 1)
    pdf.ln(3)


def _knoellchen(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [
            ("Aktenzeichen", OA_AZ),
            ("Kassenzeichen (bitte stets angeben)", KASSENZEICHEN),
            ("Sachbearbeitung", "Herr Exempel, Telefon 0123 400-3290"),
            ("Datum", "23.09.2026"),
        ],
        stacked=True,
    )
    letter.subject("Verwarnung mit Verwarnungsgeld wegen einer Verkehrsordnungswidrigkeit")
    letter.para(SALUTE_DE)
    letter.para(
        "die Halterin des unten genannten Fahrzeugs, die Beispiel Carsharing GmbH, hat Sie als "
        "Fahrzeugführer zur Tatzeit benannt. Ihnen wird vorgeworfen, folgende Ordnungswidrigkeit begangen zu "
        "haben:"
    )
    letter.kv(
        [
            ("Tatzeit", "12.09.2026, 14:37 Uhr bis 16:05 Uhr"),
            ("Tatort", "Musterstadt, Lindenstraße 14 (gebührenpflichtiger Parkplatz)"),
            ("Fahrzeug", "Pkw, amtliches Kennzeichen MU-CS 482"),
            (
                "Tatvorwurf",
                "Sie parkten ohne gültigen Parkschein. Parkdauer: länger als 1 Stunde, aber nicht länger als "
                "2 Stunden.",
            ),
            (
                "Rechtsgrundlagen",
                "§ 13 Abs. 1, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 63.3 BKat; Tatbestandsnr. 163636",
            ),
            ("Beweismittel", "Feststellung durch Verkehrsüberwachungskraft (Dienstnr. 417), 2 Fotos"),
        ],
        key_w=34,
        size=8.6,
        borders="HORIZONTAL_LINES",
        gap=2.5,
    )
    letter.para(
        "Wegen dieser Ordnungswidrigkeit werden Sie hiermit gemäß § 56 des Gesetzes über "
        "Ordnungswidrigkeiten (OWiG) verwarnt. **Das Verwarnungsgeld beträgt 30,00 €.**"
    )
    letter.para(FINE_QUOTE)
    letter.para(
        f"{ANHOERUNG_QUOTE} Wird das Verwarnungsgeld nicht fristgerecht gezahlt, wird ein "
        "Bußgeldverfahren eingeleitet; dabei entstehen zusätzlich Gebühren und Auslagen von mindestens "
        "28,50 €."
    )
    letter.box(
        [
            f"Empfänger: Stadtkasse Musterstadt · IBAN {ACC_STADTKASSE.iban_pretty} · BIC {ACC_STADTKASSE.bank.bic}",
            f"Betrag: **30,00 €** · Verwendungszweck: **Kassenzeichen {KASSENZEICHEN}**",
        ],
        title="Zahlungsangaben",
        size=8.6,
    )
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Ihre Bußgeldstelle",
        scribble=False,
        note="Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift gültig. Anlage: Anhörungsbogen",
    )
    letter.new_page()
    letter.title(
        "Anhörungsbogen im Verwarnungsgeldverfahren",
        size=13,
        sub=f"Aktenzeichen {OA_AZ} · Kassenzeichen {KASSENZEICHEN} · Tatzeit 12.09.2026, 14:37 Uhr",
    )
    letter.para(
        "Sie haben Gelegenheit, sich zu dem Vorwurf zu äußern. Bitte senden Sie diesen Bogen innerhalb einer "
        "Woche nach Zugang an die Stadt Musterstadt, Ordnungsamt – Bußgeldstelle, zurück. Haben Sie das "
        "Verwarnungsgeld bereits gezahlt, ist eine Rücksendung nicht erforderlich. Sie sind nicht "
        "verpflichtet, Angaben zur Sache zu machen."
    )
    letter.heading("1. Angaben zur Sache (freiwillig)")
    _checkbox(letter, "Ich räume den Verstoß ein.")
    _checkbox(letter, "Ich war nicht Fahrzeugführer/in. Verantwortlich war (Name, Anschrift):")
    _lines(letter, 2)
    _checkbox(letter, "Ich bestreite den Verstoß aus folgenden Gründen:")
    _lines(letter, 3)
    letter.heading("2. Angaben zur Person (Pflichtangaben nach § 111 OWiG)")
    letter.kv(
        [("Name, Vorname", ""), ("Geburtsdatum, Geburtsort", ""), ("Anschrift", "")],
        key_w=55,
        borders="HORIZONTAL_LINES",
        gap=8,
    )
    letter.signature_fields(("", "Ort, Datum", None), ("", "Unterschrift", None))


def knoellchen() -> Sample:
    """Parking fine (Verwarnungsgeld) from the Ordnungsamt, dated 23.09.2026, as a phone photo."""
    received = dc.checked("2026-09-25", "Fri")
    # "innerhalb einer Woche nach Zugang" → receipt anchor. Received Fri 25.09.2026 → one week later is
    # Fri 02.10.2026 (§§ 187 Abs. 1, 188 Abs. 2 BGB), a business day. Without a confirmed arrival date the
    # conservative fallback is the document date: Wed 23.09. + 1 week = Wed 30.09.2026 (low confidence).
    due = dc.checked(dc.plus_days(received, 7), "Fri")
    truth = Truth(
        kind="fine",
        area="mobility",
        sender_name="Stadt Musterstadt – Ordnungsamt",
        sender_kind="authority",
        document_date="2026-09-23",
        references=[
            Ref("Aktenzeichen", OA_AZ),
            Ref("Kassenzeichen", KASSENZEICHEN),
            Ref("Kennzeichen", "MU-CS 482"),
        ],
        amounts=[Amount("Verwarnungsgeld", 30.0)],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Pay the parking fine (Verwarnungsgeld)",
                expected_due=due,
                date_basis="relative",
                nature="payment",
                amount=30.0,
                direction="out",
                quote=FINE_QUOTE,
                reasoning="One week after receipt (receipt anchor). Received Fri 25.09.2026 → Fri 02.10.2026. "
                "Fallback without a confirmed arrival date: 23.09. + 1 week = 30.09.2026 (low confidence).",
            ),
            TruthItem(
                kind="deadline",
                title_hint="Optional: reply with the Anhörungsbogen instead of paying",
                expected_due=due,
                date_basis="relative",
                nature="declaration",
                quote=ANHOERUNG_QUOTE,
                reasoning="Alternative to paying; the enclosed form asks for a reply within a week of receipt (a "
                "request, not a statutory deadline).",
                optional=True,
            ),
        ],
        remedy=TruthRemedy("none", None),
        payment=TruthPayment(ACC_STADTKASSE.iban, "Stadtkasse Musterstadt", f"Kassenzeichen {KASSENZEICHEN}"),
        key_quotes=[FINE_QUOTE, ANHOERUNG_QUOTE, "Das Verwarnungsgeld beträgt 30,00 €."],
        kind_alternatives=["authority_letter"],
        notes="Photo of page 1 only (the Anhörungsbogen on page 2 was not photographed).",
    )
    return Sample(
        slug="verwarnungsgeld_parken",
        title="Verwarnung mit Verwarnungsgeld (Foto)",
        language="de",
        received_date=received,
        captured_date=dc.checked("2026-09-26", "Sat"),
        photo=True,
        render=lambda: as_photos(
            letter_pdf(STADT_ORDNUNGSAMT, "2026-09-23", _knoellchen, follow_ref=f"Az. {OA_AZ}"),
            [(0, 2026092301, "wood", -2.4)],
        ),
        truth=truth,
        subject_hint="Knöllchen / Verwarnungsgeld",
    )


# --------------------------------------------------------------------------------------------------
# Finanzamt: Einkommensteuerbescheid 2025 (15.09.2026) — two phone photos, new-mail tray
# --------------------------------------------------------------------------------------------------

STEUERNUMMER = "123/4567/8901"
GROSS_WAGE = 23298
WERBUNGSKOSTEN = 1230
VORSORGE = 3678
SA_PAUSCHBETRAG = 36
LST_WITHHELD = money("1546.45")
EST_QUOTE = "Die Einkommensteuer wird auf 1.234,00 € festgesetzt."
REFUND_QUOTE = (
    f"Der Betrag von 312,45 € wird Ihnen auf das Konto {sam.IBAN_PRETTY} bei der Musterbank eG erstattet."
)
EINSPRUCH_QUOTE = "Die Frist für die Einlegung des Einspruchs beträgt einen Monat."
BEKANNTGABE_QUOTE = (
    "Bei Zusendung durch einfachen Brief oder Zustellung mittels Einschreiben durch Übergabe gilt die Bekanntgabe "
    "mit dem vierten Tag nach Aufgabe zur Post als bewirkt, es sei denn, dass der Bescheid zu einem späteren "
    "Zeitpunkt zugegangen ist."
)


def income_tax_2025(zve: int) -> int:
    """Tariff income tax 2025 (§ 32a EStG, Grundtabelle), used to double-check the assessment."""
    if zve <= 12096:
        return 0
    if zve <= 17443:
        y = (zve - 12096) / 10000
        return math.floor((932.30 * y + 1400) * y)
    if zve <= 68480:
        z = (zve - 17443) / 10000
        return math.floor((176.64 * z + 2397) * z + 1015.13)
    raise ValueError("outside the range needed for the sample")


def _zve() -> int:
    return GROSS_WAGE - WERBUNGSKOSTEN - VORSORGE - SA_PAUSCHBETRAG


def _steuerbescheid(letter: Letter) -> None:
    est = Decimal(income_tax_2025(_zve()))
    refund = LST_WITHHELD - est
    letter.address(sam.recipient())
    letter.info(
        [
            ("Steuernummer", STEUERNUMMER),
            ("IdNr.", sam.STEUER_ID),
            ("Telefon", "0123 887-2204"),
            ("Zimmer", "3.07"),
            ("Datum", "15.09.2026"),
        ],
        title="Bitte bei Rückfragen angeben",
    )
    letter.subject("Bescheid für 2025 über Einkommensteuer und Solidaritätszuschlag")
    letter.table(
        [
            ("Festsetzung", "Einkommensteuer", "Solidaritätszuschlag"),
            ("festgesetzt werden", f"**{eur(est)}**", eur(0)),
        ],
        (75, 45, 45),
        aligns=("LEFT", "RIGHT", "RIGHT"),
        head_fill=(230, 230, 230),
        head_text=(20, 20, 20),
        gap=1.5,
    )
    letter.para(EST_QUOTE, gap=3)
    letter.table(
        [
            ("Abrechnung (Stand: 15.09.2026)", "Einkommensteuer", "Solidaritätszuschlag"),
            ("Festgesetzt", eur(est), eur(0)),
            ("abzüglich Steuerabzug vom Lohn", eur(LST_WITHHELD), eur(0)),
            ("**verbleibende Beträge**", f"**– {eur(refund)}**", eur(0)),
        ],
        (75, 45, 45),
        aligns=("LEFT", "RIGHT", "RIGHT"),
        head_fill=(230, 230, 230),
        head_text=(20, 20, 20),
        gap=2,
    )
    letter.para(REFUND_QUOTE, bold=True, gap=3)
    letter.heading("Berechnungsgrundlagen", color=(20, 20, 20))
    letter.table(
        [
            ("Einkünfte aus nichtselbständiger Arbeit", ""),
            ("Bruttoarbeitslohn", f"{de_num(GROSS_WAGE, 0)} €"),
            ("abzüglich Werbungskosten (Arbeitnehmer-Pauschbetrag)", f"{de_num(WERBUNGSKOSTEN, 0)} €"),
            (
                "Summe der Einkünfte / Gesamtbetrag der Einkünfte",
                f"{de_num(GROSS_WAGE - WERBUNGSKOSTEN, 0)} €",
            ),
            ("abzüglich Vorsorgeaufwendungen", f"{de_num(VORSORGE, 0)} €"),
            ("abzüglich Sonderausgaben-Pauschbetrag", f"{de_num(SA_PAUSCHBETRAG, 0)} €"),
            ("**zu versteuerndes Einkommen**", f"**{de_num(_zve(), 0)} €**"),
            ("tarifliche Einkommensteuer (Grundtabelle)", f"{de_num(est, 0)} €"),
        ],
        (130, 35),
        aligns=("LEFT", "RIGHT"),
        header=True,
        head_fill=(230, 230, 230),
        head_text=(20, 20, 20),
        size=8.4,
        gap=2,
    )
    letter.small(
        "Die Erläuterungen und die Rechtsbehelfsbelehrung auf Seite 2 sind Bestandteil dieses Bescheids."
    )
    letter.new_page()
    letter.heading("Erläuterungen", color=(20, 20, 20))
    letter.bullets(
        [
            "Bei der Festsetzung wurden die elektronisch übermittelten Daten Ihrer Arbeitgeber "
            "(Lohnsteuerbescheinigungen) sowie Ihrer Kranken- und Pflegeversicherung berücksichtigt.",
            "Die geltend gemachten Aufwendungen für Arbeitsmittel (412 €) übersteigen zusammen mit den übrigen "
            "Werbungskosten den Arbeitnehmer-Pauschbetrag von 1.230 € nicht; der Pauschbetrag wurde angesetzt.",
            "Der Solidaritätszuschlag wird nicht erhoben, da die Einkommensteuer die Freigrenze nicht übersteigt.",
        ],
        size=8.8,
    )
    letter.heading("Rechtsbehelfsbelehrung", color=(20, 20, 20))
    letter.para(
        "Der Bescheid kann mit dem Einspruch angefochten werden. Der Einspruch ist bei dem Finanzamt "
        "Musterstadt, Steuerplatz 1, 12345 Musterstadt, schriftlich einzureichen, diesem elektronisch zu "
        "übermitteln oder dort zur Niederschrift zu erklären. Ein Einspruch ist jedoch ausgeschlossen, soweit "
        "dieser Bescheid einen Verwaltungsakt ändert oder ersetzt, gegen den ein zulässiger Einspruch oder "
        "(nach einem zulässigen Einspruch) eine zulässige Klage, Revision oder Nichtzulassungsbeschwerde "
        "anhängig ist. In diesem Fall wird der neue Verwaltungsakt Gegenstand des Rechtsbehelfsverfahrens.",
        size=8.8,
    )
    letter.para(
        f"{EINSPRUCH_QUOTE} Sie beginnt mit Ablauf des Tages, an dem Ihnen dieser Bescheid bekannt gegeben "
        f"worden ist. {BEKANNTGABE_QUOTE} Bei Zustellung mit Postzustellungsurkunde oder mittels Einschreiben "
        "mit Rückschein oder gegen Empfangsbekenntnis ist Tag der Bekanntgabe der Tag der Zustellung. Bei "
        "Bereitstellung zum Datenabruf gilt der Bescheid am vierten Tag nach Absendung der elektronischen "
        "Benachrichtigung über die Bereitstellung der Daten als bekannt gegeben, es sei denn, dass die "
        "Benachrichtigung zu einem späteren Zeitpunkt zugegangen ist.",
        size=8.8,
    )
    letter.heading("Hinweise", color=(20, 20, 20))
    letter.para(
        "Einen Einspruch können Sie auch bequem über ELSTER (www.elster.de) einlegen. Bitte bewahren Sie "
        "diesen Bescheid auf. Informationen zum Datenschutz erhalten Sie unter "
        "finanzamt-musterstadt.example/datenschutz.",
        size=8.8,
    )
    letter.small("Dieser Bescheid wurde maschinell erstellt und wird nicht unterschrieben.", color=GREY)


def steuerbescheid() -> Sample:
    """Income-tax assessment 2025, dated Tue 15.09.2026 — two phone photos (tray)."""
    zve = _zve()
    est = income_tax_2025(zve)
    dc.expect(zve == 18354 and est == 1234, "zvE 18.354 € → 1.234 € (§ 32a EStG 2025)")
    dc.expect(LST_WITHHELD - est == money("312.45"), "refund")
    # § 122 Abs. 2 Nr. 1 AO (posted from 2025): deemed notified on the 4th day after posting.
    # Posted Tue 15.09.2026 → Sat 19.09.2026 → not a business day → Mon 21.09.2026 (§ 108 Abs. 3 AO,
    # BFH IX R 68/98). One month (§ 355 Abs. 1 AO; § 108 Abs. 1 AO with §§ 187 Abs. 1, 188 Abs. 2 BGB)
    # → Wed 21.10.2026.
    fourth_day = dc.checked(dc.plus_days("2026-09-15", 4), "Sat")
    dc.expect(not dc.is_business_day(fourth_day), "4th day is a Saturday")
    deemed = dc.checked("2026-09-21", "Mon")
    due = dc.checked(dc.plus_months(deemed, 1), "Wed")
    dc.expect(due == "2026-10-21", "expected Einspruch deadline")
    truth = Truth(
        kind="tax_assessment",
        area="tax",
        sender_name="Finanzamt Musterstadt",
        sender_kind="tax_office",
        document_date="2026-09-15",
        references=[Ref("Steuernummer", STEUERNUMMER), Ref("IdNr.", sam.STEUER_ID)],
        amounts=[
            Amount("Festgesetzte Einkommensteuer", float(est)),
            Amount("Steuerabzug vom Lohn", float(LST_WITHHELD)),
            Amount("Erstattung", 312.45),
            Amount("zu versteuerndes Einkommen", float(zve)),
        ],
        items=[
            TruthItem(
                kind="deadline",
                title_hint="Last day to file an objection (Einspruch)",
                expected_due=due,
                date_basis="relative",
                nature="objection",
                quote=EINSPRUCH_QUOTE,
                reasoning="Dated Tue 15.09.2026 → § 122 Abs. 2 Nr. 1 AO: 4th day after posting = Sat 19.09. → next "
                "business day Mon 21.09.2026 → + 1 month = Wed 21.10.2026.",
            ),
            TruthItem(
                kind="payment",
                title_hint="Tax refund 312,45 € (incoming)",
                expected_due=None,
                date_basis="none",
                nature="payment",
                amount=312.45,
                direction="in",
                quote=REFUND_QUOTE,
                reasoning="Refund is transferred by the tax office; no date stated.",
                optional=True,
            ),
        ],
        remedy=TruthRemedy("einspruch", "Finanzamt Musterstadt"),
        key_quotes=[EST_QUOTE, REFUND_QUOTE, EINSPRUCH_QUOTE, BEKANNTGABE_QUOTE],
        tax_relevant=True,
        notes="Two photos (page 1: assessment, page 2: Rechtsbehelfsbelehrung) to be combined into one document.",
    )
    return Sample(
        slug="steuerbescheid_2025",
        title="Einkommensteuerbescheid 2025 (Fotos)",
        language="de",
        received_date=dc.checked("2026-09-17", "Thu"),
        captured_date=dc.checked("2026-09-28", "Mon"),
        photo=True,
        tray=True,
        sort_date="2026-09-15",
        render=lambda: as_photos(
            letter_pdf(FINANZAMT, "2026-09-15", _steuerbescheid, follow_ref=f"Steuernummer {STEUERNUMMER}"),
            [(0, 2026091501, "desk", 1.8), (1, 2026091502, "desk", -1.3)],
        ),
        truth=truth,
        subject_hint="Steuerbescheid 2025",
    )
