"""Fictional senders ('Muster…/Beispiel…') and recipients.

Organisations whose Land is *known* name it in the letterhead (``head``); ``region`` is the label.
Organisations with ``region=None`` never name a Land, and every date derived from their letters is
asserted to be the same under all 16 Land calendars (see ``common.dated_item``).
"""

from __future__ import annotations

from .pdf import Org, Person
from .text import iban

# --------------------------------------------------------------------------------------------------
# recipients (one per Land used, plus a generic one)
# --------------------------------------------------------------------------------------------------

P_NW = Person("Mara Beispiel", "Lindenweg 12", "44137", "Musterstadt")
P_BY = Person("Jonas Mustermann", "Bergstraße 3a", "83026", "Musterbach am Inn")
P_NI = Person("Aylin Musterfrau", "Am Weidenkamp 8", "31137", "Beispielhausen")
P_HE = Person("Tobias Beispiel", "Heinrichstraße 41", "64283", "Beispielstadt")
P_SN = Person("Lea Muster", "Karl-Tauchnitz-Weg 5", "04107", "Musterlingen")
P_SH = Person("Finn Beispielsen", "Förde-Allee 19", "24105", "Beispielförde")
P_HH = Person("Sophie Mustermann", "Eppendorfer Stieg 7", "20251", "Hamburg")
P_BW = Person("Emre Beispiel", "Neckarhalde 22", "72070", "Beispielheim")
P_BE = Person("Nora Musterova", "Warschauer Zeile 14", "10245", "Berlin")
P_GEN = Person("Mara Beispiel", "Lindenweg 12", "44137", "Musterstadt")
P_GEN2 = Person("David Muster", "Sonnenhang 4", "34119", "Neu-Musterdorf")
P_EN = Person("Priya Sharma", "Lindenweg 12", "44137", "Musterstadt", country="Germany")
P_EN2 = Person("Daniel O'Connor", "Warschauer Zeile 14", "10245", "Berlin", country="GERMANY")


def _iban(blz: str, account: str) -> str:
    return iban("DE", blz + account.zfill(10))


# The recipients' own accounts (refunds are paid there) — valid check digits, fictional accounts.
RECIPIENT_IBAN = _iban("44050199", "123456789")
RECIPIENT_IBAN_2 = _iban("52050353", "8765432")


# --------------------------------------------------------------------------------------------------
# tax offices (AO)
# --------------------------------------------------------------------------------------------------

