"""Home: the lease, the service-charge statement and the electricity contract (+ price increase)."""

from __future__ import annotations

from decimal import Decimal

from samplelife import datecheck as dc
from samplelife import persona as sam
from samplelife.common import SALUTE_DE, as_pdf, letter_pdf
from samplelife.fmt import de_num, eur, money
from samplelife.letter import GREY, Letter
from samplelife.orgs import ACC_WOHNBAU, STADTWERKE, WOHNBAU
from samplelife.truth import (
    Amount,
    Ref,
    Sample,
    Truth,
    TruthChange,
    TruthContract,
    TruthItem,
    TruthPayment,
)

MV_NR = "MV-2025-0412"
WOHNUNG = "05-2-03"
VERTRAGSKONTO = "400123987"
KUNDENNR_SW = "2004711"
ZAEHLER = "1EMH0012345678"
MALO = "51238764017"


# --------------------------------------------------------------------------------------------------
# Mietvertrag (lease), signed 15.09.2025
# --------------------------------------------------------------------------------------------------

RENT_QUOTE = (
    "Die Gesamtmiete ist monatlich im Voraus, spätestens bis zum dritten Werktag eines jeden Monats, "
    "kostenfrei auf das Konto der Vermieterin zu zahlen."
)
LEASE_NOTICE_QUOTE = (
    "Der Mieter kann das Mietverhältnis spätestens am dritten Werktag eines Kalendermonats zum Ablauf des "
    "übernächsten Monats kündigen (§ 573c Abs. 1 BGB)."
)


