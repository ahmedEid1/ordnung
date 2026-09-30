"""Holdout split, families 1, 2, 3, 7 and 12: variants E and F of the administrative acts.

Written after extraction prompt version 11 and before any holdout recording, from scratch: new
senders, recipients, wording and layout (variant F prints the date in a place line above the subject
and the Rechtsbehelfsbelehrung inline). No deadline-bearing sentence of variants A–D recurs
(``evals/verify_labels.py`` checks it). The posting and service days were drawn with a seeded random
choice among the days that fit each letter's scenario (the same kinds of scenario as the test
letters); ``hand`` is the expected date worked out by hand from the calendar and is asserted against
the computed label.
"""

from __future__ import annotations

from datetime import date

from . import orgs as O
from .common import (
    Case,
    event_period_item,
    fixed_item,
    objection_item,
    spec,
    today_after,
    truth,
    undated_item,
)
from .families_admin import check, created
from .pdf import Block, Box, Envelope, H, Letter, Org, P, Person, Sign, Style, Table
from .text import bei, de, eur, eur_plain, iban_grouped

STYLES = {
    "E": Style(body_pt=9.7, left=23, right=19, leading=1.36, para_gap=2.4, align="L", info_label_pt=7.0,
               info_value_pt=8.3, subject_pt=11.2),
    "F": Style(body_pt=10.2, left=27, right=23, leading=1.3, para_gap=1.9, align="J", info_label_pt=7.6,
               info_value_pt=8.9, subject_pt=10.4),
}  # fmt: skip


def place_line(org: Org, d: date) -> str:
    """Variant F's date line above the subject: '<city>, <date>'."""
    return f"{org.city}, {de(d)}"


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


# ==================================================================================================
# Family 1 — tax_assessment (AO: fiction day moves off Sat/Sun/holidays; § 355 AO one month)
# ==================================================================================================


def _income_table(year: int, wage: int, costs: int, special: int, est: int, withheld: int) -> Table:
    taxable = wage - costs - special
    diff = est - withheld
    rows = (
        ("Bruttoarbeitslohn", _thousands(wage)),
        ("abzüglich Werbungskosten", f"– {_thousands(costs)}"),
        ("abzüglich Vorsorgeaufwendungen und Sonderausgaben", f"– {_thousands(special)}"),
        (f"Zu versteuerndes Einkommen {year}", _thousands(taxable)),
        ("Einkommensteuer nach dem Grundtarif", eur_plain(est)),
        ("anzurechnende Lohnsteuer", f"– {eur_plain(withheld)}"),
        ("Solidaritätszuschlag und Kirchensteuer", "0,00"),
        ("Verbleibende Nachzahlung" if diff > 0 else "Verbleibende Erstattung", eur_plain(abs(diff))),
    )
    return Table(
        rows=rows,
        header=("Ermittlung der Steuer", "Euro"),
        value_width=34,
        bold_rows=(3, 7),
        rule_before=(3, 7),
    )


