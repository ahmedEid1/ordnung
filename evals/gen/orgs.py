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


# --------------------------------------------------------------------------------------------------
# holdout split (variants E, F and the holdout adversarial letters): new senders and recipients,
# none of them shared with the dev or test letters
# --------------------------------------------------------------------------------------------------

H_RP = Person("Johanna Beispielkamp", "Weinbergstraße 5", "54470", "Musterweiler")
H_SL = Person("Luca Musterhofer", "Saarufer 31", "66119", "Beispielbrück")
H_ST = Person("Greta Beispielmann", "Elbwiese 2b", "39104", "Musterstedt")
H_BW = Person("Anton Musterle", "Kelterweg 9", "70599", "Beispielingen")
H_SH = Person("Merle Beispielsen", "Deichstraße 44", "25813", "Musterwik")
H_NW = Person("Hakan Beispielkötter", "Zechenweg 3", "45879", "Musterhagen")
H_HH = Person("Clara Musterbrook", "Grindelhof 21", "20146", "Hamburg")
H_BY = Person("Veronika Beispielhuber", "Almweg 6", "83684", "Beispielsee")
H_TH = Person("Ole Musterrößler", "Am Anger 14", "99084", "Musterrode")
H_MV = Person("Ida Beispielow", "Strandstraße 8", "18055", "Beispielmünde")
H_NI = Person("Maja Musterjohann", "Heideweg 27", "29221", "Beispielstedt")
H_HB = Person("Jan Beispielmeyer", "Schlachte 40", "28195", "Bremen")
H_GEN = Person("Lina Mustermeier", "Birkenallee 15", "37073", "Neu-Beispielstadt")
H_GEN2 = Person("Tarek Beispiel", "Am Mühlbach 2", "35039", "Musterbergen")
H_EN = Person("Aisha Okafor", "Birkenallee 15", "37073", "Neu-Beispielstadt", country="Germany")
H_EN2 = Person("Liam Fitzgerald", "Grindelhof 21", "20146", "Hamburg", country="GERMANY")
H_RECIPIENT_IBAN = _iban("26050001", "44102938")

# tax offices (AO)
H_FA_RP = Org(
    name="Finanzamt Musterweiler",
    kind="tax_office",
    street="Moselstraße 12",
    postcode="54470",
    city="Musterweiler",
    region="RP",
    head=("Steuerverwaltung Rheinland-Pfalz",),
    phone="Telefon 06531 880-0",
    email="poststelle@fa-musterweiler.example",
    bank="Landesbank Muster Rheinland",
    iban=_iban("57050000", "5500112"),
    bic="MURPDE5KXXX",
    style="band",
    accent=(95, 30, 50),
    hours=("Service-Center:", "Mo–Do 8–16 Uhr", "Fr 8–12 Uhr"),
)
H_FA_SL = Org(
    name="Finanzamt Beispielbrück",
    kind="tax_office",
    street="Am Hafenbecken 3",
    postcode="66111",
    city="Beispielbrück",
    region="SL",
    head=("Saarland · Steuerverwaltung", "Veranlagungsstelle Arbeitnehmer"),
    phone="0681 3000-0",
    email="poststelle@fa-beispielbrueck.example",
    bank="Saarländische Musterbank",
    iban=_iban("59050000", "8812001"),
    style="authority",
    accent=(0, 70, 120),
)
H_FA_ST = Org(
    name="Finanzamt Musterstedt",
    kind="tax_office",
    street="Domplatz 9",
    postcode="39104",
    city="Musterstedt",
    region="ST",
    head=("Land Sachsen-Anhalt · Steuerverwaltung",),
    phone="0391 885-0",
    email="poststelle@fa-musterstedt.example",
    bank="Mitteldeutsche Musterbank",
    iban=_iban("81050000", "4420003"),
    style="logo",
    accent=(20, 80, 60),
    monogram="FA",
)
H_FA_X = Org(
    name="Finanzamt Neu-Beispielstadt",
    kind="tax_office",
    street="Postfach 31 07",
    postcode="37002",
    city="Neu-Beispielstadt",
    phone="Tel. 0551 4077-0",
    email="service@fa-neu-beispielstadt.example",
    bank="Musterbank Süd",
    iban=_iban("26050001", "3107000"),
    style="minimal",
    accent=(60, 60, 110),
)
H_FA_X2 = Org(
    name="Finanzamt Musterbergen",
    kind="tax_office",
    street="Lahnufer 18",
    postcode="35037",
    city="Musterbergen",
    head=("Steuerverwaltung",),
    phone="06421 698-0",
    email="poststelle@fa-musterbergen.example",
    bank="Musterbank Mitte",
    iban=_iban("53350000", "6980002"),
    style="authority",
    accent=(90, 60, 20),
)

