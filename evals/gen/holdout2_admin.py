"""Holdout2 split, families 1, 2, 3, 7 and 12: variants G and H of the administrative acts.

Written after the release's last code change, from the law and from how such letters read, without
opening the app's ingestion code, its prompts, the recordings or the results files: new senders,
recipients, wording, layout, dates, amounts and regions. Variant G prints the date first in the
information block and the Rechtsbehelfsbelehrung in a framed box; variant H prints the bare date
right-aligned above the subject and the Belehrung under its own heading. No deadline-bearing sentence
of variants A–F recurs (``evals/verify_labels.py`` checks it).

The posting, letter and service days were drawn with a seeded random choice among the days that fit
each letter's scenario (``rng_for("holdout2", case_id)``; a day another split already uses was left
out); ``hand`` is the expected date worked out by hand from the calendar and is asserted against the
computed label.
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

SPLIT = "holdout2"
STYLES = {
    "G": Style(body_pt=9.8, left=21, right=21, leading=1.34, para_gap=2.2, align="L", info_label_pt=6.9,
               info_value_pt=8.4, subject_pt=10.9),
    "H": Style(body_pt=10.0, left=25, right=21, leading=1.4, para_gap=2.6, align="J", info_label_pt=7.2,
               info_value_pt=8.7, subject_pt=11.4),
}  # fmt: skip


def date_line(d: date) -> str:
    """Variant H's date: the bare date, right-aligned above the subject."""
    return de(d)


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _belehrung_box(*lines: str) -> Box:
    """Variant G's Rechtsbehelfsbelehrung: a framed box with its heading in bold."""
    return Box(("Rechtsbehelfsbelehrung", *lines), fill=(244, 245, 240))


# ==================================================================================================
# Family 1 — tax_assessment (AO: fiction day moves off Sat/Sun/holidays; § 355 AO one month)
# ==================================================================================================


def _assessment_table(year: int, rows: list[tuple[str, int]], est: int, withheld: int) -> Table:
    """Income lines (later lines signed: + adds, – deducts), the tax set, the tax already withheld and the balance."""
    taxable = sum(v for _, v in rows)
    diff = est - withheld
    body = [(rows[0][0], _thousands(rows[0][1]))]
    body += [(label, f"{'+' if v > 0 else '–'} {_thousands(abs(v))}") for label, v in rows[1:]]
    body += [
        (f"Zu versteuerndes Einkommen {year}", _thousands(taxable)),
        ("Festgesetzte Einkommensteuer", eur_plain(est)),
        ("Davon ab: einbehaltene Lohnsteuer", f"– {eur_plain(withheld)}"),
        ("Noch zu zahlen" if diff > 0 else "Zu erstatten", eur_plain(abs(diff))),
    ]
    n = len(rows)
    return Table(rows=tuple(body), header=("Berechnung", "Euro"), value_width=32, bold_rows=(n, n + 3),
                 rule_before=(n, n + 3))  # fmt: skip