FA_NW = Org(
    name="Finanzamt Musterstadt-Nord",
    kind="tax_office",
    street="Beispielallee 20",
    postcode="44139",
    city="Musterstadt",
    region="NW",
    head=("Finanzverwaltung des Landes Nordrhein-Westfalen",),
    phone="Telefon 0231 5550-0",
    email="service@fa-musterstadt-nord.example",
    web="www.finanzamt-musterstadt.example",
    bank="Landesbank Muster",
    iban=_iban("30050000", "4321001"),
    bic="MUSTDEDDXXX",
    style="authority",
    accent=(0, 95, 70),
    hours=("Servicezentrum:", "Mo–Mi 8–15 Uhr", "Do 8–18 Uhr, Fr 8–12 Uhr"),
)
FA_NI = Org(
    name="Finanzamt Beispielhausen",
    kind="tax_office",
    street="Am Musterwall 7",
    postcode="31134",
    city="Beispielhausen",
    region="NI",
    head=("Niedersächsische Steuerverwaltung · Land Niedersachsen",),
    phone="Tel. 05121 9876-0",
    email="poststelle@fa-beispielhausen.example",
    bank="Norddeutsche Musterbank",
    iban=_iban("25050000", "7002001"),
    bic="NOMUDE2HXXX",
    style="band",
    accent=(35, 55, 105),
    hours=("Öffnungszeiten:", "Mo–Fr 8–12 Uhr", "Do zusätzlich 14–17 Uhr"),
)
FA_BY = Org(
    name="Finanzamt Musterbach",
    kind="tax_office",
    street="Innstraße 30",
    postcode="83022",
    city="Musterbach am Inn",
    region="BY",
    head=("Bayerisches Landesamt für Steuern · Freistaat Bayern", "Dienststelle Musterbach am Inn"),
    phone="Telefon 08031 3030-0",
    email="poststelle.fa-musterbach@finanz.example",
    bank="Bayerische Musterbank",
    iban=_iban("70050000", "12345"),
    bic="BYMUDEMMXXX",
    style="authority",
    accent=(0, 85, 150),
    hours=("Servicezentrum:", "Mo–Mi 7:30–15 Uhr", "Do 7:30–17:30, Fr 7:30–12 Uhr"),
)
FA_HE = Org(
    name="Finanzamt Beispielstadt",
    kind="tax_office",
    street="Rheinstraße 88",
    postcode="64295",
    city="Beispielstadt",
    region="HE",
    head=("Hessische Steuerverwaltung · Land Hessen",),
    phone="06151 102-0",
    email="poststelle@fa-beispielstadt.example",
    bank="Hessische Musterbank",
    iban=_iban("50050000", "1002030"),
    bic="HEMUDEFFXXX",
    style="minimal",
    accent=(150, 20, 30),
)
FA_X1 = Org(
    name="Finanzamt Neu-Musterdorf",
    kind="tax_office",
    street="Postfach 12 40",
    postcode="34001",
    city="Neu-Musterdorf",
    region=None,
    head=("Steuerverwaltung",),
    phone="Tel. 0561 7040-0",
    email="poststelle@fa-neu-musterdorf.example",
    bank="Musterbank",
    iban=_iban("52050000", "1200340"),
    style="authority",
    accent=(70, 70, 75),
)
FA_X2 = Org(
    name="Finanzamt Musterhafen",
    kind="tax_office",
    street="Kaistraße 1",
    postcode="27568",
    city="Musterhafen",
    region=None,
    phone="Telefon 0471 5960-0",
    email="service@fa-musterhafen.example",
    bank="Hafenbank Muster",
    iban=_iban("29050000", "8800770"),
    style="band",
    accent=(25, 70, 90),
    hours=("Info-Center:", "Mo–Fr 8–12 Uhr"),
)

# --------------------------------------------------------------------------------------------------
# municipal / Land authorities (Land VwVfG; only Länder with the verified 4-day rule)
# --------------------------------------------------------------------------------------------------

STADT_NW = Org(
    name="Stadt Musterstadt",
    kind="authority",
    street="Rathausplatz 1",
    postcode="44135",
    city="Musterstadt",
    region="NW",
    head=("Land Nordrhein-Westfalen", "Der Oberbürgermeister · Ordnungsamt"),
    phone="Tel. 0231 50-0",
    email="ordnungsamt@musterstadt.example",
    web="www.musterstadt.example",
    bank="Sparkasse Musterstadt",
    iban=_iban("44050199", "1000100"),
    style="authority",
    accent=(160, 25, 35),
    hours=("Sprechzeiten:", "Mo, Di, Do 8–12 Uhr", "Do 14–17 Uhr"),
)
LRA_BY = Org(
    name="Landratsamt Beispielkreis",
    kind="authority",
    street="Landratsplatz 2",
    postcode="83043",
    city="Musterau",
    region="BY",
    head=("Freistaat Bayern · Landkreis Beispielkreis", "Sachgebiet 32 – Öffentliche Sicherheit und Ordnung"),
    phone="08061 58-0",
    email="poststelle@lra-beispielkreis.example",
    web="www.beispielkreis.example",
    bank="Kreissparkasse Beispielkreis",
    iban=_iban("71150000", "20304"),
    style="band",
    accent=(0, 75, 135),
    hours=("Parteiverkehr:", "Mo–Fr 8–12 Uhr", "Do 14–17:30 Uhr"),
)
KREIS_SH = Org(
    name="Kreis Beispielförde",
    kind="authority",
    street="Kreishaus, Förder Straße 3",
    postcode="24103",
    city="Beispielförde",
    region="SH",
    head=("Land Schleswig-Holstein · Der Landrat", "Fachdienst Straßenverkehr – Fahrerlaubnisse"),
    phone="Tel. 0431 9900-0",
    email="verkehr@kreis-beispielfoerde.example",
    bank="Förde Sparkasse Muster",
    iban=_iban("21050170", "9090"),
    style="authority",
    accent=(0, 70, 140),
)
BA_HH = Org(
    name="Bezirksamt Musterbek",
    kind="authority",
    street="Musterbeker Markt 4",
    postcode="22297",
    city="Hamburg",
    region="HH",
    head=("Freie und Hansestadt Hamburg", "Fachamt Management des öffentlichen Raumes"),
    phone="040 42804-0",
    email="mr@musterbek.hamburg.example",
    bank="Hamburger Musterkasse",
    iban=_iban("20050000", "1027000"),
    style="minimal",
    accent=(170, 20, 25),
)
STADT_BW = Org(
    name="Stadt Beispielheim",
    kind="authority",
    street="Am Markt 1",
    postcode="72070",
    city="Beispielheim",
    region="BW",
    head=("Land Baden-Württemberg · Große Kreisstadt Beispielheim", "Baurechtsamt"),
    phone="07071 204-0",
    email="baurecht@beispielheim.example",
    bank="Kreissparkasse Beispielheim",
    iban=_iban("64150020", "3300"),
    style="logo",
    accent=(120, 90, 0),
    monogram="SB",
)

