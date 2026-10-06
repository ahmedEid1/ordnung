"""Holdout3 split, families 1, 2, 3, 7 and 12: variants I and J of the administrative acts.

Written after the code freeze for this release, from the law and from how such letters read, without opening the app's
ingestion code, its prompts, the recordings or the results files: new senders, recipients, wording, layout, dates,
amounts and regions (Länder the earlier splits used little: MV, SL, HB, BB, RP, NI). Variant I prints the date as the
last line of the information block and the Rechtsbehelfsbelehrung as a run-in paragraph; variant J names the date in
the information block under its own label and, where the letter runs to a second page, prints the Belehrung there under
a heading. No deadline-bearing sentence of variants A–H recurs (``evals/verify_labels.py`` checks it).

The posting, letter and service days were drawn with a seeded random choice among the days that fit each letter's
scenario (``rng_for("holdout3", case_id)``; a day another split already uses was left out, and so was a label another
split already has, or, where that left no day, a label of the same family); ``hand`` is the expected date worked out by
hand from the calendar and is asserted against the computed label.
"""

from __future__ import annotations

from datetime import date

from . import law
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
from .holdout2_admin import VWGO_SHIFT
from .pdf import Block, Envelope, H, Letter, Org, P, PageBreak, Person, Sign, Style, Table
from .text import bei, de, eur, eur_plain, iban_grouped

SPLIT = "holdout3"
STYLES = {
    "I": Style(body_pt=9.9, left=24, right=19, leading=1.37, para_gap=2.3, align="J", info_label_pt=7.1,
               info_value_pt=8.5, subject_pt=11.0),
    "J": Style(body_pt=10.2, left=22, right=23, leading=1.31, para_gap=2.0, align="L", info_label_pt=7.4,
               info_value_pt=8.8, subject_pt=10.6),
}  # fmt: skip


def dated_last(refs: list[tuple[str, str]], d: date) -> list[tuple[str, str]]:
    """Variant I: the date is the last line of the information block."""
    return [*refs, ("Datum", de(d))]


def run_in(text: str, label: str = "Rechtsbehelfsbelehrung") -> P:
    """Variant I's Belehrung: a run-in paragraph in small type."""
    return P(f"**{label}:** {text}", size=8.7)


def page_two(*paragraphs: str, heading: str = "Rechtsbehelfsbelehrung") -> list[Block]:
    """Variant J's Belehrung on a page of its own."""
    return [PageBreak(), H(heading, size=10.6), *(P(text, size=9.2) for text in paragraphs)]


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


# ==================================================================================================
# Family 1 — tax_assessment (AO: fiction day moves off Sat/Sun/holidays; § 355 AO one month)
# ==================================================================================================


def _posting_note(letter_date: date, posted: date, region: str | None) -> str:
    """The note of a Bescheid that names a posting day after its date, and whether the label depends on it."""
    if posted == letter_date:
        return ""
    from_date = law.deemed_delivery(letter_date, "ao", region, law.Derivation())
    from_posting = law.deemed_delivery(posted, "ao", region, law.Derivation())
    days = (posted - letter_date).days
    if from_date == from_posting:
        return (
            f"Posting day stated in the info block, {days} days after the Bescheid date; counted from either day the AO "
            f"shift reaches the same Bekanntgabe ({law.fmt(from_posting)}), so the label does not depend on it."
        )
    return f"Posting day stated in the info block, {days} days after the Bescheid date."


def _abrechnung(
    rows: list[tuple[str, int]], tax: int, withheld: int, soli: bool = False
) -> tuple[Table, int]:
    """The income lines (later lines deducted), the tax set, the wage tax already withheld and the balance (positive =
    to pay)."""
    taxable = rows[0][1] - sum(v for _, v in rows[1:])
    body = [(rows[0][0], _thousands(rows[0][1]))]
    body += [(label, f"– {_thousands(v)}") for label, v in rows[1:]]
    body += [("Zu versteuerndes Einkommen", _thousands(taxable)), ("Einkommensteuer", eur_plain(tax))]
    if soli:
        body.append(("Solidaritätszuschlag", "0,00"))
    diff = tax - withheld
    body += [("Steuerabzug vom Lohn", f"– {eur_plain(withheld)}"),
             ("Nachzahlung" if diff > 0 else "Erstattung", eur_plain(abs(diff)))]  # fmt: skip
    n = len(rows)
    last = len(body) - 1
    return Table(rows=tuple(body), header=("Ermittlung und Abrechnung", "EUR"), value_width=30, bold_rows=(n, last),
                 rule_before=(n, last)), diff  # fmt: skip


