"""Work and study: Werkstudent contract, payslip, university letters and the (English) scholarship award."""

from __future__ import annotations

from decimal import Decimal

from samplelife import datecheck as dc
from samplelife import persona as sam
from samplelife.common import SALUTE_DE, SALUTE_EN, as_pdf, letter_pdf
from samplelife.fmt import eur, money
from samplelife.letter import GREY, Letter, tint
from samplelife.orgs import ACC_HOCHSCHULE, HOCHSCHULE, MUSTERTECH, SCHOLARSHIP
from samplelife.truth import Amount, Ref, Sample, Truth, TruthContract, TruthItem, TruthPayment

# --------------------------------------------------------------------------------------------------
# Muster Tech: befristeter Arbeitsvertrag für Werkstudierende (20.03.2026)
# --------------------------------------------------------------------------------------------------

AV_TERM_QUOTE = (
    "Das Arbeitsverhältnis beginnt am 01.04.2026 und ist bis zum 31.03.2027 befristet. Es endet mit Ablauf des "
    "31.03.2027, ohne dass es einer Kündigung bedarf."
)
AV_NOTICE_QUOTE = (
    "Nach Ablauf der Probezeit kann das Arbeitsverhältnis von beiden Seiten unter Einhaltung der gesetzlichen "
    "Kündigungsfristen (§ 622 BGB) ordentlich gekündigt werden."
)
AV_PAY_QUOTE = "Der Arbeitnehmer erhält eine Vergütung von 16,50 € brutto je geleisteter Arbeitsstunde."


def _arbeitsvertrag(letter: Letter) -> None:
    letter.size = 8.8
    letter.lh = 8.8 * 0.47
    letter.title(
        "Befristeter Arbeitsvertrag für Werkstudierende",
        size=14,
        y=40,
        sub=f"Personalnummer {sam.PERSONALNUMMER} · Bereich Data Engineering",
    )
    letter.para(
        "Zwischen der **Muster Tech GmbH**, Innovationsweg 42, 12345 Musterstadt, vertreten durch die "
        "Geschäftsführerin Dr. Miriam Beispiel – nachfolgend „Arbeitgeberin“ – und **Herrn Sam Rivera**, "
        "geb. 14.03.2000, Beispielweg 5, 12345 Musterstadt – nachfolgend „Arbeitnehmer“ – wird folgender "
        "Arbeitsvertrag geschlossen:",
        gap=2.4,
    )
    clauses = [
        (
            "§ 1 Beginn, Befristung und Tätigkeit",
            [
                f"(1) {AV_TERM_QUOTE} Die Befristung erfolgt ohne Sachgrund gemäß § 14 Abs. 2 TzBfG.",
                "(2) Der Arbeitnehmer wird als Werkstudent im Bereich Data Engineering beschäftigt. Zu seinen Aufgaben "
                "gehören insbesondere die Entwicklung und Pflege von Datenpipelines sowie die Unterstützung bei "
                "Analysen.",
                "(3) Der Arbeitnehmer versichert, an der Hochschule Musterstadt ordentlich immatrikuliert zu sein. Er legt "
                "zu Beginn jedes Semesters eine aktuelle Immatrikulationsbescheinigung vor und teilt das Ende oder eine "
                "Unterbrechung des Studiums unverzüglich mit.",
            ],
        ),
        (
            "§ 2 Probezeit",
            [
                "Die ersten drei Monate des Arbeitsverhältnisses gelten als Probezeit. Während der Probezeit kann das "
                "Arbeitsverhältnis von beiden Seiten mit einer Frist von zwei Wochen gekündigt werden (§ 622 Abs. 3 BGB).",
            ],
        ),
        (
            "§ 3 Arbeitszeit",
            [
                "Die regelmäßige wöchentliche Arbeitszeit beträgt 20 Stunden. Während der Vorlesungszeit darf sie "
                "20 Stunden pro Woche nicht überschreiten; in der vorlesungsfreien Zeit kann nach Absprache mehr "
                "gearbeitet werden. Die Arbeitszeit wird im Zeiterfassungssystem dokumentiert.",
            ],
        ),
        (
            "§ 4 Vergütung",
            [
                f"{AV_PAY_QUOTE} Die Abrechnung erfolgt monatlich nach den erfassten Stunden; die Vergütung wird "
                "spätestens am letzten Bankarbeitstag des Monats auf ein vom Arbeitnehmer benanntes Konto überwiesen.",
            ],
        ),
        (
            "§ 5 Urlaub",
            [
                "Der Arbeitnehmer hat Anspruch auf 25 Arbeitstage Erholungsurlaub im Kalenderjahr, bezogen auf eine "
                "Fünf-Tage-Woche. Bei einer anderen Verteilung der Arbeitszeit wird der Anspruch anteilig berechnet.",
            ],
        ),
        (
            "§ 6 Arbeitsverhinderung",
            [
                "Der Arbeitnehmer zeigt eine Arbeitsunfähigkeit und deren voraussichtliche Dauer unverzüglich an. Die "
                "Entgeltfortzahlung richtet sich nach dem Entgeltfortzahlungsgesetz.",
            ],
        ),
        (
            "§ 7 Kündigung",
            [
                f"(1) {AV_NOTICE_QUOTE} Das Recht zur außerordentlichen Kündigung bleibt unberührt.",
                "(2) Die Kündigung bedarf der Schriftform (§ 623 BGB); die elektronische Form ist ausgeschlossen.",
            ],
        ),
        (
            "§ 8 Verschwiegenheit",
            [
                "Der Arbeitnehmer ist verpflichtet, über alle Betriebs- und Geschäftsgeheimnisse sowie über Kundendaten "
                "auch nach Beendigung des Arbeitsverhältnisses Stillschweigen zu bewahren.",
            ],
        ),
        (
            "§ 9 Ausschlussfristen",
            [
                "Ansprüche aus dem Arbeitsverhältnis verfallen, wenn sie nicht innerhalb von drei Monaten nach "
                "Fälligkeit in Textform gegenüber der anderen Vertragspartei geltend gemacht werden. Dies gilt nicht für "
                "Ansprüche auf den gesetzlichen Mindestlohn sowie für Ansprüche aus vorsätzlicher Pflichtverletzung.",
            ],
        ),
        (
            "§ 10 Schlussbestimmungen",
            [
                "Änderungen und Ergänzungen dieses Vertrags bedürfen der Schriftform. Sollte eine Bestimmung unwirksam "
                "sein, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt.",
            ],
        ),
    ]
    for heading, paragraphs in clauses:
        letter.heading(heading, size=9.2, gap=0.4)
        for paragraph in paragraphs:
            letter.para(paragraph, gap=1.1, align="J")
        letter.space(0.8)
    letter.space(2)
    letter.signature_fields(
        ("Musterstadt, 20.03.2026", "Muster Tech GmbH (Dr. Miriam Beispiel)", "mustertech:miriam"),
        ("Musterstadt, 20.03.2026", "Sam Rivera (Arbeitnehmer)", "sam:work"),
    )