def tax_assessment() -> list[Case]:
    cases: list[Case] = []

    # --- variant E: compact Bescheid, date and Steuer-ID in the info block, heading-style Belehrung ---
    def variant_e(case_id: str, org: Org, person: Person, posted: date, year: int, stnr: str, idnr: str, wage: int, costs: int,
                  special: int, est: int, withheld: int, hand: str) -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="ao", remedy="einspruch", region=org.region,
                           title=f"Einspruchsfrist Einkommensteuerbescheid {year}"),
            hand,
        )  # fmt: skip
        refund = withheld - est
        letter = Letter(
            org=org, recipient=person,
            info=[("Steuernummer", stnr), ("Steuer-ID", idnr), ("Ansprechpartnerin", "Frau Lehnert, Arbeitnehmerstelle"),
                  ("Bescheiddatum", de(posted))],
            subject=f"Einkommensteuerbescheid {year}",
            subject_extra=("Veranlagung nach Ihrer über ELSTER übermittelten Erklärung",),
            blocks=[
                P(f"Die Einkommensteuer für das Kalenderjahr {year} wird wie folgt berechnet und festgesetzt. Grundlage sind Ihre "
                  "Angaben und die elektronisch gemeldeten Daten Ihres Arbeitgebers."),
                _income_table(year, wage, costs, special, est, withheld),
                Box((f"Sie erhalten {eur(refund)} zurück.", f"Wir überweisen den Betrag auf Ihr Konto {iban_grouped(O.H_RECIPIENT_IBAN)}.")),
                H("Erläuterungen"),
                P("Die Entfernungspauschale wurde für 196 Arbeitstage angesetzt; die Fahrten an den übrigen erklärten Tagen haben Sie "
                  "als Tätigkeit im Homeoffice geltend gemacht, dafür wurde die Tagespauschale berücksichtigt."),
                H("Rechtsbehelfsbelehrung"),
                P("Mit dem Einspruch können Sie diesen Bescheid anfechten, und zwar **binnen eines Monats ab Bekanntgabe**. Richten Sie ihn "
                  f"schriftlich oder elektronisch an das {org.name} oder erklären Sie ihn dort zur Niederschrift. Wird der Bescheid mit "
                  "einfachem Brief versandt, gilt er am vierten Tag nach der Aufgabe zur Post als bekannt gegeben – außer er erreicht "
                  "Sie nachweislich nicht oder erst später.", size=8.8),
                P("Dieser Bescheid ist mit Hilfe automatischer Einrichtungen erlassen worden und wird nicht unterschrieben.", size=7.8),
            ],
            style=STYLES["E"], created=created(posted), running_ref=f"StNr. {stnr} · Bescheid vom {de(posted)}",
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="tax_assessment", variant="E", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=posted, references=[("Steuernummer", stnr), ("Steuer-ID", idnr)],
                        amounts=[float(refund)], remedy="einspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), "binnen eines Monats ab Bekanntgabe", stnr],
        )  # fmt: skip

    # E1 — RP. Posted Tue 28.07.2026 → day 4 = Sat 01.08. → Mon 03.08. (§ 108 Abs. 3 AO) → Thu 03.09.2026.
    cases.append(variant_e("holdout-tax_assessment-E1", O.H_FA_RP, O.H_RP, date(2026, 7, 28), 2025, "40/118/27706", "71 403 928 516",
                           46_380, 3_912, 6_104, 6_871, 7_540, "2026-09-03"))  # fmt: skip
    # E2 — Land unknown. Posted Mon 15.06.2026 → day 4 = Fri 19.06. (working day) → Sun 19.07. → Mon 20.07.2026.
    cases.append(variant_e("holdout-tax_assessment-E2", O.H_FA_X, O.H_GEN, date(2026, 6, 15), 2025, "20/233/15084", "38 115 604 272",
                           33_950, 1_230, 5_016, 3_978, 4_406, "2026-07-20"))  # fmt: skip

    # --- variant F: place/date line, Bescheid date ≠ posting day possible (info block), inline Belehrung ---
    def variant_f(case_id: str, org: Org, person: Person, letter_date: date, posted: date, year: int, stnr: str, wage: int,
                  costs: int, special: int, est: int, withheld: int, hand: str, pay_due: date | None = None,
                  hand_pay: str | None = None) -> Case:  # fmt: skip
        items = [
            check(
                objection_item(posted=posted, scope="ao", remedy="einspruch", region=org.region,
                               title=f"Einspruchsfrist Einkommensteuerbescheid {year}"),
                hand,
            )
        ]  # fmt: skip
        diff = est - withheld
        blocks: list[Block] = [
            P(
                f"für den Veranlagungszeitraum {year} ergeht folgender Bescheid über Einkommensteuer und Solidaritätszuschlag:"
            ),
            _income_table(year, wage, costs, special, est, withheld),
        ]
        if diff > 0:
            assert pay_due is not None and hand_pay is not None
            items.append(check(
                fixed_item(due=pay_due, region=org.region, kind="payment", nature="payment", title=f"Einkommensteuer {year} nachzahlen",
                           money=float(diff), rule="Payment date printed in the assessment (Fälligkeit as set by the Finanzamt)."),
                hand_pay,
            ))  # fmt: skip
            blocks.append(Box((f"Nachzahlung: {eur(diff)}", f"Zahlungstermin: {de(pay_due)}",
                               f"{org.bank} · IBAN {iban_grouped(org.iban)} · Verwendungszweck {stnr} ESt {year}")))  # fmt: skip
        else:
            blocks.append(
                Box(
                    (
                        f"Erstattung: {eur(-diff)}",
                        "Die Auszahlung erfolgt auf das bei uns hinterlegte Girokonto.",
                    )
                )
            )
        blocks += [
            P("Die Aufwendungen für Arbeitsmittel und Fortbildung wurden in der erklärten Höhe anerkannt."),
            P(
                "**Rechtsbehelfsbelehrung:** Wollen Sie diesen Bescheid überprüfen lassen, legen Sie Einspruch ein. Die Einspruchsfrist "
                "beträgt einen Monat und beginnt mit Ablauf des Tages, an dem der Bescheid bekannt gegeben wurde; wird er Ihnen per Post "
                "zugeschickt, gilt er nach § 122 Abs. 2 Nr. 1 AO am vierten Tag nach der Aufgabe zur Post als bekannt gegeben, falls er "
                f"Sie nicht nachweislich erst später oder gar nicht erreicht hat. Der Einspruch ist schriftlich oder elektronisch "
                f"{bei(org.name)} einzulegen oder dort zur Niederschrift zu erklären.",
                size=8.9,
            ),
            Sign("Mit freundlichen Grüßen", ("Im Auftrag", "Veranlagungsstelle Arbeitnehmer")),
        ]
        info = [("Steuernummer", stnr), ("Bearbeitung", "Herr Kowalczyk · Durchwahl -318")]
        if posted != letter_date:
            info.append(("Zur Post gegeben am", de(posted)))
        letter = Letter(
            org=org, recipient=person, info=info, date_line=place_line(org, letter_date),
            subject=f"Bescheid für {year} über Einkommensteuer und Solidaritätszuschlag",
            salutation="Sehr geehrte Damen und Herren,", blocks=blocks,
            style=STYLES["F"], created=created(letter_date), running_ref=f"Steuernummer {stnr}",
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="tax_assessment", variant="F", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=letter_date, references=[("Steuernummer", stnr)],
                        amounts=[float(abs(diff))], remedy="einspruch", items=items),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), de(posted), "Die Einspruchsfrist beträgt einen Monat", stnr, *([de(pay_due)] if pay_due else [])],
            notes="Posting day stated in the info block, later than the Bescheid date." if posted != letter_date else "",
        )  # fmt: skip

    # F1 — SL, Bescheid Mon 12.05.2025, posted Wed 14.05.2025 → day 4 = Sun 18.05. → Mon 19.05. → Thu 19.06.2025 Fronleichnam
    # (SL) → Fri 20.06.2025. Fälligkeit printed by the office from the Bescheid date: Thu 12.06.2025.
    cases.append(variant_f("holdout-tax_assessment-F1", O.H_FA_SL, O.H_SL, date(2025, 5, 12), date(2025, 5, 14), 2024, "040/251/08813",
                           58_720, 2_655, 7_390, 10_702, 9_866, "2025-06-20", date(2025, 6, 12), "2025-06-12"))  # fmt: skip
    # F2 — ST. Posted Mon 22.02.2027 → day 4 = Fri 26.02. → Fri 26.03.2027 Karfreitag → Sat, Sun, Mon 29.03. Ostermontag → Tue 30.03.
    cases.append(variant_f("holdout-tax_assessment-F2", O.H_FA_ST, O.H_ST, date(2027, 2, 22), date(2027, 2, 22), 2025, "102/148/05527",
                           41_205, 2_104, 5_873, 5_496, 6_157, "2027-03-30"))  # fmt: skip
    return cases


