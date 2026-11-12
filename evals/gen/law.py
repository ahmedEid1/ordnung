"""Legal date arithmetic for the benchmark labels, from the statutes and decisions cited below.

The labels come from this small, readable module and from nothing else. Every function returns the date *and* the
human-readable steps that justify it; the steps end up verbatim in the manifest (``derivation``) so a reviewer can
check each label by hand. Where a rule is one of the benchmark's labelling conventions, its id in
``evals/generate.py``'s ``CONVENTIONS`` is named; "disputed" marks a reading that another defensible reading
contests.

Legal basis:

* Period start: the event day is not counted (§ 187 Abs. 1 BGB; § 108 Abs. 1 AO; § 31 Abs. 1 VwVfG;
  § 26 Abs. 1 SGB X; § 43 StPO i.V.m. § 46 OWiG).
* Period end: weeks/months end on the day with the same weekday name / day number as the event
  day; if that day number does not exist, on the last day of the month (§ 188 Abs. 2, 3 BGB).
* End shift: an end on Saturday, Sunday or a public holiday moves to the next working day (§ 193
  BGB; § 108 Abs. 3 AO; § 31 Abs. 3 VwVfG; § 26 Abs. 3 SGB X; § 64 Abs. 3 SGG; § 43 Abs. 2 StPO).
  Never for notice periods (BGH III ZR 172/04; c22, disputed) and never for appointments.
* Posted administrative acts: deemed notified on the 4th day after posting for items posted from
  2025-01-01, the 3rd day before (PostModG; Art. 97 § 1 Abs. 15 EGAO), counted from the stated posting
  day, else the letter date (c02, disputed). Tax law (AO) moves that day to the next working day
  (§ 108 Abs. 3 AO, BFH IX R 68/98); VwVfG and SGB X do not (BSG B 14 AS 12/09 R; OVG Lüneburg
  4 LA 44/10; c03, disputed).
* A Land authority's decision (scope ``vwvfg``) counts its own Land's day, as the Land's text in
  ``evals/law/laender.txt`` gives it (``LAND_VWVFG_*`` below): Hessen the 3rd day, Hamburg and
  Baden-Württemberg the 4th only from a later day, and in Baden-Württemberg, Bayern and
  Mecklenburg-Vorpommern a procedure begun before the switch keeps the 3rd. A Land whose text could not be
  read is refused (c07), and so is a decision sent other than by post.
* Holidays: weekend + the nine nationwide holidays always; regional (Land) holidays only when the
  relevant Land is known (``region``; c04); municipal-only holidays are never used — the generator
  asserts that no label depends on them (c05).
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
# Art. 97 § 1 Abs. 15 EGAO for the AO; § 37 SGB X and the federal § 41 VwVfG have no transitional rule,
# the posting date decides — for 29.–31.12.2024 the earlier 3-day result is also the safe one). A Land
# authority's day is its Land's own (the LAND_VWVFG_* tables below).
OLD_FICTION_LAST_DAY = date(2024, 12, 31)

# --------------------------------------------------------------------------------------------------
# the Länder: the day a posted decision of a Land authority counts as delivered (evals/law/laender.txt)
# --------------------------------------------------------------------------------------------------

#: The day from which a Land's authorities count the 4th day after posting (the 3rd day before it), as each Land's
#: block in evals/law/laender.txt gives it: BY (Art. 41 Abs. 2 and Art. 98 BayVwVfG), NW (§ 41 Abs. 2 VwVfG NRW, in
#: force 1 January 2025), MV (§ 41 Abs. 2 as amended by Art. 1 Nr. 14 of the act of 11 December 2024, in force
#: 1 January 2025 under its Art. 4), SH (§ 110 Abs. 2 LVwG as amended by Art. 1 Nr. 2 of the act of 13 December 2024,
#: in force 1 January 2025 under its Art. 2 Abs. 2), BE, BB, NI and SN (their acts apply the federal VwVfG, whose
#: § 41 Abs. 2 counts the 4th day from 1 January 2025), TH (§ 1 ThürVwVfG applies the federal VwVfG; the act is in
#: force from 1 January 2025 under Art. 90), HH (the Zwölftes Gesetz zur Änderung des HmbVwVfG, HmbGVBl. Nr. 17 of
#: 13 May 2025, in force the day after under Art. 54 of Hamburg's constitution) and BW (§ 102b LVwVfG: the wording
#: up to 6 February 2025 for a procedure begun before 7 February 2025).
LAND_VWVFG_FOURTH_DAY_FROM: dict[str, date] = {
    **dict.fromkeys(("BB", "BE", "BY", "MV", "NI", "NW", "SH", "SN", "TH"), date(2025, 1, 1)),
    "HH": date(2025, 5, 14),
    "BW": date(2025, 2, 7),
}
#: Länder whose authorities count the 3rd day after posting: Hessen (§ 41 Abs. 2 HVwVfG).
LAND_VWVFG_THIRD_DAY: frozenset[str] = frozenset({"HE"})
#: Länder that keep their old wording, and so the 3rd day, for a procedure begun before their switch and not
#: finished, and that switch: BW (§ 102b LVwVfG), BY (Art. 98 BayVwVfG), MV (§ 120a VwVfG M-V). Elsewhere the
#: posting day decides (NW: § 97 VwVfG NRW applies the law in force to each step; TH: § 8 Abs. 1 ThürVwVfG).
LAND_VWVFG_OLD_PROCEDURES: dict[str, date] = {
    "BW": date(2025, 2, 7),
    "BY": date(2025, 1, 1),
    "MV": date(2025, 1, 1),
}
LAND_VWVFG_OLD_PROCEDURE_RULE: dict[str, str] = {
    "BW": "§ 102b LVwVfG",
    "BY": "Art. 98 BayVwVfG",
    "MV": "§ 120a VwVfG M-V",
}
#: Länder whose text could not be read (evals/law/SOURCES.md): no letter of one of their authorities can be dated.
LAND_VWVFG_UNVERIFIED: frozenset[str] = frozenset({"HB", "RP", "SL", "ST"})
#: Each verified Land's provision for the day its authorities' posted decision counts as delivered.
LAND_VWVFG_PROVISION: dict[str, str] = {
    "BB": "§ 1 Abs. 1 VwVfGBbg with § 41 Abs. 2 S. 1 VwVfG",
    "BE": "§ 1 Abs. 1 of Berlin's Gesetz über das Verfahren der Berliner Verwaltung with § 41 Abs. 2 S. 1 VwVfG",
    "BW": "§ 41 Abs. 2 S. 1 LVwVfG",
    "BY": "Art. 41 Abs. 2 S. 1 BayVwVfG",
    "HE": "§ 41 Abs. 2 S. 1 HVwVfG",
    "HH": "§ 41 Abs. 2 S. 1 HmbVwVfG",
    "MV": "§ 41 Abs. 2 S. 1 VwVfG M-V",
    "NI": "§ 1 Abs. 1 NVwVfG with § 41 Abs. 2 S. 1 VwVfG",
    "NW": "§ 41 Abs. 2 S. 1 VwVfG NRW",
    "SH": "§ 110 Abs. 2 S. 1 LVwG",
    "SN": "§ 1 SächsVwVfZG with § 41 Abs. 2 S. 1 VwVfG",
    "TH": "§ 1 Abs. 1 ThürVwVfG with § 41 Abs. 2 S. 1 VwVfG",
}


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
    if land == "BE" and year == 2028:
        out[date(2028, 6, 17)] = "75. Jahrestag des Volksaufstandes vom 17. Juni 1953 (einmalig)"
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
    from holidays.countries.germany import Germany  # imported lazily: only used for this consistency check

    for year in years:
        package_national = {d for d in Germany(years=year) if d.weekday() != 6}
        mine_national = {d for d in national_holidays(year) if d.weekday() != 6}
        assert package_national == mine_national, (year, package_national ^ mine_national)
        for land in LAENDER:
            package = {d for d in Germany(subdiv=land, years=year) if d.weekday() != 6}
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

_EARLIER_WORDS = [False]


@contextmanager
def earlier_splits_words() -> Iterator[None]:
    """While the five earlier splits are built: a Land authority's 4th-day step keeps the words those splits' letters
    were written with (the federal rule's, "(Land VwVfG) (4-day rule for items posted from 2025-01-01 (PostModG))"),
    so they stay byte for byte. Outside it the step names the Land's own provision and the day its 4th day starts."""
    before = _EARLIER_WORDS[0]
    _EARLIER_WORDS[0] = True
    try:
        yield
    finally:
        _EARLIER_WORDS[0] = before


def in_earlier_splits_words() -> bool:
    """Whether :func:`earlier_splits_words` is in force."""
    return _EARLIER_WORDS[0]


def _land_fourth_day_rule(land: str, procedure_began: date | None) -> str:
    """Why a Land authority's decision counts the 4th day: the Land's provision and the day its 4th day starts, and
    in BW, BY and MV that the procedure began on or after the switch, or that the letter states no earlier start."""
    start = LAND_VWVFG_FOURTH_DAY_FROM[land]
    rule = f"{LAND_VWVFG_PROVISION[land]} ({LAND_NAMES[land]} counts the 4th day for items posted from {start.isoformat()}"
    switch = LAND_VWVFG_OLD_PROCEDURES.get(land)
    if switch is not None and procedure_began is None:
        rule += f"; the letter states no procedure begun before {switch.isoformat()}"
    elif switch is not None and procedure_began is not None:
        rule += f"; the procedure began {fmt(procedure_began)}, not before {switch.isoformat()}"
    return rule + ")"


def _land_vwvfg_rule(posted: date, land: str | None, procedure_began: date | None) -> str | None:
    """Why a Land authority's decision posted on ``posted`` counts the 3rd day where the federal rule counts the
    4th (Hessen; Hamburg and Baden-Württemberg before their switch; an older procedure in BW, BY or MV), or None
    when it counts the federal rule's day. Refuses a decision with no Land or from a Land with no verified text."""
    if land is None:
        raise ValueError(
            "a Land authority's decision (scope vwvfg) needs the authority's Land (land=...): the day it counts as "
            "delivered is that Land's own rule (evals/law/laender.txt)"
        )
    if land not in LAENDER:
        raise ValueError(f"unknown Land {land!r}")
    if land in LAND_VWVFG_UNVERIFIED:
        raise ValueError(
            f"{LAND_NAMES[land]} ({land}): evals/law/laender.txt holds no verified text of its rule on when its "
            "authorities' decisions count as delivered, so no letter from one of them can be dated; take the "
            "authority from a Land whose text is there"
        )
    provision, name = LAND_VWVFG_PROVISION[land], LAND_NAMES[land]
    if posted <= OLD_FICTION_LAST_DAY:
        return None  # every Land counted the 3rd day then: the old rule's words
    if land in LAND_VWVFG_THIRD_DAY:
        return f"{provision} ({name} keeps the 3-day rule, evals/law/laender.txt)"
    start = LAND_VWVFG_FOURTH_DAY_FROM[land]
    if posted < start:
        return (
            f"{provision} (Land VwVfG: {name} counts the 4th day only for items posted from {start.isoformat()}, "
            "so the old 3-day rule)"
        )
    switch = LAND_VWVFG_OLD_PROCEDURES.get(land)
    if switch is not None and procedure_began is not None and procedure_began < switch:
        return (
            f"{provision} in its wording before {switch.isoformat()} ({LAND_VWVFG_OLD_PROCEDURE_RULE[land]}: the "
            f"procedure began {fmt(procedure_began)}, before {switch.isoformat()}, so the old 3-day rule)"
        )
    return None


def deemed_delivery(
    posted: date,
    scope: str,
    region: str | None,
    why: Derivation,
    *,
    land: str | None = None,
    procedure_began: date | None = None,
    channel: str = "post",
) -> date:
    """Day a posted administrative act counts as notified (Bekanntgabe).

    ``region`` is the Land whose holidays count, the recipient's Land for the AO shift (OFD Cottbus 2004); the
    generator only uses region-dependent fiction days when the recipient lives in the authority's Land. ``land`` is
    the authority's Land: a Land authority's decision (scope ``vwvfg``) must name it, and counts that Land's own day
    (the ``LAND_VWVFG_*`` tables); tax and social-law decisions do not depend on it. ``procedure_began`` is the day
    the administrative procedure began, when the letter states it: in BW, BY and MV a procedure begun before the
    Land's switch keeps the 3rd day. ``channel`` is how the decision was sent: only ``"post"`` has a rule here.
    """
    if channel != "post":
        brandenburg = (
            " (in Brandenburg an e-mailed decision counts from the day it arrived when that can be shown, "
            "§ 7 VwVfGBbg)"
            if land == "BB"
            else ""
        )
        raise ValueError(
            f"law.py dates decisions sent by post only: there is no rule here for one sent {channel!r}{brandenburg}"
        )
    if procedure_began is not None and scope != "vwvfg":
        raise ValueError(
            "a procedure's start decides the day only for a Land authority's decision (scope vwvfg)"
        )
    if procedure_began is not None and procedure_began > posted:
        raise ValueError(f"the procedure began {procedure_began}, after the decision was posted on {posted}")
    land_rule = _land_vwvfg_rule(posted, land, procedure_began) if scope == "vwvfg" else None
    if land_rule is not None:
        days = 3
        fiction = posted + timedelta(days=days)
        why.add(f"Posted {fmt(posted)}; {land_rule}: day {days} after posting = {fmt(fiction)}.")
    elif scope == "vwvfg" and land is not None and posted > OLD_FICTION_LAST_DAY and not _EARLIER_WORDS[0]:
        days = 4
        fiction = posted + timedelta(days=days)
        why.add(
            f"Posted {fmt(posted)}; {_land_fourth_day_rule(land, procedure_began)}: day {days} after posting = "
            f"{fmt(fiction)}."
        )
    else:
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


# --------------------------------------------------------------------------------------------------
# the newkinds letters: court orders in the Mahnverfahren, dismissals, tenancy letters, withdrawal
# (each function from the statute texts in evals/law/ only; its norms are named in its docstring)
# --------------------------------------------------------------------------------------------------


def last_day_of_month(year: int, month: int) -> date:
    """The last day of a calendar month (§ 192 BGB: "Ende des Monats" is its last day)."""
    return date(year, month, calendar.monthrange(year, month)[1])


def _zpo_two_weeks(served: date, region: str | None, why: Derivation, period: str) -> date:
    """Two weeks from a Zustellung under the ZPO: § 222 Abs. 1 ZPO with §§ 187 Abs. 1, 188 Abs. 2 BGB, and an end on a
    Saturday, Sunday or general holiday moved to the next working day (§ 222 Abs. 2 ZPO)."""
    why.add(
        f"Zustellung {fmt(served)}, the day the service note on the document states (§ 180 S. 3 ZPO); {period}."
    )
    end = raw_period_end(served, 2, "weeks", region, why)
    return shift_to_working_day(end, region, why, "§ 222 Abs. 2 ZPO")


def mahnbescheid_objection_end(served: date, region: str | None, why: Derivation) -> date:
    """The end of the period a Mahnbescheid sets for paying or objecting (Widerspruch).

    Legal basis: § 692 Abs. 1 Nr. 3 ZPO (two weeks from the Zustellung of the Mahnbescheid), § 694 Abs. 1 ZPO (the
    Widerspruch is possible as long as no Vollstreckungsbescheid has been issued, which sets no fixed date), § 180 S. 3
    ZPO (the day of the Zustellung), § 222 Abs. 1 ZPO with §§ 187 Abs. 1, 188 Abs. 2 BGB, § 222 Abs. 2 ZPO."""
    return _zpo_two_weeks(served, region, why, "§ 692 Abs. 1 Nr. 3 ZPO: two weeks from the Zustellung")


def vollstreckungsbescheid_objection_end(served: date, region: str | None, why: Derivation) -> date:
    """The end of the Einspruch period against a Vollstreckungsbescheid.

    Legal basis: § 700 Abs. 1 ZPO (the Vollstreckungsbescheid stands for a Versäumnisurteil), § 339 Abs. 1 ZPO (two
    weeks, a Notfrist, from the Zustellung), § 180 S. 3 ZPO, § 222 Abs. 1 ZPO with §§ 187 Abs. 1, 188 Abs. 2 BGB,
    § 222 Abs. 2 ZPO."""
    return _zpo_two_weeks(
        served, region, why, "§ 700 Abs. 1 with § 339 Abs. 1 ZPO: two weeks from the Zustellung (Notfrist)"
    )


def employer_notice_end(received: date, *, years: int, probation: bool, why: Derivation) -> date:
    """The day an employment ends on the employer's ordinary notice that the employee received on ``received``, after
    ``years`` full years of employment.

    Legal basis: § 622 Abs. 3 BGB (in an agreed probation of at most six months: two weeks, to any day), § 622 Abs. 1
    BGB (four weeks to the 15th or to the end of a calendar month), § 622 Abs. 2 S. 1 Nr. 1–7 BGB (the employer's longer
    periods after 2, 5, 8, 10, 12, 15 and 20 years, to the end of a calendar month), § 623 BGB (written form), § 130
    Abs. 1 S. 1 BGB (effective on receipt), §§ 187 Abs. 1, 188 Abs. 2 BGB. A notice period is not moved by § 193 BGB:
    no declaration is due at its end."""
    if probation:
        end = received + timedelta(days=14)
        why.add(
            f"§ 622 Abs. 3 BGB (probation): two weeks; § 187 Abs. 1 BGB: {fmt(received)} is not counted; § 188 Abs. 2 "
            f"BGB → {fmt(end)}."
        )
        return end
    steps = ((20, 7), (15, 6), (12, 5), (10, 4), (8, 3), (5, 2), (2, 1))
    months = next((m for y, m in steps if years >= y), 0)
    if months == 0:
        earliest = received + timedelta(days=28)
        why.add(
            f"§ 622 Abs. 1 BGB: four weeks to the 15th or the end of a month; § 187 Abs. 1 BGB: {fmt(received)} is not "
            f"counted; § 188 Abs. 2 BGB: the four weeks end {fmt(earliest)}."
        )
        mid = date(earliest.year, earliest.month, 15)
        end = mid if earliest <= mid else last_day_of_month(earliest.year, earliest.month)
        why.add(f"The first 15th or month end not before it: {fmt(end)}.")
        return end
    earliest = add_months(received, months)
    why.add(
        f"§ 622 Abs. 2 S. 1 BGB ({years} years of employment): {months} month(s) to the end of a calendar month; "
        f"§ 187 Abs. 1 BGB: {fmt(received)} is not counted; § 188 Abs. 2 BGB: the period ends {fmt(earliest)}."
    )
    end = last_day_of_month(earliest.year, earliest.month)
    why.add(f"The first month end not before it: {fmt(end)}.")
    return end


def dismissal_claim_end(received: date, region: str | None, why: Derivation) -> date:
    """The last day to bring the action of § 4 KSchG against a written dismissal received on ``received``.

    Legal basis: § 4 S. 1 KSchG (three weeks from the receipt of the written dismissal, whatever the ground of
    invalidity), § 7 KSchG (otherwise the dismissal counts as valid from the start), § 130 Abs. 1 S. 1 BGB, §§ 187
    Abs. 1, 188 Abs. 2 BGB. The statute texts here do not say which rule would move an end on a Saturday, Sunday or
    holiday for this action, so only an end on a working day in ``region`` is dated (ValueError otherwise)."""
    end = received + timedelta(days=21)
    why.add(
        f"§ 4 S. 1 KSchG: three weeks from receipt of the written dismissal on {fmt(received)}; § 187 Abs. 1 BGB: that "
        f"day is not counted; § 188 Abs. 2 BGB → {fmt(end)}."
    )
    if not is_working_day(end, region):
        raise ValueError(
            f"§ 4 KSchG period ends on {fmt(end)}, {why_not_working(end, region)}: not dated here"
        )
    why.add(f"{fmt(end)} is a working day ({calendar_label(region)}), so no shift question arises.")
    return end


def _third_werktag(year: int, month: int, region: str | None, *, saturday_counts: bool) -> date:
    """The third Werktag of a month (§ 573c Abs. 1 S. 1 BGB): Sundays and public holidays never count; whether a
    Saturday does is the caller's reading."""
    counted = count_days(date(year, month, 1) - timedelta(days=1), 3, region, saturday_counts=saturday_counts)
    return counted[-1]


def landlord_notice_end(
    received: date, *, years: int, region: str | None, why: Derivation, saturday_counts: bool = True
) -> date:
    """The day a residential lease ends on the landlord's ordinary notice received on ``received``, when the flat was
    handed over ``years`` full years before.

    Legal basis: § 573c Abs. 1 S. 1 BGB (notice by the third Werktag of a calendar month to the end of the month after
    next), § 573c Abs. 1 S. 2 BGB (three months longer for the landlord after five and again after eight years since
    the handover), § 573c Abs. 4 BGB, § 130 Abs. 1 S. 1 BGB, § 192 BGB. A notice received after the third Werktag of a
    month counts for the next month. ``saturday_counts`` is the reading of "Werktag" (Monday to Saturday, or Monday to
    Friday): the caller checks that both give the same day."""
    year, month = received.year, received.month
    while received > _third_werktag(year, month, region, saturday_counts=saturday_counts):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    third = _third_werktag(year, month, region, saturday_counts=saturday_counts)
    extra = 3 * ((years >= 5) + (years >= 8))
    end_month = date(year, month, 1)
    end_month = add_months(end_month, 2 + extra)
    end = last_day_of_month(end_month.year, end_month.month)
    why.add(
        f"Notice received {fmt(received)}; § 573c Abs. 1 S. 1 BGB: the first month whose third Werktag "
        f"({fmt(third)}) is not before it is {date(year, month, 1).strftime('%Y-%m')}, so the end of the month after next"
        + (
            f", plus {extra} months for {years} years since the handover (§ 573c Abs. 1 S. 2 BGB)"
            if extra
            else ""
        )
        + f" → lease ends {fmt(end)} (§ 192 BGB)."
    )
    return end


def tenant_objection_last_day(lease_end: date, why: Derivation, *, same_day_number: bool = False) -> date:
    """The last day the tenant's Widerspruch must reach the landlord: two months before the lease ends.

    Legal basis: § 574b Abs. 2 S. 1 BGB (spätestens zwei Monate vor der Beendigung), § 574b Abs. 1 S. 1 BGB (Textform),
    § 574 BGB, §§ 187, 188 Abs. 2, 3 BGB applied backward from the end (§ 186 BGB). A lease that ends on a month's last
    day ends two months before on the last day of that month (``latest_notice_receipt``); ``same_day_number`` takes the
    other reading, the day with the lease end's day number two months earlier (or that month's last day)."""
    if same_day_number:
        day = add_months(lease_end, -2)
        why.add(f"§ 574b Abs. 2 S. 1 BGB, counted back to the same day number: {fmt(day)}.")
        return day
    day = latest_notice_receipt(lease_end, 2, "months")
    why.add(
        f"§ 574b Abs. 2 S. 1 BGB: two months before the lease ends on {fmt(lease_end)}; counted back (§§ 187, 188 "
        f"Abs. 2, 3 BGB): the latest day from which two months still end by then is {fmt(day)}."
    )
    return day


def rent_increase_consent_end(
    received: date, region: str | None, why: Derivation, *, shift: bool = True
) -> date:
    """The end of the tenant's period to consent to a rent increase up to the local comparative rent.

    Legal basis: § 558b Abs. 2 S. 1 BGB (until the end of the second calendar month after the request's receipt),
    § 558a Abs. 1 BGB (Textform), § 130 Abs. 1 S. 1 BGB, § 192 BGB, § 193 BGB (the consent is a declaration due within a
    period, so an end on a Saturday, Sunday or holiday moves to the next working day; ``shift=False`` takes the
    reading that it stays)."""
    month = add_months(date(received.year, received.month, 1), 2)
    end = last_day_of_month(month.year, month.month)
    why.add(
        f"Request received {fmt(received)}; § 558b Abs. 2 S. 1 BGB: the second calendar month after that month ends "
        f"{fmt(end)}."
    )
    if not shift:
        return end
    return shift_to_working_day(end, region, why, "§ 193 BGB")


def rent_increase_effective(received: date, why: Derivation) -> date:
    """The day from which a consented rent increase is owed: the start of the third calendar month after receipt.

    Legal basis: § 558b Abs. 1 BGB, § 558 Abs. 1 BGB (the rent unchanged for 15 months at that day), § 192 BGB."""
    start = add_months(date(received.year, received.month, 1), 3)
    why.add(
        f"§ 558b Abs. 1 BGB: the third calendar month after receipt ({fmt(received)}) begins {fmt(start)}."
    )
    return start


def operating_costs_statement_due(period_end: date, why: Derivation) -> date:
    """The last day a landlord can give the tenant the operating-cost statement for a period that ends on
    ``period_end`` (a month's last day).

    Legal basis: § 556 Abs. 3 S. 1, 2 BGB (yearly statement, given by the end of the twelfth month after the period),
    § 556 Abs. 3 S. 3 BGB (later, a Nachforderung is excluded unless the landlord is not responsible for the delay),
    § 192 BGB."""
    if period_end != last_day_of_month(period_end.year, period_end.month):
        raise ValueError(
            f"billing period ending {period_end}: only periods ending on a month's last day are dated"
        )
    month = add_months(date(period_end.year, period_end.month, 1), 12)
    due = last_day_of_month(month.year, month.month)
    why.add(
        f"§ 556 Abs. 3 S. 2 BGB: period ended {fmt(period_end)}; the twelfth month after it ends {fmt(due)}."
    )
    return due


def operating_costs_objection_end(
    received: date, region: str | None, why: Derivation, *, calendar_months: bool = False
) -> date:
    """The last day for the tenant's objections (Einwendungen) to an operating-cost statement received on
    ``received``.

    Legal basis: § 556 Abs. 3 S. 5, 6 BGB (by the end of the twelfth month after receipt), § 130 Abs. 1 S. 1 BGB,
    §§ 187 Abs. 1, 188 Abs. 2, 3 BGB, § 193 BGB (an end on a Saturday, Sunday or holiday moves to the next working
    day). ``calendar_months`` takes the other reading: the end of the twelfth calendar month after the month of
    receipt (§ 192 BGB), not moved."""
    if calendar_months:
        month = add_months(date(received.year, received.month, 1), 12)
        end = last_day_of_month(month.year, month.month)
        why.add(
            f"§ 556 Abs. 3 S. 5 BGB read by calendar months: the twelfth month after receipt ends {fmt(end)}."
        )
        return end
    why.add(f"Statement received {fmt(received)}; § 556 Abs. 3 S. 5 BGB: twelve months.")
    end = raw_period_end(received, 12, "months", region, why)
    return shift_to_working_day(end, region, why, "§ 193 BGB")


def withdrawal_end(start: date, region: str | None, why: Derivation, *, start_rule: str) -> date:
    """The last day to send a consumer's withdrawal (Widerruf) from a contract made away from business premises or at
    a distance, when the withdrawal information was given on paper by ``start``.

    Legal basis: § 355 Abs. 1 S. 5 BGB (sending in time is enough), § 355 Abs. 2 BGB (14 days from conclusion unless
    otherwise provided), § 356 Abs. 2 Nr. 1 a BGB (sale of goods: from receipt of the goods), § 356 Abs. 2 Nr. 2 BGB
    (electricity, gas: from conclusion), § 356 Abs. 3 S. 1 BGB with Art. 246a § 1 Abs. 2 S. 1 Nr. 1 EGBGB (not before
    the information), §§ 187 Abs. 1, 188 Abs. 1 BGB, § 193 BGB (the withdrawal is a declaration due within a period).
    ``start_rule`` names the start that applies."""
    why.add(
        f"{start_rule}: the period starts with {fmt(start)}; the information was handed over on paper that day."
    )
    end = raw_period_end(start, 14, "days", region, why)
    return shift_to_working_day(end, region, why, "§ 193 BGB")