def arbeitsvertrag() -> Sample:
    """Fixed-term working-student contract, Muster Tech GmbH, 20.03.2026."""
    end = dc.checked("2027-03-31", "Wed")
    # § 622 Abs. 1 BGB (employee, after probation): four weeks to the 15th or the end of a calendar month.
    # Notice received on Mon 28.09.2026 → four weeks later is Mon 26.10.2026 → next 15th/month end: Sat 31.10.2026.
    # Latest receipt for 31.10.: 31.10. − 28 days = Sat 03.10.2026 (holiday; notice deadlines do not move; the
    # safe date is Fri 02.10.2026). Written form with a wet signature (§ 623 BGB).
    dc.expect(dc.plus_days(sam.SIMULATED_TODAY, 28) == "2026-10-26", "four weeks after today")
    exit_date = dc.checked("2026-10-31", "Sat")
    cancel_by = dc.checked(dc.plus_days(exit_date, -28), "Sat")
    truth = Truth(
        kind="employment",
        area="work",
        sender_name="Muster Tech GmbH",
        sender_kind="employer",
        document_date="2026-03-20",
        references=[Ref("Personalnummer", sam.PERSONALNUMMER)],
        amounts=[Amount("Stundenlohn (brutto)", 16.50)],
        items=[
            TruthItem(
                kind="expiry",
                title_hint="Working-student contract ends",
                expected_due=end,
                date_basis="fixed",
                nature="other",
                quote=AV_TERM_QUOTE,
                reasoning="Fixed-term contract ends automatically on 31.03.2027 (relevant for the residence permit's "
                "proof of funds).",
            ),
            TruthItem(
                kind="task",
                title_hint="Hand in the enrolment certificate each semester",
                expected_due=None,
                date_basis="none",
                nature="declaration",
                quote="Er legt zu Beginn jedes Semesters eine aktuelle Immatrikulationsbescheinigung vor",
                reasoning="Recurring obligation without a date.",
                optional=True,
            ),
        ],
        contract=TruthContract(
            name="Werkstudentenvertrag Muster Tech",
            category="employment",
            regime="employment622",
            customer_number=sam.PERSONALNUMMER,
            concluded_date="2026-03-20",
            start_date="2026-04-01",
            initial_term_months=12,
            renewal_term_months=None,
            notice_value=4,
            notice_unit="weeks",
            notice_basis="end_of_month",
            end_date=end,
            cost_amount=None,
            cost_interval=None,
            expected_current_term_end=end,
            expected_cancel_by=cancel_by,
            expected_earliest_exit=exit_date,
            reasoning="Probation ended 30.06.2026. § 622 Abs. 1 BGB: 4 weeks to the 15th or month end. Notice "
            "received 2026-09-28 → earliest end 31.10.2026; it must arrive by Sat 03.10.2026 (safe date Fri "
            "02.10.2026). Otherwise the contract simply ends on 31.03.2027.",
        ),
        key_quotes=[AV_TERM_QUOTE, AV_NOTICE_QUOTE, AV_PAY_QUOTE],
        related=[("gehaltsabrechnung_2026_08", "payslip under this contract")],
    )
    return Sample(
        slug="arbeitsvertrag_werkstudent",
        title="Arbeitsvertrag Werkstudent Muster Tech",
        language="de",
        received_date=dc.checked("2026-03-20", "Fri"),
        render=lambda: as_pdf(
            letter_pdf(
                MUSTERTECH,
                "2026-03-20",
                _arbeitsvertrag,
                follow_ref=f"Arbeitsvertrag · Personalnummer {sam.PERSONALNUMMER}",
            )
        ),
        truth=truth,
        subject_hint="Arbeitsvertrag Werkstudent",
    )