def _lease(letter: Letter) -> None:
    pdf = letter.pdf
    letter.size = 8.8
    letter.lh = 8.8 * 0.47
    letter.title("Mietvertrag über Wohnraum", sub=f"Vertragsnummer {MV_NR} · Wohnung Nr. {WOHNUNG}", y=45)

    def section(title: str, clauses: list[str]) -> None:
        letter.heading(title, size=9.2, gap=0.6)
        for clause in clauses:
            letter.para(clause, gap=1.1, align="J")
        pdf.ln(0.8)

    letter.para("Zwischen", gap=0.6)
    letter.para(
        "**Wohnbau Musterstadt eG**, Genossenschaftsstraße 10, 12345 Musterstadt, vertreten durch den "
        "Vorstand – nachstehend „Vermieterin“ –",
        indent=6,
        gap=0.8,
    )
    letter.para("und", gap=0.6)
    letter.para(
        f"**Herrn {sam.NAME}**, geb. 14.03.2000, derzeit wohnhaft {sam.OLD_STREET}, {sam.OLD_CITY} – "
        "nachstehend „Mieter“ –",
        indent=6,
        gap=0.8,
    )
    letter.para("wird folgender Mietvertrag geschlossen:", gap=2.2)

    section(
        "§ 1 Mietsache",
        [
            "(1) Vermietet wird die Wohnung im Hause Beispielweg 5, 12345 Musterstadt, 2. Obergeschoss links, "
            f"Wohnungsnummer {WOHNUNG}, bestehend aus 2 Zimmern, Küche, Diele, Bad mit WC und Balkon. Die Wohnfläche "
            "beträgt ca. 48,6 m².",
            "(2) Mitvermietet wird der Kellerraum Nr. 7. Der Mieter ist berechtigt, den Wasch- und Trockenraum "
            "gemeinschaftlich mit den anderen Mietparteien zu nutzen.",
            "(3) Dem Mieter werden bei Übergabe ausgehändigt: 2 Haus- und Wohnungsschlüssel, 1 Briefkastenschlüssel, "
            "1 Kellerschlüssel.",
        ],
    )
    section(
        "§ 2 Mietzeit und Kündigung",
        [
            "(1) Das Mietverhältnis beginnt am 01.10.2025 und läuft auf unbestimmte Zeit.",
            "(2) Die Kündigung bedarf der Schriftform (§ 568 Abs. 1 BGB). " + LEASE_NOTICE_QUOTE + " Für die "
            "Rechtzeitigkeit der Kündigung kommt es auf den Zugang bei der Vermieterin an.",
            "(3) Für die Kündigung durch die Vermieterin gelten die gesetzlichen Bestimmungen (§§ 573, 573c BGB).",
            "(4) Setzt der Mieter den Gebrauch der Mietsache nach Ablauf der Mietzeit fort, gilt das Mietverhältnis "
            "nicht als verlängert; § 545 BGB findet keine Anwendung.",
        ],
    )
    letter.heading("§ 3 Miete und Betriebskosten", size=9.2, gap=0.6)
    letter.para("(1) Die Miete beträgt monatlich:", gap=0.8)
    letter.table(
        [
            ("Grundmiete (Nettokaltmiete)", eur(520)),
            ("Vorauszahlung Betriebskosten (ohne Heizung und Warmwasser)", eur(70)),
            ("Vorauszahlung Heiz- und Warmwasserkosten", eur(50)),
            ("**Gesamtmiete**", f"**{eur(640)}**"),
        ],
        (120, 35),
        aligns=("LEFT", "RIGHT"),
        header=False,
        indent=6,
        gap=2.0,
    )
    for clause in [
        "(2) Über die Vorauszahlungen wird jährlich abgerechnet; Abrechnungszeitraum ist das Kalenderjahr. Umgelegt "
        "werden die Betriebskosten im Sinne des § 2 der Betriebskostenverordnung (BetrKV) nach dem Verhältnis der "
        "Wohnflächen; die Heiz- und Warmwasserkosten werden nach der Heizkostenverordnung verteilt.",
        "(3) Nach einer Abrechnung kann jede Vertragspartei durch Erklärung in Textform eine Anpassung der "
        "Vorauszahlungen auf eine angemessene Höhe vornehmen (§ 560 Abs. 4 BGB).",
    ]:
        letter.para(clause, gap=1.1, align="J")
    pdf.ln(0.8)
    section(
        "§ 4 Zahlung der Miete",
        [
            f"(1) {RENT_QUOTE} Bankverbindung: {ACC_WOHNBAU.bank.name}, IBAN {ACC_WOHNBAU.iban_pretty}, "
            f"BIC {ACC_WOHNBAU.bank.bic}, Verwendungszweck: {MV_NR}.",
            "(2) Für die Rechtzeitigkeit der Zahlung kommt es nicht auf die Absendung, sondern auf den Eingang des "
            "Geldes bei der Vermieterin an. Der Mieter kann der Vermieterin ein SEPA-Lastschriftmandat erteilen.",
        ],
    )
    section(
        "§ 5 Mietsicherheit",
        [
            "(1) Der Mieter leistet eine Mietsicherheit (Kaution) in Höhe von 1.560,00 € (drei Nettokaltmieten).",
            "(2) Der Mieter ist berechtigt, die Mietsicherheit in drei gleichen monatlichen Teilzahlungen zu erbringen. "
            "Die erste Teilzahlung ist zu Beginn des Mietverhältnisses fällig, die weiteren Teilzahlungen werden "
            "zusammen mit den unmittelbar folgenden Mietzahlungen fällig (§ 551 Abs. 2 BGB).",
            "(3) Die Vermieterin legt die Mietsicherheit getrennt von ihrem Vermögen bei einem Kreditinstitut zu dem "
            "für Spareinlagen mit dreimonatiger Kündigungsfrist üblichen Zinssatz an.",
        ],
    )
    section(
        "§ 6 Instandhaltung und Schönheitsreparaturen",
        [
            "(1) Die Wohnung wird in renoviertem Zustand übergeben; ihr Zustand wird bei der Übergabe in einem "
            "gemeinsamen Protokoll festgehalten.",
            "(2) Die Kosten für kleine Instandhaltungen an Teilen der Mietsache, die dem häufigen Zugriff des Mieters "
            "ausgesetzt sind, trägt der Mieter bis zu 100,00 € im Einzelfall, höchstens jedoch 8 % der "
            "Jahresnettokaltmiete.",
            "(3) Schäden an der Mietsache hat der Mieter der Vermieterin unverzüglich anzuzeigen.",
        ],
    )
    section(
        "§ 7 Untervermietung und Tierhaltung",
        [
            "(1) Eine Untervermietung oder sonstige Gebrauchsüberlassung an Dritte bedarf der vorherigen Erlaubnis "
            "der Vermieterin (§ 540 BGB).",
            "(2) Die Haltung von Kleintieren ist erlaubt. Die Haltung anderer Tiere bedarf der Zustimmung der "
            "Vermieterin, die nur aus wichtigem Grund verweigert werden darf.",
        ],
    )
    section(
        "§ 8 Hausordnung und sonstige Vereinbarungen",
        [
            "(1) Die beigefügte Hausordnung ist Bestandteil dieses Vertrags.",
            "(2) Der Energieausweis (Verbrauchsausweis, Endenergieverbrauch 112 kWh/(m²·a), Energieträger Erdgas) "
            "wurde dem Mieter vor Vertragsschluss vorgelegt.",
            "(3) Der Mieter wurde auf die Möglichkeit hingewiesen, Mitglied der Genossenschaft zu werden. Änderungen "
            "und Ergänzungen dieses Vertrags bedürfen der Textform.",
        ],
    )
    letter.space(2)
    letter.signature_fields(
        ("Musterstadt, 15.09.2025", "Wohnbau Musterstadt eG (Vermieterin)", "wohnbau:petra-beispiel"),
        ("Musterstadt, 15.09.2025", "Sam Rivera (Mieter)", "sam:lease"),
        stamp_left=("Wohnbau Musterstadt eG", "Genossenschaftsstraße 10", "12345 Musterstadt"),
    )
    letter.enclosures(
        ["Hausordnung", "Energieausweis (Kopie)", "Übergabeprotokoll (wird bei Übergabe erstellt)"]
    )


