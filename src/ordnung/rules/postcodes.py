"""The Land the postcode on a sender's letter suggests: a question for the person, never an answer (ADR 0019).

A sender's Land decides which public holidays move their dates, and whether their authority's letter counts
as delivered after 3 or 4 days. Only the person sets it, in the sender's details; until then Ordnung counts
nationwide holidays and 3 days, the earlier dates (SPEC § 21). This module reads the postcode on a letter and
looks it up in GeoNames' postal codes (``data/postcodes_de.tsv``, CC BY 4.0, built by
``scripts/make_postcode_table.py``), so the app can ask "Is X in Bavaria? (80331 on their letter)". A wrong
confirmed Land can make a date late, while an unknown one only makes it early, so the lookup is exact: a
postcode GeoNames lists in exactly one Land, with no prefix, range or fuzzy inference.

**The policy** (:func:`suggest_land_why`). The first rule that applies decides:

1. A blank address: ``no_address``.
2. An address abroad (:func:`looks_foreign`): ``foreign``. Any one of these is enough: a comma- or
   line-separated part of the address that is a country other than Germany (English, German and native
   names of the EU and EEA countries, Switzerland, the UK, Ireland, the USA and Turkey; only a whole part
   counts, so "Sächsische Schweiz" is not "Schweiz", and a two-letter Land code is never a country); a
   postal country prefix other than Germany's before the digits (``F-75008``, ``CH-8001``); an e-mail or
   web address under another country's domain.
3. No 5-digit postcode (:func:`postcodes_in`; a Postfach number is never one): ``no_postcode``.
4. None of them listed: ``not_listed``. A postcode GeoNames doesn't list, next to one it lists, is ignored.
5. A listed postcode in several Länder: ``several_lands``; one listed without a Land: ``no_land``.
6. Listed postcodes in different Länder: ``postcodes_disagree``.
7. A listed postcode that is not a whole 5-digit number in the letter's visible text: ``not_visible``. An
   address a reader took from hidden text never asks.
8. The person's own Land disagrees: ``home_veto``. The first listed postcode is the person's own, or is in
   their town under the same first two digits, yet the table puts it in another Land than the one they set
   for themselves. The table and the person contradict each other, so nothing is asked. Before onboarding
   the person's Land is unknown (``Profile.known_region``) and never vetoes.
9. Otherwise the first listed postcode's Land: ``suggested``.
"""

from __future__ import annotations

import functools
import re
import string
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

from ordnung.rules.calendar_de import normalize_region

TABLE_PATH: Final[Path] = Path(__file__).with_name("data") / "postcodes_de.tsv"

Reason = Literal[
    "suggested",
    "no_address",
    "foreign",
    "no_postcode",
    "not_listed",
    "several_lands",
    "no_land",
    "postcodes_disagree",
    "not_visible",
    "home_veto",
]

_NO_LAND: Final = "-"
_TRIM: Final = string.whitespace + string.punctuation + "„“”‚‘’«»–—"


def _part(text: str) -> str:
    """A part of an address as it is compared: trimmed of punctuation, spaces collapsed, case-folded."""
    return " ".join(text.strip(_TRIM).split()).casefold()


