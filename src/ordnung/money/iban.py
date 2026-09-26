"""What an IBAN says about itself: its country, whether it is well-formed, and its bank code.

Pure code, no I/O. Policy (ISO 13616 and the SWIFT IBAN registry):

* **Well-formed** means: letters and digits only (spaces, dashes and dots as printed are ignored),
  two letters for the country, two check digits, the registered length of that country when it is
  in :data:`IBAN_COUNTRIES`, and the mod-97 checksum. A country not in the table gets the checksum
  check only, and the result says so.
* **Bank code** — the national bank identifier (and branch code where the registry defines one) is
  cut out of the account part only for the countries listed with its position; elsewhere it is
  ``None`` rather than a guess. No bank *names*: that needs each country's bank directory.
* A well-formed IBAN says nothing about who owns the account; callers must say so (a scam can use a
  perfectly valid IBAN).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

_NOISE = re.compile(r"[\s\-.]+")
_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")
MAX_LENGTH = 34
MIN_LENGTH = 15


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


#: The countries of the SEPA area and Germany's neighbours (lengths from the SWIFT IBAN registry).
IBAN_COUNTRIES: dict[str, IbanCountry] = {
    "AD": IbanCountry("Andorra", 24),
    "AL": IbanCountry("Albania", 28),
    "AT": IbanCountry("Austria", 20, bank=(4, 9), bank_label="Bankleitzahl"),
    "BA": IbanCountry("Bosnia and Herzegovina", 20),
    "BE": IbanCountry("Belgium", 16, bank=(4, 7)),
    "BG": IbanCountry("Bulgaria", 22),
    "CH": IbanCountry("Switzerland", 21, bank=(4, 9), bank_label="Bank clearing number (IID)"),
    "CY": IbanCountry("Cyprus", 28),
    "CZ": IbanCountry("Czechia", 24, bank=(4, 8)),
    "DE": IbanCountry("Germany", 22, bank=(4, 12), bank_label="Bankleitzahl (BLZ)", account=(12, 22)),
    "DK": IbanCountry("Denmark", 18, bank=(4, 8)),
    "EE": IbanCountry("Estonia", 20),
    "ES": IbanCountry("Spain", 24, bank=(4, 8), branch=(8, 12)),
    "FI": IbanCountry("Finland", 18),
    "FO": IbanCountry("Faroe Islands", 18),
    "FR": IbanCountry("France", 27, bank=(4, 9), branch=(9, 14), branch_label="Code guichet"),
    "GB": IbanCountry("United Kingdom", 22, bank=(4, 8), branch=(8, 14), branch_label="Sort code"),
    "GI": IbanCountry("Gibraltar", 23),
    "GL": IbanCountry("Greenland", 18),
    "GR": IbanCountry("Greece", 27),
    "HR": IbanCountry("Croatia", 21),
    "HU": IbanCountry("Hungary", 28),
    "IE": IbanCountry("Ireland", 22, bank=(4, 8), branch=(8, 14), branch_label="Sort code"),
    "IS": IbanCountry("Iceland", 26),
    "IT": IbanCountry("Italy", 27, bank=(5, 10), bank_label="ABI", branch=(10, 15), branch_label="CAB"),
    "LI": IbanCountry("Liechtenstein", 21),
    "LT": IbanCountry("Lithuania", 20),
    "LU": IbanCountry("Luxembourg", 20, bank=(4, 7)),
    "LV": IbanCountry("Latvia", 21),
    "MC": IbanCountry("Monaco", 27),
    "MD": IbanCountry("Moldova", 24),
    "ME": IbanCountry("Montenegro", 22),
    "MK": IbanCountry("North Macedonia", 19),
    "MT": IbanCountry("Malta", 31),
    "NL": IbanCountry("Netherlands", 18, bank=(4, 8)),
    "NO": IbanCountry("Norway", 15, bank=(4, 8)),
    "PL": IbanCountry("Poland", 28),
    "PT": IbanCountry("Portugal", 25, bank=(4, 8), branch=(8, 12)),
    "RO": IbanCountry("Romania", 24),
    "RS": IbanCountry("Serbia", 22),
    "SE": IbanCountry("Sweden", 24),
    "SI": IbanCountry("Slovenia", 19),
    "SK": IbanCountry("Slovakia", 24),
    "SM": IbanCountry("San Marino", 27),
    "TR": IbanCountry("Türkiye", 26),
    "UA": IbanCountry("Ukraine", 29),
    "VA": IbanCountry("Vatican City", 22),
    "XK": IbanCountry("Kosovo", 20),
}


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
        """``None`` when the country's length is not in the table."""
        return None if self.length_expected is None else len(self.iban) == self.length_expected

    @property
    def valid(self) -> bool:
        return self.shape_ok and self.length_ok is not False and self.checksum_ok

    @property
    def problems(self) -> list[str]:
        """Why the IBAN is not well-formed, in plain words (empty when it is)."""
        found = []
        if not self.shape_ok:
            found.append(
                "It is not shaped like an IBAN (two letters, two check digits, then letters and digits)."
            )
        elif self.length_ok is False:
            found.append(
                f"{self.country} IBANs have {self.length_expected} characters; this one has {len(self.iban)}."
            )
        if self.shape_ok and not self.checksum_ok:
            found.append("The check digits do not match: a character is wrong, missing or swapped.")
        return found


def normalize(text: str) -> str:
    """``"de89 3704-0044 0532 0130 00"`` → ``"DE89370400440532013000"``."""
    return _NOISE.sub("", text).upper()


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
    code = iban[:2] if len(iban) >= 2 and iban[:2].isalpha() and iban[:2].isascii() else None
    country = IBAN_COUNTRIES.get(code or "")
    check = IbanCheck(
        iban=iban,
        country_code=code,
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