def mietvertrag() -> Sample:
    """Lease with Wohnbau Musterstadt eG, signed 15.09.2025, start 01.10.2025."""
    # Next rent payment after the simulated today (Mon 28.09.2026): the October 2026 instalment.
    # "bis zum dritten Werktag": Thu 01.10. (1), Fri 02.10. (2), Sat 03.10. is a public holiday (Tag der
    # Deutschen Einheit), Sun 04.10., Mon 05.10. (3). Whether Saturdays count or not (BGH VIII ZR 222/15
    # excludes them for rent payments) the answer is Mon 05.10.2026.
    dc.expect(not dc.is_werktag("2026-10-03"), "03.10. is a holiday")
    rent_due = dc.checked("2026-10-05", "Mon")
    # Tenant notice (§ 573c Abs. 1 BGB): received by the 3rd Werktag of a month → end of the month after next.
    # September's 3rd Werktag (Thu 03.09.) has passed; October's is Mon 05.10.2026 (see above) → exit 31.12.2026.
    cancel_by = rent_due
    exit_date = dc.checked("2026-12-31", "Thu")
    truth = Truth(
        kind="rent_lease",
        area="home",
        sender_name="Wohnbau Musterstadt eG",
        sender_kind="landlord",
        document_date="2025-09-15",
        references=[Ref("Vertragsnummer", MV_NR), Ref("Wohnung Nr.", WOHNUNG)],
        amounts=[
            Amount("Grundmiete (Nettokaltmiete)", 520.0),
            Amount("Vorauszahlung Betriebskosten", 70.0),
            Amount("Vorauszahlung Heiz- und Warmwasserkosten", 50.0),
            Amount("Gesamtmiete", 640.0),
            Amount("Mietsicherheit (Kaution)", 1560.0),
        ],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Monthly rent (Gesamtmiete)",
                expected_due=rent_due,
                date_basis="relative",
                nature="payment",
                recurrence="monthly",
                amount=640.0,
                direction="out",
                quote=RENT_QUOTE,
                reasoning="Recurring: due by the 3rd Werktag of each month. Next instalment after 2026-09-28 is "
                "October: Thu 01.10 (1), Fri 02.10 (2), Sat 03.10 is a public holiday, Mon 05.10 (3) → 2026-10-05.",
            ),
        ],
        contract=TruthContract(
            name="Mietvertrag Beispielweg 5, 2. OG links",
            category="rent",
            regime="rent573c",
            customer_number=MV_NR,
            concluded_date="2025-09-15",
            start_date="2025-10-01",
            initial_term_months=None,
            renewal_term_months=0,
            notice_value=3,
            notice_unit="months",
            notice_basis="end_of_month",
            end_date=None,
            cost_amount=640.0,
            cost_interval="monthly",
            expected_current_term_end=None,
            expected_cancel_by=cancel_by,
            expected_earliest_exit=exit_date,
            reasoning="§ 573c Abs. 1 BGB: notice received by the 3rd Werktag of a month ends the lease at the end "
            "of the month after next. The September window closed on Thu 03.09.2026; October's 3rd Werktag is "
            "Mon 05.10.2026 (03.10. is a holiday) → lease ends 31.12.2026. Written form with signature (§ 568 BGB).",
        ),
        payment=TruthPayment(ACC_WOHNBAU.iban, "Wohnbau Musterstadt eG", MV_NR),
        key_quotes=[RENT_QUOTE, LEASE_NOTICE_QUOTE, "Das Mietverhältnis beginnt am 01.10.2025"],
        related=[("nebenkostenabrechnung_2025", "service-charge statement for this lease")],
    )
    return Sample(
        slug="mietvertrag",
        title="Mietvertrag Beispielweg 5",
        language="de",
        received_date="2025-09-15",
        render=lambda: as_pdf(letter_pdf(WOHNBAU, "2025-09-15", _lease, follow_ref=f"Mietvertrag {MV_NR}")),
        truth=truth,
        subject_hint="Mietvertrag über Wohnraum",
    )


# --------------------------------------------------------------------------------------------------
# Stadtwerke: Vertragsbestätigung (20.09.2025)
# --------------------------------------------------------------------------------------------------

SW_TERM_QUOTE = (
    "Der Vertrag hat eine Erstlaufzeit von 12 Monaten ab Lieferbeginn. Er kann mit einer Frist von einem Monat "
    "zum Ende der Erstlaufzeit gekündigt werden."
)
SW_AFTER_QUOTE = (
    "Wird der Vertrag nicht gekündigt, läuft er nach Ablauf der Erstlaufzeit auf unbestimmte Zeit weiter und kann "
    "dann jederzeit mit einer Frist von einem Monat gekündigt werden."
)