# municipal / Land authorities (Land VwVfG; only Länder with the verified 4-day rule)
H_STADT_BW = Org(
    name="Stadt Beispielingen",
    kind="authority",
    street="Marktstraße 2",
    postcode="70597",
    city="Beispielingen",
    region="BW",
    head=(
        "Land Baden-Württemberg · Stadt Beispielingen",
        "Amt für öffentliche Ordnung – Straßenverkehrsbehörde",
    ),
    phone="0711 216-0",
    email="ordnungsamt@beispielingen.example",
    bank="Kreissparkasse Beispielingen",
    iban=_iban("61150020", "77000"),
    style="authority",
    accent=(140, 100, 0),
)
H_KREIS_SH = Org(
    name="Kreis Nordmuster",
    kind="authority",
    street="Kreishaus, Marktstraße 1",
    postcode="25813",
    city="Musterwik",
    region="SH",
    head=("Land Schleswig-Holstein · Der Landrat", "Fachdienst Naturschutz"),
    phone="04841 67-0",
    email="naturschutz@kreis-nordmuster.example",
    bank="Nord-Ostsee Musterkasse",
    iban=_iban("21750000", "670100"),
    style="band",
    accent=(0, 60, 110),
)
H_STADT_NW = Org(
    name="Stadt Musterhagen",
    kind="authority",
    street="Rathausplatz 7",
    postcode="45875",
    city="Musterhagen",
    region="NW",
    head=("Land Nordrhein-Westfalen", "Die Bürgermeisterin · Untere Bauaufsichtsbehörde"),
    phone="0209 169-0",
    email="bauaufsicht@musterhagen.example",
    bank="Sparkasse Musterhagen",
    iban=_iban("42050001", "169000"),
    style="minimal",
    accent=(120, 20, 40),
)
H_BA_HH = Org(
    name="Bezirksamt Beispielbüttel",
    kind="authority",
    street="Grindelberg 62",
    postcode="20144",
    city="Hamburg",
    region="HH",
    head=("Freie und Hansestadt Hamburg", "Fachamt Wohnraumschutz"),
    phone="040 42801-0",
    email="wohnraumschutz@beispielbuettel.hamburg.example",
    bank="Hamburger Musterkasse",
    iban=_iban("20050000", "1042800"),
    style="authority",
    accent=(160, 20, 30),
)

