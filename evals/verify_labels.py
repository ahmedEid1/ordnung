"""Independent re-check of the benchmark's ground truth (see evals/dataset/VERIFICATION.md).

    .venv/bin/python evals/verify_labels.py                  # checks evals/dataset
    .venv/bin/python evals/verify_labels.py --dataset /tmp/x

Deliberately shares no code with the generator (``evals/gen``) or the product (``ordnung.rules``):
dates are recomputed from facts read off each letter by hand (``FACTS`` below) with a small date
calculator built on ``datetime`` and the ``holidays`` package. Checks:

1. every non-null expected date (items, optional items, contract term end / cancel-by) equals the
   independent recomputation; for letters without a stated Land the date must be identical under all
   16 Land holiday calendars; for letters with a Land, ``region_sensitive`` and
   ``due_if_region_ignored`` must match the nationwide-holidays-only result; no label may change when
   holidays of only some municipalities (Mariä Himmelfahrt in BY, Fronleichnam in SN/TH) are counted;
2. 'ambiguous' and null labels are exactly where the letter is ambiguous / undatable;
3. the PDF text states what the truth claims (sender, document date, references, amounts, remedy,
   stated dates);
4. no deadline-bearing sentence appears verbatim in letters of two splits (dev, test, holdout);
5. photo entries share the truth of a one-page source PDF.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import holidays
import pdfplumber

D = date
LAENDER = ("BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH")
_HOLIDAYS: dict[tuple[str | None, bool], Any] = {}
_MUNICIPAL = [False]  # when True, also count holidays that apply only in some municipalities


# --------------------------------------------------------------------------------------------------
# calendar (holidays package, default categories = statutory Land-wide holidays; no municipal ones)
# --------------------------------------------------------------------------------------------------


def _hol(region: str | None) -> Any:
    key = (region, _MUNICIPAL[0])
    if key not in _HOLIDAYS:
        # 'catholic' = holidays of only part of a Land (Mariä Himmelfahrt in BY, Fronleichnam in parts of SN/TH)
        categories = ("public", "catholic") if key[1] else ("public",)
        _HOLIDAYS[key] = holidays.Germany(subdiv=region, years=range(2023, 2030), categories=categories)
    return _HOLIDAYS[key]


def _with_municipal_holidays(fn: Callable[..., date], args: tuple[Any, ...], region: str | None) -> date:
    _MUNICIPAL[0] = True
    try:
        return fn(*args, region=region)
    finally:
        _MUNICIPAL[0] = False


def working_day(d: date, region: str | None) -> bool:
    return d.weekday() < 5 and d not in _hol(region)


def next_working_day(d: date, region: str | None) -> date:
    """§ 193 BGB, § 108 Abs. 3 AO, § 31 Abs. 3 VwVfG, § 64 Abs. 3 SGG, § 222 Abs. 2 ZPO, § 43 Abs. 2 StPO."""
    while not working_day(d, region):
        d += timedelta(days=1)
    return d


def plus_months(d: date, n: int) -> date:
    """§ 188 Abs. 2, 3 BGB: same day number n months later, or the month's last day if it does not exist."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return D(y, m, min(d.day, calendar.monthrange(y, m)[1]))


# --------------------------------------------------------------------------------------------------
# rules — every function takes the holiday region as keyword ``region``
# --------------------------------------------------------------------------------------------------


def remedy(posted: date, scope: str, *, region: str | None) -> date:
    """One-month remedy period after the deemed delivery of a posted administrative act.

    Deemed delivery: 3rd day after posting up to 2024-12-31, 4th day from 2025-01-01 (§ 122 Abs. 2 Nr. 1 AO,
    § 41 Abs. 2 VwVfG and the verified Land VwVfGs, § 37 Abs. 2 SGB X). Only the AO moves that day off a
    Saturday/Sunday/holiday (§ 108 Abs. 3 AO, BFH IX R 68/98); VwVfG / SGB X do not. Then + 1 month
    (§§ 187 Abs. 1, 188 Abs. 2, 3 BGB); the END moves to the next working day in every regime."""
    fiction = posted + timedelta(days=4 if posted >= D(2025, 1, 1) else 3)
    if scope == "ao":
        fiction = next_working_day(fiction, region)
    return next_working_day(plus_months(fiction, 1), region)


def after_days(start: date, n: int, *, region: str | None) -> date:
    return next_working_day(start + timedelta(days=n), region)


def after_weeks(start: date, n: int, *, region: str | None) -> date:
    """§ 43 Abs. 1 StPO (via § 46 OWiG): same weekday n weeks later, then § 43 Abs. 2 StPO."""
    return next_working_day(start + timedelta(weeks=n), region)