def _stadtwerke_contract(letter: Letter) -> None:
    letter.address(sam.recipient(old=True))
    letter.info(
        [
            ("Vertragskonto", VERTRAGSKONTO),
            ("Kundennummer", KUNDENNR_SW),
            ("Ihr Auftrag vom", "16.09.2025"),
            ("Kundenservice", "0123 5550-100"),
            ("Datum", "20.09.2025"),
        ]
    )
    letter.subject(
        "Ihr Stromliefervertrag „MusterStrom Flex“ – Vertragsbestätigung",
        sub=f"Lieferstelle: Beispielweg 5, 12345 Musterstadt · Vertragskonto {VERTRAGSKONTO}",
    )
    letter.para(SALUTE_DE)
    letter.para(
        "herzlichen Dank für Ihren Auftrag vom 16.09.2025 und willkommen bei den Stadtwerken Musterstadt! "
        "Gern bestätigen wir Ihnen die Belieferung Ihrer neuen Wohnung mit Strom zu den folgenden "
        "Bedingungen:"
    )
    letter.kv(
        [
            ("Lieferstelle", "Beispielweg 5, 12345 Musterstadt, 2. OG links"),
            ("Zählernummer / Marktlokation", f"{ZAEHLER} / {MALO}"),
            ("Tarif", "MusterStrom Flex (100 % Ökostrom aus Wasserkraft)"),
            ("Lieferbeginn", "01.10.2025"),
            ("Erstlaufzeit", "12 Monate (bis 30.09.2026)"),
            ("Arbeitspreis", "32,90 ct/kWh (brutto) · 27,65 ct/kWh (netto)"),
            ("Grundpreis", "11,90 €/Monat (brutto) · 10,00 €/Monat (netto)"),
            ("Voraussichtlicher Jahresverbrauch", "1.320 kWh"),
            ("Monatlicher Abschlag", "48,00 €, fällig jeweils zum 15. eines Monats, erstmals am 15.10.2025"),
            ("Zahlungsweise", f"SEPA-Lastschrift von Ihrem Konto {sam.IBAN_MASKED}"),
        ],
        key_w=58,
        bold_keys=True,
        zebra=True,
        gap=3,
    )
    letter.heading("Laufzeit und Kündigung")
    letter.para(
        f"{SW_TERM_QUOTE} {SW_AFTER_QUOTE} Die Kündigung bedarf der Textform (z. B. E-Mail); Sie können "
        "auch den Button „Vertrag kündigen“ in unserem Kundenportal nutzen."
    )
    letter.heading("Preisänderungen")
    letter.para(
        "Änderungen der Preise teilen wir Ihnen mindestens einen Monat vor ihrem Wirksamwerden in Textform "
        "mit. In diesem Fall haben Sie das Recht, den Vertrag ohne Einhaltung einer Kündigungsfrist zum "
        "Zeitpunkt des Wirksamwerdens der Änderung zu kündigen (§ 41 Abs. 5 EnWG)."
    )
    letter.heading("Zählerstand")
    letter.para(
        "Bitte teilen Sie uns den Zählerstand zum Lieferbeginn bis zum 05.10.2025 mit – am einfachsten "
        "online unter stadtwerke-musterstadt.example/zaehlerstand oder mit der beiliegenden Karte."
    )
    letter.closing(
        "Freundliche Grüße",
        org_line="Ihre Stadtwerke Musterstadt GmbH",
        signers=[("Jana Beispiel", "Kundenservice Privatkunden")],
    )
    letter.enclosures(
        ["Allgemeine Geschäftsbedingungen MusterStrom Flex", "Stromkennzeichnung 2024", "Zählerstandskarte"]
    )


def stadtwerke_vertrag() -> Sample:
    """Electricity contract confirmation, Stadtwerke Musterstadt GmbH, 20.09.2025."""
    # Initial term "12 Monate ab Lieferbeginn" 01.10.2025 → ends 30.09.2026 (§ 188 Abs. 2 Alt. 2 BGB).
    term_end = dc.checked("2026-09-30", "Wed")
    # Notice for the end of the initial term: one month before 30.09.2026 → must arrive by 30.08.2026 (passed).
    # Afterwards: any time with one month's notice; notice received on the simulated today Mon 28.09.2026
    # ends the contract one month later, Wed 28.10.2026 (§ 188 Abs. 2 BGB).
    earliest = dc.checked(dc.plus_months(sam.SIMULATED_TODAY, 1), "Wed")
    received = dc.checked("2025-09-22", "Mon")  # letter dated Sat 20.09.2025, delivered Monday
    truth = Truth(
        kind="contract",
        area="home",
        sender_name="Stadtwerke Musterstadt GmbH",
        sender_kind="utility",
        document_date="2025-09-20",
        references=[
            Ref("Vertragskonto", VERTRAGSKONTO),
            Ref("Kundennummer", KUNDENNR_SW),
            Ref("Zählernummer", ZAEHLER),
            Ref("Marktlokation", MALO),
        ],
        amounts=[
            Amount("Arbeitspreis (ct/kWh, brutto)", 32.90),
            Amount("Grundpreis pro Monat (brutto)", 11.90),
            Amount("Monatlicher Abschlag", 48.00),
        ],
        items=[
            TruthItem(
                kind="task",
                title_hint="Report the meter reading at the start of supply",
                expected_due="2025-10-05",
                date_basis="fixed",
                nature="declaration",
                quote="Bitte teilen Sie uns den Zählerstand zum Lieferbeginn bis zum 05.10.2025 mit",
                reasoning="Explicit date in the letter (already in the past on the simulated today).",
                optional=True,
            ),
            TruthItem(
                kind="payment",
                title_hint="Monthly electricity instalment (Abschlag)",
                expected_due="2026-10-15",
                date_basis="fixed",
                nature="payment",
                recurrence="monthly",
                amount=48.0,
                direction="out",
                quote="48,00 €, fällig jeweils zum 15. eines Monats, erstmals am 15.10.2025",
                reasoning="Recurring on the 15th, collected by direct debit; next after 2026-09-28 is 2026-10-15.",
                optional=True,
            ),
        ],
        contract=TruthContract(
            name="MusterStrom Flex",
            category="energy",
            regime="bgb309_new",
            customer_number=VERTRAGSKONTO,
            concluded_date="2025-09-20",
            start_date="2025-10-01",
            initial_term_months=12,
            renewal_term_months=0,
            notice_value=1,
            notice_unit="months",
            notice_basis="end_of_term",
            end_date=None,
            cost_amount=48.0,
            cost_interval="monthly",
            expected_current_term_end=term_end,
            expected_cancel_by=None,
            expected_earliest_exit=earliest,
            reasoning="Initial term 01.10.2025–30.09.2026; the notice deadline for its end (30.08.2026) has passed. "
            "Afterwards indefinite with one month's notice at any time (§ 309 Nr. 9 BGB): notice received "
            "2026-09-28 → contract ends 2026-10-28. See the price increase (tray) for the special right.",
        ),
        payment=None,
        key_quotes=[SW_TERM_QUOTE, SW_AFTER_QUOTE, "Monatlicher Abschlag"],
        related=[("stadtwerke_preisanpassung", "price increase for this contract")],
    )
    return Sample(
        slug="stadtwerke_vertrag",
        title="Stromliefervertrag MusterStrom Flex",
        language="de",
        received_date=received,
        render=lambda: as_pdf(
            letter_pdf(
                STADTWERKE, "2025-09-20", _stadtwerke_contract, follow_ref=f"Vertragskonto {VERTRAGSKONTO}"
            )
        ),
        truth=truth,
        subject_hint="Vertragsbestätigung Strom",
    )