def tax_assessment() -> list[Case]:
    cases: list[Case] = []

    # --- variant I: date last in the info block, refund, run-in Belehrung ------------------------------------------
    def variant_i(case_id: str, org: Org, person: Person, salutation: str, posted: date, year: int, stnr: str,
                  rows: list[tuple[str, int]], tax: int, withheld: int, filed: date, notes: list[str], hand: str) -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="ao", remedy="einspruch", region=org.region,
                           title=f"Einspruchsfrist Einkommensteuerbescheid {year}"),
            hand,
        )  # fmt: skip
        table, diff = _abrechnung(rows, tax, withheld, soli=True)
        assert diff < 0
        letter = Letter(
            org=org, recipient=person, salutation=salutation,
            info=dated_last([("Steuernummer", stnr), ("Ihre Erklärung vom", de(filed)), ("Auskunft erteilt", "Arbeitnehmerstelle, Zi. 114")], posted),
            subject=f"Bescheid für {year} über Einkommensteuer und Solidaritätszuschlag",
            blocks=[
                P(f"auf Grund Ihrer Erklärung setzen wir die Steuern für das Kalenderjahr {year} wie folgt fest:"),
                table,
                P(f"Wir erstatten Ihnen **{eur(-diff)}**. Der Betrag geht in den nächsten Tagen auf dem Konto "
                  f"{iban_grouped(O.R_RECIPIENT_IBAN)} ein, das Sie in der Erklärung angegeben haben."),
                H("Erläuterungen", size=9.8),
                *(P(text, size=9.2) for text in notes),
                run_in(
                    f"Halten Sie die Festsetzung für unzutreffend, können Sie {bei(org.name)} Einspruch einlegen, und zwar "
                    "schriftlich, über ELSTER oder dort zu Protokoll. Für den Einspruch haben Sie einen Monat Zeit; "
                    "die Frist läuft ab dem Ende des Tages, an dem der Bescheid als bekannt gegeben gilt. Geht er Ihnen mit "
                    "der Post zu, ist das der vierte Tag nach seiner Aufgabe zur Post, außer er erreicht Sie erst später."
                ),
                Sign("Mit freundlichen Grüßen", ("Ihr Finanzamt",)),
            ],
            style=STYLES["I"], created=created(posted), running_ref=f"Steuernummer {stnr}",
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="tax_assessment", variant="I", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=posted, references=[("Steuernummer", stnr)],
                        amounts=[float(-diff)], remedy="einspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), "Für den Einspruch haben Sie einen Monat Zeit", stnr],
        )  # fmt: skip

    # I1 — MV. Posted Tue 02.02.2027 → day 4 = Sat 06.02. → Mon 08.02.2027 → one month → Mon 08.03.2027, Internationaler
    # Frauentag in MV → Tue 09.03.2027. Nationwide holidays only would keep Mon 08.03.
    cases.append(variant_i(
        "holdout3-tax_assessment-I1", O.R_FA_MV, O.R_MV, "Sehr geehrte Frau Musterholm,", date(2027, 2, 2), 2025,
        "079/241/30586",
        [("Einkünfte aus nichtselbständiger Arbeit", 47_385), ("Werbungskosten", 2_904),
         ("Sonderausgaben und Vorsorgeaufwendungen", 7_116), ("Außergewöhnliche Belastungen", 1_240)],
        6_318, 7_090, date(2026, 11, 26),
        ["Bei den Werbungskosten sind die Fahrten zur Tätigkeitsstätte an 198 Tagen und die Kosten Ihrer Arbeitsmittel "
         "berücksichtigt. Die Kosten der Zahnbehandlung wirken sich nur aus, soweit sie die zumutbare Belastung "
         "übersteigen.",
         "Die Spenden an den Seenotrettungsverein haben wir in der nachgewiesenen Höhe angesetzt."],
        "2027-03-09",
    ))  # fmt: skip
    # I2 — Land unknown. Posted Wed 23.04.2025 → day 4 = Sun 27.04. → Mon 28.04.2025 → Wed 28.05.2025.
    cases.append(variant_i(
        "holdout3-tax_assessment-I2", O.R_FA_X, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2025, 4, 23), 2024,
        "20/318/07452",
        [("Einkünfte aus nichtselbständiger Arbeit", 36_910), ("Werbungskosten", 1_772),
         ("Sonderausgaben und Vorsorgeaufwendungen", 6_048)],
        4_627, 5_052, date(2025, 2, 17),
        ["Die Steuerermäßigung für Handwerkerleistungen haben wir für die Rechnung über den Austausch der Fenster gewährt; "
         "begünstigt sind nur die Arbeitskosten, nicht das Material.",
         "Ein Solidaritätszuschlag fällt bei Ihrem Einkommen nicht an."],
        "2025-05-28",
    ))  # fmt: skip

    # --- variant J: date under its own label, two pages, Belehrung on page 2 ------------------------------------------
    def variant_j(case_id: str, org: Org, person: Person, salutation: str, letter_date: date, posted: date, year: int,
                  stnr: str, idnr: str, rows: list[tuple[str, int]], tax: int, withheld: int, intro: str, hand: str,
                  notes: list[str], pay_due: date | None = None, hand_pay: str | None = None) -> Case:  # fmt: skip
        items = [
            check(
                objection_item(posted=posted, scope="ao", remedy="einspruch", region=org.region,
                               title=f"Einspruchsfrist Einkommensteuerbescheid {year}"),
                hand,
            )
        ]  # fmt: skip
        table, diff = _abrechnung(rows, tax, withheld)
        blocks: list[Block] = [P(intro), table]
        if diff > 0:
            assert pay_due is not None and hand_pay is not None
            items.append(check(
                fixed_item(due=pay_due, region=org.region, kind="payment", nature="payment",
                           title=f"Einkommensteuer {year} nachzahlen", money=float(diff),
                           rule="Payment date printed in the assessment (Fälligkeit as set by the Finanzamt)."),
                hand_pay,
            ))  # fmt: skip
            blocks.append(P(f"Die Nachzahlung von **{eur(diff)}** ist bis zum **{de(pay_due)}** fällig. Überweisen Sie sie bitte "
                            f"auf das Konto des Finanzamts bei der {org.bank} (IBAN {iban_grouped(org.iban)}) und geben Sie die "
                            "Steuernummer an. Zahlt die Bank später, entstehen Säumniszuschläge."))  # fmt: skip
        else:
            blocks.append(P(f"Den Betrag von **{eur(-diff)}** zahlen wir Ihnen auf das bekannte Konto aus."))
        blocks += [
            P("Die Begründung und die Belehrung über Ihren Rechtsbehelf finden Sie auf der nächsten Seite."),
            *page_two(
                *notes,
                "Wenn Sie diesen Bescheid für unrichtig halten, ist der Einspruch der richtige Rechtsbehelf. Ihr Einspruch muss "
                "innerhalb eines Monats eingelegt werden; die Monatsfrist rechnet vom Ende des Tages an, an dem Ihnen der Bescheid "
                "bekannt gegeben worden ist. Ein Bescheid, der mit einfachem "
                "Brief verschickt wird, gilt am vierten Tag nach dem Tag seiner Aufgabe zur Post als bekannt gegeben – "
                "es sei denn, er ist nicht oder zu einem späteren Zeitpunkt zugegangen.",
                f"Der Einspruch ist {bei(org.name)} einzulegen, und zwar schriftlich, elektronisch über ELSTER oder durch "
                "Erklärung zur Niederschrift.",
                heading="Erläuterungen und Rechtsbehelfsbelehrung",
            ),
            Sign("Mit freundlichen Grüßen", ("Ihr Finanzamt",)),
        ]  # fmt: skip
        info = [("Steuernummer", stnr), ("Identifikationsnummer", idnr), ("Bescheiddatum", de(letter_date))]
        if posted != letter_date:
            info.append(("Zur Post gegeben am", de(posted)))
        letter = Letter(
            org=org, recipient=person, info=info, salutation=salutation,
            subject=f"Einkommensteuerbescheid für {year}", subject_extra=("Festsetzung – Abrechnung – Erläuterungen",),
            blocks=blocks, style=STYLES["J"], created=created(letter_date), running_ref=f"StNr. {stnr} · Bescheid vom {de(letter_date)}",
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="tax_assessment", variant="J", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=letter_date,
                        references=[("Steuernummer", stnr), ("Identifikationsnummer", idnr)], amounts=[float(abs(diff))],
                        remedy="einspruch", items=items),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), de(posted), "die Monatsfrist rechnet vom Ende des Tages an",
                         stnr, *([de(pay_due)] if pay_due else [])],
            notes=_posting_note(letter_date, posted, org.region),
        )  # fmt: skip

    # J1 — HB. Bescheid Tue 23.03.2027, posted Thu 25.03.2027 → day 4 = Mon 29.03.2027 Ostermontag → Tue 30.03. →
    # Fri 30.04.2027. Payment date printed by the office: Tue 04.05.2027.
    cases.append(variant_j(
        "holdout3-tax_assessment-J1", O.R_FA_HB, O.R_HB, "Sehr geehrter Herr Beispielbrink,", date(2027, 3, 23), date(2027, 3, 25),
        2025, "460/127/51309", "57 118 402 693",
        [("Einkünfte aus nichtselbständiger Arbeit", 41_862), ("Werbungskosten", 1_230),
         ("Sonderausgaben und Vorsorgeaufwendungen", 6_377)], 6_418, 5_134,
        "die Einkommensteuer für 2025 ist festgesetzt. Neben Ihrem Arbeitslohn haben wir das Arbeitslosengeld berücksichtigt, "
        "das Sie von Januar bis März 2025 bezogen haben; es ist steuerfrei, erhöht aber den Steuersatz "
        "(Progressionsvorbehalt). Daraus ergibt sich eine Nachzahlung:",
        "2027-04-30",
        ["Erläuterung: Der Progressionsvorbehalt (§ 32b EStG) erklärt die Nachzahlung. Das Arbeitslosengeld von 4.212,00 € "
         "hat die Agentur für Arbeit elektronisch gemeldet; der Betrag ist in der Tabelle nicht enthalten, er bestimmt nur "
         "den Steuersatz."],
        date(2027, 5, 4), "2027-05-04",
    ))  # fmt: skip
    # J2 — SL. Posted Mon 17.03.2025 → day 4 = Fri 21.03. → one month → Mon 21.04.2025 Ostermontag → Tue 22.04.2025.
    cases.append(variant_j(
        "holdout3-tax_assessment-J2", O.R_FA_SL, O.R_SL, "Sehr geehrte Frau Musterbecker,", date(2025, 3, 17), date(2025, 3, 17),
        2024, "040/164/22817", "83 260 517 149",
        [("Einkünfte aus nichtselbständiger Arbeit", 28_455), ("Werbungskosten", 3_516),
         ("Sonderausgaben und Vorsorgeaufwendungen", 4_490)], 2_468, 3_133,
        "Ihre Erklärung zur Einkommensteuer 2024 haben wir bearbeitet. Wir setzen die Steuer wie folgt fest:",
        "2025-04-22",
        ["Erläuterung: Die Kosten der doppelten Haushaltsführung in Beispielbrück sind für 44 Wochen berücksichtigt. Die "
         "Fahrten nach Hause sind mit der Entfernungspauschale angesetzt."],
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 2 — municipal_decision (Land VwVfG: 4th-day fiction WITHOUT shift; Widerspruch/Klage)
# ==================================================================================================


def municipal_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, posted: date, remedy: str, subject: str,
             ref: tuple[str, str], body: list[Block], belehrung: list[str], key: str, hand: str, signer: tuple[str, ...],
             extra_items: list | None = None, photo: bool = False, notes: str = "", more_keys: list[str] | None = None,
             extra_info: list[tuple[str, str]] | None = None) -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="vwvfg", remedy=remedy, region=org.region,
                           title="Klagefrist" if remedy == "klage" else "Widerspruchsfrist",
                           note=("Remedy is Klage: SPEC §21 shows a 'get advice' card instead of a computed date; the legal date is "
                                 "still the label.") if remedy == "klage" else None),
            hand,
        )  # fmt: skip
        if variant == "I":
            info = dated_last([ref, *(extra_info or [])], posted)
            tail: list[Block] = [*(run_in(text) if i == 0 else P(text, size=8.7) for i, text in enumerate(belehrung)),
                                 Sign("Mit freundlichen Grüßen", signer)]  # fmt: skip
        else:
            info = [ref, *(extra_info or []), ("Bescheid vom", de(posted))]
            tail = [*page_two(*belehrung), Sign("Mit freundlichen Grüßen", signer, signature=True)]
        letter = Letter(
            org=org, recipient=person, info=info, subject=subject, salutation=salutation,
            blocks=[*body, *tail], style=STYLES[variant], created=created(posted), running_ref=" ".join(ref),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="municipal_decision", variant=variant, letter=letter,
            truth=truth(kind="authority_letter", sender=org.name, document_date=posted, references=[ref], amounts=[],
                        remedy=remedy, items=[item, *(extra_items or [])]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), ref[1], key, *(more_keys or [])], photo=photo, notes=notes,
        )  # fmt: skip

    # I1 — MV, Widerspruch. Posted Tue 09.12.2025 → day 4 = Sat 13.12. (no shift) → Tue 13.01.2026.
    org = O.R_LK_MV
    cases.append(make(
        "holdout3-municipal_decision-I1", "I", org, O.R_MV, "Sehr geehrte Frau Musterholm,", date(2025, 12, 9), "widerspruch",
        "Wasserrechtliche Genehmigung für einen Bootssteg am Ufer des Musterower Sees – Versagung", ("Aktenzeichen", "66.2-BS-0417/25"),
        [
            P("Sie haben am 15.09.2025 beantragt, vor Ihrem Grundstück Am Fischerhafen 4 einen Bootssteg aus Lärchenholz "
              "(12 m lang, 1,50 m breit) in den Musterower See zu bauen."),
            P("Die Genehmigung nach § 36 Wasserhaushaltsgesetz in Verbindung mit dem Landeswassergesetz wird versagt. Der Steg "
              "läge in einem gesetzlich geschützten Röhrichtbestand; der Bau und die Nutzung würden ihn auf einer Fläche von "
              "etwa 40 m² zerstören. Die untere Naturschutzbehörde hat eine Ausnahme abgelehnt. In 300 m Entfernung steht "
              "Ihnen die Gemeinschaftssteganlage der Gemeinde zur Verfügung."),
            P("Für diesen Bescheid werden keine Kosten erhoben."),
        ],
        [f"Diese Entscheidung können Sie mit dem Widerspruch angreifen, den Sie binnen eines Monats nach Bekanntgabe schriftlich "
         f"oder zur Niederschrift an den {org.name}, Der Landrat, {org.street}, {org.postcode} {org.city}, richten.",
         "Hinweis zur Bekanntgabe: Versendet der Landkreis den Bescheid mit einfacher Post, ist er am vierten Tag nach der "
         "Aufgabe zur Post bekannt gegeben (§ 41 Abs. 2 VwVfG M-V)."],
        "mit dem Widerspruch angreifen, den Sie binnen eines Monats nach Bekanntgabe", "2026-01-13", ("Im Auftrag", "Dr. Rehberg"),
        extra_info=[("Ihr Antrag vom", "15.09.2025"), ("Bearbeiterin", "Frau Dr. Rehberg")],
        notes="The deemed-delivery day is a Saturday; outside tax law it does not move.",
    ))  # fmt: skip

    # I2 — SH, Widerspruch. Posted Mon 14.06.2027 → day 4 = Fri 18.06. → one month → Sun 18.07. → Mon 19.07.2027.
    org = O.R_STADT_SH
    cases.append(make(
        "holdout3-municipal_decision-I2", "I", org, O.R_SH, "Sehr geehrter Herr Musterdahl,", date(2027, 6, 14), "widerspruch",
        "Antrag auf einen Bewohnerparkausweis für die Zone B (Altstadt) – Ablehnung", ("Kassenzeichen", "BP-2027-0388"),
        [
            P("einen Bewohnerparkausweis können wir Ihnen leider nicht ausstellen. Nach der Anordnung der Stadt erhalten ihn nur "
              "Personen, die in der Zone mit Hauptwohnung gemeldet sind und ein Fahrzeug halten oder auf Dauer nutzen. Das "
              "Fahrzeug NF-JM 512 ist auf Ihren Arbeitgeber zugelassen; eine Erklärung, dass Sie es dauerhaft privat nutzen "
              "dürfen, liegt uns nicht vor."),
            P("Reichen Sie diese Erklärung nach, prüfen wir Ihren Antrag gern erneut."),
        ],
        [f"Gegen die Ablehnung können Sie Widerspruch erheben; er muss innerhalb eines Monats, nachdem Ihnen dieser Bescheid "
         f"bekannt gegeben wurde, {bei(org.name)}, {org.street}, {org.postcode} {org.city}, schriftlich oder zur Niederschrift "
         "eingehen. Für die Bekanntgabe zählt bei Postversand der vierte Tag, nachdem der Bescheid zur Post gegeben wurde."],
        "er muss innerhalb eines Monats, nachdem Ihnen dieser Bescheid bekannt gegeben wurde", "2027-07-19",
        ("Im Auftrag", "Thomsen"), extra_info=[("Sachbearbeitung", "Herr Thomsen")], photo=True,
    ))  # fmt: skip

    # J1 — BY, Klage + removal date. Posted Thu 28.10.2027 → day 4 = Mon 01.11.2027, Allerheiligen in BY (the fiction day does
    # not move) → Wed 01.12.2027. Removal by Wed 05.01.2028.
    posted, removal = date(2027, 10, 28), date(2028, 1, 5)
    task = check(
        fixed_item(due=removal, region="BY", kind="task", nature="other", title="Pferdeunterstand im Außenbereich beseitigen",
                   rule="Compliance deadline set by the authority as a calendar date."),
        "2028-01-05",
    )  # fmt: skip
    org = O.R_LRA_BY
    cases.append(make(
        "holdout3-municipal_decision-J1", "J", org, O.R_BY, "Sehr geehrter Herr Beispielmaier,", posted, "klage",
        "Vollzug der Bayerischen Bauordnung; Beseitigung eines Pferdeunterstands auf Fl.-Nr. 1187/2, Gemarkung Mustervils",
        ("Az.", "41-602-BV/1873/27"),
        [
            P("Das Landratsamt Musterfelden erlässt folgenden"),
            P("**Bescheid:**"),
            P(f"1. Herr Korbinian Beispielmaier wird verpflichtet, den auf dem Grundstück Fl.-Nr. 1187/2 der Gemarkung Mustervils "
              f"errichteten Pferdeunterstand (Holzbau, 8,00 m × 4,50 m, mit Bodenplatte) bis spätestens {de(removal)} "
              "vollständig zu beseitigen.", indent=4),
            P("2. Kommen Sie der Verpflichtung in Nr. 1 nicht fristgerecht nach, wird ein Zwangsgeld in Höhe von 1.500,00 € "
              "fällig.", indent=4),
            P("3. Über die Kosten dieses Verfahrens ergeht ein gesonderter Bescheid.", indent=4),
            P("**Gründe:**"),
            P("Bei einer Ortseinsicht am 06.09.2027 wurde festgestellt, dass auf dem genannten Grundstück ohne Baugenehmigung ein "
              "Unterstand für zwei Pferde errichtet wurde. Das Grundstück liegt im Außenbereich (§ 35 BauGB). Das Vorhaben dient "
              "keinem landwirtschaftlichen Betrieb, sondern der Freizeitpferdehaltung, und beeinträchtigt öffentliche Belange; "
              "eine nachträgliche Genehmigung ist ausgeschlossen. Die Anordnung beruht auf Art. 76 Satz 1 BayBO. Sie wurden am "
              "21.09.2027 angehört und haben sich nicht geäußert."),
        ],
        ["Gegen diesen Bescheid kann innerhalb eines Monats nach seiner Bekanntgabe Klage erhoben werden bei dem Bayerischen "
         "Verwaltungsgericht Musterhut, Hausanschrift: Gerichtsplatz 3, 84028 Musterhut. Die Klage muss den Kläger, den "
         "Beklagten (Freistaat Bayern) und den Gegenstand des Klagebegehrens bezeichnen und soll einen bestimmten Antrag "
         "enthalten.",
         "Hinweise: Die Einlegung eines Rechtsbehelfs per einfacher E-Mail ist nicht zugelassen und entfaltet keine rechtlichen "
         "Wirkungen. Im Baurecht ist das Vorverfahren abgeschafft (Art. 12 Abs. 2 AGVwGO); Sie können sich unmittelbar an "
         "das Gericht wenden. Mit der Erhebung der Klage wird eine Verfahrensgebühr fällig."],
        "Klage erhoben werden bei dem Bayerischen Verwaltungsgericht Musterhut", "2027-12-01", ("Huber", "Regierungsrat"),
        extra_items=[task], more_keys=[de(removal)], extra_info=[("Sachgebiet", "41 – Bauordnungsrecht")],
        notes="Day 4 after posting is Allerheiligen, a holiday in BY; outside tax law the fiction day does not move.",
    ))  # fmt: skip

    # J2 — HH, Widerspruch. Posted Tue 21.04.2026 → day 4 = Sat 25.04. (no shift) → Mon 25.05.2026 Pfingstmontag → Tue 26.05.2026.
    org = O.R_BA_HH
    cases.append(make(
        "holdout3-municipal_decision-J2", "J", org, O.R_HH, "Sehr geehrte Frau Beispielstrom,", date(2026, 4, 21), "widerspruch",
        "Antrag auf Genehmigung der Zweckentfremdung von Wohnraum – Kranhausstieg 3, 2. OG rechts", ("Geschäftszeichen", "WS/A 2026-0214"),
        [
            P("Sie möchten Ihre Wohnung im Kranhausstieg 3 (2. Obergeschoss rechts, 64 m²) an bis zu 180 Tagen im Jahr an "
              "Feriengäste vermieten, während Sie im Ausland arbeiten. Dafür beantragen Sie eine Genehmigung nach dem "
              "Hamburgischen Wohnraumschutzgesetz."),
            P("Die Genehmigung kann ich nicht erteilen. Wohnraum darf in Hamburg nur dann als Ferienwohnung genutzt werden, "
              "wenn vorrangige öffentliche Interessen oder schutzwürdige private Interessen das überwiegen. Ein solcher Fall "
              "liegt nicht vor: Die Wohnung würde dem Mietwohnungsmarkt für mehr als die Hälfte des Jahres entzogen. Eine "
              "Vermietung an Feriengäste für insgesamt höchstens acht Wochen im Jahr bleibt genehmigungsfrei; sie muss aber "
              "angezeigt werden."),
            P("Die Begründung im Einzelnen und die Rechtsbehelfsbelehrung finden Sie auf Seite 2."),
        ],
        ["Wenn Sie mit dieser Entscheidung nicht einverstanden sind, können Sie Widerspruch einlegen. Ihr Widerspruch ist "
         f"innerhalb eines Monats nach Bekanntgabe dieses Bescheides an das {org.name}, {org.street}, {org.postcode} {org.city}, "
         "zu richten, schriftlich oder zur Niederschrift.",
         "Dieser Bescheid wird mit einfachem Brief versandt; er gilt nach § 41 Abs. 2 HmbVwVfG am vierten Tag nach der Aufgabe "
         "zur Post als bekannt gegeben.",
         "Bitte beachten Sie: Eine Vermietung als Ferienwohnung ohne Genehmigung ist eine Ordnungswidrigkeit, die mit einer "
         "Geldbuße geahndet werden kann."],
        "Ihr Widerspruch ist innerhalb eines Monats nach Bekanntgabe dieses Bescheides", "2026-05-26", ("Im Auftrag", "Jürgensen"),
        extra_info=[("Ansprechpartner", "Herr Jürgensen, Raum 3.21")],
        notes="The deemed-delivery day is a Saturday (no shift); the period then ends on Pfingstmontag and moves to Tuesday.",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 3 — social_decision (SGB X: 4th-day fiction WITHOUT shift; one month)
# ==================================================================================================


def social_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, posted: date, kind: str, subject: str,
             refs: list[tuple[str, str]], body: list[Block], belehrung: list[str], key: str, hand: str,
             amounts: list[float] | None = None, extra_items: list | None = None, photo: bool = False, notes: str = "",
             rule: str | None = None, closing: tuple[str, ...] = (), shift_citation: str | None = None,
             more_keys: list[str] | None = None, extra_info: list[tuple[str, str]] | None = None) -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="sgbx", remedy="widerspruch", region=org.region, title="Widerspruchsfrist",
                           rule=rule, shift_citation=shift_citation),
            hand,
        )  # fmt: skip
        if variant == "I":
            info = dated_last([*refs, *(extra_info or [])], posted)
            tail: list[Block] = [*(run_in(text) if i == 0 else P(text, size=8.7) for i, text in enumerate(belehrung)),
                                 Sign("Freundliche Grüße", closing or (org.name,))]  # fmt: skip
        else:
            info = [*refs, *(extra_info or []), ("Datum des Bescheids", de(posted))]
            tail = [*page_two(*belehrung), Sign("Mit freundlichen Grüßen", closing or ("Im Auftrag",))]
        letter = Letter(
            org=org, recipient=person, info=info, subject=subject, salutation=salutation,
            blocks=[*body, *tail], style=STYLES[variant], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="social_decision", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts or [], remedy="widerspruch",
                        items=[item, *(extra_items or [])]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), key, *(more_keys or [])], photo=photo, notes=notes,
        )  # fmt: skip

    # I1 — BKK, Land unknown. Posted Wed 07.05.2025 → day 4 = Sun 11.05. (no shift) → Wed 11.06.2025.
    org = O.R_BKK
    cases.append(make(
        "holdout3-social_decision-I1", "I", org, O.R_GEN, "Sehr geehrter Herr Musterschmidt,", date(2025, 5, 7), "health_insurance",
        "Fahrkosten zur ambulanten Behandlung – Ihr Antrag vom 14.04.2025", [("Versichertennummer", "T274019385"), ("Unser Zeichen", "FK-25-11872")],
        [
            P("Sie haben beantragt, dass wir die Kosten Ihrer Taxifahrten zur ambulanten Physiotherapie in der Praxis am Stadtpark "
              "übernehmen. Wir haben Ihren Antrag geprüft und können die Fahrkosten leider nicht übernehmen."),
            P("Fahrten zu einer ambulanten Behandlung bezahlen wir nach § 60 SGB V nur in besonderen Ausnahmefällen, zum Beispiel "
              "bei einem Pflegegrad 3 mit dauerhaft eingeschränkter Mobilität, bei den Merkzeichen aG, Bl oder H oder bei einer "
              "Dialyse- oder Strahlenbehandlung. Keiner dieser Fälle liegt bei Ihnen vor. Ihre Ärztin hat uns bestätigt, dass Sie "
              "öffentliche Verkehrsmittel benutzen können."),
        ],
        ["Wenn Sie mit unserer Entscheidung nicht einverstanden sind, legen Sie bitte innerhalb eines Monats nach Bekanntgabe "
         f"Widerspruch ein – schriftlich oder zur Niederschrift {bei(org.name)}, {org.street}, {org.postcode} {org.city}."],
        "legen Sie bitte innerhalb eines Monats nach Bekanntgabe Widerspruch ein", "2025-06-11",
        closing=("Ihre BKK Musterwerk", "Leistungszentrum Fahrkosten"),
        notes="The deemed-delivery day is a Sunday; outside tax law it does not move.",
    ))  # fmt: skip

    # I2 — Amt für Ausbildungsförderung (BAföG), Land unknown. Posted Mon 05.05.2025 → day 4 = Fri 09.05. → Mon 09.06.2025
    # Pfingstmontag → Tue 10.06.2025.
    org = O.R_BAFOEG
    cases.append(make(
        "holdout3-social_decision-I2", "I", org, O.R_GEN2, "Sehr geehrte Frau Beispielwinkel,", date(2025, 5, 5), "social_insurance",
        "Bescheid über Ausbildungsförderung nach dem BAföG – Bewilligungszeitraum 04/2025 bis 03/2026",
        [("Förderungsnummer", "412 2025 07731")],
        [
            P("für Ihr Studium der Sozialen Arbeit bewilligen wir Ihnen für den Bewilligungszeitraum April 2025 bis März 2026 "
              "Ausbildungsförderung in Höhe von **734,00 € monatlich**, je zur Hälfte als Zuschuss und als unverzinsliches "
              "Staatsdarlehen. Das Einkommen Ihrer Eltern haben wir nach den Steuerbescheiden für 2023 angerechnet."),
            P("Die Zahlung erfolgt jeweils zum Monatsende für den folgenden Monat. Teilen Sie uns Änderungen bei Ihrem Einkommen, "
              "Ihrer Wohnung oder Ihrem Studium bitte sofort mit."),
        ],
        ["Wenn Sie diese Entscheidung überprüfen lassen möchten, legen Sie innerhalb eines Monats nach ihrer Bekanntgabe "
         f"Widerspruch {bei(org.name)}, {org.street}, {org.postcode} {org.city}, ein – schriftlich oder zur Niederschrift."],
        "legen Sie innerhalb eines Monats nach ihrer Bekanntgabe Widerspruch", "2025-06-10",
        amounts=[734.0], photo=True, closing=("Amt für Ausbildungsförderung",),
        rule="Widerspruch against a BAföG decision: one month after Bekanntgabe (§ 70 Abs. 1 VwGO); BAföG disputes go to the "
             "administrative courts (§ 54 BAföG), and as a social benefit (§ 68 Nr. 1 SGB I) its deemed delivery follows § 37 "
             "Abs. 2 SGB X.",
        shift_citation=VWGO_SHIFT, extra_info=[("Ausbildungsstätte", "Hochschule Mustertor")],
        notes="The Widerspruch period ends on Pfingstmontag 2025 and moves to Tuesday.",
    ))  # fmt: skip

    # J1 — Jobcenter BB + submission date. Posted Tue 30.06.2026 → day 4 = Sat 04.07. (no shift) → Tue 04.08.2026.
    posted, submit = date(2026, 6, 30), date(2026, 7, 14)
    task = check(
        fixed_item(due=submit, region="BB", kind="task", nature="declaration", title="Neuen Mietvertrag und Kautionsnachweis einreichen",
                   rule="Submission deadline set by the authority as a calendar date."),
        "2026-07-14",
    )  # fmt: skip
    org = O.R_JC_BB
    cases.append(make(
        "holdout3-social_decision-J1", "J", org, O.R_BB, "Sehr geehrte Frau Musterlitz,", posted, "social_insurance",
        "Bewilligung von Leistungen zur Sicherung des Lebensunterhalts für die Zeit vom 01.07.2026 bis 30.06.2027",
        [("BG-Nummer", "05817//0093412"), ("Kundennummer", "731D225509")],
        [
            P("auf Ihren Weiterbewilligungsantrag vom 02.06.2026 bewilligen wir Ihnen und den Mitgliedern Ihrer "
              "Bedarfsgemeinschaft Leistungen nach dem Zweiten Buch Sozialgesetzbuch (SGB II)."),
            Table(rows=(("Regelbedarf für Sie", "563,00"), ("Regelbedarf für Ihren Sohn Elias (8 Jahre)", "390,00"),
                        ("Mehrbedarf für Alleinerziehende", "67,56"), ("Kosten der Unterkunft und Heizung", "612,40"),
                        ("abzüglich anzurechnendes Einkommen Ihres Sohnes", "– 399,00"), ("Monatlicher Gesamtbetrag", "1.233,96")),
                  header=("Leistungen ab Juli 2026", "EUR"), bold_rows=(5,), rule_before=(5,), value_width=30),
            P(f"Sie haben uns mitgeteilt, dass Sie zum 01.08.2026 umziehen. Damit wir die neue Miete berücksichtigen können, "
              f"reichen Sie bitte **bis zum {de(submit)}** den unterschriebenen Mietvertrag und den Nachweis über die Kaution "
              "ein. Ohne diese Unterlagen können wir ab August nur die bisherigen Kosten der Unterkunft zahlen (§ 60 SGB I)."),
        ],
        ["Gegen diesen Bescheid kann jede betroffene Person Widerspruch einlegen. Der Widerspruch muss innerhalb eines Monats "
         f"nach Bekanntgabe beim {org.name}, {org.street}, {org.postcode} {org.city}, eingehen. Er kann schriftlich, in "
         "elektronischer Form mit qualifizierter Signatur oder zur Niederschrift erhoben werden.",
         "Diesen Bescheid erhalten Sie per Post. Bekannt gegeben ist er am vierten Tag, nachdem wir ihn zur Post gegeben haben "
         "(§ 37 Abs. 2 SGB X)."],
        "Der Widerspruch muss innerhalb eines Monats nach Bekanntgabe beim", "2026-08-04", amounts=[1233.96],
        extra_items=[task], more_keys=[de(submit)], closing=("Im Auftrag", "Wernicke, Team Leistung 3"),
        notes="The deemed-delivery day is a Saturday; outside tax law it does not move.",
    ))  # fmt: skip

    # J2 — Elterngeldstelle RP. Posted Tue 04.02.2025 → day 4 = Sat 08.02. (no shift) → Sat 08.03.2025 → Mon 10.03.2025.
    org = O.R_EG_RP
    cases.append(make(
        "holdout3-social_decision-J2", "J", org, O.R_RP, "Sehr geehrte Frau Musterfeld,", date(2025, 2, 4), "social_insurance",
        "Elterngeld für Ihre Tochter Ida, geboren am 19.11.2024", [("Aktenzeichen", "EG 51-0412/24")],
        [
            P("auf Ihren Antrag vom 08.01.2025 bewilligen wir Ihnen Basiselterngeld für den 1. bis 12. Lebensmonat Ihrer Tochter "
              "Ida, also für die Zeit vom 19.11.2024 bis 18.11.2025."),
            Table(rows=(("Einkommen vor der Geburt (monatlich, netto)", "1.764,80"), ("Ersatzrate", "65 %"),
                        ("Elterngeld je Lebensmonat", "1.147,12")), header=("Berechnung", ""), bold_rows=(2,), rule_before=(2,),
                  value_width=30),
            P("Das Mutterschaftsgeld und den Arbeitgeberzuschuss haben wir für die ersten beiden Lebensmonate angerechnet; für "
              "diese Monate zahlen wir **0,00 €**. Ab dem 3. Lebensmonat überweisen wir **1.147,12 €** monatlich."),
        ],
        ["Gegen diese Entscheidung können Sie Widerspruch erheben. Er ist binnen eines Monats nach Bekanntgabe schriftlich oder zur "
         f"Niederschrift {bei(org.name)}, Elterngeldstelle, {org.street}, {org.postcode} {org.city}, einzulegen.",
         "Wir versenden Bescheide mit der Post; als bekannt gegeben gelten sie dann am vierten Tag nach dem Versand "
         "(§ 37 Abs. 2 SGB X)."],
        "Er ist binnen eines Monats nach Bekanntgabe schriftlich oder zur Niederschrift", "2025-03-10", amounts=[1147.12],
        closing=("Im Auftrag", "Schäfer-Kohl"),
        notes="Both the deemed-delivery day and the raw end of the period are Saturdays; only the end moves.",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 7 — fine_bussgeld (OWiG: Einspruch 2 weeks after Zustellung, § 67 OWiG, § 43 StPO)
# ==================================================================================================


def fine_bussgeld() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, letter_date: date, served: date, plate: str, when: str, place: str,
             charge: str, rules: str, fine: float, points: int, hand: str, az: str, note: str, initials: str) -> Case:  # fmt: skip
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
        register = (
            f"Der Verstoß wird mit {points} Punkt im Fahreignungsregister beim Kraftfahrt-Bundesamt eingetragen."
            if points == 1
            else "Punkte im Fahreignungsregister werden für diesen Verstoß nicht eingetragen."
        )
        costs_table = Table(rows=(("Geldbuße", eur_plain(fine)), ("Verwaltungsgebühr nach § 107 Abs. 1 OWiG", eur_plain(fee)),
                                  ("Zustellungsauslagen", eur_plain(costs)), ("Zu zahlender Betrag", eur_plain(total))),
                            header=("Rechtsfolgen und Kosten", "EUR"), bold_rows=(3,), rule_before=(3,), value_width=30)  # fmt: skip
        if variant == "I":
            info = dated_last([("Aktenzeichen", az), ("Amtl. Kennzeichen", plate)], letter_date)
            refs = [("Aktenzeichen", az), ("Amtl. Kennzeichen", plate)]
            blocks: list[Block] = [
                P(f"Gegen Sie wird wegen der folgenden Ordnungswidrigkeit eine Geldbuße festgesetzt. Sie haben am {when} in {place} "
                  f"als Führer des Pkw {plate} {charge}"),
                P(f"Angewendete Bestimmungen: {rules}. Beweismittel: Messprotokoll, Lichtbilder, Eichschein.", size=8.4),
                costs_table,
                P(f"{register} Bitte zahlen Sie den Betrag nicht vor Rechtskraft dieses Bescheids; danach ist er innerhalb von zwei "
                  f"Wochen auf das Konto {iban_grouped(org.iban)} unter Angabe des Aktenzeichens zu überweisen."),
                run_in(
                    "Dieser Bescheid wird rechtskräftig und vollstreckbar, wenn Sie nicht innerhalb von zwei Wochen nach seiner "
                    f"Zustellung Einspruch einlegen. Der Einspruch ist {bei(org.name)} schriftlich oder zur Niederschrift einzulegen. "
                    "Nach einem Einspruch kann das Amtsgericht durch Beschluss entscheiden, wenn Sie und die Staatsanwaltschaft "
                    "dem nicht widersprechen; es ist an die Höhe der Geldbuße in diesem Bescheid nicht gebunden."
                ),
            ]  # fmt: skip
            key = "wenn Sie nicht innerhalb von zwei Wochen nach seiner Zustellung Einspruch einlegen"
        else:
            info = [("Aktenzeichen", az), ("Kennzeichen", plate), ("Erlassen am", de(letter_date))]
            refs = [("Aktenzeichen", az), ("Kennzeichen", plate)]
            blocks = [
                Table(rows=(("Tatzeit", when), ("Tatort", place), ("Fahrzeug", f"Pkw, amtliches Kennzeichen {plate}")),
                      header=("Tat", ""), value_width=118, value_align="L", size=8.6),
                P(f"Tatvorwurf: {charge}"),
                P(f"Rechtsgrundlagen: {rules}", size=8.4, indent=4),
                costs_table,
                P(f"{register} Zahlen müssen Sie erst, wenn der Bescheid rechtskräftig ist; fällig wird der Betrag zwei Wochen danach."),
                H("Rechtsbehelfsbelehrung", size=9.8),
                P(f"Gegen diesen Bußgeldbescheid können Sie Einspruch einlegen, und zwar {bei(org.name)} schriftlich oder dort "
                  "zur Niederschrift. Die Einspruchsfrist beträgt zwei Wochen; sie beginnt mit der Zustellung dieses Bescheids. "
                  "Wird kein Einspruch eingelegt, ist der Bescheid danach rechtskräftig.", size=8.8),
            ]  # fmt: skip
            key = "Die Einspruchsfrist beträgt zwei Wochen; sie beginnt mit der Zustellung dieses Bescheids"
        blocks.append(Envelope(sender=org.name, recipient=person, reference=az, note=note, initials=initials))
        letter = Letter(
            org=org, recipient=person, info=info, subject="Bußgeldbescheid",
            subject_extra=("nach § 65 des Gesetzes über Ordnungswidrigkeiten (OWiG)",), blocks=blocks,
            style=STYLES[variant], created=created(letter_date), running_ref=f"Aktenzeichen {az}",
        )  # fmt: skip
        today = max(today_after(letter_date, case_id), today_after(served, case_id, 0, 2))
        return Case(
            id=case_id, split=SPLIT, family="fine_bussgeld", variant=variant, letter=letter,
            truth=truth(kind="fine", sender=org.name, document_date=letter_date, references=refs, amounts=[total, fine],
                        remedy="einspruch", items=[objection], optional_items=[payment]),
            today=today, authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), key, de(served), az],
            notes="Zustellung date is noted on the yellow envelope (page 2), not the Bescheid date.",
        )  # fmt: skip

    # I1 — SL: served Mon 18.10.2027 → Mon 01.11.2027 Allerheiligen (SL) → Tue 02.11.2027. Nationwide only: Mon 01.11.
    cases.append(make(
        "holdout3-fine_bussgeld-I1", "I", O.R_BG_SL, O.R_SL, date(2027, 10, 11), date(2027, 10, 18), "WND-NM 77",
        "02.09.2027 um 06:48 Uhr", "St. Musterwendel, Landstraße L 133, Höhe Abzweig Beispielweiler",
        "überschritten Sie außerhalb geschlossener Ortschaften die zulässige Höchstgeschwindigkeit von 70 km/h um 34 km/h "
        "(festgestellte Geschwindigkeit nach Toleranzabzug).", "§ 41 Abs. 1 i. V. m. Anlage 2, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 "
        "StVG; 11.3.6 BKat", 200.0, 1, "2027-11-02", "ZBB 6.2-27/0921457", f"zugestellt am {de(date(2027, 10, 18))}", "Ste.",
    ))  # fmt: skip
    # I2 — Land unknown: served Mon 03.05.2027 → Mon 17.05.2027 Pfingstmontag → Tue 18.05.2027.
    cases.append(make(
        "holdout3-fine_bussgeld-I2", "I", O.R_BG_X, O.R_GEN2, date(2027, 4, 27), date(2027, 5, 3), "MS-LB 4410",
        "18.03.2027 um 16:22 Uhr", "Musterberg, Bundesstraße B 480, Ortsdurchfahrt Beispielhausen",
        "benutzten Sie während der Fahrt ein Mobiltelefon, das Sie dazu in der Hand hielten.",
        "§ 23 Abs. 1a, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 246.1 BKat", 100.0, 1, "2027-05-18", "BG 27/4410/18-03",
        f"Zugestellt {de(date(2027, 5, 3))}", "Kl.",
    ))  # fmt: skip
    # J1 — BB: served Sat 23.08.2025 → Sat 06.09.2025 → Mon 08.09.2025.
    cases.append(make(
        "holdout3-fine_bussgeld-J1", "J", O.R_BG_BB, O.R_BB, date(2025, 8, 20), date(2025, 8, 23), "TF-DM 318",
        "15.07.2025, 19:03 Uhr", "Beispielsruh (Havel), Kreuzung Bahnhofstraße / Dahmeweg",
        "Sie missachteten als Führerin des Kraftfahrzeugs das Rotlicht der Lichtzeichenanlage; die Rotphase dauerte noch "
        "nicht länger als eine Sekunde.", "§ 37 Abs. 2, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 132 BKat", 90.0, 1,
        "2025-09-08", "ZBS-BB 25.441872.6", f"zugest. am {de(date(2025, 8, 23))}", "Ri.",
    ))  # fmt: skip
    # J2 — NI: served Wed 28.10.2026 → Wed 11.11.2026 (a working day in NI).
    cases.append(make(
        "holdout3-fine_bussgeld-J2", "J", O.R_BG_NI, O.R_NI, date(2026, 10, 21), date(2026, 10, 28), "HK-HM 290",
        "09.09.2026, 13:57 Uhr", "Musterhausen in der Heide, Lüneburger Straße 61 (innerorts)",
        "Sie überschritten innerhalb geschlossener Ortschaften die zulässige Höchstgeschwindigkeit von 50 km/h um 19 km/h.",
        "§ 3 Abs. 3, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 11.3.3 BKat", 70.0, 0, "2026-11-11", "OWi 12.3-26/88140",
        f"zugestellt {de(date(2026, 10, 28))}", "Mü.",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 12 — year_boundary (old 3-day rule in December 2024, month ends, the turn of the year)
# ==================================================================================================


def year_boundary() -> list[Case]:
    cases: list[Case] = []

    # --- variant I: AO decisions, date last in the info block, run-in Belehrung -----------------------------------------
    def variant_i(case_id: str, org: Org, person: Person, posted: date, subject: str, body: list[Block], refs: list[tuple[str, str]],
                  kind: str, amounts: list[float], hand: str, day_word: str, salutation: str, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="ao", remedy="einspruch", region=None, title="Einspruchsfrist"
            ),
            hand,
        )
        letter = Letter(
            org=org, recipient=person, info=dated_last(refs, posted), subject=subject, salutation=salutation,
            blocks=[
                *body,
                run_in(
                    f"Wer mit dieser Festsetzung nicht einverstanden ist, kann binnen eines Monats nach Bekanntgabe Einspruch "
                    f"{bei(org.name)} erheben – schriftlich, elektronisch über ELSTER oder zur Niederschrift. Als bekannt gegeben "
                    f"gilt ein Bescheid, den wir mit der Post verschicken, am {day_word} Tag nach der Aufgabe zur Post; das gilt "
                    "nicht, wenn er Sie nicht oder erst später erreicht hat."
                ),
                P("Dieser Bescheid ist maschinell erstellt und ohne Unterschrift gültig.", size=7.6),
            ],
            style=STYLES["I"], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="year_boundary", variant="I", letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts, remedy="einspruch",
                        items=[item]),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "kann binnen eines Monats nach Bekanntgabe Einspruch",
                         f"am {day_word} Tag nach der Aufgabe zur Post; das gilt nicht"],
            notes=notes,
        )  # fmt: skip

    # I1 — posted Tue 24.12.2024 → day 3 = Fri 27.12.2024 (a working day) → Mon 27.01.2025.
    # (The 4-day rule would give Sat 28.12. → Mon 30.12. → Thu 30.01.2025.)
    cases.append(variant_i(
        "holdout3-year_boundary-I1", O.R_FA_X2, O.R_GEN2, date(2024, 12, 24), "Bescheid für 2023 über Einkommensteuer",
        [P("die Einkommensteuer für 2023 setzen wir auf **3.476,00 €** fest. Auf die Steuer werden die einbehaltene Lohnsteuer "
           "von 4.105,00 € und die Kapitalertragsteuer von 38,00 € angerechnet. Wir erstatten Ihnen **667,00 €**."),
         P("Die Kosten Ihres Umzugs nach Musterlingen haben wir als Werbungskosten anerkannt, weil Sie ihn wegen der neuen "
           "Arbeitsstelle unternommen haben.", size=9.2)],
        [("Steuernummer", "99/062/71418")], "tax_assessment", [667.0], "2025-01-27", "dritten", "Sehr geehrte Frau Beispielwinkel,",
        notes="Posted before 2025-01-01: 3-day fiction (Art. 97 § 1 Abs. 15 EGAO); day 3 is Fri 27.12.2024, the 4-day rule "
              "would give 30.01.2025.",
    ))  # fmt: skip
    # I2 — Familienkasse, Kindergeld (EStG, so the AO applies). Posted Thu 27.03.2025 → day 4 = Mon 31.03.2025 → 31.04. does
    # not exist → Wed 30.04.2025 (§ 188 Abs. 3 BGB).
    cases.append(variant_i(
        "holdout3-year_boundary-I2", O.R_FK, O.R_GEN, date(2025, 3, 27), "Festsetzung des Kindergeldes für Ihre Tochter Marlene",
        [P("für Ihre Tochter Marlene, geboren am 14.08.2006, setzen wir ab April 2025 Kindergeld in Höhe von **255,00 € "
           "monatlich** fest (§§ 62, 63, 66 EStG). Marlene studiert seit dem Sommersemester 2025 an der Hochschule "
           "Beispielmainz; dafür besteht ein Anspruch bis zur Vollendung des 25. Lebensjahres."),
         P("Bitte teilen Sie uns mit, wenn Marlene das Studium abbricht oder unterbricht.", size=9.2)],
        [("Kindergeldnummer", "355FK207441")], "social_insurance", [255.0], "2025-04-30", "vierten", "Sehr geehrter Herr Musterschmidt,",
        notes="Kindergeld is a tax refund under the EStG: AO deemed delivery with shift, Einspruch; the period ends on 30.04.",
    ))  # fmt: skip
    # I3 — posted Mon 21.12.2026 → day 4 = Fri 25.12.2026 (1. Weihnachtstag) → Sat, Sun → Mon 28.12.2026 → Thu 28.01.2027.
    cases.append(variant_i(
        "holdout3-year_boundary-I3", O.R_FA_X, O.R_GEN, date(2026, 12, 21), "Bescheid über die Festsetzung der Arbeitnehmer-Sparzulage für 2025",
        [P("für die vermögenswirksamen Leistungen, die Ihr Arbeitgeber 2025 auf Ihren Bausparvertrag eingezahlt hat, setzen wir "
           "eine Arbeitnehmer-Sparzulage von **43,00 €** fest. Die Zulage zahlen wir nicht an Sie aus, sondern an die "
           "Bausparkasse; sie wird Ihrem Vertrag gutgeschrieben, sobald die Sperrfrist abgelaufen ist.")],
        [("Steuernummer", "20/318/07452"), ("Vertragsnummer", "BSK 4471209-06")], "tax_letter", [43.0], "2027-01-28", "vierten",
        "Sehr geehrter Herr Musterschmidt,",
        notes="Posted the Monday before Christmas: day 4 is Christmas Day and moves to Monday 28.12.",
    ))  # fmt: skip

    # --- variant J: SGB X decisions, date under its own label --------------------------------------------------------------
    def variant_j(case_id: str, org: Org, person: Person, posted: date, subject: str, body: list[Block], refs: list[tuple[str, str]],
                  amounts: list[float], hand: str, day_word: str, salutation: str, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="sgbx", remedy="widerspruch", region=None, title="Widerspruchsfrist"
            ),
            hand,
        )
        belehrung = [
            H("Rechtsbehelfsbelehrung", size=9.8),
            P(f"Den Widerspruch gegen diese Entscheidung richten Sie innerhalb eines Monats ab ihrer Bekanntgabe schriftlich oder "
              f"zur Niederschrift an die {org.name}, {org.street}, {org.postcode} {org.city}. Schicken wir Ihnen den Bescheid per "
              f"Brief, so ist er mit dem {day_word} Tag nach dessen Aufgabe zur Post bekannt gegeben.", size=8.8),
        ]  # fmt: skip
        letter = Letter(
            org=org, recipient=person, info=[*refs, ("Datum des Bescheids", de(posted))], subject=subject, salutation=salutation,
            blocks=[*body, *belehrung, Sign("Mit freundlichen Grüßen", ("Im Auftrag",))],
            style=STYLES["J"], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="year_boundary", variant="J", letter=letter,
            truth=truth(kind="social_insurance", sender=org.name, document_date=posted, references=refs, amounts=amounts,
                        remedy="widerspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "richten Sie innerhalb eines Monats ab ihrer Bekanntgabe",
                         f"so ist er mit dem {day_word} Tag nach dessen Aufgabe zur Post bekannt gegeben"],
            photo=photo, notes=notes,
        )  # fmt: skip

    # J1 — Rentenversicherung (SGB VI → SGB X). Posted Wed 27.08.2025 → day 4 = Sun 31.08.2025 (no shift) → 31.09. does not
    # exist → Tue 30.09.2025 (§ 188 Abs. 3 BGB).
    cases.append(variant_j(
        "holdout3-year_boundary-J1", O.R_RV, O.R_GEN, date(2025, 8, 27), "Feststellung von Zeiten in Ihrem Versicherungsverlauf",
        [P("wir haben Ihr Versicherungskonto geklärt. Die Daten des beigefügten Versicherungsverlaufs, die länger als sechs "
           "Kalenderjahre zurückliegen, stellen wir hiermit verbindlich fest (§ 149 Abs. 5 SGB VI)."),
         P("Die Zeit Ihrer Fachschulausbildung vom 01.09.2004 bis 30.06.2006 merken wir als Anrechnungszeit vor. Die Zeit vom "
           "01.07.2006 bis 31.12.2006 können wir nicht berücksichtigen, weil Sie für diesen Zeitraum keine Nachweise vorgelegt "
           "haben. Reichen Sie Unterlagen nach, prüfen wir das gern erneut.")],
        [("Versicherungsnummer", "65 140383 M 044")], [], "2025-09-30", "vierten", "Sehr geehrter Herr Musterschmidt,", photo=True,
        notes="The deemed-delivery day is Sunday the 31st (no shift outside tax law): the period ends on 30.09.",
    ))  # fmt: skip
    # J2 — Agentur für Arbeit (SGB III → SGB X). Posted Thu 05.12.2024 → day 3 = Sun 08.12.2024 (no shift) → Wed 08.01.2025.
    # (The 4-day rule would give Mon 09.12. → Thu 09.01.2025.)
    cases.append(variant_j(
        "holdout3-year_boundary-J2", O.R_AA, O.R_GEN2, date(2024, 12, 5), "Bewilligung von Arbeitslosengeld ab 01.01.2025",
        [P("auf Ihren Antrag vom 18.11.2024 bewilligen wir Ihnen Arbeitslosengeld ab dem 01.01.2025 für 360 Kalendertage."),
         Table(rows=(("Bemessungsentgelt täglich", "96,74"), ("Leistungsentgelt täglich", "62,15"),
                     ("Arbeitslosengeld täglich (60 %)", "37,29"), ("Arbeitslosengeld für 30 Tage", "1.118,70")),
               header=("Berechnung", "EUR"), bold_rows=(3,), rule_before=(3,), value_width=30),
         P("Das Arbeitslosengeld zahlen wir monatlich nachträglich auf Ihr Konto. Bitte melden Sie uns jede Änderung sofort, "
           "zum Beispiel eine Arbeitsaufnahme oder eine Erkrankung.")],
        [("Kundennummer", "617C442095")], [1118.70], "2025-01-08", "dritten", "Sehr geehrte Frau Beispielwinkel,",
        notes="Posted before 2025-01-01: 3-day fiction; day 3 is a Sunday and does not move outside tax law.",
    ))  # fmt: skip
    return cases
