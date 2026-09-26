"""Families 4, 5, 6, 8, 9, 10 and 11: invoices, dunning letters, appointments, contracts, price
changes, English letters and business-day periods.

Private-law deadlines are generated so that their date does not depend on any Land's holidays
(asserted in ``common.dated_item``) — the place of performance for money debts is debatable, the
label must not be. Fixed dates in dunning/English letters fall on working days (asserted), so the
§ 193 BGB question for fixed dates never arises. Werktage counts never end on a Saturday (asserted).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import law
from . import orgs as O
from .common import Case, event_period_item, fixed_item, spec, today_after, truth, undated_item
from .families_admin import STYLES, check, created
from .law import fmt
from .pdf import Letter, Org, P, Person, Sign, Style, Table
from .text import de, de_long, de_weekday, en_uk, en_us, eur_plain

INVOICE_RULE = "Payment period in days after the invoice date: the invoice day is not counted (§ 187 Abs. 1 BGB); § 193 BGB moves an end on Sat/Sun/holiday to the next working day."


def _money_table(
    rows: list[tuple[str, float]], vat: float = 0.19, header: str = "Leistung"
) -> tuple[Table, float]:
    net = round(sum(v for _, v in rows), 2)
    tax = round(net * vat, 2)
    total = round(net + tax, 2)
    body = [(label, eur_plain(v)) for label, v in rows]
    body += [
        ("Nettobetrag", eur_plain(net)),
        (f"zzgl. {round(vat * 100)} % Umsatzsteuer", eur_plain(tax)),
        ("Rechnungsbetrag", eur_plain(total)),
    ]
    n = len(rows)
    return Table(rows=tuple(body), header=(header, "EUR"), bold_rows=(n + 2,), rule_before=(n, n + 2)), total


# ==================================================================================================
# Family 4 — invoice_relative ('innerhalb von N Tagen nach Rechnungsdatum')
# ==================================================================================================


def invoice_relative() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, inv_date: date, days: int, number: str, customer: str,
             positions: list[tuple[str, float]], hand: str, intro: str, kind: str = "invoice", photo: bool = False, vat: float = 0.19) -> Case:  # fmt: skip
        table, total = _money_table(positions, vat=vat)
        item = check(
            event_period_item(event=inv_date, amount=days, unit="days", region=None, kind="payment", nature="payment",
                              title=f"Rechnung {number} bezahlen", anchor="document_date", money=total, rule=INVOICE_RULE,
                              shift_citation="§ 193 BGB"),
            hand,
        )  # fmt: skip
        pay_line = {
            "A": f"Zahlbar **innerhalb von {days} Tagen nach Rechnungsdatum** ohne Abzug.",
            "B": f"Bitte begleichen Sie den Rechnungsbetrag spätestens {days} Tage nach dem Rechnungsdatum auf das unten angegebene Konto.",
            "C": f"Zahlungsziel: {days} Tage nach Rechnungsdatum, netto ohne Abzug. Bitte geben Sie bei der Überweisung die Rechnungsnummer an.",
            "D": f"Der Rechnungsbetrag ist innerhalb von {days} Tagen nach dem Rechnungsdatum ohne Abzug zur Zahlung fällig.",
        }[variant]
        key = {
            "A": f"innerhalb von {days} Tagen nach Rechnungsdatum",
            "B": f"spätestens {days} Tage nach dem Rechnungsdatum",
            "C": f"{days} Tage nach Rechnungsdatum",
            "D": f"innerhalb von {days} Tagen nach dem Rechnungsdatum",
        }[variant]
        letter = Letter(
            org=org, recipient=person,
            info=[("Rechnungsnummer", number), ("Kundennummer", customer), ("Rechnungsdatum", de(inv_date))],
            subject=f"Rechnung Nr. {number}",
            salutation="Sehr geehrte Damen und Herren," if variant in "BD" else f"Guten Tag {person.name},",
            blocks=[P(intro), table, P(pay_line), Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(inv_date), running_ref=f"Rechnung {number}",
        )  # fmt: skip
        return Case(
            id=case_id, split=split, family="invoice_relative", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=inv_date, references=[("Rechnungsnummer", number), ("Kundennummer", customer)],
                        amounts=[total], items=[item]),
            today=today_after(inv_date, case_id), authority_region=None,
            key_phrases=[de(inv_date), key, eur_plain(total)], photo=photo,
        )  # fmt: skip

    elektro = O.company("Elektro Mustermann GmbH", "Industriestraße 14", "44147", "Musterstadt", monogram="EM", accent=(200, 90, 0) if False else (150, 70, 0),
                        tagline="Elektroinstallation · Smart Home · E-Check", phone="0231 77 66 50", email="info@elektro-mustermann.example",
                        hr="Amtsgericht Musterstadt HRB 22817", vat="USt-IdNr. DE 311 208 774", account="5566778")  # fmt: skip
    # dev A1: 20.03.2026 + 14 = Fri 03.04. Karfreitag → Sat, Sun, Mon 06.04. Ostermontag → Tue 07.04.
    cases.append(make("dev-invoice_relative-A1", "dev", "A", elektro, O.P_NW, date(2026, 3, 20), 14, "2026-0318", "K-20417",
                      [("Austausch Unterverteilung inkl. FI/LS-Schalter", 612.00), ("Arbeitszeit Monteur, 5,5 Std. à 68,00 €", 374.00),
                       ("Anfahrtspauschale", 35.00)], "2026-04-07",
                      "für die am 17.03.2026 in Ihrer Wohnung ausgeführten Arbeiten berechnen wir Ihnen wie folgt:", photo=True))  # fmt: skip

    dental = O.company("Zahnarztpraxis Dr. Beispiel", "Marktplatz 3", "34117", "Neu-Musterdorf", monogram="ZB", accent=(0, 95, 110),
                       tagline="Privatliquidation nach GOZ", phone="0561 10 20 30", email="praxis@zahnarzt-beispiel.example", account="3030303")  # fmt: skip
    # dev B1: Thu 04.09.2025 + 30 = Sat 04.10. → Mon 06.10.
    cases.append(make("dev-invoice_relative-B1", "dev", "B", dental, O.P_GEN2, date(2025, 9, 4), 30, "PL-25-0913", "Pat. 4471",
                      [("GOZ 2197 adhäsive Befestigung (2,3-fach)", 16.82), ("GOZ 2120 Kompositfüllung dreiflächig (2,3-fach)", 138.61),
                       ("Material- und Laborkosten", 42.50)], "2025-10-06",
                      "für die zahnärztliche Behandlung vom 28.08.2025 erlauben wir uns, folgende Leistungen zu berechnen:", kind="invoice", vat=0.0))  # fmt: skip

    shop = O.company("Beispiel Versand GmbH", "Logistikring 8", "36251", "Musterfeld", monogram="BV", accent=(20, 40, 110), style="band",
                     tagline="Ihr Online-Shop für Haus & Garten", phone="0800 555 12 12", email="rechnung@beispiel-versand.example",
                     web="www.beispiel-versand.example", hr="AG Musterfeld HRB 9921", vat="USt-IdNr. DE 287 551 903", account="9900112")  # fmt: skip
    # test C1: Wed 17.12.2025 + 7 = Wed 24.12. (Heiligabend is NOT a public holiday) → no shift
    cases.append(make("test-invoice_relative-C1", "test", "C", shop, O.P_GEN, date(2025, 12, 17), 7, "BV-7741203", "KD 1188204",
                      [("Akku-Heckenschere HS 18V (Art. 55123)", 109.24), ("Versandkosten", 4.19)], "2025-12-24",
                      "vielen Dank für Ihre Bestellung vom 15.12.2025 (Kauf auf Rechnung). Ihre Lieferung erfolgt heute.", photo=True))  # fmt: skip

    sanitaer = O.company("Sanitär Beispiel & Söhne", "Rohrweg 2", "64289", "Beispielstadt", monogram="SB", accent=(0, 80, 140), style="minimal",
                         tagline="Meisterbetrieb seit 1978", phone="06151 44 55 66", email="buero@sanitaer-beispiel.example", account="4455660")  # fmt: skip
    # test C2: Wed 22.04.2026 + 10 = Sat 02.05. → Sun → Mon 04.05.
    cases.append(make("test-invoice_relative-C2", "test", "C", sanitaer, O.P_HE, date(2026, 4, 22), 10, "S-26-0448", "10492",
                      [("Reparatur Spülkasten, Ersatzteile", 48.90), ("Arbeitszeit 1,5 Std.", 97.50), ("Anfahrt", 29.00)], "2026-05-04",
                      "für den Einsatz am 21.04.2026 in Ihrem Haushalt stellen wir Ihnen in Rechnung:"))  # fmt: skip

    stadtwerke = O.company("Stadtwerke Musterstadt GmbH", "Energieweg 1", "44143", "Musterstadt", monogram="SW", accent=(0, 90, 60), style="band",
                           tagline="Strom · Gas · Wasser", phone="0231 22 33 44 0", email="kundenservice@sw-musterstadt.example",
                           hr="AG Musterstadt HRB 3001", vat="USt-IdNr. DE 124 578 901", account="7000123")  # fmt: skip
    # test D1: Tue 14.04.2026 + 30 = Thu 14.05. Christi Himmelfahrt → Fri 15.05.
    cases.append(make("test-invoice_relative-D1", "test", "D", stadtwerke, O.P_NW, date(2026, 4, 14), 30, "SR-26-004187", "300 441 872",
                      [("Schlussrechnung Strom 01.01.–31.03.2026 (Mehrverbrauch 212 kWh)", 76.32), ("Abrechnung Grundpreis", 12.40)], "2026-05-15",
                      "anlässlich Ihres Auszugs erhalten Sie die Schlussrechnung für die Lieferstelle Lindenweg 12.", kind="utility_bill", photo=True))  # fmt: skip

    moving = O.company("Umzüge Muster KG", "Speditionsstraße 5", "34123", "Neu-Musterdorf", monogram="UM", accent=(120, 40, 40),
                       tagline="Umzüge · Lagerung · Montage", phone="0561 55 88 00", email="info@umzuege-muster.example", account="1122334")  # fmt: skip
    # test D2 (control): Mon 07.09.2026 + 14 = Mon 21.09. — a working day, no shift
    cases.append(make("test-invoice_relative-D2", "test", "D", moving, O.P_GEN2, date(2026, 9, 7), 14, "UM-2026-311", "U-7730",
                      [("Umzug 2-Zimmer-Wohnung, 3 Mann, 7 Std.", 1120.00), ("LKW 7,5 t inkl. Kraftstoff", 260.00), ("Verpackungsmaterial", 64.00)],
                      "2026-09-21", "für den am 04.09.2026 durchgeführten Umzug berechnen wir vereinbarungsgemäß:"))  # fmt: skip
    return cases


# ==================================================================================================
# Family 5 — dunning_fixed (pay by an explicit date)
# ==================================================================================================


# One payment sentence per variant: the test variants (C, D) repeat no dev sentence.
PAY_SENTENCE = {
    "A": (
        "Bitte überweisen Sie den Betrag {due} auf das unten genannte Konto. Sollten Sie die Zahlung bereits veranlasst haben, "
        "betrachten Sie dieses Schreiben bitte als gegenstandslos."
    ),
    "B": (
        "Bitte überweisen Sie den Betrag {due} auf das unten genannte Konto. Sollten Sie die Zahlung bereits veranlasst haben, "
        "betrachten Sie dieses Schreiben bitte als gegenstandslos."
    ),
    "C": (
        "Wir bitten Sie, den offenen Betrag {due} auszugleichen. Hat sich Ihre Zahlung mit diesem Schreiben überschnitten, "
        "betrachten Sie es bitte als erledigt."
    ),
    "D": (
        "Den ausstehenden Betrag erbitten wir {due} auf das unten genannte Konto. Falls Sie bereits gezahlt haben, ist dieses "
        "Schreiben gegenstandslos."
    ),
}


def dunning_fixed() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, letter_date: date, due: date, due_text: str, subject: str,
             refs: list[tuple[str, str]], amount: float, fee: float, body: str, kind: str = "dunning", photo: bool = False) -> Case:  # fmt: skip
        total = round(amount + fee, 2)
        item = check(
            fixed_item(due=due, region=None, kind="payment", nature="payment", title="Offenen Betrag bezahlen", money=total,
                       rule="Payment date stated in the reminder."),
            due.isoformat(),
        )  # fmt: skip
        rows = (
            [("Offener Betrag", eur_plain(amount))]
            + ([("Mahngebühr", eur_plain(fee))] if fee else [])
            + [("Zu zahlen", eur_plain(total))]
        )
        letter = Letter(
            org=org, recipient=person,
            info=[*refs, ("Datum", de(letter_date))],
            subject=subject,
            salutation="Sehr geehrte Damen und Herren," if variant in "BD" else f"Hallo {person.name.split()[0]},",
            blocks=[
                P(body),
                Table(rows=tuple(rows), header=("", "EUR"), bold_rows=(len(rows) - 1,), rule_before=(len(rows) - 1,)),
                P(PAY_SENTENCE[variant].format(due=due_text)),
                Sign("Mit freundlichen Grüßen", (f"{org.name} – Forderungsmanagement",)),
            ],
            style=STYLES[variant], created=created(letter_date), running_ref=" · ".join(f"{a} {b}" for a, b in refs),
        )  # fmt: skip
        return Case(
            id=case_id, split=split, family="dunning_fixed", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[total], items=[item]),
            today=today_after(letter_date, case_id), authority_region=None,
            key_phrases=[de(letter_date), due_text.replace("**", ""), eur_plain(total)], photo=photo,
        )  # fmt: skip

    shop = O.company("Beispiel Versand GmbH", "Logistikring 8", "36251", "Musterfeld", monogram="BV", accent=(20, 40, 110), style="band",
                     tagline="Ihr Online-Shop für Haus & Garten", phone="0800 555 12 12", email="buchhaltung@beispiel-versand.example",
                     hr="AG Musterfeld HRB 9921", account="9900112")  # fmt: skip
    cases.append(make("dev-dunning_fixed-A1", "dev", "A", shop, O.P_NW, date(2026, 5, 4), date(2026, 5, 15), "bis zum **15.05.2026**",
                      "Zahlungserinnerung", [("Kundennummer", "KD 1188204"), ("Rechnung", "BV-7790114")], 64.98, 0.0,
                      "sicher ist es Ihrer Aufmerksamkeit entgangen: Für Ihre Bestellung vom 02.04.2026 konnten wir noch keinen Zahlungseingang feststellen."))  # fmt: skip

    verlag = O.company("Muster Verlag GmbH", "Pressehaus 1", "20095", "Hamburg", monogram="MV", accent=(140, 0, 40), style="minimal",
                       tagline="Leserservice", phone="040 888 77 66", email="leserservice@muster-verlag.example", account="2020202")  # fmt: skip
    cases.append(make("dev-dunning_fixed-B1", "dev", "B", verlag, O.P_GEN2, date(2025, 6, 13), date(2025, 6, 30), "bis spätestens **30. Juni 2025**",
                      "1. Mahnung – Abonnement „Muster Magazin“", [("Abo-Nummer", "AB-5541078")], 59.40, 2.50,
                      "für Ihr Jahresabonnement „Muster Magazin“ (Bezugszeitraum 01.06.2025 – 31.05.2026) ist der Jahresbeitrag noch offen.",
                      photo=True))  # fmt: skip

    gym = O.company("MusterFit Studios GmbH", "Sportallee 10", "64293", "Beispielstadt", monogram="MF", accent=(200, 0, 90) if False else (150, 0, 70),
                    tagline="Fitness · Kurse · Wellness", phone="06151 60 70 80", email="vertrag@musterfit.example", account="6070800")  # fmt: skip
    cases.append(make("test-dunning_fixed-C1", "test", "C", gym, O.P_HE, date(2025, 12, 1), date(2025, 12, 12), "spätestens am **12.12.2025**",
                      "Mahnung – Rücklastschrift Mitgliedsbeitrag November", [("Mitgliedsnummer", "MF-40177")], 39.90, 7.50,
                      "die Lastschrift für Ihren Mitgliedsbeitrag November 2025 wurde von Ihrer Bank zurückgegeben. Die Bankgebühr für die "
                      "Rücklastschrift berechnen wir Ihnen als Mahngebühr.", photo=True))  # fmt: skip

    telco = O.company("NetzMuster GmbH", "Glasfaserweg 1", "50667", "Musterkirchen", monogram="NM", accent=(90, 30, 120), style="band",
                      tagline="Internet · Telefon · TV", phone="0800 123 00 99", email="inkasso@netzmuster.example", account="1231231")  # fmt: skip
    cases.append(make("test-dunning_fixed-C2", "test", "C", telco, O.P_NW, date(2026, 3, 26), date(2026, 4, 7), "(Zahlungseingang bis **07.04.2026**)",
                      "2. Mahnung", [("Kundennummer", "NM-3380271"), ("Rechnung", "Februar 2026")], 44.99, 5.00,
                      "trotz unserer Zahlungserinnerung vom 12.03.2026 ist die Rechnung für Februar 2026 weiterhin offen. Bitte beachten Sie: "
                      "Bei weiterem Zahlungsverzug behalten wir uns eine Sperre Ihres Anschlusses vor."))  # fmt: skip

    hv = O.company("Hausverwaltung Muster & Partner", "Am Stadtpark 22", "31134", "Beispielhausen", monogram="HV", accent=(40, 70, 40),
                   tagline="WEG- und Mietverwaltung", phone="05121 40 50 60", email="buchhaltung@hv-muster.example", account="4050600")  # fmt: skip
    cases.append(make("test-dunning_fixed-D1", "test", "D", hv, O.P_NI, date(2026, 2, 16), date(2026, 2, 27),
                      "bis spätestens Freitag, den **27. Februar 2026**", "Zahlungserinnerung – Nachzahlung Betriebskostenabrechnung 2024",
                      [("Mietobjekt", "Am Weidenkamp 8, WE 5"), ("Mieter-Nr.", "0512-05")], 286.14, 0.0,
                      "aus der Betriebskostenabrechnung 2024 vom 15.12.2025 ergibt sich eine Nachzahlung, die bisher nicht bei uns "
                      "eingegangen ist.", kind="rent_lease"))  # fmt: skip
    return cases


# ==================================================================================================
# Family 6 — appointment
# ==================================================================================================


def appointment() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, letter_date: date, when: date, time: str, subject: str,
             refs: list[tuple[str, str]], body: list, key: list[str], kind: str = "appointment", photo: bool = False, note: str = "",
             amounts: list[float] | None = None) -> Case:  # fmt: skip
        item = check(
            fixed_item(due=when, region=org.region, kind="appointment", nature="appointment", title=subject, time=time,
                       rule="Appointment set by the sender; appointments are never shifted.", appointment=True),
            when.isoformat(),
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, info=[*refs, ("Datum", de(letter_date))], subject=subject,
            salutation="Sehr geehrte Damen und Herren," if variant in "BD" else f"Guten Tag {person.name},",
            blocks=[*body, Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=split, family="appointment", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=amounts or [], items=[item]),
            today=today_after(letter_date, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), *key], photo=photo, notes=note,
        )  # fmt: skip

    buergeramt = Org(name="Stadt Musterstadt – Bürgeramt", kind="authority", street="Rathausplatz 1", postcode="44135", city="Musterstadt",
                     region="NW", head=("Land Nordrhein-Westfalen", "Bürgerdienste – Pass- und Meldewesen"), phone="0231 50-0",
                     email="buergeramt@musterstadt.example", style="authority", accent=(160, 25, 35))  # fmt: skip
    when = date(2026, 5, 12)
    cases.append(make("dev-appointment-A1", "dev", "A", buergeramt, O.P_NW, date(2026, 4, 27), when, "09:30",
                      "Terminbestätigung – Beantragung eines Reisepasses", [("Vorgangsnummer", "T-2026-044817")],
                      [P(f"hiermit bestätigen wir Ihren Termin am **{de_weekday(when)}, um 09:30 Uhr** im Bürgeramt Mitte, Schalter 4."),
                       P("Bitte bringen Sie Ihren bisherigen Ausweis, ein aktuelles biometrisches Passfoto und die Gebühr von 70,00 € "
                         "(Kartenzahlung möglich) mit. Kann der Termin nicht wahrgenommen werden, sagen Sie ihn bitte online ab.")],
                      [de(when), "09:30 Uhr"], photo=True, amounts=[70.0]))  # fmt: skip

    radiologie = O.company("Radiologie am Musterplatz", "Musterplatz 7", "34117", "Neu-Musterdorf", monogram="RM", accent=(0, 70, 120), style="minimal",
                           tagline="MRT · CT · Röntgen", phone="0561 400 500", email="termine@radiologie-musterplatz.example", account="4005000")  # fmt: skip
    when = date(2026, 2, 3)
    cases.append(make("dev-appointment-B1", "dev", "B", radiologie, O.P_GEN2, date(2026, 1, 20), when, "14:15",
                      "Ihr Untersuchungstermin (MRT Kniegelenk rechts)", [("Patienten-ID", "RM-118204")],
                      [P(f"Ihr Termin: {de(when)}, 14:15 Uhr. Bitte finden Sie sich 15 Minuten vorher an der Anmeldung im Erdgeschoss ein."),
                       P("Bringen Sie bitte Ihre Versichertenkarte, die Überweisung und ggf. Vorbefunde mit. Metallische Gegenstände "
                         "legen Sie bitte vor der Untersuchung ab.")],
                      [de(when), "14:15 Uhr"], kind="appointment"))  # fmt: skip

    abh = Org(name="Landesamt für Einwanderung Muster", kind="immigration_office", street="Friedrich-Krause-Ufer 24", postcode="13353",
              city="Berlin", region="BE", head=("Land Berlin (fiktive Musterbehörde)", "Abteilung Aufenthalt"), phone="030 90269-0",
              email="termine@einwanderung-muster.berlin.example", style="band", accent=(30, 50, 110))  # fmt: skip
    when = date(2026, 10, 15)
    cases.append(make("test-appointment-C1", "test", "C", abh, O.P_BE, date(2026, 9, 21), when, "10:45",
                      "Einladung zur persönlichen Vorsprache – Verlängerung Ihrer Aufenthaltserlaubnis",
                      [("Geschäftszeichen", "IV B 22 – 4412/26")],
                      [P(f"zur Bearbeitung Ihres Antrags vom 01.09.2026 laden wir Sie zur persönlichen Vorsprache ein am "
                         f"**Donnerstag, den {de(when)}, um 10:45 Uhr**, Haus B, Wartebereich 2."),
                       P("Bitte bringen Sie Ihren Reisepass, die aktuelle Arbeitgeberbescheinigung, den Mietvertrag sowie ein biometrisches "
                         "Lichtbild mit. Ihre Fiktionsbescheinigung behält bis zur Entscheidung ihre Gültigkeit.")],
                      [de(when), "10:45 Uhr"], kind="residence_permit"))  # fmt: skip

    jc = O.JC_SN
    when = date(2026, 4, 22)
    cases.append(make("test-appointment-C2", "test", "C", jc, O.P_SN, date(2026, 4, 8), when, "08:15",
                      "Einladung (Meldeaufforderung nach § 59 SGB II i.V.m. § 309 SGB III)", [("BG-Nummer", "04701//0081542")],
                      [P(f"bitte kommen Sie am **Mittwoch, {de(when)} um 08:15 Uhr** in das Jobcenter Musterlingen, Raum 1.18, zu Frau Petzold."),
                       P("Ich möchte mit Ihnen über Ihre aktuelle berufliche Situation sprechen. Bringen Sie bitte Ihren Lebenslauf mit."),
                       P("Rechtsfolgenbelehrung: Kommen Sie ohne wichtigen Grund nicht zu diesem Termin, wird das Bürgergeld um 10 Prozent "
                         "des maßgebenden Regelbedarfs für einen Monat gemindert (§ 32 SGB II).", size=8.8)],
                      [de(when), "08:15 Uhr"], kind="social_insurance", photo=True))  # fmt: skip

    zulassung = Org(name="Kreis Beispielförde – Zulassungsstelle", kind="authority", street="Kreishaus, Förder Straße 3", postcode="24103",
                    city="Beispielförde", region="SH", head=("Land Schleswig-Holstein", "Kfz-Zulassung – Samstagsservice"),
                    phone="0431 9900-400", email="zulassung@kreis-beispielfoerde.example", style="authority", accent=(0, 70, 140))  # fmt: skip
    when = date(2026, 3, 7)  # a Saturday: appointments are not shifted
    cases.append(make("test-appointment-D1", "test", "D", zulassung, O.P_SH, date(2026, 2, 24), when, "10:00",
                      "Terminbestätigung Samstagsservice – Umschreibung Fahrzeug", [("Buchungsnummer", "ZUL-26-07731")],
                      [P(f"wir bestätigen Ihren Termin im Samstagsservice am {de_long(when)} (Samstag) um 10:00 Uhr, Schalter 2."),
                       P("Erforderlich: Zulassungsbescheinigung Teil I und II, eVB-Nummer der Versicherung, SEPA-Mandat für die Kfz-Steuer, "
                         "Personalausweis. Gebühr ca. 37,60 €.")],
                      [de_long(when), "10:00 Uhr"], note="Saturday appointment: must not be moved to Monday.", amounts=[37.60]))  # fmt: skip
    return cases


# ==================================================================================================
# Family 8 — contract_confirmation (secondary metric: contract terms, current_term_end, cancel_by)
# ==================================================================================================


def _contract_truth(*, category: str, regime: str, party_kind: str, concluded: date, start: date, initial: int, renewal: str, notice: int,
                    notice_unit: str, today: date, price: float, interval: str, citations: str) -> dict[str, Any]:  # fmt: skip
    """Current term end and last receipt date for a notice to the end of the current term (no § 193 shift)."""
    end = law.term_end(start, initial)
    steps = [
        f"Term starts at the beginning of {fmt(start)} (§ 187 Abs. 2 BGB); {initial} months → ends {fmt(end)} (§ 188 Abs. 2 Alt. 2 BGB)."
    ]
    assert end >= today, "contract confirmations are read during the initial term"
    if regime in ("bgb309_new", "tkg56"):
        # Keep clear of the open question whether the 24-month cap runs from conclusion or from the start of service:
        # the written term must fit into 24 months counted from the conclusion date, so both readings give the same label.
        assert end <= law.term_end(concluded, 24), (
            "initial term exceeds 24 months from conclusion — label would be contestable"
        )
    cancel_by = law.latest_notice_receipt(end, notice, notice_unit)
    steps.append(
        f"Notice {notice} {notice_unit} before the end: latest receipt D with D + {notice} {notice_unit} ≤ {end.isoformat()} is {fmt(cancel_by)} "
        "(backwards per §§ 187, 188 BGB; notice periods are never moved to a working day, BGH III ZR 172/04)."
    )
    return {
        "category": category,
        "regime": regime,
        "party_kind": party_kind,
        "is_consumer": True,
        "concluded_date": concluded.isoformat(),
        "start_date": start.isoformat(),
        "initial_term_months": initial,
        "renewal": renewal,
        "notice_value": notice,
        "notice_unit": notice_unit,
        "notice_basis": "end_of_term",
        "price": price,
        "price_interval": interval,
        "expected_current_term_end": end.isoformat(),
        "expected_cancel_by": cancel_by.isoformat(),
        "derivation": f"{citations} " + " ".join(f"({i}) {s}" for i, s in enumerate(steps, 1)),
    }


def contract_confirmation() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, letter_date: date, subject: str, refs: list[tuple[str, str]],
             blocks: list, contract: dict, key: list[str], kind: str = "contract") -> Case:  # fmt: skip
        letter = Letter(
            org=org, recipient=person, info=[*refs, ("Datum", de(letter_date))], subject=subject,
            salutation=f"Hallo {person.name.split()[0]}," if variant == "A" else "Sehr geehrte Kundin, sehr geehrter Kunde,",
            blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=split, family="contract_confirmation", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[contract["price"]], items=[], contract=contract),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), *key],
        )  # fmt: skip

    # dev A1 — gym, § 309 Nr. 9 BGB (new): 12 months from 01.03.2026 → 28.02.2027; 1 month notice → receipt by Sun 31.01.2027.
    gym = O.company("MusterFit Studios GmbH", "Sportallee 10", "44145", "Musterstadt", monogram="MF", accent=(150, 0, 70),
                    tagline="Fitness · Kurse · Wellness", phone="0231 60 70 80", email="vertrag@musterfit.example", account="6070800")  # fmt: skip
    concluded, start, today_id = date(2026, 2, 10), date(2026, 3, 1), "dev-contract_confirmation-A1"
    contract = _contract_truth(category="gym", regime="bgb309_new", party_kind="gym", concluded=concluded, start=start, initial=12,
                               renewal="indefinite, cancellable any time with 1 month notice", notice=1, notice_unit="months",
                               today=today_after(concluded, today_id), price=34.90, interval="monthly",
                               citations="Consumer contract concluded after 2022-03-01: § 309 Nr. 9 BGB (n.F.).")  # fmt: skip
    assert (
        contract["expected_current_term_end"] == "2027-02-28"
        and contract["expected_cancel_by"] == "2027-01-31"
    )
    cases.append(make(today_id, "dev", "A", gym, O.P_NW, concluded, "Willkommen bei MusterFit – deine Mitgliedschaft ist bestätigt",
                      [("Mitgliedsnummer", "MF-51230"), ("Vertragsnummer", "V-2026-0877")],
                      [P("schön, dass du dabei bist! Hier die Eckdaten deiner Mitgliedschaft „Flex Premium“:"),
                       Table(rows=(("Vertragsbeginn", de(start)), ("Mindestlaufzeit", "12 Monate"), ("Monatsbeitrag", "34,90 €"),
                                   ("Kündigungsfrist", "1 Monat zum Ende der Mindestlaufzeit"),
                                   ("Danach", "unbefristet, jederzeit mit einer Frist von 1 Monat kündbar")), header=("Deine Mitgliedschaft", ""), value_width=100, value_align="L"),
                       P("Die Beiträge buchen wir monatlich im Voraus per Lastschrift ab. Kündigen kannst du bequem über den Kündigungsbutton "
                         "in der App oder per E-Mail.")],
                      contract, ["12 Monate", "34,90 €"]))  # fmt: skip

    # dev B1 — mobile, § 56 TKG: 12 months from activation 16.06.2025 → 15.06.2026; notice 1 month → Fri 15.05.2026.
    # (Not 24 months: whether the 24-month cap of § 56 Abs. 1 TKG runs from conclusion (12.06.) or activation (16.06.) is
    # open (BGH left it undecided), and 24 months from activation would exceed 24 months from conclusion — no clean label.)
    mobil = O.company("Muster Mobil GmbH", "Funkturmstraße 3", "40210", "Musterdorf", monogram="MM", accent=(0, 90, 150), style="band",
                      tagline="Mobilfunk für alle", phone="0800 800 11 22", email="service@muster-mobil.example", account="8001122")  # fmt: skip
    concluded, start, today_id = date(2025, 6, 12), date(2025, 6, 16), "dev-contract_confirmation-B1"
    contract = _contract_truth(category="mobile", regime="tkg56", party_kind="telecom", concluded=concluded, start=start, initial=12,
                               renewal="indefinite, cancellable any time with 1 month notice (§ 56 Abs. 3 TKG)", notice=1, notice_unit="months",
                               today=today_after(concluded, today_id), price=24.99, interval="monthly",
                               citations="Telecom consumer contract: § 56 TKG (max. 24 months; after that 1 month any time).")  # fmt: skip
    assert (
        contract["expected_current_term_end"] == "2026-06-15"
        and contract["expected_cancel_by"] == "2026-05-15"
    )
    cases.append(make(today_id, "dev", "B", mobil, O.P_GEN2, concluded, "Vertragszusammenfassung gemäß § 54 TKG – Tarif „Muster Allnet 20 GB“",
                      [("Kundennummer", "MM-7730921"), ("Rufnummer", "0151 2345 6789")],
                      [P("vielen Dank für Ihren Auftrag vom " + de(concluded) + ". Ihre SIM-Karte wird am " + de(start) + " freigeschaltet."),
                       Table(rows=(("Tarif", "Muster Allnet 20 GB (5G)"), ("Monatlicher Grundpreis", "24,99 €"),
                                   ("Mindestvertragslaufzeit", "12 Monate ab Freischaltung"),
                                   ("Kündigungsfrist", "1 Monat zum Ende der Mindestvertragslaufzeit"),
                                   ("Nach Ablauf", "unbefristet, jederzeit mit 1 Monat Frist kündbar")),
                             header=("Vertragsdaten", ""), value_width=100, value_align="L"),
                       P("Diese Vertragszusammenfassung ist Bestandteil Ihres Vertrags. Die vollständigen AGB finden Sie im Kundenportal.")],
                      contract, ["12 Monate ab Freischaltung", "24,99 €"]))  # fmt: skip

    # test C1 — energy special contract, § 309 Nr. 9 BGB (new): 12 months from 01.01.2026 → 31.12.2026; 1 month → Mon 30.11.2026.
    energie = O.company("Beispiel Energie AG", "Am Umspannwerk 2", "04109", "Musterlingen", monogram="BE", accent=(0, 100, 70), style="band",
                        tagline="Ökostrom für Ihr Zuhause", phone="0800 234 56 78", email="vertrag@beispiel-energie.example", account="2345678",
                        hr="AG Musterlingen HRB 14 002")  # fmt: skip
    concluded, start, today_id = date(2025, 11, 20), date(2026, 1, 1), "test-contract_confirmation-C1"
    contract = _contract_truth(category="energy", regime="bgb309_new", party_kind="utility", concluded=concluded, start=start, initial=12,
                               renewal="indefinite, cancellable any time with 1 month notice", notice=1, notice_unit="months",
                               today=today_after(concluded, today_id), price=78.00, interval="monthly",
                               citations="Consumer energy supply (Sondervertrag) concluded after 2022-03-01: § 309 Nr. 9 BGB (n.F.).")  # fmt: skip
    assert (
        contract["expected_current_term_end"] == "2026-12-31"
        and contract["expected_cancel_by"] == "2026-11-30"
    )
    cases.append(make(today_id, "test", "C", energie, O.P_SN, concluded, "Vertragsbestätigung Stromlieferung – Tarif „Ökostrom Fix 12“",
                      [("Vertragskonto", "BE-4417 2290"), ("Zählernummer", "1ESY1160571234")],
                      [P("wir freuen uns, Sie ab dem " + de(start) + " mit Strom beliefern zu dürfen. Ihr Vertrag im Überblick:"),
                       Table(rows=(("Lieferbeginn", de(start)), ("Erstlaufzeit", "12 Monate"), ("Arbeitspreis", "31,48 ct/kWh"),
                                   ("Grundpreis", "12,90 €/Monat"), ("Monatlicher Abschlag", "78,00 €"),
                                   ("Kündigung", "mit einer Frist von einem Monat zum Ablauf der Erstlaufzeit"),
                                   ("Verlängerung", "unbefristet, dann jederzeit mit 1 Monat Frist kündbar")),
                             header=("Ihr Vertrag", ""), value_width=100, value_align="L"),
                       P("Den Wechsel von Ihrem bisherigen Lieferanten übernehmen wir für Sie.")],
                      contract, ["Erstlaufzeit", "78,00 €"]))  # fmt: skip

    # test D1 — household contents insurance, § 11 VVG: 1 year from 01.10.2026 → 30.09.2027; 3 months → Wed 30.06.2027.
    vers = O.company("Beispiel Versicherung AG", "Versicherungsplatz 1", "80331", "Musterhausen", monogram="BV", accent=(0, 60, 120), style="logo",
                     tagline="Sach- und Haftpflichtversicherungen", phone="089 123 450", email="kundenservice@beispiel-versicherung.example",
                     account="1234500", hr="AG Musterhausen HRB 5500")  # fmt: skip
    concluded, start, today_id = date(2026, 9, 14), date(2026, 10, 1), "test-contract_confirmation-D1"
    contract = _contract_truth(category="insurance", regime="vvg11", party_kind="insurer", concluded=concluded, start=start, initial=12,
                               renewal="renews by 1 year unless cancelled 3 months before the end of the insurance year", notice=3,
                               notice_unit="months", today=today_after(concluded, today_id), price=96.60, interval="yearly",
                               citations="Insurance contract: § 11 VVG (yearly renewal, notice as written, max. 3 months).")  # fmt: skip
    assert (
        contract["expected_current_term_end"] == "2027-09-30"
        and contract["expected_cancel_by"] == "2027-06-30"
    )
    cases.append(make(today_id, "test", "D", vers, O.P_GEN, concluded, "Versicherungsschein – Hausratversicherung „Komfort“",
                      [("Versicherungsschein-Nr.", "HR-66 204 8813"), ("Vermittler", "Agentur Musterhausen 0712")],
                      [P("wir dokumentieren den Versicherungsvertrag wie folgt:"),
                       Table(rows=(("Versicherungsbeginn", f"{de(start)}, 00:00 Uhr"), ("Vertragsdauer", "1 Jahr"),
                                   ("Versicherungssumme", "65.000,00 €"), ("Jahresbeitrag", "96,60 €"), ("Zahlungsweise", "jährlich")),
                             header=("Vertragsdaten", ""), value_width=100, value_align="L"),
                       P("Der Vertrag verlängert sich jeweils um ein Jahr, wenn er nicht spätestens **drei Monate vor Ablauf** des jeweiligen "
                         "Versicherungsjahres in Textform gekündigt wird."),
                       P("Der Erstbeitrag wird zum Versicherungsbeginn per Lastschrift eingezogen.")],
                      contract, ["drei Monate vor Ablauf", "96,60 €"], kind="insurance"))  # fmt: skip
    return cases


# ==================================================================================================
# Family 9 — price_increase (special-cancellation window; items optional, headline unaffected)
# ==================================================================================================


def price_increase() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, letter_date: date, effective: date, regime: str,
             old: float, new: float, subject: str, refs: list[tuple[str, str]], blocks: list, key: list[str], category: str) -> Case:  # fmt: skip
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
        )
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
            org=org, recipient=person, info=[*refs, ("Datum", de(letter_date))], subject=subject,
            salutation="Sehr geehrte Kundin, sehr geehrter Kunde," if variant in "AC" else f"Guten Tag {person.name},",
            blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=split, family="price_increase", variant=variant, letter=letter,
            truth=truth(kind="price_increase", sender=org.name, document_date=letter_date, references=refs, amounts=[old, new], items=[],
                        optional_items=optional, price_change=change),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), de(effective), *key],
        )  # fmt: skip

    energie = O.company("Beispiel Energie AG", "Am Umspannwerk 2", "04109", "Musterlingen", monogram="BE", accent=(0, 100, 70), style="band",
                        tagline="Ökostrom für Ihr Zuhause", phone="0800 234 56 78", email="service@beispiel-energie.example", account="2345678")  # fmt: skip
    eff = date(2026, 1, 1)
    cases.append(make("dev-price_increase-A1", "dev", "A", energie, O.P_NW, date(2025, 10, 28), eff, "enwg41_5", 72.00, 81.00,
                      "Anpassung Ihrer Strompreise zum 01.01.2026", [("Vertragskonto", "BE-3301 8812")],
                      [P("aufgrund gestiegener Netzentgelte und Beschaffungskosten passen wir unsere Preise zum **01.01.2026** an:"),
                       Table(rows=(("Arbeitspreis", "31,48 → 34,92 ct/kWh"), ("Grundpreis", "12,90 → 13,90 €/Monat"),
                                   ("Ihr monatlicher Abschlag", "72,00 € → 81,00 €")), header=("Preisbestandteil", "alt → neu"), value_width=60),
                       P("Sie haben das Recht, Ihren Vertrag ohne Einhaltung einer Kündigungsfrist zum Zeitpunkt des Wirksamwerdens der "
                         "Preisänderung zu kündigen (§ 41 Abs. 5 EnWG). Die Kündigung bedarf der Textform.")],
                      ["ohne Einhaltung einer Kündigungsfrist"], "energy"))  # fmt: skip

    netz = O.company("NetzMuster GmbH", "Glasfaserweg 1", "50667", "Musterkirchen", monogram="NM", accent=(90, 30, 120), style="band",
                     tagline="Internet · Telefon · TV", phone="0800 123 00 99", email="service@netzmuster.example", account="1231231")  # fmt: skip
    eff = date(2026, 4, 1)
    cases.append(make("dev-price_increase-B1", "dev", "B", netz, O.P_GEN2, date(2026, 2, 16), eff, "tkg57", 39.99, 44.99,
                      "Wichtige Information zu Ihrem Vertrag: Preisanpassung ab 01.04.2026", [("Kundennummer", "NM-2291044")],
                      [P("wir investieren weiter in den Ausbau unseres Glasfasernetzes. Deshalb erhöht sich der monatliche Grundpreis Ihres "
                         "Tarifs „Muster DSL 250“ ab dem 01.04.2026 von 39,99 € auf **44,99 €**."),
                       P("Ihr Sonderkündigungsrecht: Sie können Ihren Vertrag innerhalb von drei Monaten nach Zugang dieser Mitteilung ohne "
                         "Einhaltung einer Frist und ohne Kosten kündigen, frühestens zum Zeitpunkt des Wirksamwerdens der Änderung (§ 57 TKG).")],
                      ["innerhalb von drei Monaten nach Zugang"], "internet"))  # fmt: skip

    gas = O.company("Muster Gas GmbH", "Gasometerstraße 4", "31135", "Beispielhausen", monogram="MG", accent=(160, 60, 0) if False else (130, 50, 0),
                    style="logo", tagline="Erdgas für Haushalt und Gewerbe", phone="05121 707 00", email="kundenservice@muster-gas.example",
                    account="7070000")  # fmt: skip
    eff = date(2026, 11, 1)
    cases.append(make("test-price_increase-C1", "test", "C", gas, O.P_NI, date(2026, 9, 10), eff, "enwg41_5", 96.00, 109.00,
                      "Preisänderung Erdgas „Muster Gas Komfort“ zum 01.11.2026", [("Kundennummer", "MG-510 2277"), ("Zählpunkt", "DE0005111201000000000000000123456")],
                      [P("zum **01.11.2026** ändern sich die Preise Ihres Erdgastarifs. Grund sind höhere Kosten für CO₂-Zertifikate und Speicherumlagen."),
                       Table(rows=(("Arbeitspreis", "10,94 → 12,36 ct/kWh"), ("Grundpreis", "14,50 → 14,50 €/Monat"),
                                   ("Monatlicher Abschlag", "96,00 € → 109,00 €")), header=("", "bisher → neu"), value_width=60),
                       P("Sie können den Vertrag ohne Einhaltung einer Kündigungsfrist zum Wirksamwerden der Preisänderung kündigen. "
                         "Eine Kündigung in Textform (z. B. E-Mail) genügt.")],
                      ["ohne Einhaltung einer Kündigungsfrist"], "gas"))  # fmt: skip

    mobil = O.company("Muster Mobil GmbH", "Funkturmstraße 3", "40210", "Musterdorf", monogram="MM", accent=(0, 90, 150), style="band",
                      tagline="Mobilfunk für alle", phone="0800 800 11 22", email="service@muster-mobil.example", account="8001122")  # fmt: skip
    eff = date(2026, 2, 1)
    cases.append(make("test-price_increase-D1", "test", "D", mobil, O.P_GEN, date(2025, 12, 5), eff, "tkg57", 19.99, 22.99,
                      "Ihr Tarif „Muster Allnet 10 GB“: Änderung des Grundpreises", [("Kundennummer", "MM-6612004"), ("Rufnummer", "0160 9876 5432")],
                      [P(f"ab dem {de(eff)} beträgt der monatliche Grundpreis Ihres Tarifs 22,99 € (bisher 19,99 €). Alle anderen "
                         "Leistungen bleiben unverändert."),
                       P("Da diese Änderung nicht ausschließlich zu Ihrem Vorteil ist, steht Ihnen ein Sonderkündigungsrecht zu: Sie können "
                         "binnen drei Monaten ab Zugang dieses Schreibens kostenfrei kündigen; der Vertrag endet frühestens mit Wirksamwerden der Änderung.")],
                      ["binnen drei Monaten ab Zugang"], "mobile"))  # fmt: skip
    return cases


# ==================================================================================================
# Family 10 — english_letter
# ==================================================================================================


def english_letter() -> list[Case]:
    cases: list[Case] = []
    en_style = {
        "A": STYLES["A"],
        "B": Style(body_pt=10.0, left=25, right=25, leading=1.34, align="L"),
        "C": STYLES["C"],
        "D": Style(body_pt=10.2, left=24, right=24, leading=1.3, align="L"),
    }

    def letter_for(
        org: Org,
        person: Person,
        info: list[tuple[str, str]],
        subject: str,
        blocks: list,
        variant: str,
        when: date,
        sal: str,
    ) -> Letter:
        return Letter(org=org, recipient=person, info=info, subject=subject, salutation=sal,
                      blocks=[*blocks, Sign("Kind regards," if variant in "AC" else "Sincerely,", (org.name,))],
                      style=en_style[variant], created=created(when), lang="en")  # fmt: skip

    # dev A1 — German company writing in English (UK style): within 30 days of the letter date. 11 Feb 2026 + 30 = Fri 13 Mar.
    reloc = O.company("Beispiel Relocation Services GmbH", "Friedrichstraße 90", "10117", "Berlin", monogram="BR", accent=(20, 60, 100),
                      tagline="Relocation & Settling-in Services", phone="+49 30 555 0199", email="accounts@beispiel-relocation.example",
                      account="9019901", hr="AG Charlottenburg HRB 20 441")  # fmt: skip
    when = date(2026, 2, 11)
    total = 1_190.00
    item = check(event_period_item(event=when, amount=30, unit="days", region=None, kind="payment", nature="payment", title="Pay invoice INV-26-0207",
                                   anchor="document_date", money=total, rule="Payment within 30 days of the date of the letter (letter day not counted).",
                                   shift_citation="§ 193 BGB", require_no_shift=True), "2026-03-13")  # fmt: skip
    cases.append(Case(
        id="dev-english_letter-A1", split="dev", family="english_letter", variant="A",
        letter=letter_for(reloc, O.P_EN, [("Invoice no.", "INV-26-0207"), ("Client ref.", "C-4410"), ("Date", en_uk(when))],
                          "Invoice – Settling-in package", [
                              P("Thank you for choosing our settling-in package. Please find our invoice below."),
                              Table(rows=(("Settling-in package (Anmeldung, bank account, tax ID)", "1.000,00"), ("VAT 19 %", "190,00"),
                                          ("Total due", "1.190,00")), header=("Service", "EUR"), bold_rows=(2,), rule_before=(2,)),
                              P("Please pay **within 30 days of the date of this letter** by bank transfer to the account shown below, quoting "
                                "the invoice number."),
                          ], "A", when, "Dear Ms Sharma,"),
        truth=truth(kind="invoice", sender=reloc.name, document_date=when, references=[("Invoice no.", "INV-26-0207"), ("Client ref.", "C-4410")],
                    amounts=[total], items=[item], lang="en"),
        today=today_after(when, "dev-english_letter-A1"), authority_region=None,
        key_phrases=[en_uk(when), "within 30 days of the date of this letter"],
    ))  # fmt: skip

    # dev B1 — international institute, all-numeric dates: 07/08/2026 = 8 July (US) or 7 August (UK) → ambiguous.
    inst = O.company("Global Muster Research Institute", "Science Park 2", "69117", "Beispielberg", monogram="GM", accent=(40, 40, 110), style="minimal",
                     tagline="International Study Office", phone="+49 6221 555 300", email="studies@gmri.example", account="3003003")  # fmt: skip
    when = date(2026, 5, 5)  # printed 05/05/2026 — symmetric, gives no hint
    a, b = date(2026, 7, 8), date(2026, 8, 7)
    amb = undated_item(kind="deadline", nature="declaration", title="Return the signed participation form",
                       spec=spec("fixed", anchor="explicit_date", shift=False), expected_due="ambiguous",
                       derivation=f"'07/08/2026' reads as {fmt(a)} (US month/day) or {fmt(b)} (day/month); the letter gives no reliable "
                                  "locale hint (a German sender writing English, its own date 05/05/2026 is symmetric), so the date is "
                                  "ambiguous and must not be stated confidently.",
                       candidates=[a.isoformat(), b.isoformat()])  # fmt: skip
    cases.append(Case(
        id="dev-english_letter-B1", split="dev", family="english_letter", variant="B",
        letter=letter_for(inst, O.P_EN2, [("Reference", "GMRI/ST/2026/118"), ("Date", "05/05/2026")], "Summer research programme – participation form", [
            P("We are pleased to confirm your place in the summer research programme."),
            P("Please return the signed participation form by **07/08/2026**. Forms received after this date cannot be considered."),
        ], "B", when, "Dear Mr O'Connor,"),
        truth=truth(kind="university", sender=inst.name, document_date=when, references=[("Reference", "GMRI/ST/2026/118")], amounts=[], items=[amb],
                    expect_low_confidence=True, lang="en"),
        today=today_after(when, "dev-english_letter-B1"), authority_region=None, key_phrases=["05/05/2026", "07/08/2026"],
        notes="Deliberately ambiguous numeric dates (document date is symmetric as well; truth document_date assumes 5 May).",
    ))  # fmt: skip

    # test C1 — German university, English letter, UK-style fixed date: Fri 15 May 2026 (the day after Ascension Day).
    uni = O.company("University of Beispielstadt", "Universitätsplatz 1", "64289", "Beispielstadt", monogram="UB", accent=(0, 60, 110), style="logo",
                    tagline="International Office – Outgoing Exchange", phone="+49 6151 16-0", email="exchange@uni-beispielstadt.example", account="1616160")  # fmt: skip
    when, due = date(2026, 4, 20), date(2026, 5, 15)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration", title="Submit signed Learning Agreement",
                            rule="Fixed date stated in the letter."), "2026-05-15")  # fmt: skip
    cases.append(Case(
        id="test-english_letter-C1", split="test", family="english_letter", variant="C",
        letter=letter_for(uni, O.P_EN, [("Our ref.", "IO-OUT-26-0415"), ("Date", en_uk(when))], "Erasmus+ exchange 2026/27 – next steps", [
            P("Congratulations on your nomination for an Erasmus+ exchange semester at the University of Musterholm in winter 2026/27."),
            P(f"Please submit your signed Learning Agreement by **{en_uk(due)}** via the Mobility-Online portal. We cannot forward your "
              "application to the host university without it."),
        ], "C", when, "Dear Ms Sharma,"),
        truth=truth(kind="university", sender=uni.name, document_date=when, references=[("Our ref.", "IO-OUT-26-0415")], amounts=[], items=[item], lang="en"),
        today=today_after(when, "test-english_letter-C1"), authority_region=None, key_phrases=[en_uk(when), en_uk(due)], photo=True,
    ))  # fmt: skip

    # test C2 — property manager in Germany, English: within 30 days of the letter date. 3 Nov 2025 + 30 = Wed 3 Dec 2025.
    pm = O.company("Muster Apartments GmbH", "Hafenstraße 12", "20459", "Hamburg", monogram="MA", accent=(0, 80, 90), style="band",
                   tagline="Serviced apartments for international residents", phone="+49 40 555 7070", email="billing@muster-apartments.example",
                   account="7070707")  # fmt: skip
    when = date(2025, 11, 3)
    item = check(event_period_item(event=when, amount=30, unit="days", region=None, kind="payment", nature="payment", title="Settle utility balance",
                                   anchor="document_date", money=184.20, rule="Payment within 30 days of the date of the letter (letter day not counted).",
                                   shift_citation="§ 193 BGB", require_no_shift=True), "2025-12-03")  # fmt: skip
    cases.append(Case(
        id="test-english_letter-C2", split="test", family="english_letter", variant="C",
        letter=letter_for(pm, O.P_EN2, [("Tenant no.", "MA-HH-0512"), ("Apartment", "3.07"), ("Date", en_uk(when))], "Utility statement 2024/25", [
            P("Please find enclosed your utility statement for the period 1 October 2024 to 30 September 2025. Your advance payments did not "
              "fully cover the actual costs (heating and hot water)."),
            Table(rows=(("Actual costs", "1.624,20"), ("Advance payments", "– 1.440,00"), ("Balance due", "184,20")), header=("", "EUR"),
                  bold_rows=(2,), rule_before=(2,)),
            P("Please settle the outstanding balance of €184.20 no later than 30 days after the date of this statement."),
        ], "C", when, "Dear Mr O'Connor,"),
        truth=truth(kind="rent_lease", sender=pm.name, document_date=when, references=[("Tenant no.", "MA-HH-0512")], amounts=[184.20], items=[item], lang="en"),
        today=today_after(when, "test-english_letter-C2"), authority_region=None,
        key_phrases=[en_uk(when), "no later than 30 days after the date of this statement"],
    ))  # fmt: skip

    # test D1 — US insurer, US long-form dates: claim documents must be received by Wed Sep 30, 2026.
    us = O.company("Example Student Health Plan, Inc.", "200 Beispiel Street, Suite 400", "MA 02110", "Boston", monogram="ES", accent=(20, 40, 90),
                   style="logo", tagline="Health coverage for international students", phone="+1 617 555 0142", email="claims@eshp.example",
                   account="4242424", country="USA")  # fmt: skip
    us = Org(**{**us.__dict__, "iban": "", "bank": "", "bic": "", "postcode": "", "city": "Boston, MA 02110"})
    when, due = date(2026, 9, 8), date(2026, 9, 30)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration", title="Send claim documents", rule="Fixed date stated in the letter."),
                 "2026-09-30")  # fmt: skip
    cases.append(Case(
        id="test-english_letter-D1", split="test", family="english_letter", variant="D",
        letter=letter_for(us, O.P_EN, [("Member ID", "ESHP-88120-04"), ("Claim no.", "CLM-2026-55181"), ("Date", en_us(when))], "Additional information needed for your claim", [
            P("We received your claim for the emergency room visit on August 21, 2026. To process it, we need an itemized bill and proof of payment."),
            P(f"Your claim documents must be received by **{en_us(due)}**. If we do not receive them by then, the claim will be closed."),
        ], "D", when, "Dear Priya Sharma:"),
        truth=truth(kind="insurance", sender=us.name, document_date=when, references=[("Member ID", "ESHP-88120-04"), ("Claim no.", "CLM-2026-55181")],
                    amounts=[], items=[item], lang="en"),
        today=today_after(when, "test-english_letter-D1"), authority_region=None, key_phrases=[en_us(when), en_us(due)],
    ))  # fmt: skip

    # test D2 — the ambiguous one: 03/06/2026 = Fri 6 March (US) or Wed 3 June (UK) — both plausible working days
    # (not 03/05/2026: 3 May 2026 is a Sunday, which would hint at the US reading).
    ex = O.company("Musterfield Exchange Programme", "Campus Road 5", "33615", "Musterfeld", monogram="ME", accent=(60, 30, 90), style="minimal",
                   tagline="International Admissions", phone="+49 521 555 880", email="admissions@musterfield-exchange.example", account="8808808")  # fmt: skip
    when = date(2026, 2, 2)  # printed 02/02/2026
    a, b = date(2026, 3, 6), date(2026, 6, 3)
    amb = undated_item(kind="deadline", nature="declaration", title="Return the completed housing form",
                       spec=spec("fixed", anchor="explicit_date", shift=False), expected_due="ambiguous",
                       derivation=f"'03/06/2026' reads as {fmt(a)} (US month/day) or {fmt(b)} (day/month); the letter gives no reliable "
                                  "locale hint (a German sender writing English, its own date 02/02/2026 is symmetric), so the date is "
                                  "ambiguous and must not be stated confidently.",
                       candidates=[a.isoformat(), b.isoformat()])  # fmt: skip
    cases.append(Case(
        id="test-english_letter-D2", split="test", family="english_letter", variant="D",
        letter=letter_for(ex, O.P_EN2, [("Applicant no.", "MEP-2026-0381"), ("Date", "02/02/2026")], "Your housing application", [
            P("Thank you for accepting your place in the Musterfield Exchange Programme."),
            P("The completed housing form is due on **03/06/2026**; forms that arrive later go on the waiting list."),
        ], "D", when, "Dear Mr O'Connor,"),
        truth=truth(kind="university", sender=ex.name, document_date=when, references=[("Applicant no.", "MEP-2026-0381")], amounts=[], items=[amb],
                    expect_low_confidence=True, lang="en"),
        today=today_after(when, "test-english_letter-D2"), authority_region=None, key_phrases=["02/02/2026", "03/06/2026"],
        notes="Intentionally ambiguous numeric date; truth is 'ambiguous' (document date assumed 2 Feb, symmetric).",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 11 — relative_business_days (Werktage Mon–Sat vs Arbeitstage Mon–Fri, holidays excluded)
# ==================================================================================================


def business_days() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, letter_date: date, amount: int, unit: str, phrase: str,
             subject: str, refs: list[tuple[str, str]], body_before: str, task: str, hand: str, kind: str, photo: bool = False) -> Case:  # fmt: skip
        label = "Werktage: Monday–Saturday excluding public holidays (general meaning, cf. § 3 Abs. 2 BUrlG; defined in the letter)" if unit == "werktage" \
            else "Arbeitstage: Monday–Friday excluding public holidays (defined in the letter)"  # fmt: skip
        item = check(
            event_period_item(event=letter_date, amount=amount, unit=unit, region=None, kind="deadline", nature="declaration", title=task,
                              anchor="document_date", rule=f"Period of {amount} {label}, counted from the day after the letter date (§ 187 Abs. 1 BGB).",
                              shift_citation="§ 193 BGB", forbid_saturday_end=unit == "werktage", require_no_shift=True),
            hand,
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, info=[*refs, ("Datum", de(letter_date))], subject=subject,
            salutation="Sehr geehrte Damen und Herren," if variant in "BD" else f"Guten Tag {person.name},",
            blocks=[P(body_before), P(phrase), Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        key = phrase.split("**")[1] if "**" in phrase else phrase
        return Case(
            id=case_id, split=split, family="relative_business_days", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[], items=[item]),
            today=today_after(letter_date, case_id, 1, 3), authority_region=None, key_phrases=[de(letter_date), key], photo=photo,
        )  # fmt: skip

    vers = O.company("Beispiel Versicherung AG", "Versicherungsplatz 1", "80331", "Musterhausen", monogram="BV", accent=(0, 60, 120), style="logo",
                     tagline="Schadenservice Hausrat", phone="089 123 450", email="schaden@beispiel-versicherung.example", account="1234500")  # fmt: skip
    # dev A1: Fri 27.03.2026, 10 Werktage: Sa 28(1) Mo 30(2) Di 31(3) Mi 1.4(4) Do 2.4(5) [Karfreitag] Sa 4.4(6) [So, Ostermontag]
    #         Di 7.4(7) Mi 8.4(8) Do 9.4(9) Fr 10.4(10) → Fri 10.04.2026
    cases.append(make("dev-relative_business_days-A1", "dev", "A", vers, O.P_NW, date(2026, 3, 27), 10, "werktage",
                      "Bitte reichen Sie die fehlenden Unterlagen **binnen 10 Werktagen nach dem Datum dieses Schreibens** ein (Werktage sind Montag "
                      "bis Samstag, ausgenommen gesetzliche Feiertage). Andernfalls müssen wir über den Schaden nach Aktenlage entscheiden.",
                      "Ihre Schadenmeldung vom 19.03.2026 – Wasserschaden", [("Schaden-Nr.", "HR-26-0331-778"), ("Versicherungsschein", "HR-66 204 1177")],
                      "zur weiteren Bearbeitung Ihres Schadens benötigen wir noch eine Aufstellung der beschädigten Gegenstände mit Kaufbelegen sowie "
                      "Fotos der Schäden.", "Unterlagen zum Wasserschaden einreichen", "2026-04-10", "insurance"))  # fmt: skip

    hv = O.company("Hausverwaltung Muster & Partner", "Am Stadtpark 22", "44139", "Musterstadt", monogram="HV", accent=(40, 70, 40),
                   tagline="WEG- und Mietverwaltung", phone="0231 40 50 60", email="technik@hv-muster.example", account="4050600")  # fmt: skip
    # dev B1: Mon 22.12.2025, 7 Arbeitstage: Di 23(1) Mi 24(2) [25., 26. Feiertage] Mo 29(3) Di 30(4) Mi 31(5) [Neujahr] Fr 2.1(6)
    #         Mo 5.1(7) → Mon 05.01.2026
    cases.append(make("dev-relative_business_days-B1", "dev", "B", hv, O.P_NW, date(2025, 12, 22), 7, "business_days",
                      "Bitte teilen Sie uns **innerhalb von 7 Arbeitstagen (Mo.–Fr., ohne Feiertage) nach Briefdatum** mit, an welchem der "
                      "vorgeschlagenen Termine der Zugang zu Ihrer Wohnung möglich ist.",
                      "Ablesung der Heizkostenverteiler und Rauchmelderwartung", [("Mietobjekt", "Lindenweg 12, WE 3"), ("Mieter-Nr.", "0877-03")],
                      "im Januar lässt die Eigentümergemeinschaft die Heizkostenverteiler ablesen und die Rauchwarnmelder warten. Vorgeschlagene "
                      "Termine: 12.01., 14.01. oder 16.01.2026, jeweils zwischen 8 und 12 Uhr.", "Termin für die Ablesung mitteilen", "2026-01-05",
                      "rent_lease"))  # fmt: skip

    arbeitgeber = O.company("Beispiel Logistik GmbH", "Hafenring 40", "28197", "Musterhaven", monogram="BL", accent=(0, 60, 90), style="band",
                            tagline="Personalabteilung", phone="0421 555 20 00", email="personal@beispiel-logistik.example", account="5552000")  # fmt: skip
    # test C1: Tue 28.04.2026, 10 Werktage: Mi 29(1) Do 30(2) [1. Mai] Sa 2.5(3) Mo 4(4) Di 5(5) Mi 6(6) Do 7(7) Fr 8(8) Sa 9(9)
    #          Mo 11(10) → Mon 11.05.2026
    cases.append(make("test-relative_business_days-C1", "test", "C", arbeitgeber, O.P_GEN, date(2026, 4, 28), 10, "werktage",
                      "Wir bitten Sie, die unterschriebene Zusatzvereinbarung **innerhalb von 10 Werktagen (Mo–Sa, ohne Feiertage) nach dem "
                      "Datum dieses Schreibens** an die Personalabteilung zurückzusenden.",
                      "Zusatzvereinbarung zu Ihrem Arbeitsvertrag – mobiles Arbeiten", [("Personalnummer", "40718")],
                      "wie besprochen erhalten Sie anbei die Zusatzvereinbarung über mobiles Arbeiten (bis zu zwei Tage pro Woche) ab dem 01.06.2026.",
                      "Zusatzvereinbarung unterschrieben zurücksenden", "2026-05-11", "employment"))  # fmt: skip

    bank = O.company("Muster Bank AG", "Bankplatz 1", "60311", "Musterfurt", monogram="MB", accent=(0, 45, 100), style="band",
                     tagline="Kundenservice Privatkunden", phone="069 555 100 0", email="service@muster-bank.example", account="1000001",
                     hr="AG Musterfurt HRB 88 001")  # fmt: skip
    # test C2: Thu 18.12.2025, 8 Werktage: Fr 19(1) Sa 20(2) Mo 22(3) Di 23(4) Mi 24(5) [25., 26., So] Sa 27(6) Mo 29(7) Di 30(8)
    #          → Tue 30.12.2025
    cases.append(make("test-relative_business_days-C2", "test", "C", bank, O.P_GEN2, date(2025, 12, 18), 8, "werktage",
                      "Bitte reichen Sie die Unterlagen **binnen 8 Werktagen (Montag bis Samstag, ohne Feiertage) nach dem Datum dieses "
                      "Schreibens** ein. Danach müssen wir Ihr Depot bis zur Klärung für Käufe sperren.",
                      "Aktualisierung Ihrer Kundendaten (Geldwäschegesetz)", [("Kundennummer", "7712 0045 88")],
                      "nach dem Geldwäschegesetz sind wir verpflichtet, Ihre Angaben regelmäßig zu aktualisieren. Bitte senden Sie uns eine Kopie "
                      "Ihres gültigen Ausweises und den ausgefüllten Selbstauskunftsbogen.", "Ausweiskopie und Selbstauskunft einreichen",
                      "2025-12-30", "bank_letter"))  # fmt: skip

    kfz = O.company("Beispiel Versicherung AG", "Versicherungsplatz 1", "80331", "Musterhausen", monogram="BV", accent=(0, 60, 120), style="logo",
                    tagline="Kfz-Schadenservice", phone="089 123 460", email="kfz-schaden@beispiel-versicherung.example", account="1234600")  # fmt: skip
    # test D1: Wed 06.05.2026, 10 Arbeitstage: Do 7(1) Fr 8(2) Mo 11(3) Di 12(4) Mi 13(5) [Himmelfahrt] Fr 15(6) Mo 18(7) Di 19(8)
    #          Mi 20(9) Do 21(10) → Thu 21.05.2026
    cases.append(make("test-relative_business_days-D1", "test", "D", kfz, O.P_GEN, date(2026, 5, 6), 10, "business_days",
                      "Bitte senden Sie uns den ausgefüllten Fragebogen **innerhalb von 10 Arbeitstagen (Montag bis Freitag, ohne Feiertage) nach dem "
                      "Briefdatum** zurück.",
                      "Kfz-Haftpflichtschaden vom 28.04.2026 – Fragebogen zum Unfallhergang", [("Schaden-Nr.", "KH-26-0428-112"), ("Kennzeichen", "MS-MB 77")],
                      "Ihr Unfallgegner hat Ansprüche aus dem Verkehrsunfall vom 28.04.2026 bei uns geltend gemacht. Um die Haftungsfrage zu klären, "
                      "benötigen wir Ihre Schilderung des Unfallhergangs.", "Fragebogen zum Unfallhergang zurücksenden", "2026-05-21", "insurance",
                      photo=True))  # fmt: skip
    return cases