# social law (SGB X)
H_KK = Org(
    name="Beispiel Ersatzkasse",
    kind="health_insurer",
    street="Versichertenplatz 1",
    postcode="22083",
    city="Musterhude",
    head=("Kranken- und Pflegeversicherung",),
    phone="0800 400 1234",
    email="service@beispiel-ersatzkasse.example",
    web="www.beispiel-ersatzkasse.example",
    bank="Musterbank",
    iban=_iban("20040000", "4001234"),
    style="logo",
    accent=(0, 85, 125),
    monogram="BE",
    legal=("Körperschaft des öffentlichen Rechts",),
)
H_PK = Org(
    name="Pflegekasse bei der Beispiel Ersatzkasse",
    kind="health_insurer",
    street="Versichertenplatz 1",
    postcode="22083",
    city="Musterhude",
    head=("Soziale Pflegeversicherung",),
    phone="0800 400 1250",
    email="pflege@beispiel-ersatzkasse.example",
    bank="Musterbank",
    iban=_iban("20040000", "4001250"),
    style="band",
    accent=(0, 85, 125),
    legal=("Körperschaft des öffentlichen Rechts",),
)
H_JC_BY = Org(
    name="Jobcenter Beispielsee",
    kind="authority",
    street="Seestraße 40",
    postcode="83684",
    city="Beispielsee",
    region="BY",
    head=("Freistaat Bayern · Jobcenter Landkreis Beispielsee", "Team Leistung 2"),
    phone="08022 9170-0",
    email="jobcenter-beispielsee@jobcenter.example",
    bank="Bundesbank Muster",
    iban=_iban("70000000", "70001522"),
    style="minimal",
    accent=(170, 30, 40),
)
H_ELG_MV = Org(
    name="Landesamt für Soziales Beispielmünde – Elterngeldstelle",
    kind="authority",
    street="Am Hafen 5",
    postcode="18055",
    city="Beispielmünde",
    region="MV",
    head=("Land Mecklenburg-Vorpommern", "Elterngeld und Elternzeit"),
    phone="0381 331-0",
    email="elterngeld@lafs-beispielmuende.example",
    bank="Landeszentralbank Muster",
    iban=_iban("13000000", "13001088"),
    style="authority",
    accent=(0, 75, 140),
)
H_AA_X = Org(
    name="Agentur für Arbeit Musterbergen",
    kind="authority",
    street="Bahnhofstraße 12",
    postcode="35037",
    city="Musterbergen",
    head=("Bundesagentur für Arbeit (Musterausgabe)", "Operativer Service"),
    phone="0800 4 5555 00",
    email="musterbergen@arbeitsagentur.example",
    bank="Bundesbank Muster",
    iban=_iban("76000000", "76001900"),
    style="band",
    accent=(160, 20, 35),
)
H_UK_X = Org(
    name="Unfallkasse Musterland",
    kind="authority",
    street="Postfach 11 22",
    postcode="35001",
    city="Musterbergen",
    head=("Gesetzliche Unfallversicherung (fiktiv)",),
    phone="06421 4040-0",
    email="post@unfallkasse-musterland.example",
    bank="Musterbank",
    iban=_iban("53350000", "4040000"),
    style="logo",
    accent=(0, 90, 70),
    monogram="UK",
    legal=("Körperschaft des öffentlichen Rechts",),
)
H_RV_X = Org(
    name="Muster-Rentenversicherung Nordwest",
    kind="authority",
    street="Rentenweg 1",
    postcode="26121",
    city="Beispielburg",
    head=("Gesetzliche Rentenversicherung (fiktiv)", "Abteilung Rehabilitation"),
    phone="Servicetelefon 0800 1000 490",
    email="reha@muster-rv-nordwest.example",
    style="band",
    accent=(0, 70, 130),
)

# fines (OWiG)
H_BG_TH = Org(
    name="Landratsamt Musterrode – Bußgeldstelle",
    kind="authority",
    street="Anger 2",
    postcode="99084",
    city="Musterrode",
    region="TH",
    head=("Freistaat Thüringen", "Bußgeldstelle des Landkreises"),
    phone="0361 655-0",
    email="bussgeld@lra-musterrode.example",
    bank="Sparkasse Musterrode",
    iban=_iban("82051000", "655100"),
    style="authority",
    accent=(150, 25, 35),
)
H_BG_X = Org(
    name="Regierungspräsidium Musterbergen – Zentrale Bußgeldstelle",
    kind="authority",
    street="Postfach 50 50",
    postcode="35004",
    city="Musterbergen",
    phone="06421 5050-0",
    email="zbs@rp-musterbergen.example",
    bank="Musterbank",
    iban=_iban("53350000", "505050"),
    style="minimal",
    accent=(40, 60, 100),
)
H_BG_MV = Org(
    name="Landkreis Beispielmünde – Bußgeldbehörde",
    kind="authority",
    street="Kreishaus, Ostseeallee 3",
    postcode="18055",
    city="Beispielmünde",
    region="MV",
    head=("Land Mecklenburg-Vorpommern · Der Landrat", "Straßenverkehrsamt"),
    phone="0381 403-0",
    email="bussgeld@lk-beispielmuende.example",
    bank="Ostseesparkasse Muster",
    iban=_iban("13050000", "403000"),
    style="band",
    accent=(0, 60, 100),
)
H_BG_RP = Org(
    name="Kreisverwaltung Musterweiler – Bußgeldstelle",
    kind="authority",
    street="Kurfürstenstraße 16",
    postcode="54470",
    city="Musterweiler",
    region="RP",
    head=("Land Rheinland-Pfalz · Kreisverwaltung Musterweiler",),
    phone="06531 84-0",
    email="bussgeldstelle@kv-musterweiler.example",
    bank="Kreissparkasse Musterweiler",
    iban=_iban("58751230", "840000"),
    style="logo",
    accent=(100, 30, 60),
    monogram="KV",
)


# --------------------------------------------------------------------------------------------------
# holdout2 split (variants G, H and the holdout2 adversarial letters): new senders and recipients,
# none of them shared with the dev, test or holdout letters
# --------------------------------------------------------------------------------------------------

