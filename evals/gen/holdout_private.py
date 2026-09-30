"""Holdout split, families 4, 5, 6, 8, 9, 10 and 11: variants E and F of the invoices, dunning
letters, appointments, contracts, price changes, English letters and business-day periods.

Written like ``holdout_admin`` (after extraction prompt version 11, before any holdout recording, new
senders, wording and layout). The same generation rules as ``families_private`` hold: private-law
deadlines never depend on a Land's holidays, fixed dates fall on working days and Werktage counts
never end on a Saturday (all asserted).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import law
from . import orgs as O
from .common import Case, event_period_item, fixed_item, spec, today_after, truth, undated_item
from .families_admin import check, created
from .families_private import INVOICE_RULE, _contract_truth
from .holdout_admin import STYLES, place_line
from .law import fmt
from .pdf import Block, Letter, Org, P, Person, Sign, Style, Table
from .text import de, de_long, de_weekday, en_uk, en_us, eur_plain


def _invoice_table(
    rows: list[tuple[str, float]], vat: float, labels: tuple[str, str, str], header: tuple[str, str]
) -> tuple[Table, float]:
    net = round(sum(v for _, v in rows), 2)
    tax = round(net * vat, 2)
    total = round(net + tax, 2)
    body = [(label, eur_plain(v)) for label, v in rows]
    body += [(labels[0], eur_plain(net)), (labels[1], eur_plain(tax)), (labels[2], eur_plain(total))]
    n = len(rows)
    return Table(
        rows=tuple(body), header=header, value_width=32, bold_rows=(n + 2,), rule_before=(n, n + 2)
    ), total


# ==================================================================================================
# Family 4 — invoice_relative (a period of N days after the invoice date)
# ==================================================================================================


def invoice_relative() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, inv_date: date, days: int, number: str,
             customer: str, positions: list[tuple[str, float]], hand: str, intro: str, kind: str = "invoice", vat: float = 0.19,
             photo: bool = False, statement: tuple[Table, float] | None = None) -> Case:  # fmt: skip
        if variant == "E":
            table, total = _invoice_table(positions, vat, ("Zwischensumme netto", f"MwSt. {round(vat * 100)} %", "Gesamtbetrag"),
                                          ("Bezeichnung", "Betrag €"))  # fmt: skip
            pay_line = (f"Zahlungsbedingungen: {days} Tage netto ab Rechnungsdatum. Bitte geben Sie bei der Überweisung die "
                        "Rechnungsnummer als Verwendungszweck an.")  # fmt: skip
            key = f"{days} Tage netto ab Rechnungsdatum"
            info = [("Rechnung", number), ("Kunde", customer), ("Datum", de(inv_date))]
            refs = [("Rechnung", number), ("Kunde", customer)]
            date_line = None
        else:
            # a settlement (advance payments deducted after VAT) brings its own table
            table, total = statement or _invoice_table(positions, vat, ("Summe netto", f"Umsatzsteuer {round(vat * 100)} %",
                                                                        "Rechnungsendbetrag"), ("Leistung / Material", "EUR"))  # fmt: skip
            pay_line = (f"Bitte gleichen Sie diese Rechnung binnen {days} Kalendertagen nach dem Rechnungsdatum aus; Teilzahlungen "
                        "sind nach Absprache möglich.")  # fmt: skip
            key = f"binnen {days} Kalendertagen nach dem Rechnungsdatum"
            info = [("Rechnungs-Nr.", number), ("Kunden-Nr.", customer)]
            refs = [("Rechnungs-Nr.", number), ("Kunden-Nr.", customer)]
            date_line = f"{org.city}, den {de(inv_date)}"
        item = check(
            event_period_item(event=inv_date, amount=days, unit="days", region=None, kind="payment", nature="payment",
                              title=f"Rechnung {number} bezahlen", anchor="document_date", money=total, rule=INVOICE_RULE,
                              shift_citation="§ 193 BGB"),
            hand,
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, info=info, date_line=date_line, subject=f"Rechnung {number}", salutation=salutation,
            blocks=[P(intro), table, P(pay_line), Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(inv_date), running_ref=f"Rechnung {number}",
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="invoice_relative", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=inv_date, references=refs, amounts=[total], items=[item]),
            today=today_after(inv_date, case_id), authority_region=None,
            key_phrases=[de(inv_date), key, eur_plain(total)], photo=photo,
        )  # fmt: skip

    vet = O.company("Tierarztpraxis Dr. Musterfeld", "Wiesenweg 11", "37075", "Neu-Beispielstadt", monogram="TM", accent=(20, 100, 90),
                    style="minimal", tagline="Kleintiere · Chirurgie · Zahnbehandlung", phone="0551 700 12 30",
                    email="praxis@tierarzt-musterfeld.example", account="7001230")  # fmt: skip
    # E1: Fri 17.04.2026 + 14 = Fri 01.05. Tag der Arbeit → Sat, Sun → Mon 04.05.2026
    cases.append(make("holdout-invoice_relative-E1", "E", vet, O.H_GEN, "Sehr geehrte Frau Mustermeier,", date(2026, 4, 17), 14,
                      "TA-26-1187", "T-30482",
                      [("Allgemeine Untersuchung mit Beratung, Hund", 23.62), ("Zahnsteinentfernung unter Narkose", 118.40),
                       ("Narkose und Überwachung", 64.15), ("Medikamente lt. Anlage", 21.30)], "2026-05-04",
                      "für die Behandlung Ihrer Hündin „Frieda“ am 15.04.2026 berechnen wir nach der Gebührenordnung für Tierärzte:",
                      photo=True))  # fmt: skip

    garage = O.company("Autohaus Beispiel & Co. KG", "Gewerbering 4", "35041", "Musterbergen", monogram="AB", accent=(30, 30, 90),
                       style="band", tagline="Service · Reparatur · Hauptuntersuchung", phone="06421 88 77 60",
                       email="service@autohaus-beispiel.example", hr="AG Musterbergen HRA 2210", vat="USt-IdNr. DE 301 772 418",
                       account="8877600")  # fmt: skip
    # E2: Tue 13.05.2025 + 21 = Tue 03.06.2025 — a working day, no shift
    cases.append(make("holdout-invoice_relative-E2", "E", garage, O.H_GEN2, "Guten Tag Herr Beispiel,", date(2025, 5, 13), 21,
                      "WR-25-04417", "K 55120",
                      [("Inspektion nach Herstellervorgabe (60.000 km)", 189.00), ("Motoröl 5W-30, 4,5 l", 67.50),
                       ("Bremsflüssigkeit erneuern", 54.00), ("Scheibenwischer vorn", 29.90)], "2025-06-03",
                      "vielen Dank für Ihren Werkstattauftrag vom 12.05.2025 (Fahrzeug MB-TB 318). Wir berechnen:"))  # fmt: skip

    energy = O.company("Beispielwerke Versorgung GmbH", "Gaswerkstraße 2", "35039", "Musterbergen", monogram="BV", accent=(0, 80, 60),
                       style="logo", tagline="Erdgas · Strom · Wärme", phone="06421 205-0", email="abrechnung@beispielwerke.example",
                       hr="AG Musterbergen HRB 5117", vat="USt-IdNr. DE 112 450 338", account="2050000")  # fmt: skip
    # 11.842 kWh × 9,20 ct = 1.089,46 + 12 × 13,50 = 162,00 → net 1.251,46 + 19 % 237,78 = 1.489,24 − 12 × 110,00 = 169,24
    statement = Table(rows=(("Arbeitspreis: 11.842 kWh × 9,20 ct", "1.089,46"), ("Grundpreis: 12 Monate × 13,50 €", "162,00"),
                            ("Summe netto", "1.251,46"), ("Umsatzsteuer 19 %", "237,78"), ("Summe brutto", "1.489,24"),
                            ("abzüglich geleistete Abschläge (12 × 110,00 €)", "– 1.320,00"), ("Nachzahlung", "169,24")),
                      header=("Abrechnung 01.11.2025–31.10.2026", "EUR"), value_width=32, bold_rows=(6,), rule_before=(2, 4, 6))  # fmt: skip
    assert round(round(11_842 * 0.092, 2) + 162.00, 2) == 1_251.46 and round(1_251.46 * 0.19, 2) == 237.78
    # F1: Fri 27.11.2026 + 30 = Sun 27.12.2026 → Mon 28.12.2026
    cases.append(make("holdout-invoice_relative-F1", "F", energy, O.H_GEN2, "Sehr geehrter Herr Beispiel,", date(2026, 11, 27), 30,
                      "JA-26-339120", "400 218 775", [], "2026-12-28",
                      "mit dieser Jahresabrechnung für die Lieferstelle Am Mühlbach 2 rechnen wir Ihren Erdgasverbrauch ab. Nach "
                      "Verrechnung Ihrer Abschläge ergibt sich eine Nachzahlung.", kind="utility_bill", photo=True,
                      statement=(statement, 169.24)))  # fmt: skip

    roofer = O.company("Dachdeckerei Muster", "Schieferweg 7", "37079", "Neu-Beispielstadt", monogram="DM", accent=(80, 40, 30),
                       tagline="Dach · Fassade · Dachrinnen", phone="0551 30 40 50", email="buero@dachdeckerei-muster.example",
                       account="3040500")  # fmt: skip
    # F2: Wed 04.02.2026 + 10 = Sat 14.02.2026 → Sun → Mon 16.02.2026
    cases.append(make("holdout-invoice_relative-F2", "F", roofer, O.H_GEN, "Sehr geehrte Frau Mustermeier,", date(2026, 2, 4), 10,
                      "D-2026-038", "1471",
                      [("Sturmschaden: 14 Dachziegel ersetzt, Material", 96.60), ("Arbeitszeit 2 Gesellen, 3 Std.", 297.00),
                       ("Hubsteiger", 85.00)], "2026-02-16",
                      "nach dem Sturm vom 29.01.2026 haben wir am 02.02.2026 Ihr Dach in der Birkenallee 15 repariert. Wir erlauben uns "
                      "zu berechnen:"))  # fmt: skip
    return cases


# ==================================================================================================
# Family 5 — dunning_fixed (pay by an explicit date)
# ==================================================================================================


def dunning_fixed() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, due: date, due_text: str,
             subject: str, refs: list[tuple[str, str]], amount: float, fee: float, body: str, pay: str, signer: str,
             kind: str = "dunning", photo: bool = False) -> Case:  # fmt: skip
        total = round(amount + fee, 2)
        item = check(
            fixed_item(due=due, region=None, kind="payment", nature="payment", title="Offenen Betrag bezahlen", money=total,
                       rule="Payment date stated in the reminder."),
            due.isoformat(),
        )  # fmt: skip
        rows = (
            [("Rechnungsbetrag", eur_plain(amount))]
            + ([("Mahnkosten", eur_plain(fee))] if fee else [])
            + [("Offen", eur_plain(total))]
        )
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation,
            info=[*refs, ("Datum", de(letter_date))] if variant == "E" else list(refs),
            date_line=None if variant == "E" else place_line(org, letter_date),
            blocks=[P(body), Table(rows=tuple(rows), header=("Forderung", "€"), bold_rows=(len(rows) - 1,), rule_before=(len(rows) - 1,)),
                    P(pay.format(due=due_text)), Sign("Freundliche Grüße" if variant == "E" else "Mit freundlichen Grüßen", (signer,))],
            style=STYLES[variant], created=created(letter_date), running_ref=" · ".join(f"{a} {b}" for a, b in refs),
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="dunning_fixed", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[total], items=[item]),
            today=today_after(letter_date, case_id), authority_region=None,
            key_phrases=[de(letter_date), due_text.replace("**", ""), eur_plain(total)], photo=photo,
        )  # fmt: skip

    shop = O.company("Beispiel Wohnwelt GmbH", "Möbelallee 1", "36043", "Musterfulda", monogram="BW", accent=(90, 50, 20), style="band",
                     tagline="Möbel online – geliefert bis in die Wohnung", phone="0661 250 90 90",
                     email="zahlung@beispiel-wohnwelt.example", hr="AG Musterfulda HRB 7720", account="2509090")  # fmt: skip
    due = date(2026, 8, 28)  # Fri, a working day everywhere
    cases.append(make(
        "holdout-dunning_fixed-E1", "E", shop, O.H_GEN, "Sehr geehrte Frau Mustermeier,", date(2026, 8, 18), due, f"bis {de_weekday(due)}",
        "Zahlungserinnerung zu Ihrer Bestellung 7710-2291", [("Kundennummer", "WW-448120"), ("Bestellnummer", "7710-2291")], 249.00, 0.0,
        "Ihr Sideboard „Linnea“ wurde am 24.07.2026 geliefert. Leider ist der Rechnungsbetrag bei uns noch nicht eingegangen – "
        "vielleicht ist die Rechnung im Umzugstrubel untergegangen.",
        "Überweisen Sie den offenen Betrag bitte {due}. Sollten Sie inzwischen bezahlt haben, danken wir Ihnen und bitten Sie, "
        "diese Erinnerung zu ignorieren.", "Ihr Team der Beispiel Wohnwelt", photo=True,
    ))  # fmt: skip

    billing = O.company("Muster Abrechnungszentrum für Zahnärzte GmbH", "Kaiserplatz 9", "40212", "Musterdorf", monogram="MA",
                        accent=(0, 70, 110), style="logo", tagline="Abrechnung im Auftrag Ihrer Zahnarztpraxis", phone="0211 555 71 00",
                        email="patienten@muster-abrechnung.example", hr="AG Musterdorf HRB 60 118", account="5557100")  # fmt: skip
    due = date(2026, 8, 21)  # Fri
    cases.append(make(
        "holdout-dunning_fixed-E2", "E", billing, O.H_GEN2, "Sehr geehrter Herr Beispiel,", date(2026, 8, 7), due, f"bis **{de(due)}**",
        "2. Mahnung – Rechnung der Zahnarztpraxis Dr. Beispielhaus", [("Rechnungsnummer", "ZA-26-118503"), ("Patientennummer", "40931")],
        412.80, 5.00,
        "die Zahnarztpraxis Dr. Beispielhaus hat uns mit der Abrechnung Ihrer Behandlung vom 18.05.2026 beauftragt. Auf unsere "
        "Rechnung vom 02.06.2026 und die Zahlungserinnerung vom 10.07.2026 haben Sie bisher nicht reagiert.",
        "Wir erwarten Ihre Zahlung {due}. Sollten Sie Einwände gegen die Rechnung haben, rufen Sie uns bitte an, damit wir sie "
        "vorher klären können.", "Muster Abrechnungszentrum – Patientenservice",
    ))  # fmt: skip

    club = O.company("TSV Beispielstadt 1898 e.V.", "Sportplatzweg 3", "37081", "Neu-Beispielstadt", monogram="TSV", accent=(0, 90, 40),
                     style="minimal", tagline="Geschäftsstelle · Mitgliederverwaltung", phone="0551 60 18 98",
                     email="beitraege@tsv-beispielstadt.example", account="6018980")  # fmt: skip
    due = date(2027, 6, 4)  # Fri
    cases.append(make(
        "holdout-dunning_fixed-F1", "F", club, O.H_GEN, "Liebe Frau Mustermeier,", date(2027, 5, 21), due,
        f"bis einschließlich **{de_long(due)}**", "Mahnung: Mitgliedsbeitrag 2027", [("Mitgliedsnummer", "M-1898-2207")], 180.00, 3.00,
        "leider konnten wir den Jahresbeitrag 2027 für Ihre Mitgliedschaft in der Abteilung Tennis nicht abbuchen; die Lastschrift "
        "wurde mangels Deckung zurückgegeben. Die Bankgebühr stellen wir Ihnen als Mahnkosten in Rechnung.",
        "Wir bitten Sie, den Rückstand {due} auf das unten genannte Vereinskonto zu überweisen. Geht bis dahin keine Zahlung ein, "
        "ruht Ihr Spielrecht nach § 5 unserer Beitragsordnung, bis der Betrag ausgeglichen ist.", "Der Vorstand – Kassenwartin",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 6 — appointment
# ==================================================================================================


def appointment() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, when: date, time: str,
             subject: str, refs: list[tuple[str, str]], body: list[Block], key: list[str], kind: str = "appointment",
             photo: bool = False, note: str = "", amounts: list[float] | None = None) -> Case:  # fmt: skip
        item = check(
            fixed_item(due=when, region=org.region, kind="appointment", nature="appointment", title=subject, time=time,
                       rule="Appointment set by the sender; appointments are never shifted.", appointment=True),
            when.isoformat(),
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation,
            info=[*refs, ("Datum", de(letter_date))] if variant == "E" else list(refs),
            date_line=None if variant == "E" else place_line(org, letter_date),
            blocks=[*body, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="appointment", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=amounts or [], items=[item]),
            today=today_after(letter_date, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), *key], photo=photo, notes=note,
        )  # fmt: skip

    standesamt = Org(name="Verbandsgemeindeverwaltung Musterweiler – Standesamt", kind="authority", street="Rathausstraße 1",
                     postcode="54470", city="Musterweiler", region="RP", head=("Land Rheinland-Pfalz", "Standesamt Musterweiler"),
                     phone="06531 71-120", email="standesamt@vg-musterweiler.example", style="authority", accent=(95, 30, 50))  # fmt: skip
    when = date(2026, 9, 1)  # Tue
    cases.append(make(
        "holdout-appointment-E1", "E", standesamt, O.H_RP, "Sehr geehrte Frau Beispielkamp,", date(2026, 8, 7), when, "10:15",
        "Terminbestätigung: Anmeldung der Eheschließung", [("Vorgangs-Nr.", "STA-2026-0417")],
        [P("für Sie und Ihren Partner haben wir folgenden Termin zur Anmeldung der Eheschließung reserviert: "
           f"**{de_weekday(when)}, 10:15 Uhr**, Rathaus Musterweiler, Zimmer 12 im Erdgeschoss."),
         P("Bitte kommen Sie beide persönlich und bringen Sie Ihre gültigen Ausweise sowie beglaubigte Abschriften aus dem "
           "Geburtenregister mit, die nicht älter als sechs Monate sind. Die Gebühr für die Anmeldung beträgt 80,00 €; Sie können "
           "vor Ort bar oder mit Karte zahlen.")],
        [de_weekday(when), "10:15 Uhr"], amounts=[80.0],
    ))  # fmt: skip

    gesundheitsamt = Org(name="Landkreis Beispielstedt – Gesundheitsamt", kind="authority", street="Am Kreishaus 5", postcode="29221",
                         city="Beispielstedt", region="NI", head=("Land Niedersachsen · Landkreis Beispielstedt",
                                                                 "Kinder- und Jugendgesundheitsdienst"),
                         phone="05141 916-530", email="kjgd@lk-beispielstedt.example", style="band", accent=(30, 70, 40))  # fmt: skip
    when = date(2025, 4, 2)  # Wed
    cases.append(make(
        "holdout-appointment-E2", "E", gesundheitsamt, O.H_NI, "Sehr geehrte Frau Musterjohann,", date(2025, 3, 11), when, "08:40",
        "Einladung zur Schuleingangsuntersuchung für Ihr Kind Paula", [("Unser Zeichen", "53.2-SEU-25-1182")],
        [P(f"Ihr Kind wird im Sommer 2025 schulpflichtig. Wir laden Sie und Paula deshalb zur Schuleingangsuntersuchung ein: "
           f"**am {de(when)} um 08:40 Uhr** im Gesundheitsamt, Am Kreishaus 5, Raum 014."),
         P("Bitte bringen Sie das gelbe Kinderuntersuchungsheft, den Impfausweis und – falls vorhanden – Brille oder Hörgeräte "
           "Ihres Kindes mit. Die Untersuchung dauert etwa eine Stunde und ist kostenlos. Passt Ihnen der Termin nicht, rufen Sie "
           "uns bitte unter 05141 916-530 an.")],
        [de(when), "08:40 Uhr"], photo=True,
    ))  # fmt: skip

    manager = O.company("Beispiel Immobilienverwaltung GmbH", "Marktplatz 6", "35037", "Musterbergen", monogram="BI", accent=(60, 60, 60),
                        style="logo", tagline="Miet- und WEG-Verwaltung", phone="06421 33 90 10", email="mieter@beispiel-immo.example",
                        account="3390100")  # fmt: skip
    when = date(2025, 3, 15)  # a Saturday: appointments are not shifted
    cases.append(make(
        "holdout-appointment-F1", "F", manager, O.H_GEN2, "Sehr geehrter Herr Beispiel,", date(2025, 2, 19), when, "09:30",
        "Ihre Kündigung zum 31.03.2025 – Termin für die Wohnungsabnahme", [("Mietvertrag-Nr.", "MV-3317-08")],
        [P("wir bestätigen den Eingang Ihrer Kündigung vom 20.12.2024 zum 31.03.2025. Für die Abnahme der Wohnung Am Mühlbach 2, "
           f"2. OG rechts, schlagen wir folgenden Termin vor: **Samstag, {de(when)}, 09:30 Uhr**, Treffpunkt vor der Wohnungstür."),
         P("Bitte übergeben Sie uns dabei alle Schlüssel (laut Übergabeprotokoll fünf Stück), und lesen Sie die Zählerstände "
           "gemeinsam mit uns ab. Die Wohnung ist besenrein und ohne Einbauten zurückzugeben, die bei Mietbeginn nicht vorhanden waren.")],
        [de(when), "09:30 Uhr"], kind="rent_lease", note="Saturday appointment: must not be moved to Monday.",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 8 — contract_confirmation (secondary metric: contract terms, current_term_end, cancel_by)
# ==================================================================================================


def contract_confirmation() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, subject: str,
             refs: list[tuple[str, str]], blocks: list[Block], contract: dict[str, Any], key: list[str], kind: str = "contract") -> Case:  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation,
            info=[*refs, ("Datum", de(letter_date))] if variant == "E" else list(refs),
            date_line=None if variant == "E" else place_line(org, letter_date),
            blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="contract_confirmation", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[contract["price"]], items=[],
                        contract=contract),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), *key],
        )  # fmt: skip

    # E1 — fibre internet, § 56 TKG: 12 months from provision Tue 08.04.2025 → Tue 07.04.2026; 1 month → Sat 07.03.2026.
    fibre = O.company("Beispiel Glasfaser GmbH", "Lichtweg 20", "37077", "Neu-Beispielstadt", monogram="BG", accent=(0, 70, 130),
                      style="band", tagline="Glasfaser bis in Ihre Wohnung", phone="0800 707 30 30", email="auftrag@beispiel-glasfaser.example",
                      hr="AG Neu-Beispielstadt HRB 2071", account="7073030")  # fmt: skip
    case_id, concluded, start = "holdout-contract_confirmation-E1", date(2025, 3, 19), date(2025, 4, 8)
    contract = _contract_truth(category="internet", regime="tkg56", party_kind="telecom", concluded=concluded, start=start, initial=12,
                               renewal="indefinite, cancellable any time with 1 month notice (§ 56 Abs. 3 TKG)", notice=1,
                               notice_unit="months", today=today_after(concluded, case_id), price=39.95, interval="monthly",
                               citations="Telecom consumer contract: § 56 TKG (max. 24 months; after that 1 month any time).")  # fmt: skip
    assert (
        contract["expected_current_term_end"] == "2026-04-07"
        and contract["expected_cancel_by"] == "2026-03-07"
    )
    cases.append(make(case_id, "E", fibre, O.H_GEN, "Guten Tag Frau Mustermeier,", concluded,
                      "Auftragsbestätigung und Vertragszusammenfassung – Glasfaser 300", [("Kundennummer", "BG-220-4471"),
                                                                                         ("Auftragsnummer", "A-25-031977")],
                      [P(f"vielen Dank für Ihre Bestellung vom {de(concluded)}. Wir stellen Ihren Anschluss am {de(start)} bereit; "
                         "der Techniker meldet sich vorher bei Ihnen."),
                       Table(rows=(("Produkt", "Glasfaser 300 (300/150 Mbit/s)"), ("Bereitstellung", de(start)),
                                   ("Monatlicher Preis", "39,95 €"),
                                   ("Mindestvertragslaufzeit", "12 Monate ab Bereitstellung"),
                                   ("Erste Kündigungsmöglichkeit", "zum Ablauf von 12 Monaten ab Bereitstellung"),
                                   ("Kündigungsfrist", "ein Monat"),
                                   ("Danach", "unbefristet; Kündigung jederzeit mit einem Monat Frist")),
                             header=("Ihre Vertragsdaten", ""), value_width=108, value_align="L"),
                       P("Die Vertragszusammenfassung nach § 54 TKG ist Teil Ihres Vertrags; die Leistungsbeschreibung und die AGB "
                         "finden Sie in Ihrem Kundenkonto.")],
                      contract, ["12 Monaten ab Bereitstellung", "39,95 €"]))  # fmt: skip

    # F1 — car insurance, § 11 VVG: 1 year from Mon 15.03.2027 → Tue 14.03.2028; 1 month → Mon 14.02.2028.
    insurer = O.company("Beispiel Direktversicherung AG", "Policenweg 2", "50670", "Musterköln", monogram="BD", accent=(120, 0, 50),
                        style="logo", tagline="Kfz · Haftpflicht · Hausrat", phone="0221 700 40 00",
                        email="vertrag@beispiel-direkt.example", hr="AG Musterköln HRB 88 204", account="7004000")  # fmt: skip
    case_id, concluded, start = "holdout-contract_confirmation-F1", date(2027, 3, 4), date(2027, 3, 15)
    contract = _contract_truth(category="insurance", regime="vvg11", party_kind="insurer", concluded=concluded, start=start, initial=12,
                               renewal="renews by 1 year unless cancelled 1 month before the end of the insurance year", notice=1,
                               notice_unit="months", today=today_after(concluded, case_id), price=486.20, interval="yearly",
                               citations="Insurance contract: § 11 VVG (yearly renewal, notice as written, max. 3 months).")  # fmt: skip
    assert (
        contract["expected_current_term_end"] == "2028-03-14"
        and contract["expected_cancel_by"] == "2028-02-14"
    )
    cases.append(make(case_id, "F", insurer, O.H_GEN2, "Sehr geehrter Herr Beispiel,", concluded,
                      "Versicherungsschein Kfz-Haftpflicht- und Teilkaskoversicherung", [("Versicherungsscheinnummer", "KF-7731-220-05")],
                      [P("wir freuen uns, dass Sie Ihr Fahrzeug bei uns versichern. Ihr Vertrag im Einzelnen:"),
                       Table(rows=(("Beginn des Versicherungsschutzes", f"{de(start)}, 0 Uhr"),
                                   ("Fahrzeug", "Beispiel Kombi 1.5, amtl. Kz. MB-TB 318"),
                                   ("Umfang", "Haftpflicht, Teilkasko mit 150 € Selbstbeteiligung"),
                                   ("Vertragsdauer", "ein Jahr"), ("Jahresbeitrag", "486,20 €"), ("Zahlungsweise", "jährlich im Voraus")),
                             header=("Versicherungsdaten", ""), value_width=96, value_align="L"),
                       P("Kündigen Sie den Vertrag nicht spätestens einen Monat vor dem Ende eines Versicherungsjahres in Textform, "
                         "läuft er automatisch ein weiteres Jahr."),
                       P("Den Jahresbeitrag buchen wir zum Beginn des Versicherungsschutzes von Ihrem Konto ab.")],
                      contract, ["einen Monat vor dem Ende eines Versicherungsjahres", "486,20 €"], kind="insurance"))  # fmt: skip
    return cases


# ==================================================================================================
# Family 9 — price_increase (special-cancellation window; items optional, headline unaffected)
# ==================================================================================================


def price_increase() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, effective: date, regime: str,
             old: float, new: float, subject: str, refs: list[tuple[str, str]], blocks: list[Block], key: list[str],
             category: str) -> Case:  # fmt: skip
        cancel_by = effective - timedelta(days=1)
        why = f"Effective {fmt(effective)}. " + (
            "§ 41 Abs. 5 EnWG: the customer may cancel without notice with effect from the change; the cancellation must reach the "
            f"supplier before the new price applies (BNetzA), i.e. by {fmt(cancel_by)}; the contract then ends on that day. No § 193 shift."
            if regime == "enwg41_5"
            else "§ 57 Abs. 1 TKG: special cancellation within three months of receipt of the notice; to avoid ever paying the new price "
            f"the cancellation must be received before the change takes effect, i.e. by {fmt(cancel_by)}. The three-month window depends "
            "on the (unknown) receipt date; from the letter date it would end on "
            + law.add_months(letter_date, 3).isoformat()
            + " at the earliest."
        )  # fmt: skip
        optional = [undated_item(kind="deadline", nature="notice", title="Sonderkündigung vor Inkrafttreten der Preiserhöhung",
                                 spec=spec("fixed", anchor="explicit_date", date_=cancel_by, shift=False), derivation=why,
                                 expected_due=cancel_by.isoformat())]  # fmt: skip
        change = {
            "type": "price_increase",
            "category": category,
            "effective_date": effective.isoformat(),
            "old_amount": old,
            "new_amount": new,
            "cost_interval": "monthly",
            "extra_cost_per_year": round((new - old) * 12, 2),
            "special_cancellation": {
                "basis": "§ 41 Abs. 5 EnWG" if regime == "enwg41_5" else "§ 57 Abs. 1 TKG",
                "cancel_by_to_avoid_new_price": cancel_by.isoformat(),
                "window_end": cancel_by.isoformat() if regime == "enwg41_5" else None,
                "window_end_if_received_on_letter_date": None
                if regime == "enwg41_5"
                else law.add_months(letter_date, 3).isoformat(),
                "derivation": why,
            },
        }
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation,
            info=[*refs, ("Datum", de(letter_date))] if variant == "E" else list(refs),
            date_line=None if variant == "E" else place_line(org, letter_date),
            blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="price_increase", variant=variant, letter=letter,
            truth=truth(kind="price_increase", sender=org.name, document_date=letter_date, references=refs, amounts=[old, new], items=[],
                        optional_items=optional, price_change=change),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), de(effective), *key],
        )  # fmt: skip

    power = O.company("Beispielstrom GmbH", "Windparkstraße 8", "26122", "Beispielburg", monogram="BS", accent=(0, 90, 110), style="band",
                      tagline="Strom aus erneuerbaren Quellen", phone="0441 36 36 100", email="kundenservice@beispielstrom.example",
                      account="3636100")  # fmt: skip
    eff = date(2025, 8, 1)
    cases.append(make(
        "holdout-price_increase-E1", "E", power, O.H_GEN, "Guten Tag Frau Mustermeier,", date(2025, 6, 18), eff, "enwg41_5", 64.00, 71.00,
        f"Ihr Stromtarif „Beispielstrom Natur“: neue Preise ab {de(eff)}", [("Vertragsnummer", "BS-5190-3327")],
        [P(f"ab dem **{de(eff)}** gelten für Ihren Tarif neue Preise. Die Netzbetreiber haben ihre Entgelte erhöht, und diese Kosten "
           "müssen wir weitergeben."),
         Table(rows=(("Arbeitspreis brutto", "28,90 → 32,40 ct/kWh"), ("Grundpreis brutto", "11,50 → 12,90 €/Monat"),
                     ("Ihr Abschlag", "64,00 € → 71,00 €")), header=("", "bisher → neu"), value_width=58),
         P("Wenn Sie mit der Anpassung nicht einverstanden sind, können Sie Ihren Liefervertrag fristlos auf den Tag kündigen, an dem "
           "die neuen Preise gelten (§ 41 Abs. 5 EnWG). Eine E-Mail an uns genügt.")],
        ["fristlos auf den Tag kündigen"], "energy",
    ))  # fmt: skip

    cable = O.company("Beispiel Kabel & Web GmbH", "Antennenweg 5", "04315", "Musterleipzig", monogram="KW", accent=(70, 20, 100),
                      style="logo", tagline="Kabel-TV · Internet · Telefon", phone="0800 222 44 88", email="service@beispiel-kabelweb.example",
                      account="2224488")  # fmt: skip
    eff = date(2027, 6, 1)
    cases.append(make(
        "holdout-price_increase-F1", "F", cable, O.H_GEN2, "Sehr geehrter Herr Beispiel,", date(2027, 4, 19), eff, "tkg57", 34.99, 37.99,
        "Änderung des monatlichen Grundpreises Ihres Tarifs „Web & TV 250“", [("Kundennummer", "KW-88-104577")],
        [P(f"zum {de(eff)} erhöht sich der monatliche Grundpreis Ihres Tarifs „Web & TV 250“ von 34,99 € auf **37,99 €**. Grund "
           "sind gestiegene Kosten für Programmlizenzen und Netzbetrieb; der Leistungsumfang bleibt gleich."),
         P("Weil die Preisanpassung für Sie nachteilig ist, dürfen Sie den Vertrag nach § 57 Abs. 1 TKG außerordentlich kündigen – "
           "ohne Kosten und ohne Frist, innerhalb von drei Monaten, nachdem Ihnen diese Mitteilung zugegangen ist. Die Kündigung "
           "wird frühestens zu dem Tag wirksam, an dem die Änderung in Kraft tritt.")],
        ["innerhalb von drei Monaten, nachdem Ihnen diese Mitteilung zugegangen ist"], "internet",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 10 — english_letter
# ==================================================================================================


def english_letter() -> list[Case]:
    cases: list[Case] = []
    styles = {
        "E": Style(body_pt=9.9, left=24, right=20, leading=1.36, para_gap=2.4, align="L", subject_pt=11.0),
        "F": Style(body_pt=10.3, left=26, right=26, leading=1.28, para_gap=2.0, align="L", info_label_pt=7.6),
    }

    def letter_for(org: Org, person: Person, info: list[tuple[str, str]], subject: str, blocks: list[Block], variant: str,
                   when: date, salutation: str, closing: str) -> Letter:  # fmt: skip
        return Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation,
                      blocks=[*blocks, Sign(closing, (org.name,))], style=styles[variant], created=created(when), lang="en")  # fmt: skip

    # E1 — employer's HR team in English, UK-style fixed date: Fri 6 June 2025.
    employer = O.company("Beispiel Software Solutions GmbH", "Hafenkante 3", "20457", "Hamburg", monogram="BS", accent=(20, 50, 90),
                         style="minimal", tagline="People & Culture", phone="+49 40 555 3100", email="people@beispiel-software.example",
                         account="5553100", hr="AG Hamburg HRB 170 221")  # fmt: skip
    when, due = date(2025, 5, 12), date(2025, 6, 6)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration", title="Upload onboarding documents to the HR portal",
                            rule="Fixed date stated in the letter."), "2025-06-06")  # fmt: skip
    cases.append(Case(
        id="holdout-english_letter-E1", split="holdout", family="english_letter", variant="E",
        letter=letter_for(employer, O.H_EN, [("Employee no.", "E-20417"), ("Date", en_uk(when))], "Before you start: documents we still need", [
            P("Welcome aboard! Your first working day with us is 1 July 2025. Before we can run your first payroll, we still need a "
              "few documents from you."),
            P("Please upload your tax identification number (Steuer-ID), your health insurance membership certificate and a copy of "
              f"your residence permit to the HR portal **no later than {en_uk(due)}**. Without them we cannot register you for social "
              "security on time."),
        ], "E", when, "Dear Ms Okafor,", "Best wishes,"),
        truth=truth(kind="employment", sender=employer.name, document_date=when, references=[("Employee no.", "E-20417")], amounts=[],
                    items=[item], lang="en"),
        today=today_after(when, "holdout-english_letter-E1"), authority_region=None, key_phrases=[en_uk(when), en_uk(due)], photo=True,
    ))  # fmt: skip

    # E2 — language school invoice in English: 14 days from the invoice date. Tue 5 Aug 2025 + 14 = Tue 19 Aug 2025.
    school = O.company("Beispiel Language Academy GmbH", "Weender Straße 40", "37073", "Neu-Beispielstadt", monogram="LA",
                       accent=(140, 40, 20), style="band", tagline="German courses for international residents",
                       phone="+49 551 555 2040", email="office@beispiel-language.example", account="5552040")  # fmt: skip
    when = date(2025, 8, 5)
    total = 794.50
    item = check(event_period_item(event=when, amount=14, unit="days", region=None, kind="payment", nature="payment",
                                   title="Pay invoice BLA-25-0812", anchor="document_date", money=total,
                                   rule="Payment within 14 days from the invoice date (invoice day not counted).",
                                   shift_citation="§ 193 BGB", require_no_shift=True), "2025-08-19")  # fmt: skip
    cases.append(Case(
        id="holdout-english_letter-E2", split="holdout", family="english_letter", variant="E",
        letter=letter_for(school, O.H_EN2, [("Invoice", "BLA-25-0812"), ("Student no.", "S-7731"), ("Date", en_uk(when))],
                          "Invoice – intensive German course B1.1", [
            P("Thank you for enrolling in our intensive German course B1.1 (18 August to 12 September 2025)."),
            Table(rows=(("Intensive course B1.1, 80 lessons", "760,00"), ("Course materials", "34,50"),
                        ("Total (exempt from VAT, § 4 Nr. 21 UStG)", "794,50")), header=("Item", "EUR"), bold_rows=(2,), rule_before=(2,)),
            P("Payment is due within 14 days from the invoice date; please quote your student number with the transfer."),
        ], "E", when, "Dear Mr Fitzgerald,", "Best wishes,"),
        truth=truth(kind="invoice", sender=school.name, document_date=when, references=[("Invoice", "BLA-25-0812"), ("Student no.", "S-7731")],
                    amounts=[total], items=[item], lang="en"),
        today=today_after(when, "holdout-english_letter-E2"), authority_region=None,
        key_phrases=[en_uk(when), "within 14 days from the invoice date"],
    ))  # fmt: skip

    # F1 — US college, US long-form dates: documents must reach the office by Tue April 29, 2025.
    college = O.company("Example Liberal Arts College", "12 Beispiel Avenue", "MA 01002", "Amherst", monogram="EC", accent=(90, 20, 40),
                        style="logo", tagline="Office of Global Education", phone="+1 413 555 0190", email="global@example-college.example",
                        account="1901901", country="USA")  # fmt: skip
    college = Org(
        **{**college.__dict__, "iban": "", "bank": "", "bic": "", "postcode": "", "city": "Amherst, MA 01002"}
    )
    when, due = date(2025, 4, 3), date(2025, 4, 29)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration", title="Return enrollment confirmation",
                            rule="Fixed date stated in the letter."), "2025-04-29")  # fmt: skip
    cases.append(Case(
        id="holdout-english_letter-F1", split="holdout", family="english_letter", variant="F",
        letter=letter_for(college, O.H_EN, [("Student ID", "ELAC-25-40917"), ("Date", en_us(when))], "Your exchange semester in Fall 2025", [
            P("Congratulations on your admission to our exchange semester in Fall 2025."),
            P(f"To hold your place, your signed enrollment confirmation must reach our office by **{en_us(due)}**. Places that are not "
              "confirmed by then will be offered to students on the waitlist."),
        ], "F", when, "Dear Aisha Okafor:", "Sincerely,"),
        truth=truth(kind="university", sender=college.name, document_date=when, references=[("Student ID", "ELAC-25-40917")], amounts=[],
                    items=[item], lang="en"),
        today=today_after(when, "holdout-english_letter-F1"), authority_region=None, key_phrases=[en_us(when), en_us(due)],
    ))  # fmt: skip

    # F2 — the ambiguous one: 05/06/2026 = Wed 6 May (US) or Fri 5 June (day/month) — both plausible working days; the
    # letter's own date 03/03/2026 is symmetric and the salutation ends with a comma (no locale hint).
    summer = O.company("Beispiel International Summer School", "Campusallee 9", "35032", "Musterbergen", monogram="IS",
                       accent=(0, 80, 80), style="minimal", tagline="Summer School Office", phone="+49 6421 555 900",
                       email="summer@beispiel-iss.example", account="5559000")  # fmt: skip
    when = date(2026, 3, 3)  # printed 03/03/2026
    a, b = date(2026, 5, 6), date(2026, 6, 5)
    amb = undated_item(kind="deadline", nature="declaration", title="Send the signed code of conduct and emergency contact form",
                       spec=spec("fixed", anchor="explicit_date", shift=False), expected_due="ambiguous",
                       derivation=f"'05/06/2026' reads as {fmt(a)} (US month/day) or {fmt(b)} (day/month); the letter gives no reliable "
                                  "locale hint (a German sender writing English, its own date 03/03/2026 is symmetric), so the date is "
                                  "ambiguous and must not be stated confidently.",
                       candidates=[a.isoformat(), b.isoformat()])  # fmt: skip
    cases.append(Case(
        id="holdout-english_letter-F2", split="holdout", family="english_letter", variant="F",
        letter=letter_for(summer, O.H_EN2, [("Participant no.", "ISS-26-0277"), ("Date", "03/03/2026")], "Your registration for the Summer School 2026", [
            P("Thank you for registering for the International Summer School 2026."),
            P("Please send us the signed code of conduct and your emergency contact form by **05/06/2026**; we cannot confirm your "
              "room until we have both."),
        ], "F", when, "Dear Mr Fitzgerald,", "Best regards,"),
        truth=truth(kind="university", sender=summer.name, document_date=when, references=[("Participant no.", "ISS-26-0277")], amounts=[],
                    items=[amb], expect_low_confidence=True, lang="en"),
        today=today_after(when, "holdout-english_letter-F2"), authority_region=None, key_phrases=["03/03/2026", "05/06/2026"],
        notes="Intentionally ambiguous numeric date; truth is 'ambiguous' (document date assumed 3 March, symmetric).",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 11 — relative_business_days (Werktage Mon–Sat vs Arbeitstage Mon–Fri, holidays excluded)
# ==================================================================================================


def business_days() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, amount: int, unit: str,
             phrase: str, subject: str, refs: list[tuple[str, str]], body_before: str, task: str, hand: str, kind: str,
             photo: bool = False) -> Case:  # fmt: skip
        label = "Werktage: Monday–Saturday excluding public holidays (general meaning, cf. § 3 Abs. 2 BUrlG; defined in the letter)" if unit == "werktage" \
            else "Arbeitstage: Monday–Friday excluding public holidays (defined in the letter)"  # fmt: skip
        item = check(
            event_period_item(event=letter_date, amount=amount, unit=unit, region=None, kind="deadline", nature="declaration", title=task,
                              anchor="document_date", rule=f"Period of {amount} {label}, counted from the day after the letter date (§ 187 Abs. 1 BGB).",
                              shift_citation="§ 193 BGB", forbid_saturday_end=unit == "werktage", require_no_shift=True),
            hand,
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation,
            info=[*refs, ("Datum", de(letter_date))] if variant == "E" else list(refs),
            date_line=None if variant == "E" else place_line(org, letter_date),
            blocks=[P(body_before), P(phrase), Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant],
            created=created(letter_date),
        )  # fmt: skip
        key = phrase.split("**")[1]
        return Case(
            id=case_id, split="holdout", family="relative_business_days", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[], items=[item]),
            today=today_after(letter_date, case_id, 1, 3), authority_region=None, key_phrases=[de(letter_date), key], photo=photo,
        )  # fmt: skip

    coop = O.company("Wohnungsbaugenossenschaft Beispielbau eG", "Genossenschaftsweg 1", "37083", "Neu-Beispielstadt", monogram="WB",
                     accent=(40, 80, 50), style="logo", tagline="Wohnen mit Zukunft seit 1921", phone="0551 38 38 0",
                     email="technik@beispielbau.example", account="3838000")  # fmt: skip
    # E1: Wed 16.12.2026, 10 Werktage: Do 17(1) Fr 18(2) Sa 19(3) Mo 21(4) Di 22(5) Mi 23(6) Do 24(7) [Fr 25., Sa 26. Feiertage,
    #     So 27.] Mo 28(8) Di 29(9) Mi 30(10) → Wed 30.12.2026
    cases.append(make("holdout-relative_business_days-E1", "E", coop, O.H_GEN, "Sehr geehrte Frau Mustermeier,", date(2026, 12, 16), 10,
                      "werktage",
                      "Teilen Sie uns bitte **innerhalb von 10 Werktagen ab dem Briefdatum** mit (Werktage sind Montag bis Samstag außer "
                      "gesetzlichen Feiertagen), ob Sie den Termin wahrnehmen können. Ohne Ihre Rückmeldung müssen wir einen Ersatztermin "
                      "festlegen.",
                      "Fensteraustausch in Ihrer Wohnung – Ihre Rückmeldung zum Termin", [("Nutzungsvertrag", "NV-15-07")],
                      "im Januar 2027 tauschen wir im Haus Birkenallee 15 alle Fenster aus. Für Ihre Wohnung ist der 12.01.2027 "
                      "vorgesehen; die Arbeiten beginnen um 7:30 Uhr und dauern etwa sechs Stunden.",
                      "Rückmeldung zum Termin für den Fensteraustausch", "2026-12-30", "rent_lease"))  # fmt: skip

    pkv = O.company("Beispiel Krankenversicherung a.G.", "Gesundheitsring 12", "50668", "Musterköln", monogram="BK", accent=(0, 60, 100),
                    style="band", tagline="Private Kranken- und Pflegeversicherung", phone="0221 480 480",
                    email="leistung@beispiel-kv.example", account="4804800")  # fmt: skip
    # E2: Tue 30.09.2025, 7 Arbeitstage: Mi 1.10(1) Do 2.10(2) [Fr 3.10. Tag der Deutschen Einheit] Mo 6.10(3) Di 7(4) Mi 8(5)
    #     Do 9(6) Fr 10(7) → Fri 10.10.2025
    cases.append(make("holdout-relative_business_days-E2", "E", pkv, O.H_GEN2, "Sehr geehrter Herr Beispiel,", date(2025, 9, 30), 7,
                      "business_days",
                      "Wir benötigen die Unterlagen **spätestens am 7. Arbeitstag nach dem Briefdatum**; Arbeitstage sind für uns "
                      "Montag bis Freitag ohne gesetzliche Feiertage. Andernfalls erstatten wir nur die belegten Positionen.",
                      "Ihre eingereichte Rechnung vom 12.09.2025 – wir benötigen weitere Angaben",
                      [("Versicherungsnummer", "BKV 7710 448 2"), ("Leistungsfall", "LF-25-093317")],
                      "für die Prüfung Ihrer Arztrechnung über die ambulante Operation am Knie benötigen wir den OP-Bericht und die "
                      "Verordnung der Physiotherapie.", "Unterlagen zur Arztrechnung nachreichen", "2025-10-10", "insurance"))  # fmt: skip

    care = O.company("Beispiel Pflegeheim am Park gGmbH", "Parkstraße 30", "35039", "Musterbergen", monogram="PP", accent=(90, 30, 90),
                     style="minimal", tagline="Personalabteilung", phone="06421 60 60 0", email="personal@pflegeheim-park.example",
                     account="6060600")  # fmt: skip
    # F1: Fri 16.04.2027, 6 Werktage: Sa 17(1) Mo 19(2) Di 20(3) Mi 21(4) Do 22(5) Fr 23(6) → Fri 23.04.2027 (no holiday)
    cases.append(make("holdout-relative_business_days-F1", "F", care, O.H_GEN2, "Sehr geehrter Herr Beispiel,", date(2027, 4, 16), 6,
                      "werktage",
                      "Ihre Entscheidung erbitten wir **binnen 6 Werktagen ab Datum dieses Schreibens**; als Werktage zählen dabei "
                      "Montag bis Samstag, gesetzliche Feiertage nicht. Danach planen wir die Stelle anderweitig.",
                      "Angebot zur Verlängerung Ihres befristeten Arbeitsvertrags", [("Personalnummer", "P-2291")],
                      "Ihr befristeter Arbeitsvertrag als Pflegefachkraft endet am 30.06.2027. Wir bieten Ihnen an, ihn ab dem "
                      "01.07.2027 unbefristet fortzusetzen, zu unveränderten Bedingungen in Vollzeit.",
                      "Antwort auf das Angebot zur Vertragsverlängerung", "2027-04-23", "employment", photo=True))  # fmt: skip
    return cases
