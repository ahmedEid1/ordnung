"""German calendar arithmetic: public holidays, business days and *Werktage*.

Two notions of a working day are used by German law and by Ordnung:

* **business day** — Monday to Friday, excluding public holidays. This is the "next working day" of
  § 193 BGB, § 108 Abs. 3 AO, § 31 Abs. 3 VwVfG, § 26 Abs. 3 SGB X and § 222 Abs. 2 ZPO, which all
  treat Saturday like a Sunday when a period ends.
* **Werktag** — Monday to Saturday, excluding public holidays. Used where a statute counts
  *Werktage*, e.g. the three-*Werktag* grace period for giving notice on a flat (§ 573c Abs. 1 BGB;
  BGH VIII ZR 206/04 counts Saturday).

Holidays: weekend and nationwide holidays always count. Regional (Land) holidays only count when the
region of the place that matters is known; otherwise they are ignored, which can only make a computed
deadline earlier, never later (safety policy, SPEC § 21). 24 and 31 December are *not* holidays.
A holiday that holds in only part of a Land (Mariä Himmelfahrt in Bavarian communities with more
Catholic than Protestant residents, Augsburg's Friedensfest, Fronleichnam in parts of Saxony and
Thuringia) is not counted either: :func:`partial_holidays` lists them, and the deadline rules warn
where one could move a date shown.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import holidays

NATIONWIDE_LABEL = "Germany (nationwide holidays only)"

#: Land codes accepted by :func:`normalize_region`, with the German name used in receipts.
REGION_NAMES: dict[str, str] = {
    "BB": "Brandenburg",
    "BE": "Berlin",
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "HB": "Bremen",
    "HE": "Hessen",
    "HH": "Hamburg",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SH": "Schleswig-Holstein",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "TH": "Thüringen",
}

_ALIASES: dict[str, str] = {
    **{name.casefold(): code for code, name in REGION_NAMES.items()},
    "nrw": "NW",
    "baden-wuerttemberg": "BW",
    "bavaria": "BY",
    "hesse": "HE",
    "lower saxony": "NI",
    "north rhine-westphalia": "NW",
    "rhineland-palatinate": "RP",
    "saxony": "SN",
    "saxony-anhalt": "ST",
    "thuringia": "TH",
    "thueringen": "TH",
    "mecklenburg-western pomerania": "MV",
}


def normalize_region(region: str | None) -> str | None:
    """Return the two-letter Land code for ``region`` or ``None`` when it is missing or unknown.

    Accepts codes (``"NW"``, ``"nw"``, ``"DE-NW"``) and German or English Land names.
    """
    if not region:
        return None
    raw = region.strip()
    code = raw.upper().removeprefix("DE-")
    if code in REGION_NAMES:
        return code
    return _ALIASES.get(raw.casefold())


def holiday_calendar_label(region: str | None) -> str:
    """Human-readable name of the holiday calendar used for ``region`` (shown on receipts)."""
    code = normalize_region(region)
    return REGION_NAMES[code] if code else NATIONWIDE_LABEL


#: Holidays that hold in only part of a Land, by Land and German name, with where they hold. The
#: calendar leaves them out: the place (the community) is not known.
PARTIAL_HOLIDAY_PLACES: dict[str, dict[str, str]] = {
    "BY": {
        "Mariä Himmelfahrt": "the communities of Bayern with more Catholic than Protestant residents (as the "
        "Landesamt für Statistik lists them; Munich among them)",
        "Augsburger Hohes Friedensfest": "the city of Augsburg (Bayern)",
    },
    "SN": {"Fronleichnam": "some communities of the Sorbian area of Sachsen"},
    "TH": {"Fronleichnam": "some communities of Thüringen with a Catholic majority"},
}
#: Partial holidays the holiday library leaves out even from its extra categories: (month, day, name).
_MORE_PARTIAL_HOLIDAYS: dict[str, tuple[tuple[int, int, str], ...]] = {
    "BY": ((8, 8, "Augsburger Hohes Friedensfest"),),
}


@lru_cache(maxsize=512)
def _holidays_for(code: str | None, year: int) -> dict[date, str]:
    # German names whatever the system locale (the library would translate them from LANG/LANGUAGE)
    calendar = holidays.Germany(subdiv=code, years=year, language="de")
    return dict(calendar.items())


def holiday_name(d: date, region: str | None = None) -> str | None:
    """Name of the public holiday on ``d`` in ``region`` (nationwide only if unknown), else ``None``."""
    return _holidays_for(normalize_region(region), d.year).get(d)


def is_holiday(d: date, region: str | None = None) -> bool:
    """True if ``d`` is a public holiday in ``region`` (nationwide holidays only if unknown)."""
    return holiday_name(d, region) is not None


@lru_cache(maxsize=256)
def _partial_holidays_for(code: str, year: int) -> dict[date, str]:
    found = dict(holidays.Germany(subdiv=code, years=year, categories=("catholic",), language="de"))
    found.update({date(year, month, day): name for month, day, name in _MORE_PARTIAL_HOLIDAYS.get(code, ())})
    return found


def partial_holidays(
    region: str | None, start: date, end: date, *, werktage: bool = False
) -> list[tuple[date, str]]:
    """Holidays of only part of ``region`` from ``start`` to ``end`` that fall on a counted day.

    Those are the :data:`PARTIAL_HOLIDAY_PLACES`, which the calendar does not count; a counted day is a
    business day, or a *Werktag* with ``werktage=True``. Empty for a Land without such holidays.
    """
    code = normalize_region(region)
    if code not in PARTIAL_HOLIDAY_PLACES or end < start:
        return []
    counts = is_werktag if werktage else is_business_day
    found = [
        (day, name)
        for year in range(start.year, end.year + 1)
        for day, name in _partial_holidays_for(code, year).items()
        if start <= day <= end and counts(day, code)
    ]
    return sorted(found)


def regional_holiday_lands(d: date) -> list[str]:
    """Land codes where ``d`` is a public holiday although it is not a nationwide one."""
    if is_holiday(d):
        return []
    return [code for code in REGION_NAMES if is_holiday(d, code)]


def is_business_day(d: date, region: str | None = None) -> bool:
    """True for Monday–Friday that is not a public holiday."""
    return d.weekday() < 5 and not is_holiday(d, region)


def is_bank_business_day(d: date, region: str | None = None) -> bool:
    """Business day on which German banks process transfers (not 24 or 31 December).

    Banks treat Heiligabend and Silvester as closing days for customer transfers although they are no
    public holidays (legal research, money_tax verdict; § 675n Abs. 1 BGB: the bank's business day).
    """
    return is_business_day(d, region) and (d.month, d.day) not in ((12, 24), (12, 31))


def is_werktag(d: date, region: str | None = None) -> bool:
    """True for Monday–Saturday that is not a public holiday (German *Werktag*)."""
    return d.weekday() < 6 and not is_holiday(d, region)


def day_kind(d: date, region: str | None = None) -> str | None:
    """Why ``d`` is not a business day: ``"Saturday"``, ``"Sunday"`` or the holiday name; else ``None``."""
    name = holiday_name(d, region)
    if name:
        return name
    if d.weekday() == 5:
        return "Saturday"
    if d.weekday() == 6:
        return "Sunday"
    return None


def next_business_day(d: date, region: str | None = None) -> date:
    """First business day on or after ``d`` (returns ``d`` itself if it already is one)."""
    while not is_business_day(d, region):
        d += timedelta(days=1)
    return d


def previous_business_day(d: date, region: str | None = None) -> date:
    """Last business day on or before ``d`` (returns ``d`` itself if it already is one)."""
    while not is_business_day(d, region):
        d -= timedelta(days=1)
    return d


def _add_counted_days(d: date, n: int, region: str | None, *, werktage: bool) -> date:
    counts = is_werktag if werktage else is_business_day
    step = timedelta(days=1 if n >= 0 else -1)
    remaining = abs(n)
    while remaining:
        d += step
        if counts(d, region):
            remaining -= 1
    return d


def add_business_days(d: date, n: int, region: str | None = None) -> date:
    """Move ``n`` business days from ``d`` (``d`` itself is not counted; ``n`` may be negative).

    ``add_business_days(d, 0)`` returns ``d`` unchanged.
    """
    return _add_counted_days(d, n, region, werktage=False)


def add_werktage(d: date, n: int, region: str | None = None) -> date:
    """Move ``n`` *Werktage* (Mon–Sat excluding holidays) from ``d``; ``n`` may be negative."""
    return _add_counted_days(d, n, region, werktage=True)
