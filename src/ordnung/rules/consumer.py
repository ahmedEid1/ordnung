"""Consumer letters: the right of withdrawal and the time-bar of old claims.

Pure date functions; :mod:`ordnung.rules.letters` turns the withdrawal period into a receipt.

* **Withdrawal** (*Widerruf*, §§ 355, 356 BGB) from a contract concluded online, by phone or at the
  door: 14 days from the start (the contract, or for goods the day they arrived, § 356 Abs. 2 BGB).
  The start day is not counted; a period ending on a Saturday, Sunday or holiday runs to the next
  working day (§ 193 BGB — Verbraucherzentrale: a subscription concluded at the door on a Saturday can
  be withdrawn until the Monday two weeks later). Sending the withdrawal in time is enough
  (§ 355 Abs. 1 S. 5 BGB), so there is no postal buffer.
* **Without proper instructions** the 14 days never start and the right ends 12 months after the
  regular period would have ended (§ 356 Abs. 4 S. 1 BGB; Art. 10 Abs. 1 Directive 2011/83/EU).
  The German wording ("zwölf Monate und 14 Tage") can also be read as 12 months first, then 14 days;
  the two differ by a day or two around month ends, and Ordnung uses the earlier (SPEC § 21).
* **Time-bar** (§§ 195, 199 Abs. 1 BGB): most claims become time-barred at the end of the third
  year after the year they arose (and the creditor knew of them). Only a court or a lawyer can say
  whether one really is (it can be paused, § 204 BGB), so Ordnung only says "may be time-barred".
"""

from __future__ import annotations

from datetime import date, timedelta

from ordnung.rules.periods import add_months

WITHDRAWAL_DAYS = 14
#: Regular limitation period in years (§ 195 BGB).
LIMITATION_YEARS = 3


def withdrawal_end(start: date) -> date:
    """Last day of the regular 14-day withdrawal period starting with ``start`` (before any shift)."""
    return start + timedelta(days=WITHDRAWAL_DAYS)


def long_withdrawal_end(start: date) -> tuple[date, bool]:
    """Last day of the right to withdraw without proper instructions, and whether the readings differ.

    The Directive's reading (the regular period's end plus 12 months) and the literal German one
    (12 months, then 14 days) are both computed; the earlier date is returned.
    """
    directive = add_months(withdrawal_end(start), 12)
    literal = add_months(start, 12) + timedelta(days=WITHDRAWAL_DAYS)
    return min(directive, literal), directive != literal


def limitation_end(arose: date) -> date:
    """The day a claim that arose on ``arose`` becomes time-barred at the earliest (end of year + 3)."""
    return date(arose.year + LIMITATION_YEARS, 12, 31)


def latest_barred_year(today: date) -> int:
    """Claims that arose in this year or earlier may be time-barred on ``today`` (§§ 195, 199 BGB)."""
    return today.year - LIMITATION_YEARS - 1
