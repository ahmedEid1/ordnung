"""Logic and integration of ``ordnung.rules``: regression tests from a line-by-line reading (2026-09-25).

Every test here documents a defect found by reading the engine line by line and checking it against
SPEC § 21 (earliest plausible date when uncertain; confidence rubric) and the verified legal research.
They were written as strict xfails; each defect was confirmed and the engine fixed, so they are now
plain regression tests. The last section covers observations that were fixed too.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from helpers_tables import check_rows
from ordnung.models import ContractTerms, DateSpec
from ordnung.rules import catalog
from ordnung.rules.contracts import compute_contract
from ordnung.rules.deadlines import RuleContext, compute_due

D = date.fromisoformat


def ctx(today: str = "2026-09-25", **kw: Any) -> RuleContext:
    for key in ("document_date", "received_date"):
        if isinstance(kw.get(key), str):
            kw[key] = D(kw[key])
    return RuleContext(today=D(today), **kw)


# ------------------------------------------------------------------------------------ deadlines


def test_vwvfg_portal_decision_counts_from_day_after_download() -> None:
    spec = DateSpec.model_validate(
        {
            "type": "relative",
            "anchor": "deemed_delivery",
            "amount": 1,
            "unit": "months",
            "delivery_rule": "de_admin_portal",
            "nature": "objection",
            "legal_basis": "§ 70 VwGO",
        }
    )
    receipt = compute_due(spec, ctx(document_date="2026-09-14", delivery_scope="vwvfg", region="BY"))
    # provided Mon 14 Sep → earliest download that day → delivered Tue 15 Sep → Thu 15 Oct 2026
    assert receipt.due_date is not None and receipt.due_date <= "2026-10-15"


def test_klage_deadline_is_not_a_silent_high_confidence_date() -> None:
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
        legal_basis="§ 74 VwGO",
    )
    receipt = compute_due(spec, ctx(document_date="2026-09-21", delivery_scope="vwvfg", region="BY"))
    assert "klage_1_month" in receipt.rule_ids
    assert receipt.due_date is None or (
        receipt.confidence != "high" and any("advice" in w for w in receipt.warnings)
    )


HUGE_PERIODS = [(10_000, "years"), (10**7, "days"), (-(10**7), "days")]


def test_huge_periods_do_not_crash() -> None:
    def check(amount: int, unit: str) -> None:
        spec = DateSpec(type="relative", anchor="document_date", amount=amount, unit=unit, nature="payment")  # type: ignore[arg-type]
        receipt = compute_due(spec, ctx(document_date="2026-09-20"))
        assert receipt.confidence == "low"

    check_rows(HUGE_PERIODS, check)


# ------------------------------------------------------------------------------------ contracts


def test_renewal_zero_means_indefinite_not_fixed_term() -> None:
    result = compute_contract(
        ContractTerms(
            category="gym",
            concluded_date="2025-01-01",
            start_date="2025-01-01",
            end_date="2026-12-31",
            renewal_term_months=0,
        ),
        ctx(region="NW"),
    )
    assert "no cancellation needed" not in result.summary
    assert result.cancel_by == "2026-11-30"  # ≤ 1 month before the minimum term ends (§ 309 Nr. 9 BGB)


def test_renewal_zero_old_contract_is_cancellable_any_time() -> None:
    result = compute_contract(
        ContractTerms(
            category="gym",
            concluded_date="2021-01-01",
            start_date="2021-01-01",
            initial_term_months=24,
            renewal_term_months=0,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(region="NW"),
    )
    assert result.cancel_by is None
    assert "renews" not in result.summary


def test_vvg_third_year_exit_needs_three_months_notice() -> None:
    result = compute_contract(
        ContractTerms(
            category="insurance",
            party_kind="insurer",
            start_date="2024-01-01",
            initial_term_months=60,
            renewal_term_months=12,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(today="2026-09-01"),
    )
    assert result.earliest_exit == "2026-12-31"
    assert result.cancel_by == "2026-09-30"  # before the fix: 2026-11-30
    with_end_date = compute_contract(
        ContractTerms(
            category="insurance",
            party_kind="insurer",
            start_date="2024-01-01",
            initial_term_months=60,
            end_date="2028-12-31",
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(today="2026-09-01"),
    )
    assert with_end_date.earliest_exit == "2026-12-31"
    assert with_end_date.cancel_by == "2026-09-30"  # before the fix: 2028-09-30
    # term and end date without a start: the start is derived, year 3 still comes first
    end_date_only = compute_contract(
        ContractTerms(
            category="insurance",
            party_kind="insurer",
            initial_term_months=60,
            end_date="2028-12-31",
            renewal_term_months=12,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(today="2026-09-01"),
    )
    assert (end_date_only.cancel_by, end_date_only.earliest_exit) == ("2026-09-30", "2026-12-31")


def test_old_consumer_contract_first_term_is_capped_at_two_years() -> None:
    result = compute_contract(
        ContractTerms(
            category="gym",
            concluded_date="2021-10-01",
            start_date="2021-10-01",
            initial_term_months=30,
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(today="2026-05-01"),
    )
    # capped: 30 Sep 2023, then yearly → exit 30 Sep 2026, notice by 30 Jun 2026 (before the fix: 31 Dec 2026)
    assert result.cancel_by is not None and result.cancel_by <= "2026-06-30"
    assert result.confidence != "high"


HUGE_CONTRACT_NUMBERS = [
    {
        "category": "gym",
        "concluded_date": "2021-01-01",
        "start_date": "2021-01-01",
        "initial_term_months": 12,
        "notice_value": 10**6,
        "notice_unit": "days",
    },
    {
        "category": "bank",
        "start_date": "2021-01-01",
        "initial_term_months": 10**6,
        "renewal_term_months": 12,
        "notice_value": 1,
        "notice_unit": "months",
    },
]


def test_huge_contract_numbers_do_not_crash() -> None:
    def check(kw: dict[str, Any]) -> None:
        result = compute_contract(ContractTerms(**kw), ctx())
        assert result.confidence == "low"

    check_rows(HUGE_CONTRACT_NUMBERS, check)


# ------------------------------------------------------------------------------------ catalog


def test_catalog_texts_match_engine() -> None:
    unknown = catalog.get_rule("delivery_scope_unknown").summary
    elster = catalog.get_rule("ao_122a_4").summary
    assert "3" in unknown
    assert "from 2025: after the notification" not in elster


# ------------------------------------------------------------------------------------ details of the fixes


def test_backward_period_keeps_its_day_and_gets_a_safe_date() -> None:
    """The words "pay one month before Tue 6 Oct" ends Sat 5 Sep; aim for Fri 4 Sep, never Mon 7 Sep."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-10-06",
        amount=-1,
        unit="months",
        nature="payment",
    )
    receipt = compute_due(spec, ctx(today="2026-08-01", recipient_region="NW"))
    assert (receipt.due_date, receipt.safe_date, receipt.send_by) == (
        "2026-09-05",
        "2026-09-04",
        "2026-09-03",
    )
    assert "backward_no_shift" in receipt.rule_ids and "bgb_193" not in receipt.rule_ids
    assert receipt.summary == (
        "One month before Tue 6 Oct 2026 is Sat 5 Sep 2026, a Saturday; deadlines counted backwards don't "
        "move, so aim for Fri 4 Sep 2026."
    )
    on_a_weekday = compute_due(
        spec.model_copy(update={"amount": -2, "unit": "weeks", "nature": "declaration"}),
        ctx(today="2026-08-01"),
    )
    assert (on_a_weekday.due_date, on_a_weekday.safe_date) == ("2026-09-21", "2026-09-21")
    other = compute_due(spec.model_copy(update={"nature": "other"}), ctx(today="2026-08-01"))
    assert (other.due_date, other.safe_date) == ("2026-09-05", None)
    # the letter's own words, with its date and no known payer region: never later than Sat 5 Sep
    worded = compute_due(
        spec.model_copy(update={"text": "spätestens einen Monat vor Kursbeginn am 06.10.2026"}),
        ctx(today="2026-08-01", document_date="2026-07-20"),
    )
    assert worded.due_date is not None
    assert worded.due_date <= "2026-09-05"  # before the fix: Mon 7 Sep 2026 (after "one month before")


