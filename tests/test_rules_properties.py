"""Hypothesis property tests for the rules engine (SPEC § 18)."""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from ordnung.models import ContractTerms, DateSpec
from ordnung.rules.calendar_de import (
    REGION_NAMES,
    add_business_days,
    is_business_day,
    is_holiday,
    next_business_day,
    previous_business_day,
)
from ordnung.rules.contracts import compute_contract
from ordnung.rules.deadlines import RuleContext, compute_due
from ordnung.rules.delivery import VWVFG_FOUR_DAY_FROM, deemed_delivery
from ordnung.rules.periods import add_period, days_in_month, latest_receipt_for

dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2060, 12, 31))
recent = st.dates(min_value=date(2025, 1, 1), max_value=date(2040, 12, 31))
regions = st.one_of(st.none(), st.sampled_from(sorted(REGION_NAMES)))
positive_units = st.sampled_from(["days", "weeks", "months", "years", "business_days", "werktage"])
scopes = st.sampled_from(["ao", "vwvfg", "sgbx"])
natures = st.sampled_from(["objection", "payment", "declaration", "notice", "appointment", "other"])

settings.register_profile("rules", max_examples=150, deadline=None, database=None)
settings.load_profile("rules")


@given(dates, st.integers(min_value=0, max_value=120))
def test_month_periods_keep_the_day_or_clamp_to_month_end(start: date, months: int) -> None:
    end, _ = add_period(start, months, "months")
    assert (end.year * 12 + end.month) - (start.year * 12 + start.month) == months
    if end.day != start.day:
        assert end.day == days_in_month(end.year, end.month) < start.day


@given(dates, st.integers(min_value=1, max_value=120))
def test_day_start_month_periods_end_the_day_before_the_same_number(start: date, months: int) -> None:
    end, _ = add_period(start, months, "months", mode="day_start")
    event_end, _ = add_period(start, months, "months")
    assert end <= event_end
    assert end >= event_end - timedelta(days=1) or event_end.day == days_in_month(
        event_end.year, event_end.month
    )
    assert end > start


@given(dates, st.integers(min_value=0, max_value=36), st.sampled_from(["days", "weeks", "months"]))
def test_latest_receipt_is_the_last_day_that_fits(end: date, amount: int, unit: str) -> None:
    receipt = latest_receipt_for(end, amount, unit)  # type: ignore[arg-type]
    assert add_period(receipt, amount, unit)[0] <= end  # type: ignore[arg-type]
    if amount:
        assert add_period(receipt + timedelta(days=1), amount, unit)[0] > end  # type: ignore[arg-type]


@given(dates, regions)
def test_next_business_day_is_idempotent_and_never_a_weekend_or_holiday(
    day: date, region: str | None
) -> None:
    nxt = next_business_day(day, region)
    assert nxt >= day
    assert next_business_day(nxt, region) == nxt
    assert nxt.weekday() < 5 and not is_holiday(nxt, region)
    prev = previous_business_day(day, region)
    assert prev <= day and is_business_day(prev, region)


@given(dates, st.integers(min_value=-30, max_value=30), regions)
def test_add_business_days_lands_on_business_days(day: date, n: int, region: str | None) -> None:
    result = add_business_days(day, n, region)
    if n:
        assert is_business_day(result, region)
        assert (result > day) is (n > 0)


@given(recent, scopes, st.sampled_from(["post", "electronic", "portal"]), regions)
def test_deemed_delivery_is_at_least_four_days_after_posting_since_2025(
    posted: date, scope: str, channel: str, region: str | None
) -> None:
    day, steps = deemed_delivery(posted, scope=scope, channel=channel, region=region)  # type: ignore[arg-type]
    if scope == "vwvfg" and channel == "portal":
        assert day == posted + timedelta(days=1)  # day after download (§ 41 Abs. 2a VwVfG)
    elif scope == "vwvfg" and (region not in VWVFG_FOUR_DAY_FROM or posted < VWVFG_FOUR_DAY_FROM[region]):
        assert day == posted + timedelta(days=3)  # conservative 3rd day for unconfirmed Länder
    else:
        assert day >= posted + timedelta(days=4)
    if scope == "ao":
        assert is_business_day(day, region)
    assert steps


@given(
    dates,
    st.integers(min_value=0, max_value=36),
    positive_units,
    natures,
    st.sampled_from(["auto", "none", "next_business_day"]),
    regions,
)
def test_compute_due_never_before_the_anchor_for_positive_periods(
    anchor: date, amount: int, unit: str, nature: str, shift_rule: str, region: str | None
) -> None:
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=anchor.isoformat(),
        amount=amount,
        unit=unit,  # type: ignore[arg-type]
        nature=nature,  # type: ignore[arg-type]
        shift_rule=shift_rule,  # type: ignore[arg-type]
    )
    # The person lives in the sender's Land: a payment then shifts on the same holidays (§ 193 BGB uses
    # the payer's for money owed to a private creditor).
    receipt = compute_due(spec, RuleContext(today=anchor, region=region, recipient_region=region))
    assert receipt.due_date is not None
    due = date.fromisoformat(receipt.due_date)
    assert due >= anchor
    if receipt.safe_date:
        assert date.fromisoformat(receipt.safe_date) <= due
    if receipt.send_by:
        assert anchor <= date.fromisoformat(receipt.send_by) <= due
    if nature in ("objection", "payment", "declaration") and shift_rule != "none":
        assert is_business_day(due, region)


