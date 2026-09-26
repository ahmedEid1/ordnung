"""Calendar and period arithmetic (§§ 187, 188, 193 BGB) — worked examples from the legal research.

Sources in ids/comments refer to the research rules (docs/deadline-rules.md): ``fristbeginn`` =
fristbeginn_ereignistag_nicht_mitgezaehlt, ``fristende`` = fristende_tage_wochen_monate_jahre,
``shift`` = fristende_samstag_sonntag_feiertag_naechster_werktag, ``place`` =
feiertage_massgeblicher_ort, ``arith`` = kuendigungsfrist_period_arithmetic_187_188.
"""

from __future__ import annotations

from datetime import date

import pytest

from ordnung.rules import calendar_de, periods
from ordnung.rules.calendar_de import (
    add_business_days,
    add_werktage,
    holiday_calendar_label,
    is_business_day,
    is_holiday,
    is_werktag,
    next_business_day,
    normalize_region,
    previous_business_day,
)
from ordnung.rules.periods import add_months, add_period, latest_receipt_for, shift_to_business_day

D = date.fromisoformat


# --------------------------------------------------------------------------------------- calendar


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NW", "NW"),
        ("nw", "NW"),
        (" DE-BY ", "BY"),
        ("Nordrhein-Westfalen", "NW"),
        ("NRW", "NW"),
        ("Bavaria", "BY"),
        ("thüringen", "TH"),
        ("Atlantis", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_region(raw: str | None, expected: str | None) -> None:
    assert normalize_region(raw) == expected


def test_holiday_calendar_label() -> None:
    assert holiday_calendar_label(None) == "Germany (nationwide holidays only)"
    assert holiday_calendar_label("nw") == "Nordrhein-Westfalen"
    assert holiday_calendar_label("XX") == "Germany (nationwide holidays only)"


@pytest.mark.parametrize(
    ("day", "region", "holiday"),
    [
        ("2026-10-03", None, True),  # Tag der Deutschen Einheit (a Saturday in 2026)
        ("2026-12-24", None, False),  # Heiligabend is not a public holiday (shift caveats)
        ("2026-12-31", None, False),  # Silvester is not a public holiday (BFH III B 135/17)
        ("2026-11-01", "NW", True),  # Allerheiligen, regional
        ("2026-11-01", None, False),  # ignored when the region is unknown
        ("2026-06-04", "NW", True),  # Fronleichnam NW (place example)
        ("2026-06-04", "HH", False),
        ("2027-03-08", "BE", True),  # Frauentag Berlin (place example)
        ("2027-03-08", "BB", False),
        ("2026-11-18", "SN", True),  # Buß- und Bettag Sachsen (place example)
        ("2026-11-18", "BY", False),
    ],
)
def test_holidays(day: str, region: str | None, holiday: bool) -> None:
    assert is_holiday(D(day), region) is holiday


def test_holiday_names_are_german_on_an_english_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """The holidays library translates names from LANG/LANGUAGE unless told a language; a receipt
    must read the same on every machine."""
    monkeypatch.setenv("LANGUAGE", "en")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    calendar_de._holidays_for.cache_clear()
    try:
        assert calendar_de.holiday_name(D("2026-10-03")) == "Tag der Deutschen Einheit"
        assert calendar_de.holiday_name(D("2026-06-04"), "NW") == "Fronleichnam"
    finally:
        calendar_de._holidays_for.cache_clear()


def test_day_kind_and_regional_lands() -> None:
    assert calendar_de.day_kind(D("2026-10-03")) == "Tag der Deutschen Einheit"
    assert calendar_de.day_kind(D("2026-10-10")) == "Saturday"
    assert calendar_de.day_kind(D("2026-10-11")) == "Sunday"
    assert calendar_de.day_kind(D("2026-10-12")) is None
    assert "NW" in calendar_de.regional_holiday_lands(D("2026-06-04"))
    assert calendar_de.regional_holiday_lands(D("2026-10-03")) == []  # nationwide already
    assert calendar_de.regional_holiday_lands(D("2026-10-12")) == []


def test_bank_business_days() -> None:
    assert calendar_de.is_bank_business_day(D("2026-12-23"))
    assert not calendar_de.is_bank_business_day(D("2026-12-24"))
    assert not calendar_de.is_bank_business_day(D("2026-12-31"))
    assert not calendar_de.is_bank_business_day(D("2026-12-26"))


def test_business_day_and_werktag() -> None:
    assert is_business_day(D("2026-10-02"))
    assert not is_business_day(D("2026-10-10"))  # Saturday
    assert is_werktag(D("2026-10-10"))  # Saturday is a Werktag (BGH VIII ZR 206/04)
    assert not is_werktag(D("2026-10-11"))  # Sunday
    assert not is_werktag(D("2026-10-03"))  # holiday


@pytest.mark.parametrize(
    ("day", "region", "nxt", "prev"),
    [
        ("2026-12-25", None, "2026-12-28", "2026-12-24"),  # shift example: Christmas chain
        ("2026-04-03", None, "2026-04-07", "2026-04-02"),  # shift example: Easter chain
        ("2027-01-01", None, "2027-01-04", "2026-12-31"),  # shift example: Neujahr
        ("2026-12-31", None, "2026-12-31", "2026-12-31"),  # Silvester stays
        ("2026-06-04", "NW", "2026-06-05", "2026-06-03"),  # place example: Fronleichnam NW
        ("2026-06-04", "HH", "2026-06-04", "2026-06-04"),  # place example: no holiday in HH
    ],
)
def test_next_and_previous_business_day(day: str, region: str | None, nxt: str, prev: str) -> None:
    assert next_business_day(D(day), region) == D(nxt)
    assert previous_business_day(D(day), region) == D(prev)


def test_add_business_days_and_werktage() -> None:
    assert add_business_days(D("2026-10-14"), -4) == D("2026-10-08")
    assert add_business_days(D("2026-10-02"), 1) == D("2026-10-05")  # skips Sat holiday + Sunday
    assert add_business_days(D("2026-10-10"), 0) == D("2026-10-10")
    assert add_werktage(D("2026-09-30"), 3) == D("2026-10-05")  # Thu, Fri, (Sat holiday), Mon
    assert add_werktage(D("2026-10-05"), -3) == D("2026-09-30")


# --------------------------------------------------------------------------------------- periods


@pytest.mark.parametrize(
    ("start", "amount", "unit", "expected"),
    [
        ("2026-09-07", 1, "months", "2026-10-07"),  # fristbeginn: Bekanntgabe Mon 07.09 → Wed 07.10
        ("2026-10-31", 1, "months", "2026-11-30"),  # fristbeginn: PZU Sat 31.10 → Mon 30.11
        ("2026-09-21", 10, "days", "2026-10-01"),  # fristende: 10 days
        ("2026-03-31", 1, "months", "2026-04-30"),  # fristende: § 188 Abs. 3 BGB
        ("2026-02-28", 1, "months", "2026-03-28"),  # fristende: no end-of-month rule
        ("2026-11-30", 3, "months", "2027-02-28"),  # fristende: 3 months into February
        ("2026-04-30", 1, "months", "2026-05-30"),  # SPEC § 21: 30 Apr + 1 month = 30 May
        ("2026-01-31", 1, "months", "2026-02-28"),  # arith: 31 Jan → 28 Feb
        ("2028-01-31", 1, "months", "2028-02-29"),  # leap year
        ("2024-02-29", 1, "years", "2025-02-28"),  # rbb example: 29 Feb + 1 year
        ("2026-09-17", 2, "weeks", "2026-10-01"),  # owig: Thu → Thu (§ 43 StPO)
        ("2026-09-29", 2, "weeks", "2026-10-13"),  # arith: Grundversorgung two weeks
        ("2026-09-25", 4, "business_days", "2026-10-01"),
        ("2026-09-30", 3, "werktage", "2026-10-05"),
        ("2026-09-21", 0, "days", "2026-09-21"),
    ],
)
def test_add_period_event_mode(start: str, amount: int, unit: str, expected: str) -> None:
    end, steps = add_period(D(start), amount, unit)  # type: ignore[arg-type]
    assert end == D(expected)
    assert steps[0].rule_id == "bgb_187_1"
    assert steps[-1].date == expected


def test_add_period_cites_188_3_for_short_months() -> None:
    _, steps = add_period(D("2026-01-31"), 1, "months")
    assert steps[-1].rule_id == "bgb_188_3"
    _, steps = add_period(D("2026-01-15"), 1, "months")
    assert steps[-1].rule_id == "bgb_188"
    assert "One month later: Sun 15 Feb 2026" == steps[-1].label


@pytest.mark.parametrize(
    ("start", "amount", "unit", "expected"),
    [
        ("2024-03-01", 24, "months", "2026-02-28"),  # SPEC § 21 example (§ 188 Abs. 2 Alt. 2)
        ("2026-10-01", 1, "years", "2027-09-30"),  # fristbeginn: one year 'ab 01.10.2026'
        ("2024-11-15", 24, "months", "2026-11-14"),  # arith: 24-month term from Fri 15.11.2024
        ("2023-03-01", 12, "months", "2024-02-29"),  # leap year: the day before 1 Mar 2024
        ("2026-01-31", 1, "months", "2026-02-28"),  # § 188 Abs. 3 for a day_start period
        ("2026-01-30", 1, "months", "2026-02-28"),
        ("2026-03-31", 1, "months", "2026-04-30"),  # arithmetic verdict: not 29 Apr
        ("2024-02-29", 12, "months", "2025-02-28"),  # arithmetic verdict: not 27 Feb
        ("2026-01-29", 1, "months", "2026-02-28"),  # arithmetic verdict
        ("2028-01-30", 1, "months", "2028-02-29"),
        ("2026-10-01", 14, "days", "2026-10-14"),
        ("2026-10-01", 2, "weeks", "2026-10-14"),
        ("2026-10-01", 3, "business_days", "2026-10-05"),  # Thu 1, Fri 2, Mon 5 (Sat 3 is a holiday)
        ("2026-10-01", 3, "werktage", "2026-10-05"),
    ],
)
def test_add_period_day_start_mode(start: str, amount: int, unit: str, expected: str) -> None:
    end, steps = add_period(D(start), amount, unit, mode="day_start")  # type: ignore[arg-type]
    assert end == D(expected)
    assert steps[0].rule_id == "bgb_187_2"


@pytest.mark.parametrize(("amount", "mode"), [(-1, "event"), (0, "day_start")])
def test_add_period_rejects_invalid_amounts(amount: int, mode: str) -> None:
    with pytest.raises(ValueError):
        add_period(D("2026-01-01"), amount, "days", mode=mode)  # type: ignore[arg-type]


def test_add_months_negative() -> None:
    assert add_months(D("2027-01-31"), -3) == D("2026-10-31")
    assert add_months(D("2026-03-31"), -1) == D("2026-02-28")


@pytest.mark.parametrize(
    ("end", "amount", "unit", "expected"),
    [
        ("2026-12-31", 3, "months", "2026-09-30"),  # arith / bgb_193_nicht: Oct–Dec
        ("2027-01-31", 3, "months", "2026-10-31"),  # bgb_193_nicht: Sat 31.10, no shift
        ("2027-02-28", 1, "months", "2027-01-31"),  # arith: month-end needs the previous month-end
        ("2026-11-30", 1, "months", "2026-10-31"),  # "one month to the end of the month"
        ("2027-06-30", 3, "months", "2027-03-31"),  # verdict bgb_193_nicht: not 30 Mar
        ("2027-02-28", 3, "months", "2026-11-30"),  # verdict bgb_193_nicht: not 28 Nov
        ("2026-11-14", 1, "months", "2026-10-14"),  # phone contract
        ("2026-11-30", 3, "months", "2026-08-31"),  # liability insurance year
        ("2026-10-13", 2, "weeks", "2026-09-29"),
        ("2026-10-13", 10, "days", "2026-10-03"),
        ("2026-10-13", 0, "months", "2026-10-13"),
        ("2026-10-05", 1, "business_days", "2026-10-04"),  # a notice arriving Sun 4 Oct counts from Mon 5
        ("2026-10-05", 2, "werktage", "2026-10-01"),  # Mon 5 + Fri 2 (Sat 3 is a holiday)
        ("2026-10-05", 0, "business_days", "2026-10-05"),
    ],
)
def test_latest_receipt_for(end: str, amount: int, unit: str, expected: str) -> None:
    result = latest_receipt_for(D(end), amount, unit)  # type: ignore[arg-type]
    assert result == D(expected)
    if amount:
        assert add_period(result, amount, unit)[0] <= D(end)  # type: ignore[arg-type]
        assert add_period(result + (D("2000-01-02") - D("2000-01-01")), amount, unit)[0] > D(end)  # type: ignore[arg-type]


def test_latest_receipt_for_rejects_negative() -> None:
    with pytest.raises(ValueError):
        latest_receipt_for(D("2026-10-13"), -1, "days")


@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        ("2026-03-28", None, "2026-03-30"),  # fristende: Sat → Mon
        ("2027-02-28", None, "2027-03-01"),  # fristende: Sun → Mon
        ("2026-12-25", None, "2026-12-28"),  # shift
        ("2026-12-31", None, "2026-12-31"),  # shift: Silvester no shift
        ("2026-04-03", None, "2026-04-07"),  # shift: Karfreitag → Tue
        ("2027-01-01", None, "2027-01-04"),  # shift: Neujahr
        ("2026-06-04", "NW", "2026-06-05"),  # place: BVA Cologne
        ("2026-06-04", "HH", "2026-06-04"),  # place: Finanzamt Hamburg-Nord
        ("2027-03-08", "BE", "2027-03-09"),  # place: Jobcenter Berlin
        ("2027-03-08", "BB", "2027-03-08"),  # place: Jobcenter Potsdam
        ("2026-11-18", "SN", "2026-11-19"),  # place: AG Leipzig
        ("2026-11-18", "BY", "2026-11-18"),  # place: AG München
    ],
)
def test_shift_to_business_day(raw: str, region: str | None, expected: str) -> None:
    shifted, steps = shift_to_business_day(D(raw), region, "bgb_193")
    assert shifted == D(expected)
    assert steps[0].rule_id == "bgb_193"
    assert ("moves to" in steps[0].label) is (raw != expected)


def test_days_in_month() -> None:
    assert periods.days_in_month(2028, 2) == 29
    assert periods.days_in_month(2026, 2) == 28
