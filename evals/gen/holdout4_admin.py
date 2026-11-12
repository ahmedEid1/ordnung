"""Holdout4 split, families 1, 2, 3, 7 and 12: variants K, L, M and N of the administrative acts.

Written after the code freeze for one planned reading day, 2026-11-24 (``final.FINAL_DAY``), from the law and from how
such letters read: new senders, recipients, wording, layout, amounts and the Länder mix of holdout3 at twice its size.
Every letter is read on that day, posted between 18 and 21 November 2026, and every scored date lies after the last
valid day, 2026-12-01.

Layouts: variant K prints the place and date above the subject and the Belehrung under a small heading on page 1;
variant L opens the information block with the date and prints the Belehrung on page 2; variant M names the date under
the letter's own label at the foot of the information block and runs the Belehrung in; variant N prints place and date
above the subject and the Belehrung on page 2.

The letter and posting days are drawn with ``rng_for("holdout4", case_id)`` among the days that fit each scenario and
asserted next to the label worked out by hand (``check(item, hand)``). Each scored item names the conventions its date
rests on, and for a disputed one the dates under the other reading (``tag_remedy``), all worked out with :mod:`law`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import law
from .common import (
    Case,
    event_period_item,
    fixed_item,
    objection_item,
    spec,
    truth,
    undated_item,
    with_conventions,
)
from .families_admin import check, created
from .pdf import Block, Envelope, H, Letter, Org, P, PageBreak, Person, Sign, Style, Table
from .text import bei, de, de_weekday, eur, eur_plain, iban, iban_grouped, rng_for

SPLIT = "holdout4"
#: The day every holdout4 letter is read (``final.FINAL_DAY``) and the last day its labels must lie after.
TODAY = date(2026, 11, 24)
VALID_UNTIL = date(2026, 12, 1)
#: The days an authority's letter is dated and posted (Wed–Fri, 6 to 4 days before ``TODAY``).
AUTHORITY_DAYS = (date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20))
#: The days a private sender's letter is dated (Wed–Sat, 6 to 3 days before ``TODAY``).
PRIVATE_DAYS = (*AUTHORITY_DAYS, date(2026, 11, 21))
SATURDAY_POSTING = date(2026, 11, 21)

STYLES = {
    "K": Style(body_pt=10.1, left=23, right=21, leading=1.34, para_gap=2.1, align="J", info_label_pt=7.2,
               info_value_pt=8.7, subject_pt=10.9),
    "L": Style(body_pt=9.8, left=25, right=20, leading=1.40, para_gap=2.4, align="L", info_label_pt=7.0,
               info_value_pt=8.4, subject_pt=11.2),
    "M": Style(body_pt=10.0, left=21, right=22, leading=1.33, para_gap=1.9, align="J", info_label_pt=7.5,
               info_value_pt=8.9, subject_pt=10.5),
    "N": Style(body_pt=10.3, left=24, right=24, leading=1.30, para_gap=2.2, align="L", info_label_pt=7.2,
               info_value_pt=8.6, subject_pt=11.0),
}  # fmt: skip


def drawn(case_id: str, days: tuple[date, ...], expect: date) -> date:
    """The letter's day, drawn among ``days`` with the split's seed for ``case_id``; ``expect`` is the day the hand-worked
    label below it was computed from."""
    day = rng_for(SPLIT, case_id).choice(days)
    assert day == expect, (case_id, day, expect)
    return day


# --------------------------------------------------------------------------------------------------
# recipients (new; one per Land used, two without a Land, two writing in English)
# --------------------------------------------------------------------------------------------------

S_MV = Person("Frauke Beispielrade", "Boddenweg 11", "18311", "Musterdamgarten")
S_HB = Person("Bente Beispielhusen", "Hafenkante 5", "28759", "Bremen")
S_SL = Person("Mattis Musterwadern", "Hüttenring 14", "66687", "Beispielwadern")
S_SH = Person("Tjark Beispielholm", "Knickweg 3", "24376", "Musterkappeln")
S_BY = Person("Kathrin Musterreiter", "Am Kalvarienberg 8", "94032", "Beispielpassau")
S_HH = Person("Lavinia Beispielfleet", "Kanalstraße 70", "22085", "Hamburg")
S_BB = Person("Ronny Musterspree", "Kiefernweg 19", "15848", "Beispielkow")
S_RP = Person("Annika Beispielsteiner", "Hunsrückstraße 2", "55469", "Musterbach im Hunsrück")
S_NI = Person("Fenja Musterwolde", "Moorweg 6", "26655", "Beispielstede")
S_ST = Person("Uwe Beispielharz", "Bodetal 4", "06502", "Musterquedlin")
S_BE = Person("Yusuf Beispielkiez", "Am Spreebord 3", "10589", "Berlin")
S_NW = Person("Ilka Musterlenne", "Lennestraße 41", "58119", "Beispielhagen")
S_GEN = Person("Bastian Musterquell", "Quellenweg 7", "35576", "Beispielwetzlar")
S_GEN2 = Person("Johanna Beispielacker", "Ackerstraße 26", "48143", "Mustermünster")
S_EN = Person("Kwame Asante", "Quellenweg 7", "35576", "Beispielwetzlar", country="Germany")
S_EN2 = Person("Harriet Collins", "Ackerstraße 26", "48143", "Mustermünster", country="GERMANY")
S_IBAN = iban("DE", "51390000" + "0074402218")


def authority(name: str, street: str, postcode: str, city: str, region: str | None, head: tuple[str, ...], *,
              phone: str, email: str, blz: str, account: str, kind: str = "authority", style: str = "authority",
              accent: tuple[int, int, int] = (30, 60, 120), bank: str = "Landesmusterbank", monogram: str = "",
              hours: tuple[str, ...] = (), legal: tuple[str, ...] = ()) -> Org:  # fmt: skip
    """A public sender; ``region`` is the Land its letterhead names (None: it names none)."""
    return Org(name=name, kind=kind, street=street, postcode=postcode, city=city, region=region, head=head, phone=phone,
               email=email, bank=bank, iban=iban("DE", blz + account.zfill(10)), style=style, accent=accent,
               monogram=monogram, hours=hours, legal=legal)  # fmt: skip


# --------------------------------------------------------------------------------------------------
# conventions
# --------------------------------------------------------------------------------------------------


def _remedy_end(
    posted: date, scope: str, region: str | None, *, began: date | None = None, moved: bool = False
) -> date:
    """The end of a one-month remedy period after a posted decision; ``moved`` takes the other reading of c03 for the
    fiction day (AO: it does not move; SGB X and Land VwVfG: it moves off a Saturday, Sunday or holiday)."""
    why = law.Derivation()
    if moved and scope == "ao":
        notified = law.deemed_delivery(
            posted, "sgbx", region, why
        )  # the same fourth day, left where it falls
    else:
        land = region if scope == "vwvfg" else None
        notified = law.deemed_delivery(posted, scope, region, why, land=land, procedure_began=began)
        if moved:
            notified = law.shift_to_working_day(notified, region, why, "§ 193 BGB applied to the fiction day")
    return law.period_end(notified, 1, "months", region, why, shift=True, shift_citation="§ 193 BGB")


def year_end_tag(due: date) -> list[str]:
    """f02 for a label on 24 or 31 December, which stays where it is."""
    return ["f02"] if (due.month, due.day) in ((12, 24), (12, 31)) else []


def tag_remedy(item: dict[str, Any], *, posted: date, scope: str, region: str | None, letter_date: date | None = None,
               began: date | None = None, klage: bool = False) -> dict[str, Any]:  # fmt: skip
    """Tag a remedy period with its conventions and the dates under the other readings of the disputed ones: c02 (the
    letter date where a later posting day is stated), c03 (the fiction day moved or not; in BW, BY and MV the other
    day count for the procedure's start) — c07 and c09 give no other date."""
    label = date.fromisoformat(item["expected_due"])
    ids = ["c01", "c02", "c03", "c04", *(["c07"] if scope == "vwvfg" else []), *(["c09"] if klage else [])]
    vw_began = began if scope == "vwvfg" else None
    others = {_remedy_end(posted, scope, region, began=vw_began, moved=True)}
    if letter_date is not None and letter_date != posted:
        others.add(_remedy_end(letter_date, scope, region, began=vw_began))
    switch = law.LAND_VWVFG_OLD_PROCEDURES.get(region or "") if scope == "vwvfg" else None
    if switch is not None and began is not None and began < switch:
        others.add(_remedy_end(posted, scope, region))
    elif switch is not None and began is None:
        others.add(_remedy_end(posted, scope, region, began=switch - timedelta(days=1)))
    return with_conventions(item, [*ids, *year_end_tag(label)], sorted(d for d in others if d != label))


def tag_plain(item: dict[str, Any], *ids: str) -> dict[str, Any]:
    """Tag an item whose conventions are none of them disputed."""
    return with_conventions(item, [*ids, *year_end_tag(date.fromisoformat(item["expected_due"]))])


def tag_fine(item: dict[str, Any]) -> dict[str, Any]:
    """A fine's two weeks from the Zustellung day on the envelope (c03): the other reading of c03 is about the fiction
    day of a posted decision, which a formally served Bescheid does not have, so it gives no other date."""
    return with_conventions(item, ["c01", "c03", "c04"], [])


def _case(case_id: str, family: str, variant: str, letter: Letter, t: dict[str, Any], region: str | None, key: list[str],
          *, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
    return Case(id=case_id, split=SPLIT, family=family, variant=variant, letter=letter, truth=t, today=TODAY,
                authority_region=region, recipient_region=region, key_phrases=key, photo=photo, notes=notes)  # fmt: skip


def page_two(heading: str, *paragraphs: str) -> list[Block]:
    """Variants L and N: the Belehrung on a page of its own."""
    return [PageBreak(), H(heading, size=10.4), *(P(text, size=9.1) for text in paragraphs)]


def small_heading(heading: str, *paragraphs: str) -> list[Block]:
    """Variant K: the Belehrung under a small heading on page 1."""
    return [H(heading, size=9.5), *(P(text, size=8.6) for text in paragraphs)]


def run_in(label: str, *paragraphs: str) -> list[Block]:
    """Variant M: the Belehrung run in after a bold label."""
    first, *rest = paragraphs
    return [P(f"**{label}** {first}", size=8.8), *(P(text, size=8.8) for text in rest)]


def place_date(org: Org, d: date) -> str:
    return f"{org.city}, {de(d)}"


# ==================================================================================================
# Family 1 — tax_assessment (AO: the fiction day moves off Sat/Sun/holidays; § 355 AO one month)
# ==================================================================================================


def _assessment(rows: list[tuple[str, int]], tax: int, withheld: int) -> tuple[Table, int]:
    """Income, deductions, the tax set, the wage tax already paid and the balance (positive: to pay)."""
    taxable = rows[0][1] - sum(v for _, v in rows[1:])
    body = [(rows[0][0], f"{rows[0][1]:,}".replace(",", "."))]
    body += [(label, "– " + f"{v:,}".replace(",", ".")) for label, v in rows[1:]]
    diff = tax - withheld
    body += [
        ("zu versteuerndes Einkommen (volle Euro)", f"{taxable:,}".replace(",", ".")),
        ("festgesetzte Einkommensteuer", eur_plain(tax)),
        ("abzüglich einbehaltene Lohnsteuer", f"– {eur_plain(withheld)}"),
        ("verbleibende Zahlung" if diff > 0 else "Guthaben zu Ihren Gunsten", eur_plain(abs(diff))),
    ]
    n, last = len(rows), len(body) - 1
    table = Table(
        rows=tuple(body),
        header=("Berechnung", "Euro"),
        value_width=30,
        bold_rows=(n, last),
        rule_before=(n, last),
    )
    return table, diff


def _tax_belehrung(variant: str, org: Org) -> list[Block]:
    if variant == "K":
        return small_heading(
            "Rechtsbehelfsbelehrung",
            f"Sie können gegen diesen Bescheid Einspruch einlegen. Der Einspruch muss binnen eines Monats nach der "
            f"Bekanntgabe {bei(org.name)} eingehen, schriftlich, über das Portal ELSTER oder mündlich zur Niederschrift. "
            "Haben wir Ihnen den Bescheid mit der Post geschickt, gilt er mit dem vierten Tag nach der Aufgabe zur Post "
            "als bekannt gegeben; erreicht er Sie nachweislich erst später oder gar nicht, gilt dieser Tag nicht.",
        )
    if variant == "L":
        return page_two(
            "Belehrung über Ihren Rechtsbehelf",
            "Wer diesen Bescheid für fehlerhaft hält, kann dagegen innerhalb eines Monats Einspruch erheben. Die "
            "Monatsfrist beginnt, sobald der Bescheid als bekannt gegeben gilt; bei einem Versand mit gewöhnlicher Post "
            "ist das der vierte Tag nach dem Tag, an dem er zur Post gegeben wurde.",
            f"Richten Sie den Einspruch schriftlich oder elektronisch an das {org.name}; Sie können ihn dort auch zu "
            "Protokoll geben. Eine Begründung ist erwünscht, aber keine Voraussetzung.",
        )
    if variant == "M":
        return run_in(
            "Rechtsbehelf:",
            f"Gegen die Festsetzung ist der Einspruch gegeben. Legen Sie ihn innerhalb eines Monats ab Bekanntgabe "
            f"{bei(org.name)} ein, schriftlich, elektronisch oder zur Niederschrift. Für einen per Post zugesandten "
            "Bescheid ist Bekanntgabetag der vierte Tag nach seiner Aufgabe zur Post.",
        )
    return page_two(
        "Rechtsbehelfsbelehrung",
        "Dieser Bescheid kann mit dem Einspruch angefochten werden. Die Einspruchsfrist beträgt einen Monat und rechnet ab "
        "der Bekanntgabe; ein Bescheid, der als Brief verschickt wird, ist am vierten Tag nach dem Absenden als bekannt "
        "gegeben anzusehen.",
        "Den Einspruch reichen Sie bei dem oben genannten Finanzamt ein. Er bedarf der Schriftform oder der elektronischen "
        "Übermittlung; Sie können ihn aber auch an Amtsstelle zur Niederschrift erklären.",
    )


_TAX_KEY = {
    "K": "Der Einspruch muss binnen eines Monats nach der Bekanntgabe",
    "L": "Die Monatsfrist beginnt, sobald der Bescheid als bekannt gegeben gilt",
    "M": "Legen Sie ihn innerhalb eines Monats ab Bekanntgabe",
    "N": "Die Einspruchsfrist beträgt einen Monat und rechnet ab der Bekanntgabe",
}


def tax_assessment() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, posted: date, year: int,
             stnr: str, rows: list[tuple[str, int]], tax: int, withheld: int, intro: str, notes: list[str], hand: str,
             pay_due: date | None = None, hand_pay: str | None = None, case_notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="ao", remedy="einspruch", region=org.region,
                           title=f"Einspruchsfrist Einkommensteuerbescheid {year}"),
            hand,
        )  # fmt: skip
        items = [tag_remedy(item, posted=posted, scope="ao", region=org.region, letter_date=letter_date)]
        table, diff = _assessment(rows, tax, withheld)
        money: list[Block] = []
        if diff > 0:
            assert pay_due is not None and hand_pay is not None
            pay = check(
                fixed_item(due=pay_due, region=org.region, kind="payment", nature="payment", money=float(diff),
                           title=f"Einkommensteuer {year} nachzahlen",
                           rule="Fälligkeitstag printed in the assessment (§ 36 Abs. 4 EStG, set by the Finanzamt)."),
                hand_pay,
            )  # fmt: skip
            items.append(tag_plain(pay, "c01", "c04"))
            money.append(P(f"Die verbleibende Zahlung von **{eur(diff)}** ist am **{de(pay_due)}** fällig. Überweisen Sie den "
                           f"Betrag an die {org.bank}, IBAN {iban_grouped(org.iban)}, und nennen Sie als Verwendungszweck "
                           "Ihre Steuernummer. Für jeden angefangenen Monat der Säumnis fallen Zuschläge an."))  # fmt: skip
        else:
            assert pay_due is None
            money.append(
                P(f"Das Guthaben von **{eur(-diff)}** überweisen wir auf Ihr Konto {iban_grouped(S_IBAN)}.")
            )
        explain = [P(text, size=9.0) for text in notes]
        if variant == "K":
            info = [("Steuernummer", stnr)]
            if posted != letter_date:
                info.append(("Zur Post gegeben", de(posted)))
            blocks = [P(intro), table, *money, H("Erläuterungen", size=9.6), *explain, *_tax_belehrung("K", org),
                      Sign("Mit freundlichen Grüßen", ("Ihr Finanzamt",))]  # fmt: skip
            date_line: str | None = place_date(org, letter_date)
        elif variant == "M":
            info = [("Steuernummer", stnr), ("Bescheid vom", de(letter_date))]
            blocks = [P(intro), table, *money, *explain, *_tax_belehrung("M", org),
                      P("Dieser Bescheid wurde maschinell erstellt und trägt keine Unterschrift.", size=7.6)]  # fmt: skip
            date_line = None
        else:
            info = (
                [("Datum", de(letter_date)), ("Steuernummer", stnr)]
                if variant == "L"
                else [("Steuernummer", stnr)]
            )
            if posted != letter_date:
                info.append(("Abgesandt am", de(posted)))
            blocks = [P(intro), table, *money,
                      P("Wie wir die Steuer ermittelt haben und welchen Rechtsbehelf Sie haben, lesen Sie auf Seite 2."),
                      *_tax_belehrung(variant, org)[:2], *explain, *_tax_belehrung(variant, org)[2:],
                      Sign("Freundliche Grüße", ("Ihr Finanzamt", "Veranlagungsteam 2"))]  # fmt: skip
            date_line = place_date(org, letter_date) if variant == "N" else None
        letter = Letter(
            org=org, recipient=person, info=info, salutation=salutation, date_line=date_line,
            subject=f"Bescheid für {year} über Einkommensteuer", blocks=blocks, style=STYLES[variant],
            created=created(letter_date), running_ref=f"Steuernummer {stnr}",
        )  # fmt: skip
        return _case(
            case_id, "tax_assessment", variant, letter,
            truth(kind="tax_assessment", sender=org.name, document_date=letter_date, references=[("Steuernummer", stnr)],
                  amounts=[float(abs(diff))], remedy="einspruch", items=items),
            org.region, [de(letter_date), stnr, _TAX_KEY[variant], *([de(posted)] if posted != letter_date else [])],
            notes=case_notes,
        )  # fmt: skip

    fa_mv = authority("Finanzamt Beispielgüstrow", "Domplatz 9", "18273", "Beispielgüstrow", "MV",
                      ("Land Mecklenburg-Vorpommern", "Steuerverwaltung · Veranlagung"), phone="03843 555 71-0",
                      email="poststelle@fa-beispielguestrow.example", blz="13000000", account="7110040",
                      accent=(0, 75, 135), hours=("Info-Theke:", "Mo, Di, Do 8–15 Uhr", "Mi 8–17 Uhr, Fr 8–12 Uhr"))  # fmt: skip
    # K1 — MV. Posted Wed 18.11.2026 → day 4 = Sun 22.11. → Mon 23.11. (§ 108 Abs. 3 AO) → Wed 23.12.2026.
    k1 = "holdout4-tax_assessment-K1"
    d = drawn(k1, AUTHORITY_DAYS, date(2026, 11, 18))
    cases.append(make(
        k1, "K", fa_mv, S_MV, "Sehr geehrte Frau Beispielrade,", d, d, 2025, "086/112/40917",
        [("Einkünfte aus nichtselbständiger Arbeit", 39_640), ("Werbungskosten", 1_418),
         ("Sonderausgaben", 5_902)], 4_311, 5_026,
        "nach Prüfung Ihrer Einkommensteuererklärung für das Jahr 2025 setzen wir die Steuer wie folgt fest:",
        ["Die Kosten für Ihr Arbeitszimmer konnten wir nicht berücksichtigen, weil Ihnen beim Arbeitgeber ein Büro zur "
         "Verfügung steht. Stattdessen ist die Tagespauschale für 92 Tage im Homeoffice angesetzt."],
        "2026-12-23",
        case_notes="Day 4 after posting is a Sunday; the AO moves it to Monday.",
    ))  # fmt: skip

    fa_x = authority("Finanzamt Musterhöhe", "Am Amtshof 4", "35578", "Musterhöhe", None, ("Steuerverwaltung",),
                     phone="06441 555 26-0", email="poststelle@fa-musterhoehe.example", blz="51300000", account="2600300",
                     style="minimal", accent=(80, 60, 30))  # fmt: skip
    # K2 — Land unknown. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    k2 = "holdout4-tax_assessment-K2"
    d = drawn(k2, AUTHORITY_DAYS, date(2026, 11, 19))
    cases.append(make(
        k2, "K", fa_x, S_GEN, "Sehr geehrter Herr Musterquell,", d, d, 2025, "019/437/22605",
        [("Einkünfte aus nichtselbständiger Arbeit", 52_170), ("Werbungskosten", 3_244),
         ("Sonderausgaben", 7_388), ("Außergewöhnliche Belastungen", 860)], 7_402, 8_115,
        "Ihre Steuererklärung für 2025 ist bearbeitet. Die Einkommensteuer berechnet sich so:",
        ["Für die Fahrten zur Arbeit haben wir 211 Arbeitstage und eine einfache Entfernung von 27 km angesetzt. Ihre "
         "Krankheitskosten wirken sich aus, soweit sie die zumutbare Belastung übersteigen."],
        "2026-12-23",
    ))  # fmt: skip

    fa_hb = authority("Finanzamt Beispiel-Vegesack", "Am Speicherhof 12", "28757", "Bremen", "HB",
                      ("Freie Hansestadt Bremen", "Die Senatorin für Finanzen · Steuerverwaltung"), phone="0421 555 66-40",
                      email="office@fa-beispiel-vegesack.bremen.example", blz="29000000", account="6640100",
                      bank="Bremer Landesmusterkasse", style="band", accent=(160, 25, 40))  # fmt: skip
    # L1 — HB, with a payment. Bescheid Thu 19.11.2026, sent Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026 (Heiligabend
    # is a working day). Counted from the Bescheid date: Mon 23.11. → Wed 23.12.2026. Fälligkeitstag printed: Mon 28.12.2026.
    l1 = "holdout4-tax_assessment-L1"
    d = drawn(l1, AUTHORITY_DAYS, date(2026, 11, 19))
    cases.append(make(
        l1, "L", fa_hb, S_HB, "Sehr geehrte Frau Beispielhusen,", d, date(2026, 11, 20), 2025, "460/318/72214",
        [("Einkünfte aus nichtselbständiger Arbeit", 44_930), ("Einkünfte aus Vermietung", 6_120),
         ("Werbungskosten", 1_310), ("Sonderausgaben", 6_845)], 8_036, 6_412,
        "für das Jahr 2025 setzen wir die Einkommensteuer fest. Neben Ihrem Arbeitslohn sind die Einkünfte aus der "
        "vermieteten Wohnung in der Hafenkante 7 enthalten; daraus ergibt sich eine Zahlung:",
        ["Bei der vermieteten Wohnung haben wir die Abschreibung mit 2 % der Anschaffungskosten des Gebäudes angesetzt. Die "
         "Küche ist ein eigenes Wirtschaftsgut und wird über zehn Jahre abgeschrieben."],
        "2026-12-24", date(2026, 12, 28), "2026-12-28",
        case_notes="The info block states a posting day one day after the Bescheid date (c02).",
    ))  # fmt: skip

    fa_sl = authority("Finanzamt Beispiel-Merzig", "Saargauer Straße 30", "66663", "Beispiel-Merzig", "SL",
                      ("Saarland", "Ministerium der Finanzen · Steuerverwaltung"), phone="06861 555 40-0",
                      email="poststelle@fa-beispiel-merzig.saarland.example", blz="59000000", account="4400200",
                      bank="Saarländische Landesmusterkasse", style="logo", monogram="FM", accent=(0, 70, 120))  # fmt: skip
    # L2 — SL. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    l2 = "holdout4-tax_assessment-L2"
    d = drawn(l2, AUTHORITY_DAYS, date(2026, 11, 19))
    cases.append(make(
        l2, "L", fa_sl, S_SL, "Sehr geehrter Herr Musterwadern,", d, d, 2025, "030/226/19083",
        [("Einkünfte aus nichtselbständiger Arbeit", 31_205), ("Werbungskosten", 2_486), ("Sonderausgaben", 4_970)],
        3_014, 3_668,
        "die Einkommensteuer für 2025 ist auf Grund Ihrer Erklärung festgesetzt worden:",
        ["Ihre Fortbildung zum Techniker haben wir als Werbungskosten berücksichtigt, soweit der Arbeitgeber die Kosten nicht "
         "erstattet hat."],
        "2026-12-23",
    ))  # fmt: skip

    fa_mv2 = authority("Finanzamt Musterwolgast", "Hafenstraße 2", "17438", "Musterwolgast", "MV",
                       ("Mecklenburg-Vorpommern", "Steuerverwaltung"), phone="03836 555 81-0",
                       email="poststelle@fa-musterwolgast.example", blz="15000000", account="8100500",
                       style="band", accent=(0, 95, 140))  # fmt: skip
    # M1 — MV. Posted Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026.
    m1 = "holdout4-tax_assessment-M1"
    d = drawn(m1, AUTHORITY_DAYS, date(2026, 11, 20))
    cases.append(make(
        m1, "M", fa_mv2, S_MV, "Sehr geehrte Frau Beispielrade,", d, d, 2024, "081/509/11736",
        [("Einkünfte aus nichtselbständiger Arbeit", 37_480), ("Werbungskosten", 1_960), ("Sonderausgaben", 5_520)],
        3_998, 4_431,
        "Ihre nachgereichte Erklärung für 2024 haben wir ausgewertet. Die Einkommensteuer setzen wir wie folgt fest:",
        ["Ihre Erklärung ist nach Ablauf der Abgabefrist eingegangen; einen Verspätungszuschlag setzen wir wegen der "
         "Erstattung nicht fest."],
        "2026-12-24",
    ))  # fmt: skip

    fa_x2 = authority("Finanzamt Beispielau", "Lindenplatz 3", "48145", "Beispielau", None,
                      ("Steuerverwaltung", "Arbeitnehmerbereich"), phone="0251 555 49-0",
                      email="poststelle@fa-beispielau.example", blz="40000000", account="4900100",
                      style="authority", accent=(70, 50, 100))  # fmt: skip
    # M2 — Land unknown. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    m2 = "holdout4-tax_assessment-M2"
    d = drawn(m2, AUTHORITY_DAYS, date(2026, 11, 19))
    cases.append(make(
        m2, "M", fa_x2, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, d, 2025, "337/5140/8862",
        [("Einkünfte aus nichtselbständiger Arbeit", 28_760), ("Werbungskosten", 1_230), ("Sonderausgaben", 4_410)],
        2_377, 2_916,
        "die Einkommensteuer für 2025 setzen wir auf Grund Ihrer Erklärung so fest:",
        ["Die Aufwendungen für die Betreuung Ihres Sohnes in der Kindertagesstätte sind zu zwei Dritteln als Sonderausgaben "
         "berücksichtigt."],
        "2026-12-23",
    ))  # fmt: skip

    fa_hb2 = authority("Finanzamt Musterhemelingen", "Weserwehr 18", "28309", "Bremen", "HB",
                       ("Freie Hansestadt Bremen", "Steuerverwaltung"), phone="0421 555 77-10",
                       email="office@fa-musterhemelingen.bremen.example", blz="29000000", account="7710200",
                       bank="Bremer Landesmusterkasse", style="minimal", accent=(150, 20, 30))  # fmt: skip
    # N1 — HB. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    n1 = "holdout4-tax_assessment-N1"
    d = drawn(n1, AUTHORITY_DAYS, date(2026, 11, 19))
    cases.append(make(
        n1, "N", fa_hb2, S_HB, "Sehr geehrte Frau Beispielhusen,", d, d, 2025, "475/204/66190",
        [("Einkünfte aus nichtselbständiger Arbeit", 46_315), ("Werbungskosten", 2_074), ("Sonderausgaben", 7_960)],
        5_820, 6_390,
        "wir haben Ihre Einkommensteuer für 2025 festgesetzt und dabei die Angaben Ihrer Erklärung übernommen, soweit unten "
        "nichts anderes steht:",
        ["Die Beiträge zu Ihrer Berufsunfähigkeitsversicherung wirken sich nicht aus, weil der Höchstbetrag für "
         "Vorsorgeaufwendungen bereits durch die Kranken- und Pflegeversicherung ausgeschöpft ist."],
        "2026-12-23",
    ))  # fmt: skip

    fa_sl2 = authority("Finanzamt Musterlouis", "Am Gaswerk 5", "66740", "Musterlouis", "SL", ("Saarland", "Steuerverwaltung"),
                       phone="06831 555 52-0", email="poststelle@fa-musterlouis.saarland.example", blz="59000000",
                       account="5200300", bank="Saarländische Landesmusterkasse", style="authority", accent=(0, 60, 100))  # fmt: skip
    # N2 — SL. Posted Wed 18.11.2026 → day 4 = Sun 22.11. → Mon 23.11. → Wed 23.12.2026.
    n2 = "holdout4-tax_assessment-N2"
    d = drawn(n2, AUTHORITY_DAYS, date(2026, 11, 18))
    cases.append(make(
        n2, "N", fa_sl2, S_SL, "Sehr geehrter Herr Musterwadern,", d, d, 2025, "040/882/51347",
        [("Einkünfte aus nichtselbständiger Arbeit", 33_980), ("Werbungskosten", 4_102), ("Sonderausgaben", 5_244)],
        2_906, 3_571,
        "für 2025 setzen wir die Einkommensteuer fest. Gegenüber Ihrer Erklärung gibt es eine Abweichung, die wir auf der "
        "zweiten Seite erläutern:",
        ["Für die doppelte Haushaltsführung erkennen wir Unterkunftskosten bis 1.000 € im Monat an; die darüber "
         "hinausgehende Miete Ihrer Zweitwohnung ist nicht abziehbar."],
        "2026-12-23",
        case_notes="Day 4 after posting is a Sunday; the AO moves it to Monday.",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 2 — municipal_decision (a Land authority: its Land's own delivery day, no shift; Widerspruch/Klage)
# ==================================================================================================


def _land_belehrung(
    variant: str, remedy: str, org: Org, *, provision: str, day_word: str, court: str = ""
) -> list[Block]:
    where = f"{org.name}, {org.street}, {org.postcode} {org.city}"
    posting = (f"Ein Bescheid, den die Behörde mit einfachem Brief verschickt, gilt am {day_word} Tag nach der Aufgabe "
               f"zur Post als bekannt gegeben ({provision}).")  # fmt: skip
    if remedy == "klage":
        text = (f"Gegen diesen Bescheid können Sie binnen eines Monats nach seiner Bekanntgabe Klage beim {court} erheben, "
                "schriftlich oder zur Niederschrift bei der Geschäftsstelle des Gerichts. Ein Widerspruchsverfahren ist "
                "in dieser Sache nicht vorgesehen.")  # fmt: skip
    elif variant == "K":
        text = (f"Gegen diesen Bescheid können Sie innerhalb eines Monats nach seiner Bekanntgabe Widerspruch einlegen, "
                f"schriftlich oder zur Niederschrift bei der Behörde: {where}.")  # fmt: skip
    elif variant == "L":
        text = (f"Sie können gegen diese Entscheidung Widerspruch erheben. Er ist innerhalb eines Monats, nachdem Ihnen der "
                f"Bescheid bekannt gegeben worden ist, an das {where} zu richten, und zwar schriftlich oder zur "
                "Niederschrift.")  # fmt: skip
    elif variant == "M":
        text = (f"Binnen eines Monats ab der Bekanntgabe dieses Bescheids ist der Widerspruch zulässig; er wird schriftlich "
                f"oder zur Niederschrift bei folgender Stelle erhoben: {where}.")  # fmt: skip
    else:
        text = (f"Gegen den Bescheid ist der Widerspruch statthaft. Er muss innerhalb eines Monats nach Bekanntgabe "
                f"schriftlich oder zur Niederschrift beim {where} erhoben werden.")  # fmt: skip
    if variant == "K":
        return small_heading("Rechtsbehelfsbelehrung", text, posting)
    if variant == "M":
        return run_in("Rechtsbehelfsbelehrung –", text, posting)
    heading = "Ihre Rechte" if variant == "L" else "Rechtsbehelfsbelehrung"
    return page_two(heading, text, posting)


_LAND_KEY = {
    (
        "K",
        "widerspruch",
    ): "Gegen diesen Bescheid können Sie innerhalb eines Monats nach seiner Bekanntgabe Widerspruch",
    (
        "L",
        "widerspruch",
    ): "Er ist innerhalb eines Monats, nachdem Ihnen der Bescheid bekannt gegeben worden ist",
    (
        "M",
        "widerspruch",
    ): "Binnen eines Monats ab der Bekanntgabe dieses Bescheids ist der Widerspruch zulässig",
    ("N", "widerspruch"): "Er muss innerhalb eines Monats nach Bekanntgabe schriftlich",
    ("L", "klage"): "Gegen diesen Bescheid können Sie binnen eines Monats nach seiner Bekanntgabe Klage",
    ("N", "klage"): "Gegen diesen Bescheid können Sie binnen eines Monats nach seiner Bekanntgabe Klage",
}


def municipal_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, posted: date, remedy: str, subject: str,
             ref: tuple[str, str], body: list[Block], hand: str, signer: tuple[str, ...], *, provision: str,
             day_word: str = "vierten", court: str = "", began: date | None = None, extra: list[dict[str, Any]] | None = None,
             more_keys: list[str] | None = None, photo: bool = False, notes: str = "",
             extra_info: list[tuple[str, str]] | None = None) -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="vwvfg", remedy=remedy, region=org.region, procedure_began=began,
                           title="Klagefrist" if remedy == "klage" else "Widerspruchsfrist",
                           note="Remedy is Klage (no Vorverfahren): the Klage period's end is the label." if remedy == "klage" else None),
            hand,
        )  # fmt: skip
        item = tag_remedy(
            item, posted=posted, scope="vwvfg", region=org.region, began=began, klage=remedy == "klage"
        )
        if variant == "K":
            info, date_line = [ref, *(extra_info or [])], place_date(org, posted)
        elif variant == "L":
            info, date_line = [("Datum", de(posted)), ref, *(extra_info or [])], None
        elif variant == "M":
            info, date_line = [ref, *(extra_info or []), ("Bescheiddatum", de(posted))], None
        else:
            info, date_line = [ref, *(extra_info or [])], place_date(org, posted)
        belehrung = _land_belehrung(variant, remedy, org, provision=provision, day_word=day_word, court=court)
        tail: list[Block] = [*body]
        if variant in ("L", "N"):
            tail.append(P("Die Belehrung über Ihren Rechtsbehelf steht auf der Rückseite.", size=9.0))
            tail += [Sign("Mit freundlichen Grüßen", signer, signature=True), *belehrung]
        else:
            tail += [*belehrung, Sign("Mit freundlichen Grüßen", signer)]
        letter = Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation, date_line=date_line,
                        blocks=tail, style=STYLES[variant], created=created(posted), running_ref=" ".join(ref))  # fmt: skip
        return _case(
            case_id, "municipal_decision", variant, letter,
            truth(kind="authority_letter", sender=org.name, document_date=posted, references=[ref], amounts=[], remedy=remedy,
                  items=[item, *(extra or [])]),
            org.region, [de(posted), ref[1], _LAND_KEY[(variant, remedy)], *(more_keys or [])], photo=photo, notes=notes,
        )  # fmt: skip

    # K1 — MV, Widerspruch; no procedure start named, so MV's 4th day. Posted Thu 19.11.2026 → day 4 = Mon 23.11. →
    # Wed 23.12.2026. (A procedure begun before 2025 would count the 3rd day: Sun 22.11. → Tue 22.12.2026.)
    k1 = "holdout4-municipal_decision-K1"
    posted = drawn(k1, AUTHORITY_DAYS, date(2026, 11, 19))
    org = authority("Landkreis Musterpeene", "Kreishausweg 1", "17109", "Musterdemmin", "MV",
                    ("Land Mecklenburg-Vorpommern · Der Landrat", "Untere Naturschutzbehörde"), phone="03998 555 43-0",
                    email="naturschutz@lk-musterpeene.example", blz="15050400", account="4300100", style="authority",
                    accent=(0, 90, 120))  # fmt: skip
    cases.append(make(
        k1, "K", org, S_MV, "Sehr geehrte Frau Beispielrade,", posted, "widerspruch",
        "Fällung von zwei Linden auf dem Grundstück Boddenweg 11 – Ablehnung der Ausnahmegenehmigung",
        ("Aktenzeichen", "UNB-67.1-2611/26"),
        [P("Ihren Antrag, die beiden Linden an der Grundstücksgrenze zum Boddenweg fällen zu dürfen, lehne ich "
           "ab. Die Bäume stehen nach § 18 des Naturschutzausführungsgesetzes unter gesetzlichem Schutz."),
         P("Nach der Begutachtung durch unseren Baumsachverständigen am 21.10.2026 sind beide Bäume vital und standsicher. "
           "Der Laubfall und die Verschattung Ihres Gartens rechtfertigen keine Ausnahme. Einen fachgerechten Kronenschnitt "
           "können Sie ohne Genehmigung beauftragen.")],
        "2026-12-23", ("Im Auftrag", "Wendt"), provision="§ 41 Abs. 2 VwVfG M-V",
        extra_info=[("Sachbearbeitung", "Frau Wendt")],
        notes="No procedure start is named: labelled as a procedure begun after MV's switch (c03).",
    ))  # fmt: skip

    # K2 — SH, Widerspruch (photo). Posted Wed 18.11.2026 → day 4 = Sun 22.11. (no shift) → Tue 22.12.2026.
    k2 = "holdout4-municipal_decision-K2"
    posted = drawn(k2, AUTHORITY_DAYS, date(2026, 11, 18))
    org = authority("Amt Musterschlei", "Am Markt 6", "24376", "Musterkappeln", "SH",
                    ("Land Schleswig-Holstein · Der Amtsvorsteher", "Ordnungsamt"), phone="04642 555 18-0",
                    email="ordnungsamt@amt-musterschlei.example", blz="21690000", account="1800400", style="band",
                    accent=(0, 80, 120))  # fmt: skip
    cases.append(make(
        k2, "K", org, S_SH, "Sehr geehrter Herr Beispielholm,", posted, "widerspruch",
        "Antrag auf Erlaubnis für ein Brauchtumsfeuer am Strand – Ablehnung", ("Geschäftszeichen", "OA 32-118/26"),
        [P("das beantragte Feuer zum Jahreswechsel auf dem Strandabschnitt vor dem Knickweg kann ich nicht erlauben. Der "
           "Abschnitt liegt im Landschaftsschutzgebiet „Musterschlei-Ufer“, und die Brutplätze im angrenzenden Röhricht "
           "dürfen nicht gestört werden."),
         P("Auf dem Festplatz am Hafen richtet die Gemeinde ein gemeinsames Feuer aus; dort können Sie sich beteiligen.")],
        "2026-12-22", ("Im Auftrag", "Carstensen"), provision="§ 110 Abs. 2 LVwG", photo=True,
        notes="The deemed-delivery day is a Sunday; outside tax law it does not move.",
    ))  # fmt: skip

    # L1 — BY, Klage (no Vorverfahren) and a removal date; no procedure start named, so the 4th day. Posted Wed 18.11.2026
    # → day 4 = Sun 22.11. (no shift) → Tue 22.12.2026. Removal by Fri 26.02.2027.
    l1 = "holdout4-municipal_decision-L1"
    posted = drawn(l1, AUTHORITY_DAYS, date(2026, 11, 18))
    removal = date(2027, 2, 26)
    org = authority("Landratsamt Beispielrott", "Rottaler Platz 2", "84347", "Beispielkirchen am Rott", "BY",
                    ("Freistaat Bayern", "Untere Bauaufsichtsbehörde"), phone="08561 555 20-0",
                    email="bauaufsicht@lra-beispielrott.bayern.example", blz="74351000", account="2000700",
                    bank="Sparkasse Muster-Rottal", style="logo", monogram="LR", accent=(0, 85, 150))  # fmt: skip
    task = check(
        fixed_item(due=removal, region="BY", kind="task", nature="other", title="Wohnwagen und Holzanbau vom Grundstück entfernen",
                   rule="Compliance date set by the authority as a calendar date."),
        "2027-02-26",
    )  # fmt: skip
    cases.append(make(
        l1, "L", org, S_BY, "Sehr geehrte Frau Musterreiter,", posted, "klage",
        "Baurecht; Beseitigung eines dauerhaft abgestellten Wohnwagens mit Holzanbau, Fl.-Nr. 412/3 Gemarkung Beispielrott",
        ("Az.", "BV-61-2026-0773"),
        [P("Das Landratsamt Beispielrott erlässt folgenden Bescheid:"),
         P(f"1. Sie haben den auf dem Grundstück Fl.-Nr. 412/3 abgestellten Wohnwagen samt dem angebauten Holzvorbau bis "
           f"spätestens {de(removal)} zu entfernen.", indent=4),
         P("2. Für den Fall, dass Sie Nr. 1 nicht rechtzeitig erfüllen, wird ein Zwangsgeld von 2.000 € angedroht.", indent=4),
         P("Gründe: Der Wohnwagen steht seit mindestens Frühjahr 2026 ununterbrochen auf der Wiese und wird mit dem Anbau als "
           "Wochenendunterkunft genutzt. Das Grundstück liegt im Außenbereich; eine Genehmigung kann nicht erteilt werden. Die "
           "Anordnung stützt sich auf Art. 76 Satz 1 BayBO. Ihre Stellungnahme im Anhörungsverfahren haben wir berücksichtigt.")],
        "2026-12-22", ("Bauer", "Oberregierungsrätin"), provision="Art. 41 Abs. 2 BayVwVfG",
        court="Bayerischen Verwaltungsgericht Musterregensburg, Haidplatz 4, 93047 Musterregensburg",
        extra=[tag_plain(task, "c01", "c04")], more_keys=[de(removal)],
        notes="No procedure start before 2025 is named, so BY's 4th day; day 4 is a Sunday and does not move.",
    ))  # fmt: skip

    # L2 — HH, Widerspruch. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    l2 = "holdout4-municipal_decision-L2"
    posted = drawn(l2, AUTHORITY_DAYS, date(2026, 11, 19))
    org = authority("Bezirksamt Musterwerder", "Wasserturmweg 3", "22089", "Hamburg", "HH",
                    ("Freie und Hansestadt Hamburg", "Fachamt Management des öffentlichen Raumes"), phone="040 555 732-0",
                    email="sondernutzung@musterwerder.hamburg.example", blz="20000000", account="7320400",
                    bank="Hamburger Landesmusterkasse", style="minimal", accent=(180, 20, 30))  # fmt: skip
    cases.append(make(
        l2, "L", org, S_HH, "Sehr geehrte Frau Beispielfleet,", posted, "widerspruch",
        "Sondernutzung des Gehwegs vor Kanalstraße 70 für zwei Tische und vier Stühle – Versagung",
        ("Vorgangsnummer", "SN-W/2026/1184"),
        [P("für Ihr Café möchten Sie auf dem Gehweg vor dem Haus Kanalstraße 70 zwei Tische mit vier Stühlen aufstellen. Die "
           "dafür nötige Sondernutzungserlaubnis nach dem Hamburgischen Wegegesetz kann ich leider nicht erteilen."),
         P("Der Gehweg ist an dieser Stelle nur 2,10 m breit. Mit der Möblierung bliebe für Fußgänger, Rollstühle und "
           "Kinderwagen weniger als die erforderliche Restbreite von 1,50 m. Eine Erlaubnis für einen Tisch an der Hauswand "
           "käme in Betracht; dafür genügt ein formloser neuer Antrag.")],
        "2026-12-23", ("Im Auftrag", "Petersen"), provision="§ 41 Abs. 2 HmbVwVfG",
    ))  # fmt: skip

    # M1 — MV, Widerspruch; no procedure start named, so MV's 4th day. Posted Thu 19.11.2026 → day 4 = Mon 23.11. →
    # Wed 23.12.2026. (A procedure begun before 2025 would count the 3rd day: Sun 22.11. → Tue 22.12.2026.)
    m1 = "holdout4-municipal_decision-M1"
    posted = drawn(m1, AUTHORITY_DAYS, date(2026, 11, 19))
    org = authority("Hansestadt Beispielwismar", "Am Markt 1", "23966", "Beispielwismar", "MV",
                    ("Land Mecklenburg-Vorpommern · Die Bürgermeisterin", "Untere Denkmalschutzbehörde"),
                    phone="03841 555 25-0", email="denkmalschutz@beispielwismar.example", blz="14051000", account="2500100",
                    style="logo", monogram="HB", accent=(130, 20, 30))  # fmt: skip
    cases.append(make(
        m1, "M", org, S_MV, "Sehr geehrte Frau Beispielrade,", posted, "widerspruch",
        "Denkmalrechtliche Genehmigung für neue Fenster im Haus Lübsche Straße 14 – teilweise Versagung",
        ("Aktenzeichen", "DS 63-4471/26"),
        [P("die Fenster im Erdgeschoss Ihres Hauses dürfen Sie wie beantragt durch Holzfenster mit Sprossenteilung ersetzen. "
           "Für die vier Fenster im Obergeschoss versage ich die Genehmigung, soweit Sie Kunststoffrahmen einbauen möchten."),
         P("Das Haus ist ein Einzeldenkmal im Welterbebereich der Altstadt. Kunststoffrahmen würden das überlieferte "
           "Erscheinungsbild der Straßenfassade beeinträchtigen. Für Holzfenster gewähren wir auf Antrag einen Zuschuss.")],
        "2026-12-23", ("In Vertretung", "Dr. Kröger"), provision="§ 41 Abs. 2 VwVfG M-V",
        notes="No procedure start is named: labelled as a procedure begun after MV's switch (c03).",
    ))  # fmt: skip

    # M2 — SH, Widerspruch (photo). Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    m2 = "holdout4-municipal_decision-M2"
    posted = drawn(m2, AUTHORITY_DAYS, date(2026, 11, 19))
    org = authority("Kreis Musterdithmarschen", "Stiftstraße 8", "25746", "Musterheide in Holstein", "SH",
                    ("Land Schleswig-Holstein · Der Landrat", "Fachdienst Waffen und Jagd"), phone="0481 555 97-0",
                    email="waffenbehoerde@kreis-musterdithmarschen.example", blz="21851800", account="9700300",
                    style="authority", accent=(0, 70, 110))  # fmt: skip
    cases.append(make(
        m2, "M", org, S_SH, "Sehr geehrter Herr Beispielholm,", posted, "widerspruch",
        "Antrag auf Erteilung eines Jagdscheins für drei Jahre – Ablehnung", ("Az.", "WJ-32.4-0912/26"),
        [P("einen Jagdschein kann ich Ihnen zurzeit nicht erteilen. Nach § 17 Abs. 1 Satz 2 des Bundesjagdgesetzes setzt er "
           "eine Jagdhaftpflichtversicherung voraus. Der Nachweis, den Sie vorgelegt haben, ist am 30.06.2026 abgelaufen."),
         P("Sobald Sie eine gültige Versicherungsbestätigung nachreichen, stelle ich den Jagdschein ohne neuen Antrag aus.")],
        "2026-12-23", ("Im Auftrag", "Rohwedder"), provision="§ 110 Abs. 2 LVwG", photo=True,
    ))  # fmt: skip

    # N1 — BY, Klage; no procedure start named, so BY's 4th day. Posted Wed 18.11.2026 → day 4 = Sun 22.11. (no shift) →
    # Tue 22.12.2026. (A procedure begun before 2025 would count the 3rd day: Sat 21.11. → Mon 21.12.2026.)
    n1 = "holdout4-municipal_decision-N1"
    posted = drawn(n1, AUTHORITY_DAYS, date(2026, 11, 18))
    org = authority("Landratsamt Musterinn", "Innkai 11", "94032", "Beispielpassau", "BY",
                    ("Freistaat Bayern", "Bauamt – Untere Bauaufsichtsbehörde"), phone="0851 555 39-0",
                    email="bauamt@lra-musterinn.bayern.example", blz="74050000", account="3900200",
                    bank="Sparkasse Muster-Passau", style="authority", accent=(0, 100, 170),
                    hours=("Sprechzeiten:", "Mo–Fr 8–12 Uhr", "Do 14–17 Uhr"))  # fmt: skip
    cases.append(make(
        n1, "N", org, S_BY, "Sehr geehrte Frau Musterreiter,", posted, "klage",
        "Bauantrag: Errichtung eines Carports mit Geräteraum, Fl.-Nr. 88/14 Gemarkung Musterinn – Ablehnung",
        ("Az.", "B-2026-1406"),
        [P("Ihr Bauantrag für einen Carport mit Geräteraum wird abgelehnt."),
         P("Nach dem Gutachten zur Hochwassergefahr liegt der geplante Standort im festgesetzten Überschwemmungsgebiet des "
           "Inns. Dort dürfen bauliche Anlagen nur ausnahmsweise zugelassen werden (§ 78 Abs. 5 WHG). Die Voraussetzungen "
           "liegen nicht vor: Der Carport mit geschlossenem Geräteraum würde Rückhalteraum verbrauchen, ohne dass ein "
           "Ausgleich vorgesehen ist."),
         P("Für die Ablehnung wird eine Gebühr von 120 € erhoben; hierüber erhalten Sie einen eigenen Kostenbescheid.")],
        "2026-12-22", ("Gruber", "Regierungsamtmann"), provision="Art. 41 Abs. 2 BayVwVfG",
        court="Bayerischen Verwaltungsgericht Musterregensburg, Haidplatz 4, 93047 Musterregensburg",
        more_keys=["Ihr Bauantrag für einen Carport mit Geräteraum wird abgelehnt."],
        notes="No procedure start is named: labelled as a procedure begun after BY's switch (c03); day 4 is a Sunday and does not move.",
    ))  # fmt: skip

    # N2 — HH, Widerspruch. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    n2 = "holdout4-municipal_decision-N2"
    posted = drawn(n2, AUTHORITY_DAYS, date(2026, 11, 19))
    org = authority("Bezirksamt Beispielbek", "Marktplatz am Bach 1", "22081", "Hamburg", "HH",
                    ("Freie und Hansestadt Hamburg", "Fachamt Verbraucherschutz, Gewerbe und Umwelt"), phone="040 555 619-0",
                    email="gewerbe@beispielbek.hamburg.example", blz="20000000", account="6190100",
                    bank="Hamburger Landesmusterkasse", style="band", accent=(160, 25, 35))  # fmt: skip
    cases.append(make(
        n2, "N", org, S_HH, "Sehr geehrte Frau Beispielfleet,", posted, "widerspruch",
        "Antrag auf Verlängerung der Sperrzeit-Ausnahme für das Café „Fleetblick“ – Ablehnung",
        ("Geschäftszeichen", "VS 22/0619-26"),
        [P("Sie haben beantragt, Ihr Café an Freitagen und Samstagen bis 2 Uhr nachts öffnen zu dürfen. Diesem Antrag kann ich "
           "nicht entsprechen."),
         P("In den vergangenen Monaten haben Anwohner wiederholt Lärmbeschwerden über Gäste vor dem Lokal erhoben; die Polizei "
           "musste dreimal einschreiten. Eine Verlängerung der Öffnung würde die Nachtruhe der Nachbarschaft weiter stören.")],
        "2026-12-23", ("Im Auftrag", "Lüders"), provision="§ 41 Abs. 2 HmbVwVfG",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 3 — social_decision (SGB X: the fourth day, no shift; one month)
# ==================================================================================================


def _sgb_belehrung(variant: str, org: Org, address: str) -> tuple[list[Block], str]:
    if variant == "K":
        text = (f"Gegen diesen Bescheid können Sie innerhalb eines Monats, nachdem er Ihnen bekannt gegeben wurde, "
                f"Widerspruch erheben. Richten Sie ihn schriftlich oder zur Niederschrift an: {address}.")  # fmt: skip
        posting = "Schicken wir Ihnen den Bescheid mit der Post, ist er am vierten Tag nach dem Absenden bekannt gegeben (§ 37 Abs. 2 SGB X)."
        return small_heading(
            "Rechtsbehelfsbelehrung", text, posting
        ), "innerhalb eines Monats, nachdem er Ihnen bekannt gegeben wurde"
    if variant == "L":
        text = (f"Wenn Sie mit dieser Entscheidung nicht einverstanden sind, steht Ihnen der Widerspruch offen. Er muss "
                f"innerhalb eines Monats nach Bekanntgabe des Bescheids bei uns eingehen ({address}); Sie können ihn "
                "schriftlich einreichen oder bei uns zur Niederschrift erklären.")  # fmt: skip
        posting = "Ein Bescheid, den wir per Post versenden, gilt am vierten Tag nach seiner Aufgabe zur Post als bekannt gegeben."
        return page_two(
            "Was Sie tun können", text, posting
        ), "Er muss innerhalb eines Monats nach Bekanntgabe des Bescheids bei uns eingehen"
    if variant == "M":
        text = (f"Innerhalb eines Monats ab Bekanntgabe kann gegen diesen Bescheid Widerspruch erhoben werden, schriftlich "
                f"oder zur Niederschrift bei: {address}. Bei Versand mit der Post ist der Bescheid am vierten Tag nach der "
                "Aufgabe zur Post bekannt gegeben.")  # fmt: skip
        return run_in(
            "Rechtsbehelfsbelehrung:", text
        ), "Innerhalb eines Monats ab Bekanntgabe kann gegen diesen Bescheid Widerspruch"
    text = (f"Gegen diese Entscheidung ist der Widerspruch zulässig. Die Frist dafür beträgt einen Monat ab Bekanntgabe; "
            f"der Widerspruch ist schriftlich oder zur Niederschrift bei {address} einzulegen.")  # fmt: skip
    posting = "Bekannt gegeben ist ein Bescheid, den wir mit einfachem Brief schicken, am vierten Tag nach dem Versand (§ 37 Abs. 2 SGB X)."
    return page_two(
        "Rechtsbehelfsbelehrung", text, posting
    ), "Die Frist dafür beträgt einen Monat ab Bekanntgabe"


def social_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, posted: date, kind: str, subject: str,
             refs: list[tuple[str, str]], body: list[Block], hand: str, closing: tuple[str, ...], *,
             amounts: list[float] | None = None, extra: list[dict[str, Any]] | None = None, more_keys: list[str] | None = None,
             rule: str | None = None, shift_citation: str | None = None, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="sgbx", remedy="widerspruch", region=org.region, title="Widerspruchsfrist",
                           rule=rule, shift_citation=shift_citation),
            hand,
        )  # fmt: skip
        item = tag_remedy(item, posted=posted, scope="sgbx", region=org.region)
        belehrung, key = _sgb_belehrung(variant, org, f"{org.name}, {org.street}, {org.postcode} {org.city}")
        if variant == "K":
            info, date_line = list(refs), place_date(org, posted)
        elif variant == "L":
            info, date_line = [("Datum", de(posted)), *refs], None
        elif variant == "M":
            info, date_line = [*refs, ("Bescheid vom", de(posted))], None
        else:
            info, date_line = list(refs), place_date(org, posted)
        if variant in ("L", "N"):
            blocks = [*body, P("Auf der zweiten Seite erfahren Sie, wie Sie Widerspruch einlegen können.", size=9.0),
                      Sign("Mit freundlichen Grüßen", closing), *belehrung]  # fmt: skip
        else:
            blocks = [*body, *belehrung, Sign("Mit freundlichen Grüßen", closing)]
        letter = Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation, date_line=date_line,
                        blocks=blocks, style=STYLES[variant], created=created(posted), running_ref=" ".join(refs[0]))  # fmt: skip
        return _case(
            case_id, "social_decision", variant, letter,
            truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts or [], remedy="widerspruch",
                  items=[item, *(extra or [])]),
            org.region, [de(posted), key, *(more_keys or [])], photo=photo, notes=notes,
        )  # fmt: skip

    # K1 — Krankenkasse, Land unknown. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    k1 = "holdout4-social_decision-K1"
    posted = drawn(k1, AUTHORITY_DAYS, date(2026, 11, 19))
    org = authority("Musterquell Krankenkasse", "Am Brunnenhof 2", "35390", "Mustergießen", None,
                    ("Gesetzliche Krankenversicherung (Musterausgabe)", "Leistungen bei Krankheit"), phone="0641 555 830-0",
                    email="leistung@musterquell-kk.example", blz="51350025", account="8300100", kind="health_insurer",
                    style="logo", monogram="MQ", accent=(0, 110, 100), legal=("Körperschaft des öffentlichen Rechts",))  # fmt: skip
    cases.append(make(
        k1, "K", org, S_GEN, "Sehr geehrter Herr Musterquell,", posted, "health_insurance",
        "Ihr Antrag auf Haushaltshilfe während der Reha Ihrer Frau", [("Versichertennummer", "Q803116452")],
        [P("Sie haben beantragt, dass wir während der dreiwöchigen Rehabilitation Ihrer Frau eine Haushaltshilfe bezahlen. "
           "Diesen Antrag müssen wir ablehnen."),
         P("Eine Haushaltshilfe nach § 38 SGB V kommt nur in Betracht, wenn im Haushalt ein Kind lebt, das jünger als zwölf "
           "Jahre ist, oder wenn die versicherte Person selbst den Haushalt wegen ihrer Erkrankung nicht führen kann. Ihre "
           "Kinder sind 14 und 16 Jahre alt, und Sie selbst sind nicht erkrankt.")],
        "2026-12-23", ("Ihre Musterquell Krankenkasse", "Team Leistungen"),
    ))  # fmt: skip

    # K2 — Unfallkasse, Land unknown (photo). Posted Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026.
    k2 = "holdout4-social_decision-K2"
    posted = drawn(k2, AUTHORITY_DAYS, date(2026, 11, 20))
    org = authority("Unfallkasse Beispiel-Mitte", "Präventionsweg 9", "34117", "Musterkassel", None,
                    ("Gesetzliche Unfallversicherung (Musterausgabe)", "Abteilung Rehabilitation und Entschädigung"),
                    phone="0561 555 70-0", email="reha@uk-beispiel-mitte.example", blz="52050000", account="7000300",
                    style="band", accent=(0, 85, 60), legal=("Körperschaft des öffentlichen Rechts",))  # fmt: skip
    cases.append(make(
        k2, "K", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", posted, "social_insurance",
        "Ihr Sturz auf dem Schulweg Ihres Sohnes am 14.09.2026 – Anerkennung als Arbeitsunfall",
        [("Aktenzeichen", "UK 26/41187-S")],
        [P("den Unfall Ihres Sohnes Paul am 14.09.2026 erkennen wir als Arbeitsunfall an. Paul ist auf dem direkten Weg zur "
           "Grundschule mit dem Fahrrad gestürzt; Schulwege sind nach § 8 Abs. 2 SGB VII versichert."),
         P("Wir übernehmen die Kosten der ärztlichen Behandlung und der Physiotherapie. Rechnungen schicken die Praxen direkt "
           "an uns; bitte reichen Sie selbst keine Belege ein.")],
        "2026-12-24", ("Unfallkasse Beispiel-Mitte",), photo=True,
    ))  # fmt: skip

    # L1 — Wohngeld, BB, with a submission date. Posted Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026. Documents by
    # Mon 11.01.2027.
    l1 = "holdout4-social_decision-L1"
    posted = drawn(l1, AUTHORITY_DAYS, date(2026, 11, 20))
    submit = date(2027, 1, 11)
    org = authority("Landkreis Musterspree-Neiße", "Amtsplatz 3", "15848", "Beispielkow", "BB",
                    ("Land Brandenburg · Landkreis Musterspree-Neiße", "Wohngeldstelle"), phone="03366 555 35-0",
                    email="wohngeld@lk-musterspree-neisse.example", blz="17055050", account="3500200",
                    style="authority", accent=(170, 30, 40))  # fmt: skip
    task = check(
        fixed_item(due=submit, region="BB", kind="task", nature="declaration", title="Neue Lohnabrechnungen einreichen",
                   rule="Submission date set by the authority as a calendar date."),
        "2027-01-11",
    )  # fmt: skip
    cases.append(make(
        l1, "L", org, S_BB, "Sehr geehrter Herr Musterspree,", posted, "social_insurance",
        "Bescheid über Wohngeld für die Zeit vom 01.12.2026 bis 30.11.2027", [("Wohngeldnummer", "WG-2026-07415")],
        [P("auf Ihren Antrag bewilligen wir Ihnen für den genannten Zeitraum einen Mietzuschuss von **226,00 € im Monat**. "
           "Berücksichtigt sind drei Haushaltsmitglieder, eine Bruttokaltmiete von 690,00 € und das Einkommen aus Ihrer "
           "Beschäftigung als Lagerist."),
         P(f"Ihr Arbeitgeber hat Ihnen ab Januar mehr Stunden angekündigt. Legen Sie uns bitte **bis zum {de(submit)}** die "
           "Lohnabrechnungen für November und Dezember 2026 vor, damit wir prüfen können, ob sich das Wohngeld ändert.")],
        "2026-12-24", ("Im Auftrag", "Schulze, Wohngeldstelle"), amounts=[226.0],
        extra=[tag_plain(task, "c01", "c04")], more_keys=[de(submit)],
        rule="Widerspruch against a Wohngeld decision: one month after Bekanntgabe (§ 70 Abs. 1 VwGO); Wohngeld is a social "
             "benefit (§ 68 Nr. 10 SGB I), so its deemed delivery follows § 37 Abs. 2 SGB X.",
        shift_citation="§ 57 Abs. 2 VwGO i.V.m. § 222 Abs. 2 ZPO; § 26 Abs. 3 SGB X via § 62 SGB X",
    ))  # fmt: skip

    # L2 — Unterhaltsvorschuss, RP. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    l2 = "holdout4-social_decision-L2"
    posted = drawn(l2, AUTHORITY_DAYS, date(2026, 11, 19))
    org = authority("Kreisverwaltung Musterhunsrück", "Schlossplatz 7", "55469", "Musterbach im Hunsrück", "RP",
                    ("Land Rheinland-Pfalz", "Jugendamt – Unterhaltsvorschusskasse"), phone="06761 555 82-0",
                    email="uvg@kv-musterhunsrueck.example", blz="56050180", account="8200400",
                    style="minimal", accent=(120, 30, 80))  # fmt: skip
    cases.append(make(
        l2, "L", org, S_RP, "Sehr geehrte Frau Beispielsteiner,", posted, "social_insurance",
        "Unterhaltsvorschuss für Ihre Tochter Marie", [("Aktenzeichen", "UV 51-2207/26")],
        [P("für Ihre Tochter Marie zahlen wir ab dem 01.11.2026 Unterhaltsvorschuss nach dem Unterhaltsvorschussgesetz in "
           "Höhe von **293,00 € monatlich**. Das ist der Mindestunterhalt der zweiten Altersstufe abzüglich des vollen "
           "Kindergeldes."),
         P("Den Anspruch Ihrer Tochter gegen ihren Vater machen wir selbst geltend. Teilen Sie uns bitte sofort mit, wenn er "
           "Unterhalt an Sie zahlt oder Sie umziehen.")],
        "2026-12-23", ("Im Auftrag", "Weiler"), amounts=[293.0],
        rule="Widerspruch against a UVG decision: one month after Bekanntgabe (§ 70 Abs. 1 VwGO); as a social benefit "
             "(§ 68 Nr. 14 SGB I) its deemed delivery follows § 37 Abs. 2 SGB X.",
        shift_citation="§ 57 Abs. 2 VwGO i.V.m. § 222 Abs. 2 ZPO; § 26 Abs. 3 SGB X via § 62 SGB X",
    ))  # fmt: skip

    # M1 — Pflegekasse, Land unknown. Posted Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026.
    m1 = "holdout4-social_decision-M1"
    posted = drawn(m1, AUTHORITY_DAYS, date(2026, 11, 20))
    org = authority("Pflegekasse bei der Musterquell Krankenkasse", "Am Brunnenhof 2", "35390", "Mustergießen", None,
                    ("Soziale Pflegeversicherung (Musterausgabe)", "Team Pflegegrade"), phone="0641 555 830-40",
                    email="pflege@musterquell-kk.example", blz="51350025", account="8300400", kind="health_insurer",
                    style="logo", monogram="MQ", accent=(0, 110, 100), legal=("Körperschaft des öffentlichen Rechts",))  # fmt: skip
    cases.append(make(
        m1, "M", org, S_GEN, "Sehr geehrter Herr Musterquell,", posted, "health_insurance",
        "Pflegegrad Ihrer Mutter, Frau Edith Musterquell", [("Versichertennummer", "Q441902737")],
        [P("nach dem Gutachten des Medizinischen Dienstes vom 03.11.2026 stufen wir Ihre Mutter ab dem 01.10.2026 in den "
           "**Pflegegrad 3** ein. Sie erhält damit monatlich ein Pflegegeld von **599,00 €**, solange Sie und Ihre Schwester "
           "die Pflege zu Hause übernehmen."),
         P("Das Gutachten liegt bei. Wenn Sie stattdessen einen Pflegedienst beauftragen, rechnet er direkt mit uns ab.")],
        "2026-12-24", ("Ihre Pflegekasse",), amounts=[599.0],
    ))  # fmt: skip

    # M2 — Familienkasse, Kinderzuschlag, Land unknown (photo). Posted Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026.
    m2 = "holdout4-social_decision-M2"
    posted = drawn(m2, AUTHORITY_DAYS, date(2026, 11, 20))
    org = authority("Familienkasse Musterlahn", "Bahnhofsallee 40", "35576", "Beispielwetzlar", None,
                    ("Familienkasse (Musterausgabe)", "Kinderzuschlag nach dem BKGG"), phone="0800 555 4590",
                    email="familienkasse-musterlahn@arbeitsagentur.example", blz="50000000", account="4590100",
                    style="authority", accent=(170, 20, 30))  # fmt: skip
    cases.append(make(
        m2, "M", org, S_GEN2, "Sehr geehrte Frau Beispielacker,", posted, "social_insurance",
        "Kinderzuschlag ab Dezember 2026", [("Kindergeldnummer", "214FK880153")],
        [P("für Ihre Kinder Ida und Jonas bewilligen wir Ihnen von Dezember 2026 bis Mai 2027 Kinderzuschlag von je "
           "**297,00 €** im Monat. Grundlage sind Ihr Einkommen der letzten sechs Monate und Ihre Wohnkosten."),
         P("Mit dem Bescheid erhalten Sie Leistungen für Bildung und Teilhabe; den Antrag dafür stellen Sie bei Ihrer Kommune.")],
        "2026-12-24", ("Ihre Familienkasse",), amounts=[297.0], photo=True,
        rule="Widerspruch against a Kinderzuschlag decision: one month after Bekanntgabe (§ 84 Abs. 1 SGG); the BKGG is part of "
             "the SGB (§ 68 Nr. 9 SGB I), so § 37 Abs. 2 SGB X applies.",
    ))  # fmt: skip

    # N1 — Jobcenter BB, with a submission date. Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026. Documents by
    # Fri 08.01.2027.
    n1 = "holdout4-social_decision-N1"
    posted = drawn(n1, AUTHORITY_DAYS, date(2026, 11, 19))
    submit = date(2027, 1, 8)
    org = authority("Jobcenter Beispiel-Oderland", "Seelower Weg 12", "15344", "Musterstrausberg", "BB",
                    ("Land Brandenburg · Landkreis Beispiel-Oderland", "Grundsicherung für Arbeitsuchende"),
                    phone="03341 555 64-0", email="jobcenter@beispiel-oderland.example", blz="17054040", account="6400100",
                    style="logo", monogram="JO", accent=(150, 35, 45))  # fmt: skip
    task = check(
        fixed_item(due=submit, region="BB", kind="task", nature="declaration", title="Nebenkostenabrechnung vorlegen",
                   rule="Submission date set by the authority as a calendar date."),
        "2027-01-08",
    )  # fmt: skip
    cases.append(make(
        n1, "N", org, S_BB, "Sehr geehrter Herr Musterspree,", posted, "social_insurance",
        "Bürgergeld – Bewilligung für Dezember 2026 bis November 2027", [("BG-Nummer", "12603//0441897")],
        [P("wir bewilligen Ihnen Bürgergeld für die Zeit vom 01.12.2026 bis 30.11.2027. Ihr monatlicher Anspruch beträgt "
           "**1.041,30 €**; darin sind 478,30 € für Unterkunft und Heizung enthalten."),
         P(f"Für die Heizkosten berücksichtigen wir vorläufig die bisherigen Abschläge. Bitte reichen Sie die "
           f"Nebenkostenabrechnung Ihres Vermieters für 2025 **bis {de(submit)}** ein.")],
        "2026-12-23", ("Im Auftrag", "Lehmann"), amounts=[1041.30],
        extra=[tag_plain(task, "c01", "c04")], more_keys=[de(submit)],
    ))  # fmt: skip

    # N2 — Grundsicherung, RP. Posted Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026.
    n2 = "holdout4-social_decision-N2"
    posted = drawn(n2, AUTHORITY_DAYS, date(2026, 11, 20))
    org = authority("Kreisverwaltung Beispiel-Westerwald", "Peter-Altmeier-Platz 2", "56410", "Musterbaur", "RP",
                    ("Land Rheinland-Pfalz", "Sozialamt – Grundsicherung im Alter"), phone="02602 555 12-0",
                    email="grundsicherung@kv-beispiel-westerwald.example", blz="57050120", account="1200300",
                    style="band", accent=(110, 40, 90))  # fmt: skip
    cases.append(make(
        n2, "N", org, S_RP, "Sehr geehrte Frau Beispielsteiner,", posted, "social_insurance",
        "Grundsicherung im Alter ab 01.12.2026", [("Aktenzeichen", "50.2-GS-3318")],
        [P("auf Ihren Antrag bewilligen wir Ihnen Grundsicherung im Alter nach dem Zwölften Buch Sozialgesetzbuch. Ab "
           "Dezember 2026 zahlen wir Ihnen monatlich **412,64 €**."),
         P("Ihre Altersrente von 768,36 € haben wir als Einkommen angerechnet. Die Miete für Ihre Wohnung übernehmen wir in "
           "voller Höhe, weil sie angemessen ist.")],
        "2026-12-24", ("Im Auftrag", "Hoffmann"), amounts=[412.64],
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 7 — fine_bussgeld (OWiG: Einspruch two weeks after Zustellung, § 67 OWiG, § 43 StPO)
# ==================================================================================================


def _fine_days(case_id: str, letter: date, served: date) -> tuple[date, date]:
    """The Bescheid's date (Wed–Fri) and its Zustellung (a later day up to ``TODAY``, no Sunday), drawn in that order."""
    rng = rng_for(SPLIT, case_id)
    d = rng.choice(AUTHORITY_DAYS)
    s = rng.choice([date(2026, 11, n) for n in range(d.day + 1, TODAY.day + 1) if n != 22])
    assert (d, s) == (letter, served), (case_id, d, s)
    return d, s


def fine_bussgeld() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, letter_date: date, served: date, plate: str, when: str,
             place: str, charge: str, rules: str, fine: float, points: int, hand: str, az: str, note: str,
             initials: str) -> Case:  # fmt: skip
        objection = check(
            event_period_item(
                event=served, amount=2, unit="weeks", region=org.region, kind="deadline", nature="objection",
                title="Einspruchsfrist Bußgeldbescheid", anchor="explicit_date",
                rule="Einspruch against a Bußgeldbescheid: two weeks after Zustellung (§ 67 Abs. 1 OWiG); Zustellung by "
                     "Postzustellungsurkunde on the day noted on the envelope (§ 180 ZPO); computation § 43 StPO i.V.m. § 46 Abs. 1 OWiG.",
                shift_citation="§ 43 Abs. 2 StPO i.V.m. § 46 Abs. 1 OWiG",
            ),
            hand,
        )  # fmt: skip
        fee, costs = 28.50, 3.50
        total = round(fine + fee + costs, 2)
        payment = undated_item(
            kind="payment", nature="payment", title="Geldbuße und Kosten zahlen", amount=total,
            spec=spec("relative", anchor="explicit_date", amount=2, unit="weeks", shift=True),
            derivation="Payable two weeks after the Bußgeldbescheid becomes final (Rechtskraft); the date depends on whether an "
                       "Einspruch is filed, so it is not date-scored.",
        )  # fmt: skip
        register = (f"Im Fahreignungsregister wird der Verstoß mit {points} Punkt vermerkt." if points
                    else "Eine Eintragung im Fahreignungsregister erfolgt nicht.")  # fmt: skip
        table = Table(rows=(("Geldbuße", eur_plain(fine)), ("Gebühr (§ 107 Abs. 1 OWiG)", eur_plain(fee)),
                            ("Auslagen für die Zustellung", eur_plain(costs)), ("Gesamtbetrag", eur_plain(total))),
                      header=("Festgesetzt", "Euro"), bold_rows=(3,), rule_before=(3,), value_width=30)  # fmt: skip
        refs = [("Aktenzeichen", az), ("Kennzeichen", plate)]
        if variant == "K":
            info, date_line = list(refs), place_date(org, letter_date)
            blocks: list[Block] = [
                P(f"Ihnen wird vorgeworfen, am {when} in {place} mit dem Kraftfahrzeug {plate} folgende Ordnungswidrigkeit "
                  f"begangen zu haben: {charge}"),
                P(f"Maßgebliche Vorschriften: {rules}", size=8.4),
                table,
                P(f"{register} Zahlen Sie erst, wenn dieser Bescheid rechtskräftig geworden ist, und dann binnen zwei Wochen "
                  f"auf das Konto {iban_grouped(org.iban)}."),
                *small_heading("Rechtsbehelfsbelehrung",
                               "Gegen diesen Bescheid können Sie innerhalb von zwei Wochen ab seiner Zustellung Einspruch "
                               f"einlegen, schriftlich oder zur Niederschrift {bei(org.name)}. Ohne Einspruch wird der "
                               "Bescheid rechtskräftig und kann vollstreckt werden."),
            ]  # fmt: skip
            key = "innerhalb von zwei Wochen ab seiner Zustellung Einspruch"
        elif variant == "L":
            info, date_line = [("Datum", de(letter_date)), *refs], None
            blocks = [
                Table(rows=(("Tag und Uhrzeit", when), ("Ort", place), ("Fahrzeug", plate)), header=("Tatvorwurf", ""),
                      value_width=116, value_align="L", size=8.6),
                P(charge),
                P(f"Angewandte Bestimmungen: {rules}", size=8.4),
                table,
                P(f"{register} Der Gesamtbetrag ist zwei Wochen nach Eintritt der Rechtskraft zu zahlen."),
                H("Belehrung", size=9.6),
                P("Sie können gegen den Bußgeldbescheid Einspruch einlegen. Die Frist von zwei Wochen beginnt mit dem Tag der "
                  f"Zustellung. Der Einspruch ist {bei(org.name)} schriftlich oder zur Niederschrift einzulegen.", size=8.7),
            ]  # fmt: skip
            key = "Die Frist von zwei Wochen beginnt mit dem Tag der Zustellung"
        elif variant == "M":
            info, date_line = [*refs, ("Erlassen", de(letter_date))], None
            blocks = [
                P(f"Sie haben am {when} in {place} als Führer des Fahrzeugs {plate} eine Verkehrsordnungswidrigkeit begangen. "
                  f"{charge}"),
                P(f"Vorschriften: {rules}", size=8.4),
                table,
                P(f"{register} Bitte überweisen Sie den Gesamtbetrag erst nach Rechtskraft, und zwar innerhalb von zwei "
                  "Wochen."),
                *run_in("Rechtsbehelfsbelehrung:",
                        "Binnen zwei Wochen nach der Zustellung dieses Bescheids kann Einspruch eingelegt werden, schriftlich "
                        f"oder zur Niederschrift {bei(org.name)}. Danach wird der Bescheid rechtskräftig."),
            ]  # fmt: skip
            key = "Binnen zwei Wochen nach der Zustellung dieses Bescheids kann Einspruch eingelegt werden"
        else:
            info, date_line = list(refs), place_date(org, letter_date)
            blocks = [
                Table(rows=(("Tatzeit", when), ("Tatort", place), ("Kennzeichen", plate)), header=("Zur Sache", ""),
                      value_width=116, value_align="L", size=8.6),
                P(f"Vorwurf: {charge}"),
                P(f"Rechtsgrundlagen: {rules}", size=8.4),
                table,
                P(f"{register} Fällig wird der Betrag zwei Wochen, nachdem der Bescheid rechtskräftig geworden ist."),
                H("Rechtsbehelfsbelehrung", size=9.6),
                P(f"Einspruch gegen diesen Bescheid ist zulässig. Er muss zwei Wochen nach der Zustellung {bei(org.name)} "
                  "vorliegen, schriftlich oder zur Niederschrift. Über einen Einspruch kann das Amtsgericht ohne "
                  "Hauptverhandlung durch Beschluss entscheiden, wenn niemand widerspricht.", size=8.7),
            ]  # fmt: skip
            key = "Er muss zwei Wochen nach der Zustellung"
        blocks.append(Envelope(sender=org.name, recipient=person, reference=az, note=note, initials=initials))
        letter = Letter(org=org, recipient=person, info=info, subject="Bußgeldbescheid", date_line=date_line,
                        subject_extra=("wegen einer Verkehrsordnungswidrigkeit (§ 65 OWiG)",), blocks=blocks,
                        style=STYLES[variant], created=created(letter_date), running_ref=f"Az. {az}")  # fmt: skip
        return _case(
            case_id, "fine_bussgeld", variant, letter,
            truth(kind="fine", sender=org.name, document_date=letter_date, references=refs, amounts=[total, fine],
                  remedy="einspruch", items=[tag_fine(objection)], optional_items=[payment]),
            org.region, [de(letter_date), key, de(served), az],
            notes="The Zustellung day is noted on the envelope (page 2), not the Bescheid date.",
        )  # fmt: skip

    def office(name: str, street: str, postcode: str, city: str, region: str | None, head: tuple[str, ...], blz: str,
               account: str, style: str, accent: tuple[int, int, int]) -> Org:  # fmt: skip
        slug = name.lower().replace(" ", "-").replace("–", "").replace("--", "-")
        return authority(name, street, postcode, city, region, head, phone="0800 555 0" + account[:3],
                         email=f"bussgeld@{slug[:28].strip('-')}.example", blz=blz, account=account, style=style, accent=accent)  # fmt: skip

    # K1 — SL: Bescheid Fri 20.11., served Sat 21.11.2026 → Sat 05.12.2026 → Mon 07.12.2026.
    k1 = "holdout4-fine_bussgeld-K1"
    d, s = _fine_days(k1, date(2026, 11, 20), date(2026, 11, 21))
    cases.append(make(
        k1, "K", office("Zentrale Bußgeldbehörde Beispielsaarland", "Am Römerkastell 9", "66121", "Beispielbrücken", "SL",
                        ("Saarland", "Zentrale Bußgeldbehörde"), "59010000", "6612100", "authority", (0, 60, 110)),
        S_SL, d, s, "SB-MW 418", "29.09.2026, 07:12 Uhr", "Beispielwadern, Landstraße L 152, Höhe Waldfriedhof",
        "Sie fuhren außerhalb geschlossener Ortschaften 27 km/h schneller als die zulässigen 70 km/h.",
        "§ 41 Abs. 1 i. V. m. Anlage 2, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 11.3.5 BKat", 150.0, 1, "2026-12-07",
        "VOW 4.1-26/308812", f"Zugestellt am {de(s)}", "Mü.",
    ))  # fmt: skip
    # K2 — Land unknown: Bescheid Wed 18.11., served Sat 21.11.2026 → Sat 05.12. → Mon 07.12.2026.
    k2 = "holdout4-fine_bussgeld-K2"
    d, s = _fine_days(k2, date(2026, 11, 18), date(2026, 11, 21))
    cases.append(make(
        k2, "K", office("Stadt Musterquellen – Bußgeldstelle", "Postfach 21 40", "35573", "Musterquellen", None,
                        ("Ordnungsamt", "Verkehrsüberwachung"), "51350025", "2140300", "band", (60, 90, 40)),
        S_GEN, d, s, "MQ-BQ 207", "10.10.2026, 22:48 Uhr", "Musterquellen, Bahnhofstraße, Höhe Haus Nr. 18",
        "Sie hielten in einem Bereich mit Haltverbot länger als drei Minuten und behinderten dadurch den Linienbus.",
        "§ 12 Abs. 1, § 1 Abs. 2, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 51.1 BKat", 55.0, 0, "2026-12-07",
        "OA-VÜ 26.501234", f"zugest. {de(s)}", "Fe.",
    ))  # fmt: skip
    # L1 — BB: Bescheid Thu 19.11., served Sat 21.11.2026 → Sat 05.12. → Mon 07.12.2026.
    l1 = "holdout4-fine_bussgeld-L1"
    d, s = _fine_days(l1, date(2026, 11, 19), date(2026, 11, 21))
    cases.append(make(
        l1, "L", office("Zentraldienst der Polizei Muster-Brandenburg", "Kiefernring 2", "15831", "Musterblankenfelde", "BB",
                        ("Land Brandenburg · Polizei", "Zentrale Bußgeldstelle"), "16000000", "5831200", "minimal", (140, 30, 40)),
        S_BB, d, s, "LOS-RM 66", "02.10.2026, 15:30 Uhr", "Beispielkow, Bundesstraße B 168, Ortsausgang Richtung Musterfurt",
        "Sie überholten trotz Überholverbots einen Lastkraftwagen und gefährdeten dabei den Gegenverkehr.",
        "§ 5 Abs. 3 Nr. 2, § 41 Abs. 1 i. V. m. Anlage 2, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 19.1.2 BKat", 150.0, 1,
        "2026-12-07", "BS-2026-772415.3", f"zugestellt am {de(s)}", "Kö.",
    ))  # fmt: skip
    # L2 — NI: Bescheid Fri 20.11., served Mon 23.11.2026 → Mon 07.12.2026.
    l2 = "holdout4-fine_bussgeld-L2"
    d, s = _fine_days(l2, date(2026, 11, 20), date(2026, 11, 23))
    cases.append(make(
        l2, "L", office("Landkreis Musterammerland – Bußgeldstelle", "Moorstraße 21", "26655", "Beispielstede", "NI",
                        ("Land Niedersachsen · Landkreis Musterammerland", "Straßenverkehrsbehörde"), "28050100", "2665500",
                        "logo", (20, 90, 60)),
        S_NI, d, s, "WST-FM 91", "23.09.2026, 08:05 Uhr", "Beispielstede, Oldenburger Straße 40 (innerorts)",
        "Sie überschritten innerorts die zulässige Höchstgeschwindigkeit von 30 km/h vor einer Grundschule um 18 km/h.",
        "§ 41 Abs. 1 i. V. m. Anlage 2, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 11.3.4 BKat", 115.0, 1, "2026-12-07",
        "BG 32.2-26/40918", f"Zustellung {de(s)}", "Jan.",
    ))  # fmt: skip
    # M1 — SL: Bescheid Fri 20.11., served Tue 24.11.2026 → Tue 08.12.2026.
    m1 = "holdout4-fine_bussgeld-M1"
    d, s = _fine_days(m1, date(2026, 11, 20), date(2026, 11, 24))
    cases.append(make(
        m1, "M", office("Stadt Musterhomburg (Saar) – Ordnungsbehörde", "Talstraße 57", "66424", "Musterhomburg", "SL",
                        ("Saarland · Kreisstadt Musterhomburg", "Bußgeldstelle"), "59450010", "4240100", "band", (0, 80, 130)),
        S_SL, d, s, "HOM-AM 732", "16.10.2026, 11:44 Uhr", "Musterhomburg, Kaiserstraße / Ecke Talstraße",
        "Sie benutzten beim Abbiegen ein Mobiltelefon, das Sie in der Hand hielten.",
        "§ 23 Abs. 1a, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 246.1 BKat", 100.0, 1, "2026-12-08",
        "OWi-26-118430", f"zugestellt {de(s)}", "Sch.",
    ))  # fmt: skip
    # M2 — Land unknown: Bescheid Thu 19.11., served Tue 24.11.2026 → Tue 08.12.2026.
    m2 = "holdout4-fine_bussgeld-M2"
    d, s = _fine_days(m2, date(2026, 11, 19), date(2026, 11, 24))
    cases.append(make(
        m2, "M", office("Kreis Beispielborken – Bußgeldstelle", "Burloer Weg 3", "46325", "Beispielborken", None,
                        ("Fachbereich Straßenverkehr",), "40050000", "4632500", "authority", (90, 60, 20)),
        S_GEN2, d, s, "BOR-JB 315", "05.10.2026, 17:21 Uhr", "Beispielborken, Kreisstraße K 33, Höhe Gewerbegebiet Nord",
        "Sie überschritten außerorts die zulässige Höchstgeschwindigkeit von 100 km/h um 23 km/h.",
        "§ 3 Abs. 3 Nr. 2c, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 11.3.4 BKat", 100.0, 1, "2026-12-08",
        "51.3-26/0779413", f"Zugestellt {de(s)}", "Bö.",
    ))  # fmt: skip
    # N1 — BB: Bescheid Wed 18.11., served Tue 24.11.2026 → Tue 08.12.2026.
    n1 = "holdout4-fine_bussgeld-N1"
    d, s = _fine_days(n1, date(2026, 11, 18), date(2026, 11, 24))
    cases.append(make(
        n1, "N", office("Landkreis Musteruckermark – Bußgeldstelle", "Karl-Marx-Straße 1", "17291", "Musterprenzlau", "BB",
                        ("Land Brandenburg · Landkreis Musteruckermark", "Straßenverkehrsamt"), "17056060", "1729100",
                        "authority", (150, 30, 40)),
        S_BB, d, s, "UM-RS 404", "17.10.2026, 09:56 Uhr", "Musterprenzlau, Stettiner Straße, Lichtzeichenanlage am Marktberg",
        "Sie fuhren bei Rot über die Haltlinie; die Rotphase dauerte bereits länger als eine Sekunde.",
        "§ 37 Abs. 2 Nr. 1, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 132.3 BKat", 200.0, 1, "2026-12-08",
        "VB-26-501882", f"zugestellt am {de(s)}", "Ku.",
    ))  # fmt: skip
    # N2 — NI: Bescheid Fri 20.11., served Mon 23.11.2026 → Mon 07.12.2026.
    n2 = "holdout4-fine_bussgeld-N2"
    d, s = _fine_days(n2, date(2026, 11, 20), date(2026, 11, 23))
    cases.append(make(
        n2, "N", office("Stadt Musterwilhelmshaven – Bußgeldstelle", "Rathausplatz 1", "26382", "Musterwilhelmshaven", "NI",
                        ("Land Niedersachsen · Stadt Musterwilhelmshaven", "Ordnungsamt"), "28250110", "2638200",
                        "minimal", (0, 70, 120)),
        S_NI, d, s, "WHV-FM 88", "01.10.2026, 19:09 Uhr", "Musterwilhelmshaven, Bismarckstraße 112",
        "Sie fuhren mit einem Fahrzeug, dessen Hauptuntersuchung seit mehr als vier Monaten überfällig war.",
        "§ 29 Abs. 1 StVZO i. V. m. Anlage VIII, § 69a StVZO; § 24 Abs. 1 StVG; 186.1.2 BKat", 60.0, 1, "2026-12-07",
        "32.12-26/61107", f"zugest. am {de(s)}", "Ha.",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 12 — year_boundary (the period runs over Christmas into the last days of the year)
# ==================================================================================================


def year_boundary() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, letter_date: date, posted: date,
             scope: str, subject: str, body: list[Block], refs: list[tuple[str, str]], kind: str, amounts: list[float],
             hand: str, *, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
        remedy = "einspruch" if scope == "ao" else "widerspruch"
        item = check(
            objection_item(posted=posted, scope=scope, remedy=remedy, region=None,
                           title="Einspruchsfrist" if scope == "ao" else "Widerspruchsfrist"),
            hand,
        )  # fmt: skip
        item = tag_remedy(item, posted=posted, scope=scope, region=None, letter_date=letter_date)
        stated = posted != letter_date
        if variant == "K":
            info = [*refs, ("Bescheid vom", de(letter_date)), ("Aufgabe zur Post", de_weekday(posted))]
            tail = run_in("Rechtsbehelfsbelehrung:",
                          f"Gegen diesen Bescheid kann binnen eines Monats nach Bekanntgabe Einspruch {bei(org.name)} "
                          "eingelegt werden, schriftlich, elektronisch oder zur Niederschrift. Der Bescheid gilt als am "
                          "vierten Tag nach der oben genannten Aufgabe zur Post bekannt gegeben, sofern er nicht "
                          "nachweislich später eingegangen ist.")  # fmt: skip
            key = "Der Bescheid gilt als am vierten Tag nach der oben genannten Aufgabe zur Post bekannt gegeben"
        elif variant == "M":
            info = [*refs, ("Datum", de(letter_date))]
            tail = small_heading("Rechtsbehelfsbelehrung",
                                 f"Sie können gegen diese Festsetzung innerhalb eines Monats Einspruch {bei(org.name)} "
                                 "erheben. Die Frist beginnt mit der Bekanntgabe, die bei Versand durch die Post am vierten "
                                 "Tag nach der Aufgabe zur Post eintritt.")  # fmt: skip
            key = "Die Frist beginnt mit der Bekanntgabe, die bei Versand durch die Post am vierten"
        else:
            info = [*refs, ("Datum des Bescheids", de(letter_date))]
            if stated:
                info.append(("Versandt am", de_weekday(posted)))
            where = f"{org.name}, {org.street}, {org.postcode} {org.city}"
            if variant == "L":
                text = (f"Gegen den Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden, "
                        f"schriftlich oder zur Niederschrift bei der {where}. Der Bescheid gilt mit dem vierten Tag nach dem "
                        "angegebenen Versandtag als bekannt gegeben.")  # fmt: skip
                key = "Der Bescheid gilt mit dem vierten Tag nach dem angegebenen Versandtag als bekannt gegeben"
            else:
                text = (f"Den Widerspruch können Sie binnen eines Monats ab Bekanntgabe einlegen, schriftlich oder zur "
                        f"Niederschrift bei der {where}. Als bekannt gegeben gilt der Bescheid am vierten Tag nach seiner "
                        "Aufgabe zur Post.")  # fmt: skip
                key = "Den Widerspruch können Sie binnen eines Monats ab Bekanntgabe einlegen"
            tail = small_heading("Rechtsbehelfsbelehrung", text)
        letter = Letter(org=org, recipient=person, info=info, subject=subject, salutation=salutation,
                        blocks=[*body, *tail, Sign("Mit freundlichen Grüßen", ("Im Auftrag",))], style=STYLES[variant],
                        created=created(letter_date), running_ref=" ".join(refs[0]))  # fmt: skip
        return _case(
            case_id, "year_boundary", variant, letter,
            truth(kind=kind, sender=org.name, document_date=letter_date, references=refs, amounts=amounts, remedy=remedy,
                  items=[item]),
            None, [de(letter_date), key, *([de(posted)] if stated else [])], photo=photo, notes=notes,
        )  # fmt: skip

    xmas = ("Posted on a Saturday: day 4 is Wed 25.11.2026; one month later is 1. Weihnachtstag, then a Saturday and a Sunday, "
            "so the period ends on Mon 28.12.2026. Counted from the letter date it would end before Christmas (c02).")  # fmt: skip

    # K1 — Familienkasse (Kindergeld, EStG → AO). Bescheid Thu 19.11., posted Sat 21.11.2026 → day 4 = Wed 25.11. → Fri 25.12.
    # (holiday) → Sat, Sun → Mon 28.12.2026. From the Bescheid date: Mon 23.11. → Wed 23.12.2026.
    k1 = "holdout4-year_boundary-K1"
    d = drawn(k1, AUTHORITY_DAYS, date(2026, 11, 19))
    fk = authority("Familienkasse Beispielweser", "Weserkai 14", "37603", "Musterholzminden", None,
                   ("Familienkasse (Musterausgabe)", "Kindergeld nach dem Einkommensteuergesetz"), phone="0800 555 4512",
                   email="familienkasse-beispielweser@arbeitsagentur.example", blz="25000000", account="4512000",
                   style="band", accent=(160, 25, 35))  # fmt: skip
    cases.append(make(
        k1, "K", fk, S_GEN, "Sehr geehrter Herr Musterquell,", d, SATURDAY_POSTING, "ao",
        "Aufhebung der Kindergeldfestsetzung für Ihren Sohn Lukas ab Januar 2027",
        [P("Ihr Sohn Lukas, 24 Jahre alt, hat uns mitgeteilt, dass er sein Studium im Dezember 2026 abschließt und ab Januar "
           "2027 eine feste Stelle antritt. Nach Abschluss der Ausbildung besteht nach § 32 Abs. 4 EStG kein Anspruch mehr; die "
           "Festsetzung heben wir deshalb mit Wirkung ab 01.01.2027 auf."),
         P("Bis einschließlich Dezember 2026 zahlen wir das Kindergeld von **259,00 €** im Monat weiter.", size=9.2)],
        [("Kindergeldnummer", "377FK104258")], "social_insurance", [259.0], "2026-12-28", notes=xmas,
    ))  # fmt: skip

    # K2 — Finanzamt, Grundsteuerwert. Bescheid Wed 18.11., posted Sat 21.11.2026 → Mon 28.12.2026. From the Bescheid date:
    # Sun 22.11. → Mon 23.11. → Wed 23.12.2026.
    k2 = "holdout4-year_boundary-K2"
    d = drawn(k2, AUTHORITY_DAYS, date(2026, 11, 18))
    fa = authority("Finanzamt Musterweilburg", "Schlossgasse 5", "35781", "Musterweilburg", None,
                   ("Steuerverwaltung", "Bewertungsstelle Grundbesitz"), phone="06471 555 33-0",
                   email="poststelle@fa-musterweilburg.example", blz="51350025", account="3300100",
                   style="authority", accent=(60, 70, 100))  # fmt: skip
    cases.append(make(
        k2, "K", fa, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, SATURDAY_POSTING, "ao",
        "Bescheid über die Fortschreibung des Grundsteuerwerts auf den 01.01.2026",
        [P("Ihr Wohnhaus in der Ackerstraße 26 wurde im Jahr 2025 um einen Anbau mit 38 m² Wohnfläche erweitert. Den "
           "Grundsteuerwert schreiben wir deshalb auf den 01.01.2026 auf **184.300 €** fort (Wertfortschreibung)."),
         P("Auf Grundlage dieses Werts erhalten Sie einen neuen Grundsteuermessbescheid; die Grundsteuer selbst setzt Ihre "
           "Gemeinde fest.", size=9.2)],
        [("Aktenzeichen", "35 112 0447 8810")], "tax_letter", [], "2026-12-28", notes=xmas,
    ))  # fmt: skip

    # K3 — Finanzamt, Vorauszahlungen 2027. Bescheid Fri 20.11., posted Sat 21.11.2026 → Mon 28.12.2026. From the Bescheid
    # date: Tue 24.11. → Thu 24.12.2026.
    k3 = "holdout4-year_boundary-K3"
    d = drawn(k3, AUTHORITY_DAYS, date(2026, 11, 20))
    fa2 = authority("Finanzamt Beispielsoest", "Wiesenring 30", "59494", "Beispielsoest", None,
                    ("Steuerverwaltung", "Veranlagung Freiberufler"), phone="02921 555 18-0",
                    email="poststelle@fa-beispielsoest.example", blz="41450075", account="1800200",
                    style="minimal", accent=(40, 80, 70))  # fmt: skip
    cases.append(make(
        k3, "K", fa2, S_GEN, "Sehr geehrter Herr Musterquell,", d, SATURDAY_POSTING, "ao",
        "Bescheid über Vorauszahlungen zur Einkommensteuer ab dem Kalenderjahr 2027",
        [P("nach dem Gewinn aus Ihrer Tätigkeit als freier Übersetzer im Jahr 2025 setzen wir die Vorauszahlungen zur "
           "Einkommensteuer ab 2027 auf **1.120,00 €** je Quartal fest, fällig jeweils am 10.03., 10.06., 10.09. und 10.12."),
         P("Haben sich Ihre Einkünfte inzwischen deutlich verändert, können Sie unter Vorlage einer Prognose eine Anpassung "
           "beantragen.", size=9.2)],
        [("Steuernummer", "345/2051/1187")], "tax_letter", [1120.0], "2026-12-28", notes=xmas,
    ))  # fmt: skip

    # L1 — Rentenversicherung (SGB VI → SGB X), photo. Bescheid Wed 18.11., sent Sat 21.11.2026 → day 4 = Wed 25.11. → Fri
    # 25.12. → Mon 28.12.2026. From the Bescheid date: Sun 22.11. (no shift) → Tue 22.12.2026.
    l1 = "holdout4-year_boundary-L1"
    d = drawn(l1, AUTHORITY_DAYS, date(2026, 11, 18))
    rv = authority("Rentenversicherung Musterhessen-Lahn", "Rentenweg 8", "35394", "Mustergießen", None,
                   ("Gesetzliche Rentenversicherung (fiktiv)", "Abteilung Rehabilitation"), phone="0800 555 7012",
                   email="reha@rv-musterhessen-lahn.example", blz="51300000", account="7012000", style="logo", monogram="RV",
                   accent=(0, 75, 140), legal=("Körperschaft des öffentlichen Rechts",))  # fmt: skip
    cases.append(make(
        l1, "L", rv, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, SATURDAY_POSTING, "sgbx",
        "Ihr Antrag auf eine medizinische Rehabilitation – Ablehnung",
        [P("eine stationäre Rehabilitation können wir Ihnen derzeit nicht bewilligen. Nach den ärztlichen Unterlagen ist Ihre "
           "Erwerbsfähigkeit nicht erheblich gefährdet; die ambulante Physiotherapie, die Ihr Orthopäde verordnet hat, reicht "
           "nach Einschätzung unseres sozialmedizinischen Dienstes aus."),
         P("Verschlechtern sich Ihre Beschwerden, können Sie jederzeit einen neuen Antrag stellen.", size=9.2)],
        [("Versicherungsnummer", "53 120681 B 517")], "social_insurance", [], "2026-12-28", photo=True, notes=xmas,
    ))  # fmt: skip

    # L2 — Agentur für Arbeit (SGB III → SGB X). Bescheid Fri 20.11., sent Sat 21.11.2026 → Mon 28.12.2026. From the Bescheid
    # date: Tue 24.11. → Thu 24.12.2026.
    l2 = "holdout4-year_boundary-L2"
    d = drawn(l2, AUTHORITY_DAYS, date(2026, 11, 20))
    aa = authority("Agentur für Arbeit Musterlimburg", "Agenturring 6", "65549", "Musterlimburg", None,
                   ("Bundesagentur für Arbeit (Musterausgabe)", "Leistungsteam Arbeitslosengeld"), phone="0800 555 4555",
                   email="musterlimburg@arbeitsagentur.example", blz="76000000", account="4555000",
                   style="band", accent=(170, 20, 35))  # fmt: skip
    cases.append(make(
        l2, "L", aa, S_GEN, "Sehr geehrter Herr Musterquell,", d, SATURDAY_POSTING, "sgbx",
        "Bewilligung von Arbeitslosengeld ab 01.01.2027",
        [P("ab dem 01.01.2027 erhalten Sie Arbeitslosengeld für 360 Kalendertage. Der tägliche Leistungsbetrag beträgt "
           "**48,71 €**; Grundlage ist Ihr Arbeitsentgelt der letzten zwölf Monate bei der Druckerei Beispiellahn."),
         P("Melden Sie sich bitte am ersten Tag der Arbeitslosigkeit persönlich oder online arbeitslos, falls noch nicht "
           "geschehen.", size=9.2)],
        [("Kundennummer", "418D552907")], "social_insurance", [48.71], "2026-12-28", notes=xmas,
    ))  # fmt: skip

    # M1 — Hauptzollamt, Kfz-Steuer (AO). Posted Fri 20.11.2026 → day 4 = Tue 24.11. → Thu 24.12.2026 (Heiligabend is a working
    # day, so nothing moves).
    m1 = "holdout4-year_boundary-M1"
    d = drawn(m1, AUTHORITY_DAYS, date(2026, 11, 20))
    hza = authority("Hauptzollamt Beispielhafen", "Zollkai 3", "20457", "Musterhafen", None,
                    ("Zollverwaltung (Musterausgabe)", "Sachgebiet Kraftfahrzeugsteuer"), phone="0351 555 448-0",
                    email="kfz-steuer@hza-beispielhafen.example", blz="86000000", account="4480300",
                    style="authority", accent=(0, 80, 60))  # fmt: skip
    cases.append(make(
        m1, "M", hza, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, d, "ao",
        "Festsetzung der Kraftfahrzeugsteuer für das Fahrzeug MS-JB 2604",
        [P("für Ihr Fahrzeug mit dem Kennzeichen MS-JB 2604 setzen wir die Kraftfahrzeugsteuer ab dem Tag der Zulassung, "
           "dem 02.11.2026, auf **146,00 €** für jeweils ein Jahr fest. Den Betrag buchen wir vom angegebenen Konto ab."),
         P("Die Steuer bemisst sich nach dem Hubraum und dem Kohlendioxidausstoß laut Zulassungsbescheinigung.", size=9.2)],
        [("Steuernummer", "KFZ 4480/26/77310")], "tax_letter", [146.0], "2026-12-24",
        notes="The period ends on 24.12., Heiligabend, a working day under every Land's holiday law (f02).",
    ))  # fmt: skip

    # M2 — Familienkasse, Kindergeld (AO). Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    m2 = "holdout4-year_boundary-M2"
    d = drawn(m2, AUTHORITY_DAYS, date(2026, 11, 19))
    fk2 = authority("Familienkasse Musterfulda", "Domweg 19", "36037", "Musterfulda", None,
                    ("Familienkasse (Musterausgabe)", "Kindergeld"), phone="0800 555 4513",
                    email="familienkasse-musterfulda@arbeitsagentur.example", blz="53000000", account="4513000",
                    style="logo", monogram="FK", accent=(150, 20, 30))  # fmt: skip
    cases.append(make(
        m2, "M", fk2, S_GEN, "Sehr geehrter Herr Musterquell,", d, d, "ao",
        "Kindergeld für Ihre Tochter Clara ab Oktober 2026",
        [P("für Ihre Tochter Clara, die seit dem Wintersemester 2026/27 an der Hochschule Beispielfulda studiert, setzen wir "
           "ab Oktober 2026 weiterhin Kindergeld in Höhe von **259,00 €** monatlich fest (§§ 62, 63, 66 EStG)."),
         P("Bitte reichen Sie uns zum Ende des Sommersemesters eine neue Studienbescheinigung ein.", size=9.2)],
        [("Kindergeldnummer", "355FK662019")], "social_insurance", [259.0], "2026-12-23",
    ))  # fmt: skip

    # M3 — Finanzamt, Zinsbescheid (AO). Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    m3 = "holdout4-year_boundary-M3"
    d = drawn(m3, AUTHORITY_DAYS, date(2026, 11, 19))
    cases.append(make(
        m3, "M", fa2, S_GEN, "Sehr geehrter Herr Musterquell,", d, d, "ao",
        "Bescheid über Erstattungszinsen zur Einkommensteuer 2023",
        [P("auf die Erstattung aus der geänderten Einkommensteuer 2023 zahlen wir Ihnen Zinsen von **42,00 €** für 28 volle "
           "Monate (§ 233a AO). Der Betrag wird mit der Erstattung überwiesen."),
         P("Erstattungszinsen sind bei Ihnen Einkünfte aus Kapitalvermögen; die Bescheinigung dafür erhalten Sie gesondert.",
           size=9.2)],
        [("Steuernummer", "345/2051/1187")], "tax_letter", [42.0], "2026-12-23",
    ))  # fmt: skip

    # N1 — Krankenkasse, Beitragsbescheid (SGB V → SGB X), photo. Posted Wed 18.11.2026 → day 4 = Sun 22.11. (no shift) →
    # Tue 22.12.2026.
    n1 = "holdout4-year_boundary-N1"
    d = drawn(n1, AUTHORITY_DAYS, date(2026, 11, 18))
    kk = authority("Musterquell Krankenkasse", "Am Brunnenhof 2", "35390", "Mustergießen", None,
                   ("Gesetzliche Krankenversicherung (Musterausgabe)", "Beiträge freiwillig Versicherter"),
                   phone="0641 555 830-60", email="beitraege@musterquell-kk.example", blz="51350025", account="8300600",
                   kind="health_insurer", style="logo", monogram="MQ", accent=(0, 110, 100),
                   legal=("Körperschaft des öffentlichen Rechts",))  # fmt: skip
    cases.append(make(
        n1, "N", kk, S_GEN2, "Sehr geehrte Frau Beispielacker,", d, d, "sgbx",
        "Ihre Beiträge zur Kranken- und Pflegeversicherung ab 01.01.2027",
        [P("ab dem 01.01.2027 betragen Ihre monatlichen Beiträge **318,46 €**. Die Erhöhung ergibt sich aus dem neuen "
           "Zusatzbeitragssatz unserer Kasse und Ihren Einnahmen laut Steuerbescheid für 2025."),
         P("Wir buchen den Beitrag weiter zum 15. des Folgemonats ab.", size=9.2)],
        [("Versichertennummer", "Q550274119")], "health_insurance", [318.46], "2026-12-22", photo=True,
        notes="The deemed-delivery day is a Sunday; outside tax law it does not move.",
    ))  # fmt: skip

    # N2 — Berufsgenossenschaft (SGB VII → SGB X). Posted Thu 19.11.2026 → day 4 = Mon 23.11. → Wed 23.12.2026.
    n2 = "holdout4-year_boundary-N2"
    d = drawn(n2, AUTHORITY_DAYS, date(2026, 11, 19))
    bg = authority("Musterbau-Berufsgenossenschaft", "Gerüstweg 7", "30159", "Musterhannover", None,
                   ("Gesetzliche Unfallversicherung (Musterausgabe)", "Beitragsabteilung"), phone="0511 555 98-0",
                   email="beitrag@musterbau-bg.example", blz="25050180", account="9800400", style="band",
                   accent=(200, 110, 0), legal=("Körperschaft des öffentlichen Rechts",))  # fmt: skip
    cases.append(make(
        n2, "N", bg, S_GEN, "Sehr geehrter Herr Musterquell,", d, d, "sgbx",
        "Veranlagung Ihres Unternehmens zu den Gefahrklassen ab 2027",
        [P("Ihr Malerbetrieb wird ab dem 01.01.2027 nach unserem neuen Gefahrtarif veranlagt. Für den Gewerbezweig „Maler "
           "und Lackierer“ gilt die Gefahrklasse **7,4**; für Ihre Bürokraft bleibt es bei der Gefahrklasse 0,6."),
         P("Den Beitrag berechnen wir wie bisher nach dem Ende des Jahres aus den gemeldeten Entgelten.", size=9.2)],
        [("Mitgliedsnummer", "BG 4471 0938 2")], "social_insurance", [], "2026-12-23",
    ))  # fmt: skip
    return cases