# --------------------------------------------------------------------------------------------------
# social law (SGB X)
# --------------------------------------------------------------------------------------------------

KK_X = Org(
    name="Muster BKK",
    kind="health_insurer",
    street="Beispielweg 1",
    postcode="34117",
    city="Neu-Musterdorf",
    head=("Die Betriebskrankenkasse für Beispiel-Unternehmen",),
    phone="Tel. 0561 9000-0",
    email="service@muster-bkk.example",
    web="www.muster-bkk.example",
    bank="Musterbank",
    iban=_iban("52040021", "7775550"),
    style="band",
    accent=(0, 100, 90),
    legal=("Körperschaft des öffentlichen Rechts",),
)
KK_X2 = Org(
    name="Allgemeine Musterkasse",
    kind="health_insurer",
    street="Gesundheitsplatz 5",
    postcode="30159",
    city="Musterstadt",
    head=("Die Gesundheitskasse",),
    phone="0800 123 456 7",
    email="kontakt@allgemeine-musterkasse.example",
    bank="Muster Landesbank",
    iban=_iban("25050180", "4455"),
    style="logo",
    accent=(0, 110, 60),
    monogram="AM",
    legal=("Körperschaft des öffentlichen Rechts",),
)
JC_SN = Org(
    name="Jobcenter Musterlingen",
    kind="authority",
    street="Georg-Schwarz-Straße 60",
    postcode="04177",
    city="Musterlingen",
    region="SN",
    head=("Freistaat Sachsen · gemeinsame Einrichtung", "Team 311 – Leistungsgewährung"),
    phone="0341 91335-0",
    email="jobcenter-musterlingen@jobcenter.example",
    bank="Bundesbank Muster",
    iban=_iban("86000000", "86001040"),
    style="authority",
    accent=(190, 30, 45),
    hours=("Öffnungszeiten:", "Mo, Di, Fr 8–12 Uhr", "Do 8–18 Uhr"),
)
JC_HE = Org(
    name="Jobcenter Beispielkreis",
    kind="authority",
    street="Mainzer Landstraße 5",
    postcode="64293",
    city="Beispielstadt",
    region="HE",
    head=("Land Hessen · Kommunales Jobcenter",),
    phone="06151 881-0",
    email="info@jobcenter-beispielkreis.example",
    bank="Sparkasse Beispielstadt",
    iban=_iban("50850150", "44"),
    style="minimal",
    accent=(0, 90, 150),
)
FK_X = Org(
    name="Familienkasse Muster-Mitte",
    kind="authority",
    street="Postfach 44 01",
    postcode="34002",
    city="Neu-Musterdorf",
    head=("Bundesagentur für Arbeit (Musterausgabe)",),
    phone="Tel. 0800 4 5555 30",
    email="familienkasse-muster-mitte@arbeitsagentur.example",
    bank="Bundesbank Muster",
    iban=_iban("76000000", "76001617"),
    style="band",
    accent=(170, 20, 30),
)
DRV_X = Org(
    name="Muster-Rentenversicherung Bund",
    kind="authority",
    street="Ruhrstraße 2",
    postcode="10709",
    city="Musterstadt",
    head=("Gesetzliche Rentenversicherung (fiktiv)",),
    phone="Servicetelefon 0800 1000 480",
    email="post@muster-rv.example",
    style="authority",
    accent=(0, 70, 130),
)

