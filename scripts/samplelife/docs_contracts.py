"""Running contracts: mobile phone, gym, liability insurance, Deutschlandticket and the bank account."""

from __future__ import annotations

from samplelife import datecheck as dc
from samplelife import persona as sam
from samplelife.common import SALUTE_DE, as_pdf, letter_pdf
from samplelife.fmt import eur
from samplelife.letter import Letter
from samplelife.orgs import (
    ACC_FITWELL,
    CI_FITWELL,
    CI_MVB,
    FITWELL,
    FUNKNETZ,
    MUSTERBANK_ORG,
    MVB,
    VERSICHERUNG,
)
from samplelife.truth import Amount, Ref, Sample, Truth, TruthChange, TruthContract, TruthItem

# --------------------------------------------------------------------------------------------------
# FunkNetz Mobil: Auftragsbestätigung (12.11.2024)
# --------------------------------------------------------------------------------------------------

FN_KUNDE = "FN-88213407"
FN_AUFTRAG = "A-2024-5518290"
FN_NOTICE_QUOTE = (
    "Der Vertrag kann von beiden Seiten mit einer Frist von einem Monat zum Ende der Mindestvertragslaufzeit "
    "gekündigt werden."
)
FN_AFTER_QUOTE = (
    "Wird der Vertrag nicht fristgerecht gekündigt, verlängert er sich auf unbestimmte Zeit und kann danach "
    "jederzeit mit einer Frist von einem Monat gekündigt werden."
)