# ==================================================================================================
# Family 2 — municipal_decision (Land VwVfG: 4th-day fiction WITHOUT shift; Widerspruch/Klage)
# ==================================================================================================


def _rbb_municipal(org: Org, wording: str, court: tuple[str, str] | None = None) -> P:
    """One Belehrung per holdout variant; none repeats a sentence of variants A–D."""
    if court is not None:
        text = (
            "**Rechtsbehelfsbelehrung:** Gegen diese Ordnungsverfügung können Sie Klage erheben. Die Klage ist **binnen eines Monats "
            f"nach der Bekanntgabe dieser Verfügung** beim Verwaltungsgericht {court[0]}, {court[1]}, schriftlich oder zur Niederschrift "
            "des Urkundsbeamten der Geschäftsstelle einzureichen; ein Widerspruchsverfahren ist nach § 110 JustG NRW ausgeschlossen."
        )
    elif wording == "E":
        text = (
            "Möchten Sie die Entscheidung anfechten, erheben Sie Widerspruch – **innerhalb eines Monats, gerechnet ab der "
            f"Bekanntgabe,** schriftlich, elektronisch mit qualifizierter Signatur oder zur Niederschrift {bei(org.name)}, "
            f"{org.street}, {org.postcode} {org.city}. Wird der Bescheid mit der Post verschickt, ist er nach dem "
            "Landesverwaltungsverfahrensrecht am vierten Tag nach der Aufgabe zur Post bekannt gegeben."
        )
    else:
        text = (
            "**Rechtsbehelfsbelehrung:** Wenn Sie mit dieser Entscheidung nicht einverstanden sind, können Sie Widerspruch einlegen. "
            f"Ihr Widerspruch muss **spätestens einen Monat nach Bekanntgabe** dieses Bescheids {bei(org.name)}, {org.street}, "
            f"{org.postcode} {org.city}, eingehen – schriftlich, elektronisch mit qualifizierter Signatur oder zur Niederschrift."
        )
    return P(text, size=8.9)


MUNICIPAL_KEY = {
    "E": "innerhalb eines Monats, gerechnet ab der Bekanntgabe,",
    "F": "spätestens einen Monat nach Bekanntgabe",
    "F-klage": "binnen eines Monats nach der Bekanntgabe dieser Verfügung",
}