PORTAL_RULES = [
    # § 122a Abs. 4 AO: 4th day after provision (Fri 25 Sep → Tue 29 Sep) — research example
    pytest.param("ao", "2026-09-25", "ao_122a_4", "2026-10-29", id="elster"),
    # § 37 Abs. 2a SGB X: 4th day after the notification (Sun 4 Oct, not moved)
    pytest.param("sgbx", "2026-09-30", "sgbx_37_2a", "2026-11-04", id="sgbx-portal"),
    # sender unknown: the day after the earliest download (§ 41 Abs. 2a VwVfG), earliest plausible
    pytest.param(None, "2026-09-14", "vwvfg_41_2a", "2026-10-15", id="unknown-sender-portal"),
]


def test_portal_rules_are_reachable() -> None:
    """Portal letters cite the portal rule of their scope."""

    def check(scope: str | None, provided: str, rule: str, expected: str) -> None:
        spec = DateSpec(
            type="relative",
            anchor="deemed_delivery",
            amount=1,
            unit="months",
            delivery_rule="de_admin_portal",
            nature="objection",
        )
        receipt = compute_due(
            spec, ctx(document_date=provided, delivery_scope=scope, region="NW", recipient_region="NW")
        )
        assert receipt.due_date == expected
        assert rule in receipt.rule_ids
        assert "ao_122_2a" not in receipt.rule_ids

    check_rows(PORTAL_RULES, check)


