"""Holdout3 split, families 4, 5, 6, 8, 9, 10 and 11: variants I and J of the invoices, dunning
letters, appointments, contracts, price changes, English letters and business-day periods.

Written like ``holdout3_admin`` (after the code freeze, new senders, recipients, wording, layout, dates and amounts;
letter days drawn with a seeded choice among the days that fit each scenario). The same generation rules as
``families_private`` hold: private-law deadlines never depend on a Land's holidays, fixed dates fall on working days in
every Land and Werktage counts never end on a Saturday (all asserted).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import law
from . import orgs as O
from .common import Case, event_period_item, fixed_item, spec, today_after, truth, undated_item
from .families_admin import check, created
from .families_private import INVOICE_RULE, _contract_truth
from .holdout3_admin import SPLIT, STYLES, dated_last
from .law import fmt
from .pdf import Block, Box, Letter, Org, P, Person, Sign, Style, Table
from .text import de, de_long, de_weekday, en_uk, en_us, eur_plain


def _info(variant: str, refs: list[tuple[str, str]], d: date, label: str = "Datum") -> list[tuple[str, str]]:
    """Variant I prints the date as the last line of the information block; variant J names it under ``label``."""
    return dated_last(refs, d) if variant == "I" else [*refs, (label, de(d))]


def _priced(rows: list[tuple[str, float]], header: tuple[str, str], labels: tuple[str, str, str], vat: float | None = 0.19,
            value_width: float = 30) -> tuple[Table, float]:  # fmt: skip
    """Line items, then net / VAT / total (or only the total when the service is VAT-exempt)."""
    net = round(sum(v for _, v in rows), 2)
    body = [(label, eur_plain(v)) for label, v in rows]
    n = len(rows)
    if vat is None:
        body.append((labels[2], eur_plain(net)))
        return Table(
            rows=tuple(body), header=header, value_width=value_width, bold_rows=(n,), rule_before=(n,)
        ), net
    tax = round(net * vat, 2)
    total = round(net + tax, 2)
    body += [(labels[0], eur_plain(net)), (labels[1], eur_plain(tax)), (labels[2], eur_plain(total))]
    return Table(
        rows=tuple(body), header=header, value_width=value_width, bold_rows=(n + 2,), rule_before=(n, n + 2)
    ), total


# ==================================================================================================
# Family 4 — invoice_relative (a period of N days after the invoice date)
# ==================================================================================================


def invoice_relative() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, inv_date: date, days: int, refs: list[tuple[str, str]],
             table: Table, total: float, intro: str, pay_line: str, key: str, hand: str, subject: str, photo: bool = False,
             after: list[Block] | None = None, closing: tuple[str, ...] = ()) -> Case:  # fmt: skip
        item = check(
            event_period_item(event=inv_date, amount=days, unit="days", region=None, kind="payment", nature="payment",
                              title=f"{refs[0][1]} bezahlen", anchor="document_date", money=total, rule=INVOICE_RULE,
                              shift_citation="§ 193 BGB"),
            hand,
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, info=_info(variant, refs, inv_date, "Rechnungsdatum"), subject=subject, salutation=salutation,
            blocks=[P(intro), table, P(pay_line), *(after or []), Sign("Mit freundlichen Grüßen", closing or (org.name,))],
            style=STYLES[variant], created=created(inv_date), running_ref=" · ".join(f"{a} {b}" for a, b in refs),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="invoice_relative", variant=variant, letter=letter,
            truth=truth(kind="invoice", sender=org.name, document_date=inv_date, references=refs, amounts=[total], items=[item]),
            today=today_after(inv_date, case_id), authority_region=None, key_phrases=[de(inv_date), key, eur_plain(total)], photo=photo,
        )  # fmt: skip

    electric = O.company("Elektro Beispielfunke GmbH", "Stromweg 7", "37081", "Beispielfeld", monogram="EB", accent=(20, 60, 120),
                         style="band", tagline="Elektroinstallation · Ladetechnik · Photovoltaik", phone="0551 555 71 30",
                         email="buchhaltung@elektro-beispielfunke.example", hr="AG Beispielfeld HRB 30 518",
                         vat="USt-IdNr. DE 318 552 074", account="5571300")  # fmt: skip
    table, total = _priced([("Wallbox 11 kW, Lieferung und Montage", 1180.00), ("Zuleitung 5 × 6 mm², 12 m, verlegt", 186.40),
                            ("Fehlerstromschutzschalter Typ A, Leitungsschutz", 94.60),
                            ("Anmeldung beim Netzbetreiber", 45.00)], ("Leistung", "EUR"),
                           ("Summe netto", "Umsatzsteuer 19 %", "Rechnungsbetrag"))  # fmt: skip
    # I1: Fri 16.10.2026 + 8 = Sat 24.10.2026 → Sun → Mon 26.10.2026
    cases.append(make(
        "holdout3-invoice_relative-I1", "I", electric, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2026, 10, 16), 8,
        [("Rechnung", "EB-26-1042"), ("Auftrag", "A-26-0877")], table, total,
        "für die Installation der Ladestation in Ihrer Garage, Lerchenfeld 23, am 13.10.2026 berechnen wir:",
        "Zahlbar innerhalb von 8 Tagen ab Rechnungsdatum ohne Abzug auf unser Konto bei der Musterbank AG.",
        "innerhalb von 8 Tagen ab Rechnungsdatum", "2026-10-26", "Rechnung EB-26-1042 – Ladestation", photo=True,
        after=[P("Bitte bewahren Sie diese Rechnung zwei Jahre auf (§ 14b Abs. 1 Satz 5 UStG).", size=8.0)],
    ))  # fmt: skip

    vet = O.company("Kleintierpraxis Dr. med. vet. Lena Musterpfote", "Am Tierpark 2", "73728", "Musterlingen am Neckar",
                    monogram="KP", accent=(0, 95, 85), style="minimal", tagline="Hunde · Katzen · Heimtiere",
                    phone="0711 555 92 80", email="rechnung@tierarzt-musterpfote.example", account="5592800")  # fmt: skip
    table, total = _priced([("Allgemeine Untersuchung, GOT Nr. 2", 23.62), ("Narkose und Überwachung", 61.40),
                            ("Zahnsteinentfernung mit Ultraschall", 88.57), ("Medikamente und Verbrauchsmaterial", 31.90)],
                           ("Behandlung Ihres Hundes „Pepper“ am 07.07.2026", "EUR"), ("Netto", "MwSt. 19 %", "Gesamt"))  # fmt: skip
    # I2: Thu 09.07.2026 + 21 = Thu 30.07.2026 — a working day, no shift
    cases.append(make(
        "holdout3-invoice_relative-I2", "I", vet, O.R_GEN2, "Liebe Frau Beispielwinkel,", date(2026, 7, 9), 21,
        [("Rechnungs-Nr.", "KT-2026-3381"), ("Patienten-Nr.", "P-0417")], table, total,
        "vielen Dank für Ihr Vertrauen. Für die Behandlung von Pepper berechnen wir nach der Gebührenordnung für Tierärzte:",
        "Wir bitten um Ausgleich des Gesamtbetrags innerhalb von 21 Tagen nach dem Datum der Rechnung.",
        "innerhalb von 21 Tagen nach dem Datum der Rechnung", "2026-07-30", "Tierärztliche Rechnung",
        closing=("Dr. Lena Musterpfote und Team",),
    ))  # fmt: skip

    physio = O.company("Physiotherapie Beispielbalance", "Kurparkweg 11", "38440", "Beispielsburg", monogram="PB",
                       accent=(80, 40, 110), style="logo", tagline="Krankengymnastik · Manuelle Therapie · Massage",
                       phone="05361 555 88 20", email="abrechnung@physio-beispielbalance.example", account="5588200")  # fmt: skip
    table, total = _priced([("6 × Krankengymnastik à 32,50 €", 195.00), ("6 × Wärmepackung (Fango) à 14,80 €", 88.80),
                            ("Befundbericht an die verordnende Ärztin", 17.50)], ("Leistung (Verordnung vom 14.04.2025)", "EUR"),
                           ("", "", "Rechnungsbetrag (umsatzsteuerfrei, § 4 Nr. 14 UStG)"), vat=None)  # fmt: skip
    # J1: Fri 23.05.2025 + 30 = Sun 22.06.2025 → Mon 23.06.2025
    cases.append(make(
        "holdout3-invoice_relative-J1", "J", physio, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2025, 5, 23), 30,
        [("Rechnungsnummer", "PB-0525-117"), ("Patienten-Nr.", "11 840")], table, total,
        "für die Behandlungen vom 22.04. bis 20.05.2025 stellen wir Ihnen als Privatpatient in Rechnung:",
        "Den Betrag überweisen Sie bitte binnen 30 Tagen ab dem oben genannten Rechnungsdatum; als Verwendungszweck genügt "
        "die Rechnungsnummer.",
        "binnen 30 Tagen ab dem oben genannten Rechnungsdatum", "2025-06-23", "Privatrechnung Physiotherapie", photo=True,
        closing=("Ihr Praxisteam Beispielbalance",),
    ))  # fmt: skip

    movers = O.company("Beispiel Umzugslogistik GmbH", "Speditionsstraße 18", "45879", "Beispielkirchen", monogram="BU",
                       accent=(160, 80, 0), style="band", tagline="Privatumzüge · Möbelmontage · Einlagerung",
                       phone="0209 555 61 40", email="buchhaltung@beispiel-umzug.example", hr="AG Beispielkirchen HRB 11 207",
                       account="5561400")  # fmt: skip
    table, total = _priced([("Umzug 3-Zimmer-Wohnung, 3 Packer, 6,5 Std. à 129,00 €", 838.50), ("Möbellift mit Bedienung", 120.00),
                            ("Halteverbotszone an beiden Adressen", 95.00), ("Umzugskartons, 30 Stück", 64.80)],
                           ("Position", "EUR"), ("Nettobetrag", "zzgl. 19 % USt.", "Gesamtbetrag"))  # fmt: skip
    # J2: Fri 19.03.2027 + 10 = Mon 29.03.2027 Ostermontag → Tue 30.03.2027
    cases.append(make(
        "holdout3-invoice_relative-J2", "J", movers, O.R_GEN2, "Sehr geehrte Frau Beispielwinkel,", date(2027, 3, 19), 10,
        [("Rechnung Nr.", "UL-27-0331"), ("Kunden-Nr.", "K 20 914")], table, total,
        "Ihr Umzug von der Schillerhöhe 5 in die Neckarstraße 40 am 17.03.2027 ist abgeschlossen. Wir berechnen vereinbarungsgemäß:",
        "Bitte gleichen Sie die Rechnung innerhalb von 10 Tagen nach dem Rechnungsdatum aus, ohne Abzüge. Bei der Überweisung "
        "geben Sie bitte die Rechnungsnummer an.",
        "innerhalb von 10 Tagen nach dem Rechnungsdatum aus", "2027-03-30", "Rechnung über Ihren Umzug",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 5 — dunning_fixed (pay by an explicit date)
# ==================================================================================================


def dunning_fixed() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, due: date, due_text: str,
             subject: str, refs: list[tuple[str, str]], rows: list[tuple[str, float]], body: str, pay: str, signer: tuple[str, ...],
             kind: str = "dunning", photo: bool = False, after: list[Block] | None = None) -> Case:  # fmt: skip
        total = round(sum(v for _, v in rows), 2)
        item = check(
            fixed_item(due=due, region=None, kind="payment", nature="payment", title="Offenen Betrag bezahlen", money=total,
                       rule="Payment date stated in the reminder."),
            due.isoformat(),
        )  # fmt: skip
        assert all(law.is_working_day(due, land) for land in law.LAENDER)
        table = Table(rows=(*((label, eur_plain(v)) for label, v in rows), ("Offener Gesamtbetrag", eur_plain(total))),
                      header=("Forderungsaufstellung", "EUR"), bold_rows=(len(rows),), rule_before=(len(rows),))  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date, "Briefdatum"),
            blocks=[P(body), table, P(pay.format(due=due_text)), *(after or []), Sign("Mit freundlichen Grüßen", signer)],
            style=STYLES[variant], created=created(letter_date), running_ref=" · ".join(f"{a} {b}" for a, b in refs),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="dunning_fixed", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[total], items=[item]),
            today=today_after(letter_date, case_id), authority_region=None,
            key_phrases=[de(letter_date), due_text.replace("**", ""), eur_plain(total)], photo=photo,
        )  # fmt: skip

    shop = O.company("Beispielmode Versand GmbH", "Lagerstraße 40", "33334", "Musterslohe", monogram="BV", accent=(120, 20, 60),
                     style="logo", tagline="Outdoor- und Freizeitmode", phone="05241 555 300",
                     email="zahlung@beispielmode.example", hr="AG Musterslohe HRB 7 702", account="5553000")  # fmt: skip
    due = date(2027, 8, 25)  # Wed, a working day everywhere
    cases.append(make(
        "holdout3-dunning_fixed-I1", "I", shop, O.R_GEN2, "Guten Tag Frau Beispielwinkel,", date(2027, 8, 18), due,
        f"bis zum **{de(due)}**", "1. Mahnung – Ihre Bestellung 7741-882",
        [("Kundennummer", "308 115 74"), ("Bestellnummer", "7741-882")],
        [("Rechnung vom 21.07.2027 (Regenjacke, Wanderhose)", 89.90), ("Mahngebühr", 2.50)],
        "zu unserer Rechnung vom 21.07.2027 konnten wir bis heute keinen Zahlungseingang feststellen. Vielleicht ist die "
        "Überweisung im Urlaub einfach untergegangen.",
        "Bitte überweisen Sie den offenen Gesamtbetrag {due} unter Angabe Ihrer Kundennummer. Haben Sie inzwischen bezahlt, "
        "betrachten Sie dieses Schreiben bitte als gegenstandslos.", ("Ihr Kundenservice von Beispielmode",), photo=True,
    ))  # fmt: skip

    lawyers = O.company("Rechtsanwälte Musterhoff & Kollegen", "Justizplatz 4", "73728", "Musterlingen am Neckar", monogram="MK",
                        accent=(40, 40, 40), style="minimal", tagline="Zivilrecht · Baurecht · Forderungsmanagement",
                        phone="0711 555 40 70", email="kanzlei@musterhoff-kollegen.example", account="5540700")  # fmt: skip
    due = date(2026, 2, 25)  # Wed
    cases.append(make(
        "holdout3-dunning_fixed-I2", "I", lawyers, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2026, 2, 5), due,
        f"bis spätestens **{de_weekday(due)}**", "Malerbetrieb Beispielfarbe GmbH ./. Musterschmidt – Werklohnforderung",
        [("Unser Zeichen", "MK 0219/26"), ("Rechnungsnummer", "R-2025-318")],
        [("Rechnung R-2025-318 vom 14.10.2025", 1640.00), ("Verzugszinsen bis 05.02.2026", 21.57),
         ("Rechtsanwaltsvergütung (Nr. 2300, 7002 VV RVG, USt.)", 254.15)],
        "wir zeigen an, dass uns die Malerbetrieb Beispielfarbe GmbH mit der Wahrnehmung ihrer Interessen beauftragt hat. Unsere "
        "Mandantin hat im September 2025 in Ihrem Haus die Wände und Decken von vier Räumen gestrichen. Die Rechnung ist trotz "
        "Mahnung vom 12.11.2025 nicht bezahlt; Sie befinden sich seit dem 13.11.2025 in Verzug.",
        "Wir fordern Sie auf, den Gesamtbetrag {due} auf unser Kanzleikonto zu überweisen. Geht die Zahlung nicht rechtzeitig "
        "ein, werden wir unserer Mandantin empfehlen, die Forderung ohne weitere Ankündigung gerichtlich geltend zu machen.",
        ("Dr. Musterhoff", "Rechtsanwalt"),
    ))  # fmt: skip

    school = O.company("Musikschule Klangfarbe Musterlingen gGmbH", "Am Konzertsaal 3", "73728", "Musterlingen am Neckar",
                       monogram="KM", accent=(0, 90, 120), style="band", tagline="Instrumentalunterricht für Kinder und Erwachsene",
                       phone="0711 555 18 90", email="verwaltung@klangfarbe-musterlingen.example", account="5518900")  # fmt: skip
    due = date(2025, 8, 20)  # Wed
    cases.append(make(
        "holdout3-dunning_fixed-J1", "J", school, O.R_GEN2, "Sehr geehrte Frau Beispielwinkel,", date(2025, 8, 13), due,
        f"**{de_long(due)}**", "Zahlungserinnerung – Unterrichtsentgelt Ihres Sohnes Noah",
        [("Schülernummer", "S-2207"), ("Unterrichtsvertrag", "UV-2024-0912")],
        [("Unterrichtsentgelt Juni 2025", 58.00), ("Unterrichtsentgelt Juli 2025", 58.00), ("Bankgebühren für zwei Rücklastschriften", 7.00)],
        "die Lastschriften für das Unterrichtsentgelt von Juni und Juli 2025 hat Ihre Bank leider zurückgegeben. Die Gebühren, "
        "die uns dabei entstanden sind, müssen wir Ihnen in Rechnung stellen.",
        "Wir bitten Sie, den Rückstand spätestens am {due} zu überweisen. Ab September ziehen wir das Entgelt dann wieder wie "
        "gewohnt ein; sollte sich Ihre Bankverbindung geändert haben, teilen Sie uns die neue bitte mit.",
        ("Verwaltung der Musikschule Klangfarbe",),
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 6 — appointment
# ==================================================================================================


def appointment() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, when: date, time: str,
             subject: str, refs: list[tuple[str, str]], body: list[Block], key: list[str], kind: str = "appointment",
             photo: bool = False, note: str = "", closing: tuple[str, ...] = ()) -> Case:  # fmt: skip
        item = check(
            fixed_item(due=when, region=org.region, kind="appointment", nature="appointment", title=subject, time=time,
                       rule="Appointment set by the sender; appointments are never shifted.", appointment=True),
            when.isoformat(),
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date),
            blocks=[*body, Sign("Mit freundlichen Grüßen", closing or (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="appointment", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[], items=[item]),
            today=today_after(letter_date, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), *key], photo=photo, notes=note,
        )  # fmt: skip

    radiology = O.company("Radiologie am Beispielhof – MVZ", "Beispielhof 1", "37083", "Beispielfeld", monogram="RB",
                          accent=(0, 70, 120), style="logo", tagline="MRT · CT · Röntgen · Ultraschall", phone="0551 555 77 10",
                          email="termine@radiologie-beispielhof.example", account="5577100")  # fmt: skip
    when = date(2026, 3, 26)  # Thu
    cases.append(make(
        "holdout3-appointment-I1", "I", radiology, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2026, 3, 4), when, "14:20",
        "Ihr Termin zur MRT-Untersuchung der Lendenwirbelsäule", [("Patienten-ID", "RB-0094417")],
        [P("Ihr Hausarzt hat Sie zu einer Magnetresonanztomographie (MRT) der Lendenwirbelsäule überwiesen. Wir haben für Sie "
           f"folgenden Termin reserviert: **{de_weekday(when)}, 14:20 Uhr**, Anmeldung im Erdgeschoss."),
         P("Bitte bringen Sie Ihre Versichertenkarte, die Überweisung und – falls vorhanden – frühere Aufnahmen mit. Metallische "
           "Gegenstände und Karten mit Magnetstreifen legen Sie vor der Untersuchung ab. Wenn Sie einen Herzschrittmacher oder "
           "andere Implantate tragen, rufen Sie uns bitte vorher an. Können Sie den Termin nicht wahrnehmen, sagen Sie bitte "
           "mindestens 24 Stunden vorher ab.")],
        [de_weekday(when), "14:20 Uhr"], photo=True, closing=("Ihr Team der Radiologie am Beispielhof",),
    ))  # fmt: skip

    court = Org(name="Amtsgericht Musterdal", kind="authority", street="Gerichtsstraße 6", postcode="39576", city="Musterdal (Altmark)",
                region="ST", head=("Land Sachsen-Anhalt", "Abteilung für Zivilsachen"), phone="03931 555 81-0",
                email="poststelle@ag-musterdal.justiz.sachsen-anhalt.example", style="authority", accent=(130, 20, 30))  # fmt: skip
    when = date(2027, 3, 25)  # Thu
    cases.append(make(
        "holdout3-appointment-I2", "I", court, O.R_ST, "Sehr geehrte Frau Musterwald,", date(2027, 2, 25), when, "10:30",
        "Ladung als Zeugin", [("Geschäftsnummer", "4 C 211/26")],
        [P("in dem Rechtsstreit Henning Krause gegen Beispiel Autohaus Altmark GmbH wegen Gewährleistung aus einem Autokauf "
           "werden Sie auf Anordnung des Gerichts als Zeugin geladen zu dem Termin:"),
         Box((f"{de_weekday(when)}, 10:30 Uhr", "Amtsgericht Musterdal, Gerichtsstraße 6, Sitzungssaal 2 (1. OG)",
              "Sie sollen zu dem Verkaufsgespräch am 04.06.2026 aussagen, an dem Sie teilgenommen haben.")),
         P("Bringen Sie bitte dieses Schreiben und einen Lichtbildausweis mit. Wenn Sie ohne genügende Entschuldigung nicht "
           "erscheinen, werden Ihnen die dadurch verursachten Kosten auferlegt, und gegen Sie kann ein Ordnungsgeld festgesetzt "
           "werden (§ 380 ZPO). Für Fahrtkosten und Verdienstausfall können Sie eine Entschädigung nach dem JVEG verlangen."),
         P("Dieses Schreiben wurde elektronisch erstellt und ist ohne Unterschrift gültig.", size=7.8)],
        [f"{de_weekday(when)}, 10:30 Uhr"], closing=("Hänsel, Justizbeschäftigte", "als Urkundsbeamtin der Geschäftsstelle"),
    ))  # fmt: skip

    kitchen = O.company("Küchenwerkstatt Beispielholz GmbH", "Tischlerweg 9", "37085", "Musterwiesen", monogram="KB",
                        accent=(110, 60, 20), style="band", tagline="Küchenplanung · Montage · Service", phone="0551 555 63 20",
                        email="montage@kuechenwerkstatt-beispielholz.example", account="5563200")  # fmt: skip
    when = date(2026, 9, 19)  # a Saturday: appointments are not shifted
    cases.append(make(
        "holdout3-appointment-J1", "J", kitchen, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2026, 9, 9), when, "07:30",
        "Montagetermin für Ihre neue Küche", [("Auftrag", "KW-26-0612"), ("Kundennummer", "KD 31 118")],
        [P(f"Ihre Küche ist vollständig bei uns eingetroffen. Unser Montageteam kommt am **Samstag, {de(when)}, um 07:30 Uhr** und "
           "braucht voraussichtlich den ganzen Tag."),
         P("Bitte räumen Sie die Küche vorher vollständig aus und sorgen Sie dafür, dass die Wasser- und Stromanschlüsse "
           "zugänglich sind. Die alte Küche haben Sie selbst abgebaut, wie vereinbart. Ist der Termin für Sie nicht möglich, "
           "melden Sie sich bitte bis Mittwoch der Montagewoche.")],
        [de(when), "07:30 Uhr"], note="Saturday appointment: must not be moved to Monday.", closing=("Ihr Montageteam Beispielholz",),
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
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date, "Ausgestellt am"),
            blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="contract_confirmation", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[contract["price"]], items=[],
                        contract=contract),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), *key],
        )  # fmt: skip

    # I1 — mobile contract, § 56 TKG: 12 months from activation Sat 24.01.2026 → Sat 23.01.2027; one month → Wed 23.12.2026.
    mobile = O.company("Beispielnetz Mobil GmbH", "Funkturmstraße 2", "40476", "Musterdüsseldorf", monogram="BN", accent=(0, 110, 90),
                       style="band", tagline="Mobilfunk für Privatkunden", phone="0800 555 23 23", email="vertrag@beispielnetz-mobil.example",
                       hr="AG Musterdüsseldorf HRB 88 417", account="5552323")  # fmt: skip
    case_id, concluded, start = "holdout3-contract_confirmation-I1", date(2026, 1, 23), date(2026, 1, 24)
    contract = _contract_truth(category="mobile", regime="tkg56", party_kind="telecom", concluded=concluded, start=start, initial=12,
                               renewal="indefinite, cancellable any time with 1 month notice", notice=1, notice_unit="months",
                               today=today_after(concluded, case_id), price=17.99, interval="monthly",
                               citations="Telecom contract with a consumer: § 56 Abs. 1, 3 TKG (initial term at most 24 months, then "
                                         "one month's notice).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2027-01-23",
        "2026-12-23",
    )
    cases.append(make(case_id, "I", mobile, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", concluded,
                      "Ihr Mobilfunkvertrag – Vertragszusammenfassung und Bestätigung", [("Kundennummer", "BN 7 204 118 3")],
                      [P(f"vielen Dank für Ihre Bestellung vom {de(concluded)}. Ihre SIM-Karte ist unterwegs; wir schalten sie am "
                         f"{de(start)} frei. Ihren Vertrag fassen wir hier zusammen:"),
                       Table(rows=(("Tarif", "Beispielnetz Smart 20 GB"), ("Rufnummer", "0151 555 77 104"),
                                   ("Aktivierung", de(start)), ("Mindestvertragslaufzeit", "12 Monate ab Aktivierung"),
                                   ("Kündigung", "mit 1 Monat Frist zum Ende der Mindestlaufzeit"),
                                   ("Danach", "unbefristet, jederzeit mit 1 Monat Frist kündbar"),
                                   ("Monatlicher Grundpreis", "17,99 €")),
                             header=("Vertragsübersicht", ""), value_width=100, value_align="L"),
                       P("Die Kündigung ist in Textform möglich, auch über den Kündigungsbutton in Ihrem Kundenkonto. Die erste "
                         "Rechnung erhalten Sie anteilig für den Rest des Monats.")],
                      contract, ["12 Monate ab Aktivierung", "17,99 €"]))  # fmt: skip

    # J1 — private liability insurance, § 11 VVG: 1 year from Sun 01.08.2027 → Mon 31.07.2028; one month → Fri 30.06.2028.
    insurer = O.company("Musterhanse Versicherung AG", "Kontorhaus 3", "20457", "Hamburg", monogram="MH", accent=(10, 50, 100),
                        style="logo", tagline="Haftpflicht · Hausrat · Unfall", phone="040 555 31 31",
                        email="vertrag@musterhanse-versicherung.example", hr="AG Hamburg HRB 99 712", account="5553131")  # fmt: skip
    case_id, concluded, start = "holdout3-contract_confirmation-J1", date(2027, 6, 24), date(2027, 8, 1)
    contract = _contract_truth(category="insurance", regime="vvg11", party_kind="insurer", concluded=concluded, start=start, initial=12,
                               renewal="renews by 1 year unless cancelled 1 month before the end of the insurance year", notice=1,
                               notice_unit="months", today=today_after(concluded, case_id), price=68.52, interval="yearly",
                               citations="Insurance contract: § 11 VVG (yearly renewal, notice as written, max. 3 months).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2028-07-31",
        "2028-06-30",
    )
    cases.append(make(case_id, "J", insurer, O.R_GEN2, "Sehr geehrte Frau Beispielwinkel,", concluded,
                      "Ihr Versicherungsschein – Privathaftpflichtversicherung „Komfort“", [("Versicherungsschein-Nr.", "PHV-27-5530918")],
                      [P("Ihr Antrag ist angenommen. Mit diesem Versicherungsschein bestätigen wir Ihren Versicherungsschutz:"),
                       Table(rows=(("Versicherte Personen", "Sie als Single"), ("Versicherungsbeginn", f"{de(start)}, 0:00 Uhr"),
                                   ("Vertragsdauer", "1 Jahr"), ("Deckungssumme", "10 Mio. € pauschal"),
                                   ("Jahresbeitrag", "68,52 €")),
                             header=("Ihr Vertrag", ""), value_width=92, value_align="L"),
                       P("Der Vertrag verlängert sich nach Ablauf stillschweigend um jeweils ein Jahr, wenn er nicht spätestens "
                         "einen Monat vor dem Ende des Versicherungsjahres in Textform gekündigt wird."),
                       P("Den Jahresbeitrag buchen wir zum Versicherungsbeginn von Ihrem Konto ab.")],
                      contract, ["einen Monat vor dem Ende des Versicherungsjahres", "68,52 €"], kind="insurance"))  # fmt: skip
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
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date, "Schreiben vom"),
            blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="price_increase", variant=variant, letter=letter,
            truth=truth(kind="price_increase", sender=org.name, document_date=letter_date, references=refs, amounts=[old, new], items=[],
                        optional_items=optional, price_change=change),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), de(effective), *key],
        )  # fmt: skip

    power = O.company("Musterwatt Energie GmbH", "Umspannweg 5", "37081", "Beispielfeld", monogram="MW", accent=(20, 90, 40),
                      style="minimal", tagline="Ökostrom für Haushalte", phone="0800 555 92 92", email="kundenservice@musterwatt.example",
                      account="5559292")  # fmt: skip
    eff = date(2027, 4, 1)
    cases.append(make(
        "holdout3-price_increase-I1", "I", power, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2027, 2, 18), eff, "enwg41_5",
        74.00, 81.00, f"Ihr Stromtarif „Musterwatt Natur“ – neue Preise ab {de(eff)}",
        [("Vertragskonto", "MW-6630 1187"), ("Zählernummer", "1ESY1160 4471 02")],
        [P(f"ab dem {de(eff)} ändern sich die Preise Ihres Stromtarifs. Die Netzentgelte, die wir an den Netzbetreiber zahlen, "
           "steigen im Netzgebiet Beispielfeld deutlich; diese Kosten geben wir weiter. Unsere eigene Marge bleibt gleich."),
         Table(rows=(("Arbeitspreis (brutto)", "31,48 ct/kWh → 33,91 ct/kWh"), ("Grundpreis (brutto)", "12,50 € → 13,90 € je Monat"),
                     ("Ihr Abschlag", "74,00 € → 81,00 € je Monat")), header=("", "bisher → neu"), value_width=64),
         P(f"Wenn Sie mit den neuen Preisen nicht einverstanden sind, können Sie den Vertrag ohne Einhaltung einer Kündigungsfrist "
           f"zum {de(eff)} kündigen (§ 41 Abs. 5 EnWG). Die Kündigung muss uns vorher in Textform erreichen; eine Gebühr fällt "
           "dafür nicht an.")],
        ["ohne Einhaltung einer Kündigungsfrist"], "energy",
    ))  # fmt: skip

    radio = O.company("Funkwelle Beispiel GmbH", "Sendemast 12", "50829", "Musterköln", monogram="FW", accent=(130, 0, 70), style="logo",
                      tagline="Mobilfunk · Datentarife", phone="0800 555 08 08", email="service@funkwelle-beispiel.example",
                      account="5550808")  # fmt: skip
    eff = date(2026, 6, 1)
    cases.append(make(
        "holdout3-price_increase-J1", "J", radio, O.R_GEN2, "Sehr geehrte Frau Beispielwinkel,", date(2026, 4, 13), eff, "tkg57", 24.99, 27.99,
        "Änderung Ihres Tarifs „Funkwelle Flex 30“", [("Kundennummer", "FW-30 551 802"), ("Rufnummer", "0176 555 30 118")],
        [P(f"zum {de(eff)} erhöhen wir den monatlichen Grundpreis Ihres Tarifs „Funkwelle Flex 30“ von 24,99 € auf **27,99 €**. "
           "Ihr Datenvolumen und alle anderen Leistungen bleiben unverändert."),
         P("Da die Erhöhung für Sie nachteilig ist, haben Sie nach § 57 Abs. 1 TKG ein Sonderkündigungsrecht: Sie können den "
           "Vertrag fristlos und kostenfrei beenden. Dieses Recht können Sie innerhalb von drei Monaten ausüben, nachdem "
           "Ihnen diese Mitteilung zugegangen ist; der Vertrag endet dann frühestens mit dem Tag, an dem die Preiserhöhung "
           "wirksam wird.")],
        ["innerhalb von drei Monaten ausüben"], "mobile",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 10 — english_letter
# ==================================================================================================


def english_letter() -> list[Case]:
    cases: list[Case] = []
    styles = {
        "I": Style(
            body_pt=9.9,
            left=24,
            right=20,
            leading=1.36,
            para_gap=2.3,
            align="L",
            subject_pt=10.9,
            info_label_pt=7.0,
        ),
        "J": Style(body_pt=10.2, left=22, right=23, leading=1.32, para_gap=2.1, align="L", subject_pt=11.0),
    }

    def letter_for(org: Org, person: Person, info: list[tuple[str, str]], subject: str, blocks: list[Block], variant: str,
                   when: date, salutation: str, closing: str, signer: tuple[str, ...] = ()) -> Letter:  # fmt: skip
        return Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation,
                      blocks=[*blocks, Sign(closing, signer or (org.name,))], style=styles[variant], created=created(when), lang="en")  # fmt: skip

    # I1 — university, UK-style fixed date: Tue 24 August 2027.
    uni = O.company("Beispielfeld University of Applied Sciences", "Campusallee 1", "37085", "Beispielfeld", monogram="BU",
                    accent=(0, 60, 110), style="band", tagline="International Office – Admissions", phone="+49 551 555 2040",
                    email="admissions@hs-beispielfeld.example", account="5552040")  # fmt: skip
    uni = Org(**{**uni.__dict__, "iban": "", "bank": "", "bic": ""})
    when, due = date(2027, 7, 27), date(2027, 8, 24)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration",
                            title="Submit certified copies of the bachelor's certificate", rule="Fixed date stated in the letter."),
                 "2027-08-24")  # fmt: skip
    cases.append(Case(
        id="holdout3-english_letter-I1", split=SPLIT, family="english_letter", variant="I",
        letter=letter_for(uni, O.R_EN, [("Applicant no.", "MA-27-04418"), ("Date", en_uk(when))],
                          "Your admission to the MSc Renewable Energy Systems", [
            P("Congratulations: you have been admitted to the Master's programme Renewable Energy Systems, starting in the "
              "winter semester 2027/28. Your place is reserved, but your enrolment is not yet complete."),
            P(f"Please send us officially certified copies of your bachelor's degree certificate and your transcript of records, "
              f"together with certified German or English translations, **so that they reach us by {en_uk(due)}**. Scans or "
              "uncertified copies cannot be accepted. If the documents arrive later, your place will be offered to another applicant."),
        ], "I", when, "Dear Mr Okonkwo,", "Kind regards,", ("Admissions Team, International Office",)),
        truth=truth(kind="university", sender=uni.name, document_date=when, references=[("Applicant no.", "MA-27-04418")], amounts=[],
                    items=[item], lang="en"),
        today=today_after(when, "holdout3-english_letter-I1"), authority_region=None, key_phrases=[en_uk(when), en_uk(due)], photo=True,
    ))  # fmt: skip

    # I2 — language school invoice: 14 days from the invoice date. Fri 29 Jan 2027 + 14 = Fri 12 Feb 2027, a working day.
    lang_school = O.company("Sprachinstitut Beispielwort GmbH", "Lindenstraße 8", "12435", "Berlin", monogram="SW", accent=(150, 40, 0),
                            style="logo", tagline="German courses · Exam preparation · Integration courses", phone="+49 30 555 4410",
                            email="office@sprachinstitut-beispielwort.example", account="5554410")  # fmt: skip
    when = date(2027, 1, 29)
    total = 815.00
    item = check(event_period_item(event=when, amount=14, unit="days", region=None, kind="payment", nature="payment",
                                   title="Pay invoice SW-2027-0129", anchor="document_date", money=total,
                                   rule="Payment within 14 days of the invoice date (invoice day not counted).",
                                   shift_citation="§ 193 BGB", require_no_shift=True), "2027-02-12")  # fmt: skip
    cases.append(Case(
        id="holdout3-english_letter-I2", split=SPLIT, family="english_letter", variant="I",
        letter=letter_for(lang_school, O.R_EN2, [("Invoice", "SW-2027-0129"), ("Student", "Sofia Lindqvist"), ("Date", en_uk(when))],
                          "Invoice – intensive German course B1", [
            P("Thank you for booking with us. This is your invoice for the course starting on 1 February 2027."),
            Table(rows=(("Intensive course B1, 4 weeks, 20 lessons per week", "640,00"), ("telc Deutsch B1 exam fee", "175,00"),
                        ("Total (VAT-exempt, § 4 No. 21 UStG)", "815,00")), header=("Item", "EUR"), bold_rows=(2,),
                  rule_before=(2,)),
            P("Please transfer the course fee no later than 14 days after the date of this invoice, quoting the invoice number."),
        ], "I", when, "Dear Ms Lindqvist,", "Best wishes,", ("Student Office, Sprachinstitut Beispielwort",)),
        truth=truth(kind="invoice", sender=lang_school.name, document_date=when, references=[("Invoice", "SW-2027-0129")],
                    amounts=[total], items=[item], lang="en"),
        today=today_after(when, "holdout3-english_letter-I2"), authority_region=None,
        key_phrases=[en_uk(when), "no later than 14 days after the date of this invoice"],
    ))  # fmt: skip

    # J1 — US credit union, US long-form dates: the tax form is due on Mon September 13, 2027.
    union = O.company("Example Harbor Federal Credit Union", "200 Example Avenue", "OR 97204", "Portland", monogram="EH",
                      accent=(0, 70, 60), style="minimal", tagline="Member Services – International Members", phone="+1 503 555 0190",
                      email="members@exampleharbor.example", account="5550190", country="USA")  # fmt: skip
    union = Org(
        **{**union.__dict__, "iban": "", "bank": "", "bic": "", "postcode": "", "city": "Portland, OR 97204"}
    )
    when, due = date(2027, 8, 31), date(2027, 9, 13)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration", title="Return the signed Form W-8BEN",
                            rule="Fixed date stated in the letter."), "2027-09-13")  # fmt: skip
    cases.append(Case(
        id="holdout3-english_letter-J1", split=SPLIT, family="english_letter", variant="J",
        letter=letter_for(union, O.R_EN, [("Member no.", "4471-0092-18"), ("Letter date", en_us(when))],
                          "Action required: certificate of foreign status", [
            P("Our records show that you now live outside the United States. To keep your savings account open without US "
              "backup withholding, we need a current Form W-8BEN from you."),
            P(f"Please sign the enclosed form and return it to Member Services **no later than {en_us(due)}**. If we do not "
              "receive it by then, we must withhold 24% of any interest paid to your account."),
        ], "J", when, "Dear Chidi Okonkwo:", "Sincerely,", ("Member Services",)),
        truth=truth(kind="bank_letter", sender=union.name, document_date=when, references=[("Member no.", "4471-0092-18")], amounts=[],
                    items=[item], lang="en"),
        today=today_after(when, "holdout3-english_letter-J1"), authority_region=None, key_phrases=[en_us(when), en_us(due)],
    ))  # fmt: skip

    # J2 — the ambiguous one: 06/07/2027 = Mon 7 Jun (US) or Tue 6 Jul (day/month) — both working days after "today"; the
    # letter's own date 05/05/2027 reads the same either way and the salutation names no title (no locale hint).
    school = O.company("International School Beispielfeld gGmbH", "Am Schulpark 4", "37083", "Beispielfeld", monogram="IS",
                       accent=(0, 90, 70), style="logo", tagline="Bilingual primary and secondary school", phone="+49 551 555 1700",
                       email="admissions@isb-beispielfeld.example", account="5551700")  # fmt: skip
    when = date(2027, 5, 5)  # printed 05/05/2027
    a, b = date(2027, 6, 7), date(2027, 7, 6)
    amb = undated_item(kind="deadline", nature="declaration", title="Return the signed enrolment agreement",
                       spec=spec("fixed", anchor="explicit_date", shift=False), expected_due="ambiguous",
                       derivation=f"'06/07/2027' reads as {fmt(a)} (US month/day) or {fmt(b)} (day/month); the letter gives no reliable "
                                  "locale hint (a German school writing English, its own date 05/05/2027 is symmetric, a salutation "
                                  "without title), so the date is ambiguous and must not be stated confidently.",
                       candidates=[a.isoformat(), b.isoformat()])  # fmt: skip
    cases.append(Case(
        id="holdout3-english_letter-J2", split=SPLIT, family="english_letter", variant="J",
        letter=letter_for(school, O.R_EN2, [("Reference", "ISB-ADM-2027-118"), ("Date", "05/05/2027")],
                          "A place for Leo in Year 3", [
            P("We are pleased to offer Leo a place in Year 3 from the start of the new school year. Two copies of the enrolment "
              "agreement and the fee schedule are enclosed."),
            P("To accept the place, please sign both copies and return one of them to the admissions office by **06/07/2027**. "
              "After that date we will offer the place to the next family on our waiting list."),
        ], "J", when, "Dear Sofia and Erik,", "With best wishes,", ("Admissions Office",)),
        truth=truth(kind="other", sender=school.name, document_date=when, references=[("Reference", "ISB-ADM-2027-118")], amounts=[],
                    items=[amb], expect_low_confidence=True, lang="en"),
        today=today_after(when, "holdout3-english_letter-J2"), authority_region=None, key_phrases=["05/05/2027", "06/07/2027"],
        notes="Intentionally ambiguous numeric date; truth is 'ambiguous' (document date 5 May, symmetric).",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 11 — relative_business_days (Werktage Mon–Sat vs Arbeitstage Mon–Fri, holidays excluded)
# ==================================================================================================


def business_days() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, amount: int, unit: str,
             phrase: str, subject: str, refs: list[tuple[str, str]], body_before: str, task: str, hand: str, kind: str,
             photo: bool = False, after: str = "", closing: tuple[str, ...] = ()) -> Case:  # fmt: skip
        label = "Werktage: Monday–Saturday excluding public holidays (general meaning, cf. § 3 Abs. 2 BUrlG; defined in the letter)" if unit == "werktage" \
            else "Arbeitstage: Monday–Friday excluding public holidays (defined in the letter)"  # fmt: skip
        item = check(
            event_period_item(event=letter_date, amount=amount, unit=unit, region=None, kind="deadline", nature="declaration", title=task,
                              anchor="document_date", rule=f"Period of {amount} {label}, counted from the day after the letter date (§ 187 Abs. 1 BGB).",
                              shift_citation="§ 193 BGB", forbid_saturday_end=unit == "werktage", require_no_shift=True),
            hand,
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date, "Briefdatum"),
            blocks=[P(body_before), P(phrase), *([P(after)] if after else []), Sign("Mit freundlichen Grüßen", closing or (org.name,))],
            style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        key = phrase.split("**")[1]
        return Case(
            id=case_id, split=SPLIT, family="relative_business_days", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[], items=[item]),
            today=today_after(letter_date, case_id, 1, 3), authority_region=None, key_phrases=[de(letter_date), key], photo=photo,
        )  # fmt: skip

    insurer = O.company("Beispiel Assekuranz AG", "Policenring 20", "50829", "Musterköln", monogram="BA", accent=(0, 60, 100),
                        style="logo", tagline="Kraftfahrt-Schadenservice", phone="0221 555 70 00", email="kfz-schaden@beispiel-assekuranz.example",
                        hr="AG Musterköln HRB 41 090", account="5557000")  # fmt: skip
    # I1: Mon 29.09.2025, 12 Werktage: Di 30.09.(1) Mi 01.10.(2) Do 02.10.(3) [Fr 03.10. Tag der Deutschen Einheit] Sa 04.(4)
    #     Mo 06.(5) Di 07.(6) Mi 08.(7) Do 09.(8) Fr 10.(9) Sa 11.(10) Mo 13.(11) Di 14.(12) → Tue 14.10.2025
    cases.append(make("holdout3-relative_business_days-I1", "I", insurer, O.R_GEN2, "Sehr geehrte Frau Beispielwinkel,", date(2025, 9, 29), 12,
                      "werktage",
                      "Schicken Sie uns den Kostenvoranschlag und Fotos der Schäden bitte **innerhalb von 12 Werktagen nach dem Datum "
                      "dieses Schreibens** (Werktage sind Montag bis Samstag; Sonntage und gesetzliche Feiertage zählen nicht mit).",
                      "Unfall vom 19.09.2025 – Ihr Fahrzeug S-LB 2208", [("Schadennummer", "KS-25-0919-4471"), ("Versicherungsschein", "KH 552 104 87")],
                      "unser Versicherungsnehmer hat uns den Unfall auf dem Parkplatz am Neckarufer gemeldet und seine Haftung "
                      "anerkannt. Wir übernehmen den Schaden an Ihrem Fahrzeug im Rahmen der gesetzlichen Haftpflicht.",
                      "Kostenvoranschlag und Schadenfotos einreichen", "2025-10-14", "insurance",
                      after="Bei Schäden über 1.000 € können Sie statt des Kostenvoranschlags auch ein Gutachten eines Sachverständigen "
                            "Ihrer Wahl einreichen; die Kosten dafür tragen wir.",
                      closing=("Ihr Kraftfahrt-Schadenservice",)))  # fmt: skip

    employer = O.company("Beispiel Logistik Süd GmbH", "Frachtweg 30", "73730", "Beispieltal", monogram="BL", accent=(40, 70, 40),
                         style="minimal", tagline="Personalabteilung", phone="0711 555 66 00", email="personal@beispiel-logistik.example",
                         account="5556600")  # fmt: skip
    # I2: Tue 11.05.2027, 10 Arbeitstage: Mi 12.(1) Do 13.(2) Fr 14.(3) [Mo 17.05. Pfingstmontag] Di 18.(4) Mi 19.(5) Do 20.(6)
    #     Fr 21.(7) Mo 24.(8) Di 25.(9) Mi 26.(10) → Wed 26.05.2027 (Fronleichnam 27.05. comes after the end)
    cases.append(make("holdout3-relative_business_days-I2", "I", employer, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2027, 5, 11), 10,
                      "business_days",
                      "Teilen Sie uns Ihre Entscheidung bitte **binnen 10 Arbeitstagen ab dem Briefdatum** mit. Als Arbeitstage gelten "
                      "Montag bis Freitag, gesetzliche Feiertage nicht eingerechnet.",
                      "Betriebliche Altersversorgung – Ihr Angebot zur Entgeltumwandlung", [("Personalnummer", "40 718")],
                      "ab dem 01.07.2027 können Sie einen Teil Ihres Bruttogehalts in eine Direktversicherung einzahlen. Wir legen "
                      "15 % des umgewandelten Betrags als Arbeitgeberzuschuss dazu. Das Angebot und die Beitragsrechnung liegen bei.",
                      "Entscheidung zur Entgeltumwandlung mitteilen", "2027-05-26", "employment",
                      after="Wenn Sie nicht teilnehmen möchten, genügt eine kurze Nachricht an die Personalabteilung.",
                      closing=("Personalabteilung",)))  # fmt: skip

    coop = O.company("Wohnungsgenossenschaft Beispielheim eG", "Genossenschaftsweg 2", "37083", "Beispielfeld", monogram="WB",
                     accent=(100, 50, 20), style="band", tagline="Wohnen in Beispielfeld seit 1921", phone="0551 555 39 00",
                     email="vermietung@wg-beispielheim.example", hr="GnR 214 AG Beispielfeld", account="5553900")  # fmt: skip
    # J1: Fri 04.07.2025, 14 Werktage: Sa 05.(1) Mo 07.(2) Di 08.(3) Mi 09.(4) Do 10.(5) Fr 11.(6) Sa 12.(7) Mo 14.(8) Di 15.(9)
    #     Mi 16.(10) Do 17.(11) Fr 18.(12) Sa 19.(13) Mo 21.(14) → Mon 21.07.2025 (no holiday)
    cases.append(make("holdout3-relative_business_days-J1", "J", coop, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2025, 7, 4), 14,
                      "werktage",
                      "Bitte senden Sie uns ein unterschriebenes Exemplar **innerhalb von 14 Werktagen ab dem Datum dieses Briefes** "
                      "zurück; mitgezählt werden Montag bis Samstag, nicht aber Sonntage und Feiertage.",
                      "Ihr Nutzungsvertrag für die Wohnung Lindenhof 6, 2. OG links", [("Wohnungsnummer", "LH6-2L"), ("Mitglied", "M-8840")],
                      "der Vorstand hat Ihnen die Wohnung Lindenhof 6 zum 01.09.2025 zugeteilt. Anbei erhalten Sie den Nutzungsvertrag "
                      "in zwei Exemplaren sowie die Hausordnung.",
                      "Unterschriebenen Nutzungsvertrag zurücksenden", "2025-07-21", "rent_lease", photo=True,
                      after="Geht der Vertrag nicht rechtzeitig ein, vergeben wir die Wohnung an das nächste Mitglied auf der Warteliste.",
                      closing=("Wohnungsgenossenschaft Beispielheim eG – Vermietung",)))  # fmt: skip
    return cases