Q_TH = Person("Konrad Musterlein", "Am Rosengarten 7", "07745", "Musterjena")
Q_BB = Person("Paulina Beispielwitz", "Havelufer 12", "14469", "Musterpotsdam")
Q_SH = Person("Hauke Musterjensen", "Kiefernstieg 5", "24939", "Musterflens")
Q_BW = Person("Selin Beispielbauer", "Rebenweg 18", "79104", "Musterfreiburg")
Q_NW = Person("Dariusz Musterski", "Hüttenstraße 27", "44787", "Beispielbochum")
Q_HH = Person("Thore Mustermöller", "Fleetstieg 9", "22041", "Hamburg")
Q_BE = Person("Zeynep Musterkaya", "Spreebogenweg 12", "10557", "Berlin")
Q_HE = Person("Elias Beispielhofer", "Uferweg 6", "60311", "Musterfurt am Main")
Q_SN = Person("Henriette Musterlich", "Elbblick 3", "01067", "Beispieldresden")
Q_ST = Person("Ronja Mustergrund", "Saaleweg 14", "06108", "Musterhalle")
Q_HB = Person("Jasper Beispielhorst", "Weserstieg 22", "28199", "Bremen")
Q_GEN = Person("Nele Musterkamp", "Ahornring 9", "49076", "Musterosna")
Q_GEN2 = Person("Ruben Beispielgaard", "Wiesengrund 21", "21335", "Musterlüne")
Q_EN = Person("Grace Mensah", "Ahornring 9", "49076", "Musterosna", country="Germany")
Q_EN2 = Person("Tomás Herrera", "Fleetstieg 9", "22041", "Hamburg", country="GERMANY")
Q_RECIPIENT_IBAN = _iban("26550105", "71830046")

# tax offices (AO)
Q_FA_TH = Org(
    name="Finanzamt Musterjena",
    kind="tax_office",
    street="Steuerweg 4",
    postcode="07743",
    city="Musterjena",
    region="TH",
    head=("Freistaat Thüringen", "Thüringer Steuerverwaltung"),
    phone="03641 378-0",
    email="poststelle@fa-musterjena.example",
    bank="Landesbank Muster-Thüringen",
    iban=_iban("82050000", "3780001"),
    bic="MUTHDEFFXXX",
    style="minimal",
    accent=(20, 60, 120),
    hours=("Info- und Annahmestelle:", "Mo, Di, Do 8–15 Uhr", "Mi 8–17:30, Fr 8–12 Uhr"),
)
Q_FA_X = Org(
    name="Finanzamt Beispielhain",
    kind="tax_office",
    street="Am Lindenhain 30",
    postcode="49080",
    city="Beispielhain",
    head=("Steuerverwaltung", "Veranlagung Arbeitnehmerbezirke"),
    phone="0541 3540-0",
    email="poststelle@fa-beispielhain.example",
    bank="Musterbank Nordwest",
    iban=_iban("26550000", "3540000"),
    style="band",
    accent=(40, 70, 40),
)
Q_FA_BB = Org(
    name="Finanzamt Musterpotsdam",
    kind="tax_office",
    street="Havelallee 11",
    postcode="14473",
    city="Musterpotsdam",
    region="BB",
    head=("Land Brandenburg · Steuerverwaltung",),
    phone="0331 287-0",
    email="poststelle.musterpotsdam@finanzamt.example",
    bank="Brandenburgische Musterkasse",
    iban=_iban("16050000", "2870000"),
    bic="BRMUDE21XXX",
    style="authority",
    accent=(150, 20, 40),
)
Q_FA_SH = Org(
    name="Finanzamt Musterflens",
    kind="tax_office",
    street="Hafendamm 15",
    postcode="24937",
    city="Musterflens",
    region="SH",
    head=("Land Schleswig-Holstein · Steuerverwaltung",),
    phone="0461 813-0",
    email="poststelle@fa-musterflens.example",
    bank="Förde-Musterbank",
    iban=_iban("21550000", "8130000"),
    style="logo",
    accent=(0, 70, 110),
    monogram="FA",
    hours=("Servicezentrum:", "Mo–Mi 7:30–15:30", "Do 7:30–17, Fr 7:30–12 Uhr"),
)
Q_FA_X2 = Org(
    name="Finanzamt Musterwalde",
    kind="tax_office",
    street="Forsthausweg 2",
    postcode="21339",
    city="Musterlüne",
    head=("Steuerverwaltung",),
    phone="04131 302-0",
    email="poststelle@fa-musterwalde.example",
    bank="Musterbank Lüne",
    iban=_iban("24050000", "3020000"),
    style="minimal",
    accent=(70, 50, 100),
)