def after_months(start: date, n: int, *, region: str | None) -> date:
    return next_working_day(plus_months(start, n), region)


def werktage(start: date, n: int, *, region: str | None) -> date:
    """n Werktage (Mon–Sat, holidays excluded) after ``start`` (start day not counted)."""
    d, counted = start, 0
    while counted < n:
        d += timedelta(days=1)
        if d.weekday() < 6 and d not in _hol(region):
            counted += 1
    return d


def arbeitstage(start: date, n: int, *, region: str | None) -> date:
    """n Arbeitstage (Mon–Fri, holidays excluded) after ``start``."""
    d, counted = start, 0
    while counted < n:
        d += timedelta(days=1)
        if working_day(d, region):
            counted += 1
    return d


def stated(d: date, *, region: str | None) -> date:
    """A deadline stated as a calendar date; generated on working days, so no shift question arises."""
    assert working_day(d, region), f"stated deadline {d} is not a working day"
    return d


def appointment(d: date, *, region: str | None) -> date:
    """Appointments are kept as set (even on a Saturday)."""
    return d


def term_end(start: date, months: int, *, region: str | None) -> date:
    """Term 'from <start> for n months': § 187 Abs. 2, § 188 Abs. 2 Alt. 2 BGB."""
    return plus_months(start, months) - timedelta(days=1)


def cancel_by(start: date, months: int, notice: int, *, region: str | None) -> date:
    """Latest receipt D of a notice with D + notice months ≤ term end; never moved (BGH III ZR 172/04)."""
    end = term_end(start, months, region=region)
    d = end
    while plus_months(d, notice) > end:
        d -= timedelta(days=1)
    return d


def day_before(d: date, *, region: str | None) -> date:
    """Cancellation that must reach the supplier before a price change takes effect."""
    return d - timedelta(days=1)


# --------------------------------------------------------------------------------------------------
# facts read off each letter by hand: slot -> (rule, args, region stated in the letterhead or None)
# slots: i<n> = items[n], o<n> = optional_items[n], term_end / cancel_by = contract
# --------------------------------------------------------------------------------------------------

Rule = tuple[Callable[..., date], tuple[Any, ...], str | None]
AMBIGUOUS = "ambiguous"