# --------------------------------------------------------------------------------------------------
# Muster Tech: Verdienstabrechnung August 2026 (31.08.2026)
# --------------------------------------------------------------------------------------------------

HOURS = {"04": 80, "05": 84, "06": 78, "07": 88, "08": 86}
RATE = Decimal("16.50")
RV_RATE = Decimal("0.093")
LOHNSTEUER = {
    "04": Decimal("0"),
    "05": Decimal("0"),
    "06": Decimal("0"),
    "07": Decimal("6.41"),
    "08": Decimal("1.83"),
}


def _payslip_numbers() -> dict[str, Decimal]:
    gross = {m: money(h * RATE) for m, h in HOURS.items()}
    rv = {m: money(g * RV_RATE) for m, g in gross.items()}
    aug_gross, aug_rv, aug_tax = gross["08"], rv["08"], LOHNSTEUER["08"]
    return {
        "gross": aug_gross,
        "rv": aug_rv,
        "tax": aug_tax,
        "net": aug_gross - aug_rv - aug_tax,
        "ytd_gross": sum(gross.values(), Decimal(0)),
        "ytd_rv": sum(rv.values(), Decimal(0)),
        "ytd_tax": sum(LOHNSTEUER.values(), Decimal(0)),
    }


def _gehalt(letter: Letter) -> None:
    n = _payslip_numbers()
    letter.address(sam.recipient(), note="Persönlich / Vertraulich")
    letter.info(
        [
            ("Personalnummer", sam.PERSONALNUMMER),
            ("Abrechnung", "August 2026"),
            ("Eintritt", "01.04.2026"),
            ("Steuerklasse", "1 · Kinderfreibeträge 0,0"),
            ("Konfession", "keine"),
            ("Datum", "31.08.2026"),
        ]
    )
    letter.subject("Verdienstabrechnung August 2026", sub="Abrechnungszeitraum 01.08.2026 – 31.08.2026")
    letter.kv(
        [
            ("Steuer-ID", sam.STEUER_ID),
            ("SV-Nummer", sam.RV_NUMMER),
            ("Krankenkasse", "Muster BKK (Studierende, eigene Versicherung)"),
            ("Beitragsgruppe / Personengruppe", "0-1-0-0 / 106 (Werkstudent)"),
        ],
        key_w=58,
        size=8.2,
        borders="HORIZONTAL_LINES",
        gap=3,
    )
    head = tint(MUSTERTECH.color, 0.9)
    letter.table(
        [
            ("Lohnart", "Bezeichnung", "Menge", "Faktor", "Betrag"),
            ("1000", "Stundenlohn Werkstudent", "86,00 Std.", eur(RATE), eur(n["gross"])),
            ("", "**Gesamtbrutto**", "", "", f"**{eur(n['gross'])}**"),
        ],
        (18, 72, 25, 22, 28),
        aligns=("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
        head_fill=head,
        gap=3,
    )
    letter.table(
        [
            ("Steuer- und Sozialversicherungsabzüge", "Bemessung", "Abzug"),
            ("Lohnsteuer (Steuerklasse 1)", eur(n["gross"]), eur(n["tax"])),
            ("Solidaritätszuschlag", eur(n["gross"]), eur(0)),
            ("Kirchensteuer", "–", eur(0)),
            ("Rentenversicherung Arbeitnehmeranteil (9,3 %)", eur(n["gross"]), eur(n["rv"])),
            ("Kranken-, Pflege- und Arbeitslosenversicherung", "versicherungsfrei", eur(0)),
            ("**Summe gesetzliche Abzüge**", "", f"**{eur(n['rv'] + n['tax'])}**"),
        ],
        (107, 30, 28),
        aligns=("LEFT", "RIGHT", "RIGHT"),
        head_fill=head,
        gap=3,
    )
    letter.table(
        [
            ("Auszahlung", "Betrag"),
            ("**Nettoverdienst**", f"**{eur(n['net'])}**"),
            (f"Überweisung am 31.08.2026 an IBAN {sam.IBAN_PRETTY} (Musterbank eG)", eur(n["net"])),
            ("**Auszahlungsbetrag**", f"**{eur(n['net'])}**"),
        ],
        (137, 28),
        aligns=("LEFT", "RIGHT"),
        head_fill=head,
        gap=3,
    )
    letter.table(
        [
            ("Jahreswerte 2026", "Steuer-Brutto", "Lohnsteuer", "Soli", "RV-Brutto", "RV-AN"),
            (
                "April – August",
                eur(n["ytd_gross"]),
                eur(n["ytd_tax"]),
                eur(0),
                eur(n["ytd_gross"]),
                eur(n["ytd_rv"]),
            ),
        ],
        (35, 28, 24, 18, 28, 32),
        aligns=("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
        size=8.0,
        head_fill=tint(MUSTERTECH.accent, 0.22),
        head_text=MUSTERTECH.color,
        gap=3,
    )
    letter.small(
        f"Arbeitgeberanteil Rentenversicherung: {eur(n['rv'])}. Werkstudierende sind in der Kranken-, "
        "Pflege- und Arbeitslosenversicherung versicherungsfrei (§ 6 Abs. 1 Nr. 3 SGB V, § 27 Abs. 4 "
        "SGB III). Bitte bewahren Sie diese Abrechnung auf; sie dient z. B. als Einkommensnachweis."
    )


def gehaltsabrechnung() -> Sample:
    """Payslip August 2026, Muster Tech GmbH, 31.08.2026."""
    n = _payslip_numbers()
    dc.expect(n["gross"] == money("1419.00") and n["rv"] == money("131.97"), "gross and RV")
    dc.expect(n["net"] == money("1285.20"), "net pay")
    dc.expect(n["ytd_gross"] == money("6864.00") and n["ytd_rv"] == money("638.36"), "year to date")
    truth = Truth(
        kind="payslip",
        area="work",
        sender_name="Muster Tech GmbH",
        sender_kind="employer",
        document_date="2026-08-31",
        references=[Ref("Personalnummer", sam.PERSONALNUMMER)],
        amounts=[
            Amount("Gesamtbrutto", float(n["gross"])),
            Amount("Lohnsteuer", float(n["tax"])),
            Amount("Rentenversicherung AN", float(n["rv"])),
            Amount("Nettoverdienst", float(n["net"])),
            Amount("Auszahlungsbetrag", float(n["net"])),
        ],
        items=[
            TruthItem(
                kind="payment",
                title_hint="August salary paid",
                expected_due="2026-08-31",
                date_basis="fixed",
                nature="payment",
                amount=float(n["net"]),
                direction="in",
                quote=f"Überweisung am 31.08.2026 an IBAN {sam.IBAN_PRETTY} (Musterbank eG)",
                reasoning="Already paid on the document date; informational.",
                optional=True,
            ),
        ],
        key_quotes=["Verdienstabrechnung August 2026", "Nettoverdienst", "Steuerklasse"],
        tax_relevant=True,
        related=[("arbeitsvertrag_werkstudent", "employment contract")],
        notes="Werkstudent: only pension insurance (9,3 %); Lohnsteuer is tiny at this income. Gross 1.419,00 €, "
        "net 1.285,20 €.",
    )
    return Sample(
        slug="gehaltsabrechnung_2026_08",
        title="Verdienstabrechnung August 2026",
        language="de",
        received_date=dc.checked("2026-09-02", "Wed"),
        render=lambda: as_pdf(
            letter_pdf(MUSTERTECH, "2026-08-31", _gehalt, follow_ref="Verdienstabrechnung 08/2026")
        ),
        truth=truth,
        subject_hint="Gehaltsabrechnung August",
    )


# --------------------------------------------------------------------------------------------------
# Hochschule Musterstadt: Semesterunterlagen + Rückmeldung SoSe 2027 (01.09.2026)
# --------------------------------------------------------------------------------------------------

FEE = money("312.40")
FEE_PARTS = [
    ("Sozialbeitrag Studierendenwerk Musterstadt", money("68.00")),
    ("Beitrag der Studierendenschaft", money("17.60")),
    ("Deutschlandsemesterticket (6 × 37,80 €)", money("226.80")),
]
FEE_QUOTE = (
    "Der Semesterbeitrag in Höhe von 312,40 € muss bis spätestens zum 15.01.2027 auf dem unten genannten Konto der "
    "Hochschule eingegangen sein."
)
TICKET_QUOTE = (
    "Falls Sie ein Deutschlandticket im Abonnement besitzen, denken Sie bitte daran, dieses rechtzeitig zum "
    "31.03.2027 zu kündigen."
)


def _rueckmeldung(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [
            ("Matrikelnummer", sam.MATRIKEL),
            ("Studiengang", "Data Science (M.Sc.)"),
            ("Ihr Kontakt", "Studierendenservice"),
            ("Telefon", "0123 7788-2210"),
            ("Datum", "01.09.2026"),
        ]
    )
    letter.subject("Semesterunterlagen Wintersemester 2026/27 und Rückmeldung zum Sommersemester 2027")
    letter.para(SALUTE_DE)
    letter.para(
        "Ihre Rückmeldung zum Wintersemester 2026/27 ist abgeschlossen. Anbei erhalten Sie Ihre "
        "Immatrikulationsbescheinigung."
    )
    letter.heading("Rückmeldung zum Sommersemester 2027")
    letter.para(
        "Die Rückmeldung zum Sommersemester 2027 erfolgt ausschließlich durch die fristgerechte Zahlung des "
        f"Semesterbeitrags. Der Rückmeldezeitraum beginnt am 01.12.2026. {FEE_QUOTE}"
    )
    rows = [("Zusammensetzung des Semesterbeitrags", "Betrag")]
    rows += [(label, eur(value)) for label, value in FEE_PARTS]
    rows.append(("**Semesterbeitrag Sommersemester 2027**", f"**{eur(FEE)}**"))
    letter.table(rows, (130, 35), aligns=("LEFT", "RIGHT"), head_fill=HOCHSCHULE.color, gap=2.5)
    letter.box(
        [
            f"Empfänger: Hochschule Musterstadt · IBAN {ACC_HOCHSCHULE.iban_pretty} · BIC {ACC_HOCHSCHULE.bank.bic}",
            f"Verwendungszweck (bitte unbedingt angeben): **{sam.MATRIKEL} SoSe 2027**",
        ],
        title="Zahlungsangaben",
        gap=2.5,
    )
    letter.para(
        "Bei späterem Zahlungseingang wird eine Säumnisgebühr von 15,00 € erhoben. Ohne fristgerechte "
        "Rückmeldung droht die Exmatrikulation (§ 51 Abs. 2 HG NRW)."
    )
    letter.heading("Neu: Deutschlandsemesterticket ab dem Sommersemester 2027")
    letter.para(
        "Nach der Urabstimmung der Studierendenschaft ist ab dem Sommersemester 2027 das "
        "Deutschlandsemesterticket im Semesterbeitrag enthalten (gültig 01.04.–30.09.2027). "
        f"{TICKET_QUOTE}"
    )
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Ihr Studierendenservice",
        scribble=False,
        note="Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift gültig.",
    )


def rueckmeldung() -> Sample:
    """University letter: semester documents and re-registration for SoSe 2027, 01.09.2026."""
    dc.expect(sum((v for _l, v in FEE_PARTS), Decimal(0)) == FEE, "fee parts add up")
    truth = Truth(
        kind="university",
        area="study",
        sender_name="Hochschule Musterstadt",
        sender_kind="university",
        document_date="2026-09-01",
        references=[Ref("Matrikelnummer", sam.MATRIKEL)],
        amounts=[Amount("Semesterbeitrag Sommersemester 2027", float(FEE)), Amount("Säumnisgebühr", 15.0)],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Pay the semester fee to re-register for summer 2027",
                expected_due=dc.checked("2027-01-15", "Fri"),
                date_basis="fixed",
                nature="payment",
                amount=float(FEE),
                direction="out",
                quote=FEE_QUOTE,
                reasoning="Explicit date 15.01.2027 (Friday); the payment must have arrived by then.",
            ),
            TruthItem(
                kind="milestone",
                title_hint="Re-registration period opens",
                expected_due=dc.checked("2026-12-01", "Tue"),
                date_basis="fixed",
                nature="other",
                quote="Der Rückmeldezeitraum beginnt am 01.12.2026.",
                reasoning="Explicit date.",
                optional=True,
            ),
            TruthItem(
                kind="task",
                title_hint="Cancel the Deutschlandticket subscription for end of March 2027",
                expected_due=None,
                date_basis="none",
                nature="notice",
                quote=TICKET_QUOTE,
                reasoning="Conditional advice; with the MVB subscription (by the 10th for month end) the deadline "
                "would be 10.03.2027.",
                optional=True,
            ),
        ],
        payment=TruthPayment(ACC_HOCHSCHULE.iban, "Hochschule Musterstadt", f"{sam.MATRIKEL} SoSe 2027"),
        key_quotes=[FEE_QUOTE, TICKET_QUOTE],
        related=[
            ("immatrikulationsbescheinigung_wise_2026", "enclosed certificate"),
            ("deutschlandticket_abo", "subscription made redundant by the semester ticket"),
        ],
    )
    return Sample(
        slug="rueckmeldung_sose_2027",
        title="Semesterunterlagen und Rückmeldung SoSe 2027",
        language="de",
        received_date=dc.checked("2026-09-03", "Thu"),
        render=lambda: as_pdf(
            letter_pdf(HOCHSCHULE, "2026-09-01", _rueckmeldung, follow_ref=f"Matrikelnummer {sam.MATRIKEL}")
        ),
        truth=truth,
        subject_hint="Rückmeldung Sommersemester 2027",
    )


