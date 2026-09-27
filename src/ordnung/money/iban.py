"""What an IBAN says about itself: its country, whether it is well-formed, and its bank code.

Pure code, no I/O. Policy (ISO 13616 and the SWIFT IBAN registry):

* **As printed.** A leading ``IBAN``/``IBAN:`` label, spaces, dashes and dots are ignored, and so
  are invisible format characters that copying from a PDF or web page leaves behind (zero-width
  spaces, byte-order marks: Unicode category Cf).
* **Well-formed** means: letters and digits only, two letters for a country that issues IBANs
  (:data:`IBAN_COUNTRIES`, the full SWIFT registry), two check digits, that country's registered
  length, and the mod-97 checksum. Any other two letters (``US``, ``ZZ`` …) are not an IBAN, even
  when the checksum happens to add up; the country is then reported as unknown, never as a guess.
* **Bank code** — the national bank identifier (and branch code where the registry defines one) is
  cut out of the account part only for the countries listed with its position; elsewhere it is
  ``None`` rather than a guess. No bank *names*: that needs each country's bank directory.
* A well-formed IBAN says nothing about who owns the account; callers must say so (a scam can use a
  perfectly valid IBAN).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date

_NOISE = re.compile(r"[\s\-.]+")
_LABEL = re.compile(r"^\s*IBAN\s*:?", re.IGNORECASE)
_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")
MAX_LENGTH = 34
MIN_LENGTH = 15
#: What to do about an IBAN that is not well-formed (the app's scam warning and the check_iban tool).
INVALID_IBAN_ADVICE = (
    "It may be misprinted, misread or fake — compare it with the letter and ask the sender before paying."
)


@dataclass(frozen=True)
class IbanCountry:
    """One registry entry: the country's name, IBAN length and where its bank code sits.

    ``bank`` and ``branch`` are ``(start, end)`` offsets into the whole IBAN (country code included).
    """

    name: str
    length: int
    bank: tuple[int, int] | None = None
    bank_label: str = "Bank code"
    branch: tuple[int, int] | None = None
    branch_label: str = "Branch code"
    account: tuple[int, int] | None = None


#: Every country in the SWIFT IBAN registry (release checked 2026-09) with its IBAN length; the bank
#: and branch code positions for the countries whose format shows them and that German letters use.
#: Territories that use another country's IBAN (Guernsey, Jersey and the Isle of Man: GB; Åland: FI;
#: the French overseas departments and collectivities: FR) are not separate entries.
IBAN_COUNTRIES: dict[str, IbanCountry] = {
    "AD": IbanCountry("Andorra", 24),
    "AE": IbanCountry("United Arab Emirates", 23),
    "AL": IbanCountry("Albania", 28),
    "AT": IbanCountry("Austria", 20, bank=(4, 9), bank_label="Bankleitzahl"),
    "AZ": IbanCountry("Azerbaijan", 28),
    "BA": IbanCountry("Bosnia and Herzegovina", 20),
    "BE": IbanCountry("Belgium", 16, bank=(4, 7)),
    "BG": IbanCountry("Bulgaria", 22),
    "BH": IbanCountry("Bahrain", 22),
    "BI": IbanCountry("Burundi", 27),
    "BR": IbanCountry("Brazil", 29),
    "BY": IbanCountry("Belarus", 28),
    "CH": IbanCountry("Switzerland", 21, bank=(4, 9), bank_label="Bank clearing number (IID)"),
    "CR": IbanCountry("Costa Rica", 22),
    "CY": IbanCountry("Cyprus", 28),
    "CZ": IbanCountry("Czechia", 24, bank=(4, 8)),
    "DE": IbanCountry("Germany", 22, bank=(4, 12), bank_label="Bankleitzahl (BLZ)", account=(12, 22)),
    "DJ": IbanCountry("Djibouti", 27),
    "DK": IbanCountry("Denmark", 18, bank=(4, 8)),
    "DO": IbanCountry("Dominican Republic", 28),
    "EE": IbanCountry("Estonia", 20),
    "EG": IbanCountry("Egypt", 29),
    "ES": IbanCountry("Spain", 24, bank=(4, 8), branch=(8, 12)),
    "FI": IbanCountry("Finland", 18),
    "FK": IbanCountry("Falkland Islands", 18),
    "FO": IbanCountry("Faroe Islands", 18),
    "FR": IbanCountry("France", 27, bank=(4, 9), branch=(9, 14), branch_label="Code guichet"),
    "GB": IbanCountry("United Kingdom", 22, bank=(4, 8), branch=(8, 14), branch_label="Sort code"),
    "GE": IbanCountry("Georgia", 22),
    "GI": IbanCountry("Gibraltar", 23),
    "GL": IbanCountry("Greenland", 18),
    "GR": IbanCountry("Greece", 27),
    "GT": IbanCountry("Guatemala", 28),
    "HN": IbanCountry("Honduras", 28),
    "HR": IbanCountry("Croatia", 21),
    "HU": IbanCountry("Hungary", 28),
    "IE": IbanCountry("Ireland", 22, bank=(4, 8), branch=(8, 14), branch_label="Sort code"),
    "IL": IbanCountry("Israel", 23),
    "IQ": IbanCountry("Iraq", 23),
    "IS": IbanCountry("Iceland", 26),
    "IT": IbanCountry("Italy", 27, bank=(5, 10), bank_label="ABI", branch=(10, 15), branch_label="CAB"),
    "JO": IbanCountry("Jordan", 30),
    "KW": IbanCountry("Kuwait", 30),
    "KZ": IbanCountry("Kazakhstan", 20),
    "LB": IbanCountry("Lebanon", 28),
    "LC": IbanCountry("Saint Lucia", 32),
    "LI": IbanCountry("Liechtenstein", 21),
    "LT": IbanCountry("Lithuania", 20),
    "LU": IbanCountry("Luxembourg", 20, bank=(4, 7)),
    "LV": IbanCountry("Latvia", 21),
    "LY": IbanCountry("Libya", 25),
    "MC": IbanCountry("Monaco", 27),
    "MD": IbanCountry("Moldova", 24),
    "ME": IbanCountry("Montenegro", 22),
    "MK": IbanCountry("North Macedonia", 19),
    "MN": IbanCountry("Mongolia", 20),
    "MR": IbanCountry("Mauritania", 27),
    "MT": IbanCountry("Malta", 31),
    "MU": IbanCountry("Mauritius", 30),
    "NI": IbanCountry("Nicaragua", 28),
    "NL": IbanCountry("Netherlands", 18, bank=(4, 8)),
    "NO": IbanCountry("Norway", 15, bank=(4, 8)),
    "OM": IbanCountry("Oman", 23),
    "PK": IbanCountry("Pakistan", 24),
    "PL": IbanCountry("Poland", 28),
    "PS": IbanCountry("Palestine", 29),
    "PT": IbanCountry("Portugal", 25, bank=(4, 8), branch=(8, 12)),
    "QA": IbanCountry("Qatar", 29),
    "RO": IbanCountry("Romania", 24),
    "RS": IbanCountry("Serbia", 22),
    "RU": IbanCountry("Russia", 33),
    "SA": IbanCountry("Saudi Arabia", 24),
    "SC": IbanCountry("Seychelles", 31),
    "SD": IbanCountry("Sudan", 18),
    "SE": IbanCountry("Sweden", 24),
    "SI": IbanCountry("Slovenia", 19),
    "SK": IbanCountry("Slovakia", 24),
    "SM": IbanCountry("San Marino", 27),
    "SO": IbanCountry("Somalia", 23),
    "ST": IbanCountry("São Tomé and Príncipe", 25),
    "SV": IbanCountry("El Salvador", 28),
    "TL": IbanCountry("Timor-Leste", 23),
    "TN": IbanCountry("Tunisia", 24),
    "TR": IbanCountry("Türkiye", 26),
    "UA": IbanCountry("Ukraine", 29),
    "VA": IbanCountry("Vatican City", 22),
    "VG": IbanCountry("British Virgin Islands", 24),
    "XK": IbanCountry("Kosovo", 20),
    "YE": IbanCountry("Yemen", 30),
}

#: When the payee's bank has to answer the check of the payee's name before a euro transfer
#: (Empfängerüberprüfung, verification of payee: Art. 5c Reg. (EU) No 260/2012 as amended by
#: Reg. (EU) 2024/886), by the IBAN's country. It is EU law for payment service providers in the Union:
#: in the euro area from 9 October 2025, in the member states whose currency is not the euro (CZ, DK,
#: HU, PL, RO, SE) from 9 July 2027 (Art. 5c(9)); Bulgaria, which introduced the euro on 1 January 2026,
#: has a year from then (Art. 16(9)), so 1 January 2027. Until its date a check of such an account may
#: come back "not possible". An account elsewhere — the EEA's EFTA states, Switzerland, the UK or
#: further away — may get no check at all. Territories using a member's IBAN (the French overseas
#: departments: FR; Åland: FI) count as it.
PAYEE_CHECK_FROM: dict[str, date] = {
    **dict.fromkeys(
        (
            "AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR",
            "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK",
        ),
        date(2025, 10, 9),
    ),
    "BG": date(2027, 1, 1),
    **dict.fromkeys(("CZ", "DK", "HU", "PL", "RO", "SE"), date(2027, 7, 9)),
}  # fmt: skip


@dataclass(frozen=True)
class IbanCheck:
    """The result of :func:`inspect_iban` (``None`` fields could not be determined)."""

    iban: str
    country_code: str | None
    country: str | None
    shape_ok: bool
    length_expected: int | None
    checksum_ok: bool
    bank_label: str | None = None
    bank_code: str | None = None
    branch_label: str | None = None
    branch_code: str | None = None
    account_number: str | None = None

    @property
    def length_ok(self) -> bool | None:
        """``None`` when the two letters are not an IBAN country (so there is no length to check)."""
        return None if self.length_expected is None else len(self.iban) == self.length_expected

    @property
    def valid(self) -> bool:
        return self.shape_ok and self.country is not None and self.length_ok is True and self.checksum_ok

    @property
    def problems(self) -> list[str]:
        """Why the IBAN is not well-formed, in plain words (empty when it is)."""
        found = []
        if not self.shape_ok:
            found.append(
                "It is not shaped like an IBAN (two letters, two check digits, then letters and digits)."
            )
        elif self.country is None:
            found.append(f"{self.iban[:2]} is not a country that issues IBANs, so this is not an IBAN.")
        elif self.length_ok is False:
            found.append(
                f"{self.country} IBANs have {self.length_expected} characters; this one has {len(self.iban)}."
            )
        if self.shape_ok and not self.checksum_ok:
            found.append("The check digits do not match: a character is wrong, missing or swapped.")
        return found


def normalize(text: str) -> str:
    """``"IBAN: de89 3704-0044 0532 0130 00"`` → ``"DE89370400440532013000"`` (see module policy)."""
    visible = "".join(char for char in text if unicodedata.category(char) != "Cf")
    return _NOISE.sub("", _LABEL.sub("", visible)).upper()


def grouped(iban: str) -> str:
    """Groups of four characters, as printed on letters."""
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def checksum_ok(iban: str) -> bool:
    """The ISO 13616 mod-97 check (``iban`` normalised and shaped like an IBAN)."""
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def inspect_iban(text: str) -> IbanCheck:
    """Everything the IBAN itself tells: country, length, checksum and (where known) bank code."""
    iban = normalize(text)
    shape_ok = MIN_LENGTH <= len(iban) <= MAX_LENGTH and _SHAPE.match(iban) is not None
    country = IBAN_COUNTRIES.get(iban[:2])
    check = IbanCheck(
        iban=iban,
        country_code=iban[:2] if country else None,
        country=country.name if country else None,
        shape_ok=shape_ok,
        length_expected=country.length if country else None,
        checksum_ok=shape_ok and checksum_ok(iban),
    )
    if country is None or not check.valid:
        return check
    return replace(
        check,
        bank_label=country.bank_label if country.bank else None,
        bank_code=_cut(iban, country.bank),
        branch_label=country.branch_label if country.branch else None,
        branch_code=_cut(iban, country.branch),
        account_number=_cut(iban, country.account),
    )


def _cut(iban: str, span: tuple[int, int] | None) -> str | None:
    return iban[span[0] : span[1]] if span else None