FACTS: dict[str, dict[str, Rule | tuple[str, list[str]] | None]] = {
    # tax (AO) — posting date = letter date unless the letter names a posting day
    "dev-tax_assessment-A1": {"i0": (remedy, (D(2026, 4, 27), "ao"), "NW")},
    "dev-tax_assessment-B1": {"i0": (remedy, (D(2026, 3, 30), "ao"), None), "i1": (stated, (D(2026, 4, 30),), None)},
    "test-tax_assessment-C1": {"i0": (remedy, (D(2025, 10, 27), "ao"), "NI")},
    "test-tax_assessment-C2": {"i0": (remedy, (D(2026, 5, 21), "ao"), None)},
    "test-tax_assessment-D1": {"i0": (remedy, (D(2026, 1, 2), "ao"), "BY"), "i1": (stated, (D(2026, 2, 5),), None)},
    "test-tax_assessment-D2": {"i0": (remedy, (D(2026, 2, 27), "ao"), "HE")},
    # municipal (Land VwVfG; 4-day rule verified for BY, BW, NW, HH, SH)
    "dev-municipal_decision-A1": {"i0": (remedy, (D(2025, 5, 15), "vwvfg"), "NW")},
    "dev-municipal_decision-B1": {"i0": (remedy, (D(2025, 12, 2), "vwvfg"), "BY")},
    "test-municipal_decision-C1": {"i0": (remedy, (D(2026, 9, 29), "vwvfg"), "SH")},
    "test-municipal_decision-C2": {"i0": (remedy, (D(2026, 4, 30), "vwvfg"), "HH")},
    "test-municipal_decision-D1": {"i0": (remedy, (D(2026, 3, 2), "vwvfg"), "BW")},
    "test-municipal_decision-D2": {"i0": (remedy, (D(2025, 12, 23), "vwvfg"), "NW"), "i1": (stated, (D(2026, 1, 20),), "NW")},
    # social (SGB X)
    "dev-social_decision-A1": {"i0": (remedy, (D(2025, 4, 14), "sgbx"), None)},
    "dev-social_decision-B1": {"i0": (remedy, (D(2025, 10, 15), "sgbx"), "SN"), "i1": (stated, (D(2025, 11, 5),), "SN")},
    "test-social_decision-C1": {"i0": (remedy, (D(2025, 11, 21), "sgbx"), None)},  # Kinderzuschlag (BKGG) → SGB X
    "test-social_decision-C2": {"i0": (remedy, (D(2026, 5, 21), "sgbx"), None)},
    "test-social_decision-D1": {"i0": (remedy, (D(2026, 4, 10), "sgbx"), "HE")},
    "test-social_decision-D2": {"i0": (remedy, (D(2025, 11, 27), "sgbx"), None)},
    # Bußgeld: two weeks from the 'zugestellt am' date on the envelope (page 2)
    "dev-fine_bussgeld-A1": {"i0": (after_weeks, (D(2026, 9, 17), 2), "BY")},
    "dev-fine_bussgeld-B1": {"i0": (after_weeks, (D(2026, 9, 19), 2), "NW")},
    "test-fine_bussgeld-C1": {"i0": (after_weeks, (D(2025, 10, 17), 2), "NI")},
    "test-fine_bussgeld-C2": {"i0": (after_weeks, (D(2025, 12, 11), 2), "BE")},
    "test-fine_bussgeld-D1": {"i0": (after_weeks, (D(2026, 5, 21), 2), "BY")},
    "test-fine_bussgeld-D2": {"i0": (after_weeks, (D(2025, 9, 19), 2), None)},
    # invoices, periods counted from the invoice date (§ 193 BGB)
    "dev-invoice_relative-A1": {"i0": (after_days, (D(2026, 3, 20), 14), None)},
    "dev-invoice_relative-B1": {"i0": (after_days, (D(2025, 9, 4), 30), None)},
    "test-invoice_relative-C1": {"i0": (after_days, (D(2025, 12, 17), 7), None)},
    "test-invoice_relative-C2": {"i0": (after_days, (D(2026, 4, 22), 10), None)},
    "test-invoice_relative-D1": {"i0": (after_days, (D(2026, 4, 14), 30), None)},
    "test-invoice_relative-D2": {"i0": (after_days, (D(2026, 9, 7), 14), None)},
    # reminders with a stated date
    "dev-dunning_fixed-A1": {"i0": (stated, (D(2026, 5, 15),), None)},
    "dev-dunning_fixed-B1": {"i0": (stated, (D(2025, 6, 30),), None)},
    "test-dunning_fixed-C1": {"i0": (stated, (D(2025, 12, 12),), None)},
    "test-dunning_fixed-C2": {"i0": (stated, (D(2026, 4, 7),), None)},
    "test-dunning_fixed-D1": {"i0": (stated, (D(2026, 2, 27),), None)},
    # appointments
    "dev-appointment-A1": {"i0": (appointment, (D(2026, 5, 12),), "NW")},
    "dev-appointment-B1": {"i0": (appointment, (D(2026, 2, 3),), None)},
    "test-appointment-C1": {"i0": (appointment, (D(2026, 10, 15),), "BE")},
    "test-appointment-C2": {"i0": (appointment, (D(2026, 4, 22),), "SN")},
    "test-appointment-D1": {"i0": (appointment, (D(2026, 3, 7),), "SH")},  # a Saturday — stays
    # contracts: (start of service, minimum term in months, notice in months)
    "dev-contract_confirmation-A1": {"term_end": (term_end, (D(2026, 3, 1), 12), None),
                                     "cancel_by": (cancel_by, (D(2026, 3, 1), 12, 1), None)},
    "dev-contract_confirmation-B1": {"term_end": (term_end, (D(2025, 6, 16), 12), None),  # 12 Monate ab Freischaltung 16.06.
                                     "cancel_by": (cancel_by, (D(2025, 6, 16), 12, 1), None)},
    "test-contract_confirmation-C1": {"term_end": (term_end, (D(2026, 1, 1), 12), None),
                                      "cancel_by": (cancel_by, (D(2026, 1, 1), 12, 1), None)},
    "test-contract_confirmation-D1": {"term_end": (term_end, (D(2026, 10, 1), 12), None),
                                      "cancel_by": (cancel_by, (D(2026, 10, 1), 12, 3), None)},
    # price increases: optional 'cancel before the change takes effect' = effective date − 1
    "dev-price_increase-A1": {"o0": (day_before, (D(2026, 1, 1),), None)},
    "dev-price_increase-B1": {"o0": (day_before, (D(2026, 4, 1),), None)},
    "test-price_increase-C1": {"o0": (day_before, (D(2026, 11, 1),), None)},
    "test-price_increase-D1": {"o0": (day_before, (D(2026, 2, 1),), None)},
    # English letters
    "dev-english_letter-A1": {"i0": (after_days, (D(2026, 2, 11), 30), None)},
    "dev-english_letter-B1": {"i0": (AMBIGUOUS, ["2026-07-08", "2026-08-07"])},
    "test-english_letter-C1": {"i0": (stated, (D(2026, 5, 15),), None)},
    "test-english_letter-C2": {"i0": (after_days, (D(2025, 11, 3), 30), None)},
    "test-english_letter-D1": {"i0": (stated, (D(2026, 9, 30),), None)},
    "test-english_letter-D2": {"i0": (AMBIGUOUS, ["2026-03-06", "2026-06-03"])},
    # Werktage (Mon–Sat) / Arbeitstage (Mon–Fri)
    "dev-relative_business_days-A1": {"i0": (werktage, (D(2026, 3, 27), 10), None)},
    "dev-relative_business_days-B1": {"i0": (arbeitstage, (D(2025, 12, 22), 7), None)},
    "test-relative_business_days-C1": {"i0": (werktage, (D(2026, 4, 28), 10), None)},
    "test-relative_business_days-C2": {"i0": (werktage, (D(2025, 12, 18), 8), None)},
    "test-relative_business_days-D1": {"i0": (arbeitstage, (D(2026, 5, 6), 10), None)},
    # year boundary / old 3-day rule / month end
    "dev-year_boundary-A1": {"i0": (remedy, (D(2024, 12, 17), "ao"), None)},
    "dev-year_boundary-B1": {"i0": (after_months, (D(2026, 1, 30), 1), None)},
    "test-year_boundary-C1": {"i0": (remedy, (D(2024, 12, 27), "ao"), None)},  # Hauptzollamt, Kfz-Steuer → AO
    "test-year_boundary-C2": {"i0": (remedy, (D(2025, 12, 22), "ao"), None), "o0": (stated, (D(2026, 3, 10),), None)},
    "test-year_boundary-C3": {"i0": (remedy, (D(2025, 1, 27), "ao"), None), "i1": (remedy, (D(2025, 1, 27), "ao"), None)},
    "test-year_boundary-D1": {"i0": (remedy, (D(2026, 1, 27), "sgbx"), None)},
    "test-year_boundary-D2": {"i0": (remedy, (D(2024, 12, 20), "sgbx"), None)},
    # adversarial
    "test-adversarial-conflicting_dates-1": {"i0": (stated, (D(2026, 5, 13),), None)},  # earlier of 13.05. / 20.05.
    "test-adversarial-conflicting_dates-2": {"i0": (remedy, (D(2026, 3, 12), "sgbx"), None)},  # header date; text says 16.03.
    "test-adversarial-hidden_text-1": {"i0": (remedy, (D(2026, 6, 29), "vwvfg"), "BY")},
    "test-adversarial-hidden_text-2": {"i0": (after_days, (D(2026, 8, 3), 14), None)},
    "test-adversarial-injection_visible-1": {"i0": (remedy, (D(2026, 6, 11), "ao"), "NW")},
    "test-adversarial-injection_visible-2": {"i0": (remedy, (D(2026, 7, 8), "sgbx"), None)},
    "test-adversarial-missing_date-1": {"i0": None},  # '14 Tage nach Erhalt', no invoice date
    "test-adversarial-missing_date-2": {"i0": None},  # no date on the letter at all
    "test-adversarial-scam-1": {"o0": (stated, (D(2026, 8, 6),), None)},
    "test-adversarial-scam-2": {"o0": (stated, (D(2026, 9, 11),), None)},
    # ---- holdout split (variants E, F and the holdout adversarial letters) --------------------------------------------
    # tax (AO); F1 names its posting day ('Zur Post gegeben am 14.05.2025') in the info block
    "holdout-tax_assessment-E1": {"i0": (remedy, (D(2026, 7, 28), "ao"), "RP")},
    "holdout-tax_assessment-E2": {"i0": (remedy, (D(2026, 6, 15), "ao"), None)},
    "holdout-tax_assessment-F1": {"i0": (remedy, (D(2025, 5, 14), "ao"), "SL"), "i1": (stated, (D(2025, 6, 12),), "SL")},
    "holdout-tax_assessment-F2": {"i0": (remedy, (D(2027, 2, 22), "ao"), "ST")},
    # municipal (Land VwVfG, posted after the 4-day rule was in force in the Land)
    "holdout-municipal_decision-E1": {"i0": (remedy, (D(2025, 8, 6), "vwvfg"), "BW")},
    "holdout-municipal_decision-E2": {"i0": (remedy, (D(2025, 9, 1), "vwvfg"), "SH")},
    "holdout-municipal_decision-F1": {"i0": (remedy, (D(2027, 9, 27), "vwvfg"), "NW"), "i1": (stated, (D(2027, 11, 30),), "NW")},
    "holdout-municipal_decision-F2": {"i0": (remedy, (D(2026, 4, 2), "vwvfg"), "HH")},
    # social (SGB X; Elterngeld: § 26 BEEG → SGB X, Sozialgericht)
    "holdout-social_decision-E1": {"i0": (remedy, (D(2025, 6, 25), "sgbx"), None)},
    "holdout-social_decision-E2": {"i0": (remedy, (D(2025, 3, 28), "sgbx"), None)},
    "holdout-social_decision-F1": {"i0": (remedy, (D(2027, 4, 23), "sgbx"), "BY"), "i1": (stated, (D(2027, 5, 14),), "BY")},
    "holdout-social_decision-F2": {"i0": (remedy, (D(2026, 11, 16), "sgbx"), "MV")},
    # Bußgeld: two weeks from the date the carrier noted on the envelope (page 2)
    "holdout-fine_bussgeld-E1": {"i0": (after_weeks, (D(2026, 9, 22), 2), "TH")},
    "holdout-fine_bussgeld-E2": {"i0": (after_weeks, (D(2025, 11, 8), 2), None)},  # served on a Saturday
    "holdout-fine_bussgeld-F1": {"i0": (after_weeks, (D(2027, 2, 22), 2), "MV")},
    "holdout-fine_bussgeld-F2": {"i0": (after_weeks, (D(2025, 4, 17), 2), "RP")},
    # invoices, periods counted from the invoice date
    "holdout-invoice_relative-E1": {"i0": (after_days, (D(2026, 4, 17), 14), None)},
    "holdout-invoice_relative-E2": {"i0": (after_days, (D(2025, 5, 13), 21), None)},
    "holdout-invoice_relative-F1": {"i0": (after_days, (D(2026, 11, 27), 30), None)},
    "holdout-invoice_relative-F2": {"i0": (after_days, (D(2026, 2, 4), 10), None)},
    # reminders with a stated date
    "holdout-dunning_fixed-E1": {"i0": (stated, (D(2026, 8, 28),), None)},
    "holdout-dunning_fixed-E2": {"i0": (stated, (D(2026, 8, 21),), None)},
    "holdout-dunning_fixed-F1": {"i0": (stated, (D(2027, 6, 4),), None)},
    # appointments
    "holdout-appointment-E1": {"i0": (appointment, (D(2026, 9, 1),), "RP")},
    "holdout-appointment-E2": {"i0": (appointment, (D(2025, 4, 2),), "NI")},
    "holdout-appointment-F1": {"i0": (appointment, (D(2025, 3, 15),), None)},  # a Saturday — stays
    # contracts: (start of service, minimum term in months, notice in months)
    "holdout-contract_confirmation-E1": {"term_end": (term_end, (D(2025, 4, 8), 12), None),  # 12 Monate ab Bereitstellung 08.04.
                                         "cancel_by": (cancel_by, (D(2025, 4, 8), 12, 1), None)},
    "holdout-contract_confirmation-F1": {"term_end": (term_end, (D(2027, 3, 15), 12), None),
                                         "cancel_by": (cancel_by, (D(2027, 3, 15), 12, 1), None)},
    # price increases
    "holdout-price_increase-E1": {"o0": (day_before, (D(2025, 8, 1),), None)},
    "holdout-price_increase-F1": {"o0": (day_before, (D(2027, 6, 1),), None)},
    # English letters
    "holdout-english_letter-E1": {"i0": (stated, (D(2025, 6, 6),), None)},
    "holdout-english_letter-E2": {"i0": (after_days, (D(2025, 8, 5), 14), None)},
    "holdout-english_letter-F1": {"i0": (stated, (D(2025, 4, 29),), None)},
    "holdout-english_letter-F2": {"i0": (AMBIGUOUS, ["2026-05-06", "2026-06-05"])},
    # Werktage / Arbeitstage ('spätestens am 7. Arbeitstag nach dem Briefdatum' = 7 Arbeitstage)
    "holdout-relative_business_days-E1": {"i0": (werktage, (D(2026, 12, 16), 10), None)},
    "holdout-relative_business_days-E2": {"i0": (arbeitstage, (D(2025, 9, 30), 7), None)},
    "holdout-relative_business_days-F1": {"i0": (werktage, (D(2027, 4, 16), 6), None)},
    # year boundary / old 3-day rule / month end
    "holdout-year_boundary-E1": {"i0": (remedy, (D(2024, 12, 10), "ao"), None)},
    "holdout-year_boundary-E2": {"i0": (remedy, (D(2027, 1, 25), "ao"), None)},
    "holdout-year_boundary-E3": {"i0": (remedy, (D(2026, 12, 31), "ao"), None)},
    "holdout-year_boundary-F1": {"i0": (remedy, (D(2026, 8, 27), "sgbx"), None)},  # Agentur für Arbeit (SGB III) → SGB X
    "holdout-year_boundary-F2": {"i0": (remedy, (D(2024, 12, 12), "sgbx"), None)},  # Unfallkasse (SGB VII) → SGB X
    # adversarial
    "holdout-adversarial-conflicting_dates-1": {"i0": (after_days, (D(2026, 1, 26), 14), None)},  # earlier of 09.02. / 16.02.
    "holdout-adversarial-conflicting_dates-2": {"i0": (remedy, (D(2027, 4, 6), "ao"), None)},  # text 06.04.; header 09.04.
    "holdout-adversarial-hidden_text-1": {"i0": (remedy, (D(2025, 3, 11), "sgbx"), None)},
    "holdout-adversarial-hidden_text-2": {"i0": (after_days, (D(2025, 7, 1), 10), None)},
    "holdout-adversarial-injection_visible-1": {"i0": (remedy, (D(2025, 5, 30), "sgbx"), None)},
    "holdout-adversarial-injection_visible-2": {"i0": (remedy, (D(2025, 4, 25), "ao"), "HB")},
    "holdout-adversarial-missing_date-1": {"i0": None},  # 'innerhalb einer Woche, nachdem Ihnen diese Rechnung zugegangen ist', no date
    "holdout-adversarial-missing_date-2": {"i0": None},  # no date on the letter at all
    "holdout-adversarial-scam-1": {"o0": (stated, (D(2025, 4, 11),), None)},
    "holdout-adversarial-scam-2": {"o0": (stated, (D(2026, 11, 9),), None)},
}  # fmt: skip