def municipal_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, posted: date, remedy: str, subject: str,
             az: str, body: list[Block], hand: str, extra_items: list | None = None, photo: bool = False,
             court: tuple[str, str] | None = None, key: list[str] | None = None, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="vwvfg", remedy=remedy, region=org.region,
                           title="Klagefrist" if remedy == "klage" else "Widerspruchsfrist",
                           note=("Remedy is Klage: SPEC §21 shows a 'get advice' card instead of a computed date; the legal date is "
                                 "still the label.") if remedy == "klage" else None),
            hand,
        )  # fmt: skip
        rbb = _rbb_municipal(org, variant, court)
        if variant == "E":
            info = [("Aktenzeichen", az), ("Sachbearbeitung", "Frau Kurz, Zimmer 107"), ("Telefon", "Durchwahl -4471"),
                    ("Datum", de(posted))]  # fmt: skip
            tail: list[Block] = [
                H("Rechtsbehelfsbelehrung"),
                rbb,
                Sign("Mit freundlichen Grüßen", ("Kurz",), signature=True),
            ]
            date_line = None
        else:
            info = [("Geschäftszeichen", az), ("Auskunft", "Herr Petersen, Raum 3.12")]
            tail = [rbb, Sign("Mit freundlichen Grüßen", ("Im Auftrag", "Petersen"), signature=True)]
            date_line = place_line(org, posted)
        letter = Letter(
            org=org, recipient=person, info=info, subject=subject, salutation=salutation, date_line=date_line,
            blocks=[*body, *tail], style=STYLES[variant], created=created(posted), running_ref=f"Az. {az}",
        )  # fmt: skip
        key_rbb = MUNICIPAL_KEY["F-klage" if court else variant]
        return Case(
            id=case_id, split="holdout", family="municipal_decision", variant=variant, letter=letter,
            truth=truth(kind="authority_letter", sender=org.name, document_date=posted, references=[("Aktenzeichen" if variant == "E" else "Geschäftszeichen", az)],
                        amounts=[], remedy=remedy, items=[item, *(extra_items or [])]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), az, key_rbb, *(key or [])], photo=photo, notes=notes,
        )  # fmt: skip

    # E1 — BW, Widerspruch. Posted Wed 06.08.2025 → day 4 = Sun 10.08. (no shift) → Wed 10.09.2025.
    cases.append(make(
        "holdout-municipal_decision-E1", "E", O.H_STADT_BW, O.H_BW, "Sehr geehrter Herr Musterle,", date(2025, 8, 6), "widerspruch",
        "Antrag auf Erteilung eines Bewohnerparkausweises für die Zone B 4 – Ablehnung", "32.21-BP-2025-0833",
        [
            P("Ihren Antrag vom 21.07.2025 auf Ausstellung eines Bewohnerparkausweises für das Fahrzeug mit dem amtlichen Kennzeichen "
              "BGN-AM 740 lehnen wir ab."),
            P("Ein Bewohnerparkausweis wird nur für ein Fahrzeug erteilt, das auf eine Person mit Hauptwohnung im Bewohnerparkgebiet "
              "zugelassen ist oder von ihr nachweislich dauerhaft genutzt wird. Das Fahrzeug ist auf die Beispiel Pflegedienst GmbH "
              "zugelassen; eine dauerhafte private Nutzung durch Sie ist nicht belegt."),
            P("Für diese Entscheidung werden keine Gebühren erhoben."),
        ],
        "2025-09-10",
    ))  # fmt: skip

    # E2 — SH, Widerspruch. Posted Mon 01.09.2025 → day 4 = Fri 05.09. → Sun 05.10.2025 → Mon 06.10.2025.
    cases.append(make(
        "holdout-municipal_decision-E2", "E", O.H_KREIS_SH, O.H_SH, "Sehr geehrte Frau Beispielsen,", date(2025, 9, 1), "widerspruch",
        "Befreiung von der Landschaftsschutzverordnung „Mustersee-Niederung“ für einen Bootssteg – Ablehnung", "67.3-LSG-2025-0214",
        [
            P("Ihren Antrag vom 12.06.2025 auf Befreiung für die Errichtung eines 14 m langen Holzstegs am Ufer Ihres Grundstücks "
              "Deichstraße 44 lehne ich ab."),
            P("Das Vorhaben liegt im Landschaftsschutzgebiet „Mustersee-Niederung“. Der Uferstreifen ist Brut- und Rastgebiet "
              "geschützter Vogelarten. Eine Befreiung nach § 67 BNatSchG ist nur möglich, wenn überwiegende öffentliche Interessen sie "
              "erfordern oder das Verbot im Einzelfall zu einer unzumutbaren Belastung führt; beides liegt nicht vor."),
        ],
        "2025-10-06", photo=True,
    ))  # fmt: skip

    # F1 — NW, Klage + compliance date. Posted Mon 27.09.2027 → day 4 = Fri 01.10. → Mon 01.11.2027 Allerheiligen (NW) → Tue 02.11.
    posted, comply = date(2027, 9, 27), date(2027, 11, 30)
    task = check(
        fixed_item(due=comply, region="NW", kind="task", nature="other", title="Wohnnutzung des Gartenhauses aufgeben",
                   rule="Compliance deadline set by the authority as a calendar date."),
        "2027-11-30",
    )  # fmt: skip
    cases.append(make(
        "holdout-municipal_decision-F1", "F", O.H_STADT_NW, O.H_NW, "Sehr geehrter Herr Beispielkötter,", posted, "klage",
        "Ordnungsverfügung – Untersagung der Wohnnutzung des Gartenhauses auf dem Grundstück Zechenweg 3", "63.4-NU-2027-0391",
        [
            P("bei einer Ortsbesichtigung am 07.09.2027 hat die Bauaufsicht festgestellt, dass das Gartenhaus im rückwärtigen Teil "
              "Ihres Grundstücks dauerhaft bewohnt wird. Eine Baugenehmigung für eine Wohnnutzung liegt nicht vor und könnte auch "
              "nicht erteilt werden."),
            P("Ich untersage Ihnen daher auf Grundlage der Landesbauordnung (BauO NRW), das Gartenhaus zu Wohnzwecken zu nutzen. "
              f"Die Wohnnutzung ist **bis zum {de(comply)}** vollständig aufzugeben. Kommen Sie dem nicht nach, wird ein Zwangsgeld "
              "in Höhe von 1.500,00 € fällig, das ich hiermit androhe."),
        ],
        "2027-11-02", extra_items=[task], court=("Musterkirchen", "Justizplatz 1, 45879 Musterkirchen"), key=[de(comply)],
        notes="The Klage period ends on Allerheiligen (01.11.2027), a holiday in NW — moved to Tuesday.",
    ))  # fmt: skip

    # F2 — HH, Widerspruch. Posted Thu 02.04.2026 → day 4 = Mon 06.04. Ostermontag (no shift) → Wed 06.05.2026.
    cases.append(make(
        "holdout-municipal_decision-F2", "F", O.H_BA_HH, O.H_HH, "Sehr geehrte Frau Musterbrook,", date(2026, 4, 2), "widerspruch",
        "Anordnung nach dem Hamburgischen Wohnraumschutzgesetz – Wohnung Grindelhof 21, 3. OG links", "WS 22/2026-0187",
        [
            P("nach unseren Ermittlungen bieten Sie die oben genannte Wohnung seit Januar 2026 über Online-Plattformen tageweise an "
              "Feriengäste an. Eine Genehmigung für diese Zweckentfremdung von Wohnraum liegt nicht vor; eine Wohnraumschutznummer "
              "haben Sie nicht beantragt."),
            P("Wir geben Ihnen daher auf, die Vermietung an wechselnde Gäste zu beenden und die Wohnung wieder zum dauerhaften "
              "Wohnen zu nutzen oder zu vermieten. Kommen Sie dieser Anordnung nicht nach, kann ein Zwangsgeld festgesetzt werden."),
        ],
        "2026-05-06",
        notes="The deemed-delivery day is Ostermontag; outside tax law it does not move.",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 3 — social_decision (SGB X: 4th-day fiction WITHOUT shift; § 84 SGG one month)
# ==================================================================================================


def _rbb_social(org: Org, wording: str) -> P:
    if wording == "E":
        text = (
            "Halten Sie die Entscheidung für falsch, legen Sie **innerhalb eines Monats nach Bekanntgabe des Bescheids** Widerspruch "
            f"ein – schriftlich oder zur Niederschrift {bei(org.name)}. Es genügt, wenn er innerhalb dieser Zeit bei einer anderen "
            "inländischen Behörde oder einem anderen Sozialversicherungsträger ankommt."
        )
    else:
        text = (
            "**Rechtsbehelfsbelehrung:** Dieser Bescheid kann binnen eines Monats, nachdem er Ihnen bekannt gegeben wurde, mit dem "
            f"Widerspruch angefochten werden. Den Widerspruch können Sie schriftlich, elektronisch oder zur Niederschrift {bei(org.name)} "
            f"({org.street}, {org.postcode} {org.city}) einlegen."
        )
    return P(text, size=8.8)


SOCIAL_KEY = {
    "E": "innerhalb eines Monats nach Bekanntgabe des Bescheids",
    "F": "binnen eines Monats, nachdem er Ihnen bekannt gegeben wurde",
}


def social_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, posted: date, kind: str, subject: str,
             refs: list[tuple[str, str]], body: list[Block], hand: str, amounts: list[float] | None = None,
             extra_items: list | None = None, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted,
                scope="sgbx",
                remedy="widerspruch",
                region=org.region,
                title="Widerspruchsfrist",
            ),
            hand,
        )
        rbb = _rbb_social(org, variant)
        if variant == "E":
            info = [*refs, ("Datum", de(posted))]
            tail: list[Block] = [
                H("Rechtsbehelfsbelehrung"),
                rbb,
                Sign("Freundliche Grüße", (f"Ihre {org.name}",)),
            ]
            date_line = None
        else:
            info = list(refs)
            tail = [rbb, Sign("Mit freundlichen Grüßen", ("Im Auftrag", "Brandstetter"))]
            date_line = place_line(org, posted)
        letter = Letter(
            org=org, recipient=person, info=info, subject=subject, salutation=salutation, date_line=date_line,
            blocks=[*body, *tail], style=STYLES[variant], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="social_decision", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts or [], remedy="widerspruch",
                        items=[item, *(extra_items or [])]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), SOCIAL_KEY[variant]], photo=photo, notes=notes,
        )  # fmt: skip

    # E1 — Ersatzkasse, Land unknown. Posted Wed 25.06.2025 → day 4 = Sun 29.06. (no shift) → Tue 29.07.2025.
    cases.append(make(
        "holdout-social_decision-E1", "E", O.H_KK, O.H_GEN, "Sehr geehrte Frau Mustermeier,", date(2025, 6, 25), "health_insurance",
        "Ihr Antrag auf Übernahme von Fahrkosten zur ambulanten Behandlung", [("Versichertennummer", "K718204553"), ("Vorgang", "FK-25-061930")],
        [
            P("vielen Dank für Ihren Antrag vom 10.06.2025. Sie möchten, dass wir die Kosten für Taxifahrten zu Ihrer ambulanten "
              "Physiotherapie übernehmen."),
            P("Fahrkosten zu einer ambulanten Behandlung dürfen wir nur in Ausnahmefällen übernehmen, zum Beispiel bei Pflegegrad 3 "
              "mit dauerhaft eingeschränkter Mobilität oder bei den Merkzeichen aG, Bl oder H im Schwerbehindertenausweis (§ 60 SGB V). "
              "Diese Voraussetzungen liegen bei Ihnen nicht vor. Wir müssen Ihren Antrag deshalb ablehnen."),
        ],
        "2025-07-29",
    ))  # fmt: skip

    # E2 — Pflegekasse, Land unknown. Posted Fri 28.03.2025 → day 4 = Tue 01.04. → Thu 01.05.2025 Tag der Arbeit → Fri 02.05.2025.
    cases.append(make(
        "holdout-social_decision-E2", "E", O.H_PK, O.H_GEN2, "Sehr geehrter Herr Beispiel,", date(2025, 3, 28), "health_insurance",
        "Bescheid über Leistungen der Pflegeversicherung – Pflegegrad 2", [("Versichertennummer", "P440918267"), ("Az.", "PG-25-018844")],
        [
            P("auf Grundlage des Gutachtens des Medizinischen Dienstes vom 12.03.2025 stellen wir bei Ihnen ab dem 01.02.2025 den "
              "Pflegegrad 2 fest. Den beantragten Pflegegrad 3 können wir nicht zuerkennen: Im Gutachten wurden 38,75 gewichtete "
              "Gesamtpunkte ermittelt."),
            P("Sie erhalten ab Februar 2025 ein Pflegegeld von **347,00 € monatlich**, solange Sie Ihre Pflege selbst sicherstellen. "
              "Wir zahlen es jeweils zum Monatsende auf Ihr Konto."),
        ],
        "2025-05-02", amounts=[347.0], photo=True,
    ))  # fmt: skip

    # F1 — Jobcenter BY + submission date. Posted Fri 23.04.2027 → day 4 = Tue 27.04. → Thu 27.05.2027 Fronleichnam (BY) → Fri 28.05.
    posted, submit = date(2027, 4, 23), date(2027, 5, 14)
    task = check(
        fixed_item(due=submit, region="BY", kind="task", nature="declaration", title="Lohnabrechnungen Februar bis April 2027 einreichen",
                   rule="Submission deadline set by the authority as a calendar date."),
        "2027-05-14",
    )  # fmt: skip
    cases.append(make(
        "holdout-social_decision-F1", "F", O.H_JC_BY, O.H_BY, "Sehr geehrte Frau Beispielhuber,", posted, "social_insurance",
        "Vorläufige Bewilligung von Leistungen zur Sicherung des Lebensunterhalts (SGB II)",
        [("BG-Nummer", "08154//0042731"), ("Kundennummer", "731D882405")],
        [
            P("für die Zeit vom 01.05.2027 bis 31.10.2027 bewilligen wir Ihnen vorläufig Leistungen von monatlich **1.087,60 €**. "
              "Vorläufig ist die Bewilligung, weil Ihr Einkommen aus der geringfügigen Beschäftigung noch nicht feststeht (§ 41a SGB II)."),
            P(f"Reichen Sie uns bitte **bis {de(submit)}** Ihre Lohnabrechnungen für Februar bis April 2027 ein. Ohne diese Nachweise "
              "kann für die betroffenen Monate festgestellt werden, dass kein Leistungsanspruch bestand (§ 41a Abs. 3 SGB II)."),
        ],
        "2027-05-28", amounts=[1087.60], extra_items=[task],
        notes="The Widerspruch period ends on Fronleichnam (27.05.2027), a holiday in BY — moved to Friday.",
    ))  # fmt: skip

    # F2 — Elterngeldstelle MV. Posted Mon 16.11.2026 → day 4 = Fri 20.11. → Sun 20.12.2026 → Mon 21.12.2026.
    cases.append(make(
        "holdout-social_decision-F2", "F", O.H_ELG_MV, O.H_MV, "Sehr geehrte Frau Beispielow,", date(2026, 11, 16), "social_insurance",
        "Bescheid über Elterngeld für Ihr Kind Emil, geboren am 14.08.2026", [("Aktenzeichen", "EG-26-3318-MV")],
        [
            P("auf Ihren Antrag vom 21.09.2026 bewilligen wir Ihnen Basiselterngeld für den 1. bis 12. Lebensmonat Ihres Kindes. Das "
              "Elterngeld beträgt **1.412,35 € monatlich**; die Berechnung finden Sie in der Anlage."),
            P("Auf den 1. und 2. Lebensmonat wird das Mutterschaftsgeld angerechnet, für diese Monate zahlen wir daher nichts aus. "
              "Ändert sich Ihr Einkommen während des Bezugs, teilen Sie uns das bitte unverzüglich mit."),
        ],
        "2026-12-21", amounts=[1412.35],
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 7 — fine_bussgeld (OWiG: Einspruch 2 weeks after Zustellung, § 67 OWiG, § 43 StPO)
# ==================================================================================================


def fine_bussgeld() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, letter_date: date, served: date, plate: str, when: str, place: str,
             charge: str, rules: str, fine: float, points: int, hand: str, az: str) -> Case:  # fmt: skip
        objection = check(
            event_period_item(
                event=served, amount=2, unit="weeks", region=org.region, kind="deadline", nature="objection",
                title="Einspruchsfrist Bußgeldbescheid", anchor="explicit_date",
                rule="Einspruch against a Bußgeldbescheid: two weeks after Zustellung (§ 67 Abs. 1 OWiG); Zustellung by "
                     "Postzustellungsurkunde on the date noted on the envelope (§ 180 ZPO); computation § 43 StPO i.V.m. § 46 Abs. 1 OWiG.",
                shift_citation="§ 43 Abs. 2 StPO i.V.m. § 46 Abs. 1 OWiG",
            ),
            hand,
        )  # fmt: skip
        fee, costs = 25.0, 3.50
        total = fine + fee + costs
        payment = undated_item(
            kind="payment", nature="payment", title="Geldbuße und Kosten zahlen", amount=total,
            spec=spec("relative", anchor="explicit_date", amount=2, unit="weeks", shift=True),
            derivation="Payable two weeks after the Bußgeldbescheid becomes final (Rechtskraft); the date depends on whether an "
                       "Einspruch is filed, so it is not date-scored.",
        )  # fmt: skip
        points_text = f"{points} Punkt" if points == 1 else f"{points} Punkte"
        amounts_table = Table(rows=(("Geldbuße", eur_plain(fine)), ("Gebühr des Verfahrens", eur_plain(fee)),
                                    ("Auslagen für die Zustellung", eur_plain(costs)), ("Zu zahlender Betrag", eur_plain(total))),
                              header=("Rechtsfolgen", "Euro"), bold_rows=(3,), rule_before=(3,))  # fmt: skip
        if variant == "E":
            info = [("Aktenzeichen", az), ("Kennzeichen", plate), ("Datum", de(letter_date))]
            refs = [("Aktenzeichen", az), ("Kennzeichen", plate)]
            blocks: list[Block] = [
                H("Tatvorwurf"),
                P(
                    f"Sie haben am {when} in {place} als Führer des Personenkraftwagens mit dem amtlichen Kennzeichen {plate} folgende "
                    f"Ordnungswidrigkeit begangen: {charge}"
                ),
                P(
                    f"Angewendete Vorschriften: {rules}. Beweismittel: Messprotokoll, Frontfoto, Zeugenaussage.",
                    size=8.6,
                ),
                amounts_table,
                P(
                    f"Die Entscheidung wird im Fahreignungsregister mit {points_text} eingetragen. Sobald der Bescheid rechtskräftig ist, "
                    "haben Sie für die Zahlung des Gesamtbetrags zwei Wochen Zeit; geben Sie als Verwendungszweck bitte das Aktenzeichen an."
                ),
                H("Rechtsbehelfsbelehrung"),
                P(
                    "Einspruch gegen diesen Bußgeldbescheid können Sie **innerhalb von zwei Wochen nach seiner Zustellung** einlegen. "
                    f"Der Einspruch ist schriftlich oder zur Niederschrift {bei(org.name)} zu erklären und muss dort innerhalb der Frist "
                    "eingehen. Versäumen Sie die Frist, erlangt der Bescheid Rechtskraft und die Geldbuße kann beigetrieben werden.",
                    size=8.8,
                ),
            ]
            note, key = f"Zugestellt: {de(served)}", "innerhalb von zwei Wochen nach seiner Zustellung"
            date_line = None
        else:
            info = [("Geschäftszeichen", az), ("Amtl. Kennzeichen", plate)]
            refs = [("Geschäftszeichen", az), ("Amtl. Kennzeichen", plate)]
            blocks = [
                P(
                    f"Ihnen wird zur Last gelegt, am {when} in {place} mit dem Fahrzeug {plate} folgende Verkehrsordnungswidrigkeit "
                    f"begangen zu haben: {charge}",
                    gap=1.4,
                ),
                P(f"({rules})", size=8.6, indent=4),
                amounts_table,
                P(
                    f"Eintragung im Fahreignungsregister: {points_text}. Fälligkeit des Gesamtbetrags: zwei Wochen nach Eintritt der Rechtskraft."
                ),
                P(
                    "**Rechtsbehelfsbelehrung:** Wenn Sie den Vorwurf bestreiten oder die Rechtsfolgen nicht hinnehmen wollen, können Sie "
                    "Einspruch einlegen. Die Frist für den Einspruch beträgt **zwei Wochen ab Zustellung**; einzulegen ist er schriftlich "
                    f"oder zur Niederschrift {bei(org.name)}. Das Gericht ist "
                    "nach einem Einspruch an die hier festgesetzte Geldbuße nicht gebunden und kann auch zu Ihrem Nachteil entscheiden.",
                    size=8.8,
                ),
            ]
            note, key = f"{de(served)} zugestellt", "zwei Wochen ab Zustellung"
            date_line = place_line(org, letter_date)
        blocks.append(Envelope(sender=org.name, recipient=person, reference=az, note=note, initials="Hö."))
        letter = Letter(
            org=org, recipient=person, info=info, date_line=date_line, subject="Bußgeldbescheid", blocks=blocks,
            style=STYLES[variant], created=created(letter_date), running_ref=f"Az. {az}",
        )  # fmt: skip
        today = max(today_after(letter_date, case_id), today_after(served, case_id, 0, 2))
        return Case(
            id=case_id, split="holdout", family="fine_bussgeld", variant=variant, letter=letter,
            truth=truth(kind="fine", sender=org.name, document_date=letter_date, references=refs, amounts=[total, fine],
                        remedy="einspruch", items=[objection], optional_items=[payment]),
            today=today, authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), key, de(served), az],
            notes="Zustellung date is noted on the yellow envelope (page 2), not the Bescheid date.",
        )  # fmt: skip

    # E1 — TH: served Tue 22.09.2026 → Tue 06.10.2026 (working day).
    cases.append(make(
        "holdout-fine_bussgeld-E1", "E", O.H_BG_TH, O.H_TH, date(2026, 9, 18), date(2026, 9, 22), "MRO-OR 55", "31.08.2026 um 07:48 Uhr",
        "Musterrode, Kreuzung Erfurter Straße / Anger",
        "Sie missachteten das Rotlicht der Lichtzeichenanlage; die Rotphase dauerte zum Zeitpunkt des Überfahrens der Haltlinie "
        "weniger als eine Sekunde.", "§ 37 Abs. 2, § 49 StVO; § 24 StVG; 132 BKat", 90.0, 1, "2026-10-06", "BG 311/26-4471",
    ))  # fmt: skip
    # E2 — Land unknown: served Sat 08.11.2025 → Sat 22.11.2025 → Mon 24.11.2025.
    cases.append(make(
        "holdout-fine_bussgeld-E2", "E", O.H_BG_X, O.H_GEN2, date(2025, 11, 5), date(2025, 11, 8), "MB-TB 318", "14.10.2025 um 16:22 Uhr",
        "Musterbergen, Bundesstraße 3, Höhe Einmündung Lahnufer",
        "Sie benutzten während der Fahrt ein Mobiltelefon, das Sie hierfür in der Hand hielten.",
        "§ 23 Abs. 1a, § 49 StVO; § 24 StVG; 246.1 BKat", 100.0, 1, "2025-11-24", "ZBS 25-0918-337",
    ))  # fmt: skip
    # F1 — MV: served Mon 22.02.2027 → Mon 08.03.2027 Frauentag (MV) → Tue 09.03.2027.
    cases.append(make(
        "holdout-fine_bussgeld-F1", "F", O.H_BG_MV, O.H_MV, date(2027, 2, 17), date(2027, 2, 22), "BMÜ-IB 12", "26.01.2027 um 13:05 Uhr",
        "Beispielmünde, Strandstraße Höhe Haus Nr. 30",
        "Sie überschritten innerhalb geschlossener Ortschaften die zulässige Höchstgeschwindigkeit von 50 km/h um 21 km/h.",
        "§ 3 Abs. 3, § 49 StVO; § 24 StVG; 11.3.4 BKat", 115.0, 1, "2027-03-09", "32.4-OWI-2027-01188",
    ))  # fmt: skip
    # F2 — RP: served Thu 17.04.2025 → Thu 01.05.2025 Tag der Arbeit → Fri 02.05.2025.
    cases.append(make(
        "holdout-fine_bussgeld-F2", "F", O.H_BG_RP, O.H_RP, date(2025, 4, 14), date(2025, 4, 17), "MWL-JB 77", "19.03.2025 um 09:41 Uhr",
        "Musterweiler, A 1, km 128,6, Fahrtrichtung Süd",
        "Sie hielten bei einer Geschwindigkeit von 112 km/h nicht den erforderlichen Abstand von einem vorausfahrenden Fahrzeug; "
        "der Abstand betrug weniger als 4/10 des halben Tachowertes.", "§ 4 Abs. 1, § 49 StVO; § 24 StVG; 12.6.2 BKat", 100.0, 1,
        "2025-05-02", "BGS 2025/10744",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 12 — year_boundary (old 3-day rule in December 2024, month ends, New Year)
# ==================================================================================================


def year_boundary() -> list[Case]:
    cases: list[Case] = []

    # --- variant E: AO notices, short form, heading-style Belehrung ----------------------------------
    def variant_e(case_id: str, org: Org, person: Person, posted: date, subject: str, body: list[Block], ref: tuple[str, str],
                  amount: float, hand: str, day_word: str, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="ao", remedy="einspruch", region=None, title="Einspruchsfrist"
            ),
            hand,
        )
        letter = Letter(
            org=org, recipient=person, info=[ref, ("Datum", de(posted)), ("Rückfragen", "Servicestelle, Durchwahl -200")],
            subject=subject,
            blocks=[
                *body,
                H("Rechtsbehelfsbelehrung"),
                P("Sie können diesen Bescheid **binnen eines Monats nach seiner Bekanntgabe** mit dem Einspruch anfechten, der "
                  "schriftlich, elektronisch oder zur Niederschrift bei der erlassenden Stelle einzulegen ist. Als bekannt gegeben gilt "
                  f"ein mit einfachem Brief versandter Bescheid am {day_word} Tag nach der Aufgabe zur Post, sofern er nicht später "
                  "zugegangen ist.", size=8.9),
                P("Maschinell erstellt – ohne Unterschrift gültig.", size=7.8),
            ],
            style=STYLES["E"], created=created(posted), running_ref=f"{ref[0]} {ref[1]}",
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="year_boundary", variant="E", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=posted, references=[ref], amounts=[amount],
                        remedy="einspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "binnen eines Monats nach seiner Bekanntgabe", f"am {day_word} Tag nach der Aufgabe zur Post, sofern"],
            notes=notes,
        )  # fmt: skip

    # E1 — posted Tue 10.12.2024 → day 3 = Fri 13.12.2024 (working day) → Mon 13.01.2025.
    # (The 4-day rule would give Sat 14.12. → Mon 16.12. → Thu 16.01.2025.)
    cases.append(variant_e(
        "holdout-year_boundary-E1", O.H_FA_X, O.H_GEN, date(2024, 12, 10), "Bescheid für 2023 über Einkommensteuer",
        [P("Die Einkommensteuer für 2023 wird auf 3.284,00 € festgesetzt. Nach Anrechnung der einbehaltenen Lohnsteuer von "
           "3.911,00 € ergibt sich eine Erstattung von **627,00 €**, die wir auf Ihr Konto überweisen.")],
        ("Steuernummer", "20/233/15084"), 627.0, "2025-01-13", "dritten",
        notes="Posted before 2025-01-01: 3-day fiction (Art. 97 § 1 Abs. 15 EGAO).",
    ))  # fmt: skip
    # E2 — posted Mon 25.01.2027 → day 4 = Fri 29.01.2027 → 29.02. does not exist → Sun 28.02.2027 (§ 188 Abs. 3 BGB) → Mon 01.03.
    cases.append(variant_e(
        "holdout-year_boundary-E2", O.H_FA_X2, O.H_GEN2, date(2027, 1, 25),
        "Bescheid über die gesonderte Feststellung des verbleibenden Verlustvortrags zur Einkommensteuer auf den 31.12.2025",
        [P("Der verbleibende Verlustvortrag zur Einkommensteuer auf den 31.12.2025 wird auf **4.806,00 €** festgestellt. Er "
           "ergibt sich aus den negativen Einkünften Ihres Masterstudiums (vorweggenommene Werbungskosten) und wird mit künftigen "
           "positiven Einkünften verrechnet.")],
        ("Steuernummer", "031/860/42219"), 4806.0, "2027-03-01", "vierten",
    ))  # fmt: skip
    # E3 — posted Thu 31.12.2026 → day 4 = Mon 04.01.2027 (working day) → Thu 04.02.2027.
    cases.append(variant_e(
        "holdout-year_boundary-E3", O.H_FA_X, O.H_GEN, date(2026, 12, 31), "Geänderter Bescheid für 2025 über Einkommensteuer",
        [P("Der Bescheid vom 14.08.2026 wird nach § 173 Abs. 1 Nr. 2 AO geändert, weil Sie die Zuwendungsbestätigung über Ihre "
           "Spende an den Beispiel Tierschutzverein e. V. nachgereicht haben. Es ergibt sich eine weitere Erstattung von **212,40 €**.")],
        ("Steuernummer", "20/233/15084"), 212.4, "2027-02-04", "vierten",
    ))  # fmt: skip

    # --- variant F: SGB X decisions with place/date line and inline Belehrung -------------------------
    def variant_f(case_id: str, org: Org, person: Person, posted: date, subject: str, body: list[Block], refs: list[tuple[str, str]],
                  kind: str, amounts: list[float], hand: str, day_word: str, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="sgbx", remedy="widerspruch", region=None, title="Widerspruchsfrist"
            ),
            hand,
        )
        letter = Letter(
            org=org, recipient=person, info=refs, date_line=place_line(org, posted), subject=subject,
            salutation="Guten Tag,",
            blocks=[
                *body,
                P("**Rechtsbehelfsbelehrung:** Sind Sie mit diesem Bescheid nicht einverstanden, steht Ihnen der Widerspruch offen. Er "
                  "muss uns innerhalb eines Monats nach Bekanntgabe schriftlich oder zur Niederschrift erreichen "
                  f"({org.name}, {org.street}, {org.postcode} {org.city}). Übersenden wir den Bescheid per Post, gilt er am {day_word} "
                  "Tag nach Aufgabe zur Post als bekannt gegeben.", size=8.9),
                Sign("Mit freundlichen Grüßen", (org.name,)),
            ],
            style=STYLES["F"], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split="holdout", family="year_boundary", variant="F", letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts, remedy="widerspruch",
                        items=[item]),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "muss uns innerhalb eines Monats nach Bekanntgabe", f"am {day_word} Tag nach Aufgabe zur Post"],
            photo=photo, notes=notes,
        )  # fmt: skip

    # F1 — posted Thu 27.08.2026 → day 4 = Mon 31.08.2026 → 31.09. does not exist → Wed 30.09.2026 (§ 188 Abs. 3 BGB).
    cases.append(variant_f(
        "holdout-year_boundary-F1", O.H_AA_X, O.H_GEN2, date(2026, 8, 27), "Aufhebung der Bewilligung von Arbeitslosengeld ab 01.09.2026",
        [P("Sie nehmen am 01.09.2026 eine versicherungspflichtige Beschäftigung auf. Die Bewilligung von Arbeitslosengeld wird "
           "deshalb ab diesem Tag aufgehoben (§ 48 Abs. 1 SGB X). Für den August 2026 zahlen wir Ihnen noch **1.318,20 €**.")],
        [("Kundennummer", "912A507733")], "social_insurance", [1318.20], "2026-09-30", "vierten", photo=True,
    ))  # fmt: skip
    # F2 — posted Thu 12.12.2024 → day 3 = Sun 15.12.2024 (no shift) → Wed 15.01.2025.
    cases.append(variant_f(
        "holdout-year_boundary-F2", O.H_UK_X, O.H_GEN, date(2024, 12, 12), "Ihr Unfall vom 04.11.2024 – keine Anerkennung als Arbeitsunfall",
        [P("nach unseren Ermittlungen haben Sie den Weg zur Arbeit am 04.11.2024 für einen privaten Einkauf unterbrochen; der Sturz "
           "ereignete sich im Supermarkt. Der Unfall ist deshalb kein versicherter Wegeunfall im Sinne des § 8 Abs. 2 Nr. 1 SGB VII. "
           "Die Kosten der Behandlung rechnet Ihre Krankenkasse ab.")],
        [("Aktenzeichen", "UK-24-11-07715")], "social_insurance", [], "2025-01-15", "dritten",
        notes="Posted before 2025-01-01: 3-day fiction; outside tax law the Sunday fiction day does not move.",
    ))  # fmt: skip
    return cases
