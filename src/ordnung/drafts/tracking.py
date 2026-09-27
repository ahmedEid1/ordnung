"""Tracking numbers of posted letters (Sendungsnummern), read by one short written policy (ADR 0007).

* **Normalised first.** Compatibility forms are folded (NFKC: full-width ``ＲＴ１２３`` is ``RT123``),
  every other decimal digit is written as its ASCII digit (Arabic-Indic ``١٢٣`` is ``123``), spaces,
  dots, hyphens and slashes are dropped and letters upper-cased, so ``rt 123 456 785 de`` and
  ``RT123456785DE`` are the same number. Only ASCII is stored, so the number can be pasted into a
  tracking page and matches what the person types later.
* **UPU S10** — the international format Deutsche Post prints on Einschreiben receipts: two letters,
  eight digits, a check digit and two letters for the country (``RT 123 456 785 DE``). It is accepted
  only with the right check digit: the eight digits are weighted 8 6 4 2 3 5 9 7, the sum is taken
  modulo 11 and the check digit is 11 minus the remainder, where 10 becomes 0 and 11 becomes 5. A wrong
  check digit is refused (a digit was mistyped, or two were swapped). A number that does not start
  with ``R`` (registered items do) is kept with a note.
* **Twelve digits** — Deutsche Post also prints purely numeric numbers. Ordnung knows no published
  check rule for them, so they are kept as typed, with a note to compare them with the receipt.
* **Anything else is refused**, with what a number looks like. Something shaped like S10 (letters at
  both ends) of the wrong length is a typo, never "some other format".

Display: the groups are joined with no-break spaces (U+00A0), so a number never breaks across lines
in running text; the stored number has no spaces at all.

Limits: a valid check digit shows the number is well-formed, not that it belongs to this letter; the
S10 check misses some mistakes (remainders 0 and 6 both give 5); the country letters are not checked
against a list of countries; twelve-digit numbers are not checked at all.
"""

from __future__ import annotations

import re
import unicodedata

from ordnung.models import TrackingInfo

WEIGHTS = (8, 6, 4, 2, 3, 5, 9, 7)
MAX_INPUT = 64
_SEPARATORS = re.compile(r"[\s.\-/]+")
_S10 = re.compile(r"^([A-Z]{2})([0-9]{8})([0-9])([A-Z]{2})$", re.ASCII)
_S10_SHAPE = re.compile(r"^[A-Z]{2}[0-9]+[A-Z]{2}$", re.ASCII)
_DOMESTIC = re.compile(r"^[0-9]{12}$", re.ASCII)
_SERIAL = re.compile(r"[0-9]{8}", re.ASCII)
#: joins the groups of a displayed number (no-break space: it never breaks inside the number)
GROUP_SEPARATOR = "\u00a0"

EXAMPLE = "RT 123 456 785 DE"
NOT_A_NUMBER = (
    f"This doesn't look like a tracking number. Type it as it is on your posting receipt: two letters, "
    f"nine digits and two letters (like {EXAMPLE}), or the 12 digits Deutsche Post prints."
)
WRONG_LENGTH = (
    "A number like this has two letters, nine digits and two letters (like {example}) — "
    "this one has {digits} digits. Check it against your receipt."
)
WRONG_CHECK_DIGIT = (
    "The last digit doesn't match the others (its check digit), so a digit is probably mistyped. "
    "Check the number against your receipt."
)
NOT_REGISTERED = (
    "Numbers of registered letters (Einschreiben) usually start with R — check that this is the right one."
)
DOMESTIC_NOTE = "Ordnung can't check this kind of number — compare it digit by digit with your receipt."


class TrackingError(ValueError):
    """A tracking number that was refused; the message is written for the person."""


def _ascii_digit(character: str) -> str:
    return (
        str(unicodedata.decimal(character))
        if character.isdecimal() and not character.isascii()
        else character
    )


def normalise(text: str) -> str:
    """``text`` in ASCII without separators, in upper case (``rt 123 456 785 de`` → ``RT123456785DE``,
    ``ＲＴ１２３`` → ``RT123``, ``١٢٣`` → ``123``)."""
    folded = "".join(_ascii_digit(character) for character in unicodedata.normalize("NFKC", text))
    return _SEPARATORS.sub("", folded).upper()


def s10_check_digit(serial: str) -> int:
    """The UPU S10 check digit of eight digits (``"12345678"`` → ``5``)."""
    if not _SERIAL.fullmatch(serial):
        raise ValueError("an S10 serial number has exactly eight digits")
    remainder = sum(int(digit) * weight for digit, weight in zip(serial, WEIGHTS, strict=True)) % 11
    check = 11 - remainder
    return {10: 0, 11: 5}.get(check, check)


def display(number: str) -> str:
    """A normalised number grouped for reading: ``RT 123 456 785 DE`` or ``1234 5678 9012`` (the
    groups joined by :data:`GROUP_SEPARATOR`)."""
    if _S10.match(number):
        groups = [number[:2], number[2:5], number[5:8], number[8:11], number[11:]]
    elif _DOMESTIC.match(number):
        groups = [number[i : i + 4] for i in range(0, 12, 4)]
    else:
        return number
    return GROUP_SEPARATOR.join(groups)


def parse_tracking_number(text: str) -> TrackingInfo:
    """Read a tracking number by the module's policy; raises :class:`TrackingError` when it is refused."""
    if len(text) > MAX_INPUT:
        raise TrackingError(NOT_A_NUMBER)
    number = normalise(text)
    s10 = _S10.match(number)
    if s10 is not None:
        service, serial, check, _country = s10.groups()
        if s10_check_digit(serial) != int(check):
            raise TrackingError(WRONG_CHECK_DIGIT)
        note = None if service.startswith("R") else NOT_REGISTERED
        return TrackingInfo(number=number, display=display(number), format="s10", checked=True, note=note)
    if _DOMESTIC.match(number):
        return TrackingInfo(
            number=number, display=display(number), format="domestic", checked=False, note=DOMESTIC_NOTE
        )
    if _S10_SHAPE.match(number):
        digits = sum(character.isdigit() for character in number)
        raise TrackingError(WRONG_LENGTH.format(example=EXAMPLE, digits=digits))
    raise TrackingError(NOT_A_NUMBER)


def tracking_info(number: str | None) -> TrackingInfo | None:
    """The stored number of a letter as :class:`TrackingInfo` (``None`` when there is none).

    A stored number was accepted when it was saved; one the policy no longer accepts is shown as
    typed, unchecked and of format ``unknown`` rather than hidden.
    """
    if not number:
        return None
    try:
        return parse_tracking_number(number)
    except TrackingError as exc:
        return TrackingInfo(number=number, display=number, format="unknown", checked=False, note=str(exc))