# --------------------------------------------------------------------------------------------------
# Immatrikulationsbescheinigung WiSe 2026/27 (01.09.2026)
# --------------------------------------------------------------------------------------------------

ENROL_QUOTE = (
    "Herr Sam Rivera ist im Wintersemester 2026/27 an der Hochschule Musterstadt als ordentlicher Studierender "
    "eingeschrieben."
)


def _immatrikulation(letter: Letter) -> None:
    pdf = letter.pdf
    letter.title(
        "Immatrikulationsbescheinigung",
        size=17,
        y=46,
        align="C",
        sub="Certificate of Enrolment · Wintersemester 2026/27 (01.10.2026 – 31.03.2027)",
    )
    letter.space(2)
    letter.kv(
        [
            ("Name, Vorname / Name", "Rivera, Sam"),
            ("Geburtsdatum / Date of birth", "14.03.2000"),
            ("Geburtsort / Place of birth", f"{sam.BIRTH_PLACE} (Republic of Examplia)"),
            ("Matrikelnummer / Student ID", sam.MATRIKEL),
            ("Semester / Term", "Wintersemester 2026/27 (01.10.2026 – 31.03.2027)"),
            ("Studiengang / Programme", "Data Science, Master of Science (M.Sc.)"),
            ("Fachsemester / Semester of study", "5"),
            ("Hochschulsemester / University semesters", "5"),
            ("Studienform / Mode of study", "Vollzeitstudium, Präsenzstudium / full-time"),
            ("Status", "ordentlich eingeschrieben, zurückgemeldet / enrolled"),
            ("Urlaubssemester / Leave of absence", "nein / no"),
        ],
        key_w=72,
        size=9.0,
        borders="HORIZONTAL_LINES",
        zebra=True,
        gap=5,
    )
    letter.para(ENROL_QUOTE, gap=1.5)
    letter.para(
        "Mr Sam Rivera is enrolled as a regular student at Hochschule Musterstadt in the winter semester "
        "2026/27.",
        color=GREY,
        gap=6,
    )
    y = pdf.get_y() + 26
    letter.para("Musterstadt, 01.09.2026", gap=1)
    letter.para("Der Präsident der Hochschule Musterstadt – Studierendenservice", size=8.4, color=GREY, gap=8)
    with pdf.local_context():
        pdf.set_draw_color(*HOCHSCHULE.color)
        pdf.set_line_width(0.5)
        pdf.ellipse(150, y - 26, 26, 26)
        pdf.set_line_width(0.2)
        pdf.ellipse(152, y - 24, 22, 22)
        pdf.set_font("dejavu", "B", 6.2)
        pdf.set_text_color(*HOCHSCHULE.color)
        pdf.set_xy(150, y - 16)
        pdf.cell(26, 3, "HOCHSCHULE", align="C")
        pdf.set_xy(150, y - 13)
        pdf.cell(26, 3, "MUSTERSTADT", align="C")
    pdf.set_y(max(pdf.get_y(), y + 4))
    letter.small(
        "Diese Bescheinigung wurde maschinell erstellt und ist ohne Unterschrift gültig. Prüfcode: "
        "HM-2026-9F3K-77QX – Echtheitsprüfung unter hs-musterstadt.example/verify."
    )