#: Countries other than Germany as an address names them, in English, German and their own languages.
_COUNTRIES: Final = frozenset(
    _part(name)
    for line in """
        Austria, Österreich
        Belgium, Belgien, Belgique, België
        Bulgaria, Bulgarien, България
        Croatia, Kroatien, Hrvatska
        Cyprus, Zypern, Κύπρος
        Czechia, Czech Republic, Tschechien, Tschechische Republik, Česko, Česká republika
        Denmark, Dänemark, Danmark
        Estonia, Estland, Eesti
        Finland, Finnland, Suomi
        France, Frankreich
        Greece, Griechenland, Ελλάδα, Hellas
        Hungary, Ungarn, Magyarország
        Iceland, Island, Ísland
        Ireland, Irland, Éire
        Italy, Italien, Italia
        Latvia, Lettland, Latvija
        Liechtenstein
        Lithuania, Litauen, Lietuva
        Luxembourg, Luxemburg, Lëtzebuerg
        Malta
        Netherlands, The Netherlands, Niederlande, Nederland, Holland
        Norway, Norwegen, Norge, Noreg
        Poland, Polen, Polska
        Portugal
        Romania, Rumänien, România
        Slovakia, Slowakei, Slovensko
        Slovenia, Slowenien, Slovenija
        Spain, Spanien, España, Espana
        Sweden, Schweden, Sverige
        Switzerland, Schweiz, Suisse, Svizzera, Svizra
        Turkey, Türkei, Türkiye, Turkiye
        United Kingdom, UK, Great Britain, Großbritannien, Grossbritannien, Vereinigtes Königreich
        England, Scotland, Schottland, Wales, Northern Ireland, Nordirland
        USA, U.S.A., US, U.S., United States, United States of America
        Vereinigte Staaten, Vereinigte Staaten von Amerika
    """.strip().splitlines()
    for name in line.split(",")
)

#: The top-level domains of those countries (not ``.eu`` or ``.com``, which German senders use too).
_FOREIGN_DOMAINS: Final = frozenset(
    """at be bg ch cy cz dk ee es fi fr gr hr hu ie is it li lt lu lv mt nl no pl pt ro se si sk tr
    uk us""".split()  # noqa: SIM905
)

_PARTS: Final = re.compile(r"[,;\n]")
#: A postal country prefix before the digits ("F-75008", "CH-8001"); ``D`` and ``DE`` are Germany's.
_COUNTRY_PREFIX: Final = re.compile(r"(?<!\w)([A-Z]{1,3})-[0-9]{4,5}(?![0-9])")
_GERMANY: Final = frozenset({"D", "DE"})
#: A Postfach number ("Postfach 10 01 23", "Postf. 12345", "PF 1234"), removed before postcodes are read. It is
#: on the same line: "Postfach" alone on a line leaves the postcode below it.
_POSTFACH: Final = re.compile(
    r"\b(?:postfach|postf\.?|pf\.?)(?:[^\S\n]|:)*[0-9]+(?:[ .][0-9]{1,3}(?![0-9]))*", re.I
)
#: A postcode, five digits not part of a longer number, and the rest of its line or part (the town).
_POSTCODE: Final = re.compile(r"(?<![0-9])([0-9]{5})(?![0-9])([^0-9,;\n]*)")
_WORD: Final = re.compile(r"[^\W\d_]+")
_SCHEME: Final = re.compile(r"^[a-z][a-z0-9+.-]*://")


@dataclass(frozen=True)
class PostcodeLand:
    """A suggestion: the Land of the postcode on the letter."""

    region: str
    """A key of :data:`ordnung.rules.calendar_de.REGION_NAMES`."""
    postcode: str
    """The 5 digits, as on the letter."""


@dataclass(frozen=True)
class Home:
    """Where the person lives, for the own-Land check (rule 8)."""

    postcode: str | None
    town: str | None
    """The first word after the postcode, case-folded."""
    region: str | None
    """``Profile.known_region``: ``None`` before onboarding, which never vetoes."""

    @classmethod
    def of(cls, address: str, region: str | None) -> Home:
        """The person's first postcode and town in ``address``, and their Land."""
        for postcode, town in _postcodes(address).items():
            return cls(postcode, town, normalize_region(region))
        return cls(None, None, normalize_region(region))


@functools.cache
def table() -> Mapping[str, frozenset[str]]:
    """Every postcode GeoNames lists, with its Länder (none: listed without one), read once."""
    rows: dict[str, frozenset[str]] = {}
    for line in TABLE_PATH.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            code, lands = line.split("\t")
            rows[code] = frozenset() if lands == _NO_LAND else frozenset(lands.split(","))
    return MappingProxyType(rows)