def _funknetz(letter: Letter) -> None:
    letter.address(sam.recipient(old=True))
    letter.info(
        [
            ("Kundennummer", FN_KUNDE),
            ("Auftragsnummer", FN_AUFTRAG),
            ("Ihre Rufnummer", sam.PHONE),
            ("Service", "0123 2244660"),
            ("Datum", "12.11.2024"),
        ]
    )
    letter.subject("Auftragsbestätigung – Ihr Mobilfunkvertrag FunkNetz Smart M")
    letter.para(SALUTE_DE)
    letter.para(
        "vielen Dank für Ihre Bestellung vom 11.11.2024 und herzlich willkommen bei FunkNetz Mobil! Mit "
        "diesem Schreiben bestätigen wir Ihnen den Abschluss Ihres Mobilfunkvertrags. Ihre SIM-Karte "
        "erhalten Sie mit separater Post; PIN und PUK senden wir Ihnen aus Sicherheitsgründen in einem "
        "getrennten Brief."
    )
    letter.para("Ihre Vertragsdaten im Überblick:", bold=True, gap=1.2)
    letter.kv(
        [
            ("Tarif", "FunkNetz Smart M – Allnet-Flat, SMS-Flat, 20 GB Datenvolumen (5G), EU-Roaming"),
            ("Vertragsbeginn", "15.11.2024 (Tag der Freischaltung)"),
            ("Mindestvertragslaufzeit", "24 Monate"),
            ("Monatlicher Grundpreis", "34,99 €"),
            ("Bereitstellungspreis", "0,00 € (Online-Aktion statt 39,99 €)"),
            ("Zahlungsweise", f"SEPA-Lastschrift, Mandatsreferenz {FN_KUNDE}-01"),
            ("Rechnung", "monatlich online im Kundenportal „Mein FunkNetz“"),
        ],
        key_w=52,
        bold_keys=True,
        zebra=True,
        gap=3,
    )
    letter.heading("Laufzeit und Kündigung")
    letter.para(
        f"{FN_NOTICE_QUOTE} {FN_AFTER_QUOTE} Sie können in Textform (z. B. per E-Mail an "
        "kuendigung@funknetz-mobil.example) oder über den Button „Verträge hier kündigen“ in Ihrem "
        "Kundenportal kündigen."
    )
    letter.para(
        "Die wesentlichen Vertragsbestandteile finden Sie in der beigefügten Vertragszusammenfassung "
        "(§ 54 Abs. 3 TKG). Es gelten unsere AGB, die Leistungsbeschreibung und die Preisliste."
    )
    letter.closing(
        "Wir wünschen Ihnen viel Freude mit Ihrem neuen Tarif.\nMit freundlichen Grüßen",
        org_line="Ihr FunkNetz Kundenservice",
        scribble=False,
    )
    letter.enclosures(["Vertragszusammenfassung, Widerrufsbelehrung"], label="Anlagen")
    letter.new_page()
    letter.title(
        "Vertragszusammenfassung",
        size=13,
        sub="Die Vertragszusammenfassung enthält die Hauptelemente dieses Dienstleistungsangebots, wie es "
        "im EU-Recht vorgeschrieben ist. Sie hilft beim Vergleich von Dienstleistungsangeboten. Vollständige "
        "Informationen über das Dienstleistungsangebot sind in anderen Dokumenten enthalten.",
    )
    sections = [
        (
            "FunkNetz Smart M · Kundennummer " + FN_KUNDE,
            "Anbieter: FunkNetz Mobil GmbH, Wellenweg 7, 12351 "
            "Beispielhausen, service@funknetz-mobil.example, Telefon 0123 2244660",
        ),
        (
            "Dienste und Geräte",
            "Mobilfunk-Sprach- und Datendienst: Flatrate für Telefonie in alle deutschen Netze, "
            "SMS-Flatrate, 20 GB Datenvolumen pro Abrechnungsmonat. Nach Verbrauch des Datenvolumens wird die "
            "Geschwindigkeit auf 64 kbit/s reduziert. EU-Roaming zu Inlandskonditionen. Kein Endgerät enthalten.",
        ),
        (
            "Geschwindigkeiten des Internetdienstes und Abhilfen bei Problemen",
            "Geschätzte maximale Geschwindigkeit: "
            "5G bis 300 Mbit/s im Download und 50 Mbit/s im Upload; LTE bis 150 Mbit/s bzw. 50 Mbit/s. Bei "
            "erheblichen, kontinuierlichen oder regelmäßig wiederkehrenden Abweichungen können Sie die Rechte nach "
            "§ 57 Abs. 4 TKG geltend machen.",
        ),
        (
            "Preis",
            "Monatlicher Grundpreis 34,99 €. Einmaliger Bereitstellungspreis 0,00 €. Verbindungen ins Ausland "
            "(außerhalb der EU) laut Preisliste.",
        ),
        (
            "Laufzeit, Verlängerung und Kündigung",
            "Mindestvertragslaufzeit 24 Monate ab Vertragsbeginn "
            "(15.11.2024). Kündigung mit einer Frist von einem Monat zum Ende der Mindestvertragslaufzeit. Nach Ablauf "
            "der Mindestvertragslaufzeit läuft der Vertrag auf unbestimmte Zeit und ist jederzeit mit einer Frist von "
            "einem Monat kündbar.",
        ),
        (
            "Funktionen für Endnutzer mit Behinderungen",
            "Rechnungen und Vertragsunterlagen sind auf Wunsch in "
            "Großdruck erhältlich. Der Kundenservice ist auch per Chat und E-Mail erreichbar.",
        ),
        (
            "Sonstige relevante Informationen",
            "Die Rufnummer kann bei Vertragsende zu einem anderen Anbieter "
            "mitgenommen werden. Die Kosten der Rufnummernmitnahme trägt der abgebende Anbieter.",
        ),
    ]
    for heading, text in sections:
        letter.heading(heading, size=9.2, gap=0.4)
        letter.para(text, size=8.8, gap=2.2)


def mobilfunk() -> Sample:
    """Mobile contract confirmation, FunkNetz Mobil GmbH, 12.11.2024."""
    # Minimum term: 24 months from Fri 15.11.2024 (day_start mode, § 187 Abs. 2 / § 188 Abs. 2 BGB)
    # → ends Sat 14.11.2026. Notice one month before its end: must arrive by Wed 14.10.2026.
    term_end = dc.checked("2026-11-14", "Sat")
    cancel_by = dc.checked(dc.plus_months(term_end, -1), "Wed")
    truth = Truth(
        kind="contract",
        area="home",
        sender_name="FunkNetz Mobil GmbH",
        sender_kind="telecom",
        document_date="2024-11-12",
        references=[
            Ref("Kundennummer", FN_KUNDE),
            Ref("Auftragsnummer", FN_AUFTRAG),
            Ref("Rufnummer", sam.PHONE),
        ],
        amounts=[Amount("Monatlicher Grundpreis", 34.99), Amount("Bereitstellungspreis", 0.0)],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Monthly mobile bill",
                expected_due=None,
                date_basis="none",
                nature="payment",
                recurrence="monthly",
                amount=34.99,
                direction="out",
                quote="Monatlicher Grundpreis",
                reasoning="Collected by direct debit after each monthly bill; no due date printed.",
                optional=True,
            ),
        ],
        contract=TruthContract(
            name="FunkNetz Smart M",
            category="mobile",
            regime="tkg56",
            customer_number=FN_KUNDE,
            concluded_date="2024-11-12",
            start_date="2024-11-15",
            initial_term_months=24,
            renewal_term_months=0,
            notice_value=1,
            notice_unit="months",
            notice_basis="end_of_term",
            end_date=None,
            cost_amount=34.99,
            cost_interval="monthly",
            expected_current_term_end=term_end,
            expected_cancel_by=cancel_by,
            expected_earliest_exit=term_end,
            reasoning="24 months from 15.11.2024 end on Sat 14.11.2026; one month's notice → must be received by "
            "Wed 14.10.2026. If missed, § 56 Abs. 3 TKG: indefinite, cancellable any time with one month's notice.",
        ),
        key_quotes=[FN_NOTICE_QUOTE, FN_AFTER_QUOTE, "Vertragsbeginn"],
    )
    return Sample(
        slug="mobilfunkvertrag",
        title="Auftragsbestätigung Mobilfunkvertrag",
        language="de",
        received_date=dc.checked("2024-11-14", "Thu"),
        render=lambda: as_pdf(
            letter_pdf(FUNKNETZ, "2024-11-12", _funknetz, follow_ref=f"Kundennummer {FN_KUNDE}")
        ),
        truth=truth,
        subject_hint="Auftragsbestätigung Mobilfunk",
    )