# --------------------------------------------------------------------------------------------------
# Betriebs- und Heizkostenabrechnung 2025 (08.09.2026)
# --------------------------------------------------------------------------------------------------

AREA_SAM = Decimal("48.60")
AREA_HOUSE = Decimal("742.80")
DAYS_SAM = 92  # 01.10.–31.12.2025
DAYS_YEAR = 365
COLD_COSTS: list[tuple[str, Decimal]] = [
    ("Grundsteuer", Decimal("2312.40")),
    ("Wasserversorgung und Entwässerung", Decimal("4986.30")),
    ("Müllbeseitigung", Decimal("1874.00")),
    ("Straßenreinigung", Decimal("412.80")),
    ("Gebäudereinigung", Decimal("2640.00")),
    ("Gartenpflege", Decimal("1190.00")),
    ("Allgemeinstrom (Beleuchtung)", Decimal("548.25")),
    ("Schornsteinfeger / Immissionsmessung", Decimal("286.20")),
    ("Sach- und Haftpflichtversicherung", Decimal("1842.60")),
    ("Hauswart", Decimal("2160.00")),
]
TOTAL_SHARE = money("544.30")
PREPAID = money(3 * 120)
NACHZAHLUNG = money("184.30")
NK_PAY_QUOTE = (
    "Bitte überweisen Sie den Nachzahlungsbetrag in Höhe von 184,30 € bis zum 09.10.2026 auf unser Konto bei der "
    "Sparkasse Musterstadt."
)
NK_OBJECTION_QUOTE = (
    "Einwendungen gegen diese Abrechnung teilen Sie uns bitte innerhalb von zwölf Monaten nach Zugang dieser "
    "Abrechnung mit (§ 556 Abs. 3 Satz 5 BGB)."
)
NK_ADJUST_QUOTE = "Ihre Gesamtmiete beträgt ab dem 01.11.2026 somit 670,00 € (bisher 640,00 €)."


def _cold_shares() -> list[tuple[str, Decimal, Decimal]]:
    factor = AREA_SAM / AREA_HOUSE * Decimal(DAYS_SAM) / Decimal(DAYS_YEAR)
    return [(label, total, money(total * factor)) for label, total in COLD_COSTS]


def _heating_split() -> tuple[Decimal, Decimal, Decimal]:
    cold = sum((share for _l, _t, share in _cold_shares()), Decimal(0))
    heating_total = TOTAL_SHARE - cold
    heizung = money(heating_total * Decimal("0.78"))
    return cold, heizung, heating_total - heizung


