"""The fictional senders of Sam Rivera's mail: letterhead style, colours, contact data and banks.

Every name, address, phone number, register number and account is invented. Postcodes use the
``1234x`` "Musterstadt" range, phone numbers start with ``0123``, websites end in ``.example``.
IBANs, creditor IDs and VAT IDs carry valid check digits (see :mod:`samplelife.ids`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from samplelife.ids import creditor_id, de_iban, format_iban, ust_idnr

RGB = tuple[int, int, int]
HeaderStyle = Literal["band", "classic", "modern", "sidebar", "authority", "plain", "centered", "cheap"]
LogoKind = Literal[
    "house",
    "signal",
    "pulse",
    "bolt",
    "shield",
    "cross",
    "wave",
    "crest",
    "book",
    "grid",
    "hexagon",
    "bag",
    "tram",
    "star",
    "bank",
    "tooth",
    "scam",
    "none",
]


@dataclass(frozen=True)
class Bank:
    """A fictional bank (name, Bankleitzahl, BIC)."""

    name: str
    blz: str
    bic: str

    def iban(self, account: str) -> str:
        """IBAN for a 10-digit account number at this bank."""
        return de_iban(self.blz, account)


SPARKASSE = Bank("Sparkasse Musterstadt", "12345600", "MUSKDEM1XXX")
MUSTERBANK = Bank("Musterbank eG", "12346700", "MUBKDEM1XXX")
KREDITBANK = Bank("Beispiel Kreditbank AG", "12347800", "BEKRDEM1XXX")
LANDESBANK = Bank("Beispiel Landesbank", "12348900", "BLBADEM1XXX")


@dataclass(frozen=True)
class Account:
    """A payee account printed on a letter."""

    bank: Bank
    iban: str

    @property
    def iban_pretty(self) -> str:
        """IBAN grouped in blocks of four."""
        return format_iban(self.iban)


def account(bank: Bank, number: str) -> Account:
    """Shorthand for an :class:`Account` with a computed IBAN."""
    return Account(bank, bank.iban(number))


@dataclass(frozen=True)
class Org:
    """A sender and everything its letterhead and footer need."""

    key: str
    name: str
    wordmark: tuple[str, str]
    street: str
    city: str
    color: RGB
    accent: RGB
    style: HeaderStyle
    logo: LogoKind
    phone: str = ""
    email: str = ""
    web: str = ""
    tagline: str = ""
    dept: tuple[str, ...] = ()
    footer: tuple[tuple[str, ...], ...] = ()
    account: Account | None = None
    ink: RGB | None = None
    return_line: str = ""
    body_size: float = 9.0

    @property
    def text_color(self) -> RGB:
        """Colour for headings on white paper (``ink`` for light brand colours)."""
        return self.ink or self.color

    @property
    def sender_line(self) -> str:
        """The small return address above the address window."""
        return self.return_line or f"{self.name} · {self.street} · {self.city}"

    def with_dept(self, *dept: str, return_line: str) -> Org:
        """Same organisation, another department with its own return address."""
        return replace(self, dept=dept, return_line=return_line)


def _bank_lines(acc: Account) -> tuple[str, ...]:
    return (acc.bank.name, f"IBAN {acc.iban_pretty}", f"BIC {acc.bank.bic}")


# --------------------------------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------------------------------

ACC_WOHNBAU = account(SPARKASSE, "0004455660")
ACC_STADTWERKE = account(SPARKASSE, "0000400100")
ACC_STADTKASSE = account(SPARKASSE, "0000100017")
ACC_HOCHSCHULE = account(SPARKASSE, "0007700220")
ACC_MVB = account(SPARKASSE, "0000630000")
ACC_BKK = account(SPARKASSE, "0006060000")
ACC_FITWELL = account(MUSTERBANK, "0029900150")
ACC_MUSTERTECH = account(MUSTERBANK, "0042420000")
ACC_TECHMARKT = account(KREDITBANK, "0048213000")
ACC_VERSICHERUNG = account(KREDITBANK, "0059900000")
ACC_FUNKNETZ = account(KREDITBANK, "0088213400")
ACC_SCHOLARSHIP = account(KREDITBANK, "0031702026")
ACC_BEITRAGSSERVICE = account(LANDESBANK, "0055081836")
ACC_FINANZAMT = account(LANDESBANK, "0012300010")

CI_FUNKNETZ = creditor_id("DE", "00000204170")
CI_FITWELL = creditor_id("DE", "00000104570")
CI_STADTWERKE = creditor_id("DE", "00000401239")
CI_MVB = creditor_id("DE", "00000330471")
CI_VERSICHERUNG = creditor_id("DE", "00000447122")
CI_BKK = creditor_id("DE", "00000606017")

VAT_FUNKNETZ = ust_idnr("20417551")
VAT_FITWELL = ust_idnr("31045782")
VAT_STADTWERKE = ust_idnr("40012398")
VAT_MUSTERTECH = ust_idnr("42424207")
VAT_TECHMARKT = ust_idnr("48213377")
VAT_MUSTERBANK = ust_idnr("12346701")
VAT_MVB = ust_idnr("33047196")

# --------------------------------------------------------------------------------------------------
# Organisations
# --------------------------------------------------------------------------------------------------

FUNKNETZ = Org(
    key="funknetz",
    name="FunkNetz Mobil GmbH",
    wordmark=("FunkNetz", "mobil"),
    street="Wellenweg 7",
    city="12351 Beispielhausen",
    color=(92, 35, 148),
    accent=(0, 184, 212),
    style="band",
    logo="signal",
    phone="0123 2244660",
    email="service@funknetz-mobil.example",
    web="www.funknetz-mobil.example",
    tagline="Einfach. Verbunden.",
    footer=(
        (
            "FunkNetz Mobil GmbH",
            "Wellenweg 7 · 12351 Beispielhausen",
            "Kundenservice 0123 2244660",
            "www.funknetz-mobil.example",
        ),
        (
            "Geschäftsführung:",
            "Dr. Lena Exempel, Marco Muster",
            "Sitz: Beispielhausen",
            "Amtsgericht Beispielhausen HRB 20417",
        ),
        (
            f"USt-IdNr. {VAT_FUNKNETZ}",
            f"Gläubiger-ID {CI_FUNKNETZ}",
            "Hinweise zum Datenschutz:",
            "funknetz-mobil.example/datenschutz",
        ),
        _bank_lines(ACC_FUNKNETZ),
    ),
    account=ACC_FUNKNETZ,
    return_line="FunkNetz Mobil GmbH · Postfach 20 41 70 · 12351 Beispielhausen",
    body_size=9.0,
)

FITWELL = Org(
    key="fitwell",
    name="FitWell Studios GmbH",
    wordmark=("FitWell", "STUDIOS"),
    street="Sportparkstraße 3",
    city="12345 Musterstadt",
    color=(236, 102, 16),
    accent=(38, 38, 44),
    style="band",
    logo="pulse",
    phone="0123 889900",
    email="hallo@fitwell-studios.example",
    web="www.fitwell-studios.example",
    tagline="Dein Studio in Musterstadt-Mitte",
    footer=(
        (
            "FitWell Studios GmbH",
            "Sportparkstraße 3 · 12345 Musterstadt",
            "Telefon 0123 889900",
            "hallo@fitwell-studios.example",
        ),
        (
            "Geschäftsführer: Tim Beispiel",
            "Sitz: Musterstadt",
            "Amtsgericht Musterstadt HRB 31045",
            f"USt-IdNr. {VAT_FITWELL}",
        ),
        (*_bank_lines(ACC_FITWELL), f"Gläubiger-ID {CI_FITWELL}"),
    ),
    account=ACC_FITWELL,
    ink=(196, 78, 0),
    body_size=8.8,
)

WOHNBAU = Org(
    key="wohnbau",
    name="Wohnbau Musterstadt eG",
    wordmark=("WOHNBAU", "Musterstadt eG"),
    street="Genossenschaftsstraße 10",
    city="12345 Musterstadt",
    color=(0, 104, 71),
    accent=(132, 189, 0),
    style="classic",
    logo="house",
    phone="0123 45678-0",
    email="vermietung@wohnbau-musterstadt.example",
    web="www.wohnbau-musterstadt.example",
    tagline="Gut wohnen seit 1921",
    footer=(
        (
            "Wohnbau Musterstadt eG",
            "Genossenschaftsstraße 10",
            "12345 Musterstadt",
            "www.wohnbau-musterstadt.example",
        ),
        (
            "Vorstand: Petra Beispiel (Vors.),",
            "Jonas Muster",
            "Vorsitzender des Aufsichtsrats:",
            "Dr. Klaus Exempel",
        ),
        (
            "Sitz der Genossenschaft: Musterstadt",
            "Amtsgericht Musterstadt GnR 123",
            "Geschäftszeiten:",
            "Mo–Do 8–16 Uhr, Fr 8–12 Uhr",
        ),
        _bank_lines(ACC_WOHNBAU),
    ),
    account=ACC_WOHNBAU,
    body_size=8.9,
)

STADTWERKE = Org(
    key="stadtwerke",
    name="Stadtwerke Musterstadt GmbH",
    wordmark=("Stadtwerke", "Musterstadt"),
    street="Energieplatz 1",
    city="12345 Musterstadt",
    color=(0, 84, 159),
    accent=(255, 184, 28),
    style="modern",
    logo="bolt",
    phone="0123 5550-100",
    email="kundenservice@stadtwerke-musterstadt.example",
    web="www.stadtwerke-musterstadt.example",
    tagline="Energie aus Ihrer Stadt",
    footer=(
        (
            "Stadtwerke Musterstadt GmbH",
            "Energieplatz 1 · 12345 Musterstadt",
            "Kundenzentrum: Mo–Fr 8–18 Uhr",
            "www.stadtwerke-musterstadt.example",
        ),
        (
            "Geschäftsführung: Dipl.-Ing. Frank Muster",
            "Vorsitzende des Aufsichtsrats:",
            "Bürgermeisterin Eva Beispiel",
            "Sitz: Musterstadt · Amtsgericht Musterstadt HRB 4711",
        ),
        (
            f"USt-IdNr. {VAT_STADTWERKE}",
            f"Gläubiger-ID {CI_STADTWERKE}",
            "Hinweise zur Verbraucherschlichtung:",
            "stadtwerke-musterstadt.example/verbraucherrechte",
        ),
        _bank_lines(ACC_STADTWERKE),
    ),
    account=ACC_STADTWERKE,
)

VERSICHERUNG = Org(
    key="versicherung",
    name="Muster Versicherung AG",
    wordmark=("Muster", "Versicherung"),
    street="Versicherungsring 20",
    city="12352 Beispielstadt",
    color=(22, 45, 95),
    accent=(200, 30, 45),
    style="classic",
    logo="shield",
    phone="0123 7070-0",
    email="service@muster-versicherung.example",
    web="www.muster-versicherung.example",
    tagline="Sicher. Seit 1887.",
    footer=(
        (
            "Muster Versicherung AG",
            "Versicherungsring 20 · 12352 Beispielstadt",
            "Telefon 0123 7070-0",
            "www.muster-versicherung.example",
        ),
        (
            "Vorstand: Dr. Carla Muster (Vors.),",
            "Henrik Beispiel, Sabine Exempel",
            "Vorsitzender des Aufsichtsrats:",
            "Prof. Dr. Otto Beispiel",
        ),
        (
            "Sitz: Beispielstadt",
            "Amtsgericht Beispielstadt HRB 1887",
            "Versicherungsteuer-Nr. 812/V/4471",
            f"Gläubiger-ID {CI_VERSICHERUNG}",
        ),
        _bank_lines(ACC_VERSICHERUNG),
    ),
    account=ACC_VERSICHERUNG,
    body_size=9.0,
)

BKK = Org(
    key="bkk",
    name="Muster BKK",
    wordmark=("Muster BKK", ""),
    street="Kassenstraße 3",
    city="12346 Musterstadt",
    color=(0, 128, 118),
    accent=(150, 200, 40),
    style="sidebar",
    logo="cross",
    phone="0123 6060-0",
    email="service@muster-bkk.example",
    web="www.muster-bkk.example",
    tagline="Die Betriebskrankenkasse für Musterstadt",
    footer=(
        (
            "Muster BKK · Körperschaft des öffentlichen Rechts",
            "Kassenstraße 3 · 12346 Musterstadt",
            "Servicetelefon 0123 6060-0 (Mo–Fr 8–18 Uhr)",
        ),
        ("Vorstand: Andrea Beispiel", "Verwaltungsratsvorsitzender: Peter Muster", f"Gläubiger-ID {CI_BKK}"),
        _bank_lines(ACC_BKK),
    ),
    account=ACC_BKK,
)

BEITRAGSSERVICE = Org(
    key="beitragsservice",
    name="Beitragsservice Musterstadt",
    wordmark=("Beitragsservice", "Musterstadt"),
    street="Postfach 12 34 56",
    city="12399 Musterstadt",
    color=(0, 91, 150),
    accent=(126, 170, 205),
    style="plain",
    logo="wave",
    phone="0123 9900-500",
    email="kontakt@rundfunkbeitrag-musterstadt.example",
    web="www.rundfunkbeitrag-musterstadt.example",
    tagline="Rundfunkbeitrag",
    footer=(
        ("Beitragsservice Musterstadt", "Einrichtung der Rundfunkanstalten", "12399 Musterstadt"),
        ("Service: 0123 9900-500", "Mo–Fr 7–19 Uhr", "www.rundfunkbeitrag-musterstadt.example"),
        _bank_lines(ACC_BEITRAGSSERVICE),
    ),
    account=ACC_BEITRAGSSERVICE,
    return_line="Beitragsservice Musterstadt · 12399 Musterstadt",
    body_size=9.0,
)

_STADT_FOOTER = (
    ("Stadt Musterstadt", "Musterplatz 1 · 12345 Musterstadt", "www.musterstadt.example"),
    ("Barrierefreier Zugang", "Eingang Rathausgasse", "Bus/Tram: Haltestelle Rathaus"),
    ("Stadtkasse Musterstadt", *_bank_lines(ACC_STADTKASSE)),
)

STADT = Org(
    key="stadt",
    name="Stadt Musterstadt",
    wordmark=("Stadt Musterstadt", "Der Oberbürgermeister"),
    street="Musterplatz 1",
    city="12345 Musterstadt",
    color=(158, 27, 38),
    accent=(212, 175, 55),
    style="authority",
    logo="crest",
    web="www.musterstadt.example",
    footer=_STADT_FOOTER,
    account=ACC_STADTKASSE,
    body_size=9.2,
)

STADT_ABH = STADT.with_dept(
    "Amt für Migration und Integration",
    "Ausländerbehörde",
    return_line="Stadt Musterstadt · Ausländerbehörde · Musterplatz 1 · 12345 Musterstadt",
)
STADT_ORDNUNGSAMT = STADT.with_dept(
    "Ordnungsamt",
    "Verkehrsüberwachung – Bußgeldstelle",
    return_line="Stadt Musterstadt · Ordnungsamt · Postfach 10 01 00 · 12345 Musterstadt",
)

BIBLIOTHEK = Org(
    key="bibliothek",
    name="Stadtbibliothek Musterstadt",
    wordmark=("Stadtbibliothek", "Musterstadt"),
    street="Bibliotheksplatz 2",
    city="12345 Musterstadt",
    color=(104, 46, 140),
    accent=(240, 170, 0),
    style="sidebar",
    logo="book",
    phone="0123 400-7700",
    email="stadtbibliothek@musterstadt.example",
    web="www.stadtbibliothek-musterstadt.example",
    footer=(
        ("Stadtbibliothek Musterstadt", "Bibliotheksplatz 2 · 12345 Musterstadt", "Telefon 0123 400-7700"),
        ("Öffnungszeiten:", "Di–Fr 10–19 Uhr, Sa 10–14 Uhr", "Rückgabebox rund um die Uhr"),
        ("Stadtkasse Musterstadt", *_bank_lines(ACC_STADTKASSE)[1:]),
    ),
    account=ACC_STADTKASSE,
    body_size=9.0,
)

HOCHSCHULE = Org(
    key="hochschule",
    name="Hochschule Musterstadt",
    wordmark=("Hochschule", "Musterstadt"),
    street="Hochschulallee 1",
    city="12347 Musterstadt",
    color=(0, 70, 130),
    accent=(0, 160, 205),
    style="modern",
    logo="grid",
    phone="0123 7788-2210",
    email="studierendenservice@hs-musterstadt.example",
    web="www.hs-musterstadt.example",
    tagline="University of Applied Sciences",
    dept=("Studierendenservice", "Studierendensekretariat"),
    footer=(
        ("Hochschule Musterstadt", "Hochschulallee 1 · 12347 Musterstadt", "www.hs-musterstadt.example"),
        (
            "Studierendenservice, Gebäude A, Raum A 0.12",
            "Mo, Di, Do 9–12 Uhr, Mi 13–16 Uhr",
            "Telefon 0123 7788-2210",
        ),
        _bank_lines(ACC_HOCHSCHULE),
    ),
    account=ACC_HOCHSCHULE,
    body_size=9.0,
)

MUSTERTECH = Org(
    key="mustertech",
    name="Muster Tech GmbH",
    wordmark=("muster", "tech"),
    street="Innovationsweg 42",
    city="12345 Musterstadt",
    color=(24, 34, 56),
    accent=(0, 168, 210),
    style="modern",
    logo="hexagon",
    phone="0123 4242-0",
    email="people@mustertech.example",
    web="www.mustertech.example",
    tagline="Data & Software Engineering",
    footer=(
        ("Muster Tech GmbH", "Innovationsweg 42 · 12345 Musterstadt", "www.mustertech.example"),
        ("Geschäftsführerin: Dr. Miriam Beispiel", "Sitz: Musterstadt", "Amtsgericht Musterstadt HRB 42424"),
        (f"USt-IdNr. {VAT_MUSTERTECH}", *_bank_lines(ACC_MUSTERTECH)[:2]),
    ),
    account=ACC_MUSTERTECH,
    body_size=9.0,
)

TECHMARKT = Org(
    key="techmarkt",
    name="TechMarkt Online GmbH",
    wordmark=("TechMarkt", "online"),
    street="Handelsstraße 88",
    city="12353 Beispielburg",
    color=(210, 32, 39),
    accent=(255, 205, 0),
    style="band",
    logo="bag",
    phone="0123 6655440",
    email="kundenservice@techmarkt-online.example",
    web="www.techmarkt-online.example",
    tagline="Technik. Morgen da.",
    footer=(
        (
            "TechMarkt Online GmbH",
            "Handelsstraße 88 · 12353 Beispielburg",
            "kundenservice@techmarkt-online.example",
        ),
        (
            "Geschäftsführer: Jan Exempel, Aylin Muster",
            "Sitz: Beispielburg",
            "Amtsgericht Beispielburg HRB 48213",
        ),
        (f"USt-IdNr. {VAT_TECHMARKT}", "WEEE-Reg.-Nr. DE 00000000", "Steuernummer 212/5812/0048"),
        _bank_lines(ACC_TECHMARKT),
    ),
    account=ACC_TECHMARKT,
    ink=(190, 25, 32),
    body_size=8.8,
)

MVB = Org(
    key="mvb",
    name="Musterstadt Verkehrsbetriebe GmbH",
    wordmark=("MVB", "Musterstadt Verkehrsbetriebe"),
    street="Bahnhofstraße 20",
    city="12345 Musterstadt",
    color=(255, 204, 0),
    accent=(35, 35, 35),
    style="modern",
    logo="tram",
    phone="0123 6300-63",
    email="abo@mvb-musterstadt.example",
    web="www.mvb-musterstadt.example",
    tagline="Bus & Tram für Musterstadt",
    footer=(
        (
            "Musterstadt Verkehrsbetriebe GmbH (MVB)",
            "Bahnhofstraße 20 · 12345 Musterstadt",
            "Abo-Service 0123 6300-63",
        ),
        (
            "Geschäftsführung: Olaf Beispiel",
            "Sitz: Musterstadt · Amtsgericht Musterstadt HRB 3304",
            f"USt-IdNr. {VAT_MVB}",
        ),
        (*_bank_lines(ACC_MVB), f"Gläubiger-ID {CI_MVB}"),
    ),
    account=ACC_MVB,
    ink=(35, 35, 35),
    return_line="MVB Abo-Service · Bahnhofstraße 20 · 12345 Musterstadt",
)

SCHOLARSHIP = Org(
    key="scholarship",
    name="Global Talent Scholarship Foundation",
    wordmark=("GLOBAL TALENT", "SCHOLARSHIP FOUNDATION"),
    street="Beispielallee 20",
    city="12350 Berlin",
    color=(122, 24, 56),
    accent=(186, 146, 62),
    style="centered",
    logo="star",
    phone="+49 123 555 0317",
    email="scholars@globaltalent-scholarship.example",
    web="www.globaltalent-scholarship.example",
    footer=(
        (
            "Global Talent Scholarship Foundation",
            "gemeinnützige Stiftung bürgerlichen Rechts",
            "Beispielallee 20 · 12350 Berlin · Germany",
        ),
        (
            "Board: Prof. Dr. Amara Beispiel (Chair)",
            "Programme Director: Dr. Helen Example",
            "Foundation register Berlin 3/GT-2011",
        ),
    ),
    account=ACC_SCHOLARSHIP,
    return_line="Global Talent Scholarship Foundation · Beispielallee 20 · 12350 Berlin",
    body_size=9.4,
)

MUSTERBANK_ORG = Org(
    key="musterbank",
    name="Musterbank eG",
    wordmark=("Musterbank", "eG"),
    street="Bankplatz 1",
    city="12345 Musterstadt",
    color=(0, 92, 110),
    accent=(225, 150, 30),
    style="classic",
    logo="bank",
    phone="0123 4000-0",
    email="info@musterbank.example",
    web="www.musterbank.example",
    tagline="Ihre Bank in Musterstadt",
    footer=(
        ("Musterbank eG", "Bankplatz 1 · 12345 Musterstadt", "Telefon 0123 4000-0 · www.musterbank.example"),
        (
            "Vorstand: Stefan Muster (Vors.), Leonie Exempel",
            "Vorsitzende des Aufsichtsrats: Birgit Beispiel",
            "Sitz: Musterstadt · Amtsgericht Musterstadt GnR 88",
        ),
        (f"BIC {MUSTERBANK.bic}", f"USt-IdNr. {VAT_MUSTERBANK}", "BLZ 123 467 00"),
    ),
    body_size=9.0,
)

FINANZAMT = Org(
    key="finanzamt",
    name="Finanzamt Musterstadt",
    wordmark=("Finanzamt Musterstadt", ""),
    street="Steuerplatz 1",
    city="12345 Musterstadt",
    color=(25, 25, 25),
    accent=(110, 110, 110),
    style="plain",
    logo="none",
    phone="0123 887-0",
    email="poststelle@fa-musterstadt.example",
    web="www.finanzamt-musterstadt.example",
    footer=(
        ("Finanzamt Musterstadt", "Steuerplatz 1 · 12345 Musterstadt", "Telefon 0123 887-0"),
        ("Öffnungszeiten Servicezentrum:", "Mo–Fr 8:30–12 Uhr, Do 13:30–17 Uhr", "und nach Vereinbarung"),
        ("Bankverbindung: Finanzkasse", f"{LANDESBANK.name}", f"IBAN {ACC_FINANZAMT.iban_pretty}"),
    ),
    account=ACC_FINANZAMT,
    return_line="Finanzamt Musterstadt · Steuerplatz 1 · 12345 Musterstadt",
    body_size=9.0,
)

DENTIST = Org(
    key="dentist",
    name="Zahnarztpraxis Dr. Anna Beispiel",
    wordmark=("Dr. Anna Beispiel", "Zahnärztin"),
    street="Lindenallee 8",
    city="12345 Musterstadt",
    color=(0, 140, 160),
    accent=(120, 200, 210),
    style="plain",
    logo="tooth",
    phone="0123 334455",
    web="www.zahnarzt-beispiel.example",
)

SCAM = Org(
    key="scam",
    name="Rundfunk-Beitragsservice – Zahlungszentrale",
    wordmark=("RUNDFUNK-BEITRAGSSERVICE", "Zahlungszentrale"),
    street="Postfach 4 41 10",
    city="12399 Musterstadt",
    color=(24, 78, 176),
    accent=(214, 0, 0),
    style="cheap",
    logo="scam",
    email="zahlung@rundfunk-beitragservice.example",
    return_line="Rundfunk Zahlungszentrale, Postfach 4 41 10, 12399 Musterstadt",
    body_size=9.8,
)
