"""Hypothesis properties of the high-stakes letter rules (SPEC § 18): what holds for every date."""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from ordnung.models import DateSpec, DocumentExtraction, ExtractedParty
from ordnung.rules import calendar_de, routing
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.consumer import long_withdrawal_end, withdrawal_end
from ordnung.rules.deadlines import RuleContext, compute_due
from ordnung.rules.employment import registration_deadline
from ordnung.rules.periods import add_months
from ordnung.rules.tenancy import consent_period, month_end, notice_objection_deadline, statement_check

dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2060, 12, 31))
regions = st.one_of(st.none(), st.sampled_from(sorted(REGION_NAMES)))

settings.register_profile("letters", max_examples=150, deadline=None, database=None)
settings.load_profile("letters")


@given(dates)
def test_the_consent_period_ends_on_a_month_end_two_to_three_months_later(arrived: date) -> None:
    last, rent_from = consent_period(arrived)
    assert last == month_end(last)
    assert 59 <= (last - arrived).days <= 92
    assert rent_from.day == 1 and rent_from == last + timedelta(days=1)


@given(dates)
def test_the_notice_objection_is_the_last_day_two_months_still_fit(end: date) -> None:
    due = notice_objection_deadline(end)
    assert add_months(due, 2) <= end < add_months(due + timedelta(days=1), 2)


@given(dates, st.one_of(st.none(), st.integers(min_value=0, max_value=400)))
def test_registration_is_never_later_than_either_rule_allows(learned: date, days_left: int | None) -> None:
    end = learned + timedelta(days=days_left) if days_left is not None else None
    due, basis = registration_deadline(learned, end)
    if basis == "before_end":
        assert end is not None and learned <= due and add_months(due, 3) <= end
    else:
        assert due == learned + timedelta(days=3)
        assert end is None or add_months(learned, 3) > end or learned > due - timedelta(days=3)


@given(dates)
def test_the_long_withdrawal_period_is_a_year_after_the_regular_one(start: date) -> None:
    end, differ = long_withdrawal_end(start)
    regular = withdrawal_end(start)
    assert 363 <= (end - regular).days <= 366
    directive, literal = add_months(regular, 12), add_months(start, 12) + timedelta(days=14)
    assert end == min(directive, literal) and differ == (directive != literal)
    assert abs((directive - literal).days) <= 3


@given(dates, regions)
def test_a_withdrawal_ends_on_a_working_day_and_only_has_to_be_sent(start: date, region: str | None) -> None:
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=start.isoformat(),
        amount=14,
        unit="days",
        nature="declaration",
        legal_basis="§ 355 BGB",
    )
    receipt = compute_due(spec, RuleContext(today=start, recipient_region=region))
    assert receipt.due_date is not None
    due = date.fromisoformat(receipt.due_date)
    assert calendar_de.is_business_day(due, region)
    assert 14 <= (due - start).days <= 18
    assert receipt.send_by == receipt.due_date


@given(dates, regions, st.sampled_from(["court_payment_order", "enforcement_order"]))
def test_court_orders_end_on_a_working_day_and_are_never_high(served: date, region: str | None, kind: str) -> None:
    spec = DateSpec(type="relative", anchor="receipt", amount=2, unit="weeks", nature="objection")
    ctx = RuleContext(
        today=served, region=region, document_date=served, received_date=served, received_confirmed=True, letter_kind=kind
    )
    receipt = compute_due(spec, ctx)
    assert receipt.due_date is not None and receipt.confidence != "high"
    due = date.fromisoformat(receipt.due_date)
    assert calendar_de.is_business_day(due, region) and 14 <= (due - served).days <= 18


@given(dates, st.integers(min_value=0, max_value=800), st.booleans(), regions)
def test_a_statement_is_only_called_late_when_it_certainly_is(
    period_end: date, days: int, confirmed: bool, region: str | None
) -> None:
    arrived = period_end + timedelta(days=days)
    check = statement_check(period_end, arrived, confirmed=confirmed, region=region)
    assert check.deadline >= month_end(add_months(period_end, 12))
    if check.late:
        assert arrived > check.deadline
    elif check.late is False:
        assert confirmed and arrived <= check.deadline
    else:
        assert not confirmed and arrived <= check.deadline
    assert check.objections_by >= add_months(arrived, 12)


names = st.text(alphabet=st.characters(categories=["L", "Zs"]), max_size=40).filter(
    lambda name: "gericht" not in name.casefold()
)


@given(names, st.sampled_from(["Mahnbescheid", "Vollstreckungsbescheid"]))
def test_only_a_court_makes_a_court_order(name: str, title: str) -> None:
    extraction = DocumentExtraction(
        kind="dunning",
        title=title,
        summary=title,
        explanation="",
        sender=ExtractedParty(name=name or "Inkasso", kind="company"),
    )
    assert routing.classify_letter(extraction) not in ("court_payment_order", "enforcement_order")