def _nebenkosten(letter: Letter) -> None:
    cold, heizung, warmwasser = _heating_split()
    letter.address(sam.recipient())
    letter.info(
        [
            ("Vertragsnummer", MV_NR),
            ("Wohnung", f"Nr. {WOHNUNG}, 2. OG links"),
            ("Ansprechpartner", "Tobias Exempel"),
            ("Telefon", "0123 45678-214"),
            ("Datum", "08.09.2026"),
        ]
    )
    letter.subject(
        "Betriebs- und Heizkostenabrechnung 2025",
        sub="Abrechnungszeitraum 01.01.–31.12.2025 · Ihr Nutzungszeitraum 01.10.–31.12.2025 (92 Tage)",
    )
    letter.para(SALUTE_DE)
    letter.para(
        "anbei erhalten Sie die Abrechnung der Betriebs- und Heizkosten für das Jahr 2025 für Ihre Wohnung "
        "im Hause Beispielweg 5. Da Ihr Mietverhältnis am 01.10.2025 begonnen hat, werden die Kosten des "
        "Hauses zeitanteilig für 92 von 365 Tagen und nach Ihrem Wohnflächenanteil (48,60 m² von 742,80 m²) "
        "berechnet. Die Einzelaufstellung finden Sie in der Anlage."
    )
    letter.table(
        [
            ("Zusammenfassung", "Betrag"),
            ("Kalte Betriebskosten (Ihr Anteil, siehe Anlage)", eur(cold)),
            ("Heizkosten lt. Einzelabrechnung Mess-Service Beispiel GmbH", eur(heizung)),
            ("Warmwasserkosten lt. Einzelabrechnung Mess-Service Beispiel GmbH", eur(warmwasser)),
            ("**Ihre Kosten 2025**", f"**{eur(TOTAL_SHARE)}**"),
            ("abzüglich Ihrer Vorauszahlungen (3 × 120,00 €)", f"– {eur(PREPAID)}"),
            ("**Nachzahlung**", f"**{eur(NACHZAHLUNG)}**"),
        ],
        (130, 35),
        aligns=("LEFT", "RIGHT"),
        head_fill=WOHNBAU.color,
        gap=3,
    )
    letter.box(
        [
            NK_PAY_QUOTE,
            f"IBAN {ACC_WOHNBAU.iban_pretty} · BIC {ACC_WOHNBAU.bank.bic} · Verwendungszweck: {MV_NR} NK 2025",
        ],
        title="Nachzahlung 184,30 €",
    )
    letter.heading("Anpassung Ihrer Vorauszahlungen")
    letter.para(
        "Auf Grundlage dieser Abrechnung passen wir Ihre monatlichen Vorauszahlungen gemäß § 560 Abs. 4 BGB "
        "ab dem 01.11.2026 an: Betriebskosten 85,00 € (bisher 70,00 €), Heiz- und Warmwasserkosten "
        f"65,00 € (bisher 50,00 €). {NK_ADJUST_QUOTE} Haben Sie uns ein SEPA-Lastschriftmandat erteilt, "
        "buchen wir den neuen Betrag automatisch ab; andernfalls passen Sie bitte Ihren Dauerauftrag an."
    )
    letter.heading("Einwendungen und Belegeinsicht")
    letter.para(
        f"{NK_OBJECTION_QUOTE} Die Belege können Sie nach vorheriger Terminvereinbarung in unserer "
        "Geschäftsstelle einsehen."
    )
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Wohnbau Musterstadt eG",
        signers=[("Tobias Exempel", "Betriebskostenabrechnung")],
    )
    letter.space(4)
    letter.rule()
    letter.title("Anlage: Einzelaufstellung der kalten Betriebskosten 2025", size=11)
    letter.para(
        "Umlageschlüssel: Wohnfläche 48,60 m² / 742,80 m² × 92 / 365 Tage (Faktor 0,016491).",
        size=8.4,
        color=GREY,
    )
    rows = [("Kostenart (§ 2 BetrKV)", "Gesamtkosten Haus", "Ihr Anteil")]
    rows += [(label, eur(total), eur(share)) for label, total, share in _cold_shares()]
    rows.append(
        (
            "**Summe kalte Betriebskosten**",
            f"**{eur(sum((t for _l, t in COLD_COSTS), Decimal(0)))}**",
            f"**{eur(cold)}**",
        )
    )
    letter.table(
        rows, (95, 38, 32), aligns=("LEFT", "RIGHT", "RIGHT"), head_fill=WOHNBAU.color, zebra=True, gap=4
    )
    letter.heading("Heiz- und Warmwasserkosten", size=9.6)
    letter.para(
        "Die Heiz- und Warmwasserkosten wurden von der Mess-Service Beispiel GmbH nach der Heizkostenverordnung "
        "zu 70 % nach Verbrauch und zu 30 % nach Wohnfläche verteilt. Ihr Verbrauch im Nutzungszeitraum: "
        "Heizung 1.412 Einheiten (Heizkostenverteiler), Warmwasser 4,8 m³.",
        size=8.8,
    )
    letter.table(
        [
            ("Position", "Ihr Anteil"),
            ("Heizkosten (Grund- und Verbrauchskosten)", eur(heizung)),
            ("Warmwasserkosten (Grund- und Verbrauchskosten)", eur(warmwasser)),
            ("**Summe Heiz- und Warmwasserkosten**", f"**{eur(heizung + warmwasser)}**"),
        ],
        (133, 32),
        aligns=("LEFT", "RIGHT"),
        head_fill=WOHNBAU.color,
        gap=4,
    )
    letter.small(
        "Nicht umlagefähige Kosten (Verwaltung, Instandhaltung, Rücklagen) sind in dieser Abrechnung nicht "
        "enthalten. Die Kosten für den Kabelanschluss werden seit dem 01.07.2024 nicht mehr umgelegt."
    )