def land_of_postcode(code: str) -> str | None:
    """The Land of ``code`` when GeoNames lists it in exactly one, else ``None``."""
    lands = table().get(code, frozenset())
    return next(iter(lands)) if len(lands) == 1 else None


def _postcodes(address: str) -> dict[str, str | None]:
    """Each distinct postcode in ``address``, in order, with the first word of the town after it."""
    found: dict[str, str | None] = {}
    for match in _POSTCODE.finditer(_POSTFACH.sub(" ", address)):
        words = _WORD.findall(match.group(2).casefold())
        found.setdefault(match.group(1), words[0] if words else None)
    return found


def postcodes_in(address: str) -> list[str]:
    """The distinct 5-digit postcodes in ``address``, in order ("D-80331" included); a Postfach number
    ("Postfach 12345") is never one."""
    return list(_postcodes(address))


def _domain(value: str) -> str:
    """The top-level domain of an e-mail or web address ("" when it names no domain)."""
    host = re.split(r"[/?#]", _SCHEME.sub("", value.strip().casefold()), maxsplit=1)[0]
    head, dot, top = host.rpartition("@")[2].partition(":")[0].rpartition(".")
    return top if dot and head else ""


def looks_foreign(address: str, *, email: str | None = None, website: str | None = None) -> bool:
    """Whether the address, e-mail or website says the sender is abroad (rule 2 of the policy)."""
    if any(_part(part) in _COUNTRIES for part in _PARTS.split(address)):
        return True
    if any(match.group(1) not in _GERMANY for match in _COUNTRY_PREFIX.finditer(address)):
        return True
    return any(_domain(value) in _FOREIGN_DOMAINS for value in (email, website) if value)


def _shows(code: str, text: str) -> bool:
    return re.search(rf"(?<![0-9]){code}(?![0-9])", text) is not None


def _contradicts(home: Home, region: str, postcode: str, town: str | None) -> bool:
    """Rule 8: the person's own postcode, or their town under the same first two digits, in another Land."""
    if home.region is None or home.postcode is None or home.region == region:
        return False
    return postcode == home.postcode or (
        town is not None and town == home.town and postcode[:2] == home.postcode[:2]
    )


def suggest_land_why(
    address: str | None,
    *,
    email: str | None = None,
    website: str | None = None,
    visible_text: str | None = None,
    home: Home | None = None,
) -> tuple[PostcodeLand | None, Reason]:
    """The Land the postcode in a sender's ``address`` suggests, and why (the policy above).

    ``email`` and ``website`` are the sender's; ``visible_text`` is the letter's text as shown (``None``:
    not checked); ``home`` is the person's (``None``: no own-Land check).
    """
    if not address or not address.strip():
        return None, "no_address"
    if looks_foreign(address, email=email, website=website):
        return None, "foreign"
    found = _postcodes(address)
    if not found:
        return None, "no_postcode"
    listed = {code: table()[code] for code in found if code in table()}
    if not listed:
        return None, "not_listed"
    if any(len(lands) > 1 for lands in listed.values()):
        return None, "several_lands"
    if any(not lands for lands in listed.values()):
        return None, "no_land"
    regions = {land for lands in listed.values() for land in lands}
    if len(regions) > 1:
        return None, "postcodes_disagree"
    if visible_text is not None and not all(_shows(code, visible_text) for code in listed):
        return None, "not_visible"
    (region,) = regions
    postcode = next(iter(listed))
    if home is not None and _contradicts(home, region, postcode, found[postcode]):
        return None, "home_veto"
    return PostcodeLand(region, postcode), "suggested"


def suggest_land(
    address: str | None,
    *,
    email: str | None = None,
    website: str | None = None,
    visible_text: str | None = None,
    home: Home | None = None,
) -> PostcodeLand | None:
    """The suggestion of :func:`suggest_land_why`, without its reason."""
    return suggest_land_why(address, email=email, website=website, visible_text=visible_text, home=home)[0]