# --------------------------------------------------------------------------------------------------
# FitWell Studios: Mitgliedsvertrag (02.01.2025)
# --------------------------------------------------------------------------------------------------

FW_NR = "FW-10457"
FW_TERM_QUOTE = "Die Mitgliedschaft beginnt am 15.01.2025 und hat eine Erstlaufzeit von 12 Monaten."
FW_AFTER_QUOTE = (
    "Nach Ablauf der Erstlaufzeit läuft die Mitgliedschaft auf unbestimmte Zeit weiter und kann jederzeit mit einer "
    "Frist von einem Monat gekündigt werden."
)


def _fitwell(letter: Letter) -> None:
    letter.size = 8.6
    letter.lh = 8.6 * 0.47
    letter.title("Mitgliedsvertrag", sub=f"Mitgliedsnummer {FW_NR} · Studio Musterstadt-Mitte", y=36)
    letter.kv(
        [
            ("Mitglied", f"{sam.NAME}, geb. 14.03.2000"),
            ("Anschrift", f"{sam.OLD_STREET}, {sam.OLD_CITY}"),
            ("E-Mail / Telefon", f"{sam.EMAIL} / {sam.PHONE}"),
        ],
        key_w=40,
        bold_keys=True,
        borders="HORIZONTAL_LINES",
        gap=2.5,
    )
    letter.table(
        [
            ("Tarif", "Monatsbeitrag", "Aufnahmegebühr", "Beginn", "Erstlaufzeit"),
            ("FitWell Flex 12 (Studenten)", "29,90 €", "19,90 €", "15.01.2025", "12 Monate"),
        ],
        (52, 28, 33, 26, 26),
        aligns=("LEFT", "RIGHT", "RIGHT", "CENTER", "CENTER"),
        head_fill=FITWELL.accent,
        gap=3,
    )
    clauses = [
        (
            "§ 1 Leistungen",
            "Das Mitglied ist berechtigt, während der Öffnungszeiten (Mo–Fr 6–23 Uhr, Sa/So 8–21 Uhr) "
            "die Trainingsflächen, Kursangebote und Umkleiden des Studios Musterstadt-Mitte zu nutzen. Getränke-Flat "
            "und Personal Training sind nicht enthalten.",
        ),
        (
            "§ 2 Beiträge und Zahlung",
            "Der Monatsbeitrag von 29,90 € ist monatlich im Voraus fällig und wird zum "
            "1. eines Monats per SEPA-Lastschrift eingezogen. Die Aufnahmegebühr von 19,90 € wird mit dem ersten "
            "Beitrag eingezogen. Der Studententarif setzt die Vorlage einer gültigen Immatrikulationsbescheinigung zu "
            "Beginn jedes Semesters voraus.",
        ),
        (
            "§ 3 Laufzeit und Kündigung",
            f"{FW_TERM_QUOTE} Sie kann erstmals zum Ende der Erstlaufzeit mit einer Frist "
            f"von einem Monat gekündigt werden. {FW_AFTER_QUOTE} Die Kündigung bedarf der Textform (z. B. E-Mail an "
            "kuendigung@fitwell-studios.example); sie kann auch über den Button „Vertrag kündigen“ auf unserer "
            "Website erklärt werden.",
        ),
        (
            "§ 4 Ruhen der Mitgliedschaft",
            "Bei Krankheit, Schwangerschaft oder einem Auslandsaufenthalt von mehr als "
            "vier Wochen ruht die Mitgliedschaft auf Antrag gegen Nachweis; für diese Zeit sind keine Beiträge zu "
            "zahlen.",
        ),
        (
            "§ 5 Hausordnung und Datenschutz",
            "Es gilt die im Studio aushängende Hausordnung. Einzelheiten zur "
            "Datenverarbeitung enthält die Datenschutzerklärung unter fitwell-studios.example/datenschutz.",
        ),
    ]
    for heading, text in clauses:
        letter.heading(heading, size=9.2, gap=0.3)
        letter.para(text, gap=1.4)
    letter.box(
        [
            f"Ich ermächtige die FitWell Studios GmbH (Gläubiger-ID {CI_FITWELL}), Zahlungen von meinem Konto mittels "
            "Lastschrift einzuziehen, und weise mein Kreditinstitut an, diese Lastschriften einzulösen. Ich kann "
            "innerhalb von acht Wochen ab dem Belastungsdatum die Erstattung des belasteten Betrages verlangen.",
            f"Kontoinhaber: {sam.NAME} · IBAN: {sam.IBAN_MASKED} · Mandatsreferenz: {FW_NR}-M1",
        ],
        title="SEPA-Lastschriftmandat",
        size=8.0,
        gap=2,
    )
    letter.signature_fields(
        ("Musterstadt, 02.01.2025", "FitWell Studios GmbH", "fitwell:studio-lead"),
        ("Musterstadt, 02.01.2025", "Unterschrift Mitglied", "sam:gym"),
    )
    letter.small(
        f"Beiträge gehen auf das Konto {ACC_FITWELL.iban_pretty} ({ACC_FITWELL.bank.name}). Eine Kopie "
        "dieses Vertrags wurde dem Mitglied ausgehändigt."
    )