# municipal authorities (Land VwVfG; Länder with the verified 4-day rule, posted after it took effect)
Q_STADT_BW = Org(
    name="Stadt Musterfreiburg",
    kind="authority",
    street="Rathausplatz 2–4",
    postcode="79098",
    city="Musterfreiburg",
    region="BW",
    head=("Land Baden-Württemberg", "Garten- und Tiefbauamt – Baumschutz"),
    phone="0761 201-0",
    email="baumschutz@musterfreiburg.example",
    bank="Sparkasse Muster-Breisgau",
    iban=_iban("68050101", "2010000"),
    style="band",
    accent=(30, 90, 50),
)
Q_AMT_SH = Org(
    name="Amt Musterflens-Land",
    kind="authority",
    street="Amtsweg 1",
    postcode="24983",
    city="Beispielhusby",
    region="SH",
    head=("Land Schleswig-Holstein · Der Amtsvorsteher", "Ordnungsamt"),
    phone="04608 609-0",
    email="ordnungsamt@amt-musterflens-land.example",
    bank="Nord-Ostsee Musterbank",
    iban=_iban("21750000", "6090000"),
    style="authority",
    accent=(0, 60, 120),
)
Q_STADT_NW = Org(
    name="Stadt Beispielbochum",
    kind="authority",
    street="Rathausallee 5",
    postcode="44777",
    city="Beispielbochum",
    region="NW",
    head=("Land Nordrhein-Westfalen · Der Oberbürgermeister", "Bauordnungsamt"),
    phone="0234 910-0",
    email="bauordnung@beispielbochum.example",
    bank="Sparkasse Beispielbochum",
    iban=_iban("43050001", "9100000"),
    style="logo",
    accent=(0, 80, 130),
    monogram="BO",
)
Q_BA_HH = Org(
    name="Bezirksamt Musterwandsbek",
    kind="authority",
    street="Am Musterschloss 12",
    postcode="22041",
    city="Hamburg",
    region="HH",
    head=("Freie und Hansestadt Hamburg", "Fachamt Management des öffentlichen Raumes"),
    phone="040 42881-0",
    email="sondernutzung@musterwandsbek.hamburg.example",
    bank="Hamburger Musterkasse",
    iban=_iban("20050000", "4288100"),
    style="minimal",
    accent=(170, 20, 30),
)

# social law (SGB X; Wohngeld and Unterhaltsvorschuss are social benefits under § 68 SGB I, so SGB X applies)
Q_IKK = Org(
    name="IKK Mustertal",
    kind="health_insurer",
    street="Handwerkerplatz 3",
    postcode="57072",
    city="Mustertal",
    head=("Die Innungskrankenkasse (Musterausgabe)", "Leistungszentrum Häusliche Versorgung"),
    phone="0800 455 4500",
    email="leistung@ikk-mustertal.example",
    web="www.ikk-mustertal.example",
    bank="Musterbank",
    iban=_iban("46050000", "4554500"),
    style="band",
    accent=(0, 95, 70),
    legal=("Körperschaft des öffentlichen Rechts",),
)
Q_RV = Org(
    name="Rentenversicherung Beispiel-Mitte",
    kind="authority",
    street="Am Versorgungspark 8",
    postcode="34117",
    city="Beispielkassel",
    head=("Gesetzliche Rentenversicherung (fiktiv)", "Abteilung Rente – Erwerbsminderung"),
    phone="Servicetelefon 0800 6000 410",
    email="rente@rv-beispiel-mitte.example",
    style="logo",
    accent=(0, 70, 140),
    monogram="RV",
    legal=("Körperschaft des öffentlichen Rechts",),
)
Q_BA_BE = Org(
    name="Bezirksamt Beispiel-Spreeufer von Berlin",
    kind="authority",
    street="Uferstraße 40",
    postcode="10551",
    city="Berlin",
    region="BE",
    head=("Land Berlin", "Amt für Bürgerdienste – Wohngeldstelle"),
    phone="030 90298-0",
    email="wohngeld@ba-beispiel-spreeufer.berlin.example",
    bank="Berliner Musterkasse",
    iban=_iban("10050000", "9029800"),
    style="authority",
    accent=(160, 20, 30),
)
Q_JA_HE = Org(
    name="Landkreis Musterhöhe – Jugendamt",
    kind="authority",
    street="Kreishausstraße 1",
    postcode="61169",
    city="Beispielberg",
    region="HE",
    head=("Land Hessen · Der Kreisausschuss des Landkreises Musterhöhe", "Unterhaltsvorschusskasse"),
    phone="06031 83-0",
    email="uvg@lk-musterhoehe.example",
    bank="Sparkasse Musterhöhe",
    iban=_iban("51850079", "830000"),
    style="band",
    accent=(110, 30, 70),
)