def test_payment_holidays_follow_the_payer_only_for_private_creditors() -> None:
    """A private payment → payer's Land (unknown → nationwide + warning); tax payment → the office's."""
    invoice = DateSpec(
        type="relative", anchor="document_date", amount=14, unit="days", nature="payment"
    )  # 22 Feb 2027 + 14 days = Mon 8 Mar 2027 (Frauentag in Berlin)
    payer_berlin = compute_due(
        invoice, ctx(today="2027-02-22", document_date="2027-02-22", region="NW", recipient_region="BE")
    )
    assert payer_berlin.due_date == "2027-03-09"
    assert payer_berlin.holiday_calendar == "Berlin"
    payer_unknown = compute_due(invoice, ctx(today="2027-02-22", document_date="2027-02-22", region="BE"))
    assert payer_unknown.due_date == "2027-03-08"
    assert payer_unknown.confidence == "medium"  # a regional holiday could make it later
    tax = compute_due(
        invoice,
        ctx(
            today="2027-02-22",
            document_date="2027-02-22",
            region="BE",
            recipient_region="NW",
            delivery_scope="ao",
        ),
    )
    assert tax.due_date == "2027-03-09"  # holidays at the tax office's seat
    assert "ao_108_3" in tax.rule_ids
    payer_nrw = compute_due(
        invoice.model_copy(update={"text": "zahlbar innerhalb von 14 Tagen nach Rechnungsdatum"}),
        ctx(today="2027-02-22", document_date="2027-02-22", region="BE", recipient_region="NW"),
    )
    # Mon 8 Mar 2027 is Frauentag in Berlin only; in NRW (payer) it is a working day.
    assert payer_nrw.due_date == "2027-03-08"  # before the fix: Tue 9 Mar 2027


def test_today_anchor_never_counts_from_a_later_day() -> None:
    """The anchor 'today' is the letter's date; the processing day only when that is earlier or unknown."""
    spec = DateSpec(type="relative", anchor="today", amount=14, unit="days", nature="declaration")
    written = compute_due(spec, ctx(document_date="2026-09-01"))
    assert written.due_date == "2026-09-15"
    assert written.confidence != "high"
    future = compute_due(spec, ctx(document_date="2026-10-01"))
    assert (future.due_date, future.confidence) == ("2026-10-09", "medium")
    undated = compute_due(spec, ctx())
    assert (undated.due_date, undated.confidence) == ("2026-10-09", "low")