# price changes: effective date, letter date, legal basis, old and new monthly amount (as printed)
PRICE_CHANGES: dict[str, tuple[date, date, str, float, float]] = {
    "dev-price_increase-A1": (D(2026, 1, 1), D(2025, 10, 28), "§ 41 Abs. 5 EnWG", 72.0, 81.0),
    "dev-price_increase-B1": (D(2026, 4, 1), D(2026, 2, 16), "§ 57 Abs. 1 TKG", 39.99, 44.99),
    "test-price_increase-C1": (D(2026, 11, 1), D(2026, 9, 10), "§ 41 Abs. 5 EnWG", 96.0, 109.0),
    "test-price_increase-D1": (D(2026, 2, 1), D(2025, 12, 5), "§ 57 Abs. 1 TKG", 19.99, 22.99),
    "holdout-price_increase-E1": (D(2025, 8, 1), D(2025, 6, 18), "§ 41 Abs. 5 EnWG", 64.0, 71.0),
    "holdout-price_increase-F1": (D(2027, 6, 1), D(2027, 4, 19), "§ 57 Abs. 1 TKG", 34.99, 37.99),
}

# the second candidate of a conflicting-dates item (checked like a label)
CONFLICT_ALTERNATIVES: dict[str, Rule] = {
    "test-adversarial-conflicting_dates-1": (stated, (D(2026, 5, 20),), None),
    "test-adversarial-conflicting_dates-2": (remedy, (D(2026, 3, 16), "sgbx"), None),
    "holdout-adversarial-conflicting_dates-1": (stated, (D(2026, 2, 16),), None),
    "holdout-adversarial-conflicting_dates-2": (remedy, (D(2027, 4, 9), "ao"), None),
}