def fitness() -> Sample:
    """Gym membership contract, FitWell Studios GmbH, signed 02.01.2025."""
    # Initial term 12 months from Wed 15.01.2025 → ends Wed 14.01.2026. Since then indefinite with one month's
    # notice at any time (§ 309 Nr. 9 BGB, consumer contract concluded after 01.03.2022). Notice received on
    # the simulated today Mon 28.09.2026 → membership ends Wed 28.10.2026.
    initial_end = dc.checked("2026-01-14", "Wed")
    dc.expect(initial_end < sam.SIMULATED_TODAY, "initial term is over")
    earliest = dc.checked(dc.plus_months(sam.SIMULATED_TODAY, 1), "Wed")
    truth = Truth(
        kind="contract",
        area="leisure",
        sender_name="FitWell Studios GmbH",
        sender_kind="gym",
        document_date="2025-01-02",
        references=[Ref("Mitgliedsnummer", FW_NR)],
        amounts=[Amount("Monatsbeitrag", 29.90), Amount("Aufnahmegebühr", 19.90)],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Monthly gym fee",
                expected_due="2026-10-01",
                date_basis="fixed",
                nature="payment",
                recurrence="monthly",
                amount=29.90,
                direction="out",
                quote="wird zum 1. eines Monats per SEPA-Lastschrift eingezogen",
                reasoning="Direct debit on the 1st of each month; next after 2026-09-28 is 2026-10-01.",
                optional=True,
            ),
        ],
        contract=TruthContract(
            name="FitWell Flex 12 (Studenten)",
            category="gym",
            regime="bgb309_new",
            customer_number=FW_NR,
            concluded_date="2025-01-02",
            start_date="2025-01-15",
            initial_term_months=12,
            renewal_term_months=0,
            notice_value=1,
            notice_unit="months",
            notice_basis="end_of_term",
            end_date=None,
            cost_amount=29.90,
            cost_interval="monthly",
            expected_current_term_end=None,
            expected_cancel_by=None,
            expected_earliest_exit=earliest,
            reasoning="Initial term 15.01.2025–14.01.2026 is over; now indefinite with one month's notice at any time "
            "(§ 309 Nr. 9 BGB). Notice received 2026-09-28 → ends 2026-10-28.",
        ),
        key_quotes=[FW_TERM_QUOTE, FW_AFTER_QUOTE],
    )
    return Sample(
        slug="fitnessstudio_mitgliedsvertrag",
        title="Mitgliedsvertrag FitWell Studios",
        language="de",
        received_date=dc.checked("2025-01-02", "Thu"),
        render=lambda: as_pdf(
            letter_pdf(
                FITWELL, "2025-01-02", _fitwell, follow_ref=f"Mitgliedsnummer {FW_NR}", fold_marks=False
            )
        ),
        truth=truth,
        subject_hint="Mitgliedsvertrag Fitnessstudio",
    )


