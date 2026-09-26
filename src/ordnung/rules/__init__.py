"""Deterministic German date rules: the model reads a letter, this package computes the dates.

Every public function returns explained results (steps with rule ids and citations, a one-sentence
plain-English summary, warnings and a confidence) so the UI can answer "Why this date?". The legal
basis of each rule is in :mod:`ordnung.rules.catalog` and ``docs/deadline-rules.md``.
"""

from __future__ import annotations

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
from ordnung.rules.catalog import LAST_CHECKED, RULES, get_rule, list_rules
from ordnung.rules.contracts import compute_contract, price_increase_window, regime_for
from ordnung.rules.deadlines import RuleContext, compute_due, compute_one_year_fallback
from ordnung.rules.delivery import (
    DeliveryChannel,
    DeliveryScope,
    deemed_delivery,
    is_private_sender,
    scope_for_party_kind,
)
from ordnung.rules.periods import PeriodMode, add_months, add_period
from ordnung.rules.send import send_guidance

__all__ = [
    "LAST_CHECKED",
    "RULES",
    "DeliveryChannel",
    "DeliveryScope",
    "PeriodMode",
    "RuleContext",
    "add_business_days",
    "add_months",
    "add_period",
    "add_werktage",
    "compute_contract",
    "compute_due",
    "compute_one_year_fallback",
    "deemed_delivery",
    "get_rule",
    "holiday_calendar_label",
    "is_business_day",
    "is_holiday",
    "is_private_sender",
    "is_werktag",
    "list_rules",
    "next_business_day",
    "normalize_region",
    "previous_business_day",
    "price_increase_window",
    "regime_for",
    "scope_for_party_kind",
    "send_guidance",
]