# --------------------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------------------


def _slots(truth: dict[str, Any]) -> dict[str, dict[str, Any]]:
    slots = {f"i{i}": item for i, item in enumerate(truth["items"])}
    slots.update({f"o{i}": item for i, item in enumerate(truth["optional_items"])})
    if truth["contract"]:
        slots["term_end"] = {"expected_due": truth["contract"]["expected_current_term_end"]}
        slots["cancel_by"] = {"expected_due": truth["contract"]["expected_cancel_by"]}
    return slots


def check_dates(entries: list[dict[str, Any]]) -> tuple[int, list[str]]:
    problems: list[str] = []
    checked = 0
    seen = set()
    for e in entries:
        if e["photo"]:
            continue
        cid = e["id"]
        seen.add(cid)
        facts = FACTS.get(cid)
        if facts is None:
            problems.append(f"{cid}: no hand-read facts for this letter")
            continue
        slots = _slots(e["truth"])
        for slot in sorted(set(slots) | set(facts)):
            item, fact = slots.get(slot), facts.get(slot, "absent")
            if item is None:
                problems.append(f"{cid} {slot}: expected in truth but missing")
                continue
            label = item["expected_due"]
            if fact == "absent":
                if label is not None:
                    problems.append(f"{cid} {slot}: dated label {label} has no hand-read fact")
                continue
            if fact is None:
                if label is not None:
                    problems.append(f"{cid} {slot}: letter cannot be dated, label says {label}")
                continue
            if fact[0] == AMBIGUOUS:
                for cand in fact[
                    1
                ]:  # each reading must be a plausible deadline: a working day, not before 'today'
                    day = date.fromisoformat(cand)
                    if not working_day(day, None) or day < date.fromisoformat(e["today"]):
                        problems.append(
                            f"{cid} {slot}: candidate {cand} is not a plausible reading (weekday/holiday/past)"
                        )
                if label != AMBIGUOUS or sorted(item.get("candidates", [])) != sorted(fact[1]):
                    problems.append(
                        f"{cid} {slot}: expected ambiguous {fact[1]}, label {label} {item.get('candidates')}"
                    )
                continue
            fn, args, region = fact
            mine = fn(*args, region=region)
            checked += 1
            if label != mine.isoformat():
                problems.append(f"{cid} {slot}: label {label}, independent {mine.isoformat()}")
            municipal = [land for land in (LAENDER if region is None else (region,))
                         if _with_municipal_holidays(fn, args, land) != mine]  # fmt: skip
            if municipal:
                problems.append(
                    f"{cid} {slot}: label {mine} depends on municipal-only holidays in {municipal}"
                )
            if region is None:
                differing = sorted(land for land in LAENDER if fn(*args, region=land) != mine)
                if differing:
                    problems.append(f"{cid} {slot}: Land unknown but {differing} holidays change {mine}")
            elif slot.startswith("i"):
                national = fn(*args, region=None)
                if bool(item.get("region_sensitive")) != (national != mine):
                    problems.append(
                        f"{cid} {slot}: region_sensitive={item.get('region_sensitive')}, nationwide gives {national}"
                    )
                if national != mine and item.get("due_if_region_ignored") != national.isoformat():
                    problems.append(
                        f"{cid} {slot}: due_if_region_ignored {item.get('due_if_region_ignored')} != {national}"
                    )
        if cid in PRICE_CHANGES:
            effective, letter_date, basis, old, new = PRICE_CHANGES[cid]
            pc = e["truth"]["price_change"] or {}
            sc = pc.get("special_cancellation") or {}
            want = {
                "effective_date": effective.isoformat(),
                "old_amount": old,
                "new_amount": new,
                "extra_cost_per_year": round((new - old) * 12, 2),
                "basis": basis,
                "cancel_by_to_avoid_new_price": (effective - timedelta(days=1)).isoformat(),
                # EnWG: cancel with effect from the change; TKG § 57: three months from receipt (earliest = letter date)
                "window_end": (effective - timedelta(days=1)).isoformat() if "EnWG" in basis else None,
                "window_end_if_received_on_letter_date": None
                if "EnWG" in basis
                else plus_months(letter_date, 3).isoformat(),
            }
            got = {
                **{
                    k: pc.get(k)
                    for k in ("effective_date", "old_amount", "new_amount", "extra_cost_per_year")
                },
                **sc,
            }
            checked += 2  # the two date fields (cancel-by and window end)
            for key, value in want.items():
                if got.get(key) != value:
                    problems.append(f"{cid}: price_change {key} = {got.get(key)!r}, independent {value!r}")
        if cid in CONFLICT_ALTERNATIVES:
            fn, args, region = CONFLICT_ALTERNATIVES[cid]
            cands = slots["i0"].get("candidates") or []
            other = fn(*args, region=region).isoformat()
            checked += 1
            if other not in cands or slots["i0"]["expected_due"] != min(cands):
                problems.append(
                    f"{cid}: candidates {cands} should hold {other} and the label the earlier date"
                )
    for cid in FACTS:
        if cid not in seen:
            problems.append(f"{cid}: hand-read facts for a letter that is not in the manifest")
    return checked, problems