def immatrikulationsbescheinigung() -> Sample:
    """Certificate of enrolment for the winter semester 2026/27, 01.09.2026."""
    truth = Truth(
        kind="certificate",
        area="study",
        sender_name="Hochschule Musterstadt",
        sender_kind="university",
        document_date="2026-09-01",
        references=[Ref("Matrikelnummer", sam.MATRIKEL), Ref("Prüfcode", "HM-2026-9F3K-77QX")],
        amounts=[],
        items=[
            TruthItem(
                kind="expiry",
                title_hint="Enrolment certificate valid until end of winter semester",
                expected_due=dc.checked("2027-03-31", "Wed"),
                date_basis="fixed",
                nature="other",
                quote="Wintersemester 2026/27 (01.10.2026 – 31.03.2027)",
                reasoning="The certificate covers the semester ending 31.03.2027.",
                optional=True,
            ),
        ],
        key_quotes=[ENROL_QUOTE, "Immatrikulationsbescheinigung"],
        kind_alternatives=["university"],
        related=[("rueckmeldung_sose_2027", "cover letter")],
        notes="Needed for the residence-permit appointment and the employer.",
    )
    return Sample(
        slug="immatrikulationsbescheinigung_wise_2026",
        title="Immatrikulationsbescheinigung WiSe 2026/27",
        language="de",
        received_date=dc.checked("2026-09-03", "Thu"),
        render=lambda: as_pdf(letter_pdf(HOCHSCHULE, "2026-09-01", _immatrikulation, fold_marks=False)),
        truth=truth,
        subject_hint="Immatrikulationsbescheinigung",
    )