# --------------------------------------------------------------------------------------------------
# Muster Versicherung: Versicherungsschein – Nachtrag (19.01.2026)
# --------------------------------------------------------------------------------------------------

VS_NR = "PHV 71-4471220"
VS_PREMIUM_QUOTE = (
    "Der nächste Jahresbeitrag in Höhe von 59,90 € wird am 01.12.2026 von Ihrem Konto abgebucht."
)
VS_TERM_QUOTE = (
    "Der Vertrag verlängert sich jeweils um ein weiteres Jahr, wenn er nicht spätestens drei Monate vor Ablauf "
    "des Versicherungsjahres in Textform gekündigt wird."
)


def _versicherung(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [
            ("Vers.-Nr.", VS_NR),
            ("Kundennummer", "K 2231 0917"),
            ("Ihr Kontakt", "Kundenservice"),
            ("Telefon", "0123 7070-0"),
            ("Datum", "19.01.2026"),
        ]
    )
    letter.subject(
        "Versicherungsschein – Nachtrag Nr. 1 zur Privat-Haftpflichtversicherung",
        sub="Grund des Nachtrags: Änderung der Anschrift und der Bankverbindung. Dieser Nachtrag ersetzt "
        "den Versicherungsschein vom 24.11.2023.",
    )
    letter.para(SALUTE_DE)
    letter.para(
        "vielen Dank für Ihre Mitteilung. Wir haben Ihre neue Anschrift und Bankverbindung gespeichert "
        "und übersenden Ihnen den aktualisierten Versicherungsschein."
    )
    letter.kv(
        [
            ("Versicherungsnehmer", f"Herr {sam.NAME}, {sam.STREET}, {sam.CITY}, geb. 14.03.2000"),
            ("Produkt", "Privat-Haftpflichtversicherung, Tarif Basis Single"),
            ("Versicherungsbeginn", "01.12.2023, 00:00 Uhr"),
            ("Versicherungsjahr", "01.12. – 30.11."),
            ("Vertragsdauer", "1 Jahr mit automatischer Verlängerung um jeweils ein Jahr"),
            ("Hauptfälligkeit", "01.12. eines jeden Jahres"),
            (
                "Deckungssummen",
                "10.000.000 € pauschal für Personen-, Sach- und Vermögensschäden; Mietsachschäden "
                "1.000.000 €; fremde Schlüssel 50.000 €; keine Selbstbeteiligung",
            ),
        ],
        key_w=44,
        bold_keys=True,
        zebra=True,
        gap=3,
    )
    letter.table(
        [
            ("Beitrag", "Nettobeitrag", "Versicherungsteuer 19 %", "Jahresbeitrag"),
            ("jährlich zum 01.12.", eur("50.34"), eur("9.56"), f"**{eur('59.90')}**"),
        ],
        (42, 33, 55, 35),
        aligns=("LEFT", "RIGHT", "RIGHT", "RIGHT"),
        head_fill=VERSICHERUNG.color,
        gap=2.5,
    )
    letter.para(
        f"Der Beitrag wird jährlich zur Hauptfälligkeit per SEPA-Lastschrift von Ihrem Konto bei der "
        f"Musterbank eG eingezogen (Mandatsreferenz {VS_NR.replace(' ', '')}-01). {VS_PREMIUM_QUOTE}"
    )
    letter.heading("Vertragslaufzeit und Kündigung")
    letter.para(VS_TERM_QUOTE)
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Muster Versicherung AG",
        signers=[("Dr. Carla Muster", "Vorsitzende des Vorstands"), ("Henrik Beispiel", "Vorstand")],
        scribble=False,
        note="Dieser Versicherungsschein wurde maschinell erstellt und ist ohne Unterschrift gültig.",
    )