def test_dates_at_the_end_of_the_calendar_do_not_crash() -> None:
    """A misread anchor near year 9999 gives a 'no date' receipt instead of an exception."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="9999-12-20",
        amount=1,
        unit="months",
        nature="payment",
    )
    receipt = compute_due(spec, ctx())
    assert (receipt.due_date, receipt.confidence) == (None, "low")
    assert (
        receipt.summary
        == "No date could be computed: the dates in the letter are out of range — please check them."
    )
    contract = compute_contract(
        ContractTerms(
            category="gym",
            concluded_date="9999-06-01",
            start_date="9999-06-01",
            initial_term_months=12,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
    )
    assert (contract.cancel_by, contract.confidence) == (None, "low")
    assert contract.summary.endswith("the contract's dates are out of range — please check them.")


def test_renewal_zero_as_written_and_insurance() -> None:
    """A renewal of 0 = indefinite after the first term, for contracts as written and (yearly periods) insurance."""
    running = compute_contract(
        ContractTerms(
            category="bank",
            start_date="2026-01-01",
            initial_term_months=12,
            renewal_term_months=0,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
    )
    assert (running.cancel_by, running.earliest_exit) == ("2026-11-30", "2026-12-31")
    assert "otherwise it continues" in running.summary
    after = compute_contract(
        ContractTerms(
            category="bank",
            start_date="2025-01-01",
            initial_term_months=12,
            renewal_term_months=0,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
    )
    assert (after.cancel_by, after.earliest_exit) == (None, "2026-11-01")  # letter arrives Thu 1 Oct
    insurance = compute_contract(
        ContractTerms(
            category="insurance",
            party_kind="insurer",
            start_date="2024-01-01",
            initial_term_months=12,
            renewal_term_months=0,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(),
    )
    assert (insurance.cancel_by, insurance.current_term_end) == ("2026-09-30", "2026-12-31")
    assert insurance.confidence == "medium"
    assert any("§ 11 Abs. 2 VVG" in w for w in insurance.warnings)


# ------------------------------------------------------------------------------------ observations


def test_fine_counted_from_the_letter_date_without_the_envelope() -> None:
    """Observation (§ 67 OWiG): with the deemed-delivery anchor the 4th-day fiction could be up to three
    days later than a yellow-envelope delivery; the engine counts from the letter's date instead."""
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=2,
        unit="weeks",
        delivery_rule="de_admin_post",
        nature="objection",
        legal_basis="§ 67 OWiG",
    )
    receipt = compute_due(spec, ctx(document_date="2026-09-21", region="NW", delivery_scope="vwvfg"))
    assert receipt.due_date == "2026-10-05"  # Mon 21 Sep + 2 weeks; PZU on Tue 22 Sep would give Tue 6 Oct
    assert receipt.confidence == "medium"
    assert not any(step.rule_id in ("vwvfg_41_2", "vwvfg_land_days") for step in receipt.steps)


TAX_DELIVERY_DAYS = [
    # 4th day Tue 6 Jan 2026 is Epiphany in Saxony-Anhalt (tax office) only: nothing to flag
    pytest.param("2026-01-02", "ST", "NW", "high", False, id="holiday-at-tax-office-only"),
    # 4th day Thu 4 Jun 2026 is Fronleichnam where the person lives: it may move → flagged
    pytest.param("2026-05-31", "ST", "NW", "medium", True, id="holiday-at-home"),
    # tax office's Land unknown, Epiphany is no holiday in NW: nothing to flag
    pytest.param("2026-01-02", None, "NW", "high", False, id="office-unknown-no-home-holiday"),
]


def test_tax_delivery_day_flags_only_the_person_s_holidays() -> None:
    """Observation: two different known Länder no longer produce the 'if you live in the same Land' text."""

    def check(posted: str, tax_office: str | None, home: str, confidence: str, flagged: bool) -> None:
        spec = DateSpec(
            type="relative",
            anchor="deemed_delivery",
            amount=1,
            unit="months",
            delivery_rule="de_admin_post",
            nature="objection",
            legal_basis="§ 355 AO",
        )
        receipt = compute_due(
            spec, ctx(document_date=posted, region=tax_office, recipient_region=home, delivery_scope="ao")
        )
        assert receipt.confidence == confidence, receipt.warnings
        assert not any("same Land" in w for w in receipt.warnings)
        assert any("where you live (Nordrhein-Westfalen)" in w for w in receipt.warnings) == flagged

    check_rows(TAX_DELIVERY_DAYS, check)


def test_health_insurance_exit_is_a_month_end_after_a_mid_month_start() -> None:
    """Observation (§ 175 Abs. 4 SGB V): membership from 15 Jun 2026 is bound until 14 Jun 2027 and can
    end on 30 Jun 2027 at the earliest; notice given in April 2027 reaches that end."""
    result = compute_contract(
        ContractTerms(category="insurance", party_kind="health_insurer", start_date="2026-06-15"), ctx()
    )
    assert (result.earliest_exit, result.cancel_by) == ("2027-06-30", "2027-04-30")


def test_vvg_short_term_end_date_and_missing_dates() -> None:
    """The insurance-year helper: an end date within three years is the first insurance-year end (no assumption needed);
    without start and end there is nothing to count from."""
    two_years = compute_contract(
        ContractTerms(
            category="insurance",
            party_kind="insurer",
            start_date="2025-01-01",
            end_date="2026-12-31",
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(),
    )
    assert (two_years.cancel_by, two_years.earliest_exit, two_years.confidence) == (
        "2026-09-30",
        "2026-12-31",
        "high",
    )
    assert not any("§ 11 Abs. 4 VVG" in w for w in two_years.warnings)
    undated = compute_contract(
        ContractTerms(category="insurance", party_kind="insurer", notice_value=3, notice_unit="months"), ctx()
    )
    assert (undated.cancel_by, undated.confidence) == (None, "low")