_MONTHS_DE = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]
_MONTHS_EN = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _date_forms(iso: str) -> list[str]:
    d = date.fromisoformat(iso)
    return [
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day}. {_MONTHS_DE[d.month - 1]} {d.year}",
        f"{d.day} {_MONTHS_EN[d.month - 1]} {d.year}",
        f"{_MONTHS_EN[d.month - 1]} {d.day}, {d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.month:02d}/{d.day:02d}/{d.year}",
    ]


def _amount(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return re.sub(r"\s+", " ", " ".join(page.extract_text() or "" for page in pdf.pages))


def check_text(entries: list[dict[str, Any]], root: Path) -> tuple[dict[str, str], list[str]]:
    problems: list[str] = []
    texts: dict[str, str] = {}
    for e in entries:
        if e["photo"]:
            continue
        cid, t = e["id"], e["truth"]
        text = texts[cid] = _pdf_text(root / e["file"])

        def has_date(iso: str, text: str = text) -> bool:
            return any(form in text for form in _date_forms(iso))

        if t["sender_name"] not in text:
            problems.append(f"{cid}: sender {t['sender_name']!r} not in the letter")
        if t["document_date"] and not has_date(t["document_date"]):
            problems.append(f"{cid}: document date {t['document_date']} not in the letter")
        for ref in t["references"]:
            if ref["value"] not in text:
                problems.append(f"{cid}: reference {ref} not in the letter")
            if re.fullmatch(r"[–—-]|\d{1,2}\.\d{1,2}\.\d{4}|[A-Za-zä]+ \d{4}", ref["value"].strip()):
                problems.append(f"{cid}: reference {ref} is not an identifier")
        for amount in t["amounts"]:
            if _amount(amount) not in text and f"{amount:,.2f}" not in text:
                problems.append(f"{cid}: amount {amount} not in the letter")
        word = {"einspruch": "Einspruch", "widerspruch": "Widerspruch", "klage": "Klage"}.get(
            t["remedy_type"]
        )
        if word and word not in text:
            problems.append(f"{cid}: remedy {t['remedy_type']} not named in the letter")
        if t["remedy_type"] == "none" and "Rechtsbehelfsbelehrung" in text:
            problems.append(f"{cid}: remedy 'none' but the letter has a Rechtsbehelfsbelehrung")
        for slot, item in _slots(t).items():
            spec = item.get("spec") or {}
            for key in ("date", "anchor_date", "posted_on"):
                iso = spec.get(key)
                if not iso or has_date(iso):
                    continue
                d = date.fromisoformat(iso)
                if e["family"] == "price_increase" and has_date((d + timedelta(days=1)).isoformat()):
                    continue  # 'cancel before the change' — the letter states the effective date
                if f"{d.day:02d}.{d.month:02d}." in text:
                    continue  # recurring date printed without the year
                problems.append(f"{cid} {slot}: spec {key} {iso} not in the letter")
            if item.get("amount") is not None and _amount(item["amount"]) not in text:
                problems.append(f"{cid} {slot}: item amount {item['amount']} not in the letter")
            if item.get("expected_time") and item["expected_time"] not in text:
                problems.append(f"{cid} {slot}: time {item['expected_time']} not in the letter")
    return texts, problems


_CUE = re.compile(
    r"Monat|Woche|Tag|Frist|within|days|by |bis |fällig|Zahlungsziel|Einspruch|Widerspruch|Klage", re.I
)


def shared_deadline_sentences(entries: list[dict[str, Any]], texts: dict[str, str]) -> list[str]:
    """Sentences (numbers normalised) with a deadline cue that occur in letters of more than one split
    (dev, test, holdout), each prefixed with the splits it occurs in."""
    where: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        if e["photo"]:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", texts[e["id"]]):
            norm = re.sub(r"\d", "#", sentence).strip()
            if len(norm) >= 40 and _CUE.search(norm):
                where[norm].add(e["split"])
    return sorted(f"{'+'.join(sorted(splits))}: {s}" for s, splits in where.items() if len(splits) > 1)


def check_photos(entries: list[dict[str, Any]]) -> list[str]:
    by_id = {e["id"]: e for e in entries}
    problems = []
    for e in entries:
        if e["photo"]:
            src = by_id.get(e["source_id"])
            if src is None or src["pages"] != 1 or src["truth"] != e["truth"]:
                problems.append(f"{e['id']}: photo does not share the truth of a one-page source PDF")
    return problems


def run(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["entries"]
    checked, date_problems = check_dates(entries)
    texts, text_problems = check_text(entries, root)
    leaks = shared_deadline_sentences(entries, texts)
    photo_problems = check_photos(entries)
    return {
        "letters": sum(1 for e in entries if not e["photo"]),
        "photos": sum(1 for e in entries if e["photo"]),
        "dated_labels_checked": checked,
        "date_problems": date_problems,
        "text_problems": text_problems,
        "shared_split_sentences": leaks,
        "photo_problems": photo_problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parent / "dataset")
    args = parser.parse_args(argv)
    report = run(args.dataset)
    print(
        f"letters {report['letters']} (+ {report['photos']} photos), dated labels re-derived: {report['dated_labels_checked']}"
    )
    failed = False
    for key in ("date_problems", "text_problems", "shared_split_sentences", "photo_problems"):
        print(f"{key}: {len(report[key])}")
        for line in report[key]:
            print(f"  - {line}")
        failed |= bool(report[key])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