# --------------------------------------------------------------------------------------------------
# fines (OWiG)
# --------------------------------------------------------------------------------------------------

BG_BY = Org(
    name="Stadt Musterau – Bußgeldstelle",
    kind="authority",
    street="Rosenheimer Straße 12",
    postcode="83043",
    city="Musterau",
    region="BY",
    head=("Freistaat Bayern", "Kommunale Verkehrsüberwachung"),
    phone="08061 99-120",
    email="bussgeld@musterau.example",
    bank="Sparkasse Musterau",
    iban=_iban("71150000", "7707"),
    bic="BYLADEM1MUS",
    style="authority",
    accent=(0, 85, 150),
)
BG_NW = Org(
    name="Kreis Musterland – Bußgeldstelle",
    kind="authority",
    street="Kreishausstraße 1",
    postcode="59494",
    city="Beispielsoest",
    region="NW",
    head=("Land Nordrhein-Westfalen · Der Landrat",),
    phone="02921 30-0",
    email="bussgeldstelle@kreis-musterland.example",
    bank="Sparkasse Musterland",
    iban=_iban("41450075", "20001"),
    style="band",
    accent=(0, 95, 70),
)
BG_NI = Org(
    name="Landkreis Beispielheide",
    kind="authority",
    street="Am Kreishaus 3",
    postcode="29614",
    city="Heidemuster",
    region="NI",
    head=("Land Niedersachsen", "Bußgeldstelle – Verkehrsordnungswidrigkeiten"),
    phone="05191 970-0",
    email="bussgeld@lk-beispielheide.example",
    bank="Kreissparkasse Beispielheide",
    iban=_iban("25851660", "5566"),
    style="authority",
    accent=(40, 90, 40),
)
BG_BE = Org(
    name="Polizei Berlin (Muster) – Bußgeldstelle",
    kind="authority",
    street="Musterdamm 45",
    postcode="10179",
    city="Berlin",
    region="BE",
    head=("Land Berlin · Der Polizeipräsident (fiktive Musterbehörde)",),
    phone="030 4664-0",
    email="bussgeldstelle@polizei-muster.berlin.example",
    bank="Berliner Musterbank",
    iban=_iban("10050000", "990007"),
    style="minimal",
    accent=(30, 50, 110),
)
BG_X = Org(
    name="Zentrale Bußgeldstelle Musterland",
    kind="authority",
    street="Postfach 20 20",
    postcode="34003",
    city="Neu-Musterdorf",
    phone="0561 1060-0",
    email="zbs@bussgeld-musterland.example",
    bank="Musterbank",
    iban=_iban("52050000", "3434"),
    style="band",
    accent=(40, 40, 90),
)

# --------------------------------------------------------------------------------------------------
# companies
# --------------------------------------------------------------------------------------------------


def company(name: str, street: str, postcode: str, city: str, *, monogram: str, accent: tuple[int, int, int],
            style: str = "logo", kind: str = "company", tagline: str = "", phone: str = "", email: str = "",
            web: str = "", blz: str = "37050198", account: str = "1234567", hr: str = "", vat: str = "",
            country: str = "") -> Org:  # fmt: skip
    legal = tuple(x for x in (hr, vat) if x)
    return Org(
        name=name,
        kind=kind,
        street=street,
        postcode=postcode,
        city=city,
        head=(tagline,) if tagline else (),
        phone=phone,
        email=email,
        web=web,
        bank="Musterbank AG",
        iban=_iban(blz, account),
        bic="MUSTDEMMXXX",
        style=style,
        accent=accent,
        monogram=monogram,
        legal=legal,
        country=country,
    )
