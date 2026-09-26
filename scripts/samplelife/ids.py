"""Check-digit helpers so that every fictional identifier is at least *formally* valid.

IBANs (ISO 13616, mod 97), SEPA creditor identifiers (EPC262-08, mod 97 without the business code),
German VAT IDs (ISO 7064 MOD 11,10) and ICAO 9303 machine-readable-zone check digits (7-3-1).
"""

from __future__ import annotations


def _alnum_to_digits(text: str) -> str:
    """Replace letters by two-digit numbers (A=10 … Z=35), keep digits."""
    return "".join(str(int(ch, 36)) for ch in text)


def iban_check_digits(country: str, bban: str) -> str:
    """Return the two ISO 13616 check digits for ``country`` + ``bban``."""
    remainder = int(_alnum_to_digits(bban + country + "00")) % 97
    return f"{98 - remainder:02d}"


def make_iban(country: str, bban: str) -> str:
    """Build an IBAN (without spaces) with valid check digits."""
    return f"{country}{iban_check_digits(country, bban)}{bban}"


def de_iban(blz: str, account: str) -> str:
    """German IBAN from an 8-digit Bankleitzahl and a 10-digit account number."""
    if len(blz) != 8 or len(account) != 10 or not (blz + account).isdigit():
        raise ValueError("a German BBAN is an 8-digit bank code plus a 10-digit account number")
    return make_iban("DE", blz + account)


def is_valid_iban(iban: str) -> bool:
    """Validate an IBAN's mod-97 checksum (spaces are ignored)."""
    compact = iban.replace(" ", "").upper()
    if len(compact) < 15 or not compact.isalnum() or not compact[:2].isalpha():
        return False
    return int(_alnum_to_digits(compact[4:] + compact[:4])) % 97 == 1


def format_iban(iban: str) -> str:
    """Group an IBAN in blocks of four characters, as printed on letters."""
    compact = iban.replace(" ", "")
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def creditor_id(country: str, national_id: str, business_code: str = "ZZZ") -> str:
    """SEPA creditor identifier; the business code is excluded from the checksum."""
    return f"{country}{iban_check_digits(country, national_id)}{business_code}{national_id}"


def ust_idnr(base8: str) -> str:
    """German VAT ID ``DE`` + 8 digits + ISO 7064 MOD 11,10 check digit."""
    if len(base8) != 8 or not base8.isdigit():
        raise ValueError("expected 8 digits")
    product = 10
    for ch in base8:
        total = (int(ch) + product) % 10 or 10
        product = (2 * total) % 11
    check = (11 - product) % 10
    return f"DE{base8}{check}"


def mrz_check_digit(field: str) -> str:
    """ICAO 9303 check digit: weights 7, 3, 1; ``<`` counts as 0, letters as 10–35."""
    weights = (7, 3, 1)
    total = 0
    for index, ch in enumerate(field):
        value = 0 if ch == "<" else int(ch, 36)
        total += value * weights[index % 3]
    return str(total % 10)