def haftpflicht() -> Sample:
    """Liability insurance policy (endorsement after the move), Muster Versicherung AG, 19.01.2026."""
    # Insurance year 01.12.–30.11.; current year ends Mon 30.11.2026. Three months' notice before the end
    # → must arrive by Mon 31.08.2026 — already passed on 2026-09-28. Next window: by Tue 31.08.2027 for the
    # end of the insurance year on Tue 30.11.2027.
    current_end = dc.checked("2026-11-30", "Mon")
    dc.expect(dc.checked("2026-08-31", "Mon") < sam.SIMULATED_TODAY, "2026 window closed")
    next_cancel = dc.checked("2027-08-31", "Tue")
    next_exit = dc.checked("2027-11-30", "Tue")
    truth = Truth(
        kind="insurance",
        area="insurance",
        sender_name="Muster Versicherung AG",
        sender_kind="insurer",
        document_date="2026-01-19",
        references=[Ref("Vers.-Nr.", VS_NR), Ref("Kundennummer", "K 2231 0917")],
        amounts=[
            Amount("Jahresbeitrag", 59.90),
            Amount("Nettobeitrag", 50.34),
            Amount("Versicherungsteuer", 9.56),
        ],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Annual liability insurance premium",
                expected_due=dc.checked("2026-12-01", "Tue"),
                date_basis="fixed",
                nature="payment",
                recurrence="yearly",
                amount=59.90,
                direction="out",
                quote=VS_PREMIUM_QUOTE,
                reasoning="Explicit date 01.12.2026 (direct debit at the main due date, yearly).",
            ),
        ],
        contract=TruthContract(
            name="Privat-Haftpflichtversicherung Basis Single",
            category="insurance",
            regime="vvg11",
            customer_number=VS_NR,
            concluded_date="2023-12-01",
            start_date="2023-12-01",
            initial_term_months=12,
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
            notice_basis="end_of_term",
            end_date=None,
            cost_amount=59.90,
            cost_interval="yearly",
            expected_current_term_end=current_end,
            expected_cancel_by=next_cancel,
            expected_earliest_exit=next_exit,
            reasoning="Insurance year ends 30.11.2026; 3 months' notice → deadline 31.08.2026 already passed. Next: "
            "notice by 31.08.2027 → contract ends 30.11.2027.",
        ),
        key_quotes=[VS_PREMIUM_QUOTE, VS_TERM_QUOTE],
        tax_relevant=True,
        notes="Liability insurance premiums are Sonderausgaben (Vorsorgeaufwendungen) – usually absorbed by the "
        "Höchstbetrag.",
    )
    return Sample(
        slug="haftpflicht_versicherungsschein",
        title="Versicherungsschein Privat-Haftpflicht (Nachtrag)",
        language="de",
        received_date=dc.checked("2026-01-21", "Wed"),
        render=lambda: as_pdf(
            letter_pdf(VERSICHERUNG, "2026-01-19", _versicherung, follow_ref=f"Versicherungs-Nr. {VS_NR}")
        ),
        truth=truth,
        subject_hint="Versicherungsschein Haftpflicht",
    )


# --------------------------------------------------------------------------------------------------
# MVB: Deutschlandticket-Abo (10.12.2025)
# --------------------------------------------------------------------------------------------------

DT_ABO = "DT-2025-3304719"
DT_NOTICE_QUOTE = "Die Kündigung muss bis zum 10. eines Monats zum Ende dieses Monats bei uns eingehen."


def _deutschlandticket(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [
            ("Abonummer", DT_ABO),
            ("Kundenkonto", sam.EMAIL),
            ("Abo-Service", "0123 6300-63"),
            ("Datum", "10.12.2025"),
        ]
    )
    letter.subject("Ihr Deutschlandticket im Abonnement – Auftragsbestätigung")
    letter.para(SALUTE_DE)
    letter.para(
        "vielen Dank für Ihre Bestellung des Deutschlandtickets als Handyticket im Abonnement. Wir "
        "bestätigen Ihnen die folgenden Vertragsdaten:"
    )
    letter.kv(
        [
            ("Ticket", "Deutschlandticket, persönlich und nicht übertragbar, 2. Klasse"),
            ("Gültig ab", "01.01.2026"),
            ("Preis", "63,00 € pro Monat"),
            ("Geltungsbereich", "bundesweit in allen Verkehrsmitteln des Nahverkehrs"),
            ("Ticketmedium", "Handyticket in der App „MVB mobil“ (Anmeldung mit Ihrer E-Mail-Adresse)"),
            ("Zahlungsweise", f"SEPA-Lastschrift, Abbuchung zum Monatsanfang, Gläubiger-ID {CI_MVB}"),
        ],
        key_w=40,
        bold_keys=True,
        zebra=True,
        gap=3,
    )
    letter.heading("Laufzeit und Kündigung")
    letter.para(
        f"Das Abonnement läuft auf unbestimmte Zeit und ist monatlich kündbar. {DT_NOTICE_QUOTE} Sie können "
        "online in Ihrem Kundenkonto (Button „Abo kündigen“), per E-Mail an abo@mvb-musterstadt.example "
        "oder schriftlich kündigen."
    )
    letter.heading("Preisänderungen")
    letter.para(
        "Der Preis des Deutschlandtickets wird von Bund und Ländern festgelegt. Über Preisänderungen "
        "informieren wir Sie mindestens sechs Wochen im Voraus; Sie können dann zum Zeitpunkt des "
        "Inkrafttretens der Preisänderung kündigen."
    )
    letter.closing("Gute Fahrt wünscht Ihnen", org_line="Ihr MVB-Aboservice", scribble=False)


