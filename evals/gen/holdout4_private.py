"""Holdout4 split, families 4, 5, 6, 8, 9, 10 and 11: variants K, L, M and N of the invoices, dunning letters,
appointments, contracts, price changes, English letters and business-day periods.

Written like ``holdout4_admin`` (for the reading day 2026-11-24; new senders, recipients, wording, layout and amounts;
letter days drawn with ``rng_for("holdout4", case_id)`` and asserted next to the hand-worked labels). The generation rules
of the private families hold: private-law deadlines never depend on a Land's holidays, fixed dates fall on working days in
every Land, and a count of Werktage never ends on a Saturday (all asserted).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import law
from . import orgs as O
from .common import Case, event_period_item, fixed_item, spec, truth, undated_item, with_conventions
from .families_admin import check, created
from .families_private import INVOICE_RULE, _contract_truth
from .holdout4_admin import (
    AUTHORITY_DAYS,
    PRIVATE_DAYS,
    S_EN,
    S_EN2,
    S_GEN,
    S_GEN2,
    S_ST,
    SPLIT,
    STYLES,
    TODAY,
    authority,
    drawn,
    place_date,
    tag_plain,
)
from .law import fmt
from .pdf import Block, Box, Letter, Org, P, Person, Sign, Style, Table
from .text import de, de_long, de_weekday, en_uk, en_us, eur_plain

PRIVATE_IDS = ("c01", "c06")


def _layout(
    variant: str, org: Org, refs: list[tuple[str, str]], d: date, label: str
) -> tuple[list[tuple[str, str]], str | None]:
    """K and N: place and date above the subject; L: the date first in the information block; M: under ``label`` last."""
    if variant in ("K", "N"):
        return list(refs), place_date(org, d)
    if variant == "L":
        return [("Datum", de(d)), *refs], None
    return [*refs, (label, de(d))], None


def _sum_table(
    rows: list[tuple[str, float]], header: tuple[str, str], total_label: str, vat: float | None = 0.19
) -> tuple[Table, float]:
    """Line items, then net / VAT / total (or only the total for a VAT-exempt service)."""
    net = round(sum(v for _, v in rows), 2)
    body = [(label, eur_plain(v)) for label, v in rows]
    n = len(rows)
    if vat is None:
        body.append((total_label, eur_plain(net)))
        return Table(rows=tuple(body), header=header, value_width=30, bold_rows=(n,), rule_before=(n,)), net
    tax = round(net * vat, 2)
    total = round(net + tax, 2)
    body += [("Summe ohne Umsatzsteuer", eur_plain(net)), (f"Umsatzsteuer {round(vat * 100)} %", eur_plain(tax)),
             (total_label, eur_plain(total))]  # fmt: skip
    return Table(
        rows=tuple(body), header=header, value_width=30, bold_rows=(n + 2,), rule_before=(n, n + 2)
    ), total


def _private_case(case_id: str, family: str, variant: str, letter: Letter, t: dict[str, Any], key: list[str], *,
                  region: str | None = None, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
    return Case(id=case_id, split=SPLIT, family=family, variant=variant, letter=letter, truth=t, today=TODAY,
                authority_region=region, recipient_region=region, key_phrases=key, photo=photo, notes=notes)  # fmt: skip


# ==================================================================================================
# Family 4 — invoice_relative (a period of N days after the invoice date)
# ==================================================================================================


def invoice_relative() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, inv_date: date, days: int,
             refs: list[tuple[str, str]], table: Table, total: float, intro: str, pay_line: str, key: str, hand: str,
             subject: str, *, photo: bool = False, closing: tuple[str, ...] = ()) -> Case:  # fmt: skip
        item = check(
            event_period_item(event=inv_date, amount=days, unit="days", region=None, kind="payment", nature="payment",
                              title=f"{refs[0][1]} bezahlen", anchor="document_date", money=total, rule=INVOICE_RULE,
                              shift_citation="§ 193 BGB"),
            hand,
        )  # fmt: skip
        info, date_line = _layout(variant, org, refs, inv_date, "Rechnungsdatum")
        letter = Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation, date_line=date_line,
                        blocks=[P(intro), table, P(pay_line), Sign("Mit freundlichen Grüßen", closing or (org.name,))],
                        style=STYLES[variant], created=created(inv_date), running_ref=" · ".join(f"{a} {b}" for a, b in refs))  # fmt: skip
        return _private_case(
            case_id, "invoice_relative", variant, letter,
            truth(kind="invoice", sender=org.name, document_date=inv_date, references=refs, amounts=[total],
                  items=[tag_plain(item, *PRIVATE_IDS)]),
            [de(inv_date), key, eur_plain(total)], photo=photo,
        )  # fmt: skip

    # K1 (photo): Thu 19.11.2026 + 14 = Thu 03.12.2026, a working day.
    k1 = "holdout4-invoice_relative-K1"
    d = drawn(k1, PRIVATE_DAYS, date(2026, 11, 19))
    org = O.company("Schornsteintechnik Beispielruß GmbH", "Kaminweg 4", "35578", "Musterhöhe", monogram="SR",
                    accent=(90, 40, 30), style="band", tagline="Schornsteinsanierung · Abgasanlagen · Kaminöfen",
                    phone="06441 555 72 40", email="rechnung@beispielruss.example", account="5572400")  # fmt: skip
    table, total = _sum_table([("Edelstahl-Abgasrohr einziehen, 9 m", 1240.00), ("Anschlussstück und Reinigungstür", 186.00),
                               ("Abnahme durch den Bezirksschornsteinfeger (Fremdleistung)", 74.50)],
                              ("Ausgeführte Arbeiten", "EUR"), "Zu zahlen")  # fmt: skip
    cases.append(make(
        k1, "K", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, 14, [("Rechnungs-Nr.", "SR-26-0914"), ("Objekt", "Quellenweg 7")],
        table, total, "für die Sanierung Ihres Schornsteins am 16. und 17.11.2026 stellen wir Ihnen folgende Leistungen in Rechnung:",
        "Bitte begleichen Sie den Betrag binnen 14 Tagen ab dem Rechnungsdatum ohne Abzug.",
        "binnen 14 Tagen ab dem Rechnungsdatum", "2026-12-03", "Rechnung Schornsteinsanierung", photo=True,
    ))  # fmt: skip

    # K2: Sat 21.11.2026 + 21 = Sat 12.12.2026 → Mon 14.12.2026.
    k2 = "holdout4-invoice_relative-K2"
    d = drawn(k2, PRIVATE_DAYS, date(2026, 11, 21))
    org = O.company("Fotostudio Beispiellicht", "Bildergasse 12", "48143", "Mustermünster", monogram="FB", accent=(30, 30, 30),
                    style="minimal", tagline="Porträts · Hochzeiten · Bewerbungsbilder", phone="0251 555 31 08",
                    email="studio@beispiellicht.example", account="5531080")  # fmt: skip
    table, total = _sum_table([("Familienshooting im Studio, 90 Minuten", 180.00), ("12 bearbeitete Bilddateien", 96.00),
                               ("Fotobuch 30 × 30 cm, 40 Seiten", 89.00)], ("Leistung", "EUR"), "Rechnungsbetrag")  # fmt: skip
    cases.append(make(
        k2, "K", org, S_GEN2, "Liebe Frau Beispielacker,", d, 21, [("Rechnung", "FB-2026-388")], table, total,
        "herzlichen Dank für den schönen Nachmittag mit Ihrer Familie. Hier ist unsere Rechnung:",
        "Überweisen Sie den Rechnungsbetrag bitte spätestens 21 Tage nach dem Datum dieser Rechnung.",
        "spätestens 21 Tage nach dem Datum dieser Rechnung", "2026-12-14", "Ihre Rechnung vom Fotostudio",
        closing=("Ihr Fotostudio Beispiellicht",),
    ))  # fmt: skip

    # L1 (photo): Thu 19.11.2026 + 30 = Sat 19.12.2026 → Mon 21.12.2026.
    l1 = "holdout4-invoice_relative-L1"
    d = drawn(l1, PRIVATE_DAYS, date(2026, 11, 19))
    org = O.company("Hörakustik Beispielklang", "Marktstraße 31", "35390", "Mustergießen", monogram="HK", accent=(0, 90, 130),
                    style="logo", tagline="Hörgeräte · Gehörschutz · Hörtests", phone="0641 555 27 70",
                    email="abrechnung@hoerakustik-beispielklang.example", account="5527700")  # fmt: skip
    table, total = _sum_table([("Eigenanteil Hörsystem rechts und links (Mehrkostenvereinbarung)", 1380.00),
                               ("Ladeschale", 0.00), ("Gesetzliche Zuzahlung (2 × 10,00 €)", 20.00)],
                              ("Abrechnung nach Kassenanteil", "EUR"), "Ihr Anteil", vat=None)  # fmt: skip
    cases.append(make(
        l1, "L", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, 30, [("Rechnungsnummer", "HK-11-2026-047")], table, total,
        "Ihre Krankenkasse hat den Festbetrag für Ihre neuen Hörgeräte übernommen. Ihren eigenen Anteil berechnen wir wie "
        "vereinbart:",
        "Den Betrag erbitten wir innerhalb von 30 Tagen nach Rechnungsdatum auf unser Konto; Ratenzahlung ist nach Absprache "
        "möglich.",
        "innerhalb von 30 Tagen nach Rechnungsdatum", "2026-12-21", "Rechnung Hörsysteme", photo=True,
    ))  # fmt: skip

    # L2: Thu 19.11.2026 + 20 = Wed 09.12.2026.
    l2 = "holdout4-invoice_relative-L2"
    d = drawn(l2, PRIVATE_DAYS, date(2026, 11, 19))
    org = O.company("Klavierbau Muster & Söhne", "Saitenweg 2", "37603", "Musterholzminden", monogram="MS", accent=(60, 30, 20),
                    style="band", tagline="Stimmung · Reparatur · Transport", phone="05531 555 63 10",
                    email="buero@klavierbau-muster.example", account="5563100")  # fmt: skip
    table, total = _sum_table([("Klavier stimmen (Grundstimmung, Tonhöhe angehoben)", 145.00),
                               ("Mechanik regulieren, zwei Hämmer ersetzt", 118.00), ("Anfahrt", 28.00)],
                              ("Arbeiten an Ihrem Klavier", "EUR"), "Endbetrag")  # fmt: skip
    cases.append(make(
        l2, "L", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, 20, [("Rechnung Nr.", "KB 26-517"), ("Kunde", "4471")],
        table, total, "für die Arbeiten an Ihrem Klavier am 13.11.2026 berechnen wir:",
        "Wir bitten Sie, die Rechnung binnen 20 Tagen ab Rechnungsdatum zu bezahlen.",
        "binnen 20 Tagen ab Rechnungsdatum zu bezahlen", "2026-12-09", "Rechnung Klavierservice",
    ))  # fmt: skip

    # M1 (photo): Sat 21.11.2026 + 14 = Sat 05.12.2026 → Mon 07.12.2026.
    m1 = "holdout4-invoice_relative-M1"
    d = drawn(m1, PRIVATE_DAYS, date(2026, 11, 21))
    org = O.company("Hundeschule Beispielpfote", "Wiesenrain 8", "35394", "Mustergießen", monogram="HP", accent=(120, 80, 20),
                    style="logo", tagline="Welpenkurse · Alltagstraining · Einzelstunden", phone="0641 555 49 12",
                    email="kurse@hundeschule-beispielpfote.example", account="5549120")  # fmt: skip
    table, total = _sum_table([("Welpenkurs, 8 Termine", 160.00), ("Einzelstunde Leinenführigkeit", 55.00)],
                              ("Kurse für „Bruno“", "EUR"), "Gesamt")  # fmt: skip
    cases.append(make(
        m1, "M", org, S_GEN, "Hallo Herr Musterquell,", d, 14, [("Rechnung", "HP-1121")], table, total,
        "schön, dass Bruno so fleißig mitgemacht hat! Für den Kurs und die Einzelstunde berechnen wir:",
        "Zahlbar 14 Tage nach Rechnungsdatum per Überweisung.", "Zahlbar 14 Tage nach Rechnungsdatum", "2026-12-07",
        "Rechnung Welpenkurs", photo=True, closing=("Sandra Beispielpfote",),
    ))  # fmt: skip

    # M2: Fri 20.11.2026 + 14 = Fri 04.12.2026.
    m2 = "holdout4-invoice_relative-M2"
    d = drawn(m2, PRIVATE_DAYS, date(2026, 11, 20))
    org = O.company("Glaserei Beispielscheibe", "Fensterstraße 15", "48145", "Beispielau", monogram="GB", accent=(0, 100, 140),
                    style="minimal", tagline="Glasreparatur · Spiegel · Duschabtrennungen", phone="0251 555 80 66",
                    email="info@glaserei-beispielscheibe.example", account="5580660")  # fmt: skip
    table, total = _sum_table([("Isolierglasscheibe 112 × 96 cm, geliefert und eingesetzt", 268.00),
                               ("Notverglasung am 10.11.2026", 65.00)], ("Position", "EUR"), "Rechnungssumme")  # fmt: skip
    cases.append(make(
        m2, "M", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, 14, [("Rechnungsnummer", "GS-26-1185")], table, total,
        "für den Austausch der beschädigten Scheibe in Ihrem Wohnzimmerfenster stellen wir in Rechnung:",
        "Der Betrag ist innerhalb von 14 Tagen ab Rechnungsdatum ohne Abzug fällig.",
        "innerhalb von 14 Tagen ab Rechnungsdatum ohne Abzug fällig", "2026-12-04", "Rechnung Glasreparatur",
    ))  # fmt: skip

    # N1 (photo): Wed 18.11.2026 + 21 = Wed 09.12.2026.
    n1 = "holdout4-invoice_relative-N1"
    d = drawn(n1, PRIVATE_DAYS, date(2026, 11, 18))
    org = O.company("Ergotherapie Beispielhand", "Lindenhof 5", "35576", "Beispielwetzlar", monogram="EH", accent=(110, 60, 140),
                    style="logo", tagline="Ergotherapie für Kinder und Erwachsene", phone="06441 555 90 21",
                    email="abrechnung@ergo-beispielhand.example", account="5590210")  # fmt: skip
    table, total = _sum_table([("10 × Ergotherapie, sensomotorisch-perzeptiv à 41,20 €", 412.00),
                               ("Bericht an den behandelnden Kinderarzt", 18.00)],
                              ("Behandlung Ihrer Tochter (Privatrezept vom 01.09.2026)", "EUR"),
                              "Summe (umsatzsteuerfrei nach § 4 Nr. 14 UStG)", vat=None)  # fmt: skip
    cases.append(make(
        n1, "N", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, 21, [("Rechnungs-Nr.", "EH-2026-1102")], table, total,
        "für die Behandlungen Ihrer Tochter von September bis November 2026 berechnen wir als Privatleistung:",
        "Bitte überweisen Sie den Betrag binnen 21 Tagen nach dem Rechnungsdatum.",
        "binnen 21 Tagen nach dem Rechnungsdatum", "2026-12-09", "Privatrechnung Ergotherapie", photo=True,
    ))  # fmt: skip

    # N2: Fri 20.11.2026 + 30 = Sun 20.12.2026 → Mon 21.12.2026.
    n2 = "holdout4-invoice_relative-N2"
    d = drawn(n2, PRIVATE_DAYS, date(2026, 11, 20))
    org = O.company("Dachdeckerei Beispielziegel GmbH", "Firstweg 22", "35781", "Musterweilburg", monogram="DZ", accent=(150, 50, 30),
                    style="band", tagline="Steildach · Flachdach · Dachrinnen", phone="06471 555 14 50",
                    email="rechnung@dach-beispielziegel.example", hr="AG Musterlimburg HRB 5521", account="5514500")  # fmt: skip
    table, total = _sum_table([("Dachrinne erneuert, 14 m, Zink", 612.00), ("Fallrohr mit Laubfang", 148.00),
                               ("Gerüst, Auf- und Abbau", 290.00)], ("Leistung", "EUR"), "Gesamtbetrag")  # fmt: skip
    cases.append(make(
        n2, "N", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, 30, [("Rechnung", "DZ-26-0419"), ("Auftrag", "A-0388")],
        table, total, "die Arbeiten an der Dachentwässerung Ihres Hauses sind abgeschlossen. Wir berechnen:",
        "Zahlungsziel: 30 Tage ab Rechnungsdatum. Bitte geben Sie bei der Überweisung die Rechnungsnummer an.",
        "Zahlungsziel: 30 Tage ab Rechnungsdatum", "2026-12-21", "Schlussrechnung Dachrinne",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 5 — dunning_fixed (pay by an explicit date)
# ==================================================================================================


def dunning_fixed() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, due: date, due_text: str,
             subject: str, refs: list[tuple[str, str]], rows: list[tuple[str, float]], body: str, pay: str,
             signer: tuple[str, ...], *, kind: str = "dunning", photo: bool = False) -> Case:  # fmt: skip
        total = round(sum(v for _, v in rows), 2)
        assert all(law.is_working_day(due, land) for land in law.LAENDER)
        item = check(
            fixed_item(due=due, region=None, kind="payment", nature="payment", title="Rückstand ausgleichen", money=total,
                       rule="Payment date stated in the reminder."),
            due.isoformat(),
        )  # fmt: skip
        table = Table(rows=(*((label, eur_plain(v)) for label, v in rows), ("Summe offen", eur_plain(total))),
                      header=("Offene Posten", "EUR"), bold_rows=(len(rows),), rule_before=(len(rows),))  # fmt: skip
        info, date_line = _layout(variant, org, refs, letter_date, "Schreiben vom")
        letter = Letter(org=org, recipient=person, subject=subject, salutation=salutation, info=info, date_line=date_line,
                        blocks=[P(body), table, P(pay.format(due=due_text)), Sign("Mit freundlichen Grüßen", signer)],
                        style=STYLES[variant], created=created(letter_date))  # fmt: skip
        return _private_case(
            case_id, "dunning_fixed", variant, letter,
            truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[total],
                  items=[tag_plain(item, *PRIVATE_IDS)]),
            [de(letter_date), due_text.replace("**", ""), eur_plain(total)], photo=photo,
        )  # fmt: skip

    # K1 (photo): letter Sat 21.11.2026, pay by Fri 04.12.2026.
    k1 = "holdout4-dunning_fixed-K1"
    d = drawn(k1, PRIVATE_DAYS, date(2026, 11, 21))
    due = date(2026, 12, 4)
    org = O.company("Gartencenter Beispielblüte", "Gewächshausweg 1", "35582", "Musterwettenberg", monogram="GB",
                    accent=(40, 110, 40), style="logo", tagline="Pflanzen · Gartenmöbel · Floristik", phone="0641 555 82 82",
                    email="buchhaltung@beispielbluete.example", account="5582820")  # fmt: skip
    cases.append(make(
        k1, "K", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, due, f"bis zum **{de(due)}**", "Zahlungserinnerung",
        [("Kundenkonto", "GB-30418"), ("Lieferschein", "LS-26-7712")],
        [("Lieferung und Pflanzung von 6 Obstbäumen am 22.10.2026", 534.00), ("Erinnerungspauschale", 3.00)],
        "für die Obstbäume, die wir im Oktober in Ihrem Garten gepflanzt haben, ist bei uns noch keine Zahlung eingegangen. "
        "Sicher haben Sie die Rechnung nur übersehen.",
        "Bitte überweisen Sie die offene Summe {due}. Falls sich Ihre Zahlung mit diesem Schreiben gekreuzt hat, danken wir "
        "Ihnen und bitten Sie, die Erinnerung zu ignorieren.", ("Buchhaltung Gartencenter Beispielblüte",), photo=True,
    ))  # fmt: skip

    # K2: letter Wed 18.11.2026, pay by Wed 02.12.2026.
    k2 = "holdout4-dunning_fixed-K2"
    d = drawn(k2, PRIVATE_DAYS, date(2026, 11, 18))
    due = date(2026, 12, 2)
    org = O.company("Inkassobüro Beispielrecht GmbH", "Paragraphenring 3", "48151", "Mustermünster", monogram="IB",
                    accent=(50, 50, 70), style="minimal", tagline="Forderungsmanagement für den Mittelstand",
                    phone="0251 555 66 40", email="fall@inkasso-beispielrecht.example", hr="AG Mustermünster HRB 18 033",
                    account="5566400")  # fmt: skip
    cases.append(make(
        k2, "K", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, due, f"spätestens am **{de_weekday(due)}**",
        "Forderung der Beispielnetz Kabel GmbH – Zahlungsaufforderung", [("Aktenzeichen", "IB-26-552019"), ("Kundennummer Gläubiger", "KD 7 118 205")],
        [("Hauptforderung: Rechnungen August und September 2026", 79.98), ("Mahngebühr der Gläubigerin", 2.50),
         ("Inkassovergütung (nach RVG begrenzt)", 49.00)],
        "die Beispielnetz Kabel GmbH hat uns beauftragt, ihre Forderung gegen Sie einzuziehen. Nach den uns vorliegenden "
        "Unterlagen sind die Entgelte für Ihren Internetanschluss für August und September 2026 offen; Sie wurden am "
        "12.10.2026 gemahnt.",
        "Zahlen Sie den Gesamtbetrag {due} auf unser Treuhandkonto. Wenn Sie die Forderung bestreiten, teilen Sie uns das "
        "bitte mit Begründung mit; wir klären den Sachverhalt dann mit unserer Auftraggeberin.",
        ("Inkassobüro Beispielrecht GmbH", "Sachbearbeitung Team 3"),
    ))  # fmt: skip

    # L1: letter Fri 20.11.2026, pay by Mon 07.12.2026.
    l1 = "holdout4-dunning_fixed-L1"
    d = drawn(l1, PRIVATE_DAYS, date(2026, 11, 20))
    due = date(2026, 12, 7)
    org = O.company("Hausverwaltung Beispieldach & Partner", "Treppenweg 9", "35392", "Mustergießen", monogram="HB",
                    accent=(100, 70, 40), style="band", tagline="Miet- und WEG-Verwaltung", phone="0641 555 93 30",
                    email="mieten@hv-beispieldach.example", account="5593300")  # fmt: skip
    cases.append(make(
        l1, "L", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, due, f"bis **{de_long(due)}**",
        "Mietrückstand Wohnung Quellenweg 7, 1. OG links", [("Mietkonto", "MK-0711-03")],
        [("Miete November 2026 (Restbetrag)", 340.00), ("Betriebskostennachzahlung 2025", 186.42)],
        "auf Ihrem Mietkonto ist für November nur ein Teil der Miete eingegangen. Außerdem ist die Nachzahlung aus der "
        "Betriebskostenabrechnung 2025, die Ihnen im September zugegangen ist, noch nicht beglichen.",
        "Wir bitten Sie, den Rückstand {due} zu überweisen. Wenn Sie vorübergehend in Schwierigkeiten sind, sprechen Sie uns "
        "an; eine Ratenvereinbarung ist möglich.", ("Hausverwaltung Beispieldach & Partner", "Mietenbuchhaltung"),
        kind="rent_lease",
    ))  # fmt: skip

    # M1 (photo): letter Thu 19.11.2026, pay by Thu 03.12.2026.
    m1 = "holdout4-dunning_fixed-M1"
    d = drawn(m1, PRIVATE_DAYS, date(2026, 11, 19))
    due = date(2026, 12, 3)
    org = O.company("Sportverein Beispielau 1911 e.V.", "Am Sportpark 1", "48145", "Beispielau", monogram="SV",
                    accent=(0, 90, 50), style="logo", tagline="Fußball · Turnen · Leichtathletik", phone="0251 555 19 11",
                    email="kasse@sv-beispielau.example", account="5519110")  # fmt: skip
    cases.append(make(
        m1, "M", org, S_GEN2, "Liebe Frau Beispielacker,", d, due, f"bis zum **{de(due)}**", "Mitgliedsbeitrag 2026 – Erinnerung",
        [("Mitgliedsnummer", "SV-2207")], [("Jahresbeitrag Familie 2026", 168.00), ("Rücklastschriftgebühr", 4.50)],
        "der Einzug des Familienbeitrags für 2026 ist leider gescheitert, weil die Lastschrift von Ihrer Bank zurückgegeben "
        "wurde.",
        "Bitte überweisen Sie den Betrag {due} auf das Vereinskonto. Hat sich Ihre Bankverbindung geändert, schicken Sie uns "
        "einfach ein neues SEPA-Mandat.", ("Vereinskasse",), photo=True,
    ))  # fmt: skip

    # M2: letter Thu 19.11.2026, pay by Thu 10.12.2026.
    m2 = "holdout4-dunning_fixed-M2"
    d = drawn(m2, PRIVATE_DAYS, date(2026, 11, 19))
    due = date(2026, 12, 10)
    org = O.company("Stadtwerke Beispielsoest GmbH", "Energieweg 3", "59494", "Beispielsoest", monogram="SB",
                    accent=(0, 80, 150), style="band", tagline="Strom · Gas · Wasser", phone="02921 555 40 40",
                    email="forderungen@stadtwerke-beispielsoest.example", hr="AG Beispielsoest HRB 2210",
                    account="5540400")  # fmt: skip
    cases.append(make(
        m2, "M", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, due, f"bis spätestens **{de(due)}**",
        "Mahnung – Abschläge Strom und Wasser", [("Vertragskonto", "4007 3318 52")],
        [("Abschlag Oktober 2026", 112.00), ("Abschlag November 2026", 112.00), ("Mahnkosten", 2.00)],
        "die Abschläge für Oktober und November 2026 sind trotz Fälligkeit nicht bei uns eingegangen.",
        "Wir fordern Sie auf, den offenen Betrag {due} zu zahlen. Andernfalls behalten wir uns vor, die Versorgung nach "
        "vorheriger Ankündigung zu unterbrechen.", ("Stadtwerke Beispielsoest GmbH", "Forderungsmanagement"),
        kind="utility_bill",
    ))  # fmt: skip

    # N1: letter Fri 20.11.2026, pay by Fri 11.12.2026.
    n1 = "holdout4-dunning_fixed-N1"
    d = drawn(n1, PRIVATE_DAYS, date(2026, 11, 20))
    due = date(2026, 12, 11)
    org = O.company("Möbelhaus Beispielwohnen KG", "Sofaallee 50", "35398", "Mustergießen", monogram="MW", accent=(140, 30, 60),
                    style="minimal", tagline="Wohnen · Küchen · Schlafen", phone="0641 555 77 00",
                    email="finanzbuchhaltung@beispielwohnen.example", account="5577000")  # fmt: skip
    cases.append(make(
        n1, "N", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, due, f"bis **{de_weekday(due)}**", "2. Mahnung",
        [("Auftrag", "BW-26-30871"), ("Kundennummer", "K-881 204")],
        [("Restzahlung Esstisch und sechs Stühle (Lieferung 15.10.2026)", 690.00), ("Mahngebühren", 5.00)],
        "trotz unserer Erinnerung vom 04.11.2026 ist die Restzahlung für Ihre Esszimmermöbel weiterhin offen.",
        "Wir bitten Sie dringend, den Gesamtbetrag {due} zu begleichen. Geht bis dahin keine Zahlung ein, übergeben wir die "
        "Forderung einem Inkassounternehmen; die Kosten dafür gehen zu Ihren Lasten.",
        ("Möbelhaus Beispielwohnen KG", "Debitorenbuchhaltung"),
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 6 — appointment
# ==================================================================================================


def appointment() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, when: date, time: str,
             subject: str, refs: list[tuple[str, str]], body: list[Block], key: list[str], *, kind: str = "appointment",
             photo: bool = False, notes: str = "", closing: tuple[str, ...] = ()) -> Case:  # fmt: skip
        item = check(
            fixed_item(due=when, region=org.region, kind="appointment", nature="appointment", title=subject, time=time,
                       rule="Appointment set by the sender; appointments are never shifted.", appointment=True),
            when.isoformat(),
        )  # fmt: skip
        info, date_line = _layout(variant, org, refs, letter_date, "Datum")
        letter = Letter(org=org, recipient=person, subject=subject, salutation=salutation, info=info, date_line=date_line,
                        blocks=[*body, Sign("Mit freundlichen Grüßen", closing or (org.name,))], style=STYLES[variant],
                        created=created(letter_date))  # fmt: skip
        return _private_case(
            case_id, "appointment", variant, letter,
            truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[],
                  items=[with_conventions(item, ["c01"])]),
            [de(letter_date), *key], region=org.region, photo=photo, notes=notes,
        )  # fmt: skip

    # K1 (photo): letter Fri 20.11.2026, appointment Tue 08.12.2026, 09:40.
    k1 = "holdout4-appointment-K1"
    d = drawn(k1, PRIVATE_DAYS, date(2026, 11, 20))
    when = date(2026, 12, 8)
    org = O.company("Augenzentrum Beispielblick", "Sehweg 3", "35390", "Mustergießen", monogram="AB", accent=(0, 100, 120),
                    style="logo", tagline="Augenheilkunde · Netzhautsprechstunde · Laser", phone="0641 555 61 61",
                    email="termine@augenzentrum-beispielblick.example", account="5561610")  # fmt: skip
    cases.append(make(
        k1, "K", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, when, "09:40", "Ihr Termin in der Netzhautsprechstunde",
        [("Patientennummer", "AB-218804")],
        [P(f"auf Überweisung Ihrer Augenärztin haben wir für Sie einen Termin vereinbart: **{de_weekday(when)}, 09:40 Uhr**, "
           "Anmeldung im 2. Obergeschoss."),
         P("Für die Untersuchung werden Ihre Pupillen erweitert. Danach dürfen Sie für einige Stunden nicht selbst Auto "
           "fahren; kommen Sie bitte mit Begleitung oder öffentlichen Verkehrsmitteln. Bringen Sie Ihre Brille und eine "
           "Liste Ihrer Medikamente mit.")],
        [de_weekday(when), "09:40 Uhr"], photo=True, closing=("Ihr Team im Augenzentrum Beispielblick",),
    ))  # fmt: skip

    # K2: Amtsgericht in ST; letter Fri 20.11.2026, hearing Wed 13.01.2027, 09:00.
    k2 = "holdout4-appointment-K2"
    d = drawn(k2, PRIVATE_DAYS, date(2026, 11, 20))
    when = date(2027, 1, 13)
    court = authority("Amtsgericht Musterquedlin", "Gerichtsgasse 2", "06484", "Musterquedlin", "ST",
                      ("Land Sachsen-Anhalt", "Zivilabteilung"), phone="03946 555 20-0",
                      email="poststelle@ag-musterquedlin.justiz.sachsen-anhalt.example", blz="81000000", account="2000100",
                      style="authority", accent=(120, 25, 35))  # fmt: skip
    cases.append(make(
        k2, "K", court, S_ST, "Sehr geehrter Herr Beispielharz,", d, when, "09:00", "Ladung zum Termin als Zeuge",
        [("Aktenzeichen", "2 C 318/26")],
        [P("in dem Rechtsstreit Beispielharz Dachbau GmbH gegen Marion Kessler wegen Werklohn sollen Sie als Zeuge vernommen "
           "werden. Das Gericht lädt Sie deshalb zu folgendem Termin:"),
         Box((f"{de_weekday(when)}, 09:00 Uhr", "Amtsgericht Musterquedlin, Gerichtsgasse 2, Saal 104",
              "Beweisthema: Ausführung der Dacharbeiten am Haus Bodetal 6 im Mai 2026")),
         P("Bringen Sie bitte diese Ladung und einen amtlichen Ausweis mit. Bleiben Sie ohne ausreichende Entschuldigung fern, "
           "können Ihnen die verursachten Kosten und ein Ordnungsgeld auferlegt werden (§ 380 ZPO). Eine Entschädigung für "
           "Fahrtkosten und Verdienstausfall richtet sich nach dem JVEG.")],
        [f"{de_weekday(when)}, 09:00 Uhr"], closing=("Bode, Justizobersekretärin", "als Urkundsbeamtin der Geschäftsstelle"),
    ))  # fmt: skip

    # L1: letter Wed 18.11.2026, delivery Sat 12.12.2026, 08:00 (a Saturday appointment, not moved).
    l1 = "holdout4-appointment-L1"
    d = drawn(l1, PRIVATE_DAYS, date(2026, 11, 18))
    when = date(2026, 12, 12)
    org = O.company("Beispielwohnen Lieferservice", "Sofaallee 50", "35398", "Mustergießen", monogram="BL", accent=(140, 30, 60),
                    style="band", tagline="Auslieferung und Montage", phone="0641 555 77 50",
                    email="lieferung@beispielwohnen.example", account="5577500")  # fmt: skip
    cases.append(make(
        l1, "L", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, when, "08:00", "Liefertermin für Ihren Kleiderschrank",
        [("Auftrag", "BW-26-31502")],
        [P(f"Ihr Kleiderschrank „Nordsee“ ist eingetroffen. Wir liefern und montieren ihn am **Samstag, {de(when)}**; unser "
           "Team ist **ab 08:00 Uhr** bei Ihnen und braucht etwa drei Stunden."),
         P("Bitte sorgen Sie dafür, dass der Aufstellort frei ist und wir in der Nähe des Hauses halten können. Passt Ihnen "
           "der Tag nicht, rufen Sie uns spätestens drei Werktage vorher an.")],
        [de(when), "ab 08:00 Uhr"], notes="Saturday appointment: it is kept on the Saturday.",
    ))  # fmt: skip

    # M1 (photo): letter Thu 19.11.2026, appointment Mon 14.12.2026, 16:15.
    m1 = "holdout4-appointment-M1"
    d = drawn(m1, PRIVATE_DAYS, date(2026, 11, 19))
    when = date(2026, 12, 14)
    org = O.company("Zahnarztpraxis Beispielweiß", "Am Lahnufer 9", "35576", "Beispielwetzlar", monogram="ZB", accent=(0, 120, 140),
                    style="minimal", tagline="Prophylaxe · Kinderzahnheilkunde", phone="06441 555 34 34",
                    email="praxis@zahnarzt-beispielweiss.example", account="5534340")  # fmt: skip
    cases.append(make(
        m1, "M", org, S_GEN, "Lieber Herr Musterquell,", d, when, "16:15", "Erinnerung an Ihre Zahnreinigung",
        [("Patient", "Bastian Musterquell")],
        [P(f"Ihr nächster Termin zur professionellen Zahnreinigung ist am **{de_weekday(when)} um 16:15 Uhr**. Er dauert "
           "etwa eine Stunde."),
         P("Wenn Sie verhindert sind, sagen Sie bitte mindestens zwei Werktage vorher ab, damit wir den Termin anderweitig "
           "vergeben können.")],
        [de_weekday(when), "16:15 Uhr"], photo=True, closing=("Ihr Praxisteam",),
    ))  # fmt: skip

    # M2: Amtsgericht in ST; letter drawn among the authority days: Thu 19.11.2026; hearing Thu 21.01.2027, 13:30.
    m2 = "holdout4-appointment-M2"
    d = drawn(m2, AUTHORITY_DAYS, date(2026, 11, 19))
    when = date(2027, 1, 21)
    court2 = authority("Amtsgericht Musterwernigerode", "Rathausplatz 6", "38855", "Musterwernigerode", "ST",
                       ("Land Sachsen-Anhalt", "Betreuungsgericht"), phone="03943 555 41-0",
                       email="poststelle@ag-musterwernigerode.justiz.sachsen-anhalt.example", blz="81000000",
                       account="4100200", style="authority", accent=(120, 25, 35))  # fmt: skip
    cases.append(make(
        m2, "M", court2, S_ST, "Sehr geehrter Herr Beispielharz,", d, when, "13:30",
        "Anhörung im Betreuungsverfahren für Frau Gertrud Beispielharz", [("Geschäftszeichen", "6 XVII 412/26")],
        [P("in dem Verfahren über die Bestellung eines Betreuers für Ihre Mutter möchte die Richterin Sie als Sohn anhören. "
           f"Der Termin findet am **{de_weekday(when)}, 13:30 Uhr**, im Pflegeheim „Am Brockenblick“, Zimmer 12, statt."),
         P("Sie werden als Beteiligter angehört; Ihr Erscheinen ist erwünscht, aber nicht erzwingbar. Wenn Sie verhindert "
           "sind, können Sie Ihre Sicht auch schriftlich mitteilen.")],
        [de_weekday(when), "13:30 Uhr"], closing=("Auf Anordnung", "Harnisch, Justizbeschäftigte"),
    ))  # fmt: skip

    # N1: letter Sat 21.11.2026, appointment Thu 07.01.2027, 07:30.
    n1 = "holdout4-appointment-N1"
    d = drawn(n1, PRIVATE_DAYS, date(2026, 11, 21))
    when = date(2027, 1, 7)
    org = O.company("Fahrschule Beispielspur", "Kreiselweg 4", "35394", "Mustergießen", monogram="FS", accent=(150, 85, 0),
                    style="logo", tagline="Klassen B, BE, A2 · Auffrischungsstunden", phone="0641 555 18 18",
                    email="buero@fahrschule-beispielspur.example", account="5518180")  # fmt: skip
    cases.append(make(
        n1, "N", org, S_GEN2, "Hallo Frau Beispielacker,", d, when, "07:30", "Ihr Termin für die praktische Prüfung",
        [("Schülernummer", "FS-6170")],
        [P(f"Ihre praktische Fahrprüfung Klasse B ist am **{de_weekday(when)}**. Treffpunkt ist um **07:30 Uhr** an der "
           "Prüfstelle in der Industriestraße 30; Ihr Fahrlehrer holt Sie dort ab."),
         P("Denken Sie an Ihren Personalausweis. Die Prüfungsgebühr der Prüfstelle haben Sie bereits mit der Anmeldung "
           "bezahlt.")],
        [de_weekday(when), "07:30 Uhr"],
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 8 — contract_confirmation (secondary metric: current term end and cancel-by)
# ==================================================================================================


def _tag_contract(contract: dict[str, Any], regime: str) -> dict[str, Any]:
    """c22 (disputed): a cancel-by day on a Saturday, Sunday or holiday stays; the other reading moves it (§ 193 BGB)."""
    cancel_by = date.fromisoformat(contract["expected_cancel_by"])
    moved = law.shift_to_working_day(cancel_by, None, law.Derivation(), "§ 193 BGB")
    ids = ["c01", *(["c21"] if regime in ("tkg56", "bgb309_new") else []), "c22"]
    return with_conventions(contract, ids, {"expected_cancel_by": [moved] if moved != cancel_by else []})


def contract_confirmation() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, subject: str,
             refs: list[tuple[str, str]], blocks: list[Block], contract: dict[str, Any], key: list[str], regime: str,
             kind: str = "contract") -> Case:  # fmt: skip
        info, date_line = _layout(variant, org, refs, letter_date, "Bestätigt am")
        letter = Letter(org=org, recipient=person, subject=subject, salutation=salutation, info=info, date_line=date_line,
                        blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant],
                        created=created(letter_date))  # fmt: skip
        return _private_case(
            case_id, "contract_confirmation", variant, letter,
            truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[contract["price"]], items=[],
                  contract=_tag_contract(contract, regime)),
            [de(letter_date), *key],
        )  # fmt: skip

    # K1 — fibre broadband, § 56 TKG: 12 months from Thu 03.12.2026 → Thu 02.12.2027; one month → Tue 02.11.2027.
    k1 = "holdout4-contract_confirmation-K1"
    concluded = drawn(k1, PRIVATE_DAYS, date(2026, 11, 20))
    start = date(2026, 12, 3)
    org = O.company("Glasfaser Beispielland GmbH", "Lichtleiterweg 1", "35394", "Mustergießen", monogram="GL", accent=(0, 90, 160),
                    style="band", tagline="Internet · Telefon · TV über Glasfaser", phone="0800 555 64 64",
                    email="vertrag@glasfaser-beispielland.example", hr="AG Mustergießen HRB 9 914", account="5564640")  # fmt: skip
    contract = _contract_truth(category="internet", regime="tkg56", party_kind="telecom", concluded=concluded, start=start,
                               initial=12, renewal="indefinite, cancellable any time with 1 month notice", notice=1,
                               notice_unit="months", today=TODAY, price=39.90, interval="monthly",
                               citations="Telecom contract with a consumer: § 56 Abs. 1, 3 TKG (initial term at most 24 months, "
                                         "then one month's notice).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2027-12-02",
        "2027-11-02",
    )
    cases.append(make(
        k1, "K", org, S_GEN, "Sehr geehrter Herr Musterquell,", concluded, "Auftragsbestätigung Ihres Glasfaseranschlusses",
        [("Kundennummer", "GL-5 501 873")],
        [P(f"wir bestätigen Ihren Auftrag. Ihr Anschluss im Quellenweg 7 wird am {de(start)} freigeschaltet; ab diesem Tag "
           "läuft Ihr Vertrag."),
         Table(rows=(("Tarif", "Beispielland Faser 500"), ("Bereitstellung", de(start)), ("Mindestlaufzeit", "12 Monate ab Bereitstellung"),
                     ("Kündigungsfrist", "1 Monat zum Ende der Mindestlaufzeit"), ("Nach Ablauf", "monatlich kündbar mit 1 Monat Frist"),
                     ("Monatspreis", "39,90 €")), header=("Ihr Vertrag auf einen Blick", ""), value_width=96, value_align="L"),
         P("Sie können den Vertrag in Textform oder über die Kündigungsschaltfläche auf unserer Website kündigen.")],
        contract, ["12 Monate ab Bereitstellung", "39,90 €"], "tkg56",
    ))  # fmt: skip

    # L1 — gym, § 309 Nr. 9 BGB: 12 months from Fri 01.01.2027 → Fri 31.12.2027; one month → Tue 30.11.2027.
    l1 = "holdout4-contract_confirmation-L1"
    concluded = drawn(l1, PRIVATE_DAYS, date(2026, 11, 19))
    start = date(2027, 1, 1)
    org = O.company("Fitnesswerk Beispielstark", "Hantelstraße 8", "35390", "Mustergießen", monogram="FB", accent=(160, 30, 30),
                    style="logo", tagline="Training · Kurse · Sauna", phone="0641 555 24 24",
                    email="mitglieder@fitnesswerk-beispielstark.example", account="5524240")  # fmt: skip
    contract = _contract_truth(category="gym", regime="bgb309_new", party_kind="company", concluded=concluded, start=start,
                               initial=12, renewal="indefinite, cancellable any time with 1 month notice", notice=1,
                               notice_unit="months", today=TODAY, price=34.00, interval="monthly",
                               citations="Consumer contract concluded after 2022-03-01: § 309 Nr. 9 BGB (n.F.).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2027-12-31",
        "2027-11-30",
    )
    cases.append(make(
        l1, "L", org, S_GEN2, "Hallo Frau Beispielacker,", concluded, "Willkommen im Fitnesswerk – Ihre Mitgliedschaft",
        [("Mitgliedsnummer", "FW-20871")],
        [P(f"schön, dass Sie dabei sind! Ihre Mitgliedschaft beginnt am {de(start)}; bis dahin dürfen Sie schon kostenlos "
           "trainieren."),
         Table(rows=(("Beginn", de(start)), ("Erstlaufzeit", "12 Monate"), ("Kündigung", "1 Monat vor Ende der Erstlaufzeit"),
                     ("Danach", "unbefristet, monatlich kündbar"), ("Beitrag", "34,00 € monatlich")),
               header=("Mitgliedschaft", ""), value_width=96, value_align="L")],
        contract, ["1 Monat vor Ende der Erstlaufzeit", "34,00 €"], "bgb309_new",
    ))  # fmt: skip

    # M1 — household contents insurance, § 11 VVG: 1 year from Fri 15.01.2027 → Fri 14.01.2028; three months → Thu 14.10.2027.
    m1 = "holdout4-contract_confirmation-M1"
    concluded = drawn(m1, PRIVATE_DAYS, date(2026, 11, 18))
    start = date(2027, 1, 15)
    org = O.company("Beispielschutz Versicherung AG", "Policenplatz 1", "65185", "Musterwiesbaden", monogram="BS", accent=(0, 60, 120),
                    style="minimal", tagline="Hausrat · Wohngebäude · Haftpflicht", phone="0611 555 10 10",
                    email="vertrag@beispielschutz.example", hr="AG Musterwiesbaden HRB 31 220", account="5510100")  # fmt: skip
    contract = _contract_truth(category="insurance", regime="vvg11", party_kind="insurer", concluded=concluded, start=start,
                               initial=12, renewal="renews by 1 year unless cancelled 3 months before the end of the insurance year",
                               notice=3, notice_unit="months", today=TODAY, price=96.60, interval="yearly",
                               citations="Insurance contract: § 11 VVG (yearly renewal, notice as written, max. 3 months).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2028-01-14",
        "2027-10-14",
    )
    cases.append(make(
        m1, "M", org, S_GEN, "Sehr geehrter Herr Musterquell,", concluded, "Versicherungsschein Hausratversicherung „Plus“",
        [("Versicherungsschein-Nr.", "HR-27-0044186")],
        [P("wir haben Ihren Antrag angenommen und versichern Ihren Hausrat in der Wohnung Quellenweg 7:"),
         Table(rows=(("Beginn", f"{de(start)}, 0 Uhr"), ("Dauer", "1 Jahr, Verlängerung jeweils um 1 Jahr"),
                     ("Versicherungssumme", "65.000 €"), ("Jahresbeitrag", "96,60 €")),
               header=("Vertragsdaten", ""), value_width=96, value_align="L"),
         P("Beide Seiten können den Vertrag zum Ablauf eines Versicherungsjahres kündigen; die Kündigung muss der anderen "
           "Seite spätestens drei Monate vorher in Textform zugehen.")],
        contract, ["spätestens drei Monate vorher in Textform", "96,60 €"], "vvg11", kind="insurance",
    ))  # fmt: skip

    # N1 — newspaper subscription, § 309 Nr. 9 BGB: 12 months from Tue 01.12.2026 → Tue 30.11.2027; one month → Sun 31.10.2027
    # (31.10. + one month = 30.11.; a notice day stays on the Sunday, c22; moved, it would be Mon 01.11.2027).
    n1 = "holdout4-contract_confirmation-N1"
    concluded = drawn(n1, PRIVATE_DAYS, date(2026, 11, 19))
    start = date(2026, 12, 1)
    org = O.company("Beispiellahn Zeitungsverlag GmbH", "Pressehaus 2", "35576", "Beispielwetzlar", monogram="BZ", accent=(30, 30, 30),
                    style="band", tagline="Abo-Service", phone="06441 555 45 45", email="abo@beispiellahn-zeitung.example",
                    hr="AG Beispielwetzlar HRB 1 207", account="5545450")  # fmt: skip
    contract = _contract_truth(category="other", regime="bgb309_new", party_kind="company", concluded=concluded, start=start,
                               initial=12, renewal="indefinite, cancellable any time with 1 month notice", notice=1,
                               notice_unit="months", today=TODAY, price=42.50, interval="monthly",
                               citations="Consumer subscription concluded after 2022-03-01: § 309 Nr. 9 BGB (n.F.).")  # fmt: skip
    assert (contract["expected_current_term_end"], contract["expected_cancel_by"]) == (
        "2027-11-30",
        "2027-10-31",
    )
    cases.append(make(
        n1, "N", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", concluded, "Ihr Abonnement der Beispiellahn-Zeitung",
        [("Abonummer", "A-704 118")],
        [P(f"vielen Dank für Ihre Bestellung. Ab dem {de(start)} erhalten Sie die Zeitung täglich außer sonntags; das E-Paper "
           "ist inklusive."),
         P("Das Abonnement läuft zunächst zwölf Monate und kann mit einer Frist von einem Monat zum Ende dieser Laufzeit "
           "gekündigt werden. Danach ist es jederzeit mit einem Monat Frist kündbar. Der Bezugspreis beträgt 42,50 € im Monat.")],
        contract, ["mit einer Frist von einem Monat zum Ende dieser Laufzeit", "42,50 €"], "bgb309_new",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 9 — price_increase (special-cancellation window; items optional, headline unaffected)
# ==================================================================================================


def price_increase() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, effective: date,
             regime: str, old: float, new: float, subject: str, refs: list[tuple[str, str]], blocks: list[Block], key: list[str],
             category: str, earliest: str | None = None) -> Case:  # fmt: skip
        cancel_by = effective - timedelta(days=1)
        three = law.add_months(letter_date, 3)
        why = f"Effective {fmt(effective)}. " + (
            "§ 41 Abs. 5 EnWG: the customer may cancel without notice with effect from the change; the cancellation must reach the "
            f"supplier before the new price applies, i.e. by {fmt(cancel_by)}. No § 193 shift."
            if regime == "enwg41_5"
            else "§ 57 Abs. 1 TKG: special cancellation within three months of receipt of the notice; to avoid ever paying the new "
            f"price it must be received before the change takes effect, i.e. by {fmt(cancel_by)}. From the letter date the "
            f"three-month window would end on {three.isoformat()} at the earliest."
        )  # fmt: skip
        if regime == "enwg41_5":
            optional = [undated_item(kind="deadline", nature="notice", title="Sonderkündigung vor Inkrafttreten der Preisänderung",
                                     spec=spec("fixed", anchor="explicit_date", date_=cancel_by, shift=False), derivation=why,
                                     expected_due=cancel_by.isoformat())]  # fmt: skip
        else:
            # § 57 Abs. 1 S. 2 TKG: three months from the day the notice reaches the customer. A private sender's letter has
            # no deemed delivery (§ 130 Abs. 1 BGB) and the letter states no day of receipt; the reading day is none (c13).
            # The eve of the change ends no period: a later cancellation within the three months still ends the contract,
            # at the earliest when the change takes effect (§ 57 Abs. 1 S. 3 TKG). So no date follows (c11).
            assert earliest is not None and three.isoformat() == earliest, (case_id, three, earliest)
            optional = [undated_item(
                kind="deadline", nature="notice", title="Sonderkündigung wegen der Preisänderung",
                spec=spec("relative", anchor="receipt", amount=3, unit="months", shift=True),
                derivation=f"Effective {fmt(effective)}. § 57 Abs. 1 S. 2 TKG: the special cancellation may be declared within "
                "three months of the day the notice reaches the customer. The letter names no day of receipt, and a private "
                "company's letter carries no deemed-delivery rule (§ 130 Abs. 1 BGB); the reading day is not a receipt day. "
                f"The day before the change ({fmt(cancel_by)}) only avoids the new price: a cancellation declared later within "
                "the three months is still valid and ends the contract no earlier than the change (§ 57 Abs. 1 S. 3 TKG). Had "
                f"the notice arrived on its own date, the window would end on {fmt(three)} at the earliest. No date can be "
                "computed.",
            )]  # fmt: skip
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
                "window_end_if_received_on_letter_date": None if regime == "enwg41_5" else three.isoformat(),
                "derivation": why,
            },
        }
        info, date_line = _layout(variant, org, refs, letter_date, "Mitteilung vom")
        letter = Letter(org=org, recipient=person, subject=subject, salutation=salutation, info=info, date_line=date_line,
                        blocks=[*blocks, Sign("Mit freundlichen Grüßen", (org.name,))], style=STYLES[variant],
                        created=created(letter_date))  # fmt: skip
        return _private_case(
            case_id, "price_increase", variant, letter,
            truth(kind="price_increase", sender=org.name, document_date=letter_date, references=refs, amounts=[old, new], items=[],
                  optional_items=optional, price_change=change),
            [de(letter_date), de(effective), *key],
        )  # fmt: skip

    # K1 — electricity, § 41 Abs. 5 EnWG, effective Fri 01.01.2027.
    k1 = "holdout4-price_increase-K1"
    d = drawn(k1, PRIVATE_DAYS, date(2026, 11, 19))
    eff = date(2027, 1, 1)
    org = O.company("Beispielstrom Mittelhessen GmbH", "Umspannwerk 2", "35390", "Mustergießen", monogram="BM", accent=(0, 110, 60),
                    style="logo", tagline="Strom aus der Region", phone="0800 555 33 44", email="service@beispielstrom.example",
                    account="5533440")  # fmt: skip
    cases.append(make(
        k1, "K", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, eff, "enwg41_5", 86.00, 92.00,
        f"Anpassung Ihrer Strompreise zum {de(eff)}", [("Vertragsnummer", "BM-31 774 208")],
        [P(f"zum {de(eff)} passen wir die Preise in Ihrem Tarif „Region Basis“ an. Grund sind höhere Kosten für die Nutzung "
           "des Stromnetzes und für die Beschaffung."),
         Table(rows=(("Arbeitspreis", "32,10 ct/kWh → 34,45 ct/kWh"), ("Grundpreis", "13,20 € → 14,10 € im Monat"),
                     ("Monatlicher Abschlag", "86,00 € → 92,00 €")), header=("Preisbestandteil", "alt → neu"), value_width=62),
         P(f"Sind Sie mit der Änderung nicht einverstanden, dürfen Sie den Vertrag fristlos zum {de(eff)} kündigen. Ihre "
           "Kündigung muss uns vor diesem Tag in Textform erreichen; Kosten entstehen Ihnen dadurch nicht.")],
        ["fristlos zum"], "energy",
    ))  # fmt: skip

    # L1 — mobile, § 57 Abs. 1 TKG, effective Fri 01.01.2027.
    l1 = "holdout4-price_increase-L1"
    d = drawn(l1, PRIVATE_DAYS, date(2026, 11, 21))
    eff = date(2027, 1, 1)
    org = O.company("Beispielfunk Mobile GmbH", "Antennenweg 6", "35394", "Mustergießen", monogram="BF", accent=(150, 0, 90),
                    style="band", tagline="Mobilfunk ohne Schnickschnack", phone="0800 555 70 70",
                    email="kundenservice@beispielfunk.example", account="5570700")  # fmt: skip
    cases.append(make(
        l1, "L", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, eff, "tkg57", 14.99, 16.99,
        "Neuer Preis für Ihren Tarif „Beispielfunk Allnet 15“", [("Kundennummer", "BF-7 220 418"), ("Rufnummer", "0160 555 41 27")],
        [P(f"ab dem {de(eff)} kostet Ihr Tarif monatlich **16,99 €** statt bisher 14,99 €. Alle Leistungen bleiben gleich."),
         P("Weil die Änderung für Sie ungünstig ist, können Sie den Vertrag ohne Frist und ohne Kosten kündigen. Für diese "
           "Kündigung haben Sie drei Monate Zeit, gerechnet ab dem Zugang dieser Mitteilung; wirksam wird sie frühestens an "
           "dem Tag, an dem der neue Preis gilt.")],
        ["Für diese Kündigung haben Sie drei Monate Zeit"], "mobile", "2027-02-21",
    ))  # fmt: skip

    # M1 — gas, § 41 Abs. 5 EnWG, effective Fri 01.01.2027.
    m1 = "holdout4-price_increase-M1"
    d = drawn(m1, PRIVATE_DAYS, date(2026, 11, 20))
    eff = date(2027, 1, 1)
    org = O.company("Erdgas Beispieltal GmbH", "Leitungsweg 12", "48143", "Mustermünster", monogram="EB", accent=(0, 70, 140),
                    style="minimal", tagline="Erdgas für Haushalte und Gewerbe", phone="0800 555 81 81",
                    email="kunden@erdgas-beispieltal.example", account="5581810")  # fmt: skip
    cases.append(make(
        m1, "M", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, eff, "enwg41_5", 104.00, 118.00,
        f"Ihre Gaspreise ab {de(eff)}", [("Kundennummer", "EB-552 0814"), ("Zählpunkt", "DE000555 0018 77 41")],
        [P(f"wir müssen die Preise für Ihre Erdgasbelieferung zum {de(eff)} erhöhen. Der Arbeitspreis steigt von 9,84 ct/kWh "
           "auf 11,12 ct/kWh; Ihr monatlicher Abschlag steigt von 104,00 € auf **118,00 €**."),
         P(f"Sie haben das Recht, den Vertrag ohne Einhaltung einer Frist zum {de(eff)} zu kündigen. Damit die Kündigung "
           "wirkt, muss sie bei uns vor dem Inkrafttreten der neuen Preise eingehen.")],
        ["ohne Einhaltung einer Frist zum"], "energy",
    ))  # fmt: skip

    # N1 — broadband, § 57 Abs. 1 TKG, effective Mon 01.02.2027.
    n1 = "holdout4-price_increase-N1"
    d = drawn(n1, PRIVATE_DAYS, date(2026, 11, 18))
    eff = date(2027, 2, 1)
    org = O.company("Kabelnetz Beispielstadt GmbH", "Verteilerstraße 3", "48151", "Mustermünster", monogram="KB", accent=(0, 100, 150),
                    style="logo", tagline="Internet · TV · Telefon", phone="0800 555 12 21", email="service@kabelnetz-beispielstadt.example",
                    account="5512210")  # fmt: skip
    cases.append(make(
        n1, "N", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, eff, "tkg57", 34.99, 37.99,
        "Preisänderung für Ihren Internetanschluss", [("Kundennummer", "KB-1 093 377")],
        [P(f"zum {de(eff)} erhöhen wir den Preis Ihres Tarifs „Kabel 250“ um 3,00 € auf **37,99 €** im Monat (bisher 34,99 €)."),
         P("Diese Änderung ist für Sie nicht ausschließlich vorteilhaft. Sie dürfen den Vertrag deshalb innerhalb von drei "
           "Monaten nach Erhalt dieses Schreibens kostenlos und ohne Kündigungsfrist beenden, frühestens zum Wirksamwerden der "
           "Preisänderung.")],
        ["innerhalb von drei Monaten nach Erhalt dieses Schreibens"], "internet", "2027-02-18",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 10 — english_letter
# ==================================================================================================

EN_STYLES = {
    "K": Style(body_pt=10.0, left=23, right=21, leading=1.35, para_gap=2.2, align="L", subject_pt=10.9),
    "L": Style(
        body_pt=9.8,
        left=25,
        right=20,
        leading=1.40,
        para_gap=2.4,
        align="L",
        subject_pt=11.2,
        info_label_pt=7.0,
    ),
    "M": Style(body_pt=10.1, left=21, right=22, leading=1.33, para_gap=2.0, align="L", subject_pt=10.6),
    "N": Style(body_pt=10.3, left=24, right=24, leading=1.30, para_gap=2.2, align="L", subject_pt=11.0),
}


def english_letter() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, info: list[tuple[str, str]], subject: str, blocks: list[Block],
             when: date, salutation: str, closing: str, signer: tuple[str, ...], kind: str, item: dict[str, Any],
             refs: list[tuple[str, str]], key: list[str], *, amounts: list[float] | None = None, photo: bool = False) -> Case:  # fmt: skip
        letter = Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation,
                        blocks=[*blocks, Sign(closing, signer)], style=EN_STYLES[variant], created=created(when), lang="en")  # fmt: skip
        return _private_case(
            case_id, "english_letter", variant, letter,
            truth(kind=kind, sender=org.name, document_date=when, references=refs, amounts=amounts or [],
                  items=[tag_plain(item, *PRIVATE_IDS)], lang="en"),
            key, photo=photo,
        )  # fmt: skip

    def fixed(due: date, title: str, hand: str, nature: str = "declaration") -> dict[str, Any]:
        return check(fixed_item(due=due, region=None, kind="deadline", nature=nature, title=title,
                                rule="Fixed date stated in the letter."), hand)  # fmt: skip

    def within(when: date, days: int, total: float, title: str, hand: str) -> dict[str, Any]:
        return check(event_period_item(event=when, amount=days, unit="days", region=None, kind="payment", nature="payment",
                                       title=title, anchor="document_date", money=total, shift_citation="§ 193 BGB",
                                       rule=f"Payment within {days} days of the invoice date (invoice day not counted; §§ 187, "
                                            "188, 193 BGB)."), hand)  # fmt: skip

    def no_bank(org: Org) -> Org:
        return Org(**{**org.__dict__, "iban": "", "bank": "", "bic": ""})

    # K1 (photo) — university, UK date: documents by Mon 14 December 2026.
    k1 = "holdout4-english_letter-K1"
    when = drawn(k1, PRIVATE_DAYS, date(2026, 11, 20))
    due = date(2026, 12, 14)
    uni = no_bank(O.company("Beispielwetzlar Graduate School of Engineering", "Campusring 4", "35578", "Beispielwetzlar",
                            monogram="GS", accent=(0, 70, 120), style="band", tagline="Admissions Office",
                            phone="+49 6441 555 9000", email="admissions@gs-beispielwetzlar.example", account="5590000"))  # fmt: skip
    cases.append(make(
        k1, "K", uni, S_EN, [("Application ID", "GSE-26-7713"), ("Date", en_uk(when))], "Conditional offer: MSc Embedded Systems",
        [P("We are delighted to make you a conditional offer for the MSc Embedded Systems, starting in April 2027. The offer "
           "becomes final once we have verified your previous degree."),
         P(f"Please upload a certified copy of your bachelor's certificate and your final transcript to the applicant portal "
           f"**no later than {en_uk(due)}**. If we have not received them by that day, the offer lapses.")],
        when, "Dear Mr Asante,", "Yours sincerely,", ("Admissions Office",), "university",
        fixed(due, "Upload certified degree documents", "2026-12-14"), [("Application ID", "GSE-26-7713")],
        [en_uk(when), en_uk(due)], photo=True,
    ))  # fmt: skip

    # K2 — coworking invoice: 14 days. Sat 21.11.2026 + 14 = Sat 05.12.2026 → Mon 07.12.2026.
    k2 = "holdout4-english_letter-K2"
    when = drawn(k2, PRIVATE_DAYS, date(2026, 11, 21))
    cowork = O.company("Hub Beispielhafen Coworking GmbH", "Speicherweg 19", "48155", "Mustermünster", monogram="HB",
                       accent=(170, 80, 0), style="logo", tagline="Desks · Meeting rooms · Community",
                       phone="+49 251 555 7788", email="billing@hub-beispielhafen.example", account="5577880")  # fmt: skip
    total = 297.50
    cases.append(make(
        k2, "K", cowork, S_EN2, [("Invoice no.", "HUB-2611-044"), ("Invoice date", en_uk(when))], "Invoice: flex desk, December 2026",
        [Table(rows=(("Flex desk membership, December 2026", "230,00"), ("Meeting room, 3 hours", "20,00"),
                     ("VAT 19 %", "47,50"), ("Total", "297,50")), header=("Item", "EUR"), bold_rows=(3,), rule_before=(2, 3)),
         P("Please settle this invoice within 14 days of the invoice date. Late payment may pause your access card.")],
        when, "Dear Harriet,", "Cheers,", ("Billing team, Hub Beispielhafen",), "invoice",
        within(when, 14, total, "Pay invoice HUB-2611-044", "2026-12-07"), [("Invoice no.", "HUB-2611-044")],
        [en_uk(when), "within 14 days of the invoice date"], amounts=[total],
    ))  # fmt: skip

    # L1 — US bank, US date: form by Fri January 15, 2027.
    l1 = "holdout4-english_letter-L1"
    when = drawn(l1, PRIVATE_DAYS, date(2026, 11, 21))
    due = date(2027, 1, 15)
    bank = O.company("Example Prairie Savings Bank", "1400 Example Boulevard", "IA 50309", "Des Moines", monogram="EP",
                     accent=(20, 60, 110), style="minimal", tagline="Customer Care – Accounts Abroad", phone="+1 515 555 0144",
                     email="care@exampleprairie.example", account="5550144", country="USA")  # fmt: skip
    bank = Org(**{**no_bank(bank).__dict__, "postcode": "", "city": "Des Moines, IA 50309"})
    cases.append(make(
        l1, "L", bank, S_EN, [("Date", en_us(when)), ("Account ending", "…4471")], "Please confirm your address abroad",
        [P("Federal rules require us to confirm the residential address of customers who live outside the United States "
           "once a year. Our records still show an address in Iowa for you."),
         P(f"Please complete the enclosed address certification and mail or upload it **by {en_us(due)}**. Without it, we will "
           "restrict online access to your account until the form arrives.")],
        when, "Dear Kwame Asante:", "Sincerely,", ("Customer Care",), "bank_letter",
        fixed(due, "Return the address certification", "2027-01-15"), [("Account ending", "…4471")],
        [en_us(when), en_us(due)],
    ))  # fmt: skip

    # L2 — landlord: notify by Wed 16 December 2026.
    l2 = "holdout4-english_letter-L2"
    when = drawn(l2, PRIVATE_DAYS, date(2026, 11, 18))
    due = date(2026, 12, 16)
    flats = O.company("Beispielhof Serviced Living GmbH", "Hofgarten 2", "48143", "Mustermünster", monogram="SL",
                      accent=(60, 100, 80), style="band", tagline="Furnished apartments for international residents",
                      phone="+49 251 555 4040", email="residents@beispielhof-living.example", account="5540400")  # fmt: skip
    cases.append(make(
        l2, "L", flats, S_EN2, [("Date", en_uk(when)), ("Apartment", "B 3.07")], "Your lease ends on 31 January 2027",
        [P("Your fixed-term lease for apartment B 3.07 ends on 31 January 2027. We would be happy to offer you an extension "
           "of six or twelve months at the current rent."),
         P(f"Please tell us in writing **by {en_uk(due)}** whether you would like to extend. If we do not hear from you, we "
           "will plan the handover of the apartment for the end of January.")],
        when, "Dear Ms Collins,", "Kind regards,", ("Resident Services",), "rent_lease",
        fixed(due, "Tell the landlord whether to extend the lease", "2026-12-16"), [("Apartment", "B 3.07")],
        [en_uk(when), en_uk(due)],
    ))  # fmt: skip

    # M1 (photo) — language school: placement test registration by Thu 10 December 2026.
    m1 = "holdout4-english_letter-M1"
    when = drawn(m1, PRIVATE_DAYS, date(2026, 11, 18))
    due = date(2026, 12, 10)
    school = no_bank(O.company("Sprachforum Beispiellahn e.V.", "Brückenstraße 6", "35576", "Beispielwetzlar", monogram="SF",
                               accent=(120, 40, 120), style="logo", tagline="German courses for newcomers",
                               phone="+49 6441 555 2828", email="courses@sprachforum-beispiellahn.example", account="5528280"))  # fmt: skip
    cases.append(make(
        m1, "M", school, S_EN, [("Student no.", "SF-26-1190"), ("Date", en_uk(when))], "German B1 course from January",
        [P("Thank you for your interest in our evening course German B1, which starts on 12 January 2027."),
         P(f"Before we can place you, you need to book a short placement test. Please register for one of the test slots "
           f"**by {en_uk(due)}**, using the link in our e-mail. Places are limited to sixteen per course.")],
        when, "Dear Kwame,", "Best regards,", ("Course Office",), "other",
        fixed(due, "Register for the placement test", "2026-12-10"), [("Student no.", "SF-26-1190")],
        [en_uk(when), en_uk(due)], photo=True,
    ))  # fmt: skip

    # M2 — translation agency invoice: 21 days. Sat 21.11.2026 + 21 = Sat 12.12.2026 → Mon 14.12.2026.
    m2 = "holdout4-english_letter-M2"
    when = drawn(m2, PRIVATE_DAYS, date(2026, 11, 21))
    agency = O.company("Beispielwort Translations", "Übersetzerweg 3", "35390", "Mustergießen", monogram="BT", accent=(0, 90, 90),
                       style="minimal", tagline="Certified translations · English, German, French", phone="+49 641 555 6262",
                       email="office@beispielwort-translations.example", account="5562620")  # fmt: skip
    total = 142.80
    cases.append(make(
        m2, "M", agency, S_EN2, [("Invoice", "BT-26-4407"), ("Date", en_uk(when))], "Invoice for certified translations",
        [Table(rows=(("Certified translation, birth certificate", "60,00"), ("Certified translation, degree certificate", "60,00"),
                     ("VAT 19 %", "22,80"), ("Total", "142,80")), header=("Service", "EUR"), bold_rows=(3,), rule_before=(2, 3)),
         P("Kindly transfer the total within 21 days of the date of this invoice, quoting the invoice number.")],
        when, "Dear Ms Collins,", "With kind regards,", ("Beispielwort Translations",), "invoice",
        within(when, 21, total, "Pay invoice BT-26-4407", "2026-12-14"), [("Invoice", "BT-26-4407")],
        [en_uk(when), "within 21 days of the date of this invoice"], amounts=[total],
    ))  # fmt: skip

    # N1 — health insurer (English service letter): proof by Mon 11 January 2027.
    n1 = "holdout4-english_letter-N1"
    when = drawn(n1, PRIVATE_DAYS, date(2026, 11, 19))
    due = date(2027, 1, 11)
    insurer = no_bank(O.company("Beispielvita Expat Health AG", "Gesundheitsplatz 1", "65189", "Musterwiesbaden", monogram="BV",
                                accent=(0, 110, 140), style="band", tagline="International health insurance",
                                phone="+49 611 555 3030", email="members@beispielvita.example", account="5530300"))  # fmt: skip
    cases.append(make(
        n1, "N", insurer, S_EN, [("Policy no.", "BV-EXP-40917"), ("Date", en_uk(when))], "Student rate: proof of enrolment needed",
        [P("Your policy is on our student rate, which requires a current certificate of enrolment for each semester."),
         P(f"Please send us the certificate for the winter semester 2026/27 **by {en_uk(due)}**. If it does not reach us by "
           "then, we will switch your policy to the standard rate from February 2027.")],
        when, "Dear Mr Asante,", "Kind regards,", ("Member Services",), "insurance",
        fixed(due, "Send the certificate of enrolment", "2027-01-11"), [("Policy no.", "BV-EXP-40917")],
        [en_uk(when), en_uk(due)],
    ))  # fmt: skip

    # N2 — employer: sign the contract amendment by Fri 11 December 2026.
    n2 = "holdout4-english_letter-N2"
    when = drawn(n2, PRIVATE_DAYS, date(2026, 11, 18))
    due = date(2026, 12, 11)
    employer = no_bank(O.company("Beispielsoft Solutions GmbH", "Codeweg 10", "48149", "Mustermünster", monogram="BS",
                                 accent=(40, 40, 120), style="logo", tagline="People & Culture", phone="+49 251 555 0909",
                                 email="people@beispielsoft.example", account="5509090"))  # fmt: skip
    cases.append(make(
        n2, "N", employer, S_EN2, [("Employee no.", "E-2291"), ("Date", en_uk(when))], "Your new working hours from January 2027",
        [P("As agreed in your review meeting, your weekly hours will rise from 32 to 40 from 1 January 2027, with your salary "
           "adjusted accordingly. The amendment to your employment contract is enclosed."),
         P(f"Please sign both copies and return one to People & Culture **by {en_uk(due)}** so that payroll can apply the change "
           "in January.")],
        when, "Dear Harriet,", "Best wishes,", ("People & Culture",), "employment",
        fixed(due, "Return the signed contract amendment", "2026-12-11"), [("Employee no.", "E-2291")],
        [en_uk(when), en_uk(due)],
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 11 — relative_business_days (Werktage Mon–Sat vs Arbeitstage Mon–Fri, holidays excluded)
# ==================================================================================================


def business_days() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, amount: int, unit: str,
             phrase: str, subject: str, refs: list[tuple[str, str]], body: str, task: str, hand: str, kind: str, *,
             photo: bool = False, after: str = "") -> Case:  # fmt: skip
        label = ("Werktage: Monday–Saturday excluding public holidays (general meaning, cf. § 3 Abs. 2 BUrlG; defined in the letter)"
                 if unit == "werktage" else "Arbeitstage: Monday–Friday excluding public holidays (defined in the letter)")  # fmt: skip
        item = check(
            event_period_item(event=letter_date, amount=amount, unit=unit, region=None, kind="deadline", nature="declaration",
                              title=task, anchor="document_date",
                              rule=f"Period of {amount} {label}, counted from the day after the letter date (§ 187 Abs. 1 BGB).",
                              shift_citation="§ 193 BGB", forbid_saturday_end=unit == "werktage", require_no_shift=True),
            hand,
        )  # fmt: skip
        info, date_line = _layout(variant, org, refs, letter_date, "Briefdatum")
        letter = Letter(org=org, recipient=person, subject=subject, salutation=salutation, info=info, date_line=date_line,
                        blocks=[P(body), P(phrase), *([P(after)] if after else []), Sign("Mit freundlichen Grüßen", (org.name,))],
                        style=STYLES[variant], created=created(letter_date))  # fmt: skip
        return _private_case(
            case_id, "relative_business_days", variant, letter,
            truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=[],
                  items=[tag_plain(item, *PRIVATE_IDS)]),
            [de(letter_date), phrase.split("**")[1]], photo=photo,
        )  # fmt: skip

    # K1: Sat 21.11.2026, 10 Arbeitstage: Mo 23.(1) Di 24.(2) Mi 25.(3) Do 26.(4) Fr 27.(5) Mo 30.(6) Di 01.12.(7) Mi 02.(8)
    #     Do 03.(9) Fr 04.(10) → Fri 04.12.2026.
    k1 = "holdout4-relative_business_days-K1"
    d = drawn(k1, PRIVATE_DAYS, date(2026, 11, 21))
    org = O.company("Bauspar Beispielheim AG", "Sparerweg 1", "35390", "Mustergießen", monogram="BH", accent=(0, 80, 60),
                    style="logo", tagline="Bausparen · Baufinanzierung", phone="0641 555 52 52",
                    email="darlehen@bauspar-beispielheim.example", hr="AG Mustergießen HRB 2 017", account="5552520")  # fmt: skip
    cases.append(make(
        k1, "K", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, 10, "business_days",
        "Bitte reichen Sie den Nachweis **binnen 10 Arbeitstagen nach dem Briefdatum** ein. Arbeitstage sind Montag bis "
        "Freitag; gesetzliche Feiertage zählen nicht.",
        "Ihr Bauspardarlehen – Nachweis der Verwendung", [("Vertragsnummer", "BH 6 330 418-02")],
        "für die Auszahlung des Bauspardarlehens fehlt uns noch ein Nachweis, dass Sie das Geld für Ihre Wohnung verwenden: "
        "die Rechnung der Heizungsfirma oder der unterschriebene Auftrag.",
        "Verwendungsnachweis für das Bauspardarlehen einreichen", "2026-12-04", "bank_letter",
        after="Geht der Nachweis nicht rechtzeitig ein, verschiebt sich die Auszahlung auf den nächsten Monatsersten.",
    ))  # fmt: skip

    # K2: Wed 18.11.2026, 14 Werktage: Do 19.(1) Fr 20.(2) Sa 21.(3) Mo 23.(4) Di 24.(5) Mi 25.(6) Do 26.(7) Fr 27.(8) Sa 28.(9)
    #     Mo 30.(10) Di 01.12.(11) Mi 02.(12) Do 03.(13) Fr 04.(14) → Fri 04.12.2026.
    k2 = "holdout4-relative_business_days-K2"
    d = drawn(k2, PRIVATE_DAYS, date(2026, 11, 18))
    org = O.company("Wohnbau Beispielgrund eG", "Siedlungsweg 14", "48147", "Mustermünster", monogram="WB", accent=(110, 70, 30),
                    style="band", tagline="Genossenschaftliches Wohnen", phone="0251 555 36 36",
                    email="vermietung@wohnbau-beispielgrund.example", hr="GnR 377 AG Mustermünster", account="5536360")  # fmt: skip
    cases.append(make(
        k2, "K", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, 14, "werktage",
        "Den unterschriebenen Vertrag benötigen wir **innerhalb von 14 Werktagen ab dem Briefdatum** zurück. Werktage sind "
        "Montag bis Samstag; Sonn- und Feiertage werden nicht gezählt.",
        "Ihre neue Wohnung Siedlungsweg 18, Erdgeschoss rechts", [("Mitgliedsnummer", "WB-4402"), ("Wohnung", "SW18-EG-R")],
        "der Vorstand hat Ihnen die Wohnung Siedlungsweg 18 zum 01.01.2027 zugeteilt. Den Nutzungsvertrag in zwei Ausfertigungen "
        "legen wir bei.",
        "Unterschriebenen Nutzungsvertrag zurückgeben", "2026-12-04", "rent_lease",
    ))  # fmt: skip

    # L1 (photo): Sat 21.11.2026, 13 Werktage: Mo 23.(1) Di 24.(2) Mi 25.(3) Do 26.(4) Fr 27.(5) Sa 28.(6) Mo 30.(7)
    #     Di 01.12.(8) Mi 02.(9) Do 03.(10) Fr 04.(11) Sa 05.(12) Mo 07.(13) → Mon 07.12.2026.
    l1 = "holdout4-relative_business_days-L1"
    d = drawn(l1, PRIVATE_DAYS, date(2026, 11, 21))
    org = O.company("Kfz-Versicherung Beispielsicher AG", "Schadenring 5", "65189", "Musterwiesbaden", monogram="KS",
                    accent=(0, 60, 130), style="minimal", tagline="Schadenservice Kraftfahrt", phone="0611 555 47 47",
                    email="schaden@beispielsicher.example", hr="AG Musterwiesbaden HRB 40 112", account="5547470")  # fmt: skip
    cases.append(make(
        l1, "L", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, 13, "werktage",
        "Senden Sie uns das ausgefüllte Formular bitte **binnen 13 Werktagen nach dem Datum dieses Schreibens** zurück "
        "(Werktage: Montag bis Samstag ohne gesetzliche Feiertage).",
        "Wildunfall vom 09.11.2026 – Ihr Fahrzeug MQ-BQ 207", [("Schadennummer", "KS-26-1109-218")],
        "Sie haben uns einen Zusammenstoß mit einem Reh gemeldet. Für die Teilkaskoregulierung brauchen wir die "
        "Wildschadenbescheinigung des Jagdpächters oder der Polizei sowie den beiliegenden Schadenfragebogen.",
        "Schadenfragebogen und Wildschadenbescheinigung einsenden", "2026-12-07", "insurance", photo=True,
    ))  # fmt: skip

    # M1: Wed 18.11.2026, 10 Arbeitstage: Do 19.(1) Fr 20.(2) Mo 23.(3) Di 24.(4) Mi 25.(5) Do 26.(6) Fr 27.(7) Mo 30.(8)
    #     Di 01.12.(9) Mi 02.(10) → Wed 02.12.2026.
    m1 = "holdout4-relative_business_days-M1"
    d = drawn(m1, PRIVATE_DAYS, date(2026, 11, 18))
    org = O.company("Druckerei Beispiellahn GmbH", "Papiermühle 2", "35576", "Beispielwetzlar", monogram="DL", accent=(80, 80, 80),
                    style="band", tagline="Personalabteilung", phone="06441 555 81 00", email="personal@druckerei-beispiellahn.example",
                    account="5581000")  # fmt: skip
    cases.append(make(
        m1, "M", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, 10, "business_days",
        "Ihre Wünsche für den Urlaub im ersten Halbjahr tragen Sie bitte **binnen 10 Arbeitstagen ab dem Briefdatum** in die "
        "Liste ein; Arbeitstage sind Montag bis Freitag ohne Feiertage.",
        "Urlaubsplanung Januar bis Juni 2027", [("Personalnummer", "DL-0718")],
        "damit wir die Schichten im neuen Jahr planen können, bitten wir alle Beschäftigten, ihre Urlaubswünsche frühzeitig "
        "anzumelden. Die Liste hängt im Pausenraum aus und ist auch im Mitarbeiterportal abrufbar.",
        "Urlaubswünsche für das erste Halbjahr eintragen", "2026-12-02", "employment",
    ))  # fmt: skip

    # M2: Fri 20.11.2026, 15 Werktage: Sa 21.(1) Mo 23.(2) Di 24.(3) Mi 25.(4) Do 26.(5) Fr 27.(6) Sa 28.(7) Mo 30.(8)
    #     Di 01.12.(9) Mi 02.(10) Do 03.(11) Fr 04.(12) Sa 05.(13) Mo 07.(14) Di 08.(15) → Tue 08.12.2026.
    m2 = "holdout4-relative_business_days-M2"
    d = drawn(m2, PRIVATE_DAYS, date(2026, 11, 20))
    org = O.company("Musterhausen Bausachverständige GbR", "Gutachterweg 7", "35394", "Mustergießen", monogram="MB",
                    accent=(70, 50, 20), style="minimal", tagline="Gutachten · Baubegleitung · Abnahmen", phone="0641 555 70 17",
                    email="buero@sv-musterhausen.example", account="5570170")  # fmt: skip
    cases.append(make(
        m2, "M", org, S_GEN, "Sehr geehrter Herr Musterquell,", d, 15, "werktage",
        "Bitte geben Sie uns **innerhalb von 15 Werktagen nach dem Briefdatum** Bescheid, ob wir das Gutachten erstellen "
        "sollen; als Werktage zählen Montag bis Samstag, nicht aber Sonn- und Feiertage.",
        "Ihre Anfrage: Feuchtigkeit im Keller", [("Anfrage", "SV-26-311")],
        "vielen Dank für Ihre Anfrage. Für ein Gutachten zur Ursache der Feuchtigkeit in Ihrem Keller veranschlagen wir "
        "einen Ortstermin und die Ausarbeitung zu einem Pauschalpreis; das Angebot liegt bei.",
        "Gutachtenauftrag erteilen oder absagen", "2026-12-08", "other",
    ))  # fmt: skip

    # N1 (photo): Thu 19.11.2026, 12 Arbeitstage: Fr 20.(1) Mo 23.(2) Di 24.(3) Mi 25.(4) Do 26.(5) Fr 27.(6) Mo 30.(7)
    #     Di 01.12.(8) Mi 02.(9) Do 03.(10) Fr 04.(11) Mo 07.(12) → Mon 07.12.2026.
    n1 = "holdout4-relative_business_days-N1"
    d = drawn(n1, PRIVATE_DAYS, date(2026, 11, 19))
    org = O.company("Kita-Verbund Beispielkinder gGmbH", "Spielplatzweg 3", "35390", "Mustergießen", monogram="KB",
                    accent=(160, 80, 0), style="logo", tagline="Platzvergabe", phone="0641 555 40 80",
                    email="platzvergabe@kita-beispielkinder.example", account="5540800")  # fmt: skip
    cases.append(make(
        n1, "N", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, 12, "business_days",
        "Bitte sagen Sie uns **binnen 12 Arbeitstagen ab dem Datum dieses Briefes** zu oder ab. Gezählt werden Montag bis "
        "Freitag; Feiertage bleiben außer Betracht.",
        "Ein Krippenplatz für Ihren Sohn ab Februar 2027", [("Vormerkung", "KV-2026-0815")],
        "wir freuen uns, Ihnen für Ihren Sohn Jonas einen Krippenplatz in der Kita Sonnenblume ab dem 01.02.2027 anbieten zu "
        "können, mit einer Betreuungszeit von 35 Stunden in der Woche.",
        "Krippenplatz zusagen oder absagen", "2026-12-07", "other", photo=True,
        after="Ohne Rückmeldung vergeben wir den Platz an die nächste Familie auf der Warteliste.",
    ))  # fmt: skip
    return cases
