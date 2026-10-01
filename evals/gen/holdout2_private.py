"""Holdout2 split, families 4, 5, 6, 8, 9, 10 and 11: variants G and H of the invoices, dunning
letters, appointments, contracts, price changes, English letters and business-day periods.

Written like ``holdout2_admin`` (after the release's last code change, new senders, recipients, wording,
layout, dates and amounts; letter days drawn with a seeded choice among the days that fit each
scenario). The same generation rules as ``families_private`` hold: private-law deadlines never depend on
a Land's holidays, fixed dates fall on working days in every Land and Werktage counts never end on a
Saturday (all asserted).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import law
from . import orgs as O
from .common import Case, event_period_item, fixed_item, spec, today_after, truth, undated_item
from .families_admin import check, created
from .families_private import INVOICE_RULE, _contract_truth
from .holdout2_admin import SPLIT, STYLES, date_line
from .law import fmt
from .pdf import Block, Box, Letter, Org, P, Person, Sign, Style, Table
from .text import de, de_long, de_weekday, en_uk, en_us, eur_plain


def _info(variant: str, refs: list[tuple[str, str]], d: date) -> list[tuple[str, str]]:
    """Variant G prints the date first in the information block; variant H prints it above the subject."""
    return [("Datum", de(d)), *refs] if variant == "G" else list(refs)


def _line(variant: str, d: date) -> str | None:
    return None if variant == "G" else date_line(d)


def _net_vat_table(rows: list[tuple[str, float]], vat: float, header: tuple[str, str], labels: tuple[str, str, str],
                   vat_free: bool = False) -> tuple[Table, float]:  # fmt: skip
    net = round(sum(v for _, v in rows), 2)
    body = [(label, eur_plain(v)) for label, v in rows]
    n = len(rows)
    if vat_free:
        body.append((labels[2], eur_plain(net)))
        return Table(rows=tuple(body), header=header, value_width=30, bold_rows=(n,), rule_before=(n,)), net
    tax = round(net * vat, 2)
    total = round(net + tax, 2)
    body += [(labels[0], eur_plain(net)), (labels[1], eur_plain(tax)), (labels[2], eur_plain(total))]
    return Table(
        rows=tuple(body), header=header, value_width=30, bold_rows=(n + 2,), rule_before=(n, n + 2)
    ), total


# ==================================================================================================
# Family 4 — invoice_relative (a period of N days after the invoice date)
# ==================================================================================================


def invoice_relative() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, inv_date: date, days: int, refs: list[tuple[str, str]],
             table: Table, total: float, intro: str, pay_line: str, key: str, hand: str, subject: str, photo: bool = False,
             after: list[Block] | None = None) -> Case:  # fmt: skip
        item = check(
            event_period_item(event=inv_date, amount=days, unit="days", region=None, kind="payment", nature="payment",
                              title=f"{refs[0][1]} bezahlen", anchor="document_date", money=total, rule=INVOICE_RULE,
                              shift_citation="§ 193 BGB"),
            hand,
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, info=_info(variant, refs, inv_date), date_line=_line(variant, inv_date), subject=subject,
            salutation=salutation, blocks=[P(intro), table, P(pay_line), *(after or []), Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(inv_date), running_ref=" · ".join(f"{a} {b}" for a, b in refs),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="invoice_relative", variant=variant, letter=letter,
            truth=truth(kind="invoice", sender=org.name, document_date=inv_date, references=refs, amounts=[total], items=[item]),
            today=today_after(inv_date, case_id), authority_region=None, key_phrases=[de(inv_date), key, eur_plain(total)], photo=photo,
        )  # fmt: skip

    heating = O.company("Heizungsbau Beispielwärme GmbH", "Kesselstraße 14", "49084", "Musterosna", monogram="BW", accent=(150, 50, 10),
                        style="band", tagline="Heizung · Lüftung · Solar · Kundendienst", phone="0541 77 06 50",
                        email="rechnung@beispielwaerme.example", hr="AG Musterosna HRB 21 804", vat="USt-IdNr. DE 287 551 903",
                        account="7706500")  # fmt: skip
    table, total = _net_vat_table([("Wartung Gas-Brennwerttherme inkl. Abgasmessung", 149.00), ("Zündelektrode ersetzt", 38.40),
                                   ("Anfahrtspauschale", 29.50)], 0.19, ("Leistung", "EUR"),
                                  ("Nettobetrag", "zzgl. 19 % USt.", "Rechnungsbetrag"))  # fmt: skip
    # G1: Wed 25.11.2026 + 10 = Sat 05.12.2026 → Sun → Mon 07.12.2026
    cases.append(make(
        "holdout2-invoice_relative-G1", "G", heating, O.Q_GEN, "Sehr geehrte Frau Musterkamp,", date(2026, 11, 25), 10,
        [("Rechnung", "KD-2026-11873"), ("Kundennummer", "40 517")], table, total,
        "für die jährliche Wartung Ihrer Heizungsanlage im Ahornring 9 am 23.11.2026 berechnen wir Ihnen:",
        "Den Rechnungsbetrag erbitten wir ohne Abzug binnen 10 Tagen ab Rechnungsdatum auf das unten genannte Konto. Vielen Dank "
        "für Ihren Auftrag!",
        "binnen 10 Tagen ab Rechnungsdatum", "2026-12-07", "Rechnung KD-2026-11873 – Wartung Heizungsanlage", photo=True,
    ))  # fmt: skip

    school = O.company("Fahrschule Musterfahrt", "Bahnhofsallee 3", "21335", "Musterlüne", monogram="MF", accent=(0, 90, 160),
                       style="logo", tagline="Klasse B · BE · A2 · Auffrischungsstunden", phone="04131 40 30 20",
                       email="info@fahrschule-musterfahrt.example", account="4030200")  # fmt: skip
    table, total = _net_vat_table([("Übungsfahrten, 6 × 45 Min. à 62,00 €", 372.00), ("Sonderfahrt Autobahn, 2 × 45 Min.", 150.00),
                                   ("Vorstellung zur praktischen Prüfung", 165.00)], 0.19, ("Ausbildungsleistung", "EUR"),
                                  ("Netto", "MwSt. 19 %", "Gesamt"))  # fmt: skip
    # G2: Mon 08.09.2025 + 7 = Mon 15.09.2025 — a working day, no shift
    cases.append(make(
        "holdout2-invoice_relative-G2", "G", school, O.Q_GEN2, "Hallo Ruben,", date(2025, 9, 8), 7,
        [("Rechnungsnr.", "FS-25-0938"), ("Schüler-Nr.", "B-2214")], table, total,
        "herzlichen Glückwunsch zur bestandenen Prüfung am 04.09.2025! Für die letzten Fahrstunden und die Prüfung stellen wir "
        "dir in Rechnung:",
        "Bitte überweise den Gesamtbetrag binnen 7 Tagen nach dem Rechnungsdatum auf unser Konto bei der Musterbank AG (siehe unten).",
        "binnen 7 Tagen nach dem Rechnungsdatum", "2025-09-15", "Rechnung FS-25-0938",
    ))  # fmt: skip

    ortho = O.company("Privatpraxis Dr. med. Hanna Musterknie", "Am Klinikum 12", "22043", "Hamburg", monogram="MK", accent=(60, 40, 110),
                      style="minimal", tagline="Fachärztin für Orthopädie und Unfallchirurgie", phone="040 655 44 30",
                      email="abrechnung@praxis-musterknie.example", account="6554430")  # fmt: skip
    table = Table(rows=(("13.05.2026 · GOÄ 1 · Beratung, 2,3-fach", "10,72"), ("13.05.2026 · GOÄ 7 · Untersuchung, 2,3-fach", "21,45"),
                        ("13.05.2026 · GOÄ 5729 · MRT Kniegelenk, 1,8-fach", "257,04"),
                        ("22.06.2026 · GOÄ 3 · eingehende Beratung, 2,3-fach", "20,11"), ("Rechnungsbetrag", "309,32")),
                  header=("Datum · Ziffer · Leistung", "EUR"), value_width=26, bold_rows=(4,), rule_before=(4,))  # fmt: skip
    # H1: Fri 26.06.2026 + 30 = Sun 26.07.2026 → Mon 27.07.2026
    cases.append(make(
        "holdout2-invoice_relative-H1", "H", ortho, O.Q_HH, "Sehr geehrter Herr Mustermöller,", date(2026, 6, 26), 30,
        [("Rechnungsnummer", "2026-04471"), ("Patient", "PN 18 330")], table, 309.32,
        "für die ärztliche Behandlung (Diagnose: Innenmeniskusläsion rechts) berechne ich nach der Gebührenordnung für Ärzte:",
        "Bitte begleichen Sie den Rechnungsbetrag innerhalb von 30 Tagen nach dem Rechnungsdatum unter Angabe der Rechnungsnummer. "
        "Die Rechnung können Sie bei Ihrer privaten Krankenversicherung einreichen.",
        "innerhalb von 30 Tagen nach dem Rechnungsdatum", "2026-07-27", "Privatärztliche Liquidation", photo=True,
    ))  # fmt: skip

    tax = O.company("Steuerberatung Beispielmann & Partner mbB", "Kanzleistraße 8", "21335", "Musterlüne", monogram="BP",
                    accent=(20, 40, 80), style="band", tagline="Steuerberatung · Lohnbuchhaltung · Erbschaftsteuer",
                    phone="04131 22 33 40", email="kanzlei@beispielmann-partner.example", hr="PR 1127 AG Musterlüne",
                    account="2233400")  # fmt: skip
    table, total = _net_vat_table([("Einkommensteuererklärung 2024, § 24 Abs. 1 Nr. 1 StBVV", 412.00),
                                   ("Anlage V (zwei Objekte), § 24 Abs. 1 Nr. 1 StBVV", 186.00),
                                   ("Post- und Telekommunikationspauschale, § 16 StBVV", 20.00)], 0.19, ("Gegenstand", "EUR"),
                                  ("Summe netto", "Umsatzsteuer 19 %", "Zu zahlen"))  # fmt: skip
    # H2: Mon 26.05.2025 + 14 = Mon 09.06.2025 Pfingstmontag → Tue 10.06.2025
    cases.append(make(
        "holdout2-invoice_relative-H2", "H", tax, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", date(2025, 5, 26), 14,
        [("Rechnung Nr.", "2025/0712"), ("Mandant", "10 448")], table, total,
        "für unsere Tätigkeit im Zusammenhang mit Ihrer Einkommensteuererklärung 2024 erlauben wir uns, nach der "
        "Steuerberatervergütungsverordnung abzurechnen:",
        "Der Rechnungsbetrag ist ohne Abzug binnen 14 Tagen ab Rechnungsdatum fällig.",
        "binnen 14 Tagen ab Rechnungsdatum fällig", "2025-06-10", "Gebührenrechnung",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 5 — dunning_fixed (pay by an explicit date)
# ==================================================================================================


def dunning_fixed() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, due: date, due_text: str,
             subject: str, refs: list[tuple[str, str]], rows: list[tuple[str, float]], body: str, pay: str, signer: str,
             kind: str = "dunning", photo: bool = False, after: list[Block] | None = None) -> Case:  # fmt: skip
        total = round(sum(v for _, v in rows), 2)
        item = check(
            fixed_item(due=due, region=None, kind="payment", nature="payment", title="Offenen Betrag bezahlen", money=total,
                       rule="Payment date stated in the reminder."),
            due.isoformat(),
        )  # fmt: skip
        assert all(law.is_working_day(due, land) for land in law.LAENDER)
        table = Table(rows=(*((label, eur_plain(v)) for label, v in rows), ("Gesamtforderung", eur_plain(total))),
                      header=("Offene Posten", "EUR"), bold_rows=(len(rows),), rule_before=(len(rows),))  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date),
            date_line=_line(variant, letter_date),
            blocks=[P(body), table, P(pay.format(due=due_text)), *(after or []), Sign("Mit freundlichen Grüßen", (signer,))],
            style=STYLES[variant], created=created(letter_date), running_ref=" · ".join(f"{a} {b}" for a, b in refs),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="dunning_fixed", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[total], items=[item]),
            today=today_after(letter_date, case_id), authority_region=None,
            key_phrases=[de(letter_date), due_text.replace("**", ""), eur_plain(total)], photo=photo,
        )  # fmt: skip

    mobile = O.company("Beispielfon Mobilfunk GmbH", "Antennenring 2", "40472", "Musterdüssel", monogram="BF", accent=(110, 0, 90),
                       style="band", tagline="Mobilfunk · Internet · Festnetz", phone="0800 330 44 55", email="forderung@beispielfon.example",
                       hr="AG Musterdüssel HRB 90 114", account="3304455")  # fmt: skip
    due = date(2025, 9, 2)  # Tue, a working day everywhere
    cases.append(make(
        "holdout2-dunning_fixed-G1", "G", mobile, O.Q_GEN, "Guten Tag Frau Musterkamp,", date(2025, 8, 19), due,
        f"bis spätestens {de_weekday(due)}", "Zahlungserinnerung zu Ihrem Mobilfunkvertrag",
        [("Kundennummer", "771 204 558"), ("Rufnummer", "0176 4401 2290")], [("Rechnung Juli 2025", 34.99), ("Rücklastschriftgebühr Ihrer Bank", 3.00)],
        "die Abbuchung der Rechnung vom 03.08.2025 ist leider nicht gelungen – Ihre Bank hat die Lastschrift zurückgegeben. Die "
        "Gebühr, die uns die Bank dafür berechnet, geben wir an Sie weiter.",
        "Gleichen Sie den Rückstand bitte {due} aus; eine Überweisung oder die Zahlung im Kundenportal genügt. Danach buchen wir "
        "wieder wie gewohnt ab.", "Ihr Beispielfon Kundenservice", photo=True,
    ))  # fmt: skip

    inkasso = O.company("Beispiel Inkasso Service GmbH", "Forderungsweg 10", "20097", "Hamburg", monogram="BI", accent=(40, 60, 70),
                        style="logo", tagline="Registriert nach § 10 RDG beim Präsidenten des Amtsgerichts Muster", phone="040 300 66 70",
                        email="kundenservice@beispiel-inkasso.example", hr="AG Hamburg HRB 155 309", account="3006670")  # fmt: skip
    due = date(2027, 3, 2)  # Tue
    cases.append(make(
        "holdout2-dunning_fixed-G2", "G", inkasso, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", date(2027, 2, 9), due,
        f"bis zum **{de(due)}**", "Forderung der Beispiel Gartenmarkt GmbH – Bestellung vom 14.11.2026",
        [("Unser Zeichen", "BIS-27-018834"), ("Auftraggeberin", "Beispiel Gartenmarkt GmbH")],
        [("Hauptforderung, Rechnung GM-26-77410 vom 16.11.2026", 236.40), ("Verzugszinsen bis heute", 3.62), ("Inkassokosten (§ 13e RDG)", 42.49)],
        "die Beispiel Gartenmarkt GmbH hat uns beauftragt, ihre Forderung aus Ihrer Bestellung eines Hochbeets und von Zubehör "
        "einzuziehen. Die Ware wurde am 18.11.2026 geliefert; trotz Rechnung und Mahnung der Auftraggeberin ist keine Zahlung "
        "eingegangen.",
        "Wir fordern Sie auf, die Gesamtforderung {due} auf das unten angegebene Konto zu zahlen. Wenn Sie die Forderung für "
        "unberechtigt halten, teilen Sie uns Ihre Gründe bitte innerhalb dieser Zeit schriftlich mit.", "Beispiel Inkasso Service GmbH",
        after=[P("Datenschutzhinweis: Ihre Daten verarbeiten wir zur Durchsetzung der Forderung (Art. 6 Abs. 1 lit. f DSGVO).", size=7.8)],
    ))  # fmt: skip

    energy = O.company("Beispiel Energie Nordost GmbH", "Kraftwerksallee 7", "17489", "Mustergreifs", monogram="EN", accent=(0, 80, 60),
                       style="minimal", tagline="Strom und Gas – bundesweit (Musterausgabe)", phone="03834 55 70 0",
                       email="mahnung@beispiel-energie-nordost.example", account="5570000")  # fmt: skip
    due = date(2025, 4, 23)  # Wed
    cases.append(make(
        "holdout2-dunning_fixed-H1", "H", energy, O.Q_GEN, "Sehr geehrte Frau Musterkamp,", date(2025, 4, 16), due,
        f"bis zum **{de_long(due)}**", "Mahnung und Androhung der Unterbrechung der Stromversorgung",
        [("Vertragskonto", "300 4471 882"), ("Zählernummer", "1EBZ0100447218")],
        [("Abschläge Februar und März 2025", 196.00), ("Mahngebühr", 2.50)],
        "trotz unserer Zahlungserinnerung vom 24.03.2025 sind die Abschläge für Ihre Lieferstelle Ahornring 9 weiterhin offen.",
        "Bitte begleichen Sie den Gesamtbetrag {due}. Geht bis dahin keine Zahlung ein, sind wir nach § 19 StromGVV berechtigt, "
        "die Versorgung frühestens vier Wochen nach dieser Androhung durch den Netzbetreiber unterbrechen zu lassen; den genauen "
        "Termin kündigen wir Ihnen acht Werktage vorher an. Die Kosten der Unterbrechung und Wiederherstellung trügen Sie.",
        "Ihre Beispiel Energie Nordost – Forderungsmanagement",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 6 — appointment
# ==================================================================================================


def appointment() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, when: date, time: str,
             subject: str, refs: list[tuple[str, str]], body: list[Block], key: list[str], kind: str = "appointment",
             photo: bool = False, note: str = "", amounts: list[float] | None = None, closing: tuple[str, ...] = ()) -> Case:  # fmt: skip
        item = check(
            fixed_item(due=when, region=org.region, kind="appointment", nature="appointment", title=subject, time=time,
                       rule="Appointment set by the sender; appointments are never shifted.", appointment=True),
            when.isoformat(),
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date),
            date_line=_line(variant, letter_date), blocks=[*body, Sign("Mit freundlichen Grüßen", closing or (org.name,))],
            style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="appointment", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=amounts or [], items=[item]),
            today=today_after(letter_date, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), *key], photo=photo, notes=note,
        )  # fmt: skip

    md = O.company("Medizinischer Dienst Beispielland", "Gutachterweg 6", "49082", "Musterosna", monogram="MD", accent=(0, 85, 110),
                   style="logo", tagline="Begutachtung Pflege", phone="0541 66 09-0", email="pflege@md-beispielland.example",
                   account="6609000")  # fmt: skip
    when = date(2026, 8, 26)  # Wed
    cases.append(make(
        "holdout2-appointment-G1", "G", md, O.Q_GEN, "Sehr geehrte Frau Musterkamp,", date(2026, 8, 14), when, "10:30",
        "Begutachtung zur Feststellung der Pflegebedürftigkeit – Ihr Hausbesuch", [("Auftragsnummer", "PG-2026-118 734")],
        [P("Ihre Pflegekasse hat uns beauftragt, Ihre Pflegebedürftigkeit festzustellen. Unsere Gutachterin, Frau Rehberg, besucht Sie "
           f"dazu am **{de_weekday(when)} um 10:30 Uhr** in Ihrer Wohnung, Ahornring 9."),
         P("Halten Sie bitte Arztberichte, Ihren Medikamentenplan und – falls vorhanden – ein Pflegetagebuch bereit. Es ist hilfreich, "
           "wenn eine Person dabei ist, die Sie pflegt. Der Besuch dauert etwa eine Stunde. Können Sie den Termin nicht wahrnehmen, "
           "rufen Sie uns bitte umgehend an; ohne Begutachtung kann Ihre Pflegekasse nicht entscheiden.")],
        [de_weekday(when), "10:30 Uhr"], photo=True, closing=("Ihr Medizinischer Dienst Beispielland",),
    ))  # fmt: skip

    police = Org(name="Polizeipräsidium Beispielfurt", kind="authority", street="Wachstraße 14", postcode="60322",
                 city="Musterfurt am Main", region="HE", head=("Land Hessen · Polizei", "Kriminalinspektion 2 – Kommissariat 21"),
                 phone="069 755-0", email="k21.beispielfurt@polizei.hessen.example", style="authority", accent=(0, 60, 120))  # fmt: skip
    when = date(2025, 6, 2)  # Mon
    cases.append(make(
        "holdout2-appointment-G2", "G", police, O.Q_HE, "Sehr geehrter Herr Beispielhofer,", date(2025, 5, 9), when, "09:15",
        "Vorladung zur Vernehmung als Zeuge", [("Tagebuchnummer", "ST/0418877/2025")],
        [P("in einem Ermittlungsverfahren wegen Sachbeschädigung (beschädigte Fahrzeuge in der Tiefgarage Uferweg am 21.04.2025) "
           "kommen Sie als Zeuge in Betracht. Ich bitte Sie deshalb, zu einer Vernehmung zu erscheinen:"),
         Box((f"Termin: {de_weekday(when)}, 09:15 Uhr", "Ort: Polizeipräsidium Beispielfurt, Wachstraße 14, Zimmer 3.118",
              "Bitte mitbringen: Personalausweis oder Reisepass, dieses Schreiben")),
         P("Wenn Sie verhindert sind, vereinbaren Sie bitte telefonisch einen anderen Termin (Durchwahl -21180). Als Zeuge können Sie "
           "eine Entschädigung nach dem JVEG für Fahrtkosten und Verdienstausfall beantragen.")],
        [f"Termin: {de_weekday(when)}, 09:15 Uhr"], closing=("Im Auftrag", "Kriminaloberkommissarin Feldmann"),
    ))  # fmt: skip

    meter = O.company("Beispiel Messdienst GmbH", "Zählerstraße 21", "45127", "Musteressen", monogram="BM", accent=(0, 100, 130),
                      style="band", tagline="Heizkostenabrechnung · Rauchwarnmelder · Wasserzähler", phone="0201 88 00 40",
                      email="termine@beispiel-messdienst.example", account="8800400")  # fmt: skip
    when = date(2026, 8, 22)  # a Saturday: appointments are not shifted
    cases.append(make(
        "holdout2-appointment-H1", "H", meter, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", date(2026, 7, 24), when, "08:45",
        "Austausch Ihrer Heizkostenverteiler und Wasserzähler", [("Liegenschaft", "Wiesengrund 21"), ("Nutzer-Nr.", "0214-07")],
        [P("im Auftrag Ihrer Hausverwaltung tauschen wir in allen Wohnungen die Heizkostenverteiler und Wasserzähler gegen funkende "
           f"Geräte aus. Für Ihre Wohnung haben wir **Samstag, {de(when)}, 08:45 Uhr** eingeplant."),
         P("Bitte sorgen Sie dafür, dass unser Monteur alle Heizkörper sowie Küche und Bad erreichen kann. Wenn Sie selbst nicht da "
           "sind, kann eine beauftragte Person die Wohnung öffnen. Passt der Termin nicht, melden Sie sich bitte online oder telefonisch "
           "unter 0201 88 00 40.")],
        [de(when), "08:45 Uhr"], note="Saturday appointment: must not be moved to Monday.",
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
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date),
            date_line=_line(variant, letter_date), blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="contract_confirmation", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[contract["price"]], items=[],
                        contract=contract),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), *key],
        )  # fmt: skip

    # G1 — newspaper subscription, § 309 Nr. 9 BGB (new): 12 months from Fri 25.06.2027 → Sat 24.06.2028; 1 month → Wed 24.05.2028.
    paper = O.company("Beispielstädter Tageblatt Verlag GmbH", "Pressehaus 1", "49074", "Musterosna", monogram="BT", accent=(30, 30, 30),
                      style="logo", tagline="Abonnentenservice", phone="0541 310 310", email="abo@beispielstaedter-tageblatt.example",
                      hr="AG Musterosna HRB 4410", account="3103100")  # fmt: skip
    case_id, concluded, start = "holdout2-contract_confirmation-G1", date(2027, 6, 18), date(2027, 6, 25)
    contract = _contract_truth(category="other", regime="bgb309_new", party_kind="company", concluded=concluded, start=start,
                               initial=12, renewal="indefinite, cancellable any time with 1 month notice", notice=1, notice_unit="months",
                               today=today_after(concluded, case_id), price=42.90, interval="monthly",
                               citations="Consumer subscription concluded after 2022-03-01: § 309 Nr. 9 BGB (n.F.).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2028-06-24",
        "2028-05-24",
    )
    cases.append(make(case_id, "G", paper, O.Q_GEN, "Sehr geehrte Frau Musterkamp,", concluded,
                      "Ihr Abonnement „Tageblatt Kombi“ – Bestätigung", [("Abo-Nummer", "TK-0098 4417"), ("Kundennummer", "551 207")],
                      [P(f"herzlich willkommen als Abonnentin! Ihre Bestellung vom {de(concluded)} bestätigen wir gern. Die gedruckte "
                         f"Zeitung erhalten Sie ab dem {de(start)} montags bis samstags; das E-Paper ist ab sofort freigeschaltet."),
                       Table(rows=(("Produkt", "Tageblatt Kombi (Zeitung + E-Paper)"), ("Lieferbeginn", de(start)),
                                   ("Bezugspreis", "42,90 € monatlich"),
                                   ("Mindestbezugsdauer", "12 Monate ab Lieferbeginn"),
                                   ("Kündigungsfrist", "1 Monat zum Ende der Mindestbezugsdauer"),
                                   ("Anschließend", "unbefristet, jederzeit mit 1 Monat Frist kündbar")),
                             header=("Ihr Abonnement", ""), value_width=104, value_align="L"),
                       P("Kündigen können Sie in Textform oder über den Kündigungsbutton auf unserer Website. Bei Urlaub stellen wir "
                         "Ihre Zeitung gern auf das E-Paper um.")],
                      contract, ["12 Monate ab Lieferbeginn", "42,90 €"]))  # fmt: skip

    # H1 — legal-expenses insurance, § 11 VVG: 1 year from Mon 01.02.2027 → Mon 31.01.2028; 3 months → Sun 31.10.2027 (not moved).
    legal = O.company("Beispiel Rechtsschutz Versicherung AG", "Paragraphenplatz 4", "65185", "Musterwiesbaden", monogram="BR",
                      accent=(90, 20, 60), style="band", tagline="Rechtsschutz für Privat, Beruf und Verkehr", phone="0611 900 77 00",
                      email="vertrag@beispiel-rechtsschutz.example", hr="AG Musterwiesbaden HRB 30 771", account="9007700")  # fmt: skip
    case_id, concluded, start = "holdout2-contract_confirmation-H1", date(2026, 12, 9), date(2027, 2, 1)
    contract = _contract_truth(category="insurance", regime="vvg11", party_kind="insurer", concluded=concluded, start=start, initial=12,
                               renewal="renews by 1 year unless cancelled 3 months before the end of the insurance year", notice=3,
                               notice_unit="months", today=today_after(concluded, case_id), price=298.40, interval="yearly",
                               citations="Insurance contract: § 11 VVG (yearly renewal, notice as written, max. 3 months).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2028-01-31",
        "2027-10-31",
    )
    cases.append(make(case_id, "H", legal, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", concluded,
                      "Versicherungsschein – Privat-, Berufs- und Verkehrsrechtsschutz", [("Versicherungsschein-Nr.", "RS 4471-0098-22")],
                      [P("vielen Dank für Ihr Vertrauen. Hiermit erhalten Sie Ihren Versicherungsschein:"),
                       Table(rows=(("Versicherungsbeginn", f"{de(start)}, 0:00 Uhr"), ("Vertragsdauer", "1 Jahr"),
                                   ("Wartezeit", "3 Monate (nicht für Verkehrsrechtsschutz)"),
                                   ("Selbstbeteiligung", "150 € je Rechtsschutzfall"), ("Jahresbeitrag", "298,40 €")),
                             header=("Vertragsdaten", ""), value_width=96, value_align="L"),
                       P("Der Vertrag verlängert sich jeweils um ein weiteres Jahr, wenn er nicht spätestens drei Monate vor Ablauf "
                         "des Versicherungsjahres in Textform gekündigt wird."),
                       P("Den ersten Jahresbeitrag ziehen wir zum Versicherungsbeginn per Lastschrift ein.")],
                      contract, ["spätestens drei Monate vor Ablauf", "298,40 €"], kind="insurance"))  # fmt: skip
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
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date),
            date_line=_line(variant, letter_date), blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="price_increase", variant=variant, letter=letter,
            truth=truth(kind="price_increase", sender=org.name, document_date=letter_date, references=refs, amounts=[old, new], items=[],
                        optional_items=optional, price_change=change),
            today=today_after(letter_date, case_id), authority_region=None, key_phrases=[de(letter_date), de(effective), *key],
        )  # fmt: skip

    gas = O.company("Gasversorgung Beispielhain GmbH", "Gasometerweg 3", "49080", "Beispielhain", monogram="GB", accent=(150, 70, 0),
                    style="logo", tagline="Erdgas für Haushalt und Gewerbe", phone="0541 2002-0", email="kundenservice@gas-beispielhain.example",
                    account="2002000")  # fmt: skip
    eff = date(2025, 5, 1)
    cases.append(make(
        "holdout2-price_increase-G1", "G", gas, O.Q_GEN, "Sehr geehrte Frau Musterkamp,", date(2025, 3, 7), eff, "enwg41_5", 89.00, 97.00,
        f"Preisanpassung zum {de(eff)} – Tarif „Beispielhain Gas Komfort“", [("Kundennummer", "GB-2207 4419"), ("Verbrauchsstelle", "Ahornring 9")],
        [P(f"zum {de(eff)} passen wir die Preise Ihres Erdgastarifs an. Grund sind höhere Kosten für die Gasspeicherung und gestiegene "
           "Netzentgelte; den CO₂-Preis geben wir unverändert weiter."),
         Table(rows=(("Arbeitspreis (brutto)", "10,84 ct/kWh → 11,92 ct/kWh"), ("Grundpreis (brutto)", "14,90 €/Monat → 16,40 €/Monat"),
                     ("Monatlicher Abschlag", "89,00 € → 97,00 €")), header=("Preisbestandteil", "alt → neu"), value_width=62),
         P("Sie müssen nichts tun, wenn Sie einverstanden sind. Andernfalls haben Sie ein Sonderkündigungsrecht: Sie können den Vertrag "
           f"ohne Einhaltung einer Frist zum {de(eff)} kündigen (§ 41 Abs. 5 EnWG). Ihre Kündigung muss uns vor diesem Tag erreichen.")],
        ["ohne Einhaltung einer Frist"], "gas",
    ))  # fmt: skip

    net = O.company("Netzwelt Beispiel GmbH", "Glasfaserallee 9", "49084", "Musterosna", monogram="NW", accent=(0, 70, 140), style="minimal",
                    tagline="DSL · Glasfaser · Telefon", phone="0800 22 66 77", email="service@netzwelt-beispiel.example", account="2266770")  # fmt: skip
    eff = date(2025, 6, 1)
    cases.append(make(
        "holdout2-price_increase-H1", "H", net, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", date(2025, 4, 15), eff, "tkg57", 44.99, 49.99,
        "Ihr Tarif „Netzwelt DSL 100“: neuer Monatspreis", [("Kundennummer", "NWB-551 207 9")],
        [P(f"ab dem {de(eff)} kostet Ihr Tarif „Netzwelt DSL 100“ **49,99 €** statt bisher 44,99 € im Monat. Die Leistung bleibt unverändert; "
           "wir investieren in den Ausbau und die Wartung unseres Netzes."),
         P("Da die Änderung für Sie nachteilig ist, können Sie Ihren Vertrag nach § 57 Abs. 1 TKG ohne Einhaltung einer Kündigungsfrist "
           "und ohne Kosten kündigen. Das Kündigungsrecht besteht drei Monate ab Zugang dieser Mitteilung; der Vertrag endet frühestens "
           "zu dem Zeitpunkt, an dem der neue Preis wirksam wird.")],
        ["drei Monate ab Zugang dieser Mitteilung"], "internet",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 10 — english_letter
# ==================================================================================================


def english_letter() -> list[Case]:
    cases: list[Case] = []
    styles = {
        "G": Style(
            body_pt=9.8,
            left=22,
            right=22,
            leading=1.35,
            para_gap=2.3,
            align="L",
            subject_pt=10.8,
            info_label_pt=6.9,
        ),
        "H": Style(body_pt=10.1, left=25, right=22, leading=1.33, para_gap=2.4, align="L", subject_pt=11.2),
    }

    def letter_for(org: Org, person: Person, info: list[tuple[str, str]], subject: str, blocks: list[Block], variant: str,
                   when: date, salutation: str, closing: str, signer: tuple[str, ...] = ()) -> Letter:  # fmt: skip
        return Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation,
                      blocks=[*blocks, Sign(closing, signer or (org.name,))], style=styles[variant], created=created(when), lang="en")  # fmt: skip

    # G1 — bank, UK-style fixed date: Wed 29 October 2025.
    bank = O.company("Beispiel Direktbank AG", "Bankenplatz 2", "60311", "Musterfurt am Main", monogram="BD", accent=(0, 50, 100),
                     style="band", tagline="International Customer Service", phone="+49 69 555 7700",
                     email="international@beispiel-direktbank.example", account="5557700", hr="AG Musterfurt HRB 60 210")  # fmt: skip
    when, due = date(2025, 10, 9), date(2025, 10, 29)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration",
                            title="Return the tax residency self-certification", rule="Fixed date stated in the letter."),
                 "2025-10-29")  # fmt: skip
    cases.append(Case(
        id="holdout2-english_letter-G1", split=SPLIT, family="english_letter", variant="G",
        letter=letter_for(bank, O.Q_EN, [("Date", en_uk(when)), ("Customer no.", "7704 2219 03")],
                          "Your tax residency – self-certification required", [
            P("Under the Common Reporting Standard, banks in Germany must confirm in which countries their customers are resident for "
              "tax purposes. Our records show an address in Germany but a telephone number registered in Ghana."),
            P(f"Please complete the enclosed self-certification form and send it back to us **by {en_uk(due)}**. If we have not "
              "received it by then, we are required to report your account to the tax authorities of both countries."),
        ], "G", when, "Dear Ms Mensah,", "Kind regards,", ("International Customer Service",)),
        truth=truth(kind="bank_letter", sender=bank.name, document_date=when, references=[("Customer no.", "7704 2219 03")], amounts=[],
                    items=[item], lang="en"),
        today=today_after(when, "holdout2-english_letter-G1"), authority_region=None, key_phrases=[en_uk(when), en_uk(due)], photo=True,
    ))  # fmt: skip

    # G2 — bilingual kindergarten fees: 10 days from the invoice date. Tue 30 Dec 2025 + 10 = Fri 9 Jan 2026, a working day.
    kita = O.company("Little Explorers Beispiel gGmbH", "Kastanienallee 5", "22043", "Hamburg", monogram="LE", accent=(150, 60, 0),
                     style="logo", tagline="Bilingual kindergarten · English / Deutsch", phone="+49 40 555 3030",
                     email="office@little-explorers-beispiel.example", account="5553030")  # fmt: skip
    when = date(2025, 12, 30)
    total = 1188.00
    item = check(event_period_item(event=when, amount=10, unit="days", region=None, kind="payment", nature="payment",
                                   title="Pay invoice LE-26-0041", anchor="document_date", money=total,
                                   rule="Payment within 10 days of the invoice date (invoice day not counted).",
                                   shift_citation="§ 193 BGB", require_no_shift=True), "2026-01-09")  # fmt: skip
    cases.append(Case(
        id="holdout2-english_letter-G2", split=SPLIT, family="english_letter", variant="G",
        letter=letter_for(kita, O.Q_EN2, [("Date", en_uk(when)), ("Invoice", "LE-26-0041"), ("Child", "Lucía Herrera")],
                          "Invoice – childcare fees, January to March 2026", [
            P("Please find below the fees for Lucía's place in our Butterfly group for the first quarter of 2026."),
            Table(rows=(("Childcare fee, 3 months × 330,00", "990,00"), ("Lunch and snacks, 3 months × 66,00", "198,00"),
                        ("Total due (exempt from VAT, § 4 No. 25 UStG)", "1.188,00")), header=("Item", "EUR"), bold_rows=(2,),
                  rule_before=(2,)),
            P("The total is payable within 10 days of the invoice date. Please use the invoice number as the payment reference."),
        ], "G", when, "Dear Mr Herrera,", "Warm regards,", ("Little Explorers – Parent Office",)),
        truth=truth(kind="invoice", sender=kita.name, document_date=when, references=[("Invoice", "LE-26-0041")], amounts=[total],
                    items=[item], lang="en"),
        today=today_after(when, "holdout2-english_letter-G2"), authority_region=None,
        key_phrases=[en_uk(when), "within 10 days of the invoice date"],
    ))  # fmt: skip

    # H1 — US employer, US long-form dates: the signed offer letter is due on Wed March 26, 2025.
    employer = O.company("Example Analytics, Inc.", "400 Example Street, Suite 1200", "CA 94105", "San Francisco", monogram="EA",
                         accent=(30, 30, 100), style="minimal", tagline="People Operations", phone="+1 415 555 0142",
                         email="people@example-analytics.example", account="1420142", country="USA")  # fmt: skip
    employer = Org(
        **{
            **employer.__dict__,
            "iban": "",
            "bank": "",
            "bic": "",
            "postcode": "",
            "city": "San Francisco, CA 94105",
        }
    )
    when, due = date(2025, 3, 12), date(2025, 3, 26)
    item = check(fixed_item(due=due, region=None, kind="deadline", nature="declaration", title="Return the signed offer letter",
                            rule="Fixed date stated in the letter."), "2025-03-26")  # fmt: skip
    cases.append(Case(
        id="holdout2-english_letter-H1", split=SPLIT, family="english_letter", variant="H",
        letter=letter_for(employer, O.Q_EN2, [("Date", en_us(when)), ("Requisition", "REQ-2025-0318")], "Offer of employment", [
            P("We are delighted to offer you the position of Senior Data Engineer, working remotely from Germany through our employer "
              "of record, starting May 5, 2025, at an annual base salary of EUR 92,000.00."),
            P(f"To accept, please sign the enclosed offer letter and return it to People Operations no later than **{en_us(due)}**. "
              "After that date the offer lapses."),
        ], "H", when, "Dear Tomás:", "Sincerely,", ("People Operations",)),
        truth=truth(kind="employment", sender=employer.name, document_date=when, references=[("Requisition", "REQ-2025-0318")],
                    amounts=[92000.0], items=[item], lang="en"),
        today=today_after(when, "holdout2-english_letter-H1"), authority_region=None, key_phrases=[en_us(when), en_us(due)],
    ))  # fmt: skip

    # H2 — the ambiguous one: 08/09/2027 = Mon 9 Aug (US) or Wed 8 Sep (day/month) — both working days after "today"; the letter's
    # own date 07/07/2027 reads the same either way and the salutation ends with a comma (no locale hint).
    flats = O.company("Beispiel Living Apartments GmbH", "Hafenterrassen 2", "20457", "Hamburg", monogram="BL", accent=(0, 90, 90),
                      style="band", tagline="Furnished apartments for international residents", phone="+49 40 555 6060",
                      email="lettings@beispiel-living.example", account="5556060")  # fmt: skip
    when = date(2027, 7, 7)  # printed 07/07/2027
    a, b = date(2027, 8, 9), date(2027, 9, 8)
    amb = undated_item(kind="deadline", nature="declaration", title="Return the signed lease and proof of the deposit transfer",
                       spec=spec("fixed", anchor="explicit_date", shift=False), expected_due="ambiguous",
                       derivation=f"'08/09/2027' reads as {fmt(a)} (US month/day) or {fmt(b)} (day/month); the letter gives no reliable "
                                  "locale hint (a German landlord writing English, its own date 07/07/2027 is symmetric), so the date is "
                                  "ambiguous and must not be stated confidently.",
                       candidates=[a.isoformat(), b.isoformat()])  # fmt: skip
    cases.append(Case(
        id="holdout2-english_letter-H2", split=SPLIT, family="english_letter", variant="H",
        letter=letter_for(flats, O.Q_EN, [("Date", "07/07/2027"), ("Reference", "BL-APT-3.12")], "Your apartment at Hafenterrassen 2", [
            P("Thank you for choosing apartment 3.12. We have reserved it for you from the date you mentioned in your application."),
            P("To complete the booking, please return the signed lease together with proof that you have transferred the deposit by "
              "**08/09/2027**. After that we will release the apartment to the next applicant."),
        ], "H", when, "Dear Ms Mensah,", "Best regards,", ("Lettings Team",)),
        truth=truth(kind="rent_lease", sender=flats.name, document_date=when, references=[("Reference", "BL-APT-3.12")], amounts=[],
                    items=[amb], expect_low_confidence=True, lang="en"),
        today=today_after(when, "holdout2-english_letter-H2"), authority_region=None, key_phrases=["07/07/2027", "08/09/2027"],
        notes="Intentionally ambiguous numeric date; truth is 'ambiguous' (document date 7 July, symmetric).",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 11 — relative_business_days (Werktage Mon–Sat vs Arbeitstage Mon–Fri, holidays excluded)
# ==================================================================================================


def business_days() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, amount: int, unit: str,
             phrase: str, subject: str, refs: list[tuple[str, str]], body_before: str, task: str, hand: str, kind: str,
             photo: bool = False, after: str = "") -> Case:  # fmt: skip
        label = "Werktage: Monday–Saturday excluding public holidays (general meaning, cf. § 3 Abs. 2 BUrlG; defined in the letter)" if unit == "werktage" \
            else "Arbeitstage: Monday–Friday excluding public holidays (defined in the letter)"  # fmt: skip
        item = check(
            event_period_item(event=letter_date, amount=amount, unit=unit, region=None, kind="deadline", nature="declaration", title=task,
                              anchor="document_date", rule=f"Period of {amount} {label}, counted from the day after the letter date (§ 187 Abs. 1 BGB).",
                              shift_citation="§ 193 BGB", forbid_saturday_end=unit == "werktage", require_no_shift=True),
            hand,
        )  # fmt: skip
        letter = Letter(
            org=org, recipient=person, subject=subject, salutation=salutation, info=_info(variant, refs, letter_date),
            date_line=_line(variant, letter_date),
            blocks=[P(body_before), P(phrase), *([P(after)] if after else []), Sign("Mit freundlichen Grüßen", (org.name,))],
            style=STYLES[variant], created=created(letter_date),
        )  # fmt: skip
        key = phrase.split("**")[1]
        return Case(
            id=case_id, split=SPLIT, family="relative_business_days", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[], items=[item]),
            today=today_after(letter_date, case_id, 1, 3), authority_region=None, key_phrases=[de(letter_date), key], photo=photo,
        )  # fmt: skip

    bank = O.company("Musterbank Lüne eG", "Marktstieg 40", "21335", "Musterlüne", monogram="ML", accent=(0, 60, 130), style="logo",
                     tagline="Baufinanzierung", phone="04131 707-0", email="baufinanzierung@musterbank-luene.example", account="7070000",
                     hr="GnR 112 AG Musterlüne")  # fmt: skip
    # G1: Thu 02.10.2025, 8 Werktage: [Fr 03.10. Tag der Deutschen Einheit] Sa 04(1) Mo 06(2) Di 07(3) Mi 08(4) Do 09(5) Fr 10(6)
    #     Sa 11(7) Mo 13(8) → Mon 13.10.2025
    cases.append(make("holdout2-relative_business_days-G1", "G", bank, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", date(2025, 10, 2), 8,
                      "werktage",
                      "Wir brauchen die Unterlagen **innerhalb von 8 Werktagen, gerechnet ab dem Tag nach dem Datum dieses Schreibens**; "
                      "Samstage zählen mit, Sonn- und Feiertage nicht. Danach können wir den angebotenen Zinssatz nicht mehr garantieren.",
                      "Ihre Finanzierungsanfrage – fehlende Unterlagen", [("Anfrage-Nr.", "BF-2025-3317")],
                      "für die Prüfung Ihrer Anfrage über ein Darlehen zum Kauf der Wohnung Wiesengrund 23 fehlen uns noch "
                      "Ihre letzten drei Gehaltsabrechnungen, der Grundbuchauszug und die Teilungserklärung.",
                      "Unterlagen zur Finanzierungsanfrage einreichen", "2025-10-13", "bank_letter"))  # fmt: skip

    manager = O.company("Verwaltung Musterhof GmbH", "Hofstraße 11", "49074", "Musterosna", monogram="VM", accent=(70, 70, 40), style="band",
                        tagline="Haus- und WEG-Verwaltung", phone="0541 98 76 50", email="technik@verwaltung-musterhof.example",
                        account="9876500")  # fmt: skip
    # G2: Wed 20.05.2026, 5 Arbeitstage: Do 21(1) Fr 22(2) [Mo 25.05. Pfingstmontag] Di 26(3) Mi 27(4) Do 28(5) → Thu 28.05.2026
    cases.append(make("holdout2-relative_business_days-G2", "G", manager, O.Q_GEN, "Sehr geehrte Frau Musterkamp,", date(2026, 5, 20), 5,
                      "business_days",
                      "Bitte vereinbaren Sie **binnen 5 Arbeitstagen ab Briefdatum** einen Termin mit der Firma Trocknungstechnik "
                      "Beispiel (Telefon 0541 22 11 00); Arbeitstage sind Montag bis Freitag, gesetzliche Feiertage ausgenommen.",
                      "Wasserschaden aus der Wohnung über Ihnen – Trocknung Ihrer Decke", [("Objekt", "Ahornring 9, 2. OG links")],
                      "nach dem Rohrbruch in der Wohnung über Ihnen hat der Gutachter der Gebäudeversicherung festgestellt, dass die "
                      "Decke in Ihrem Badezimmer technisch getrocknet werden muss.",
                      "Termin für die Bautrocknung vereinbaren", "2026-05-28", "rent_lease",
                      after="Melden Sie sich nicht fristgerecht, müssen wir den Termin ohne Rücksprache mit Ihnen festlegen."))  # fmt: skip

    insurer = O.company("Musterländische Versicherung VVaG", "Sicherheitsplatz 1", "48143", "Mustermünster", monogram="MV",
                        accent=(0, 80, 50), style="minimal", tagline="Hausrat · Haftpflicht · Wohngebäude", phone="0251 702-0",
                        email="schaden@musterlaendische.example", account="7020000")  # fmt: skip
    # H1: Mon 20.07.2026, 10 Werktage: Di 21(1) Mi 22(2) Do 23(3) Fr 24(4) Sa 25(5) Mo 27(6) Di 28(7) Mi 29(8) Do 30(9) Fr 31(10)
    #     → Fri 31.07.2026 (no holiday)
    cases.append(make("holdout2-relative_business_days-H1", "H", insurer, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", date(2026, 7, 20), 10,
                      "werktage",
                      "Senden Sie uns die Stehlgutliste und die Kaufbelege bitte **spätestens 10 Werktage nach dem Datum dieses Briefes**; "
                      "Werktage sind dabei Montag bis Samstag ohne die gesetzlichen Feiertage.",
                      "Ihr Schaden vom 11.07.2026 – Einbruchdiebstahl", [("Schadennummer", "HR-26-0714 882"), ("Vertrag", "MV 55 120 447")],
                      "wir haben Ihre Schadenmeldung zum Einbruch in Ihre Wohnung erhalten. Damit wir den Schaden regulieren können, "
                      "brauchen wir eine vollständige Liste der gestohlenen Gegenstände mit Anschaffungsjahr und Preis.",
                      "Stehlgutliste und Belege einreichen", "2026-07-31", "insurance", photo=True,
                      after="Die Liste reichen Sie bitte auch bei der Polizei ein, damit die Gegenstände in die Fahndung aufgenommen werden."))  # fmt: skip
    return cases