def deutschlandticket() -> Sample:
    """Deutschlandticket subscription confirmation, MVB, 10.12.2025."""
    # Monthly subscription; cancellation must arrive by the 10th for the end of that month. On the simulated
    # today (28.09.) September's deadline has passed; next: Sat 10.10.2026 for the end of October (Sat 31.10.).
    # A notice deadline does not move off the weekend; the safe date is Fri 09.10.2026.
    cancel_by = dc.checked("2026-10-10", "Sat")
    exit_date = dc.checked("2026-10-31", "Sat")
    truth = Truth(
        kind="contract",
        area="mobility",
        sender_name="Musterstadt Verkehrsbetriebe GmbH",
        sender_kind="transport",
        document_date="2025-12-10",
        references=[Ref("Abonummer", DT_ABO)],
        amounts=[Amount("Preis pro Monat", 63.00)],
        items=[
            TruthItem(
                kind="payment",
                title_hint="Monthly Deutschlandticket fee",
                expected_due=None,
                date_basis="none",
                nature="payment",
                recurrence="monthly",
                amount=63.0,
                direction="out",
                quote="Abbuchung zum Monatsanfang",
                reasoning="Direct debit at the start of each month; no exact day printed.",
                optional=True,
            ),
        ],
        contract=TruthContract(
            name="Deutschlandticket-Abo",
            category="transport",
            regime="bgb309_new",
            customer_number=DT_ABO,
            concluded_date="2025-12-10",
            start_date="2026-01-01",
            initial_term_months=1,
            renewal_term_months=1,
            notice_value=None,
            notice_unit=None,
            notice_basis="end_of_month",
            end_date=None,
            cost_amount=63.0,
            cost_interval="monthly",
            expected_current_term_end=None,
            expected_cancel_by=cancel_by,
            expected_earliest_exit=exit_date,
            reasoning="Cancellation by the 10th for the end of that month. 10.09. has passed → next deadline Sat "
            "10.10.2026 (safe date Fri 09.10.2026; online button works on weekends) → ends 31.10.2026.",
        ),
        key_quotes=[DT_NOTICE_QUOTE, "63,00 € pro Monat"],
        related=[
            ("rueckmeldung_sose_2027", "from SoSe 2027 the semester fee includes a Deutschlandsemesterticket")
        ],
    )
    return Sample(
        slug="deutschlandticket_abo",
        title="Deutschlandticket-Abo – Auftragsbestätigung",
        language="de",
        received_date=dc.checked("2025-12-12", "Fri"),
        render=lambda: as_pdf(
            letter_pdf(MVB, "2025-12-10", _deutschlandticket, follow_ref=f"Abonummer {DT_ABO}")
        ),
        truth=truth,
        subject_hint="Deutschlandticket Abo",
    )


# --------------------------------------------------------------------------------------------------
# Musterbank: Preisänderung, Zustimmung erforderlich (18.09.2026)
# --------------------------------------------------------------------------------------------------

BANK_CONSENT_QUOTE = "Bitte erteilen Sie Ihre Zustimmung bis zum 30.11.2026."
BANK_PRICE_QUOTE = (
    "Für Ihr Girokonto Klassik möchten wir den monatlichen Kontoführungspreis ab dem 01.12.2026 von 4,90 € auf "
    "6,90 € anpassen."
)