# fines (OWiG)
Q_BG_SN = Org(
    name="Landkreis Beispielelbe – Bußgeldstelle",
    kind="authority",
    street="Schloßhof 2",
    postcode="01796",
    city="Musterpirna",
    region="SN",
    head=("Freistaat Sachsen · Landratsamt Beispielelbe", "Straßenverkehrsamt – Bußgeldstelle"),
    phone="03501 515-0",
    email="bussgeld@lra-beispielelbe.example",
    bank="Ostsächsische Musterkasse",
    iban=_iban("85050300", "5150000"),
    style="authority",
    accent=(0, 100, 60),
)
Q_BG_X = Org(
    name="Landesverwaltungsamt Musterhöhe – Zentrale Bußgeldstelle",
    kind="authority",
    street="Postfach 12 12",
    postcode="34001",
    city="Beispielkassel",
    phone="0561 1060-0",
    email="zbs@lva-musterhoehe.example",
    bank="Musterbank",
    iban=_iban("52050000", "10600"),
    style="band",
    accent=(50, 50, 90),
)
Q_BG_ST = Org(
    name="Stadt Musterhalle – Bußgeldstelle",
    kind="authority",
    street="Marktplatz 1",
    postcode="06108",
    city="Musterhalle",
    region="ST",
    head=("Land Sachsen-Anhalt · Stadt Musterhalle", "Fachbereich Sicherheit – Bußgeldstelle"),
    phone="0345 221-0",
    email="bussgeldstelle@musterhalle.example",
    bank="Saalesparkasse Muster",
    iban=_iban("80053762", "2210000"),
    style="logo",
    accent=(120, 20, 40),
    monogram="HA",
)
Q_BG_HB = Org(
    name="Ordnungsamt Weserstadt – Bußgeldstelle",
    kind="authority",
    street="Ordnungsweg 21",
    postcode="28207",
    city="Bremen",
    region="HB",
    head=("Freie Hansestadt Bremen", "Verkehrsordnungswidrigkeiten"),
    phone="0421 361-1",
    email="bussgeld@ordnungsamt-weserstadt.bremen.example",
    bank="Bremer Musterkasse",
    iban=_iban("29050101", "3611000"),
    style="minimal",
    accent=(160, 20, 30),
)

# year boundary (AO: Finanzamt, Familienkasse for Kindergeld under the EStG; SGB X: Versorgungsamt, Berufsgenossenschaft)
Q_FK = Org(
    name="Familienkasse Beispiel-Nord",
    kind="authority",
    street="Kindergeldweg 5",
    postcode="21337",
    city="Musterlüne",
    head=("Familienkasse (Musterausgabe)", "Kindergeld nach dem Einkommensteuergesetz"),
    phone="0800 4 5555 30",
    email="familienkasse-beispiel-nord@arbeitsagentur.example",
    bank="Bundesbank Muster",
    iban=_iban("76000000", "76005530"),
    style="band",
    accent=(140, 20, 30),
)
Q_VA = Org(
    name="Versorgungsamt Beispielfeld",
    kind="authority",
    street="Am Versorgungsamt 1",
    postcode="49074",
    city="Musterosna",
    head=("Feststellungen nach dem Schwerbehindertenrecht (SGB IX)",),
    phone="0541 314-0",
    email="sb-recht@versorgungsamt-beispielfeld.example",
    style="authority",
    accent=(60, 70, 90),
)
Q_BGN = Org(
    name="Beispiel-Berufsgenossenschaft Bau und Holz",
    kind="authority",
    street="Unfallweg 4",
    postcode="30159",
    city="Musterhannover",
    head=("Gesetzliche Unfallversicherung (fiktiv)", "Bezirksverwaltung Nord"),
    phone="0511 9870-0",
    email="bv-nord@bg-bau-holz-beispiel.example",
    bank="Musterbank",
    iban=_iban("25050000", "98700"),
    style="logo",
    accent=(0, 90, 60),
    monogram="BG",
    legal=("Körperschaft des öffentlichen Rechts",),
)