# --------------------------------------------------------------------------------------------------
# Global Talent Scholarship Foundation (English, 05.09.2026)
# --------------------------------------------------------------------------------------------------

REPORT_QUOTE = (
    "Your first progress report is due on 15 December 2026. Please submit it through the scholarship portal using "
    "the template provided there."
)
ADDRESS_QUOTE = (
    "Please notify us of any change of address, bank details or study status within two weeks of the change."
)
STIPEND_QUOTE = (
    "The monthly stipend of EUR 450.00 will be paid from October 2026 to September 2027 by bank transfer on or "
    "around the first working day of each month."
)


def _stipendium(letter: Letter) -> None:
    letter.address(sam.recipient(english=True))
    letter.info(
        [
            ("Scholarship ID", "GTSF-2026-0317"),
            ("Contact", "Dr. Helen Example"),
            ("Phone", SCHOLARSHIP.phone),
            ("Date", "5 September 2026"),
        ]
    )
    letter.subject("Award of the Global Talent Scholarship 2026/27")
    letter.para(SALUTE_EN)
    letter.para(
        "On behalf of the Selection Committee, I am delighted to inform you that you have been awarded a "
        "Global Talent Scholarship for the academic year 2026/27. The Committee was particularly impressed "
        "by your academic record and by the data-literacy workshops you co-organise for students at "
        "Hochschule Musterstadt."
    )
    letter.heading("Scholarship details")
    letter.bullets(
        [
            STIPEND_QUOTE,
            "Funding period: 1 October 2026 – 30 September 2027 (12 months).",
            "Scholarship ID: GTSF-2026-0317 (please quote it in all correspondence).",
        ]
    )
    letter.heading("Conditions")
    letter.bullets(
        [
            "You remain enrolled as a full-time student at Hochschule Musterstadt throughout the funding period and "
            "upload your certificate of enrolment for each semester to the scholarship portal.",
            f"{REPORT_QUOTE} The report (max. two pages) must be countersigned by your academic supervisor.",
            ADDRESS_QUOTE,
            "Other scholarships or grants must be reported to us before you accept them.",
        ],
        numbered=True,
    )
    letter.para(
        "The scholarship is granted to cover living costs while studying. It is generally tax-free under "
        "§ 3 No. 44 of the German Income Tax Act (EStG); please keep this letter for your records."
    )
    letter.para(
        "We look forward to welcoming you to our scholar community at the Autumn Meeting in Berlin on "
        "7 November 2026. A separate invitation with the programme will follow."
    )
    letter.closing("Yours sincerely,", signers=[("Dr. Helen Example", "Programme Director")])