def _bank(letter: Letter) -> None:
    letter.address(sam.recipient())
    letter.info(
        [
            ("Kundennummer", "7004 1128"),
            ("Konto", "Girokonto Klassik"),
            ("IBAN", sam.IBAN_PRETTY),
            ("Ihre Beraterin", "Leonie Exempel"),
            ("Telefon", "0123 4000-218"),
            ("Datum", "18.09.2026"),
        ]
    )
    letter.subject(
        "Änderung unseres Preis- und Leistungsverzeichnisses zum 01.12.2026 – Ihre Zustimmung ist "
        "erforderlich"
    )
    letter.para(SALUTE_DE)
    letter.para(
        "seit vielen Jahren haben wir die Preise für unsere Kontomodelle stabil gehalten. Gestiegene Kosten "
        f"für IT-Sicherheit und Zahlungsverkehr machen nun eine Anpassung erforderlich. {BANK_PRICE_QUOTE} "
        "Alle übrigen Leistungen Ihres Kontomodells bleiben unverändert."
    )
    letter.para(
        "Nach der Rechtsprechung des Bundesgerichtshofs (Urteil vom 27.04.2021, XI ZR 26/20) benötigen wir "
        "für diese Änderung Ihre ausdrückliche Zustimmung. Ihr Schweigen gilt nicht als Zustimmung."
    )
    letter.box(
        [
            "im Online-Banking unter „Postfach › Zustimmungen“ oder",
            "mit dem beigefügten Antwortbogen, den Sie unterschrieben an uns zurücksenden.",
            f"**{BANK_CONSENT_QUOTE}**",
        ],
        title="So stimmen Sie zu",
    )
    letter.heading("Was passiert, wenn Sie nicht zustimmen?")
    letter.para(
        "Ohne Ihre Zustimmung können wir Ihr Konto nicht dauerhaft zu den bisherigen Bedingungen "
        "weiterführen. In diesem Fall behalten wir uns vor, die Geschäftsbeziehung für dieses Konto unter "
        "Einhaltung einer Frist von zwei Monaten zu kündigen (Nr. 19 Abs. 1 unserer Allgemeinen "
        "Geschäftsbedingungen). Selbstverständlich können auch Sie Ihr Girokonto jederzeit kostenfrei "
        "kündigen."
    )
    letter.para(
        "Übrigens: Für junge Leute in Ausbildung und Studium bis zum vollendeten 27. Lebensjahr bieten wir "
        "das Kontomodell „Start“ ohne monatlichen Kontoführungspreis an. Sprechen Sie uns gern an."
    )
    letter.closing(
        "Mit freundlichen Grüßen",
        org_line="Musterbank eG",
        signers=[("Stefan Muster", "Vorstand"), ("Leonie Exempel", "Privatkundenberatung")],
    )
    letter.enclosures(["Antwortbogen", "Preis- und Leistungsverzeichnis (Auszug) gültig ab 01.12.2026"])


def bank_preisaenderung() -> Sample:
    """Account fee increase asking for active consent, Musterbank eG, 18.09.2026."""
    received = dc.checked("2026-09-21", "Mon")  # dated Fri 18.09.2026; +2 days is a Sunday → Monday
    truth = Truth(
        kind="bank_letter",
        area="money",
        sender_name="Musterbank eG",
        sender_kind="bank",
        document_date="2026-09-18",
        references=[Ref("Kundennummer", "7004 1128")],
        amounts=[Amount("Kontoführungspreis bisher", 4.90), Amount("Kontoführungspreis neu", 6.90)],
        items=[
            TruthItem(
                kind="deadline",
                title_hint="Decide whether to consent to the new account fee",
                expected_due=dc.checked("2026-11-30", "Mon"),
                date_basis="fixed",
                nature="declaration",
                quote=BANK_CONSENT_QUOTE,
                reasoning="Explicit date 30.11.2026 (Monday).",
            ),
        ],
        change=TruthChange("price_increase", "2026-12-01", 4.90, 6.90, "monthly"),
        key_quotes=[BANK_CONSENT_QUOTE, BANK_PRICE_QUOTE],
        kind_alternatives=["price_increase", "contract_change"],
        notes="Saving idea: the free 'Start' account for under-27s (Sam is 26) saves 82,80 €/year.",
    )
    return Sample(
        slug="bank_preisaenderung",
        title="Änderung Preis- und Leistungsverzeichnis – Zustimmung",
        language="de",
        received_date=received,
        render=lambda: as_pdf(
            letter_pdf(MUSTERBANK_ORG, "2026-09-18", _bank, follow_ref="Kundennummer 7004 1128")
        ),
        truth=truth,
        subject_hint="Kontoführungspreis – Zustimmung",
    )
