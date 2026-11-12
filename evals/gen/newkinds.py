"""Newkinds split: seven kinds of letter no earlier split has, four one-page letters of each.

The kinds: a court payment order (Mahnbescheid), an enforcement order (Vollstreckungsbescheid), an employer's notice of
dismissal, a landlord's notice to end a lease, a landlord's request to raise the rent, a late statement of operating
costs, and a contract made away from business premises or at a distance with its withdrawal information.

Every letter is read on 2026-11-24 (``final.FINAL_DAY``) and stays valid through 2026-12-01; it is dated, posted or
handed over between 18 and 21 November 2026, and every scored date lies after 2026-12-01. The days are drawn with
``rng_for("newkinds", case_id)`` and asserted next to the date worked out by hand (``check(item, hand)``); every date of a
truth comes from a function of :mod:`law` written for these kinds from the statute texts in ``evals/law/``. Each scored
item and each optional item names the conventions its date rests on, and for a disputed one the date under the other
reading, worked out with :mod:`law` as well. Senders, recipients, addresses, accounts and file numbers are made up.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from . import law
from .common import Case, dated_item, fixed_item, spec, truth, with_conventions
from .families_admin import check, created
from .law import Derivation, fmt
from .pdf import Block, Box, H, Letter, Org, P, Person, Sign, Style, Table
from .text import de, de_long, de_weekday, eur_plain, iban, rng_for

SPLIT = "newkinds"
#: The day every newkinds letter is read (``final.FINAL_DAY``) and the last day of its window (``final.VALID_UNTIL``).
TODAY = date(2026, 11, 24)
VALID_UNTIL = date(2026, 12, 1)
#: The days a letter is dated, posted or handed over (Wed–Fri, 6 to 4 days before ``TODAY``).
LETTER_DAYS = (date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20))
#: The withdrawal letters may also be handed over on the Saturday.
HANDOVER_DAYS = (*LETTER_DAYS, date(2026, 11, 21))
#: The days a court order may be served after it was issued (no Sunday).
SERVICE_DAYS = (date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 21), date(2026, 11, 23))

STYLES = {
    "1": Style(body_pt=9.6, left=24, right=20, leading=1.32, para_gap=1.8, align="J", info_label_pt=7.1,
               info_value_pt=8.5, subject_pt=10.8),
    "2": Style(body_pt=9.4, left=22, right=22, leading=1.36, para_gap=2.0, align="L", info_label_pt=7.3,
               info_value_pt=8.6, subject_pt=11.0),
    "3": Style(body_pt=9.7, left=25, right=19, leading=1.30, para_gap=1.7, align="J", info_label_pt=7.0,
               info_value_pt=8.4, subject_pt=10.6),
    "4": Style(body_pt=9.5, left=23, right=21, leading=1.34, para_gap=1.9, align="L", info_label_pt=7.4,
               info_value_pt=8.7, subject_pt=11.1),
}  # fmt: skip

#: The conventions every label of a private sender rests on (c06: private-law periods are drawn region-independent)
#: and every label of a court (c04: the court's Land names the holidays), with the receipt rule of the private letters
#: (f03) and the service rule of the court orders (f04).
PRIVATE_IDS = ("c01", "c04", "c06", "f03")
COURT_IDS = ("c01", "c04", "f04")


def drawn(case_id: str, days: tuple[date, ...], expect: date) -> date:
    """The letter's day, drawn among ``days`` with the split's seed for ``case_id``; ``expect`` is the day the hand-worked
    label was computed from."""
    day = rng_for(SPLIT, case_id).choice(days)
    assert day == expect, (case_id, day, expect)
    return day


def court_days(case_id: str, issued: date, served: date) -> tuple[date, date]:
    """A court order's date (Wed–Fri) and its Zustellung (a later day up to the day before ``TODAY``, no Sunday), drawn
    in that order."""
    rng = rng_for(SPLIT, case_id)
    d = rng.choice(LETTER_DAYS)
    s = rng.choice([day for day in SERVICE_DAYS if day > d])
    assert (d, s) == (issued, served), (case_id, d, s)
    return d, s


def tag(item: dict[str, Any], ids: tuple[str, ...], alternatives: list[date] | None = None) -> dict[str, Any]:
    """Tag an item with its conventions (and f02 for a label on 24 or 31 December, which stays there)."""
    due = date.fromisoformat(item["expected_due"])
    year_end = ["f02"] if (due.month, due.day) in ((12, 24), (12, 31)) else []
    return with_conventions(item, [*ids, *year_end], alternatives)


def _case(case_id: str, family: str, letter: Letter, t: dict[str, Any], key: list[str], *, land: str,
          authority_region: str | None = None, photo: bool = False, notes: str = "") -> Case:  # fmt: skip
    return Case(id=case_id, split=SPLIT, family=family, variant=case_id.rsplit("-", 1)[1], letter=letter, truth=t,
                today=TODAY, authority_region=authority_region, recipient_region=land, key_phrases=key, photo=photo,
                notes=notes)  # fmt: skip


def court(name: str, street: str, postcode: str, city: str, land: str, head: tuple[str, ...], *, phone: str,
          accent: tuple[int, int, int], hours: tuple[str, ...]) -> Org:  # fmt: skip
    """A court: its letterhead names the Land (``authority_region``)."""
    return Org(name=name, kind="authority", street=street, postcode=postcode, city=city, region=land, head=head,
               phone=phone, style="authority", accent=accent, hours=hours)  # fmt: skip


def firm(name: str, street: str, postcode: str, city: str, *, monogram: str, accent: tuple[int, int, int], style: str,
         tagline: str = "", phone: str = "", email: str = "", blz: str = "", account: str = "",
         legal: tuple[str, ...] = (), kind: str = "company") -> Org:  # fmt: skip
    """A private sender (company, landlord, employer); an account is printed where ``account`` is given."""
    return Org(name=name, kind=kind, street=street, postcode=postcode, city=city, head=(tagline,) if tagline else (),
               phone=phone, email=email, bank="Beispielsparkasse" if account else "",
               iban=iban("DE", blz + account.zfill(10)) if account else "", style=style, accent=accent,
               monogram=monogram, legal=legal)  # fmt: skip


def money_table(
    rows: list[tuple[str, float]], header: tuple[str, str], total_label: str
) -> tuple[Table, float]:
    total = round(sum(v for _, v in rows), 2)
    body = (*((label, eur_plain(v)) for label, v in rows), (total_label, eur_plain(total)))
    n = len(rows)
    return Table(rows=body, header=header, value_width=30, bold_rows=(n,), rule_before=(n,), size=8.6), total


# --------------------------------------------------------------------------------------------------
# recipients (new; one per letter, in the Land the notes give)
# --------------------------------------------------------------------------------------------------

R_MB1 = Person("Dennis Exempelmann", "Hohlweg 23", "58642", "Musteriserlohn")
R_MB2 = Person("Theresa Beispielhuber", "Lechauer Straße 9", "86899", "Musterlandsberg")
R_MB3 = Person("Okan Demirbeispiel", "Am Deichtor 4", "26721", "Beispielemden")
R_MB4 = Person("Marlene Probstweiler", "Taunusblick 12", "61348", "Musterhomburg")
R_VB1 = Person("Jens Musterhalder", "Hölderlinweg 31", "72622", "Beispielnürtingen")
R_VB2 = Person("Sabine Beispielwitz", "Elbuferstraße 7", "01662", "Mustermeißen")
R_VB3 = Person("Hauke Exempelsen", "Kirchenstieg 2", "25813", "Beispielhusum")
R_VB4 = Person("Daria Kowalbeispiel", "Pankstraße 58", "13357", "Berlin")
R_KA1 = Person("Leon Musterkamp", "Wandsbeker Zollstraße 101", "22041", "Hamburg")
R_KA2 = Person("Ute Beispielberger", "Moselweinstraße 15", "54470", "Musterkastel")
R_KA3 = Person("Kevin Exempelroda", "Saaleblick 6", "07743", "Beispieljena")
R_KA4 = Person("Natalia Musterowa", "Havelstraße 40", "14776", "Musterbrandenburg")
R_MK1 = Person("Ingrid Exempelhaus", "Ruhrallee 77", "45138", "Beispielessen")
R_MK2 = Person("Florian Beispielmoser", "Innstraße 21", "84453", "Mustermühldorf")
R_MK3 = Person("Merle Musterweser", "Vegesacker Heerstraße 140", "28757", "Bremen")
R_MK4 = Person("Steffen Beispielrügen", "Strandstraße 3", "18609", "Musterbinz")
R_ME1 = Person("Aylin Exempeloğlu", "Sonnenallee 210", "12059", "Berlin")
R_ME2 = Person("Gregor Musterfulda", "Am Domplatz 5", "36037", "Beispielfulda")
R_ME3 = Person("Chantal Beispielsaar", "Saaruferweg 18", "66117", "Mustersaarbrücken")
R_ME4 = Person("Bernd Exempelheide", "Heidekamp 9", "29614", "Beispielsoltau")
R_BK1 = Person("Simone Musterbreisgau", "Kaiser-Joseph-Weg 44", "79098", "Beispielfreiburg")
R_BK2 = Person("Ralf Beispielmagd", "Elbstraße 66", "39104", "Mustermagdeburg")
R_BK3 = Person("Wiebke Exempelförde", "Hafenstraße 12", "24937", "Musterflensburg")
R_BK4 = Person("Pascal Musterwartburg", "Lutherstraße 19", "99817", "Beispieleisenach")
R_WR1 = Person("Joachim Beispielalster", "Barmbeker Ring 8", "22305", "Hamburg")
R_WR2 = Person("Esra Exempelrhein", "Rheinuferstraße 27", "47051", "Musterduisburg")
R_WR3 = Person("Veronika Musterchiem", "Seestraße 3", "83209", "Beispielprien")
R_WR4 = Person("Timo Beispielneckar", "Neckarstraße 88", "70190", "Musterstuttgart")


# ==================================================================================================
# 1 — Mahnbescheid (§ 692 Abs. 1 Nr. 3 ZPO: pay or object within two weeks of the Zustellung)
# ==================================================================================================

MB_RULE = (
    "Mahnbescheid: the debtor is asked to pay or to say whether and how far the claim is contested (Widerspruch) within "
    "two weeks of the Zustellung (§ 692 Abs. 1 Nr. 3 ZPO); a later Widerspruch counts while no Vollstreckungsbescheid "
    "has been issued (§ 694 Abs. 1 ZPO), which gives no fixed date."
)


def mahnbescheid() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, land: str, org: Org, person: Person, issued: date, served: date, az: str,
             claimant: str, rows: list[tuple[str, float]], service_note: str, blocks: list[Block], key: str, hand: str,
             *, photo: bool = False) -> Case:  # fmt: skip
        table, total = money_table(rows, ("Geltend gemachter Anspruch", "EUR"), "Gesamtbetrag")

        def calc(region: str | None) -> tuple[date, Derivation]:
            why = Derivation()
            return law.mahnbescheid_objection_end(served, region, why), why

        item = check(
            dated_item(kind="deadline", nature="objection", title="Mahnbescheid: zahlen oder Widerspruch erheben", calc=calc,
                       region=land, spec=spec("relative", anchor="explicit_date", amount=2, unit="weeks", anchor_date=served,
                                              shift=True), rule=MB_RULE, amount=total),
            hand,
        )  # fmt: skip
        item = tag(item, (*COURT_IDS, "f05"))
        letter = Letter(org=org, recipient=person, info=[("Geschäftsnummer", az), ("Erlassen am", de(issued))],
                        subject="Mahnbescheid", subject_extra=(f"Antragsteller: {claimant}",),
                        blocks=[Box((service_note,), fill=(250, 244, 214), bold_first=False), table, *blocks,
                                Sign("", ("Rechtspflegerin / Rechtspfleger", "maschinell erstellt, ohne Unterschrift gültig"))],
                        style=STYLES[case_id[-1]], created=created(issued))  # fmt: skip
        t = truth(kind="dunning", sender=org.name, document_date=issued, references=[("Geschäftsnummer", az)],
                  amounts=[total], remedy="widerspruch", items=[item])  # fmt: skip
        return _case(case_id, "mahnbescheid", letter, t, [de(issued), de(served), key, eur_plain(total)], land=land,
                     authority_region=land, photo=photo,
                     notes=f"Mahnbescheid issued {issued}, served {served}; two weeks → {hand}.")  # fmt: skip

    # 1 (NW): issued Fri 20.11.2026, served Mon 23.11.2026 → Mon 07.12.2026, a working day.
    c1 = "newkinds-mahnbescheid-1"
    issued, served = court_days(c1, date(2026, 11, 20), date(2026, 11, 23))
    org = court("Amtsgericht Exempelbrück", "Gerichtsplatz 2", "58089", "Exempelbrück", "NW",
                ("Land Nordrhein-Westfalen", "Zentrales Mahngericht"), phone="02331 555 90 00", accent=(30, 70, 120),
                hours=("Mo–Fr 8:30–12:00 Uhr",))  # fmt: skip
    cases.append(make(
        c1, "NW", org, R_MB1, issued, served, "26-5531904-0-7", "Beispielfunk Mobilnetz GmbH, Funkturmweg 1, 40221 Musterdorf",
        [("Hauptforderung: Mobilfunkentgelte Juni bis August 2026", 214.37), ("Zinsen bis zum Erlass", 4.12),
         ("Kosten dieses Verfahrens (Gericht)", 36.00), ("Auslagen des Antragstellers", 18.00)],
        f"Zugestellt durch Einlegen in den Briefkasten am {de(served)} (Vermerk der Zustellerin auf dem Umschlag).",
        [P("Die Antragstellerin behauptet, Ihnen stehe der oben genannte Betrag zu. Ob das zutrifft, hat das Gericht nicht "
           "untersucht."),
         P("Ihnen bleiben **zwei Wochen ab der Zustellung**. In dieser Zeit sollen Sie den Gesamtbetrag nebst weiteren Zinsen "
           "an die Antragstellerin zahlen, wenn Sie die Forderung für berechtigt halten, oder dem Gericht auf dem beigefügten "
           "Vordruck mitteilen, ob und wie weit Sie Widerspruch erheben."),
         P("Geht innerhalb dieser Zeit weder Zahlung noch Widerspruch ein, kann die Antragstellerin einen "
           "Vollstreckungsbescheid beantragen und mit ihm die Zwangsvollstreckung gegen Sie betreiben."),
         P("Nach einem Widerspruch gibt das Gericht die Sache an das Amtsgericht Musterdorf ab; dieses prüft seine "
           "Zuständigkeit selbst.", size=8.6)],
        "zwei Wochen ab der Zustellung", "2026-12-07",
    ))  # fmt: skip

    # 2 (BY, photo): issued Wed 18.11.2026, served Fri 20.11.2026 → Fri 04.12.2026.
    c2 = "newkinds-mahnbescheid-2"
    issued, served = court_days(c2, date(2026, 11, 18), date(2026, 11, 20))
    org = court("Amtsgericht Beispielcoburg", "Ketschendorfer Straße 5", "96450", "Beispielcoburg", "BY",
                ("Freistaat Bayern · Justiz", "Mahngericht für Bayern"), phone="09561 555 30 30", accent=(20, 90, 150),
                hours=("Servicezeiten Mo–Do 8–15 Uhr, Fr 8–12 Uhr",))  # fmt: skip
    cases.append(make(
        c2, "BY", org, R_MB2, issued, served, "26-2208415-1-2", "Exempel Fitnesswelt GmbH & Co. KG, vertreten durch "
        "Rechtsanwältin Dr. Muster, Isarstraße 3, 80469 Beispielmünchen",
        [("Hauptforderung: Mitgliedsbeiträge März bis Juli 2026", 249.50), ("Rücklastschriftgebühren", 9.00),
         ("Gerichtskosten", 36.00), ("Vergütung der Prozessbevollmächtigten", 70.20)],
        f"Zustellungsvermerk: übergeben am {de(served)} an den Empfänger persönlich.",
        [P("Dieser Bescheid ergeht allein auf Grund der Angaben der Antragstellerin. Das Gericht hat ihren Anspruch nicht "
           "geprüft."),
         P("**Was Sie jetzt tun müssen:** Halten Sie die Forderung für berechtigt, begleichen Sie die Summe samt laufender "
           "Zinsen binnen zwei Wochen seit Zustellung dieses Bescheids direkt bei der Antragstellerin. Bestreiten Sie sie "
           "ganz oder zum Teil, teilen Sie dem Mahngericht innerhalb derselben Frist mit, dass Sie Widerspruch erheben; "
           "verwenden Sie dafür möglichst den beigelegten Vordruck."),
         P("Ohne Zahlung und ohne Widerspruch kann ein Vollstreckungsbescheid erlassen werden. Aus ihm darf die "
           "Antragstellerin vollstrecken, etwa durch eine Kontopfändung."),
         P("Im Fall eines Widerspruchs geht das Verfahren an das Amtsgericht Beispielmünchen, das über seine Zuständigkeit "
           "selbst befindet.", size=8.6)],
        "binnen zwei Wochen seit Zustellung dieses Bescheids", "2026-12-04", photo=True,
    ))  # fmt: skip

    # 3 (NI): issued Thu 19.11.2026, served Fri 20.11.2026 → Fri 04.12.2026.
    c3 = "newkinds-mahnbescheid-3"
    issued, served = court_days(c3, date(2026, 11, 19), date(2026, 11, 20))
    org = court("Amtsgericht Musteruelzen", "Lüneburger Tor 11", "29525", "Musteruelzen", "NI",
                ("Niedersachsen", "Zentrales Mahngericht"), phone="0581 555 74 00", accent=(150, 30, 40),
                hours=("telefonisch Mo–Fr 9–13 Uhr",))  # fmt: skip
    cases.append(make(
        c3, "NI", org, R_MB3, issued, served, "26-7710623-0-5", "Beispielhaus Versandhandel AG, Katalogring 8, 33602 Exempelfeld",
        [("Kaufpreis Bestellung vom 14.04.2026", 389.90), ("Mahnkosten", 7.50), ("Zinsen", 11.64),
         ("Gerichtskosten des Mahnverfahrens", 36.00)],
        f"Vom Postzusteller vermerktes Zustelldatum: {de_weekday(served)}.",
        [P("Die Antragstellerin verlangt von Ihnen den Betrag aus der Tabelle. Hinweis: Das Gericht hat nicht nachgeprüft, "
           "ob ihr der Anspruch wirklich zusteht."),
         P("Begleichen Sie die Schuld, soweit Sie sie anerkennen, oder erheben Sie Widerspruch, soweit Sie sie bestreiten. "
           "Für das eine wie das andere bleiben Ihnen vierzehn Tage, beginnend mit dem Tag, an dem Ihnen dieser Bescheid zugestellt wurde."),
         P("Lassen Sie die Frist verstreichen, ohne zu reagieren, darf auf Antrag ein Vollstreckungsbescheid ergehen; dann "
           "drohen Vollstreckungsmaßnahmen."),
         P("Den Widerspruch richten Sie schriftlich an dieses Gericht. Danach wird die Sache an das Amtsgericht Exempelfeld "
           "abgegeben, das seine Zuständigkeit eigenständig prüft.", size=8.6)],
        "bleiben Ihnen vierzehn Tage, beginnend mit dem Tag, an dem Ihnen dieser Bescheid zugestellt wurde", "2026-12-04",
    ))  # fmt: skip

    # 4 (HE): issued Thu 19.11.2026, served Fri 20.11.2026 → Fri 04.12.2026.
    c4 = "newkinds-mahnbescheid-4"
    issued, served = court_days(c4, date(2026, 11, 19), date(2026, 11, 20))
    org = court("Amtsgericht Beispielhünfeld", "Schlossgasse 6", "36088", "Beispielhünfeld", "HE",
                ("Land Hessen · Ordentliche Gerichtsbarkeit", "Zentrales Mahngericht Hessen"), phone="06652 555 18 80",
                accent=(110, 30, 60), hours=("Sprechzeiten Di und Do 9–12 Uhr",))  # fmt: skip
    cases.append(make(
        c4, "HE", org, R_MB4, issued, served, "26-0934877-0-1", "Zahnarztpraxis Dr. Exempelzahn, Kurhausstraße 2, 61348 "
        "Musterhomburg",
        [("Honorar privatzahnärztliche Behandlung (Rechnung vom 02.06.2026)", 612.40), ("Zinsen seit Verzug", 15.28),
         ("Kosten des Verfahrens", 39.00)],
        f"Zugestellt am {de(served)} – Einwurf in den Hausbriefkasten (Vermerk auf dem Briefumschlag).",
        [P("Das Gericht weist darauf hin, dass es nicht untersucht hat, ob der Anspruch der Antragstellerin besteht."),
         P("Sie werden aufgefordert, innerhalb von zwei Wochen nach der Zustellung entweder den Gesamtbetrag samt weiterer "
           "Zinsen an die Antragstellerin zu überweisen oder dem Gericht zu erklären, ob und in welcher Höhe Sie "
           "widersprechen."),
         P("Liegt nach Fristablauf kein Widerspruch vor, kann gegen Sie ein Vollstreckungsbescheid erlassen werden, aus dem "
           "die Antragstellerin die Zwangsvollstreckung betreiben darf."),
         P("Nach einem Widerspruch geht das Verfahren an das Amtsgericht Musterhomburg, das selbst entscheidet, ob es "
           "zuständig ist.", size=8.6)],
        "innerhalb von zwei Wochen nach der Zustellung", "2026-12-04",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# 2 — Vollstreckungsbescheid (§ 700 Abs. 1, § 339 Abs. 1 ZPO: Einspruch within two weeks, a Notfrist)
# ==================================================================================================

VB_RULE = (
    "Vollstreckungsbescheid: it stands for a default judgment declared provisionally enforceable (§ 700 Abs. 1 ZPO); "
    "the Einspruch period is two weeks from its Zustellung, a Notfrist (§ 339 Abs. 1 ZPO)."
)


def vollstreckungsbescheid() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, land: str, org: Org, person: Person, issued: date, served: date, az: str, claimant: str,
             earlier: str, rows: list[tuple[str, float]], service_note: str, blocks: list[Block], key: str, hand: str) -> Case:  # fmt: skip
        table, total = money_table(rows, ("Tituliert", "EUR"), "Gesamtbetrag")

        def calc(region: str | None) -> tuple[date, Derivation]:
            why = Derivation()
            return law.vollstreckungsbescheid_objection_end(served, region, why), why

        item = check(
            dated_item(kind="deadline", nature="objection", title="Einspruch gegen den Vollstreckungsbescheid", calc=calc,
                       region=land, spec=spec("relative", anchor="explicit_date", amount=2, unit="weeks", anchor_date=served,
                                              shift=True), rule=VB_RULE),
            hand,
        )  # fmt: skip
        item = tag(item, COURT_IDS)
        letter = Letter(org=org, recipient=person, info=[("Geschäftsnummer", az), ("Datum", de(issued))],
                        subject="Vollstreckungsbescheid", subject_extra=(f"in der Mahnsache {claimant} gegen Sie",),
                        blocks=[Box((service_note,), fill=(250, 244, 214), bold_first=False), P(earlier), table, *blocks,
                                Sign("", ("Rechtspfleger/in", "Maschinell gefertigt, daher ohne Unterschrift."))],
                        style=STYLES[case_id[-1]], created=created(issued))  # fmt: skip
        t = truth(kind="authority_letter", sender=org.name, document_date=issued, references=[("Geschäftsnummer", az)],
                  amounts=[total], remedy="einspruch", items=[item])  # fmt: skip
        return _case(case_id, "vollstreckungsbescheid", letter, t, [de(issued), de(served), key, eur_plain(total)], land=land,
                     authority_region=land,
                     notes=f"Vollstreckungsbescheid issued {issued}, served {served}; two weeks → {hand}.")  # fmt: skip

    # 1 (BW): issued Wed 18.11.2026, served Fri 20.11.2026 → Fri 04.12.2026.
    c1 = "newkinds-vollstreckungsbescheid-1"
    issued, served = court_days(c1, date(2026, 11, 18), date(2026, 11, 20))
    org = court("Amtsgericht Musterstetten", "Justizstraße 14", "70173", "Musterstetten", "BW",
                ("Baden-Württemberg", "Zentrales Mahngericht"), phone="0711 555 21 40", accent=(160, 120, 20),
                hours=("Mo–Fr 9–12 Uhr",))  # fmt: skip
    cases.append(make(
        c1, "BW", org, R_VB1, issued, served, "26-8812045-0-3", "Exempelstrom Neckar GmbH",
        "Gegen den Ihnen am 28.10.2026 zugestellten Mahnbescheid haben Sie keinen Widerspruch erhoben. Auf Antrag der "
        "Antragstellerin wird deshalb der folgende Betrag für vollstreckbar erklärt:",
        [("Hauptforderung: Stromlieferung, Schlussrechnung", 486.19), ("Zinsen bis zum Erlass", 12.07),
         ("Kosten des Mahnbescheids", 36.00), ("Kosten dieses Bescheids", 5.20)],
        f"Zugestellt am {de(served)} durch Einlegen in den Briefkasten (Vermerk auf dem Umschlag).",
        [P("Der Vollstreckungsbescheid hat die Wirkung eines vorläufig vollstreckbaren Versäumnisurteils. Die Antragstellerin "
           "kann daraus sofort vollstrecken."),
         H("Belehrung über den Einspruch", size=9.4),
         P("Gegen diesen Vollstreckungsbescheid steht Ihnen der Einspruch zu. Er muss binnen einer Notfrist von zwei Wochen ab "
           "der Zustellung bei diesem Gericht eingehen; eine Verlängerung ist ausgeschlossen. Ist die Frist verstrichen, kann "
           "der Bescheid nicht mehr angefochten werden.", size=8.7)],
        "Notfrist von zwei Wochen ab der Zustellung", "2026-12-04",
    ))  # fmt: skip

    # 2 (SN): issued Thu 19.11.2026, served Mon 23.11.2026 → Mon 07.12.2026.
    c2 = "newkinds-vollstreckungsbescheid-2"
    issued, served = court_days(c2, date(2026, 11, 19), date(2026, 11, 23))
    org = court("Amtsgericht Beispielaue", "Zwickauer Platz 1", "08280", "Beispielaue", "SN",
                ("Freistaat Sachsen", "Zentrales Mahngericht Sachsen"), phone="03771 555 12 00", accent=(30, 110, 60),
                hours=("Mo, Mi, Do 9–14 Uhr",))  # fmt: skip
    cases.append(make(
        c2, "SN", org, R_VB2, issued, served, "26-3301772-1-9", "Musterwohnen Elbtal eG",
        "Der Mahnbescheid vom 16.10.2026 ist Ihnen zugestellt worden; ein Widerspruch ist beim Gericht nicht eingegangen. "
        "Antragsgemäß ergeht daher gegen Sie folgender Vollstreckungsbescheid:",
        [("Hauptforderung: Nutzungsentgelt Garage Mai bis Oktober 2026", 270.00), ("Zinsen", 6.30),
         ("Verfahrenskosten", 41.20)],
        f"Zustellvermerk: am {de(served)} in den Briefkasten eingelegt.",
        [P("Aus diesem Bescheid kann die Antragstellerin die Zwangsvollstreckung betreiben, auch bevor er rechtskräftig ist."),
         P("**Rechtsbehelf:** Sie können sich mit einem Einspruch wehren. Er ist schriftlich beim "
           "Amtsgericht Beispielaue einzulegen, und zwar innerhalb von zwei Wochen; die Frist beginnt mit der Zustellung und "
           "ist eine Notfrist.", size=8.7),
         P("Nach einem Einspruch wird der Rechtsstreit an das Amtsgericht Mustermeißen abgegeben.", size=8.7)],
        "innerhalb von zwei Wochen; die Frist beginnt mit der Zustellung", "2026-12-07",
    ))  # fmt: skip

    # 3 (SH): issued Fri 20.11.2026, served Mon 23.11.2026 → Mon 07.12.2026.
    c3 = "newkinds-vollstreckungsbescheid-3"
    issued, served = court_days(c3, date(2026, 11, 20), date(2026, 11, 23))
    org = court("Amtsgericht Exempelsund", "Am Gerichtshof 9", "24837", "Exempelsund", "SH",
                ("Land Schleswig-Holstein", "Mahngericht"), phone="04621 555 66 10", accent=(0, 80, 140),
                hours=("Mo–Fr 8–12 Uhr",))  # fmt: skip
    cases.append(make(
        c3, "SH", org, R_VB3, issued, served, "26-6604318-0-0", "Beispielauto Leasing GmbH",
        "Auf den Mahnbescheid vom 21.10.2026, zugestellt am 26.10.2026, haben Sie nicht widersprochen. Das Gericht erklärt "
        "die Forderung der Antragstellerin deshalb für vollstreckbar:",
        [("Hauptforderung: Leasingraten August und September 2026", 598.00), ("Zinsen", 9.41),
         ("Kosten des Mahnverfahrens", 36.00), ("Anwaltskosten", 105.30)],
        f"Durch die Post zugestellt am {de_weekday(served)}.",
        [P("Dieser Bescheid steht einem für vorläufig vollstreckbar erklärten Versäumnisurteil gleich."),
         H("Einspruch", size=9.4),
         P("Wer den Bescheid nicht hinnehmen will, legt dagegen Einspruch ein. Dafür steht ein Zeitraum von zwei Wochen ab "
           "Zustellung zur Verfügung, der sich nicht verlängern lässt. Adressat des Einspruchs ist das Amtsgericht "
           "Exempelsund.", size=8.7)],
        "Zeitraum von zwei Wochen ab Zustellung", "2026-12-07",
    ))  # fmt: skip

    # 4 (BE): issued Wed 18.11.2026, served Mon 23.11.2026 → Mon 07.12.2026.
    c4 = "newkinds-vollstreckungsbescheid-4"
    issued, served = court_days(c4, date(2026, 11, 18), date(2026, 11, 23))
    org = court("Amtsgericht Musterwedding", "Kriminalgerichtsweg 3", "13353", "Berlin", "BE",
                ("Land Berlin", "Zentrales Mahngericht Berlin-Brandenburg"), phone="030 555 80 20", accent=(140, 20, 30),
                hours=("Servicetelefon Mo–Fr 9–13 Uhr",))  # fmt: skip
    cases.append(make(
        c4, "BE", org, R_VB4, issued, served, "26-1129650-1-4", "Exempel Online-Akademie UG",
        "Sie haben gegen den Mahnbescheid vom 12.10.2026 innerhalb der gesetzten Frist keinen Widerspruch eingelegt. Es "
        "ergeht daher dieser Vollstreckungsbescheid über:",
        [("Hauptforderung: Kursgebühren Fernlehrgang", 720.00), ("Zinsen", 17.95), ("Gerichtskosten", 39.00),
         ("Auslagen", 12.50)],
        f"Zugestellt am {de(served)} (Datum laut Vermerk des Zustellers).",
        [P("Die Antragstellerin darf aus diesem Titel vollstrecken lassen."),
         P("**Belehrung:** Ein Einspruch gegen den Bescheid ist möglich. Dafür haben Sie ab der Zustellung zwei Wochen "
           "Zeit (Notfrist). Der Einspruch ist schriftlich an das Amtsgericht Musterwedding zu senden; ohne ihn wird der "
           "Bescheid rechtskräftig.", size=8.7)],
        "Dafür haben Sie ab der Zustellung zwei Wochen Zeit", "2026-12-07",
    ))  # fmt: skip
    return cases


# ==================================================================================================
# 3 — Kündigung eines Arbeitsverhältnisses (§ 622 BGB end; § 4 KSchG three weeks to sue)
# ==================================================================================================

KA_RULE = (
    "Written dismissal received on the day it was handed over (§ 130 Abs. 1 S. 1 BGB); an action against it must be "
    "brought within three weeks of receipt, whatever the ground (§ 4 S. 1 KSchG), or the dismissal counts as valid "
    "(§ 7 KSchG)."
)


def kuendigung_arbeit() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, land: str, org: Org, person: Person, salutation: str, handed: date, years: int, probation: bool,
             end_hand: str, refs: list[tuple[str, str]], handover: str, body: Callable[[str], list[Block]], key: str,
             hand: str, signer: tuple[str, ...], *, photo: bool = False) -> Case:  # fmt: skip
        end_why = Derivation()
        end = law.employer_notice_end(handed, years=years, probation=probation, why=end_why)
        assert end.isoformat() == end_hand, (case_id, end)

        def calc(region: str | None) -> tuple[date, Derivation]:
            why = Derivation()
            return law.dismissal_claim_end(handed, region, why), why

        item = check(
            dated_item(kind="deadline", nature="objection", title="Klage gegen die Kündigung beim Arbeitsgericht", calc=calc,
                       region=None, spec=spec("relative", anchor="explicit_date", amount=3, unit="weeks", anchor_date=handed,
                                              shift=False), rule=KA_RULE,
                       note=f"The employment ends {end.isoformat()} ({end_why.text()}); that day is not scored."),
            hand,
        )  # fmt: skip
        item = tag(item, (*PRIVATE_IDS, "f06"))
        letter = Letter(org=org, recipient=person, info=[*refs, ("Datum", de(handed))],
                        subject="Kündigung Ihres Arbeitsverhältnisses", salutation=salutation,
                        subject_extra=(handover,), blocks=[*body(de(end)),
                                Sign("Mit freundlichen Grüßen", signer, signature=True)],
                        style=STYLES[case_id[-1]], created=created(handed))  # fmt: skip
        t = truth(kind="employment", sender=org.name, document_date=handed, references=refs, amounts=[], remedy="klage",
                  items=[item])  # fmt: skip
        return _case(case_id, "kuendigung_arbeit", letter, t, [de(handed), de(end), key], land=land, photo=photo,
                     notes=f"Dismissal handed over {handed}; employment ends {end_hand}; § 4 KSchG → {hand}.")  # fmt: skip

    # 1 (HH): probation, handed over Thu 19.11.2026; § 622 Abs. 3 two weeks → Thu 03.12.2026; three weeks → Thu 10.12.2026.
    c1 = "newkinds-kuendigung_arbeit-1"
    handed = drawn(c1, LETTER_DAYS, date(2026, 11, 19))
    org = firm("Exempel Logistik Hafenrand GmbH", "Kaistraße 41", "20457", "Hamburg", monogram="EL", accent=(0, 70, 110),
               style="band", tagline="Kontraktlogistik · Lagerhaltung", phone="040 555 47 10",
               email="personal@exempel-logistik.example", legal=("AG Hamburg HRB 555 471",))  # fmt: skip
    cases.append(make(
        c1, "HH", org, R_KA1, "Sehr geehrter Herr Musterkamp,", handed, 0, True, "2026-12-03",
        [("Personalnummer", "EL-40917")],
        f"Persönlich übergeben am {de(handed)} um 9:40 Uhr im Personalbüro, Halle 2. Empfang quittiert.",
        lambda end: [
            P("Sie sind seit dem 01.08.2026 bei uns als Lagerfachkraft beschäftigt; nach Ihrem Arbeitsvertrag gilt eine "
              "Probezeit von sechs Monaten."),
            P(f"Innerhalb der Probezeit kündigen wir das Arbeitsverhältnis mit der vereinbarten Frist von zwei Wochen, also "
              f"zum **{end}**. Der Betriebsrat ist vor dieser Kündigung angehört worden."),
            P("Bitte melden Sie sich unverzüglich bei der Agentur für Arbeit arbeitsuchend; sonst kann es Nachteile beim "
              "Arbeitslosengeld geben. Ihre Arbeitskleidung und den Transponder geben Sie bitte am letzten Arbeitstag ab."),
            P("Wenn Sie die Kündigung für unwirksam halten, können Sie das nur mit einer Klage vor dem Arbeitsgericht "
              "geltend machen. Sie muss binnen drei Wochen nach Zugang dieses Schreibens erhoben werden.", size=8.8),
        ],
        "binnen drei Wochen nach Zugang dieses Schreibens", "2026-12-10",
        ("Carola Beispielhafen", "Leitung Personal"),
    ))  # fmt: skip

    # 2 (RP, photo): 6 years, handed over Wed 18.11.2026; § 622 Abs. 2 Nr. 2 → 31.01.2027; three weeks → Wed 09.12.2026.
    c2 = "newkinds-kuendigung_arbeit-2"
    handed = drawn(c2, LETTER_DAYS, date(2026, 11, 18))
    org = firm("Weingut Musterreben KG", "Kelterweg 3", "54470", "Musterkastel", monogram="MR", accent=(110, 20, 50),
               style="logo", tagline="Weinbau seit 1898", phone="06531 555 20 80",
               email="buero@weingut-musterreben.example", legal=("AG Musterwittlich HRA 2208",))  # fmt: skip
    cases.append(make(
        c2, "RP", org, R_KA2, "Sehr geehrte Frau Beispielberger,", handed, 6, False, "2027-01-31",
        [("Arbeitsvertrag", "AV-2020-07")],
        f"Übergeben am {de(handed)} im Büro des Weinguts in Anwesenheit von Herrn Exempelwinzer (Zeuge).",
        lambda end: [
            P("nach mehr als sechs Jahren Zusammenarbeit fällt uns dieser Schritt schwer. Weil wir den Flaschenverkauf ab "
              "dem kommenden Jahr vollständig an einen Großhändler abgeben, entfällt Ihr Arbeitsplatz in der "
              "Verkaufsstelle."),
            P(f"Wir kündigen deshalb das Arbeitsverhältnis ordentlich unter Einhaltung der gesetzlichen Frist zum "
              f"**{end}**. Ihr restlicher Urlaub wird bis dahin gewährt."),
            P("Um Nachteile beim Arbeitslosengeld zu vermeiden, müssen Sie sich sofort bei der Agentur für Arbeit "
              "arbeitsuchend melden."),
            P("Zu Ihrer Information: Eine Klage gegen diese Kündigung wäre innerhalb von drei Wochen nach Erhalt des "
              "Schreibens beim Arbeitsgericht einzureichen.", size=8.8),
        ],
        "innerhalb von drei Wochen nach Erhalt des Schreibens", "2026-12-09",
        ("Hubert Musterreben", "Inhaber"), photo=True,
    ))  # fmt: skip

    # 3 (TH): 9 years, handed over Wed 18.11.2026; § 622 Abs. 2 Nr. 3 → 28.02.2027; three weeks → Wed 09.12.2026.
    c3 = "newkinds-kuendigung_arbeit-3"
    handed = drawn(c3, LETTER_DAYS, date(2026, 11, 18))
    org = firm("Beispieloptik Saaletal GmbH", "Linsenstraße 12", "07745", "Beispieljena", monogram="BO", accent=(40, 40, 90),
               style="minimal", tagline="Präzisionsoptik für Medizin und Forschung", phone="03641 555 33 90",
               email="hr@beispieloptik.example", legal=("AG Musterjena HRB 503 390",))  # fmt: skip
    cases.append(make(
        c3, "TH", org, R_KA3, "Sehr geehrter Herr Exempelroda,", handed, 9, False, "2027-02-28",
        [("Personal-Nr.", "BO-1173"), ("Kostenstelle", "Fertigung 3")],
        f"Dieses Schreiben wurde Ihnen am {de(handed)} am Arbeitsplatz persönlich ausgehändigt.",
        lambda end: [
            P("wegen der Verlagerung der Linsenfertigung an unseren Standort in Musterilmenau fällt die Arbeit in Ihrer "
              "Abteilung ab Frühjahr weg. Eine freie Stelle, die wir Ihnen anbieten könnten, gibt es nicht."),
            P(f"Hiermit kündigen wir Ihr seit dem 01.03.2017 bestehendes Arbeitsverhältnis fristgerecht zum **{end}**. Der "
              "Betriebsrat hat der Kündigung nicht widersprochen; seine Stellungnahme liegt bei."),
            P("Bitte denken Sie daran, sich umgehend bei der Agentur für Arbeit arbeitsuchend zu melden. Ihr Arbeitszeugnis "
              "erhalten Sie mit der letzten Abrechnung."),
            P("Möchten Sie die Wirksamkeit der Kündigung gerichtlich überprüfen lassen, müssen Sie spätestens drei Wochen "
              "nach ihrem Zugang Klage beim Arbeitsgericht erheben.", size=8.8),
        ],
        "spätestens drei Wochen nach ihrem Zugang Klage", "2026-12-09",
        ("i. V. Doreen Musterilm", "Personalleiterin"),
    ))  # fmt: skip

    # 4 (BB): 1 year 7 months, handed over Thu 19.11.2026; § 622 Abs. 1 (4 weeks → Thu 17.12.) → 31.12.2026; → Thu 10.12.2026.
    c4 = "newkinds-kuendigung_arbeit-4"
    handed = drawn(c4, LETTER_DAYS, date(2026, 11, 19))
    org = firm("Bäckerei Exempelkorn GmbH", "Mühlendamm 7", "14770", "Musterbrandenburg", monogram="EK", accent=(150, 90, 20),
               style="logo", tagline="Handwerksbäckerei mit sechs Filialen", phone="03381 555 61 61",
               email="verwaltung@exempelkorn.example", legal=("AG Musterpotsdam HRB 26 616",))  # fmt: skip
    cases.append(make(
        c4, "BB", org, R_KA4, "Sehr geehrte Frau Musterowa,", handed, 1, False, "2026-12-31",
        [("Mitarbeiterin", "Filiale Havelstraße")],
        f"Übergabe durch die Filialleitung am {de_long(handed)}; die Empfangsbestätigung ist unterschrieben.",
        lambda end: [
            P("wir schließen die Filiale in der Havelstraße zum Jahresende. Ihr Arbeitsverhältnis, das am 01.04.2025 "
              "begonnen hat, kündigen wir deshalb ordentlich und fristgemäß zum **" + end + "**."),
            P("Ihren Resturlaub nehmen Sie bitte bis zu diesem Tag. Die Schlüssel der Filiale geben Sie an Ihrem letzten "
              "Arbeitstag bei der Filialleitung ab."),
            P("Sie sind verpflichtet, sich unverzüglich bei der Agentur für Arbeit arbeitsuchend zu melden."),
            P("Eine Klage gegen die Kündigung ist beim Arbeitsgericht Musterbrandenburg möglich; dafür gilt eine Frist von "
              "drei Wochen ab dem Zugang dieser Kündigung.", size=8.8),
        ],
        "Frist von drei Wochen ab dem Zugang dieser Kündigung", "2026-12-10",
        ("Matthias Exempelkorn", "Geschäftsführer"),
    ))  # fmt: skip
    return cases


# ==================================================================================================
# 4 — Kündigung eines Mietverhältnisses (§ 573c Abs. 1 BGB end; § 574b Abs. 2 BGB Widerspruch two months before)
# ==================================================================================================

MK_RULE = (
    "Landlord's notice received by messenger on the stated day (§ 130 Abs. 1 S. 1 BGB); the lease ends as § 573c Abs. 1 "
    "BGB gives; the tenant's Widerspruch (§ 574 BGB) must reach the landlord in Textform two months before that end "
    "(§ 574b Abs. 1, 2 BGB)."
)


def kuendigung_miete() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, land: str, org: Org, person: Person, salutation: str, received: date, years: int, end_hand: str,
             refs: list[tuple[str, str]], handover: str, body: Callable[[str, str], list[Block]], key: list[str], hand: str,
             alternative: list[date], signer: tuple[str, ...], *, photo: bool = False) -> Case:  # fmt: skip
        ends = {s: law.landlord_notice_end(received, years=years, region=None, why=Derivation(), saturday_counts=s)
                for s in (True, False)}  # fmt: skip
        assert len(set(ends.values())) == 1, (case_id, ends)  # both readings of "Werktag" give the same end
        end = ends[True]
        assert end.isoformat() == end_hand, (case_id, end)

        def calc(region: str | None) -> tuple[date, Derivation]:
            why = Derivation()
            lease_end = law.landlord_notice_end(received, years=years, region=region, why=why)
            return law.tenant_objection_last_day(lease_end, why), why

        item = check(
            dated_item(kind="deadline", nature="objection", title="Widerspruch gegen die Kündigung (Härte)", calc=calc,
                       region=None, spec=spec("relative", anchor="explicit_date", amount=2, unit="months", anchor_date=received,
                                              shift=False), rule=MK_RULE),
            hand,
        )  # fmt: skip
        other = law.tenant_objection_last_day(end, Derivation(), same_day_number=True)
        assert sorted(d for d in {other} if d.isoformat() != hand) == alternative, (case_id, other)
        item = tag(item, (*PRIVATE_IDS, "f07"), alternative)
        letter = Letter(org=org, recipient=person, info=[*refs, ("Datum", de(received))],
                        subject="Kündigung des Mietverhältnisses", salutation=salutation,
                        subject_extra=(handover,), blocks=[*body(de(end), hand),
                                Sign("Mit freundlichen Grüßen", signer, signature=True)],
                        style=STYLES[case_id[-1]], created=created(received))  # fmt: skip
        t = truth(kind="rent_lease", sender=org.name, document_date=received, references=refs, amounts=[], remedy="widerspruch",
                  items=[item])  # fmt: skip
        return _case(case_id, "kuendigung_miete", letter, t, [de(received), de(end), *key], land=land, photo=photo,
                     notes=f"Notice received {received}; lease ends {end_hand}; Widerspruch by {hand}.")  # fmt: skip

    def objection_hint(last: str | None, size: float = 8.7) -> P:
        when = (
            f"spätestens am {last}" if last else "spätestens zwei Monate vor dem Ende des Mietverhältnisses"
        )
        return P(f"**Hinweis nach §§ 574 bis 574b BGB:** Wäre der Auszug für Sie oder Ihre Familie eine Härte, die auch unter "
                 f"Berücksichtigung meiner Interessen nicht zu rechtfertigen ist, können Sie der Kündigung widersprechen und "
                 f"die Fortsetzung des Mietverhältnisses verlangen. Der Widerspruch bedarf der Textform und muss mir {when} "
                 "zugehen.", size=size)  # fmt: skip

    # 1 (NW, photo): messenger Thu 19.11.2026; 3 years → 28.02.2027; two months before → Thu 31.12.2026 (other: Mon 28.12.2026).
    c1 = "newkinds-kuendigung_miete-1"
    received = drawn(c1, LETTER_DAYS, date(2026, 11, 19))
    org = firm("Gisela Beispielruhr", "Moltkeplatz 6", "45138", "Beispielessen", monogram="GB", accent=(70, 70, 70),
               style="minimal", phone="0201 555 80 14", kind="landlord")  # fmt: skip
    cases.append(make(
        c1, "NW", org, R_MK1, "Sehr geehrte Frau Exempelhaus,", received, 3, "2027-02-28",
        [("Mietobjekt", "Ruhrallee 77, 2. OG rechts")],
        f"Per Boten: am {de_weekday(received)} gegen 10 Uhr in Ihren Briefkasten eingeworfen (Botin: Lena Beispielruhr).",
        lambda end, last: [
            P("hiermit kündige ich das Mietverhältnis über die Wohnung Ruhrallee 77, 2. Obergeschoss rechts, ordentlich zum "
              f"**{end}**."),
            P("Ich benötige die Wohnung für meine Tochter Lena, die im Frühjahr ihre Stelle am Klinikum in Beispielessen antritt "
              "und mit ihrem Partner eine Wohnung in der Nähe sucht. Eine andere freie Wohnung habe ich nicht."),
            objection_hint(de(date.fromisoformat(last))),
            P("Für die Übergabe der Wohnung werde ich mich rechtzeitig mit Ihnen abstimmen."),
        ],
        ["Wohnung Ruhrallee 77"], "2026-12-31", [date(2026, 12, 28)], ("Gisela Beispielruhr",), photo=True,
    ))  # fmt: skip

    # 2 (BY): messenger Thu 19.11.2026; 6 years (+3 months) → 31.05.2027; → Wed 31.03.2027 (both readings).
    c2 = "newkinds-kuendigung_miete-2"
    received = drawn(c2, LETTER_DAYS, date(2026, 11, 19))
    org = firm("Kanzlei Exempelrain & Kollegen", "Stadtplatz 14", "84453", "Mustermühldorf", monogram="ER", accent=(20, 50, 90),
               style="band", tagline="Rechtsanwälte · Miet- und Wohnungseigentumsrecht", phone="08631 555 40 40",
               email="kanzlei@exempelrain.example")  # fmt: skip
    cases.append(make(
        c2, "BY", org, R_MK2, "Sehr geehrter Herr Beispielmoser,", received, 6, "2027-05-31",
        [("Unser Zeichen", "ER-M-26/0418"), ("Mandanten", "Eheleute Mustertaler")],
        f"Zustellung durch Kanzleiboten: Einwurf in den Briefkasten am {de(received)}, 9:15 Uhr.",
        lambda end, last: [
            P("wir vertreten Ihre Vermieter, die Eheleute Mustertaler; eine Vollmacht liegt im Original bei."),
            P(f"Namens und in Vollmacht unserer Mandanten kündigen wir das Mietverhältnis über die Wohnung Innstraße 21, "
              f"Erdgeschoss, ordentlich zum **{end}**. Da Ihnen die Wohnung im Juli 2020 übergeben wurde, verlängert sich die "
              "Kündigungsfrist um drei Monate."),
            P("Herr Mustertaler ist nach einem Unfall auf eine ebenerdige Wohnung angewiesen; Ihre Erdgeschosswohnung ist die "
              "einzige dieser Art im Haus unserer Mandanten."),
            objection_hint(None),
        ],
        ["Kündigungsfrist um drei Monate"], "2027-03-31", [], ("Dr. Konstanze Exempelrain", "Rechtsanwältin"),
    ))  # fmt: skip

    # 3 (HB): messenger Fri 20.11.2026; 11 years (+6 months) → 31.08.2027; → Wed 30.06.2027 (both readings).
    c3 = "newkinds-kuendigung_miete-3"
    received = drawn(c3, LETTER_DAYS, date(2026, 11, 20))
    org = firm("Hinrich Musterlesum", "Burgdammer Weg 2", "28717", "Bremen", monogram="HM", accent=(0, 90, 70), style="minimal",
               phone="0421 555 39 12", kind="landlord")  # fmt: skip
    cases.append(make(
        c3, "HB", org, R_MK3, "Liebe Frau Musterweser,", received, 11, "2027-08-31",
        [("Wohnung", "Vegesacker Heerstraße 140, DG")],
        f"Von mir selbst am {de(received)} vormittags in Ihren Briefkasten gesteckt.",
        lambda end, last: [
            P("nach elf Jahren, in denen Sie meine Mieterin waren, muss ich Ihnen leider schreiben, dass ich die Dachwohnung "
              "selbst brauche. Meine Frau und ich können die Treppen in unserem jetzigen Haus nicht mehr bewältigen und "
              "wollen in die Wohnung mit Aufzug ziehen."),
            P(f"Ich kündige deshalb den Mietvertrag ordentlich. Wegen der langen Mietdauer endet er erst am **{end}**."),
            objection_hint(de(date.fromisoformat(last))),
            P("Wenn ich Ihnen bei der Suche nach einer neuen Wohnung helfen kann, sagen Sie es mir bitte."),
        ],
        ["endet er erst am"], "2027-06-30", [], ("Hinrich Musterlesum",),
    ))  # fmt: skip

    # 4 (MV): messenger Wed 18.11.2026; 2 years → 28.02.2027; → Thu 31.12.2026 (other: Mon 28.12.2026).
    c4 = "newkinds-kuendigung_miete-4"
    received = drawn(c4, LETTER_DAYS, date(2026, 11, 18))
    org = firm("Hausverwaltung Beispielbodden GmbH", "Hafenpromenade 9", "18609", "Musterbinz", monogram="HB",
               accent=(0, 100, 150), style="logo", tagline="Verwaltung von Miet- und Ferienwohnungen", phone="038393 555 70",
               email="mieter@beispielbodden.example", legal=("AG Musterstralsund HRB 7 707",))  # fmt: skip
    cases.append(make(
        c4, "MV", org, R_MK4, "Sehr geehrter Herr Beispielrügen,", received, 2, "2027-02-28",
        [("Objekt", "Strandstraße 3, Whg. 4"), ("Eigentümer", "Herr Olaf Exempeldüne")],
        f"Durch unseren Mitarbeiter am {de(received)} um 11 Uhr in den Briefkasten der Strandstraße 3 eingelegt.",
        lambda end, last: [
            P("im Auftrag und mit beigefügter Vollmacht des Eigentümers, Herrn Olaf Exempeldüne, kündigen wir das "
              f"Mietverhältnis über die Wohnung Nr. 4 in der Strandstraße 3 fristgerecht zum **{end}**."),
            P("Herr Exempeldüne zieht nach dem Ende seiner Tätigkeit im Ausland mit seiner Familie zurück nach Musterbinz und "
              "wird die Wohnung selbst bewohnen."),
            objection_hint(None),
            P("Einen Termin zur Wohnungsabnahme schlagen wir Ihnen im Februar vor."),
        ],
        ["Strandstraße 3"], "2026-12-31", [date(2026, 12, 28)], ("Hausverwaltung Beispielbodden GmbH", "Kerstin Mustermole"),
    ))  # fmt: skip
    return cases


# ==================================================================================================
# 5 — Mieterhöhungsverlangen (§§ 558, 558a, 558b BGB)
# ==================================================================================================

ME_RULE = (
    "Rent increase up to the local comparative rent, received by messenger on the stated day (§ 130 Abs. 1 S. 1 BGB): the "
    "tenant may consent until the end of the second calendar month after receipt (§ 558b Abs. 2 S. 1 BGB); a consented "
    "increase is owed from the start of the third calendar month (§ 558b Abs. 1 BGB)."
)


def mieterhoehung() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, land: str, org: Org, person: Person, salutation: str, received: date, old: float, new: float,
             refs: list[tuple[str, str]], handover: str, body: Callable[[str], list[Block]], key: list[str], hand: str,
             signer: tuple[str, ...], *, consent_line: bool = True) -> Case:  # fmt: skip
        effective = law.rent_increase_effective(received, Derivation())
        assert effective == date(2027, 2, 1), (case_id, effective)

        def calc(region: str | None) -> tuple[date, Derivation]:
            why = Derivation()
            return law.rent_increase_consent_end(received, region, why), why

        item = check(
            dated_item(kind="deadline", nature="declaration", title="Zustimmung zur Mieterhöhung", calc=calc, region=None,
                       spec=spec("relative", anchor="explicit_date", amount=2, unit="months", anchor_date=received, shift=True),
                       rule=ME_RULE, note=f"The new rent would be owed from {effective.isoformat()} (§ 558b Abs. 1 BGB)."),
            hand,
        )  # fmt: skip
        unmoved = law.rent_increase_consent_end(received, None, Derivation(), shift=False)
        item = tag(item, (*PRIVATE_IDS, "f08"), [unmoved])
        table = Table(rows=(("Nettokaltmiete bisher", eur_plain(old)), ("Nettokaltmiete neu", eur_plain(new)),
                            ("Erhöhung", eur_plain(round(new - old, 2)))), header=("Monatlich", "EUR"), value_width=30,
                      bold_rows=(1,), size=8.6)  # fmt: skip
        tail: list[Block] = (
            [P("Bitte senden Sie mir die beigefügte Zustimmungserklärung unterschrieben zurück.")]
            if consent_line
            else []
        )
        letter = Letter(org=org, recipient=person, info=[*refs, ("Datum", de(received))],
                        subject="Mieterhöhungsverlangen nach § 558 BGB", salutation=salutation,
                        subject_extra=(handover,), blocks=[*body(de(effective)), table, *tail,
                                Sign("Mit freundlichen Grüßen", signer)],
                        style=STYLES[case_id[-1]], created=created(received))  # fmt: skip
        t = truth(kind="rent_lease", sender=org.name, document_date=received, references=refs, amounts=[old, new],
                  items=[item])  # fmt: skip
        return _case(case_id, "mieterhoehung", letter, t, [de(received), eur_plain(new), *key], land=land,
                     notes=f"Request received {received}; consent by {hand} (unmoved: {unmoved}); new rent from {effective}.")  # fmt: skip

    # Every request below reaches the tenant in November 2026: the second calendar month after it ends Sun 31.01.2027,
    # § 193 BGB → Mon 01.02.2027 (f08's other reading: Sun 31.01.2027); the new rent is owed from Mon 01.02.2027.

    # 1 (BE): messenger Thu 19.11.2026.
    c1 = "newkinds-mieterhoehung-1"
    received = drawn(c1, LETTER_DAYS, date(2026, 11, 19))
    org = firm("Exempelkiez Wohnbau GmbH", "Hermannplatz 10", "10967", "Berlin", monogram="EW", accent=(180, 70, 0), style="band",
               tagline="Mietwohnungen in Neukölln und Kreuzberg", phone="030 555 62 00", email="mieten@exempelkiez.example",
               legal=("AG Charlottenburg HRB 555 620",))  # fmt: skip
    cases.append(make(
        c1, "BE", org, R_ME1, "Sehr geehrte Frau Exempeloğlu,", received, 642.00, 718.00,
        [("Mieternummer", "EW-3304-12"), ("Wohnung", "Sonnenallee 210, 3. OG")],
        f"Durch Boten zugestellt: Einwurf in Ihren Briefkasten am {de(received)} vormittags.",
        lambda eff: [
            P("Ihre Nettokaltmiete für die 68 m² große Wohnung beträgt seit dem 01.06.2024 unverändert 642,00 €, also 9,44 € "
              "je Quadratmeter. Nach dem Berliner Mietspiegel 2026 liegt die ortsübliche Vergleichsmiete für Ihre Wohnung "
              "(Baujahr 1958, mittlere Wohnlage, Sondermerkmal Aufzug) bei 10,71 € je Quadratmeter; die Spanne reicht bis "
              "11,92 €."),
            P(f"Wir bitten Sie daher, einer Erhöhung der Nettokaltmiete auf 718,00 € (10,56 € je m²) mit Wirkung ab dem {eff} "
              "zuzustimmen. Die Kappungsgrenze von 15 % in drei Jahren ist eingehalten. Die Vorauszahlungen für Betriebs- "
              "und Heizkosten bleiben gleich."),
            P("Für Ihre Entscheidung haben Sie bis zum Ablauf des zweiten Kalendermonats nach dem Zugang dieses Schreibens "
              "Zeit."),
        ],
        ["bis zum Ablauf des zweiten Kalendermonats nach dem Zugang dieses Schreibens"], "2027-02-01",
        ("Exempelkiez Wohnbau GmbH", "Mietenmanagement"),
    ))  # fmt: skip

    # 2 (HE): messenger Wed 18.11.2026.
    c2 = "newkinds-mieterhoehung-2"
    received = drawn(c2, LETTER_DAYS, date(2026, 11, 18))
    org = firm("Roswitha Musterrhön", "Pfandhausstraße 3", "36037", "Beispielfulda", monogram="RM", accent=(90, 60, 30),
               style="minimal", phone="0661 555 28 77", kind="landlord")  # fmt: skip
    cases.append(make(
        c2, "HE", org, R_ME2, "Sehr geehrter Herr Musterfulda,", received, 480.00, 545.00,
        [("Mietwohnung", "Am Domplatz 5, 1. OG")],
        f"Diesen Brief hat mein Sohn am {de_long(received)} um 10:30 Uhr bei Ihnen eingeworfen.",
        lambda eff: [
            P("seit Ihrem Einzug im März 2023 zahlen Sie für die Wohnung eine Nettokaltmiete von 480,00 €; eine Erhöhung hat "
              "es seitdem nicht gegeben."),
            P("Zur Begründung meines Verlangens nenne ich Ihnen drei vergleichbare Wohnungen in der Fuldaer Innenstadt, für die "
              "zwischen 7,80 € und 8,40 € je m² gezahlt werden: Pfandhausstraße 3 (2. OG, 62 m², 505,00 €), Löherstraße 11 "
              "(1. OG, 70 m², 560,00 €) und Bonifatiusplatz 2 (EG, 66 m², 528,00 €)."),
            P(f"Ich bitte Sie, der Erhöhung Ihrer Nettokaltmiete von 480,00 € auf 545,00 € (7,90 € je m² bei 69 m²) ab dem "
              f"{eff} zuzustimmen. Damit bleibt die Erhöhung unter 15 %."),
        ],
        ["drei vergleichbare Wohnungen"], "2027-02-01", ("Roswitha Musterrhön",),
    ))  # fmt: skip

    # 3 (SL): messenger Wed 18.11.2026.
    c3 = "newkinds-mieterhoehung-3"
    received = drawn(c3, LETTER_DAYS, date(2026, 11, 18))
    org = firm("Beispielsaar Wohnungsgenossenschaft eG", "Am Staden 15", "66121", "Mustersaarbrücken", monogram="BS",
               accent=(0, 110, 120), style="logo", tagline="Gemeinsam gut wohnen seit 1921", phone="0681 555 92 92",
               email="mitglieder@beispielsaar-eg.example", legal=("GnR 555 AG Mustersaarbrücken",))  # fmt: skip
    cases.append(make(
        c3, "SL", org, R_ME3, "Sehr geehrte Frau Beispielsaar,", received, 395.00, 434.50,
        [("Mitgliedsnummer", "4471-B"), ("Nutzungsvertrag", "NV 12-0087")],
        f"Zugestellt durch Boten der Genossenschaft am {de(received)} (Einwurf in den Briefkasten, 8:50 Uhr).",
        lambda eff: [
            P("die letzte Anpassung Ihres Nutzungsentgelts liegt mehr als drei Jahre zurück. Für Ihre Wohnung mit 55 m² "
              "zahlen Sie derzeit 395,00 € kalt."),
            P("Ein öffentlich bestellter und vereidigter Sachverständiger hat die ortsübliche Vergleichsmiete für Wohnungen "
              "dieser Art in Mustersaarbrücken mit 7,90 € je m² ermittelt; sein Gutachten vom 02.10.2026 liegt bei."),
            P(f"Wir bitten Sie um Ihre Zustimmung, das Nutzungsentgelt ab dem {eff} um 10 % auf 434,50 € zu erhöhen. Ihre "
              "Antwort benötigen wir bis Ende Januar 2027."),
        ],
        ["bis Ende Januar 2027"], "2027-02-01", ("Vorstand der Beispielsaar Wohnungsgenossenschaft eG",),
    ))  # fmt: skip

    # 4 (NI): messenger Fri 20.11.2026.
    c4 = "newkinds-mieterhoehung-4"
    received = drawn(c4, LETTER_DAYS, date(2026, 11, 20))
    org = firm("Immobilienverwaltung Musterheide OHG", "Marktstraße 30", "29614", "Beispielsoltau", monogram="IM",
               accent=(60, 100, 40), style="band", tagline="Haus- und Mietverwaltung", phone="05191 555 47 00",
               email="verwaltung@musterheide.example", legal=("AG Musterlüneburg HRA 1 470",))  # fmt: skip
    cases.append(make(
        c4, "NI", org, R_ME4, "Sehr geehrter Herr Exempelheide,", received, 560.00, 616.00,
        [("Objekt", "Heidekamp 9, EG links"), ("Vermieterin", "Erbengemeinschaft Beispielmoor")],
        f"Persönlich durch unsere Mitarbeiterin am {de(received)} in den Hausbriefkasten eingelegt.",
        lambda eff: [
            P("im Namen der Vermieterin, der Erbengemeinschaft Beispielmoor, bitten wir Sie, einer Anhebung Ihrer "
              f"Nettokaltmiete von 560,00 € auf 616,00 € ab dem {eff} zuzustimmen. Die Vollmacht fügen wir bei."),
            P("Ihre Miete ist seit dem 01.09.2023 gleich geblieben. Nach dem Mietspiegel der Stadt Beispielsoltau 2026 "
              "beträgt die Vergleichsmiete für Ihre Wohnung (80 m², Baujahr 1994, gute Lage) 7,70 € bis 8,30 € je m²; "
              "verlangt werden 7,70 €."),
            P("Sie können Ihre Zustimmung bis zum Ende des übernächsten Monats nach Erhalt dieses Schreibens erklären."),
        ],
        ["bis zum Ende des übernächsten Monats nach Erhalt dieses Schreibens"], "2027-02-01",
        ("Immobilienverwaltung Musterheide OHG", "i. A. Jannik Musterheide"), consent_line=False,
    ))  # fmt: skip
    return cases


# ==================================================================================================
# 6 — Betriebskostenabrechnung, late (§ 556 Abs. 3 BGB)
# ==================================================================================================

BK_RULE = (
    "Operating-cost statement received by messenger on the stated day (§ 130 Abs. 1 S. 1 BGB): the tenant's objections "
    "must reach the landlord by the end of the twelfth month after receipt (§ 556 Abs. 3 S. 5, 6 BGB)."
)


def betriebskosten() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, land: str, org: Org, person: Person, salutation: str, received: date, period: tuple[date, date],
             rows: list[tuple[str, float]], advance: float, refs: list[tuple[str, str]], handover: str, intro: str,
             closing: list[str], key: list[str], hand: str, pay_by: date | None, signer: tuple[str, ...], *,
             photo: bool = False) -> Case:  # fmt: skip
        due_why = Derivation()
        due = law.operating_costs_statement_due(period[1], due_why)
        assert due < received, (case_id, due)  # the statement comes late
        share = round(sum(v for _, v in rows), 2)
        balance = round(share - advance, 2)
        body = (*((label, eur_plain(v)) for label, v in rows), ("Ihr Anteil gesamt", eur_plain(share)),
                ("abzüglich Ihrer Vorauszahlungen", f"– {eur_plain(advance)}"),
                ("Nachzahlung" if balance > 0 else "Guthaben", eur_plain(abs(balance))))  # fmt: skip
        n = len(rows)
        table = Table(rows=body, header=(f"Abrechnung {de(period[0])} – {de(period[1])}", "EUR"), value_width=28,
                      bold_rows=(n, n + 2), rule_before=(n, n + 2), size=8.3)  # fmt: skip

        def calc(region: str | None) -> tuple[date, Derivation]:
            why = Derivation()
            return law.operating_costs_objection_end(received, region, why), why

        item = check(
            dated_item(kind="deadline", nature="objection", title="Einwendungen gegen die Betriebskostenabrechnung", calc=calc,
                       region=None, spec=spec("relative", anchor="explicit_date", amount=12, unit="months", anchor_date=received,
                                              shift=True), rule=BK_RULE,
                       note=f"The statement was due by {due.isoformat()} ({due_why.text()}); it comes late."),
            hand,
        )  # fmt: skip
        other = law.operating_costs_objection_end(received, None, Derivation(), calendar_months=True)
        item = tag(item, (*PRIVATE_IDS, "f09"), [other])
        optional: list[dict[str, Any]] = []
        if pay_by is not None:
            assert balance > 0, case_id
            pay = fixed_item(due=pay_by, region=None, kind="payment", nature="payment", title="Nachzahlung Betriebskosten",
                             money=balance, rule=f"Payment date the statement asks for; the statement was due by "
                             f"{fmt(due)} and comes late, so the Nachforderung is excluded (§ 556 Abs. 3 S. 3 BGB).")  # fmt: skip
            optional.append(with_conventions(pay, ["c01", "c06", "c10", "f10"], []))
        letter = Letter(org=org, recipient=person, info=[*refs, ("Datum", de(received))],
                        subject=f"Betriebskostenabrechnung {de(period[0])} bis {de(period[1])}", salutation=salutation,
                        subject_extra=(handover,), blocks=[P(intro), table,
                                *(P(text) for text in closing), Sign("Mit freundlichen Grüßen", signer)],
                        style=STYLES[case_id[-1]], created=created(received))  # fmt: skip
        t = truth(kind="rent_lease", sender=org.name, document_date=received, references=refs, amounts=[abs(balance)],
                  items=[item], optional_items=optional)  # fmt: skip
        return _case(case_id, "betriebskosten", letter, t, [de(received), eur_plain(abs(balance)), *key], land=land, photo=photo,
                     notes=f"Statement due {due}, received {received}; objections by {hand} (calendar-month reading {other}).")  # fmt: skip

    # 1 (BW, photo): period 2024 (due 31.12.2025, late); messenger Thu 19.11.2026 → Fri 19.11.2027 (other: Tue 30.11.2027).
    c1 = "newkinds-betriebskosten-1"
    received = drawn(c1, LETTER_DAYS, date(2026, 11, 19))
    pay_by = date(2026, 12, 15)
    org = firm("Hausverwaltung Exempeldreisam", "Bertoldstraße 20", "79098", "Beispielfreiburg", monogram="HE",
               accent=(40, 90, 60), style="logo", tagline="Mietverwaltung · WEG-Verwaltung", phone="0761 555 13 30",
               email="abrechnung@exempeldreisam.example", blz="68050101", account="5513300")  # fmt: skip
    cases.append(make(
        c1, "BW", org, R_BK1, "Sehr geehrte Frau Musterbreisgau,", received, (date(2024, 1, 1), date(2024, 12, 31)),
        [("Grundsteuer", 186.40), ("Wasser und Abwasser", 241.75), ("Müllabfuhr", 98.10), ("Hausreinigung", 132.00),
         ("Allgemeinstrom", 41.30), ("Gebäudeversicherung", 112.85), ("Heizung und Warmwasser", 694.20)],
        1320.00, [("Mieterkonto", "HE-0711-08")],
        f"Durch Boten am {de(received)} um 10:20 Uhr in Ihren Briefkasten eingeworfen.",
        "anbei erhalten Sie die Abrechnung der Betriebs- und Heizkosten Ihrer Wohnung Kaiser-Joseph-Weg 44 für das "
        "Kalenderjahr 2024. Ihr Anteil wurde nach Wohnfläche (74 m² von 612 m²) und für die Heizung nach Verbrauch ermittelt.",
        [f"Den Nachzahlungsbetrag überweisen Sie bitte bis zum {de(pay_by)} auf unser Konto.",
         "Die Belege können Sie nach Terminabsprache in unserem Büro einsehen."],
        ["Kalenderjahr 2024"], "2027-11-19", pay_by, ("Hausverwaltung Exempeldreisam", "Abteilung Abrechnung"), photo=True,
    ))  # fmt: skip

    # 2 (ST): period 01.07.2024–30.06.2025 (due 30.06.2026, late); messenger Wed 18.11.2026 → Thu 18.11.2027 (other 30.11.2027).
    c2 = "newkinds-betriebskosten-2"
    received = drawn(c2, LETTER_DAYS, date(2026, 11, 18))
    pay_by = date(2026, 12, 11)
    org = firm("Beispielelbe Immobilien GmbH", "Breiter Weg 101", "39104", "Mustermagdeburg", monogram="BE",
               accent=(0, 70, 130), style="band", tagline="Wohnen an der Elbe", phone="0391 555 72 72",
               email="service@beispielelbe.example", blz="81053272", account="5572720",
               legal=("AG Mustermagdeburg HRB 27 272",))  # fmt: skip
    cases.append(make(
        c2, "ST", org, R_BK2, "Sehr geehrter Herr Beispielmagd,", received, (date(2024, 7, 1), date(2025, 6, 30)),
        [("Grundsteuer", 154.90), ("Wasserversorgung und Entwässerung", 288.30), ("Straßenreinigung und Müll", 121.60),
         ("Aufzug", 96.00), ("Hauswart", 178.20), ("Heizkosten (Verbrauch und Grundkosten)", 802.45)],
        1500.00, [("Vertragsnummer", "BEI-58-2210")],
        f"Zugestellt durch unseren Hausmeister: Einwurf in den Briefkasten am {de(received)}, 9 Uhr.",
        "wir übersenden Ihnen die Abrechnung der Nebenkosten für den Abrechnungszeitraum vom 01.07.2024 bis zum 30.06.2025. "
        "Umgelegt wurde nach Wohnfläche (58 m²), die Heizkosten zu 70 % nach Verbrauch.",
        [f"Bitte gleichen Sie den offenen Betrag bis spätestens {de(pay_by)} aus.",
         "An der Höhe Ihrer monatlichen Abschläge ändert sich nichts."],
        ["01.07.2024 bis zum 30.06.2025"], "2027-11-18", pay_by, ("Beispielelbe Immobilien GmbH",),
    ))  # fmt: skip

    # 3 (SH): period 2024 (due 31.12.2025, late), credit; messenger Fri 20.11.2026 → Sat 20.11.2027 → Mon 22.11.2027
    # (other: Tue 30.11.2027).
    c3 = "newkinds-betriebskosten-3"
    received = drawn(c3, LETTER_DAYS, date(2026, 11, 20))
    org = firm("Klaus-Dieter Beispielmürwik", "Fördestraße 61", "24944", "Musterflensburg", monogram="KB",
               accent=(30, 60, 100), style="minimal", phone="0461 555 31 19", kind="landlord")  # fmt: skip
    cases.append(make(
        c3, "SH", org, R_BK3, "Moin Frau Exempelförde,", received, (date(2024, 1, 1), date(2024, 12, 31)),
        [("Grundsteuer", 132.00), ("Wasser/Abwasser", 205.80), ("Müll", 88.40), ("Schornsteinfeger", 38.50),
         ("Versicherungen", 96.70), ("Heizung (Gas)", 512.60)],
        1140.00, [("Wohnung", "Hafenstraße 12, OG")],
        f"Am {de(received)} um 9:30 Uhr persönlich in Ihren Briefkasten gesteckt.",
        "endlich komme ich dazu, Ihnen die Nebenkostenabrechnung für das Jahr 2024 zu schicken. Verteilt habe ich die Kosten "
        "nach Wohnfläche (64 m² von 128 m²), die Heizung nach den Zählerständen.",
        ["Das Guthaben überweise ich Ihnen in den nächsten Tagen auf Ihr bekanntes Konto.",
         "Wenn Sie Fragen haben, rufen Sie mich gerne an."],
        ["Nebenkostenabrechnung für das Jahr 2024"], "2027-11-22", None, ("Klaus-Dieter Beispielmürwik",),
    ))  # fmt: skip

    # 4 (TH): period 01.10.2024–30.09.2025 (due 30.09.2026, late); messenger Wed 18.11.2026 → Thu 18.11.2027 (other 30.11.2027).
    c4 = "newkinds-betriebskosten-4"
    received = drawn(c4, LETTER_DAYS, date(2026, 11, 18))
    pay_by = date(2027, 1, 8)
    org = firm("Wohnungsbau Exempelhörsel GmbH", "Karlsplatz 4", "99817", "Beispieleisenach", monogram="WE",
               accent=(120, 40, 40), style="logo", tagline="Kommunale Wohnungsgesellschaft", phone="03691 555 84 00",
               email="betriebskosten@exempelhoersel.example", blz="82050084", account="5584000",
               legal=("AG Musterjena HRB 584 000",))  # fmt: skip
    cases.append(make(
        c4, "TH", org, R_BK4, "Sehr geehrter Herr Musterwartburg,", received, (date(2024, 10, 1), date(2025, 9, 30)),
        [("Grundsteuer", 118.20), ("Kaltwasser und Abwasser", 236.90), ("Müllbeseitigung", 104.30), ("Gartenpflege", 64.00),
         ("Beleuchtung", 22.70), ("Fernwärme", 731.15)],
        1200.00, [("Mietvertrag", "WE-4417"), ("Wirtschaftseinheit", "Lutherstraße 15–21")],
        f"Zustellung durch Boten am {de_long(received)}, Einwurf in den Briefkasten um 11:05 Uhr.",
        "für den Zeitraum vom 01.10.2024 bis zum 30.09.2025 rechnen wir die Betriebskosten Ihrer Wohnung ab. Grundlage sind "
        "die Wohnfläche von 62 m² und die abgelesenen Wärmemengenzähler.",
        [f"Wir bitten um Zahlung der Nachforderung bis zum {de(pay_by)}.",
         "Einwendungen gegen diese Abrechnung teilen Sie uns bitte schriftlich mit."],
        ["01.10.2024 bis zum 30.09.2025"], "2027-11-18", pay_by, ("Wohnungsbau Exempelhörsel GmbH", "Mieterservice"),
    ))  # fmt: skip
    return cases


# ==================================================================================================
# 7 — Widerrufsbelehrung (§§ 355, 356 BGB): the withdrawal date is an optional item (c10)
# ==================================================================================================


def widerruf() -> list[Case]:
    cases: list[Case] = []

    def make(case_id: str, land: str, org: Org, person: Person, salutation: str, handed: date, start: date, start_rule: str,
             refs: list[tuple[str, str]], subject: str, intro: list[Block], belehrung: list[str], key: list[str], hand: str,
             amounts: list[float], signer: tuple[str, ...]) -> Case:  # fmt: skip
        def calc(region: str | None) -> tuple[date, Derivation]:
            why = Derivation()
            return law.withdrawal_end(start, region, why, start_rule=start_rule), why

        item = check(
            dated_item(kind="deadline", nature="declaration", title="Widerruf des Vertrags (freiwillig)", calc=calc, region=None,
                       spec=spec("relative", anchor="explicit_date", amount=14, unit="days", anchor_date=start, shift=True),
                       rule="Consumer's right of withdrawal: 14 days, sending in time suffices (§ 355 Abs. 1 S. 5, Abs. 2 BGB)."),
            hand,
        )  # fmt: skip
        item = tag(item, ("c01", "c04", "c06", "c10", "f11"), [])
        letter = Letter(org=org, recipient=person, info=[*refs, ("Datum", de(handed))], subject=subject, salutation=salutation,
                        blocks=[*intro, H("Widerrufsbelehrung", size=9.6), *(P(text, size=8.4) for text in belehrung),
                                Sign("Mit freundlichen Grüßen", signer)],
                        style=STYLES[case_id[-1]], created=created(handed))  # fmt: skip
        t = truth(kind="contract", sender=org.name, document_date=handed, references=refs, amounts=amounts, items=[],
                  optional_items=[item])  # fmt: skip
        return _case(case_id, "widerruf", letter, t, [de(handed), *key], land=land,
                     notes=f"Withdrawal period from {start}: 14 days → {hand} (optional).")  # fmt: skip

    # 1 (HH): service contract signed at the customer's home Fri 20.11.2026 → Fri 04.12.2026.
    c1 = "newkinds-widerruf-1"
    handed = drawn(c1, HANDOVER_DAYS, date(2026, 11, 20))
    org = firm("Wärmepumpenservice Beispielelbe GmbH", "Billstraße 90", "20539", "Hamburg", monogram="WB", accent=(0, 120, 90),
               style="band", tagline="Wartung · Störungsdienst · Effizienz-Check", phone="040 555 90 12",
               email="vertrag@wp-beispielelbe.example", legal=("AG Hamburg HRB 555 901",))  # fmt: skip
    cases.append(make(
        c1, "HH", org, R_WR1, "Sehr geehrter Herr Beispielalster,", handed, handed,
        "§ 355 Abs. 2 S. 2 BGB (a service contract: from conclusion)",
        [("Vertragsnummer", "WB-WV-26-3318")], "Ihr Wartungsvertrag für die Wärmepumpe",
        [P(f"Sie haben heute, am {de(handed)}, bei unserem Besuch in Ihrem Haus den Wartungsvertrag „Komfort“ für Ihre "
           "Luft-Wasser-Wärmepumpe unterschrieben. Dieses Schreiben hat Ihnen unser Techniker gleich danach übergeben."),
         Table(rows=(("Leistung", "jährliche Wartung, Störungsdienst werktags"), ("Laufzeit", "12 Monate ab 01.01.2027"),
                     ("Preis", "19,90 € monatlich")), header=("Vertragsinhalt", ""), value_width=86, value_align="L", size=8.6)],
        ["Sie können diesen Vertrag innerhalb von vierzehn Tagen ohne Begründung widerrufen. Die Frist beginnt mit dem Tag, "
         "an dem der Vertrag geschlossen wurde.",
         "Um zu widerrufen, schicken Sie uns (Wärmepumpenservice Beispielelbe GmbH, Billstraße 90, 20539 Hamburg, "
         "vertrag@wp-beispielelbe.example) eine eindeutige Erklärung, etwa per Brief oder E-Mail. Sie dürfen dafür das "
         "beiliegende Formular nehmen, müssen es aber nicht. Es reicht, wenn Ihre Erklärung vor Ablauf der Frist abgeschickt "
         "wird.",
         "Widerrufen Sie, erstatten wir alle Zahlungen spätestens vierzehn Tage nach Eingang Ihres Widerrufs."],
        ["innerhalb von vierzehn Tagen ohne Begründung widerrufen"], "2026-12-04", [19.90],
        ("Wärmepumpenservice Beispielelbe GmbH",),
    ))  # fmt: skip

    # 2 (NW): electricity contract signed at the door Fri 20.11.2026 (§ 356 Abs. 2 Nr. 2 BGB) → Fri 04.12.2026.
    c2 = "newkinds-widerruf-2"
    handed = drawn(c2, HANDOVER_DAYS, date(2026, 11, 20))
    org = firm("Exempelenergie Rheinschiene AG", "Kraftwerkstraße 4", "47053", "Musterduisburg", monogram="ER",
               accent=(170, 80, 0), style="logo", tagline="Strom und Gas für Haushalte", phone="0203 555 44 22",
               email="kundenservice@exempelenergie.example", legal=("AG Musterduisburg HRB 44 220",))  # fmt: skip
    cases.append(make(
        c2, "NW", org, R_WR2, "Sehr geehrte Frau Exempelrhein,", handed, handed,
        "§ 356 Abs. 2 Nr. 2 BGB (electricity supply: from conclusion)",
        [("Kundennummer", "ER-77104528"), ("Zählernummer", "1EBZ0115508822")], "Bestätigung Ihres Stromliefervertrags",
        [P(f"vielen Dank für das Gespräch an Ihrer Haustür. Mit Ihrer Unterschrift vom {de(handed)} haben Sie unseren Tarif "
           "„Rhein Strom fix 24“ abgeschlossen; diese Bestätigung hat Ihnen unsere Beraterin vor Ort ausgehändigt."),
         Table(rows=(("Lieferbeginn", "voraussichtlich 01.02.2027"), ("Arbeitspreis", "29,80 Cent/kWh"),
                     ("Grundpreis", "12,50 € monatlich"), ("Abschlag", "74,00 € monatlich")),
               header=("Ihr Tarif", ""), value_width=80, value_align="L", size=8.6)],
        ["Sie haben das Recht, binnen vierzehn Tagen ab Vertragsschluss ohne Angabe von Gründen von diesem Vertrag "
         "zurückzutreten, indem Sie ihn widerrufen.",
         "Ihre Erklärung richten Sie an die Exempelenergie Rheinschiene AG, Kraftwerkstraße 4, 47053 Musterduisburg, oder "
         "an kundenservice@exempelenergie.example. Ein Formular liegt bei; Sie können aber auch formlos schreiben. Für die "
         "Frist kommt es darauf an, wann Sie den Widerruf absenden.",
         "Haben Sie verlangt, dass die Belieferung schon während der Widerrufsfrist beginnt, zahlen Sie für die bis zum "
         "Widerruf gelieferte Energie einen anteiligen Betrag."],
        ["binnen vierzehn Tagen ab Vertragsschluss"], "2026-12-04", [74.00], ("Exempelenergie Rheinschiene AG",),
    ))  # fmt: skip

    # 3 (BY): furniture ordered online, delivered by the seller's own team Wed 18.11.2026 (§ 356 Abs. 2 Nr. 1 a BGB)
    # → Wed 02.12.2026.
    c3 = "newkinds-widerruf-3"
    handed = drawn(c3, HANDOVER_DAYS, date(2026, 11, 18))
    org = firm("Möbelmanufaktur Musterwendel GmbH", "Tischlerweg 7", "83022", "Beispielrosenheim", monogram="MW",
               accent=(120, 80, 40), style="minimal", tagline="Massivholzmöbel online bestellen", phone="08031 555 66 70",
               email="bestellung@musterwendel.example", legal=("AG Beispielrosenheim HRB 6 667",))  # fmt: skip
    cases.append(make(
        c3, "BY", org, R_WR3, "Sehr geehrte Frau Musterchiem,", handed, handed,
        "§ 356 Abs. 2 Nr. 1 a BGB (sale of goods: from receipt of the goods)",
        [("Bestellnummer", "MW-2026-10-4471"), ("Lieferschein", "LS-88213")], "Lieferschein und Rechnung zu Ihrer Bestellung",
        [P(f"unser Auslieferungsteam hat Ihnen heute, am {de(handed)}, den Esstisch „Chiemgau“ in Eiche (180 × 90 cm) und "
           "sechs Stühle geliefert und aufgebaut. Ihre Bestellung in unserem Onlineshop vom 26.10.2026 ist damit vollständig "
           "erfüllt; dieses Blatt erhalten Sie zusammen mit der Ware."),
         Table(rows=(("Esstisch Eiche massiv", "1.690,00 €"), ("6 Stühle Eiche, Sitz Leder", "1.344,00 €"),
                     ("Gesamt, bereits bezahlt", "3.034,00 €")), header=("Rechnung", ""), value_width=40, size=8.6)],
        ["Sie können Ihre Bestellung binnen vierzehn Tagen widerrufen, ohne Gründe zu nennen. Die Frist läuft ab dem Tag, an "
         "dem Sie die Ware erhalten haben.",
         "Teilen Sie uns Ihren Entschluss eindeutig mit, zum Beispiel per Brief an Möbelmanufaktur Musterwendel GmbH, "
         "Tischlerweg 7, 83022 Beispielrosenheim, oder per E-Mail an bestellung@musterwendel.example. Rechtzeitig ist der "
         "Widerruf, wenn Sie ihn vor Fristende absenden.",
         "Nach einem Widerruf holen wir die Möbel auf unsere Kosten ab und zahlen Ihnen den Kaufpreis zurück."],
        ["Die Frist läuft ab dem Tag, an dem Sie die Ware erhalten haben"], "2026-12-02", [],
        ("Möbelmanufaktur Musterwendel GmbH", "Kundenservice"),
    ))  # fmt: skip

    # 4 (BW): cleaning-service contract at a promotion stand in a shopping centre Sat 21.11.2026 → Sat 05.12.2026, § 193 BGB
    # → Mon 07.12.2026.
    c4 = "newkinds-widerruf-4"
    handed = drawn(c4, HANDOVER_DAYS, date(2026, 11, 21))
    org = firm("Glanzwerk Beispielputz GmbH", "Reinigungsallee 12", "70565", "Musterstuttgart", monogram="GB",
               accent=(0, 120, 170), style="band", tagline="Haushaltsreinigung im Abo", phone="0711 555 87 87",
               email="abo@glanzwerk-beispielputz.example", legal=("AG Musterstuttgart HRB 758 787",))  # fmt: skip
    cases.append(make(
        c4, "BW", org, R_WR4, "Hallo Herr Beispielneckar,", handed, handed,
        "§ 355 Abs. 2 S. 2 BGB (a service contract: from conclusion)",
        [("Kundennummer", "GW-10-55821")], "Willkommen bei Glanzwerk – Ihre Vertragsbestätigung",
        [P(f"schön, dass Sie sich am {de(handed)} an unserem Aktionsstand im Einkaufszentrum Neckarbogen für unser "
           "Reinigungsabo entschieden haben. Diese Bestätigung haben Sie direkt am Stand mitbekommen."),
         Table(rows=(("Leistung", "Wohnungsreinigung alle 14 Tage, 3 Stunden"), ("Beginn", "07.01.2027"),
                     ("Preis", "119,00 € monatlich")), header=("Ihr Abo", ""), value_width=86, value_align="L", size=8.6)],
        ["Innerhalb von 14 Tagen nach Vertragsschluss können Sie sich ohne Begründung wieder von diesem Vertrag lösen, "
         "indem Sie ihn widerrufen.",
         "Dazu genügt eine klare Mitteilung an Glanzwerk Beispielputz GmbH, Reinigungsallee 12, 70565 Musterstuttgart, "
         "oder an abo@glanzwerk-beispielputz.example. Das beigefügte Formular können Sie verwenden. Maßgeblich ist, dass "
         "Sie den Widerruf innerhalb der Frist absenden.",
         "Bereits gezahlte Beträge erhalten Sie nach einem Widerruf binnen 14 Tagen zurück."],
        ["Innerhalb von 14 Tagen nach Vertragsschluss"], "2026-12-07", [119.00], ("Ihr Glanzwerk-Team",),
    ))  # fmt: skip
    return cases
