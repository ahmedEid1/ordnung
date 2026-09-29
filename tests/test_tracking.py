"""Tracking numbers (``drafts.tracking``): the UPU S10 check digit, Deutsche Post's twelve digits, refusals."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ordnung.drafts.tracking import (
    DOMESTIC_NOTE,
    EXAMPLE,
    GROUP_SEPARATOR,
    NOT_A_NUMBER,
    NOT_REGISTERED,
    ONLINE_STAMP_NOTE,
    TrackingError,
    display,
    normalise,
    parse_tracking_number,
    s10_check_digit,
    tracking_info,
)

NB = GROUP_SEPARATOR
LETTERS = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=2, max_size=2)
SERIALS = st.text(alphabet="0123456789", min_size=8, max_size=8)


# --------------------------------------------------------------------------------------------------
# the check digit
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("serial", "check"),
    [
        ("12345678", 5),  # the UPU's own example, RR 123 456 785 DE: sum 204, remainder 6
        ("47312482", 9),  # sum 200, remainder 2
        ("00300000", 0),  # remainder 1: 11 − 1 = 10 becomes 0
        ("00000000", 5),  # remainder 0: 11 becomes 5
        ("01000000", 5),  # remainder 6 gives 5 as well (the check's known blind spot)
        ("00000001", 4),  # remainder 7
    ],
)
def test_s10_check_digit_worked_examples(serial: str, check: int) -> None:
    assert s10_check_digit(serial) == check


def test_s10_check_digit_needs_eight_digits() -> None:
    with pytest.raises(ValueError):
        s10_check_digit("1234567")
    with pytest.raises(ValueError):
        s10_check_digit("1234567X")


@given(LETTERS, SERIALS, LETTERS)
def test_every_serial_has_exactly_one_valid_check_digit(service: str, serial: str, country: str) -> None:
    valid = [digit for digit in range(10) if _accepted(f"{service}{serial}{digit}{country}")]
    assert valid == [s10_check_digit(serial)]


@given(LETTERS, SERIALS, LETTERS)
def test_spacing_and_case_never_change_the_reading(service: str, serial: str, country: str) -> None:
    number = f"{service}{serial}{s10_check_digit(serial)}{country}"
    typed = f" {number[:2].lower()} {number[2:5]}-{number[5:8]}.{number[8:11]} {number[11:].lower()} "
    assert parse_tracking_number(typed).number == number
    assert normalise(display(number)) == number


@given(
    LETTERS, SERIALS, LETTERS, st.integers(min_value=0, max_value=7), st.integers(min_value=1, max_value=9)
)
def test_a_changed_serial_digit_is_caught_unless_the_arithmetic_collides(
    service: str, serial: str, country: str, position: int, shift: int
) -> None:
    good = f"{service}{serial}{s10_check_digit(serial)}{country}"
    changed = serial[:position] + str((int(serial[position]) + shift) % 10) + serial[position + 1 :]
    typo = f"{service}{changed}{s10_check_digit(serial)}{country}"
    # the known limit: remainders 0 and 6 both give 5, so some typos keep a valid check digit
    assert _accepted(typo) == (s10_check_digit(changed) == s10_check_digit(serial))
    assert _accepted(good)


def _accepted(text: str) -> bool:
    try:
        parse_tracking_number(text)
    except TrackingError:
        return False
    return True


# --------------------------------------------------------------------------------------------------
# the policy
# --------------------------------------------------------------------------------------------------


def test_a_registered_s10_number_is_checked_and_grouped() -> None:
    info = parse_tracking_number("rt 123 456 785 de")
    assert (info.number, info.display, info.format, info.checked, info.note) == (
        "RT123456785DE",
        f"RT{NB}123{NB}456{NB}785{NB}DE",
        "s10",
        True,
        None,
    )


def test_a_wrong_check_digit_is_refused() -> None:
    with pytest.raises(TrackingError, match="check digit"):
        parse_tracking_number("RT123456784DE")


def test_two_swapped_digits_are_refused() -> None:
    with pytest.raises(TrackingError, match="mistyped"):
        parse_tracking_number("RT213456785DE")


def test_an_item_that_is_not_registered_is_kept_with_a_note() -> None:
    info = parse_tracking_number("LX123456785DE")
    assert info.checked and info.note == NOT_REGISTERED


def test_twelve_digits_are_kept_unchecked_with_a_note() -> None:
    info = parse_tracking_number("0034 0434 1234")
    assert (info.number, info.display, info.format, info.checked, info.note) == (
        "003404341234",
        f"0034{NB}0434{NB}1234",
        "domestic",
        False,
        DOMESTIC_NOTE,
    )


@pytest.mark.parametrize(
    "typed", ["A0 0123 45D6 0000 123C EC", "a0012345d60000123cec", "A0-0123-45D6-0000-123C-EC"]
)
def test_the_number_of_an_online_stamp_is_kept_unchecked_with_a_note(typed: str) -> None:
    """An Einschreiben bought online (Internetmarke) has the 20 characters next to its square code."""
    info = parse_tracking_number(typed)
    assert (info.number, info.display, info.format, info.checked, info.note) == (
        "A0012345D60000123CEC",
        f"A0{NB}0123{NB}45D6{NB}0000{NB}123C{NB}EC",
        "online_stamp",
        False,
        ONLINE_STAMP_NOTE,
    )


@pytest.mark.parametrize("text", ["A0012345D60000123CE", "A0012345D60000123CEC0", "G0012345D60000123CEC"])
def test_an_online_stamp_number_of_another_length_or_letter_is_refused(text: str) -> None:
    with pytest.raises(TrackingError, match="20 characters next to the square code"):
        parse_tracking_number(text)


def test_the_refusal_names_the_formats_a_person_can_find() -> None:
    assert "12 digits" not in NOT_A_NUMBER and "online" in NOT_A_NUMBER and EXAMPLE in NOT_A_NUMBER


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("RT12345678DE", "8 digits"),  # one digit missing: a typo, never "another format"
        ("RT1234567855DE", "10 digits"),
        ("hello", "doesn't look like a tracking number"),
        ("12345678901", "doesn't look like"),  # eleven digits
        ("1234567890123", "doesn't look like"),  # thirteen digits
        ("", "doesn't look like"),
        ("R" * 100, "doesn't look like"),
    ],
)
def test_anything_else_is_refused_with_what_a_number_looks_like(text: str, message: str) -> None:
    with pytest.raises(TrackingError, match=message):
        parse_tracking_number(text)


def test_a_stored_number_is_shown_even_when_the_policy_changed() -> None:
    assert tracking_info(None) is None
    assert tracking_info("") is None
    kept = tracking_info("RT123456784DE")
    assert kept is not None and not kept.checked and kept.display == "RT123456784DE"
    assert kept.format == "unknown"  # not passed off as a twelve-digit Deutsche Post number
    assert kept.note and "check digit" in kept.note


@pytest.mark.parametrize(
    ("typed", "number"),
    [
        ("RR１２３４５６７８５DE", "RR123456785DE"),  # full-width digits
        ("ＲＲ１２３４５６７８５ＤＥ", "RR123456785DE"),  # full-width letters too
        ("RR١٢٣٤٥٦٧٨٥DE", "RR123456785DE"),  # Arabic-Indic digits
        ("RR۱۲۳۴۵۶۷۸۵DE", "RR123456785DE"),  # Eastern Arabic-Indic (Persian) digits
        ("RR १२३ ४५६ ७८५ DE", "RR123456785DE"),  # Devanagari digits, spaced
        ("１２３４５６７８９０１２", "123456789012"),  # a domestic number in full-width digits
        ("٠٠٣٤ ٠٤٣٤ ١٢٣٤", "003404341234"),
    ],
)
def test_other_digits_are_stored_as_ascii(typed: str, number: str) -> None:
    info = parse_tracking_number(typed)
    assert info.number == number and info.number.isascii()
    assert normalise(info.display) == number


def test_a_wrong_check_digit_in_other_digits_is_still_refused() -> None:
    with pytest.raises(TrackingError, match="check digit"):
        parse_tracking_number("RR١٢٣٤٥٦٧٨٤DE")


def test_letters_that_only_look_latin_are_refused() -> None:
    with pytest.raises(TrackingError):
        parse_tracking_number("РТ123456785DE")  # Cyrillic Er and Te


def test_the_display_never_breaks_inside_the_number() -> None:
    assert " " not in display("RT123456785DE") and display("RT123456785DE").count(NB) == 4