@given(recent, st.integers(min_value=1, max_value=36), positive_units, natures, regions)
def test_backward_periods_never_move_past_the_count(
    event: date, amount: int, unit: str, nature: str, region: str | None
) -> None:
    """Audit B1: "N before <event>" ends on the backward count, never on a later day."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=event.isoformat(),
        amount=-amount,
        unit=unit,  # type: ignore[arg-type]
        nature=nature,  # type: ignore[arg-type]
    )
    receipt = compute_due(spec, RuleContext(today=date(2024, 1, 1), region=region, recipient_region=region))
    assert receipt.due_date is not None
    inclusive_end = event if nature == "notice" else event - timedelta(days=1)
    assert receipt.due_date == latest_receipt_for(inclusive_end, amount, unit, region).isoformat()  # type: ignore[arg-type]
    if receipt.safe_date:
        assert receipt.safe_date <= receipt.due_date
        assert is_business_day(date.fromisoformat(receipt.safe_date), region)


@given(
    st.dates(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.sampled_from(["days", "weeks", "months", "years"]),
    natures,
)
def test_compute_due_never_raises(anchor: date, amount: int, unit: str, nature: str) -> None:
    """Audit B6: any anchor and period gives a receipt; impossible ones give no date and low confidence."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=anchor.isoformat(),
        amount=amount,
        unit=unit,  # type: ignore[arg-type]
        nature=nature,  # type: ignore[arg-type]
    )
    receipt = compute_due(spec, RuleContext(today=date(2026, 9, 25)))
    assert receipt.due_date is not None or receipt.confidence == "low"


@given(recent, scopes, regions, natures)
def test_compute_due_with_deemed_delivery_is_after_posting(
    posted: date, scope: str, region: str | None, nature: str
) -> None:
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature=nature,  # type: ignore[arg-type]
    )
    receipt = compute_due(
        spec, RuleContext(today=posted, region=region, document_date=posted, delivery_scope=scope)
    )  # type: ignore[arg-type]
    assert receipt.due_date is not None
    assert date.fromisoformat(receipt.due_date) > posted + timedelta(days=28)


contract_terms = st.builds(
    ContractTerms,
    category=st.sampled_from(
        [
            "mobile",
            "internet",
            "energy",
            "gas",
            "insurance",
            "gym",
            "streaming",
            "rent",
            "employment",
            "bank",
            "other",
        ]
    ),
    party_kind=st.sampled_from([None, "insurer", "health_insurer", "telecom", "landlord"]),
    concluded_date=st.one_of(st.none(), dates.map(date.isoformat)),
    start_date=st.one_of(st.none(), dates.map(date.isoformat)),
    initial_term_months=st.one_of(st.none(), st.integers(min_value=-1, max_value=48)),
    renewal_term_months=st.one_of(st.none(), st.integers(min_value=-1, max_value=24)),
    notice_value=st.one_of(st.none(), st.integers(min_value=-1, max_value=6)),
    notice_unit=st.one_of(st.none(), st.sampled_from(["days", "weeks", "months"])),
    notice_basis=st.one_of(st.none(), st.sampled_from(["end_of_term", "any_time", "end_of_month"])),
    notice_day=st.one_of(st.none(), st.integers(min_value=-1, max_value=33)),
    notice_before_end=st.booleans(),
    end_date=st.one_of(st.none(), dates.map(date.isoformat)),
    is_consumer=st.booleans(),
    is_basic_supply=st.booleans(),
    status=st.sampled_from(["active", "active", "active", "cancelled", "ended"]),
)


@given(
    contract_terms,
    dates,
    regions,
    st.sampled_from(["letter", "registered_letter", "email", "fax", "portal", "in_person", "online_button"]),
)
def test_contract_dates_are_consistent(
    terms: ContractTerms, today: date, region: str | None, channel: str
) -> None:
    result = compute_contract(terms, RuleContext(today=today, region=region), channel=channel)  # type: ignore[arg-type]
    assert result.summary
    if result.cancel_by:
        cancel_by = date.fromisoformat(result.cancel_by)
        assert cancel_by >= today
        assert result.send_by is not None and result.safe_date is not None
        assert today <= date.fromisoformat(result.send_by) <= cancel_by
        assert date.fromisoformat(result.safe_date) <= cancel_by
        assert result.earliest_exit is not None and date.fromisoformat(result.earliest_exit) >= cancel_by
    if result.earliest_exit and terms.status == "active" and result.cancel_by is None and result.next_renewal:
        assert date.fromisoformat(result.earliest_exit) > today