def nebenkostenabrechnung() -> Sample:
    """Service-charge statement 2025, dated Tue 08.09.2026."""
    cold, heizung, warmwasser = _heating_split()
    dc.expect(cold + heizung + warmwasser == TOTAL_SHARE, "shares add up")
    dc.expect(TOTAL_SHARE - PREPAID == NACHZAHLUNG, "Nachzahlung = 544,30 − 360,00")
    dc.expect(Decimal(150) < heizung + warmwasser < Decimal(300), "plausible Q4 heating share")
    received = dc.checked("2026-09-10", "Thu")  # dated Tue 08.09.2026, delivered two days later
    # Objection period (§ 556 Abs. 3 S. 5 BGB, as printed): "innerhalb von zwölf Monaten nach Zugang".
    # Receipt Thu 10.09.2026 + 12 months → Fri 10.09.2027 (§§ 187 Abs. 1, 188 Abs. 2 BGB), a business day.
    objection_due = dc.checked(dc.plus_months(received, 12), "Fri")
    truth = Truth(
        kind="utility_bill",
        area="home",
        sender_name="Wohnbau Musterstadt eG",
        sender_kind="landlord",
        document_date="2026-09-08",
        references=[Ref("Vertragsnummer", MV_NR), Ref("Wohnung", WOHNUNG)],
        amounts=[
            Amount("Ihre Kosten 2025", float(TOTAL_SHARE)),
            Amount("Vorauszahlungen", float(PREPAID)),
            Amount("Nachzahlung", float(NACHZAHLUNG)),
            Amount("Neue Gesamtmiete ab 01.11.2026", 670.0),
        ],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Pay the service-charge balance (Nachzahlung)",
                expected_due=dc.checked("2026-10-09", "Fri"),
                date_basis="fixed",
                nature="payment",
                amount=float(NACHZAHLUNG),
                direction="out",
                quote=NK_PAY_QUOTE,
                reasoning="Explicit date 'bis zum 09.10.2026' (a Friday, business day).",
            ),
            TruthItem(
                kind="deadline",
                title_hint="Last day to object to the statement",
                expected_due=objection_due,
                date_basis="relative",
                nature="objection",
                quote=NK_OBJECTION_QUOTE,
                reasoning="12 months after receipt. Received 2026-09-10 (manifest received_date) → 2026-09-10 + 12 "
                "months = Fri 2027-09-10. Without a confirmed arrival date the document date gives 2027-09-08.",
            ),
            TruthItem(
                kind="payment",
                title_hint="New monthly rent 670 € from November",
                expected_due="2026-11-04",
                date_basis="relative",
                nature="payment",
                recurrence="monthly",
                amount=670.0,
                direction="out",
                quote=NK_ADJUST_QUOTE,
                reasoning="First instalment at the new amount: November 2026, 3rd Werktag. Sun 01.11. is a holiday "
                "(Allerheiligen), Mon 02.11 (1), Tue 03.11 (2), Wed 04.11 (3) → 2026-11-04.",
                optional=True,
            ),
        ],
        change=TruthChange("terms_change", "2026-11-01", 640.0, 670.0, "monthly"),
        payment=TruthPayment(ACC_WOHNBAU.iban, "Wohnbau Musterstadt eG", f"{MV_NR} NK 2025"),
        key_quotes=[NK_PAY_QUOTE, NK_OBJECTION_QUOTE, NK_ADJUST_QUOTE],
        kind_alternatives=["rent_lease", "invoice"],
        related=[("mietvertrag", "lease this statement belongs to")],
        tax_relevant=True,
        notes="Household-related services (Hauswart, Gebäudereinigung, Gartenpflege) are § 35a EStG deductible.",
    )
    return Sample(
        slug="nebenkostenabrechnung_2025",
        title="Betriebs- und Heizkostenabrechnung 2025",
        language="de",
        received_date=received,
        render=lambda: as_pdf(
            letter_pdf(WOHNBAU, "2026-09-08", _nebenkosten, follow_ref=f"Vertragsnummer {MV_NR}")
        ),
        truth=truth,
        subject_hint="Nachzahlung Betriebskosten 2025",
    )


# --------------------------------------------------------------------------------------------------
# Stadtwerke: Preisanpassung (24.09.2026) — new-mail tray
# --------------------------------------------------------------------------------------------------

USAGE_KWH = 1320
OLD_WORK, NEW_WORK = Decimal("0.3290"), Decimal("0.3640")
OLD_BASE, NEW_BASE = Decimal("11.90"), Decimal("13.90")
PRICE_RIGHT_QUOTE = (
    "Sie sind berechtigt, den Vertrag ohne Einhaltung einer Kündigungsfrist zum Zeitpunkt des Wirksamwerdens der "
    "Preisänderung in Textform zu kündigen (§ 41 Abs. 5 Energiewirtschaftsgesetz – EnWG)."
)
PRICE_EFFECTIVE_QUOTE = (
    "Daher passen wir die Preise für Ihren Tarif MusterStrom Flex zum 01.11.2026 wie folgt an:"
)
ABSCHLAG_QUOTE = "Ihren monatlichen Abschlag passen wir deshalb ab dem 15.11.2026 von 48,00 € auf 54,00 € an."


def _yearly(work: Decimal, base: Decimal) -> Decimal:
    return money(USAGE_KWH * work + 12 * base)


