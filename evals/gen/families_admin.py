"""Families 1, 2, 3, 7 and 12: administrative acts with remedy periods.

Posting date = letter date unless the letter states a different posting day. Every date below was
chosen to exercise one rule (fiction day on a weekend/holiday, period end on a regional holiday,
old 3-day rule, § 188 Abs. 3 BGB month end, …); ``hand`` is the expected date worked out by hand
from the calendar and is asserted against the computed label.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

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
from .pdf import Block, Box, Envelope, H, Letter, Org, P, Person, Sign, Style, Table
from .text import bei, de, eur, eur_plain, iban_grouped

STYLES = {
    "A": Style(body_pt=9.6, left=25, right=20, leading=1.38, align="J"),
    "B": Style(body_pt=10.1, left=24, right=18, leading=1.32, para_gap=2.6, align="L"),
    "C": Style(body_pt=9.4, left=22, right=20, leading=1.42, para_gap=2.0, align="J"),
    "D": Style(body_pt=9.9, left=25, right=22, leading=1.35, align="L"),
}


def created(d: date | None) -> datetime:
    d = d or date(2026, 1, 1)
    return datetime(d.year, d.month, d.day, 8, 0, tzinfo=UTC)


def check(item: dict, hand: str) -> dict:
    """Assert the computed label equals the date worked out by hand."""
    assert item["expected_due"] == hand, (item["title"], item["expected_due"], hand)
    return item


# ==================================================================================================
# Family 1 — tax_assessment (AO: 4th-day fiction WITH weekend/holiday shift, § 355 AO one month)
# ==================================================================================================


def _tax_table(year: int, zve: int, est: int, lst: int) -> Table:
    diff = est - lst
    einkuenfte = zve + 3_140
    rows = (
        ("Einkünfte aus nichtselbständiger Arbeit", f"{einkuenfte:,}".replace(",", ".")),
        ("Summe der Einkünfte / Gesamtbetrag der Einkünfte", f"{einkuenfte:,}".replace(",", ".")),
        ("Sonderausgaben und außergewöhnliche Belastungen", f"– {3_140:,}".replace(",", ".")),
        ("Zu versteuerndes Einkommen", f"{zve:,}".replace(",", ".")),
        ("Festgesetzt werden: Einkommensteuer", eur_plain(est)),
        ("Solidaritätszuschlag", "0,00"),
        ("Abzüglich einbehaltene Lohnsteuer", f"– {eur_plain(lst)}"),
        ("Nachzahlung" if diff > 0 else "Erstattung", eur_plain(abs(diff))),
    )
    return Table(rows=rows, header=(f"Berechnung für {year}", "EUR"), bold_rows=(3, 7), rule_before=(3, 7))


def tax_assessment() -> list[Case]:
    cases: list[Case] = []

    # --- variant A (dev): classic long form, Rechtsbehelfsbelehrung states the 4th-day fiction -----
    posted = date(2026, 4, 27)  # Mon → day 4 = Fri 01.05. (Tag der Arbeit) → Mon 04.05.
    org, person, year, stnr = O.FA_NW, O.P_NW, 2025, "315/5118/4072"
    zve, est, lst = 41_912, 8_214, 9_102
    item = check(
        objection_item(
            posted=posted,
            scope="ao",
            remedy="einspruch",
            region=org.region,
            title="Einspruchsfrist Einkommensteuerbescheid 2025",
        ),
        "2026-06-05",  # 04.05. + 1 month = Thu 04.06. = Fronleichnam (NW) → Fri 05.06.
    )
    letter = Letter(
        org=org,
        recipient=person,
        info=[
            ("Steuernummer", stnr),
            ("Identifikationsnummer", "58 214 730 915"),
            ("Bearbeitet von", "Frau Kowalski, Zimmer 214"),
            ("Telefon", "0231 5550-2140"),
            ("Datum", de(posted)),
        ],
        subject=f"Bescheid für {year} über Einkommensteuer und Solidaritätszuschlag",
        subject_extra=("Festsetzung – Der Bescheid ist nach § 164 AO nicht vorläufig.",),
        blocks=[
            P(f"Aufgrund Ihrer Einkommensteuererklärung für {year} wird die Steuer wie folgt festgesetzt:"),
            _tax_table(year, zve, est, lst),
            Box(
                (
                    f"Erstattung: {eur(lst - est)}",
                    f"Der Betrag wird auf Ihr Konto {iban_grouped(O.RECIPIENT_IBAN)} überwiesen.",
                )
            ),
            H("Erläuterungen"),
            P(
                "Die Aufwendungen für das häusliche Arbeitszimmer konnten nur in Höhe der Homeoffice-Pauschale (6 € je Tag, höchstens 1.260 €) berücksichtigt werden, da das Arbeitszimmer nicht den Mittelpunkt der gesamten betrieblichen und beruflichen Betätigung bildet."
            ),
            P(
                "Bitte bewahren Sie diesen Bescheid auf. Er ist Grundlage für eventuelle Anträge auf Förderleistungen."
            ),
            H("Rechtsbehelfsbelehrung"),
            P(
                "Der Bescheid kann mit dem Einspruch angefochten werden. Der Einspruch ist bei dem vorbezeichneten Finanzamt "
                "schriftlich einzureichen, diesem elektronisch zu übermitteln oder dort zur Niederschrift zu erklären. Die Frist "
                "für die Einlegung des Einspruchs beträgt **einen Monat**. Sie beginnt mit Ablauf des Tages, an dem Ihnen dieser "
                "Bescheid bekannt gegeben worden ist. Bei Zusendung durch einfachen Brief gilt die Bekanntgabe mit dem vierten "
                "Tag nach Aufgabe zur Post als bewirkt, es sei denn, dass der Bescheid zu einem späteren Zeitpunkt zugegangen ist.",
                size=8.8,
            ),
            Sign("Mit freundlichen Grüßen", ("Ihr Finanzamt Musterstadt-Nord",)),
            P("Dieser Bescheid wurde maschinell erstellt und ist ohne Unterschrift gültig.", size=7.8),
        ],
        style=STYLES["A"],
        created=created(posted),
        running_ref=f"Steuernummer {stnr} · Bescheid vom {de(posted)}",
    )
    cases.append(
        Case(
            id="dev-tax_assessment-A1", split="dev", family="tax_assessment", variant="A", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=posted,
                        references=[("Steuernummer", stnr), ("Identifikationsnummer", "58 214 730 915")],
                        amounts=[lst - est], remedy="einspruch", items=[item]),
            today=today_after(posted, "dev-tax_assessment-A1"), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), "einen Monat", "vierten Tag nach Aufgabe zur Post", stnr],
        )
    )  # fmt: skip

    # --- variant B (dev): short form; separate posting note; Nachzahlung with printed due date ----
    letter_date, posted = date(2026, 3, 26), date(2026, 3, 30)  # posted Mon → day 4 = Karfreitag 03.04.
    org, person, year, stnr = O.FA_X1, O.P_GEN2, 2025, "026 812 40517"
    zve, est, lst = 52_300, 11_405, 10_771
    pay_due = date(2026, 4, 30)  # printed by the Finanzamt (computed from the Bescheid date)
    objection = check(
        objection_item(
            posted=posted,
            scope="ao",
            remedy="einspruch",
            region=None,
            title="Einspruchsfrist Einkommensteuerbescheid 2025",
        ),
        "2026-05-07",  # Fri 03.04. Karfreitag → Sat, Sun, Mon 06.04. Ostermontag → Tue 07.04.; + 1 month = Thu 07.05.
    )
    payment = check(
        fixed_item(due=pay_due, region=None, kind="payment", nature="payment", title="Nachzahlung Einkommensteuer", money=est - lst,
                   rule="Payment date printed in the assessment (Fälligkeit, § 36 Abs. 4 EStG as set by the Finanzamt)."),
        "2026-04-30",
    )  # fmt: skip
    letter = Letter(
        org=org,
        recipient=person,
        info=[
            ("Steuernummer", stnr),
            ("Bescheiddatum", de(letter_date)),
            ("Auskunft", "Herr Brandt · 0561 7040-311"),
        ],
        subject=f"Einkommensteuerbescheid {year}",
        blocks=[
            P(f"Die Einkommensteuer für das Kalenderjahr {year} wird auf **{eur(est)}** festgesetzt."),
            _tax_table(year, zve, est, lst),
            Box(
                (
                    f"Bitte zahlen Sie {eur(est - lst)} bis zum {de(pay_due)}.",
                    f"Empfänger: {org.name} · IBAN {iban_grouped(org.iban)}",
                    f"Verwendungszweck: {stnr} ESt {year}",
                )
            ),
            P("Die Kosten für die doppelte Haushaltsführung wurden wie erklärt berücksichtigt."),
            H("Rechtsbehelf"),
            P(
                f"Einspruch {bei(org.name)} (schriftlich, elektronisch über ELSTER oder zur Niederschrift). "
                "Frist: **ein Monat nach Bekanntgabe** dieses Bescheids.",
                size=9.0,
            ),
            P(f"Hinweis: Dieser Bescheid wurde am {de(posted)} zur Post gegeben.", size=9.0),
            Sign("Mit freundlichen Grüßen", ("Finanzamt Neu-Musterdorf",)),
        ],
        style=STYLES["B"],
        created=created(letter_date),
        running_ref=f"StNr. {stnr}",
    )
    cases.append(
        Case(
            id="dev-tax_assessment-B1", split="dev", family="tax_assessment", variant="B", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=letter_date, references=[("Steuernummer", stnr)],
                        amounts=[est - lst], remedy="einspruch", items=[objection, payment]),
            today=today_after(posted, "dev-tax_assessment-B1"), authority_region=None,
            key_phrases=[de(letter_date), de(posted), "ein Monat nach Bekanntgabe", de(pay_due)],
            notes="Posting date (30.03.) differs from the Bescheid date (26.03.); the payment date was computed by the office from the Bescheid date.",
        )
    )  # fmt: skip

    # --- variant C (test): 'Gegen diesen Bescheid ist der Einspruch gegeben' ---------------------
    def variant_c(case_id: str, org: Org, person: Person, posted: date, year: int, stnr: str, zve: int, est: int, lst: int,
                  hand: str, photo: bool = False) -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted,
                scope="ao",
                remedy="einspruch",
                region=org.region,
                title=f"Einspruchsfrist Einkommensteuerbescheid {year}",
            ),
            hand,
        )
        refund = lst - est
        letter = Letter(
            org=org,
            recipient=person,
            info=[
                ("Datum", de(posted)),
                ("Steuernummer", stnr),
                ("Ansprechpartner", "Veranlagungsteil 3"),
                ("Durchwahl", "-4410"),
            ],
            subject=f"Bescheid für {year} über Einkommensteuer",
            subject_extra=("Der Bescheid ergeht aufgrund Ihrer elektronisch übermittelten Erklärung.",),
            blocks=[
                P("Sehr geehrte Steuerpflichtige, sehr geehrter Steuerpflichtiger,", gap=1.5),
                P(
                    f"für das Jahr {year} ergibt sich folgende Festsetzung. Die einbehaltene Lohnsteuer wird angerechnet."
                ),
                _tax_table(year, zve, est, lst),
                Box(
                    (
                        f"Erstattungsbetrag: {eur(refund)}",
                        "Die Auszahlung erfolgt in den nächsten Tagen auf das bekannte Konto.",
                    )
                ),
                H("Rechtsbehelfsbelehrung"),
                P(
                    "Gegen diesen Bescheid ist der Einspruch gegeben. Der Einspruch ist **innerhalb eines Monats nach Bekanntgabe** "
                    f"dieses Bescheids {bei(org.name)}, {org.street}, {org.postcode} {org.city}, schriftlich oder elektronisch "
                    "einzulegen oder dort zur Niederschrift zu erklären. Ein durch einfachen Brief übermittelter Bescheid gilt am "
                    "vierten Tag nach Aufgabe zur Post als bekannt gegeben, außer wenn er nicht oder zu einem späteren Zeitpunkt "
                    "zugegangen ist.",
                    size=8.8,
                ),
                P("Dieser Bescheid ist maschinell erstellt und ohne Unterschrift gültig.", size=7.8),
            ],
            style=STYLES["C"],
            created=created(posted),
            running_ref=f"Steuernummer {stnr}",
        )
        return Case(
            id=case_id, split="test", family="tax_assessment", variant="C", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=posted, references=[("Steuernummer", stnr)],
                        amounts=[refund], remedy="einspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), "innerhalb eines Monats nach Bekanntgabe", stnr], photo=photo,
        )  # fmt: skip

    # posted Mon 27.10.2025 → day 4 = Fri 31.10. Reformationstag (NI) → Mon 03.11. → Wed 03.12.
    cases.append(
        variant_c(
            "test-tax_assessment-C1",
            O.FA_NI,
            O.P_NI,
            date(2025, 10, 27),
            2024,
            "31/217/40955",
            38_450,
            7_012,
            7_779,
            "2025-12-03",
        )
    )
    # posted Thu 21.05.2026 → day 4 = Mon 25.05. Pfingstmontag → Tue 26.05. → Fri 26.06.
    cases.append(
        variant_c(
            "test-tax_assessment-C2",
            O.FA_X2,
            O.P_GEN,
            date(2026, 5, 21),
            2025,
            "075/104/33871",
            29_870,
            4_402,
            5_195,
            "2026-06-26",
        )
    )

    # --- variant D (test): Bescheid date ≠ posting date (stated), BY, Nachzahlung ------------------
    def variant_d(case_id: str, org: Org, person: Person, letter_date: date, posted: date, year: int, stnr: str, zve: int, est: int,
                  lst: int, hand: str, pay_due: date | None, hand_pay: str | None) -> Case:  # fmt: skip
        objection = check(
            objection_item(
                posted=posted,
                scope="ao",
                remedy="einspruch",
                region=org.region,
                title=f"Einspruchsfrist Einkommensteuerbescheid {year}",
            ),
            hand,
        )
        items = [objection]
        diff = est - lst
        blocks: list[Block] = [
            P("Sehr geehrte Damen und Herren,", gap=1.5),
            P(
                f"die Einkommensteuer, der Solidaritätszuschlag und die Kirchensteuer für {year} werden wie folgt festgesetzt."
            ),
            _tax_table(year, zve, est, lst),
        ]
        if diff > 0:
            assert pay_due is not None and hand_pay is not None
            items.append(check(
                fixed_item(due=pay_due, region=org.region, kind="payment", nature="payment", title=f"Nachzahlung Einkommensteuer {year}",
                           money=float(diff), rule="Payment date printed in the assessment (Fälligkeit as set by the Finanzamt)."),
                hand_pay,
            ))  # fmt: skip
            blocks.append(Box((f"Zu zahlen: {eur(diff)} – fällig am {de(pay_due)}",
                               f"Bitte überweisen Sie auf das Konto des Finanzamts (siehe unten), Verwendungszweck {stnr}.")))  # fmt: skip
        else:
            blocks.append(Box((f"Erstattung: {eur(-diff)}", "Der Betrag wird Ihrem Konto gutgeschrieben.")))
        blocks += [
            P("Ihre Angaben zu den Handwerkerleistungen (§ 35a EStG) wurden übernommen."),
            H("Rechtsbehelfsbelehrung"),
            P(
                "Gegen diesen Bescheid kann binnen eines Monats nach Bekanntgabe Einspruch erhoben werden. Der Einspruch ist "
                f"{bei(org.name)} schriftlich, elektronisch oder zur Niederschrift einzulegen.",
                size=8.8,
            ),
            P(
                f"Hinweis zur Bekanntgabe: Dieser Bescheid wurde am **{de(posted)}** zur Post gegeben. Er gilt am vierten Tag nach "
                "Aufgabe zur Post als bekannt gegeben, es sei denn, er ist nicht oder später zugegangen.",
                size=8.8,
            ),
            Sign("Mit freundlichen Grüßen", (f"{org.name}",)),
        ]
        letter = Letter(
            org=org,
            recipient=person,
            info=[
                ("Steuernummer", stnr),
                ("Datum des Bescheids", de(letter_date)),
                ("Sachbearbeitung", "Herr Obermaier"),
                ("Telefon", "-2214"),
            ],
            subject=f"Bescheid für {year} über Einkommensteuer, Solidaritätszuschlag und Kirchensteuer",
            blocks=blocks,
            style=STYLES["D"],
            created=created(letter_date),
            running_ref=f"Steuernummer {stnr}",
        )
        return Case(
            id=case_id, split="test", family="tax_assessment", variant="D", letter=letter,
            truth=truth(kind="tax_assessment", sender=org.name, document_date=letter_date, references=[("Steuernummer", stnr)],
                        amounts=[float(abs(diff))], remedy="einspruch", items=items),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), de(posted), "binnen eines Monats nach Bekanntgabe", stnr],
            notes="Posting date stated separately from the Bescheid date." if letter_date != posted else "",
        )  # fmt: skip

    # Bescheid 31.12.2025, posted Fri 02.01.2026 → day 4 = Tue 06.01. Heilige Drei Könige (BY) → Wed 07.01.
    # → Sat 07.02. → Mon 09.02. (From the Bescheid date the office computed the Fälligkeit Thu 05.02.)
    cases.append(variant_d("test-tax_assessment-D1", O.FA_BY, O.P_BY, date(2025, 12, 31), date(2026, 1, 2), 2024, "156/274/61023",
                           61_240, 15_130, 13_894, "2026-02-09", date(2026, 2, 5), "2026-02-05"))  # fmt: skip
    # posted Fri 27.02.2026 → day 4 = Tue 03.03. → Fri 03.04. Karfreitag → … → Tue 07.04.
    cases.append(variant_d("test-tax_assessment-D2", O.FA_HE, O.P_HE, date(2026, 2, 27), date(2026, 2, 27), 2025, "007 842 51206",
                           44_100, 8_990, 9_540, "2026-04-07", None, None))  # fmt: skip
    return cases


# ==================================================================================================
# Family 2 — municipal_decision (Land VwVfG: 4th-day fiction WITHOUT shift; Widerspruch/Klage)
# ==================================================================================================


def _rbb_widerspruch(org: Org, wording: str) -> P:
    """One Rechtsbehelfsbelehrung wording per template variant: the test variants (C, D) must not repeat a dev sentence."""
    if wording == "A":
        text = (
            "Gegen diesen Bescheid kann **innerhalb eines Monats nach Bekanntgabe** Widerspruch erhoben werden. Der Widerspruch "
            f"ist schriftlich, in elektronischer Form oder zur Niederschrift {bei(org.name)}, {org.street}, {org.postcode} "
            f"{org.city}, einzulegen."
        )
    elif wording == "B":
        text = (
            "Gegen diesen Bescheid können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch einlegen. Der Widerspruch "
            f"ist bei der oben genannten Behörde ({org.name}) schriftlich oder zur Niederschrift zu erheben. Die Frist ist auch "
            "gewahrt, wenn der Widerspruch innerhalb der Frist bei der Widerspruchsbehörde eingeht."
        )
    elif wording == "C":
        text = (
            "Dieser Bescheid kann mit dem Widerspruch angefochten werden. Der Widerspruch muss **binnen eines Monats, nachdem "
            f"Ihnen der Bescheid bekannt gegeben worden ist,** schriftlich, elektronisch oder zur Niederschrift {bei(org.name)}, "
            f"{org.street}, {org.postcode} {org.city}, erhoben werden."
        )
    else:
        text = (
            "Rechtsbehelf: Widerspruch. Frist: ein Monat ab Bekanntgabe dieses Bescheids. Einzulegen ist er schriftlich oder zur "
            f"Niederschrift {bei(org.name)}; es genügt aber auch, wenn er vor Fristablauf bei der zuständigen Widerspruchsbehörde "
            "eingeht."
        )
    return P(text, size=8.9)


def _rbb_klage(court: str, address: str, wording: str = "A") -> P:
    if wording in ("A", "B"):
        text = (
            "Gegen diesen Bescheid kann **innerhalb eines Monats nach Bekanntgabe** Klage beim Verwaltungsgericht "
            f"{court}, {address}, erhoben werden. Die Klage ist schriftlich oder zu Protokoll des Urkundsbeamten der "
            "Geschäftsstelle zu erheben. Ein Widerspruchsverfahren findet nicht statt."
        )
    else:
        text = (
            f"Gegen diesen Bescheid ist unmittelbar die Klage zum Verwaltungsgericht {court} ({address}) gegeben; ein Vorverfahren "
            "entfällt. Die Klage muss **binnen eines Monats ab Bekanntgabe des Bescheids** schriftlich oder zur Niederschrift des "
            "Urkundsbeamten der Geschäftsstelle erhoben werden."
        )
    return P(text, size=8.9)


def municipal_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, posted: date, remedy: str, subject: str,
             az: str, body: list, hand: str, extra_items: list | None = None, photo: bool = False, court: tuple[str, str] | None = None,
             key: list[str] | None = None, notes: str = "") -> Case:  # fmt: skip
        item = check(
            objection_item(posted=posted, scope="vwvfg", remedy=remedy, region=org.region,
                           title="Klagefrist" if remedy == "klage" else "Widerspruchsfrist",
                           note=("Remedy is Klage: SPEC §21 shows a 'get advice' card instead of a computed date; the legal date is "
                                 "still the label.") if remedy == "klage" else None),
            hand,
        )  # fmt: skip
        style = STYLES[variant]
        rbb = (
            _rbb_klage(*court, wording=variant)
            if remedy == "klage" and court
            else _rbb_widerspruch(org, variant)
        )
        letter = Letter(
            org=org,
            recipient=person,
            info=[("Aktenzeichen", az), ("Auskunft erteilt", "Frau Demir" if variant in "AC" else "Herr Lindqvist"),
                  ("Zimmer", "2.14" if variant in "AC" else "E 07"), ("Datum", de(posted))],
            subject=subject,
            salutation="Sehr geehrte Damen und Herren," if variant in "BD" else f"Sehr geehrte/r {person.name},",
            blocks=[*body, H("Rechtsbehelfsbelehrung"), rbb, Sign("Mit freundlichen Grüßen", ("Im Auftrag", "Demir" if variant in "AC" else "Lindqvist"), signature=True)],
            style=style,
            created=created(posted),
            running_ref=f"Az. {az}",
        )  # fmt: skip
        items = [item, *(extra_items or [])]
        return Case(
            id=case_id, split=split, family="municipal_decision", variant=variant, letter=letter,
            truth=truth(kind="authority_letter", sender=org.name, document_date=posted, references=[("Aktenzeichen", az)],
                        amounts=[], remedy=remedy, items=items),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), az, *(key or [])], photo=photo, notes=notes,
        )  # fmt: skip

    # dev A1 — NW, Klage (no Vorverfahren). Posted Thu 15.05.2025 → Mon 19.05. → Thu 19.06. Fronleichnam (NW) → Fri 20.06.
    posted = date(2025, 5, 15)
    cases.append(make(
        "dev-municipal_decision-A1", "dev", "A", O.STADT_NW, O.P_NW, posted, "klage",
        "Ordnungsverfügung – Anordnung der Anleinpflicht für Ihren Hund „Bruno“", "32.1-HU-2025-0417",
        [
            P("aufgrund des Vorfalls vom 28.04.2025 im Stadtpark Musterstadt, bei dem Ihr Hund einen Passanten ansprang, ordne ich "
              "hiermit gemäß § 14 Abs. 1 OBG NRW an, dass Ihr Hund außerhalb Ihres befriedeten Besitztums ab sofort an einer "
              "höchstens zwei Meter langen Leine zu führen ist."),
            P("Sie wurden mit Schreiben vom 06.05.2025 angehört. Ihre Stellungnahme wurde berücksichtigt; sie rechtfertigt jedoch "
              "keine andere Entscheidung. Für den Fall der Zuwiderhandlung wird ein Zwangsgeld in Höhe von 250,00 € angedroht."),
        ],
        "2025-06-20", court=("Musterstadt", "Justizzentrum, Gerichtsstraße 5, 44135 Musterstadt"), key=["innerhalb eines Monats nach Bekanntgabe"],
    ))  # fmt: skip

    # dev B1 — BY, Widerspruch. Posted Tue 02.12.2025 → Sat 06.12. (no shift) → Tue 06.01.2026 Hl. Drei Könige (BY) → Wed 07.01.
    posted = date(2025, 12, 2)
    cases.append(make(
        "dev-municipal_decision-B1", "dev", "B", O.LRA_BY, O.P_BY, posted, "widerspruch",
        "Ihr Antrag auf Ausnahmegenehmigung zum Befahren des Forstwegs „Am Hochries“ – Ablehnung", "32-1415.3/2025-118",
        [
            P("Ihren Antrag vom 14.10.2025 auf Erteilung einer Ausnahmegenehmigung nach Art. 13 Abs. 3 BayWaldG zum Befahren des "
              "Forstwegs „Am Hochries“ mit einem Kraftfahrzeug lehnen wir ab."),
            P("Gründe: Der Weg ist für den allgemeinen Kraftfahrzeugverkehr gesperrt. Ein besonderes Bedürfnis, das eine Ausnahme "
              "rechtfertigen würde, haben Sie nicht dargelegt; die Zufahrt zu Ihrem Grundstück ist über die Gemeindestraße möglich."),
            P("Kosten werden für diesen Bescheid nicht erhoben."),
        ],
        "2026-01-07", key=["binnen eines Monats nach seiner Bekanntgabe"],
    ))  # fmt: skip

    # test C1 — SH, Widerspruch. Posted Tue 29.09.2026 → Sat 03.10. (holiday; no shift) → Tue 03.11.
    posted = date(2026, 9, 29)
    cases.append(make(
        "test-municipal_decision-C1", "test", "C", O.KREIS_SH, O.P_SH, posted, "widerspruch",
        "Anordnung einer Fahrtenbuchauflage gemäß § 31a StVZO", "FD 3.40-FB-2026-0093",
        [
            P("mit dem auf Sie zugelassenen Fahrzeug (amtliches Kennzeichen BF-MU 412) wurde am 14.07.2026 eine Verkehrsordnungswidrigkeit "
              "begangen. Der verantwortliche Fahrzeugführer konnte nicht festgestellt werden."),
            P("Ich ordne daher an, dass Sie für dieses Fahrzeug für die Dauer von **sechs Monaten** ein Fahrtenbuch zu führen haben. Die "
              "Auflage beginnt mit Eintritt der Bestandskraft dieses Bescheids."),
        ],
        "2026-11-03", photo=True, key=["binnen eines Monats, nachdem Ihnen der Bescheid bekannt gegeben worden ist"],
    ))  # fmt: skip

    # test C2 — HH, Widerspruch. Posted Thu 30.04.2026 → Mon 04.05. → Thu 04.06. = Fronleichnam, which is NOT a holiday in
    # Hamburg → no shift (trap: treating Fronleichnam as nationwide gives Fri 05.06.).
    posted = date(2026, 4, 30)
    cases.append(make(
        "test-municipal_decision-C2", "test", "C", O.BA_HH, O.P_HH, posted, "widerspruch",
        "Ablehnung Ihres Antrags auf Fällgenehmigung (Baumschutzverordnung)", "MR 23/BS-2026-0691",
        [
            P("Ihren Antrag vom 16.03.2026 auf Genehmigung der Fällung einer Rotbuche (Stammumfang 1,65 m) auf dem Grundstück "
              "Eppendorfer Stieg 7 lehne ich ab."),
            P("Der Baum ist nach der Baumschutzverordnung geschützt. Er ist vital und standsicher; die geltend gemachte Verschattung "
              "Ihres Balkons stellt keine unzumutbare Beeinträchtigung dar."),
        ],
        "2026-06-04", key=["binnen eines Monats, nachdem Ihnen der Bescheid bekannt gegeben worden ist"],
        notes="Trap: the period ends on Fronleichnam (04.06.2026), which is not a holiday in Hamburg — no shift.",
    ))  # fmt: skip

    # test D1 — BW, Widerspruch. Posted Mon 02.03.2026 → Fri 06.03. → Mon 06.04. Ostermontag → Tue 07.04.
    posted = date(2026, 3, 2)
    cases.append(make(
        "test-municipal_decision-D1", "test", "D", O.STADT_BW, O.P_BW, posted, "widerspruch",
        "Bauvoranfrage zur Errichtung eines Gartenhauses – Ablehnung", "BRA 63-0214/2026",
        [
            P("Ihre Bauvoranfrage vom 12.01.2026 zur Errichtung eines Gartenhauses mit 42 m³ umbautem Raum im Außenbereich wird "
              "abgelehnt. Das Vorhaben ist nach § 35 Abs. 2 BauGB nicht zulässig, da es öffentliche Belange beeinträchtigt."),
            P("Für diese Entscheidung wird eine Gebühr festgesetzt; hierzu erhalten Sie einen gesonderten Gebührenbescheid."),
        ],
        "2026-04-07", key=["ein Monat ab Bekanntgabe dieses Bescheids"],
    ))  # fmt: skip

    # test D2 — NW, Klage + fixed compliance date. Posted Tue 23.12.2025 → Sat 27.12. (no shift) → Tue 27.01.2026.
    posted = date(2025, 12, 23)
    comply = date(2026, 1, 20)
    task = check(
        fixed_item(due=comply, region="NW", kind="task", nature="other", title="Grünschnitt entfernen",
                   rule="Compliance deadline set by the authority as a calendar date."),
        "2026-01-20",
    )  # fmt: skip
    cases.append(make(
        "test-municipal_decision-D2", "test", "D", O.STADT_NW, O.P_NW, posted, "klage",
        "Ordnungsverfügung – Beseitigung von Grünschnittablagerungen", "32.3-AB-2025-1187",
        [
            P("bei einer Ortsbesichtigung am 09.12.2025 wurde festgestellt, dass auf der städtischen Grünfläche hinter Ihrem Grundstück "
              "Lindenweg 12 Grünschnitt in erheblichem Umfang abgelagert wurde."),
            P(f"Ich fordere Sie gemäß § 14 OBG NRW auf, die Ablagerungen **bis zum {de(comply)}** vollständig zu beseitigen. Für den "
              "Fall, dass Sie dieser Aufforderung nicht fristgerecht nachkommen, drohe ich die Ersatzvornahme an (voraussichtliche "
              "Kosten 480,00 €)."),
        ],
        "2026-01-27", extra_items=[task], court=("Musterstadt", "Justizzentrum, Gerichtsstraße 5, 44135 Musterstadt"),
        key=["binnen eines Monats ab Bekanntgabe des Bescheids", de(comply)],
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 3 — social_decision (SGB X: 4th-day fiction WITHOUT shift; § 84 SGG one month)
# ==================================================================================================


SGBX_KEY = {
    "A": "innerhalb eines Monats nach Bekanntgabe",
    "B": "innerhalb eines Monats nach Bekanntgabe",
    "C": "einen Monat ab Bekanntgabe",
    "D": "binnen eines Monats nach dessen Bekanntgabe",
}


def rbb_sgbx(org: Org, wording: str) -> P:
    """SGB X Rechtsbehelfsbelehrung, one wording per template variant (test variants C, D repeat no dev sentence)."""
    if wording == "A":
        text = (
            "Gegen diesen Bescheid kann **innerhalb eines Monats nach Bekanntgabe** Widerspruch erhoben werden. Der Widerspruch "
            f"ist schriftlich, in elektronischer Form oder zur Niederschrift {bei(org.name)}, {org.street}, {org.postcode} "
            f"{org.city}, einzulegen."
        )
    elif wording == "B":
        text = (
            "Gegen diesen Bescheid kann jede betroffene Person innerhalb eines Monats nach Bekanntgabe Widerspruch erheben. "
            f"Der Widerspruch ist schriftlich oder zur Niederschrift bei der im Briefkopf genannten Stelle ({org.name}) "
            "einzulegen. Die Frist ist auch gewahrt, wenn der Widerspruch bei einer anderen inländischen Behörde eingeht."
        )
    elif wording == "C":
        text = (
            "Sie können gegen diesen Bescheid Widerspruch einlegen. Die Frist dafür beträgt **einen Monat ab Bekanntgabe**; der "
            f"Widerspruch ist schriftlich, elektronisch oder zur Niederschrift {bei(org.name)}, {org.street}, {org.postcode} "
            f"{org.city}, zu erheben."
        )
    else:
        text = (
            "Ein Widerspruch gegen diesen Bescheid ist binnen eines Monats nach dessen Bekanntgabe zulässig. Jede betroffene "
            f"Person kann ihn schriftlich oder zur Niederschrift {bei(org.name)} einlegen; rechtzeitig ist er auch, wenn er vor "
            "Fristablauf bei einer anderen inländischen Behörde oder einem Sozialleistungsträger eingeht."
        )
    return P(text, size=8.7)


def social_decision() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, posted: date, kind: str, subject: str,
             refs: list[tuple[str, str]], body: list, hand: str, amounts: list[float] | None = None, extra_items: list | None = None,
             photo: bool = False) -> Case:  # fmt: skip
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
        rbb = rbb_sgbx(org, variant)
        info = [(label, value) for label, value in refs] + [("Datum", de(posted))]
        letter = Letter(
            org=org,
            recipient=person,
            info=info,
            subject=subject,
            salutation=f"Guten Tag {person.name}," if variant in "AC" else "Sehr geehrte Damen und Herren,",
            blocks=[*body, H("Rechtsbehelfsbelehrung"), rbb, Sign("Mit freundlichen Grüßen", (f"Ihre {org.name}" if org.kind == "health_insurer" else org.name,))],
            style=STYLES[variant],
            created=created(posted),
            running_ref=" · ".join(f"{a} {b}" for a, b in refs[:1]),
        )  # fmt: skip
        return Case(
            id=case_id, split=split, family="social_decision", variant=variant, letter=letter,
            truth=truth(kind=kind, sender=org.name, document_date=posted, references=refs, amounts=amounts or [], remedy="widerspruch",
                        items=[item, *(extra_items or [])]),
            today=today_after(posted, case_id), authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(posted), SGBX_KEY[variant]], photo=photo,
        )  # fmt: skip

    # dev A1 — Krankenkasse, Land unknown. Posted Mon 14.04.2025 → Fri 18.04. Karfreitag (no shift) → Sun 18.05. → Mon 19.05.
    posted = date(2025, 4, 14)
    cases.append(make(
        "dev-social_decision-A1", "dev", "A", O.KK_X, O.P_GEN2, posted, "health_insurance",
        "Ihr Antrag auf Kostenübernahme für orthopädische Einlagen", [("Versichertennummer", "M482915673"), ("Unser Zeichen", "HM-25-044712")],
        [
            P("vielen Dank für Ihren Antrag vom 02.04.2025 und die Verordnung von Dr. Beispiel. Nach Prüfung durch unseren "
              "Fachbereich Hilfsmittel können wir die Kosten für die beantragten sensomotorischen Einlagen leider nicht übernehmen."),
            P("Sensomotorische Einlagen sind nicht im Hilfsmittelverzeichnis gelistet; ihr therapeutischer Nutzen ist nicht nachgewiesen "
              "(§ 33 SGB V). Die Kosten für zwei Paar herkömmliche Einlagen übernehmen wir abzüglich der gesetzlichen Zuzahlung."),
        ],
        "2025-05-19", photo=True,
    ))  # fmt: skip

    # dev B1 — Jobcenter SN. Posted Wed 15.10.2025 → Sun 19.10. (no shift) → Wed 19.11. Buß- und Bettag (SN) → Thu 20.11.
    posted = date(2025, 10, 15)
    submit = date(2025, 11, 5)
    task = check(
        fixed_item(due=submit, region="SN", kind="task", nature="declaration", title="Kontoauszüge einreichen",
                   rule="Submission deadline set by the authority as a calendar date."),
        "2025-11-05",
    )  # fmt: skip
    cases.append(make(
        "dev-social_decision-B1", "dev", "B", O.JC_SN, O.P_SN, posted, "social_insurance",
        "Änderungsbescheid über Leistungen zur Sicherung des Lebensunterhalts (Bürgergeld)",
        [("BG-Nummer", "04701//0081542"), ("Kundennummer", "912D415377")],
        [
            P("die Leistungen für den Zeitraum 01.11.2025 bis 30.04.2026 werden aufgrund der geänderten Heizkostenabschläge neu "
              "berechnet. Der monatliche Gesamtanspruch beträgt ab 01.11.2025 **1.126,40 €**."),
            P(f"Bitte reichen Sie bis zum {de(submit)} die Kontoauszüge der letzten drei Monate ein. Ohne diese Unterlagen können die "
              "Leistungen ab Dezember nicht weiter bewilligt werden (§§ 60, 66 SGB I)."),
        ],
        "2025-11-20", amounts=[1126.40], extra_items=[task],
    ))  # fmt: skip

    # test C1 — Familienkasse (BKGG, Kinderzuschlag), Land unknown. Posted Fri 21.11.2025 → Tue 25.11. → Thu 25.12. → Mon 29.12.
    posted = date(2025, 11, 21)
    cases.append(make(
        "test-social_decision-C1", "test", "C", O.FK_X, O.P_GEN2, posted, "social_insurance",
        "Kinderzuschlag nach § 6a Bundeskindergeldgesetz – Ablehnung", [("Kinderzuschlag-Nr.", "215KZ508814"), ("Ihr Zeichen", "–")],
        [
            P("Ihr Antrag auf Kinderzuschlag vom 06.10.2025 für den Bewilligungszeitraum Oktober 2025 bis März 2026 wird abgelehnt."),
            P("Begründung: Das zu berücksichtigende Einkommen Ihrer Bedarfsgemeinschaft übersteigt die Höchsteinkommensgrenze nach "
              "§ 6a Abs. 1 Nr. 3 BKGG. Die Berechnung finden Sie in der beigefügten Anlage."),
        ],
        "2025-12-29",
    ))  # fmt: skip

    # test C2 — Krankenkasse, Land unknown. Posted Thu 21.05.2026 → Mon 25.05. Pfingstmontag (no shift) → Thu 25.06.
    posted = date(2026, 5, 21)
    cases.append(make(
        "test-social_decision-C2", "test", "C", O.KK_X2, O.P_GEN, posted, "health_insurance",
        "Beitragsbescheid – freiwillige Mitgliedschaft ab 01.06.2026", [("Versichertennummer", "A204518872"), ("Beitragskonto", "7700.1245.08")],
        [
            P("ab dem 01.06.2026 sind Sie bei uns freiwillig versichert. Auf Grundlage Ihrer Einkommensnachweise setzen wir die Beiträge "
              "wie folgt fest: Krankenversicherung 412,65 €, Pflegeversicherung 118,20 € – insgesamt **530,85 € monatlich**."),
            P("Die Beiträge werden jeweils zum 15. des Folgemonats per Lastschrift eingezogen."),
        ],
        "2026-06-25", amounts=[530.85], photo=True,
    ))  # fmt: skip

    # test D1 — Jobcenter HE. Posted Fri 10.04.2026 → Tue 14.04. → Thu 14.05. Christi Himmelfahrt → Fri 15.05.
    posted = date(2026, 4, 10)
    cases.append(make(
        "test-social_decision-D1", "test", "D", O.JC_HE, O.P_HE, posted, "social_insurance",
        "Antrag auf Erstausstattung der Wohnung (§ 24 Abs. 3 SGB II) – Ablehnung", [("BG-Nummer", "06433//0215771"), ("Kundennummer", "605C221908")],
        [
            P("Ihr Antrag vom 03.03.2026 auf Leistungen für die Erstausstattung Ihrer Wohnung wird abgelehnt."),
            P("Eine Erstausstattung liegt nicht vor, da die beantragten Gegenstände (Waschmaschine, Kleiderschrank) als Ersatzbeschaffung "
              "anzusehen sind. Hierfür kann ein Darlehen nach § 24 Abs. 1 SGB II beantragt werden."),
        ],
        "2026-05-15",
    ))  # fmt: skip

    # test D2 — Rentenversicherung, Land unknown. Posted Thu 27.11.2025 → Mon 01.12. → Thu 01.01.2026 Neujahr → Fri 02.01.
    posted = date(2025, 11, 27)
    cases.append(make(
        "test-social_decision-D2", "test", "D", O.DRV_X, O.P_GEN, posted, "social_insurance",
        "Feststellung von Zeiten nach § 149 Abs. 5 SGB VI (Kontenklärung)", [("Versicherungsnummer", "12 150388 B 512"), ("Ihr Schreiben vom", "08.09.2025")],
        [
            P("die in dem beigefügten Versicherungsverlauf enthaltenen Daten, die länger als sechs Kalenderjahre zurückliegen, werden "
              "hiermit verbindlich festgestellt."),
            P("Die Zeit Ihres Studiums vom 01.10.2008 bis 30.09.2011 kann nicht als Anrechnungszeit vorgemerkt werden, da der "
              "Studienabschluss nicht nachgewiesen wurde (§ 58 Abs. 1 Nr. 4 SGB VI)."),
        ],
        "2026-01-02",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# Family 7 — fine_bussgeld (OWiG: Einspruch 2 weeks after Zustellung, § 67 OWiG, § 43 StPO)
# ==================================================================================================


def fine_bussgeld() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, split: str, variant: str, org: Org, person: Person, letter_date: date, served: date, plate: str,
             offence: str, place: str, fine: float, points: int, hand: str, az: str) -> Case:  # fmt: skip
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
        fee = 28.50
        total = fine + fee
        payment = undated_item(
            kind="payment", nature="payment", title="Geldbuße und Kosten zahlen", amount=total,
            spec=spec("relative", anchor="explicit_date", amount=2, unit="weeks", shift=True),
            derivation="Payable within two weeks after the Bußgeldbescheid becomes final (Rechtskraft); the date depends on whether "
                       "an Einspruch is filed, so it is not date-scored.",
        )  # fmt: skip
        head = {
            "A": "Bußgeldbescheid",
            "B": "Bußgeldbescheid – Verkehrsordnungswidrigkeit",
            "C": "Bußgeldbescheid",
            "D": "Bußgeldbescheid gemäß §§ 65, 66 OWiG",
        }[variant]
        # One wording per variant: the test variants (C, D) repeat no sentence of the dev variants (A, B).
        rbb = {
            "A": (
                "Dieser Bußgeldbescheid wird rechtskräftig und vollstreckbar, wenn Sie nicht **innerhalb von zwei Wochen nach "
                "Zustellung** schriftlich oder zur Niederschrift bei der oben bezeichneten Verwaltungsbehörde Einspruch einlegen. Bei "
                "einem Einspruch kann auch eine für Sie nachteiligere Entscheidung getroffen werden."
            ),
            "B": (
                "Sie können gegen diesen Bescheid binnen zwei Wochen nach Zustellung Einspruch einlegen – schriftlich oder zur "
                f"Niederschrift {bei(org.name)}. Legen Sie keinen Einspruch ein, wird der Bescheid rechtskräftig und vollstreckbar."
            ),
            "C": (
                "Gegen diesen Bußgeldbescheid ist der Einspruch zulässig. Er muss **binnen zwei Wochen ab der Zustellung** schriftlich "
                f"oder zur Niederschrift {bei(org.name)} eingelegt werden. Wird kein Einspruch erhoben, ist der Bescheid danach "
                "rechtskräftig; im gerichtlichen Verfahren ist das Gericht nicht an die festgesetzte Geldbuße gebunden."
            ),
            "D": (
                "Rechtsbehelf: Einspruch. Frist: zwei Wochen nach dem Tag der Zustellung. Form: schriftlich oder zur "
                f"Niederschrift {bei(org.name)}. Ohne rechtzeitigen Einspruch kann aus dem Bescheid vollstreckt werden."
            ),
        }[variant]
        pay_text = {
            "A": (
                "Bitte zahlen Sie den Gesamtbetrag spätestens zwei Wochen nach Rechtskraft unter Angabe des Aktenzeichens auf das "
                "unten genannte Konto."
            ),
            "B": (
                "Bitte zahlen Sie den Gesamtbetrag spätestens zwei Wochen nach Rechtskraft unter Angabe des Aktenzeichens auf das "
                "unten genannte Konto."
            ),
            "C": (
                "Der Gesamtbetrag ist zwei Wochen, nachdem der Bescheid rechtskräftig geworden ist, fällig; geben Sie bei der "
                "Überweisung bitte das Aktenzeichen an."
            ),
            "D": (
                "Zahlung: Gesamtbetrag binnen zwei Wochen ab Rechtskraft auf das unten angegebene Konto (Verwendungszweck: "
                "Aktenzeichen)."
            ),
        }[variant]
        key_rbb = {"A": "zwei Wochen nach Zustellung", "B": "zwei Wochen nach Zustellung", "C": "zwei Wochen ab der Zustellung",
                   "D": "zwei Wochen nach dem Tag der Zustellung"}[variant]  # fmt: skip
        letter = Letter(
            org=org,
            recipient=person,
            info=[("Aktenzeichen", az), ("Kennzeichen", plate), ("Datum", de(letter_date)), ("Sachbearbeitung", "Frau Nguyen · -214")],
            subject=head,
            blocks=[
                P(f"Ihnen wird vorgeworfen, am {offence} in {place} als Führer des PKW, amtliches Kennzeichen {plate}, folgende "
                  "Verkehrsordnungswidrigkeit begangen zu haben:"),
                P("Sie überschritten die zulässige Höchstgeschwindigkeit außerhalb geschlossener Ortschaften um 23 km/h. Zulässige "
                  "Geschwindigkeit: 70 km/h. Festgestellte Geschwindigkeit (nach Toleranzabzug): 93 km/h.", indent=5),
                P("§ 41 Abs. 1 i.V.m. Anlage 2, § 49 StVO; § 24 Abs. 1, 3 Nr. 5 StVG; 11.3.4 BKat. Beweismittel: Messung, Lichtbild.", size=8.6, indent=5),
                Table(rows=(("Geldbuße", eur_plain(fine)), ("Gebühr (§ 107 Abs. 1 OWiG)", "25,00"), ("Auslagen (§ 107 Abs. 3 OWiG)", "3,50"),
                            ("Gesamtbetrag", eur_plain(total))), header=("", "EUR"), bold_rows=(3,), rule_before=(3,)),
                P(f"Im Fahreignungsregister wird diese Entscheidung mit {points} Punkt eingetragen. {pay_text}"),
                H("Rechtsbehelfsbelehrung"),
                P(rbb, size=8.8),
                Envelope(sender=org.name, recipient=person, reference=az, note=f"zugestellt am {de(served)}"),
            ],
            style=STYLES[variant],
            created=created(letter_date),
            running_ref=f"Az. {az}",
        )  # fmt: skip
        today = max(today_after(letter_date, case_id), today_after(served, case_id, 0, 2))
        return Case(
            id=case_id, split=split, family="fine_bussgeld", variant=variant, letter=letter,
            truth=truth(kind="fine", sender=org.name, document_date=letter_date, references=[("Aktenzeichen", az), ("Kennzeichen", plate)],
                        amounts=[total, fine], remedy="einspruch", items=[objection], optional_items=[payment]),
            today=today, authority_region=org.region, recipient_region=org.region,
            key_phrases=[de(letter_date), key_rbb, de(served), az],
            notes="Zustellung date is noted on the yellow envelope (page 2), not the Bescheid date.",
        )  # fmt: skip

    # dev A1 — BY: served Thu 17.09.2026 → Thu 01.10.
    cases.append(
        make(
            "dev-fine_bussgeld-A1",
            "dev",
            "A",
            O.BG_BY,
            O.P_BY,
            date(2026, 9, 14),
            date(2026, 9, 17),
            "RO-JM 318",
            "02.09.2026 um 14:37 Uhr",
            "Musterau, Staatsstraße 2089, km 3,2",
            70.0,
            1,
            "2026-10-01",
            "BG-2026-114502",
        )
    )
    # dev B1 — NW: served Sat 19.09.2026 (letterbox) → Sat 03.10. (+ holiday) → Mon 05.10.
    cases.append(
        make(
            "dev-fine_bussgeld-B1",
            "dev",
            "B",
            O.BG_NW,
            O.P_NW,
            date(2026, 9, 15),
            date(2026, 9, 19),
            "MS-MB 77",
            "25.08.2026 um 08:12 Uhr",
            "Beispielsoest, B 229, Höhe Abzweig Musterfeld",
            70.0,
            1,
            "2026-10-05",
            "7.3-OWi-2026-88213",
        )
    )
    # test C1 — NI: served Fri 17.10.2025 → Fri 31.10. Reformationstag (NI) → Mon 03.11.
    cases.append(
        make(
            "test-fine_bussgeld-C1",
            "test",
            "C",
            O.BG_NI,
            O.P_NI,
            date(2025, 10, 13),
            date(2025, 10, 17),
            "BH-AM 204",
            "21.09.2025 um 17:05 Uhr",
            "Heidemuster, L 211, km 5,8",
            70.0,
            1,
            "2025-11-03",
            "32.2-OWi-25-064411",
        )
    )
    # test C2 — BE: served Thu 11.12.2025 → Thu 25.12. → Fri 26.12. → Sat, Sun → Mon 29.12.
    cases.append(
        make(
            "test-fine_bussgeld-C2",
            "test",
            "C",
            O.BG_BE,
            O.P_BE,
            date(2025, 12, 8),
            date(2025, 12, 11),
            "B-NM 2291",
            "12.11.2025 um 22:48 Uhr",
            "Berlin, Musterallee Höhe Hausnummer 120",
            70.0,
            1,
            "2025-12-29",
            "OWi 5114/25-VK",
        )
    )
    # test D1 — BY: served Thu 21.05.2026 → Thu 04.06. Fronleichnam (BY) → Fri 05.06.
    cases.append(
        make(
            "test-fine_bussgeld-D1",
            "test",
            "D",
            O.BG_BY,
            O.P_BY,
            date(2026, 5, 18),
            date(2026, 5, 21),
            "RO-JM 318",
            "30.04.2026 um 06:52 Uhr",
            "Musterau, Kreisstraße RO 5, km 1,1",
            70.0,
            1,
            "2026-06-05",
            "BG-2026-052877",
        )
    )
    # test D2 — Land unknown: served Fri 19.09.2025 → Fri 03.10. Tag der Deutschen Einheit → Mon 06.10.
    cases.append(
        make(
            "test-fine_bussgeld-D2",
            "test",
            "D",
            O.BG_X,
            O.P_GEN2,
            date(2025, 9, 16),
            date(2025, 9, 19),
            "KS-DM 88",
            "27.08.2025 um 11:20 Uhr",
            "Neu-Musterdorf, A 49, km 12,4",
            70.0,
            1,
            "2025-10-06",
            "ZBS-25-7781204",
        )
    )
    return cases


# ==================================================================================================
# Family 12 — year_boundary_and_month_end
# ==================================================================================================


def year_boundary() -> list[Case]:
    cases: list[Case] = []

    # --- variant A (dev): AO Bescheid posted in Dec 2024 → OLD 3-day rule --------------------------
    posted = date(
        2024, 12, 17
    )  # Tue → day 3 = Fri 20.12. → Mon 20.01.2025 (day 4 would be Sat 21.12. → Mon 23.12. → Thu 23.01.)
    org, person, stnr = O.FA_X1, O.P_GEN2, "026 812 40517"
    item = check(
        objection_item(
            posted=posted,
            scope="ao",
            remedy="einspruch",
            region=None,
            title="Einspruchsfrist Änderungsbescheid 2022",
        ),
        "2025-01-20",
    )
    letter = Letter(
        org=org, recipient=person,
        info=[("Steuernummer", stnr), ("Datum", de(posted)), ("Bearbeiter/in", "Frau Yıldız")],
        subject="Geänderter Bescheid für 2022 über Einkommensteuer",
        subject_extra=("Änderung nach § 175 Abs. 1 Satz 1 Nr. 1 AO aufgrund einer geänderten Mitteilung Ihres Arbeitgebers",),
        blocks=[
            P("Der Bescheid vom 14.06.2023 wird geändert. Die Einkommensteuer wird auf 6.918,00 € festgesetzt (bisher 6.918,00 €); "
              "es ergibt sich keine Nachzahlung und keine Erstattung."),
            H("Rechtsbehelfsbelehrung"),
            P("Der Bescheid kann mit dem Einspruch angefochten werden. Die Frist für die Einlegung des Einspruchs beträgt **einen Monat**. "
              "Sie beginnt mit Ablauf des Tages, an dem Ihnen dieser Bescheid bekannt gegeben worden ist. Bei Zusendung durch einfachen "
              "Brief gilt die Bekanntgabe mit dem dritten Tag nach Aufgabe zur Post als bewirkt, es sei denn, dass der Bescheid zu einem "
              "späteren Zeitpunkt zugegangen ist.", size=8.9),
            Sign("Mit freundlichen Grüßen", ("Ihr Finanzamt",)),
        ],
        style=STYLES["A"], created=created(posted), running_ref=f"StNr. {stnr}",
    )  # fmt: skip
    cases.append(Case(
        id="dev-year_boundary-A1", split="dev", family="year_boundary", variant="A", letter=letter,
        truth=truth(kind="tax_assessment", sender=org.name, document_date=posted, references=[("Steuernummer", stnr)], amounts=[6918.0],
                    remedy="einspruch", items=[item]),
        today=today_after(posted, "dev-year_boundary-A1"), authority_region=None,
        key_phrases=[de(posted), "dritten Tag nach Aufgabe zur Post", "einen Monat"],
        notes="Posted before 2025-01-01: 3-day fiction (Art. 97 § 1 Abs. 15 EGAO).",
    ))  # fmt: skip

    # --- variant B (dev): invoice 'innerhalb eines Monats' from 30 January ----------------------------
    inv_date = date(2026, 1, 30)  # + 1 month = 28.02. (§ 188 Abs. 3) = Sat → Mon 02.03.
    org = O.company("Muster Möbelwerkstatt GmbH", "Holzweg 9", "34121", "Neu-Musterdorf", monogram="MM", accent=(90, 60, 30),
                    tagline="Tischlerei · Einbaumöbel · Reparaturen", phone="0561 88 44 20", email="info@muster-moebel.example",
                    hr="Amtsgericht Neu-Musterdorf HRB 4471", vat="USt-IdNr. DE 298 441 207", account="80044120")  # fmt: skip
    total = 1_487.50
    item = check(
        event_period_item(event=inv_date, amount=1, unit="months", region=None, kind="payment", nature="payment",
                          title="Rechnung RE-2026-0142 bezahlen", anchor="document_date", money=total,
                          rule="Payment period of one month after the invoice date; § 193 BGB moves an end on Sat/Sun/holiday.",
                          shift_citation="§ 193 BGB"),
        "2026-03-02",
    )  # fmt: skip
    net = round(total / 1.19, 2)
    letter = Letter(
        org=org, recipient=O.P_GEN2,
        info=[("Rechnungsnummer", "RE-2026-0142"), ("Kundennummer", "K-10877"), ("Rechnungsdatum", de(inv_date)), ("Leistungsdatum", "26.01.2026")],
        subject="Rechnung RE-2026-0142",
        salutation="Sehr geehrter Herr Muster,",
        blocks=[
            P("für die Anfertigung und Montage eines Einbauregals (Eiche geölt, 2,40 m × 2,10 m) berechnen wir Ihnen:"),
            Table(rows=(("Material und Fertigung", eur_plain(net - 380.0)), ("Montage vor Ort, 8 Std.", "380,00"), ("Nettobetrag", eur_plain(net)),
                        ("zzgl. 19 % USt", eur_plain(total - net)), ("Rechnungsbetrag", eur_plain(total))),
                  header=("Position", "EUR"), bold_rows=(4,), rule_before=(2, 4)),
            P("Bitte überweisen Sie den Rechnungsbetrag **innerhalb eines Monats nach Rechnungsdatum** ohne Abzug auf unser Konto "
              "(IBAN siehe unten). Vielen Dank für Ihren Auftrag!"),
            Sign("Mit freundlichen Grüßen", ("Muster Möbelwerkstatt GmbH",)),
        ],
        style=STYLES["B"], created=created(inv_date),
    )  # fmt: skip
    cases.append(Case(
        id="dev-year_boundary-B1", split="dev", family="year_boundary", variant="B", letter=letter,
        truth=truth(kind="invoice", sender=org.name, document_date=inv_date, references=[("Rechnungsnummer", "RE-2026-0142"), ("Kundennummer", "K-10877")],
                    amounts=[total], items=[item]),
        today=today_after(inv_date, "dev-year_boundary-B1"), authority_region=None,
        key_phrases=[de(inv_date), "innerhalb eines Monats nach Rechnungsdatum", "1.487,50"],
    ))  # fmt: skip

    # --- variant C (test): short-form AO notices around the year end / month end --------------------
    def variant_c(case_id: str, org: Org, person: Person, posted: date, subject: str, body: str, ref: tuple[str, str], amount: float,
                  hand: str, day_word: str, extra: list | None = None, optional: list | None = None) -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="ao", remedy="einspruch", region=None, title="Einspruchsfrist"
            ),
            hand,
        )
        letter = Letter(
            org=org, recipient=person,
            info=[(ref[0], ref[1]), ("Datum", de(posted))],
            subject=subject,
            blocks=[
                P(body),
                H("Rechtsbehelfsbelehrung"),
                P("Gegen diesen Bescheid ist der Einspruch zulässig. Er ist **innerhalb eines Monats nach Bekanntgabe** bei der "
                  f"erlassenden Behörde schriftlich oder elektronisch einzulegen. Bei Übermittlung durch die Post gilt der Bescheid am "
                  f"{day_word} Tag nach Aufgabe zur Post als bekannt gegeben, es sei denn, er ist später zugegangen.", size=8.9),
                P("Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift gültig.", size=7.8),
            ],
            style=STYLES["C"], created=created(posted), running_ref=f"{ref[0]} {ref[1]}",
        )  # fmt: skip
        return Case(
            id=case_id, split="test", family="year_boundary", variant="C", letter=letter,
            truth=truth(kind="tax_assessment" if "Finanzamt" in org.name else "tax_letter", sender=org.name, document_date=posted,
                        references=[ref], amounts=[amount], remedy="einspruch", items=[item, *(extra or [])], optional_items=optional),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "innerhalb eines Monats nach Bekanntgabe", f"{day_word} Tag nach Aufgabe zur Post"],
        )  # fmt: skip

    hza = Org(name="Hauptzollamt Musterhafen", kind="authority", street="Zollweg 3", postcode="27570", city="Musterhafen",
              head=("Zollverwaltung · Kraftfahrzeugsteuer",), phone="0471 180-0", email="poststelle.hza-musterhafen@zoll.example",
              bank="Bundesbank Muster", iban=O._iban("29000000", "29001020"), style="band", accent=(20, 75, 60))  # fmt: skip
    # C1 posted Fri 27.12.2024 → day 3 = Mon 30.12.2024 → Thu 30.01.2025 (4-day rule would give Tue 31.12. → Fri 31.01.)
    cases.append(variant_c(
        "test-year_boundary-C1", hza, O.P_GEN, date(2024, 12, 27), "Kraftfahrzeugsteuerbescheid – Neufestsetzung ab 01.01.2025",
        "Für Ihr Fahrzeug mit dem amtlichen Kennzeichen MH-BK 510 wird die Kraftfahrzeugsteuer ab 01.01.2025 auf jährlich 186,00 € "
        "festgesetzt. Die Steuer wird jährlich im Voraus durch Lastschrift eingezogen.",
        ("Steuernummer", "K 4710 0815 22"), 186.0, "2025-01-30", "dritten",
    ))  # fmt: skip
    # C2 posted Mon 22.12.2025 → day 4 = Fri 26.12. 2. Weihnachtstag → Sat, Sun → Mon 29.12. → Thu 29.01.2026
    cases.append(variant_c(
        "test-year_boundary-C2", O.FA_X2, O.P_GEN, date(2025, 12, 22), "Bescheid über Einkommensteuer-Vorauszahlungen ab 2026",
        "Die Vorauszahlungen zur Einkommensteuer werden ab dem Kalenderjahr 2026 auf vierteljährlich 420,00 € festgesetzt "
        "(fällig jeweils am 10.03., 10.06., 10.09. und 10.12.).",
        ("Steuernummer", "075/104/33871"), 420.0, "2026-01-29", "vierten",
        optional=[fixed_item(due=date(2026, 3, 10), region=None, kind="payment", nature="payment", title="Erste Vorauszahlung 2026",
                             money=420.0, rule="First quarterly prepayment date printed in the notice (recurring; optional item).")],
    ))  # fmt: skip
    # C3 posted Mon 27.01.2025 → day 4 = Fri 31.01. → 31.02. does not exist → Fri 28.02.2025 (§ 188 Abs. 3 BGB)
    cases.append(variant_c(
        "test-year_boundary-C3", O.FA_X1, O.P_GEN2, date(2025, 1, 27), "Festsetzung eines Verspätungszuschlags zur Einkommensteuer 2023",
        "Ihre Einkommensteuererklärung für 2023 ist verspätet eingegangen. Nach § 152 AO wird ein Verspätungszuschlag in Höhe von "
        "75,00 € festgesetzt. Bitte zahlen Sie den Betrag innerhalb eines Monats nach Bekanntgabe dieses Bescheids.",
        ("Steuernummer", "026 812 40517"), 75.0, "2025-02-28", "vierten",
        extra=[check(objection_item(posted=date(2025, 1, 27), scope="ao", remedy="einspruch", region=None, kind="payment", nature="payment",
                                    title="Verspätungszuschlag zahlen", money=75.0,
                                    rule="Payment period set by the Finanzamt: one month after Bekanntgabe (§ 108 Abs. 1, 3 AO)."),
                     "2025-02-28")],
    ))  # fmt: skip

    # --- variant D (test): SGB X decisions (no fiction shift) around month / year end ---------------
    def variant_d(case_id: str, org: Org, person: Person, posted: date, subject: str, body: str, refs: list[tuple[str, str]],
                  hand: str, day_word: str, photo: bool = False) -> Case:  # fmt: skip
        item = check(
            objection_item(
                posted=posted, scope="sgbx", remedy="widerspruch", region=None, title="Widerspruchsfrist"
            ),
            hand,
        )
        letter = Letter(
            org=org, recipient=person,
            info=[*refs, ("Datum", de(posted))],
            subject=subject,
            salutation="Sehr geehrte Damen und Herren,",
            blocks=[
                P(body),
                H("Rechtsbehelfsbelehrung"),
                P("Widerspruch gegen diesen Bescheid kann **innerhalb eines Monats nach Bekanntgabe** schriftlich oder zur Niederschrift "
                  f"{bei(org.name)} erhoben werden. Ein mit einfacher Post übermittelter Bescheid gilt am {day_word} Tag nach der "
                  "Aufgabe zur Post als bekannt gegeben.", size=8.9),
                Sign("Mit freundlichen Grüßen", (f"Ihre {org.name}",)),
            ],
            style=STYLES["D"], created=created(posted), running_ref=" ".join(refs[0]),
        )  # fmt: skip
        return Case(
            id=case_id, split="test", family="year_boundary", variant="D", letter=letter,
            truth=truth(kind="health_insurance", sender=org.name, document_date=posted, references=refs, amounts=[], remedy="widerspruch", items=[item]),
            today=today_after(posted, case_id), authority_region=None,
            key_phrases=[de(posted), "innerhalb eines Monats nach Bekanntgabe", f"{day_word} Tag nach der Aufgabe zur Post"], photo=photo,
        )  # fmt: skip

    # D1 posted Tue 27.01.2026 → day 4 = Sat 31.01. (no shift) → 28.02. (§ 188 Abs. 3) = Sat → Mon 02.03.
    cases.append(variant_d(
        "test-year_boundary-D1", O.KK_X, O.P_GEN2, date(2026, 1, 27), "Ablehnung von Krankengeld ab 12.01.2026",
        "Ihr Anspruch auf Krankengeld ruht, weil die Arbeitsunfähigkeit nicht innerhalb einer Woche gemeldet wurde (§ 49 Abs. 1 Nr. 5 "
        "SGB V). Die Bescheinigung ging am 22.01.2026 bei uns ein. Krankengeld zahlen wir daher erst ab dem 22.01.2026.",
        [("Versichertennummer", "M482915673")], "2026-03-02", "vierten", photo=True,
    ))  # fmt: skip
    # D2 posted Fri 20.12.2024 → day 3 = Mon 23.12.2024 → Thu 23.01.2025 (4-day rule would give Tue 24.12. → Fri 24.01.)
    cases.append(variant_d(
        "test-year_boundary-D2", O.KK_X2, O.P_GEN, date(2024, 12, 20), "Zuzahlungsbefreiung 2025 – Ablehnung",
        "Ihren Antrag auf Befreiung von Zuzahlungen für das Jahr 2025 lehnen wir ab. Die Summe Ihrer Zuzahlungen hat die Belastungsgrenze "
        "von 2 % der jährlichen Bruttoeinnahmen (748,20 €) nicht erreicht (§ 62 SGB V).",
        [("Versichertennummer", "A204518872")], "2025-01-23", "dritten",
    ))  # fmt: skip
    return cases
