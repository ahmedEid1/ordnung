"""Independent legal date arithmetic for the benchmark labels (SPEC §17, §21).

This module deliberately does **not** import ``ordnung.rules``: the benchmark compares the product's
rules engine against these labels, so the labels must come from a separate, small, readable
implementation. Every function returns the date *and* the human-readable steps that justify it; the
steps end up verbatim in the manifest (``derivation``) so a reviewer can check each label by hand.

Legal basis (see docs/deadline-rules.md and the verified research notes):

* Period start: the event day is not counted (§ 187 Abs. 1 BGB; § 108 Abs. 1 AO; § 31 Abs. 1 VwVfG;
  § 26 Abs. 1 SGB X; § 43 StPO i.V.m. § 46 OWiG).
* Period end: weeks/months end on the day with the same weekday name / day number as the event
  day; if that day number does not exist, on the last day of the month (§ 188 Abs. 2, 3 BGB).
* End shift: an end on Saturday, Sunday or a public holiday moves to the next working day (§ 193
  BGB; § 108 Abs. 3 AO; § 31 Abs. 3 VwVfG; § 26 Abs. 3 SGB X; § 64 Abs. 3 SGG; § 43 Abs. 2 StPO).
  Never for notice periods (BGH III ZR 172/04) and never for appointments.
* Posted administrative acts: deemed notified on the 4th day after posting for items posted from
  2025-01-01, the 3rd day before (PostModG; Art. 97 § 1 Abs. 15 EGAO). Tax law (AO) moves that day
  to the next working day (§ 108 Abs. 3 AO, BFH IX R 68/98); VwVfG and SGB X do not (BSG B 14 AS
  12/09 R; OVG Lüneburg 4 LA 44/10).
* Holidays: weekend + the nine nationwide holidays always; regional (Land) holidays only when the
  relevant Land is known (``region``); municipal-only holidays are never used — the generator
  asserts that no label depends on them.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta

LAENDER: tuple[str, ...] = (
    "BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV", "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH",
)  # fmt: skip

LAND_NAMES: dict[str, str] = {
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

WEEKDAYS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
WEEKDAYS_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Posting dates up to and including this day use the old 3-day fiction (PostModG, in force 2025-01-01;
# Art. 97 § 1 Abs. 15 EGAO for the AO; § 37 SGB X and § 41 VwVfG have no transitional rule, the
# posting date decides — for 29.–31.12.2024 the earlier 3-day result is also the safe one).
OLD_FICTION_LAST_DAY = date(2024, 12, 31)


def fmt(d: date) -> str:
    """``Tue 2026-09-29`` — the format used in every derivation step."""
    return f"{WEEKDAYS_EN[d.weekday()]} {d.isoformat()}"


# --------------------------------------------------------------------------------------------------
# holidays
# --------------------------------------------------------------------------------------------------


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm, Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - the algorithm's own name
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def national_holidays(year: int) -> dict[date, str]:
    """The nine holidays every Land has (3 October is federal law, the rest are in all 16 Land laws)."""
    easter = easter_sunday(year)
    return {
        date(year, 1, 1): "Neujahr",
        easter - timedelta(days=2): "Karfreitag",
        easter + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        easter + timedelta(days=39): "Christi Himmelfahrt",
        easter + timedelta(days=50): "Pfingstmontag",
        date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 12, 25): "1. Weihnachtstag",
        date(year, 12, 26): "2. Weihnachtstag",
    }


def _buss_und_bettag(year: int) -> date:
    """The Wednesday before 23 November (strictly before)."""
    d = date(year, 11, 22)
    while d.weekday() != 2:
        d -= timedelta(days=1)
    return d


def regional_holidays(year: int, land: str) -> dict[date, str]:
    """Land-wide holidays of one Land (Feiertagsgesetze der Länder), excluding municipal-only days.

    Municipal-only days (Mariä Himmelfahrt in parts of BY, Fronleichnam in parts of SN/TH, the
    Augsburger Friedensfest) are listed in :func:`municipal_only_holidays` and never used for labels.
    """
    easter = easter_sunday(year)
    out: dict[date, str] = {}
    if land in ("BW", "BY", "ST"):
        out[date(year, 1, 6)] = "Heilige Drei Könige"
    if (land == "BE" and year >= 2019) or (land == "MV" and year >= 2023):
        out[date(year, 3, 8)] = "Internationaler Frauentag"
    if land == "BE" and year == 2025:
        out[date(2025, 5, 8)] = "80. Jahrestag der Befreiung (einmalig)"
    if land in ("BW", "BY", "HE", "NW", "RP", "SL"):
        out[easter + timedelta(days=60)] = "Fronleichnam"
    if land == "SL":
        out[date(year, 8, 15)] = "Mariä Himmelfahrt"
    if land == "TH" and year >= 2019:
        out[date(year, 9, 20)] = "Weltkindertag"
    if land in ("BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"):
        out[date(year, 10, 31)] = "Reformationstag"
    if land in ("BW", "BY", "NW", "RP", "SL"):
        out[date(year, 11, 1)] = "Allerheiligen"
    if land == "SN":
        out[_buss_und_bettag(year)] = "Buß- und Bettag"
    return out


def municipal_only_holidays(year: int, region: str | None) -> dict[date, str]:
    """Days that are holidays only in some municipalities of ``region`` (all such days when the Land
    is unknown) — labels must never depend on them."""
    easter = easter_sunday(year)
    out: dict[date, str] = {}
    if region in (None, "BY"):
        out[date(year, 8, 8)] = "Augsburger Friedensfest (nur Stadt Augsburg)"
        out[date(year, 8, 15)] = "Mariä Himmelfahrt (nur Teile Bayerns)"
    if region in (None, "SN", "TH"):
        out[easter + timedelta(days=60)] = "Fronleichnam (nur Teile von Sachsen/Thüringen)"
    return out


_WITH_MUNICIPAL = [False]


@contextmanager
def municipal_holidays_counted() -> Iterator[None]:
    """Temporarily treat municipal-only holidays as holidays everywhere (used to prove that no label
    depends on them)."""
    _WITH_MUNICIPAL[0] = True
    try:
        yield
    finally:
        _WITH_MUNICIPAL[0] = False


def holidays_for(year: int, region: str | None) -> dict[date, str]:
    """Public holidays that count for ``region`` (``None`` = Land unknown → nationwide only)."""
    out = national_holidays(year)
    if region is not None:
        if region not in LAENDER:
            raise ValueError(f"unknown Land {region!r}")
        out.update(regional_holidays(year, region))
    if _WITH_MUNICIPAL[0]:
        for day, name in municipal_only_holidays(year, region).items():
            out.setdefault(day, name)
    return out


def holiday_name(d: date, region: str | None) -> str | None:
    return holidays_for(d.year, region).get(d)


def is_working_day(d: date, region: str | None) -> bool:
    """Mon–Fri and not a public holiday (Saturday is never a working day for § 193 BGB & co.)."""
    return d.weekday() < 5 and holiday_name(d, region) is None


def why_not_working(d: date, region: str | None) -> str:
    parts = []
    if d.weekday() == 5:
        parts.append("a Saturday")
    elif d.weekday() == 6:
        parts.append("a Sunday")
    name = holiday_name(d, region)
    if name:
        parts.append(f"a public holiday ({name})")
    return " and ".join(parts)


def cross_check_with_holidays_package(years: Iterable[int]) -> None:
    """Assert that the hand-written tables above equal the ``holidays`` package (public category).

    Brandenburg's Ostersonntag/Pfingstsonntag are Sundays anyway and are ignored.
    """
    import holidays  # imported lazily: only used for this consistency check

    for year in years:
        package_national = {d for d in holidays.Germany(years=year) if d.weekday() != 6}
        mine_national = {d for d in national_holidays(year) if d.weekday() != 6}
        assert package_national == mine_national, (year, package_national ^ mine_national)
        for land in LAENDER:
            package = {d for d in holidays.Germany(subdiv=land, years=year) if d.weekday() != 6}
            mine = {d for d in holidays_for(year, land) if d.weekday() != 6}
            assert package == mine, (year, land, sorted(package ^ mine))


# --------------------------------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------------------------------


@dataclass
class Derivation:
    """The result date plus the reasoning steps (each step one sentence with its citation)."""

    steps: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.steps.append(text)

    def text(self) -> str:
        return " ".join(f"({i}) {s}" for i, s in enumerate(self.steps, 1))


def shift_to_working_day(d: date, region: str | None, why: Derivation, citation: str) -> date:
    """§ 193 BGB & co.: an end on Sat/Sun/holiday moves to the next working day (loop for chains)."""
    start = d
    while not is_working_day(d, region):
        why.add(f"{fmt(d)} is {why_not_working(d, region)} → next day ({citation}).")
        d += timedelta(days=1)
    if d == start:
        why.add(f"{fmt(d)} is a working day ({calendar_label(region)}), no shift.")
    else:
        why.add(f"{fmt(d)} is the next working day ({calendar_label(region)}).")
    return d


def calendar_label(region: str | None) -> str:
    if region is None:
        return "Land unknown: weekends + nationwide holidays only"
    return f"weekends + nationwide + {region} holidays"


# --------------------------------------------------------------------------------------------------
# period arithmetic (§§ 187, 188 BGB)
# --------------------------------------------------------------------------------------------------


def add_months(d: date, months: int) -> date:
    """§ 188 Abs. 2, 3 BGB: same day number ``months`` later, else the last day of that month."""
    index = d.month - 1 + months
    year, month0 = divmod(index, 12)
    year += d.year
    last = calendar.monthrange(year, month0 + 1)[1]
    return date(year, month0 + 1, min(d.day, last))


def count_days(start_event: date, amount: int, region: str | None, *, saturday_counts: bool) -> list[date]:
    """The counted days of a period in business days (Mon–Fri) or Werktage (Mon–Sat), holidays skipped.

    The event day itself is not counted (§ 187 Abs. 1 BGB); counting starts the next day.
    """
    counted: list[date] = []
    d = start_event
    while len(counted) < amount:
        d += timedelta(days=1)
        if d.weekday() == 6 or holiday_name(d, region):
            continue
        if d.weekday() == 5 and not saturday_counts:
            continue
        counted.append(d)
    return counted


def raw_period_end(event: date, amount: int, unit: str, region: str | None, why: Derivation) -> date:
    """End of a period that starts with an event on ``event`` (not counted), before any shift."""
    if unit == "days":
        end = event + timedelta(days=amount)
        why.add(
            f"§ 187 Abs. 1 BGB: {fmt(event)} is not counted; § 188 Abs. 1 BGB: +{amount} days → {fmt(end)}."
        )
    elif unit == "weeks":
        end = event + timedelta(days=7 * amount)
        why.add(
            f"§ 187 Abs. 1 BGB: {fmt(event)} is not counted; § 188 Abs. 2 BGB: {amount} week(s) end on the same "
            f"weekday → {fmt(end)}."
        )
    elif unit == "months":
        end = add_months(event, amount)
        clipped = end.day != event.day
        why.add(
            f"§ 187 Abs. 1 BGB: {fmt(event)} is not counted; § 188 Abs. 2 BGB: {amount} month(s) end on the day "
            f"with the same number → {fmt(end)}"
            + (" (§ 188 Abs. 3 BGB: that day does not exist, last day of the month)." if clipped else ".")
        )
    elif unit in ("business_days", "werktage"):
        saturday = unit == "werktage"
        counted = count_days(event, amount, region, saturday_counts=saturday)
        end = counted[-1]
        label = "Werktage (Mon–Sat, excl. Sundays and public holidays)" if saturday else (
            "Arbeitstage (Mon–Fri, excl. public holidays)")  # fmt: skip
        skipped = _skipped_holidays(event, end, region)
        why.add(
            f"§ 187 Abs. 1 BGB: {fmt(event)} is not counted; counting {amount} {label} from {fmt(event + timedelta(days=1))}"
            + (f", skipping {skipped}" if skipped else "")
            + f" → day {amount} is {fmt(end)}."
        )
    else:
        raise ValueError(unit)
    return end


def _skipped_holidays(start: date, end: date, region: str | None) -> str:
    names = []
    d = start + timedelta(days=1)
    while d <= end:
        name = holiday_name(d, region)
        if name:
            names.append(f"{name} {d.isoformat()}")
        d += timedelta(days=1)
    return ", ".join(names)


def period_end(
    event: date,
    amount: int,
    unit: str,
    region: str | None,
    why: Derivation,
    *,
    shift: bool,
    shift_citation: str,
) -> date:
    """Raw end (§§ 187, 188 BGB) followed by the working-day shift of the end (if it applies)."""
    end = raw_period_end(event, amount, unit, region, why)
    if not shift:
        return end
    return shift_to_working_day(end, region, why, shift_citation)


# --------------------------------------------------------------------------------------------------
# deemed delivery of posted administrative acts
# --------------------------------------------------------------------------------------------------

SCOPE_CITATION = {
    "ao": "§ 122 Abs. 2 Nr. 1 AO",
    "vwvfg": "§ 41 Abs. 2 S. 1 VwVfG (Land VwVfG)",
    "sgbx": "§ 37 Abs. 2 S. 1 SGB X",
}


def deemed_delivery(posted: date, scope: str, region: str | None, why: Derivation) -> date:
    """Day a posted administrative act counts as notified (Bekanntgabe).

    ``region`` is the recipient's Land for the AO shift (OFD Cottbus 2004); the generator only uses
    region-dependent fiction days when the recipient lives in the authority's Land.
    """
    days = 3 if posted <= OLD_FICTION_LAST_DAY else 4
    fiction = posted + timedelta(days=days)
    rule = (
        "old 3-day rule, posted before 2025-01-01"
        if days == 3
        else "4-day rule for items posted from 2025-01-01 (PostModG)"
    )
    why.add(
        f"Posted {fmt(posted)}; {SCOPE_CITATION[scope]} ({rule}): day {days} after posting = {fmt(fiction)}."
    )
    if scope == "ao":
        if is_working_day(fiction, region):
            why.add(f"{fmt(fiction)} is a working day, so Bekanntgabe is {fmt(fiction)}.")
            return fiction
        return shift_to_working_day(
            fiction, region, why, "§ 108 Abs. 3 AO applied to § 122 Abs. 2 AO, BFH IX R 68/98"
        )
    if not is_working_day(fiction, region):
        why.add(
            f"{fmt(fiction)} is {why_not_working(fiction, region)}, but the fiction day does NOT move outside tax law "
            "(BSG B 14 AS 12/09 R; OVG Lüneburg 4 LA 44/10); only the end of the following period can move."
        )
    else:
        why.add(f"Bekanntgabe {fmt(fiction)} (no shift of the fiction day outside tax law).")
    return fiction


# --------------------------------------------------------------------------------------------------
# contracts (§§ 187 Abs. 2, 188 Abs. 2 Alt. 2 BGB; backward notice computation)
# --------------------------------------------------------------------------------------------------


def term_end(start: date, months: int) -> date:
    """A term starting at the beginning of ``start`` (counted, § 187 Abs. 2) ends the day before the
    same day number ``months`` later (§ 188 Abs. 2 Alt. 2 BGB)."""
    return add_months(start, months) - timedelta(days=1)


def latest_notice_receipt(end: date, amount: int, unit: str) -> date:
    """Latest receipt day D such that a notice period of ``amount unit`` from D ends on or before ``end``.

    Brute force by stepping back from ``end`` — no closed form, so no month-end subtleties can hide.
    Notice periods are never shifted (BGH III ZR 172/04).
    """
    d = end
    while True:
        if unit == "months":
            fwd = add_months(d, amount)
        elif unit == "weeks":
            fwd = d + timedelta(days=7 * amount)
        elif unit == "days":
            fwd = d + timedelta(days=amount)
        else:
            raise ValueError(unit)
        if fwd <= end:
            return d
        d -= timedelta(days=1)
