"""Formatting helpers: German/English dates and money, valid (fictional) IBANs, stable seeds."""

from __future__ import annotations

import hashlib
import random
from datetime import date

MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)  # fmt: skip
MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
WEEKDAYS_LONG_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
WEEKDAYS_LONG_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def de(d: date) -> str:
    """``02.01.2026``"""
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def de_short(d: date) -> str:
    """``02.01.26``"""
    return f"{d.day:02d}.{d.month:02d}.{d.year % 100:02d}"


def de_long(d: date) -> str:
    """``2. Januar 2026``"""
    return f"{d.day}. {MONTHS_DE[d.month - 1]} {d.year}"


def de_weekday(d: date) -> str:
    """``Freitag, 02.01.2026``"""
    return f"{WEEKDAYS_LONG_DE[d.weekday()]}, {de(d)}"


def en_uk(d: date) -> str:
    """``2 January 2026``"""
    return f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}"


def en_us(d: date) -> str:
    """``January 2, 2026``"""
    return f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}"


def us_numeric(d: date) -> str:
    """``01/02/2026`` (month first)"""
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def eur(amount: float) -> str:
    """``1.234,56 €``"""
    whole, cents = divmod(round(amount * 100), 100)
    grouped = f"{whole:,}".replace(",", ".")
    return f"{grouped},{cents:02d} €"


def eur_plain(amount: float) -> str:
    """``1.234,56`` (for table columns headed EUR)"""
    return eur(amount)[:-2]


def gbp_style(amount: float, symbol: str = "€") -> str:
    """``€1,234.56`` (English letters)"""
    return f"{symbol}{amount:,.2f}"


def seed_for(*parts: object) -> int:
    """A stable 32-bit seed from any parts (no dependence on Python's salted ``hash``)."""
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:4], "big")


def rng_for(*parts: object) -> random.Random:
    return random.Random(seed_for(*parts))


# --------------------------------------------------------------------------------------------------
# IBANs (ISO 13616 mod-97 check digits)
# --------------------------------------------------------------------------------------------------


def _iban_numeric(text: str) -> int:
    return int("".join(str(int(ch, 36)) for ch in text))


def iban(country: str, bban: str) -> str:
    """A syntactically valid IBAN for ``country`` + ``bban`` (check digits computed)."""
    check = 98 - _iban_numeric(bban + country + "00") % 97
    return f"{country}{check:02d}{bban}"


def iban_is_valid(value: str) -> bool:
    compact = value.replace(" ", "")
    return _iban_numeric(compact[4:] + compact[:4]) % 97 == 1


def iban_grouped(value: str) -> str:
    compact = value.replace(" ", "")
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def invalid_iban(country: str, bban: str) -> str:
    """Same as :func:`iban` but with deliberately wrong check digits (for the scam case)."""
    good = iban(country, bban)
    wrong = (int(good[2:4]) + 11) % 97 or 13
    candidate = f"{country}{wrong:02d}{bban}"
    assert not iban_is_valid(candidate)
    return candidate


_FEMININE = (
    "Stadt ",
    "Familienkasse",
    "Muster BKK",
    "Muster-Rentenversicherung",
    "Zentrale ",
    "Polizei ",
    "Allgemeine ",
)
_ADJECTIVE_DATIVE = {"Allgemeine ": "Allgemeinen ", "Zentrale ": "Zentralen "}


def bei(name: str) -> str:
    """German 'bei + Dativ' for an organisation name: 'beim Finanzamt …', 'bei der Stadt …'."""
    if name.startswith(_FEMININE):
        for nominative, dative in _ADJECTIVE_DATIVE.items():
            if name.startswith(nominative):
                name = dative + name[len(nominative) :]
        return f"bei der {name}"
    return f"beim {name}"