def tax_assessment() -> list[Case]:
    cases: list[Case] = []

    # --- variant G: date first in the info block, refund, Belehrung in a box ---------------------------
    def variant_g(case_id: str, org: Org, person: Person, posted: date, year: int, stnr: str, idnr: str,
                  rows: list[tuple[str, int]], est: int, withheld: int, filed: date, note: str, hand: str) -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="ao", remedy="einspruch", region=org.region,
                           title=f"Einspruchsfrist Einkommensteuerbescheid {year}"),
            hand,
        )  # fmt: skip
        refund = withheld - est
        assert refund > 0
        letter = Letter(
            org=org, recipient=person,
            info=[("Datum", de(posted)), ("Steuernummer", stnr), ("Identifikationsnummer", idnr),
                  ("Bearbeitung", "Sachgebiet 21 · Durchwahl -214")],
            subject=f"Bescheid für {year} über Einkommensteuer",
            subject_extra=(f"Festsetzung nach Ihrer Erklärung, eingegangen am {de(filed)}",),
            blocks=[
                P(f"Die Einkommensteuer für das Jahr {year} wird nach den folgenden Besteuerungsgrundlagen festgesetzt:"),
                _assessment_table(year, rows, est, withheld),
                P(f"Den Betrag von **{eur(refund)}** erstatten wir auf Ihr Konto {iban_grouped(O.Q_RECIPIENT_IBAN)}. "
                  "Er wird in den nächsten Tagen gutgeschrieben."),
                H("Erläuterungen"),
                P(note),
                _belehrung_box(
                    f"Gegen die Festsetzung können Sie sich mit einem Einspruch wehren. Der Einspruch muss innerhalb eines Monats {bei(org.name)} "
                    "eingehen; die Frist beginnt mit dem Tag nach der Bekanntgabe. Einen Bescheid, den wir mit einfachem Brief "
                    "schicken, behandelt das Gesetz am vierten Tag nach dem Absenden als bekannt gegeben – es sei denn, er ist Ihnen "
                    "nicht oder später zugegangen.",
                    "Einlegen können Sie den Einspruch schriftlich, über ELSTER oder durch Erklärung an Amtsstelle.",
                ),
                P("Dieser Bescheid wurde maschinell erstellt und ist ohne Unterschrift wirksam.", size=7.8),
            ],
            style=STYLES["G"], created=created(posted), running_ref=f"StNr. {stnr} · {de(posted)}",
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="tax_assessment", variant="G", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=posted,
                        references=[("Steuernummer", stnr), ("Identifikationsnummer", idnr)], amounts=[float(refund)],
                        remedy="einspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), "Der Einspruch muss innerhalb eines Monats", stnr],
        )  # fmt: skip

    # G1 — TH. Posted Mon 16.08.2027 → day 4 = Fri 20.08. (working day) → one month → Mon 20.09.2027, Weltkindertag in TH →
    # Tue 21.09.2027. Nationwide holidays only would keep Mon 20.09.
    cases.append(variant_g(
        "holdout2-tax_assessment-G1", O.Q_FA_TH, O.Q_TH, date(2027, 8, 16), 2026, "161/208/41537", "48 230 175 966",
        [("Einkünfte aus nichtselbständiger Arbeit (Bruttoarbeitslohn)", 51_640), ("Werbungskosten", -4_386),
         ("Sonderausgaben und Vorsorgeaufwendungen", -7_912)], 6_744, 7_603, date(2027, 5, 3),
        "Die Werbungskosten enthalten die Entfernungspauschale für 212 Arbeitstage und die Kosten Ihrer Fortbildung zur "
        "Techniker. Die Spenden an den Beispiel Kinderhospiz e. V. wurden in der nachgewiesenen Höhe berücksichtigt.",
        "2027-09-21",
    ))  # fmt: skip
    # G2 — Land unknown. Posted Thu 05.06.2025 → day 4 = Mon 09.06.2025 Pfingstmontag → Tue 10.06. → Thu 10.07.2025.
    cases.append(variant_g(
        "holdout2-tax_assessment-G2", O.Q_FA_X, O.Q_GEN, date(2025, 6, 5), 2024, "65/112/30894", "71 604 293 518",
        [("Bruttoarbeitslohn aus zwei Dienstverhältnissen", 38_215), ("Werbungskosten", -1_642),
         ("Vorsorgeaufwendungen und Sonderausgaben", -6_377)], 4_518, 5_197, date(2025, 3, 24),
        "Für das zweite Dienstverhältnis wurde die Lohnsteuer nach Steuerklasse VI einbehalten; daraus erklärt sich der größte "
        "Teil der Erstattung. Die Kinderbetreuungskosten wurden zu zwei Dritteln als Sonderausgaben angesetzt.",
        "2025-07-10",
    ))  # fmt: skip

    # --- variant H: bare date above the subject, Belehrung under a heading ------------------------------
    def variant_h(case_id: str, org: Org, person: Person, salutation: str, letter_date: date, posted: date, year: int, stnr: str,
                  rows: list[tuple[str, int]], est: int, withheld: int, intro: str, hand: str, pay_due: date | None = None,
                  hand_pay: str | None = None) -> Case:  # fmt: skip
        items = [
            check(
                objection_item(posted=posted, scope="ao", remedy="einspruch", region=org.region,
                               title=f"Einspruchsfrist Einkommensteuerbescheid {year}"),
                hand,
            )
        ]  # fmt: skip
        diff = est - withheld
        blocks: list[Block] = [P(intro), _assessment_table(year, rows, est, withheld)]
        if diff > 0:
            assert pay_due is not None and hand_pay is not None
            items.append(check(
                fixed_item(due=pay_due, region=org.region, kind="payment", nature="payment",
                           title=f"Einkommensteuer {year} nachzahlen", money=float(diff),
                           rule="Payment date printed in the assessment (Fälligkeit as set by the Finanzamt)."),
                hand_pay,
            ))  # fmt: skip
            blocks.append(P(f"Bitte überweisen Sie den Betrag von **{eur(diff)}** so, dass er spätestens am **{de(pay_due)}** "
                            f"auf unserem Konto gutgeschrieben ist ({org.bank}, IBAN {iban_grouped(org.iban)}). Geben Sie "
                            f"als Verwendungszweck „{stnr} ESt {year}“ an."))  # fmt: skip
        else:
            blocks.append(P(f"Der Erstattungsbetrag von **{eur(-diff)}** wird an Sie ausgezahlt; dafür verwenden wir das Konto, das "
                            "Sie in Ihrer Steuererklärung angegeben haben."))  # fmt: skip
        blocks += [
            H("Rechtsbehelfsbelehrung"),
            P("Ein Einspruch ist innerhalb eines Monats zu erheben; der Tag, an dem Ihnen der Bescheid bekannt gegeben wird, zählt "
              "dabei nicht mit. Wird der Bescheid mit einfachem Brief übermittelt, gilt er mit dem vierten Tag nach seiner Aufgabe zur "
              "Post als bekannt gegeben (§ 122 Abs. 2 Nr. 1 AO), es sei denn, er ist nicht oder später zugegangen. Zuständig ist das "
              f"{org.name}; den Einspruch nimmt es schriftlich, elektronisch über ELSTER oder zur Niederschrift entgegen.", size=8.9),
            Sign("Mit freundlichen Grüßen", ("Ihr Finanzamt",)),
        ]  # fmt: skip
        info = [("Steuernummer", stnr), ("Ansprechpartner", "Herr Wendt, Zimmer 2.07")]
        if posted != letter_date:
            info.append(("Tag der Aufgabe zur Post", de(posted)))
        letter = Letter(
            org=org, recipient=person, info=info, date_line=date_line(letter_date),
            subject=f"Einkommensteuerbescheid {year}", salutation=salutation, blocks=blocks, style=STYLES["H"],
            created=created(letter_date),
            running_ref=f"Steuernummer {stnr}",
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="tax_assessment", variant="H", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=letter_date, references=[("Steuernummer", stnr)],
                        amounts=[float(abs(diff))], remedy="einspruch", items=items),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), de(posted), "der Tag, an dem Ihnen der Bescheid bekannt gegeben wird, zählt dabei nicht mit", stnr,
                         *([de(pay_due)] if pay_due else [])],
            notes="Posting day stated in the info block, a day after the Bescheid date." if posted != letter_date else "",
        )  # fmt: skip

    # H1 — BB. Bescheid Mon 23.06.2025, posted Tue 24.06.2025 → day 4 = Sat 28.06. → Mon 30.06. → Wed 30.07.2025.
    # Payment date printed by the office: Tue 22.07.2025.
    cases.append(variant_h(
        "holdout2-tax_assessment-H1", O.Q_FA_BB, O.Q_BB, "Sehr geehrte Frau Beispielwitz,", date(2025, 6, 23), date(2025, 6, 24), 2024, "046/219/05731",
        [("Einkünfte aus nichtselbständiger Arbeit", 44_180), ("Einkünfte aus Vermietung und Verpachtung", 4_870),
         ("Sonderausgaben und Vorsorgeaufwendungen", -6_904)], 8_213, 6_975,
        "für das Kalenderjahr 2024 setzen wir die Einkommensteuer fest. Neben Ihrem Arbeitslohn sind erstmals die Mieteinnahmen "
        "aus der Wohnung Havelufer 14 berücksichtigt:", "2025-07-30", date(2025, 7, 22), "2025-07-22",
    ))  # fmt: skip
    # H2 — SH. Posted Fri 02.04.2027 → day 4 = Tue 06.04. → one month → Thu 06.05.2027 Christi Himmelfahrt → Fri 07.05.2027.
    cases.append(variant_h(
        "holdout2-tax_assessment-H2", O.Q_FA_SH, O.Q_SH, "Sehr geehrter Herr Musterjensen,", date(2027, 4, 2), date(2027, 4, 2), 2025, "15/287/40312",
        [("Einkünfte aus nichtselbständiger Arbeit", 29_870), ("Werbungskosten (Arbeitszimmer, Fahrten)", -2_418),
         ("Sonderausgaben und Vorsorgeaufwendungen", -4_955)], 2_766, 3_489,
        "Ihre Einkommensteuererklärung für 2025 haben wir geprüft. Abweichend von Ihren Angaben haben wir die Kosten des "
        "häuslichen Arbeitszimmers mit der Jahrespauschale angesetzt:", "2027-05-07",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 2 — municipal_decision (Land VwVfG: 4th-day fiction WITHOUT shift; Widerspruch/Klage)
# ==================================================================================================


def municipal_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, salutation: str, posted: date, remedy: str, subject: str,
             ref: tuple[str, str], body: list[Block], belehrung: list[str], key: str, hand: str, signer: str,
             extra_items: list | None = None, photo: bool = False, notes: str = "", more_keys: list[str] | None = None) -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="vwvfg", remedy=remedy, region=org.region,
                           title="Klagefrist" if remedy == "klage" else "Widerspruchsfrist",
                           note=("Remedy is Klage: SPEC §21 shows a 'get advice' card instead of a computed date; the legal date is "
                                 "still the label.") if remedy == "klage" else None),
            hand,
        )  # fmt: skip
        if variant == "G":
            info = [("Datum", de(posted)), ref, ("Sachbearbeitung", signer), ("Telefon", "Durchwahl -3318")]
            tail: list[Block] = [
                _belehrung_box(*belehrung),
                Sign("Mit freundlichen Grüßen", (signer,), signature=True),
            ]
            line = None
        else:
            info = [ref, ("Zimmer", "B 2.14"), ("Sprechzeiten", "Di und Do 9–12 Uhr")]
            tail = [H("Rechtsbehelfsbelehrung"), *(P(text, size=8.9) for text in belehrung),
                    Sign("Mit freundlichen Grüßen", ("Im Auftrag", signer), signature=True)]  # fmt: skip
            line = date_line(posted)
        letter = Letter(
            org=org, recipient=person, info=info, subject=subject, salutation=salutation, date_line=line,
            blocks=[*body, *tail], style=STYLES[variant], created=created(posted), running_ref=" ".join(ref),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="municipal_decision", variant=variant, letter=letter,
            truth=truth(kind="authority_letter", sender=org.name, document_date=posted, references=[ref], amounts=[],
                        remedy=remedy, items=[item, *(extra_items or [])]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), ref[1], key, *(more_keys or [])], photo=photo, notes=notes,
        )  # fmt: skip

    # G1 — BW, Widerspruch. Posted Wed 02.12.2026 → day 4 = Sun 06.12. (no shift) → Wed 06.01.2027, Heilige Drei Könige in BW
    # → Thu 07.01.2027. Nationwide holidays only would keep Wed 06.01.
    org = O.Q_STADT_BW
    cases.append(make(
        "holdout2-municipal_decision-G1", "G", org, O.Q_BW, "Sehr geehrte Frau Beispielbauer,", date(2026, 12, 2), "widerspruch",
        "Antrag auf Befreiung von der Baumschutzsatzung – Fällung einer Rotbuche, Rebenweg 18", ("Aktenzeichen", "67.20-BS-2026-1184"),
        [
            P("Sie haben am 28.10.2026 beantragt, die Rotbuche im Vorgarten Ihres Grundstücks Rebenweg 18 (Stammumfang 2,10 m) fällen "
              "zu dürfen, weil das Laub die Dachrinnen verstopft und der Baum die Terrasse beschattet."),
            P("Diesen Antrag lehne ich ab. Der Baum ist nach dem Gutachten unseres Baumkontrolleurs vom 12.11.2026 gesund und "
              "standsicher. Laubfall und Verschattung sind übliche Begleiterscheinungen eines Baumes und rechtfertigen keine Befreiung "
              "nach § 6 der Baumschutzsatzung der Stadt Musterfreiburg. Für den Rückschnitt einzelner Äste über dem Dach können Sie "
              "eine Genehmigung beantragen."),
            P("Dieser Bescheid ist gebührenfrei."),
        ],
        [f"Gegen diesen Bescheid ist innerhalb eines Monats nach seiner Bekanntgabe der Widerspruch {bei(org.name)}, {org.street}, "
         f"{org.postcode} {org.city}, zulässig. Er kann schriftlich, zur Niederschrift oder elektronisch mit qualifizierter "
         "elektronischer Signatur eingelegt werden.",
         "Für die Bekanntgabe gilt: Ein durch die Post übermittelter Bescheid ist am vierten Tag nach seiner Absendung bekannt "
         "gegeben (§ 41 Abs. 2 LVwVfG)."],
        "innerhalb eines Monats nach seiner Bekanntgabe der Widerspruch", "2027-01-07", "Frau Kessler",
        notes="The Widerspruch period ends on Heilige Drei Könige (06.01.2027), a holiday in BW — moved to Thursday.",
    ))  # fmt: skip

    # G2 — SH, Widerspruch. Posted Wed 02.07.2025 → day 4 = Sun 06.07. (no shift) → Wed 06.08.2025.
    org = O.Q_AMT_SH
    cases.append(make(
        "holdout2-municipal_decision-G2", "G", org, O.Q_SH, "Sehr geehrter Herr Musterjensen,", date(2025, 7, 2), "widerspruch",
        "Anordnung von Leinen- und Maulkorbzwang für Ihren Hund „Bruno“", ("Geschäftszeichen", "32.1-HU-25/0611"),
        [
            P("am 14.06.2025 hat Ihr Hund auf dem Strandweg in Beispielhusby einen anderen Hund gebissen und dessen Halterin, die "
              "dazwischenging, an der Hand verletzt. Den Vorfall haben zwei Zeugen bestätigt; Sie selbst haben ihn bei Ihrer Anhörung "
              "am 25.06.2025 nicht bestritten."),
            P("Nach dem Gesetz über das Halten von Hunden ordne ich deshalb an, dass Sie Ihren Hund außerhalb Ihres eingefriedeten "
              "Grundstücks ab sofort an einer höchstens zwei Meter langen Leine führen und ihm einen Maulkorb anlegen. Die Anordnung "
              "gilt, bis ein Wesenstest das Gegenteil belegt."),
        ],
        [f"Gegen diese Anordnung ist innerhalb eines Monats nach ihrer Bekanntgabe der Widerspruch {bei(org.name)}, {org.street}, "
         f"{org.postcode} {org.city}, gegeben – schriftlich oder zur Niederschrift. Ein per Post versandtes Schreiben gilt am vierten "
         "Tag nach Aufgabe zur Post als bekannt gegeben."],
        "innerhalb eines Monats nach ihrer Bekanntgabe der Widerspruch", "2025-08-06", "Herr Clausen", photo=True,
        notes="The deemed-delivery day is a Sunday; outside tax law it does not move.",
    ))  # fmt: skip

    # H1 — NW, Klage + removal date. Posted Mon 22.09.2025 → day 4 = Fri 26.09. → Sun 26.10.2025 → Mon 27.10.2025.
    posted, removal = date(2025, 9, 22), date(2025, 11, 28)
    task = check(
        fixed_item(due=removal, region="NW", kind="task", nature="other", title="Carport im Vorgarten beseitigen",
                   rule="Compliance deadline set by the authority as a calendar date."),
        "2025-11-28",
    )  # fmt: skip
    org = O.Q_STADT_NW
    cases.append(make(
        "holdout2-municipal_decision-H1", "H", org, O.Q_NW, "Sehr geehrter Herr Musterski,", posted, "klage",
        "Ordnungsverfügung – Beseitigung des ungenehmigten Carports auf dem Grundstück Hüttenstraße 27", ("Az.", "63.2-BV-2025-2207"),
        [
            P("bei einer Kontrolle am 02.09.2025 wurde festgestellt, dass Sie im Vorgarten Ihres Grundstücks einen Carport aus Holz "
              "(5,60 m × 3,20 m) errichtet haben. Eine Baugenehmigung liegt nicht vor. Der Bebauungsplan Nr. 412 setzt für den Vorgarten "
              "eine nicht überbaubare Fläche fest; eine Befreiung kommt nicht in Betracht."),
            P(f"Ich gebe Ihnen daher nach § 82 BauO NRW auf, den Carport **bis spätestens {de(removal)}** vollständig zu beseitigen. "
              "Erfüllen Sie diese Pflicht nicht fristgerecht, setze ich ein Zwangsgeld von 2.000,00 € fest; es wird hiermit angedroht."),
            P("Die Gebühr für diese Verfügung wird mit gesondertem Bescheid erhoben."),
        ],
        ["Diese Verfügung können Sie durch Klage beim Verwaltungsgericht Beispielgelsen, Bahnhofsvorplatz 3, 45879 Beispielgelsen, "
         "anfechten; die Klage ist innerhalb eines Monats nach Bekanntgabe zu erheben. Sie ist schriftlich einzureichen oder zur Niederschrift "
         "der Urkundsbeamtin oder des Urkundsbeamten der Geschäftsstelle zu erklären. Eines Vorverfahrens bedarf es nicht "
         "(§ 110 JustG NRW)."],
        "Klage beim Verwaltungsgericht Beispielgelsen", "2025-10-27", "Lindemann", extra_items=[task],
        more_keys=[de(removal)],
    ))  # fmt: skip

    # H2 — HH, Widerspruch. Posted Tue 13.04.2027 → day 4 = Sat 17.04. (no shift) → Mon 17.05.2027 Pfingstmontag → Tue 18.05.2027.
    org = O.Q_BA_HH
    cases.append(make(
        "holdout2-municipal_decision-H2", "H", org, O.Q_HH, "Sehr geehrter Herr Mustermöller,", date(2027, 4, 13), "widerspruch",
        "Ihr Antrag auf Sondernutzung – Abstellen eines Bauschuttcontainers vor dem Haus Fleetstieg 9", ("Az.", "MR 31/27-0442"),
        [
            P("Sie möchten vom 03.05. bis 28.05.2027 einen Container (7 m³) für Bauschutt auf dem Gehweg vor Ihrem Haus abstellen. "
              "Diese Sondernutzung des öffentlichen Wegs kann ich nicht erlauben."),
            P("Der Gehweg ist an dieser Stelle nur 1,80 m breit. Mit dem Container blieben für Fußgängerinnen und Fußgänger, Kinderwagen "
              "und Rollstühle weniger als 1,00 m – das ist nach dem Hamburgischen Wegegesetz nicht hinnehmbar. Auf der Fahrbahn ist "
              "wegen der Busspur kein Platz. Bitte prüfen Sie, ob der Container auf Ihrem Grundstück stehen kann."),
        ],
        [f"Sie sind mit der Ablehnung nicht einverstanden? Dann können Sie Widerspruch erheben. Dafür haben Sie einen Monat Zeit, gerechnet ab der "
         f"Bekanntgabe. Richten Sie den Widerspruch schriftlich oder zur Niederschrift an das {org.name}, {org.street}, "
         f"{org.postcode} {org.city}.",
         "Einen Bescheid, den wir mit der Post schicken, behandelt das Gesetz am vierten Tag nach der Aufgabe zur Post als bekannt "
         "gegeben."],
        "Dafür haben Sie einen Monat Zeit, gerechnet ab der Bekanntgabe", "2027-05-18", "Petersen",
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
             rule: str | None = None, closing: tuple[str, ...] = ()) -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted,
                scope="sgbx",
                remedy="widerspruch",
                region=org.region,
                title="Widerspruchsfrist",
                rule=rule,
            ),
            hand,
        )
        if variant == "G":
            info = [("Datum", de(posted)), *refs]
            tail: list[Block] = [
                _belehrung_box(*belehrung),
                Sign("Freundliche Grüße", closing or (org.name,)),
            ]
            line = None
        else:
            info = list(refs)
            tail = [H("Rechtsbehelfsbelehrung"), *(P(text, size=8.9) for text in belehrung),
                    Sign("Mit freundlichen Grüßen", closing or ("Im Auftrag",))]  # fmt: skip
            line = date_line(posted)
        letter = Letter(
            org=org, recipient=person, info=info, subject=subject, salutation=salutation, date_line=line,
            blocks=[*body, *tail], style=STYLES[variant], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="social_decision", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts or [], remedy="widerspruch",
                        items=[item, *(extra_items or [])]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), key], photo=photo, notes=notes,
        )  # fmt: skip

    # G1 — IKK, Land unknown. Posted Tue 20.04.2027 → day 4 = Sat 24.04. (no shift) → Mon 24.05.2027.
    org = O.Q_IKK
    cases.append(make(
        "holdout2-social_decision-G1", "G", org, O.Q_GEN2, "Sehr geehrter Herr Beispielgaard,", date(2027, 4, 20), "health_insurance",
        "Ihr Antrag auf Haushaltshilfe nach § 38 SGB V", [("Versichertennummer", "R512077348"), ("Vorgang", "HH-27-04412")],
        [
            P("Sie haben für die Zeit Ihrer Reha-Maßnahme vom 03.05. bis 24.05.2027 eine Haushaltshilfe beantragt. Wir haben Ihren "
              "Antrag sorgfältig geprüft, können ihm aber leider nicht entsprechen."),
            P("Haushaltshilfe zahlen wir als Satzungsleistung nur, wenn im Haushalt ein Kind lebt, das bei Beginn der Leistung das "
              "zwölfte Lebensjahr noch nicht vollendet hat, oder wenn niemand sonst im Haushalt die Arbeit übernehmen kann. Ihre "
              "Tochter ist 14 Jahre alt, und Ihre Ehefrau lebt mit Ihnen im Haushalt."),
        ],
        ["Sie können die Ablehnung mit einem Widerspruch angreifen. Ihr Widerspruch muss uns innerhalb eines Monats erreichen, "
         f"nachdem Ihnen der Bescheid bekannt gegeben wurde – schriftlich oder zur Niederschrift {bei(org.name)}, {org.street}, "
         f"{org.postcode} {org.city}."],
        "Ihr Widerspruch muss uns innerhalb eines Monats erreichen", "2027-05-24", closing=("Ihre IKK Mustertal", "Team Häusliche Versorgung"),
    ))  # fmt: skip

    # G2 — Rentenversicherung, Land unknown. Posted Wed 29.09.2027 → day 4 = Sun 03.10.2027 (Tag der Deutschen Einheit; no shift)
    # → Wed 03.11.2027.
    org = O.Q_RV
    cases.append(make(
        "holdout2-social_decision-G2", "G", org, O.Q_GEN, "Sehr geehrte Frau Musterkamp,", date(2027, 9, 29), "social_insurance",
        "Ihr Antrag auf Rente wegen Erwerbsminderung vom 07.06.2027", [("Versicherungsnummer", "23 140983 K 517")],
        [
            P("Ihren Antrag auf Rente wegen Erwerbsminderung lehnen wir ab."),
            P("Nach den Feststellungen unseres Sozialmedizinischen Dienstes können Sie leichte Arbeiten im Wechsel von Sitzen, Gehen "
              "und Stehen noch mindestens sechs Stunden täglich verrichten. Damit sind Sie weder voll noch teilweise erwerbsgemindert "
              "(§ 43 SGB VI). Ob Ihnen Leistungen zur Teilhabe am Arbeitsleben helfen können, prüfen wir gesondert; Sie erhalten dazu "
              "ein eigenes Schreiben."),
        ],
        [f"Wer mit diesem Bescheid nicht einverstanden ist, kann ihn mit dem Widerspruch anfechten; dafür steht ab der Bekanntgabe "
         f"ein Monat zur Verfügung. Richten Sie ihn schriftlich oder zur Niederschrift an die {org.name}, {org.street}, "
         f"{org.postcode} {org.city}."],
        "dafür steht ab der Bekanntgabe ein Monat zur Verfügung", "2027-11-03", photo=True,
        notes="The deemed-delivery day is a Sunday and a holiday; outside tax law it does not move.",
        closing=("Rentenversicherung Beispiel-Mitte",),
    ))  # fmt: skip

    # H1 — Wohngeldstelle BE + submission date. Posted Fri 04.04.2025 → day 4 = Tue 08.04. → Thu 08.05.2025, in BE a one-off
    # holiday (80th anniversary of the liberation) → Fri 09.05.2025. Nationwide holidays only would keep Thu 08.05.
    posted, submit = date(2025, 4, 4), date(2025, 4, 24)
    task = check(
        fixed_item(due=submit, region="BE", kind="task", nature="declaration", title="Mietbescheinigung für 2025 einreichen",
                   rule="Submission deadline set by the authority as a calendar date."),
        "2025-04-24",
    )  # fmt: skip
    org = O.Q_BA_BE
    cases.append(make(
        "holdout2-social_decision-H1", "H", org, O.Q_BE, "Sehr geehrte Frau Musterkaya,", posted, "social_insurance",
        "Bescheid über Wohngeld (Mietzuschuss) für die Zeit vom 01.03.2025 bis 28.02.2026",
        [("Wohngeldnummer", "WG 0417-25-2291"), ("Haushaltsmitglieder", "2")],
        [
            P("auf Ihren Antrag vom 21.02.2025 bewilligen wir Ihnen für die Zeit vom 01.03.2025 bis 28.02.2026 Wohngeld in Höhe "
              "von **312,00 € monatlich**. Die Berechnung finden Sie in der Anlage."),
            P(f"Die Miete für März 2025 haben Sie mit dem alten Mietvertrag belegt. Bitte senden Sie uns **bis zum {de(submit)}** die "
              "Mietbescheinigung Ihrer Vermieterin für die neue Miete ab Januar 2025 zu. Geht sie nicht rechtzeitig ein, kann das "
              "Wohngeld nach § 27 WoGG neu berechnet und zu viel gezahltes Wohngeld zurückgefordert werden."),
        ],
        ["Ist Ihrer Meinung nach etwas falsch entschieden worden, legen Sie bitte Widerspruch ein. Erheben Sie ihn binnen eines Monats "
         f"ab Bekanntgabe schriftlich oder zur Niederschrift beim {org.name}, {org.street}, {org.postcode} {org.city}. Schicken wir "
         "Ihnen den Bescheid mit der Post, ist er nach § 37 Abs. 2 SGB X am vierten Tag nach dem Absenden bekannt gegeben."],
        "Erheben Sie ihn binnen eines Monats ab Bekanntgabe", "2025-05-09", amounts=[312.0], extra_items=[task],
        rule="Widerspruch against a Wohngeld decision: one month after Bekanntgabe (§ 70 Abs. 1 VwGO); Wohngeld is a social benefit "
             "(§ 68 Nr. 10 SGB I), so § 37 Abs. 2 SGB X governs the deemed delivery.",
        notes="The Widerspruch period ends on 08.05.2025, a one-off holiday in BE — moved to Friday.",
        closing=("Im Auftrag", "Szymański"),
    ))  # fmt: skip

    # H2 — Jugendamt HE (Unterhaltsvorschuss). Posted Mon 15.09.2025 → day 4 = Fri 19.09. → Sun 19.10.2025 → Mon 20.10.2025.
    org = O.Q_JA_HE
    cases.append(make(
        "holdout2-social_decision-H2", "H", org, O.Q_HE, "Sehr geehrter Herr Beispielhofer,", date(2025, 9, 15), "social_insurance",
        "Unterhaltsvorschuss für Ihre Tochter Mila, geboren am 11.02.2018", [("Aktenzeichen", "51.4-UV-2025-0718")],
        [
            P("für Ihre Tochter Mila zahlen wir ab dem 01.08.2025 Unterhaltsleistungen nach dem Unterhaltsvorschussgesetz in Höhe "
              "von **299,00 € monatlich**. Der Betrag wird jeweils zum Monatsanfang auf Ihr Konto überwiesen."),
            P("Teilen Sie uns bitte unverzüglich mit, wenn Mila nicht mehr bei Ihnen lebt, wenn Sie heiraten oder wenn der andere "
              "Elternteil Unterhalt zahlt. Den Unterhaltsanspruch Ihrer Tochter gegen den anderen Elternteil machen wir selbst geltend."),
        ],
        [f"Gegen die Bewilligung in dieser Höhe ist ein Widerspruch möglich. Einen Widerspruch reichen Sie bitte binnen Monatsfrist "
         f"nach Bekanntgabe ein, und zwar schriftlich oder zur Niederschrift beim {org.name}, {org.street}, {org.postcode} {org.city}."],
        "binnen Monatsfrist nach Bekanntgabe", "2025-10-20", amounts=[299.0],
        rule="Widerspruch against an Unterhaltsvorschuss decision: one month after Bekanntgabe (§ 70 Abs. 1 VwGO); UVG is a social "
             "benefit (§ 68 Nr. 14 SGB I), so § 37 Abs. 2 SGB X governs the deemed delivery.",
        closing=("Im Auftrag", "Brückner"),
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 7 — fine_bussgeld (OWiG: Einspruch 2 weeks after Zustellung, § 67 OWiG, § 43 StPO)
# ==================================================================================================


def fine_bussgeld() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, variant: str, org: Org, person: Person, letter_date: date, served: date, plate: str, when: str, place: str,
             charge: str, rules: str, fine: float, points: int, hand: str, az: str, note: str) -> Case:  # fmt: skip
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
            f"Die Ordnungswidrigkeit wird mit {points} Punkt im Fahreignungsregister eingetragen."
            if points == 1
            else "Eine Eintragung im Fahreignungsregister erfolgt nicht."
        )
        costs_table = Table(rows=(("Geldbuße", eur_plain(fine)), ("Gebühr (§ 107 Abs. 1 OWiG)", eur_plain(fee)),
                                  ("Auslagen (§ 107 Abs. 3 OWiG)", eur_plain(costs)), ("Gesamtbetrag", eur_plain(total))),
                            header=("Festgesetzt werden", "Euro"), bold_rows=(3,), rule_before=(3,))  # fmt: skip
        if variant == "G":
            info = [("Datum", de(letter_date)), ("Aktenzeichen", az), ("Kennzeichen", plate)]
            refs = [("Aktenzeichen", az), ("Kennzeichen", plate)]
            blocks: list[Block] = [
                H("Ihnen wird Folgendes zur Last gelegt"),
                P(f"Sie führten am {when} in {place} den Pkw mit dem amtlichen Kennzeichen {plate}. Dabei {charge}"),
                P(f"Rechtsgrundlagen: {rules}. Beweismittel: Messung mit geeichtem Gerät, Lichtbild, Messprotokoll.", size=8.5),
                costs_table,
                P(f"{register} Den Gesamtbetrag zahlen Sie bitte, sobald dieser Bescheid rechtskräftig ist – spätestens zwei Wochen "
                  f"danach – unter Angabe des Aktenzeichens auf das Konto {iban_grouped(org.iban)}."),
                H("Rechtsbehelfsbelehrung"),
                P("Legen Sie nicht binnen zwei Wochen nach der Zustellung Einspruch ein, wird dieser Bescheid rechtskräftig, und die "
                  f"Geldbuße kann vollstreckt werden. Den Einspruch richten Sie schriftlich oder zur Niederschrift an die oben genannte "
                  f"Verwaltungsbehörde ({org.name}). Legen Sie Einspruch ein, entscheidet gegebenenfalls das Amtsgericht; es ist "
                  "dabei nicht an diesen Bescheid gebunden.", size=8.8),
            ]  # fmt: skip
            key = "Legen Sie nicht binnen zwei Wochen nach der Zustellung Einspruch ein"
            line = None
        else:
            info = [("Az.", az), ("Fahrzeug", plate)]
            refs = [("Az.", az), ("Fahrzeug", plate)]
            blocks = [
                P(f"Tatzeit: {when} · Tatort: {place}", bold=True, gap=1.2),
                P(f"Ihnen wird folgende Ordnungswidrigkeit mit dem Kraftfahrzeug {plate} vorgeworfen: {charge}"),
                P(f"Angewandte Vorschriften: {rules}", size=8.5, indent=4),
                costs_table,
                P(f"{register} Der Gesamtbetrag ist zwei Wochen nach Rechtskraft fällig."),
                H("Rechtsbehelfsbelehrung"),
                P("Sie können diesen Bußgeldbescheid mit dem Einspruch anfechten; er muss innerhalb von zwei Wochen ab der Zustellung "
                  f"vorliegen (§ 67 Abs. 1 OWiG), schriftlich oder zur Niederschrift {bei(org.name)}. Nach einem Einspruch kann das "
                  "Gericht auch eine höhere Geldbuße festsetzen.", size=8.8),
            ]  # fmt: skip
            key = "innerhalb von zwei Wochen ab der Zustellung"
            line = date_line(letter_date)
        blocks.append(Envelope(sender=org.name, recipient=person, reference=az, note=note, initials="Wr."))
        letter = Letter(
            org=org, recipient=person, info=info, date_line=line, subject="Bußgeldbescheid", blocks=blocks,
            style=STYLES[variant], created=created(letter_date), running_ref=f"Az. {az}",
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

    # G1 — SN: served Wed 04.11.2026 → Wed 18.11.2026 Buß- und Bettag (SN) → Thu 19.11.2026. Nationwide only: Wed 18.11.
    cases.append(make(
        "holdout2-fine_bussgeld-G1", "G", O.Q_BG_SN, O.Q_SN, date(2026, 10, 30), date(2026, 11, 4), "PIR-HM 418", "06.10.2026 um 22:14 Uhr",
        "der Gemarkung Musterpirna, Staatsstraße S 172, km 4,3, Fahrtrichtung Beispieldresden",
        "überschritten Sie außerhalb geschlossener Ortschaften die zulässige Höchstgeschwindigkeit von 100 km/h um 27 km/h "
        "(nach Abzug der Messtoleranz).", "§ 3 Abs. 3, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 11.3.5 BKat", 150.0, 1, "2026-11-19",
        "BG 2026/08-77412", f"am {de(date(2026, 11, 4))} zugestellt",
    ))  # fmt: skip
    # G2 — Land unknown: served Fri 18.12.2026 → Fri 01.01.2027 Neujahr → Sat, Sun → Mon 04.01.2027.
    cases.append(make(
        "holdout2-fine_bussgeld-G2", "G", O.Q_BG_X, O.Q_GEN2, date(2026, 12, 14), date(2026, 12, 18), "LÜ-RB 207", "19.11.2026 um 08:02 Uhr",
        "Musterlüne, Schulstraße, Fußgängerüberweg vor der Grundschule",
        "ermöglichten Sie einem Fußgänger, der den Fußgängerüberweg erkennbar benutzen wollte, das Überqueren der Fahrbahn nicht.",
        "§ 26 Abs. 1, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 112 BKat", 100.0, 1, "2027-01-04", "ZBS 26-1119-0583",
        f"am {de(date(2026, 12, 18))} zugestellt",
    ))  # fmt: skip
    # H1 — ST: served Sat 24.04.2027 → Sat 08.05.2027 → Mon 10.05.2027.
    cases.append(make(
        "holdout2-fine_bussgeld-H1", "H", O.Q_BG_ST, O.Q_ST, date(2027, 4, 21), date(2027, 4, 24), "HAL-RM 63", "16.03.2027 um 11:37 Uhr",
        "Musterhalle, Merseburger Straße / Ecke Saaleweg (Verkehrskontrolle)",
        "Sie führten das Fahrzeug im Straßenverkehr, obwohl der Termin für die vorgeschriebene Hauptuntersuchung um mehr als "
        "acht Monate überschritten war.", "§ 29 Abs. 1, § 69a Abs. 2 Nr. 14 StVZO; § 24 Abs. 1 StVG; 186.1.4 BKat", 60.0, 1, "2027-05-10",
        "32.21-OWI-2027-03390", f"Zust. {de(date(2027, 4, 24))}",
    ))  # fmt: skip
    # H2 — HB: served Mon 06.09.2027 → Mon 20.09.2027 (a working day in HB).
    cases.append(make(
        "holdout2-fine_bussgeld-H2", "H", O.Q_BG_HB, O.Q_HB, date(2027, 8, 30), date(2027, 9, 6), "HB-JB 1422", "27.07.2027 um 17:51 Uhr",
        "Bremen, Weserstieg, Höhe Haus Nr. 40 (Tempo-30-Zone)",
        "Sie überschritten innerhalb geschlossener Ortschaften die zulässige Höchstgeschwindigkeit von 30 km/h um 18 km/h.",
        "§ 41 Abs. 1 i.V.m. Anlage 2, § 49 StVO; § 24 Abs. 1 StVG; 11.3.3 BKat", 70.0, 0, "2027-09-20", "OWi 27/40-118833",
        f"Zust. {de(date(2027, 9, 6))}",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 12 — year_boundary (old 3-day rule in December 2024, month ends, New Year)
# ==================================================================================================


def year_boundary() -> list[Case]:
    cases: list[Case] = []

    # --- variant G: AO notices with the Belehrung in a box ---------------------------------------------
    def variant_g(case_id: str, org: Org, person: Person, posted: date, subject: str, body: list[Block], refs: list[tuple[str, str]],
                  kind: str, amounts: list[float], hand: str, day_word: str, salutation: str | None = None, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="ao", remedy="einspruch", region=None, title="Einspruchsfrist"
            ),
            hand,
        )
        letter = Letter(
            org=org, recipient=person, info=[("Datum", de(posted)), *refs], subject=subject, salutation=salutation,
            blocks=[
                *body,
                _belehrung_box(
                    f"Den Bescheid können Sie mit einem Einspruch {bei(org.name)} angreifen. Einzulegen ist er innerhalb eines Monats "
                    "seit der Bekanntgabe – schriftlich, elektronisch oder mündlich zur Niederschrift.",
                    f"Bei Versand mit einfachem Brief gilt als Tag der Bekanntgabe der {day_word} Tag nach der Aufgabe zur Post, "
                    "außer der Bescheid geht nicht oder zu einem späteren Zeitpunkt zu.",
                ),
                P("Maschinell erstellt; ohne Unterschrift gültig.", size=7.8),
            ],
            style=STYLES["G"], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="year_boundary", variant="G", letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts, remedy="einspruch",
                        items=[item]),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "Einzulegen ist er innerhalb eines Monats seit der Bekanntgabe",
                         f"gilt als Tag der Bekanntgabe der {day_word} Tag nach der Aufgabe zur Post"],
            notes=notes,
        )  # fmt: skip

    # G1 — posted Fri 06.12.2024 → day 3 = Mon 09.12.2024 (working day) → Thu 09.01.2025.
    # (The 4-day rule would give Tue 10.12. → Fri 10.01.2025.)
    cases.append(variant_g(
        "holdout2-year_boundary-G1", O.Q_FA_X2, O.Q_GEN2, date(2024, 12, 6), "Bescheid für 2023 über Einkommensteuer",
        [P("Die Einkommensteuer für 2023 wird auf 5.118,00 € festgesetzt. Abzüglich der einbehaltenen Lohnsteuer von 5.530,00 € "
           "ergibt sich eine Erstattung von **412,00 €**, die auf das in der Erklärung genannte Konto überwiesen wird.")],
        [("Steuernummer", "33/451/20877")], "tax_assessment", [412.0], "2025-01-09", "dritten",
        notes="Posted before 2025-01-01: 3-day fiction (Art. 97 § 1 Abs. 15 EGAO).",
    ))  # fmt: skip
    # G2 — Familienkasse, Kindergeld (EStG, so the AO applies). Posted Fri 27.08.2027 → day 4 = Tue 31.08.2027 → 31.09. does not
    # exist → Thu 30.09.2027 (§ 188 Abs. 3 BGB).
    cases.append(variant_g(
        "holdout2-year_boundary-G2", O.Q_FK, O.Q_GEN2, date(2027, 8, 27), "Aufhebung der Festsetzung des Kindergeldes für Ihren Sohn Jonas",
        [P("die Festsetzung des Kindergeldes für Ihren Sohn Jonas, geboren am 02.03.2004, heben wir ab September 2027 auf "
           "(§ 70 Abs. 2 EStG). Jonas hat seine Berufsausbildung nach Ihrer Mitteilung am 31.07.2027 abgeschlossen und ist seit "
           "dem 01.08.2027 in Vollzeit beschäftigt."),
         P("Für August 2027 steht Ihnen das Kindergeld noch zu; es wurde bereits ausgezahlt. Eine Rückforderung ergibt sich nicht.")],
        [("Kindergeldnummer", "212FK558104")], "social_insurance", [], "2027-09-30", "vierten",
        salutation="Sehr geehrter Herr Beispielgaard,",
        notes="Kindergeld is a tax refund under the EStG: AO deemed delivery with shift, Einspruch.",
    ))  # fmt: skip
    # G3 — posted Mon 29.12.2025 → day 4 = Fri 02.01.2026 (working day) → Mon 02.02.2026.
    cases.append(variant_g(
        "holdout2-year_boundary-G3", O.Q_FA_X2, O.Q_GEN, date(2025, 12, 29), "Geänderter Bescheid für 2024 über Einkommensteuer",
        [P("Auf Ihren Antrag vom 01.12.2025 ändern wir den Bescheid vom 22.09.2025 nach § 172 Abs. 1 Satz 1 Nr. 2 Buchst. a AO und "
           "berücksichtigen die nachgewiesenen Kosten der Handwerkerleistungen in Ihrer Mietwohnung (§ 35a EStG). Es ergibt sich "
           "eine weitere Erstattung von **186,30 €**.")],
        [("Steuernummer", "33/451/31206")], "tax_assessment", [186.3], "2026-02-02", "vierten",
    ))  # fmt: skip

    # --- variant H: SGB X decisions with the bare date above the subject ------------------------------------
    def variant_h(case_id: str, org: Org, person: Person, posted: date, subject: str, body: list[Block], refs: list[tuple[str, str]],
                  amounts: list[float], hand: str, day_word: str, salutation: str, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="sgbx", remedy="widerspruch", region=None, title="Widerspruchsfrist"
            ),
            hand,
        )
        letter = Letter(
            org=org, recipient=person, info=refs, date_line=date_line(posted), subject=subject, salutation=salutation,
            blocks=[
                *body,
                H("Rechtsbehelfsbelehrung"),
                P(f"Gegen diesen Bescheid können Sie innerhalb eines Monats Widerspruch erheben, schriftlich oder zur Niederschrift "
                  f"{bei(org.name)}, {org.street}, {org.postcode} {org.city}. Die Frist beginnt mit der Bekanntgabe; ein Bescheid, den "
                  f"wir mit der Post schicken, gilt am {day_word} Tag nach der Aufgabe zur Post als bekannt gegeben.", size=8.9),
                Sign("Mit freundlichen Grüßen", ("Im Auftrag",)),
            ],
            style=STYLES["H"], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split=SPLIT, family="year_boundary", variant="H", letter=letter,
            truth=truth(kind="social_insurance", sender=org.name, document_date=posted, references=refs, amounts=amounts,
                        remedy="widerspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "können Sie innerhalb eines Monats Widerspruch erheben",
                         f"gilt am {day_word} Tag nach der Aufgabe zur Post"],
            photo=photo, notes=notes,
        )  # fmt: skip

    # H1 — Versorgungsamt (SGB IX → SGB X). Posted Wed 27.05.2026 → day 4 = Sun 31.05.2026 (no shift) → 31.06. does not exist →
    # Tue 30.06.2026 (§ 188 Abs. 3 BGB).
    cases.append(variant_h(
        "holdout2-year_boundary-H1", O.Q_VA, O.Q_GEN, date(2026, 5, 27), "Feststellung des Grades der Behinderung",
        [P("auf Ihren Antrag vom 19.02.2026 stellen wir bei Ihnen einen Grad der Behinderung (GdB) von **40** fest. Die "
           "Voraussetzungen für ein Merkzeichen liegen nicht vor."),
         P("Berücksichtigt haben wir: eine Funktionsstörung der Wirbelsäule mit Bandscheibenschaden (Einzel-GdB 30) und ein "
           "Bluthochdruckleiden (Einzel-GdB 20). Einen Ausweis stellen wir erst ab einem GdB von 50 aus; mit einem GdB von 30 oder "
           "40 können Sie bei der Agentur für Arbeit die Gleichstellung beantragen.")],
        [("Aktenzeichen", "SB 61-0447/26"), ("Antrag vom", "19.02.2026")], [], "2026-06-30", "vierten",
        "Sehr geehrte Frau Musterkamp,", photo=True,
        notes="The deemed-delivery day is a Sunday (no shift outside tax law) and the 31st: the period ends on 30.06.",
    ))  # fmt: skip
    # H2 — Berufsgenossenschaft (SGB VII → SGB X). Posted Fri 13.12.2024 → day 3 = Mon 16.12.2024 → Thu 16.01.2025.
    # (The 4-day rule would give Tue 17.12. → Fri 17.01.2025.)
    cases.append(variant_h(
        "holdout2-year_boundary-H2", O.Q_BGN, O.Q_GEN2, date(2024, 12, 13), "Ihr Arbeitsunfall vom 26.08.2024 – Ende des Verletztengeldes",
        [P("nach dem Bericht Ihres Durchgangsarztes vom 05.12.2024 sind Sie ab dem 16.12.2024 wieder arbeitsfähig. Den Anspruch auf "
           "Verletztengeld stellen wir deshalb mit Ablauf des 15.12.2024 ein (§ 46 Abs. 3 SGB VII)."),
         P("Für die Zeit vom 01.12. bis 15.12.2024 überweisen wir Ihnen noch **1.064,25 €**. Die Kosten der weiteren ambulanten "
           "Behandlung übernehmen wir weiterhin.")],
        [("Unfallaktenzeichen", "UV 24-08-55193-N")], [1064.25], "2025-01-16", "dritten", "Sehr geehrter Herr Beispielgaard,",
        notes="Posted before 2025-01-01: 3-day fiction.",
    ))  # fmt: skip
    return cases