def _price_increase(letter: Letter) -> None:
    old, new = _yearly(OLD_WORK, OLD_BASE), _yearly(NEW_WORK, NEW_BASE)
    letter.address(sam.recipient())
    letter.info(
        [
            ("Vertragskonto", VERTRAGSKONTO),
            ("Kundennummer", KUNDENNR_SW),
            ("Tarif", "MusterStrom Flex"),
            ("Kundenservice", "0123 5550-100"),
            ("Datum", "24.09.2026"),
        ]
    )
    letter.subject(
        "Anpassung Ihrer Strompreise zum 01.11.2026",
        sub="Lieferstelle: Beispielweg 5, 12345 Musterstadt · Zählernummer " + ZAEHLER,
    )
    letter.para(SALUTE_DE)
    letter.para(
        "die Kosten der Stromversorgung sind im laufenden Jahr deutlich gestiegen. Insbesondere die Entgelte "
        "für die Nutzung der Stromnetze, die der örtliche Netzbetreiber festlegt, sowie unsere "
        f"Beschaffungskosten haben sich erhöht. {PRICE_EFFECTIVE_QUOTE}"
    )
    letter.table(
        [
            ("Preisbestandteil", "bisher (brutto)", "ab 01.11.2026 (brutto)"),
            ("Arbeitspreis", "32,90 ct/kWh", "**36,40 ct/kWh**"),
            ("Grundpreis", "11,90 €/Monat", "**13,90 €/Monat**"),
        ],
        (75, 42, 48),
        aligns=("LEFT", "RIGHT", "RIGHT"),
        head_fill=STADTWERKE.color,
        gap=1.2,
    )
    letter.small(
        "Alle Preise inkl. 19 % Umsatzsteuer. Netto: Arbeitspreis bisher 27,65 ct/kWh, künftig 30,59 ct/kWh; "
        "Grundpreis bisher 10,00 €/Monat, künftig 11,68 €/Monat.",
        gap=3,
    )
    letter.heading("Was bedeutet das für Sie?")
    letter.para(
        f"Bei Ihrem Jahresverbrauch von {de_num(USAGE_KWH, 0)} kWh steigen Ihre jährlichen Kosten von "
        f"{eur(old)} auf {eur(new)} brutto, also um {eur(new - old)} pro Jahr. {ABSCHLAG_QUOTE}"
    )
    letter.box(
        [
            PRICE_RIGHT_QUOTE,
            "Die Kündigung muss uns vor dem Wirksamwerden der Preisänderung zugehen. Sie "
            "ist für Sie kostenfrei – am einfachsten über den Button „Vertrag kündigen“ im Kundenportal.",
        ],
        title="Ihr Sonderkündigungsrecht",
    )
    letter.para("Wir würden uns freuen, Sie weiterhin mit Energie aus Ihrer Stadt versorgen zu dürfen.")
    letter.closing(
        "Freundliche Grüße",
        org_line="Ihre Stadtwerke Musterstadt GmbH",
        signers=[("Dipl.-Ing. Frank Muster", "Geschäftsführer"), ("Jana Beispiel", "Kundenservice")],
    )


def stadtwerke_preisanpassung() -> Sample:
    """Electricity price increase letter, 24.09.2026 (new-mail tray)."""
    old, new = _yearly(OLD_WORK, OLD_BASE), _yearly(NEW_WORK, NEW_BASE)
    dc.expect((old, new) == (money("577.08"), money("647.28")), "yearly costs")
    dc.expect(money(old / 12) == money("48.09") and money(new / 12) == money("53.94"), "Abschlag 48 → 54")
    received = dc.checked("2026-09-26", "Sat")  # dated Thu 24.09.2026, Saturday delivery
    # § 41 Abs. 5 EnWG: cancel without notice effective when the change takes effect (Sun 01.11.2026).
    # The cancellation must be received before that: last day Sat 31.10.2026. Notice-type deadlines are not
    # moved by § 193 BGB; Ordnung should show the safe date Fri 30.10.2026 as well.
    cancel_by = dc.checked(dc.plus_days("2026-11-01", -1), "Sat")
    truth = Truth(
        kind="price_increase",
        area="home",
        sender_name="Stadtwerke Musterstadt GmbH",
        sender_kind="utility",
        document_date="2026-09-24",
        references=[
            Ref("Vertragskonto", VERTRAGSKONTO),
            Ref("Kundennummer", KUNDENNR_SW),
            Ref("Zählernummer", ZAEHLER),
        ],
        amounts=[
            Amount("Arbeitspreis neu (ct/kWh, brutto)", 36.40),
            Amount("Grundpreis neu pro Monat (brutto)", 13.90),
            Amount("Abschlag neu", 54.00),
            Amount("Mehrkosten pro Jahr", float(new - old)),
        ],
        items=[
            TruthItem(
                kind="deadline",
                title_hint="Special right to cancel before the price increase",
                expected_due=cancel_by,
                date_basis="relative",
                nature="notice",
                quote=PRICE_RIGHT_QUOTE,
                reasoning="Price change takes effect Sun 01.11.2026; a cancellation 'zum Zeitpunkt des "
                "Wirksamwerdens' must be received before then → Sat 31.10.2026 (notice deadline, no § 193 shift; "
                "safe date Fri 30.10.2026).",
            ),
            TruthItem(
                kind="payment",
                title_hint="New monthly instalment 54 €",
                expected_due="2026-11-15",
                date_basis="fixed",
                nature="payment",
                recurrence="monthly",
                amount=54.0,
                direction="out",
                quote=ABSCHLAG_QUOTE,
                reasoning="First instalment at the new amount on 15.11.2026 (direct debit).",
                optional=True,
            ),
        ],
        change=TruthChange(
            "price_increase", "2026-11-01", 48.0, 54.0, "monthly", "32,90 ct/kWh", "36,40 ct/kWh"
        ),
        key_quotes=[PRICE_RIGHT_QUOTE, PRICE_EFFECTIVE_QUOTE, ABSCHLAG_QUOTE],
        related=[("stadtwerke_vertrag", "contract whose prices change")],
        notes="Special cancellation right (§ 41 Abs. 5 EnWG) → Idea with a computed window. Extra cost +70,20 €/year.",
    )
    return Sample(
        slug="stadtwerke_preisanpassung",
        title="Anpassung Ihrer Strompreise zum 01.11.2026",
        language="de",
        received_date=received,
        render=lambda: as_pdf(
            letter_pdf(STADTWERKE, "2026-09-24", _price_increase, follow_ref=f"Vertragskonto {VERTRAGSKONTO}")
        ),
        truth=truth,
        tray=True,
        subject_hint="Preisanpassung Strom",
    )