def stipendium() -> Sample:
    """Scholarship award letter in English, Global Talent Scholarship Foundation, 05.09.2026."""
    truth = Truth(
        kind="other",
        area="study",
        sender_name="Global Talent Scholarship Foundation",
        sender_kind="other",
        document_date="2026-09-05",
        references=[Ref("Scholarship ID", "GTSF-2026-0317")],
        amounts=[Amount("Monthly stipend", 450.0)],
        items=[
            TruthItem(
                kind="deadline",
                title_hint="Submit the first scholarship progress report",
                expected_due=dc.checked("2026-12-15", "Tue"),
                date_basis="fixed",
                nature="declaration",
                quote=REPORT_QUOTE,
                reasoning="Explicit date 15 December 2026 (Tuesday).",
            ),
            TruthItem(
                kind="payment",
                title_hint="Monthly stipend 450 €",
                expected_due="2026-10-01",
                date_basis="fixed",
                nature="payment",
                recurrence="monthly",
                amount=450.0,
                direction="in",
                quote=STIPEND_QUOTE,
                reasoning="Paid around the first working day of each month from October 2026 (Thu 01.10.2026).",
                optional=True,
            ),
            TruthItem(
                kind="appointment",
                title_hint="Scholars' Autumn Meeting in Berlin",
                expected_due=dc.checked("2026-11-07", "Sat"),
                date_basis="fixed",
                nature="appointment",
                quote="Autumn Meeting in Berlin on 7 November 2026",
                reasoning="Explicit date; no time given yet.",
                location="Berlin",
                optional=True,
            ),
            TruthItem(
                kind="task",
                title_hint="Report address/bank/study changes within two weeks",
                expected_due=None,
                date_basis="none",
                nature="declaration",
                quote=ADDRESS_QUOTE,
                reasoning="Conditional obligation (two weeks after a change); no date until something changes.",
                optional=True,
            ),
        ],
        key_quotes=[REPORT_QUOTE, ADDRESS_QUOTE, STIPEND_QUOTE],
        kind_alternatives=["university", "personal", "certificate"],
        notes="English letter; stipend counts as proof of funds for the residence permit.",
    )
    return Sample(
        slug="stipendium_zusage",
        title="Award of the Global Talent Scholarship 2026/27",
        language="en",
        received_date=dc.checked("2026-09-07", "Mon"),
        render=lambda: as_pdf(
            letter_pdf(
                SCHOLARSHIP, "2026-09-05", _stipendium, lang="en", follow_ref="Scholarship ID GTSF-2026-0317"
            )
        ),
        truth=truth,
        subject_hint="Scholarship award",
    )
