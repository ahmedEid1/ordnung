"""Contracts, price-increase windows, send guidance and the rules catalog.

Research rules cited in ids: ``309new``/``309old`` = bgb_309_nr9_*, ``no193`` =
kuendigung_no_193_zugang_deadline_and_send_by, ``arith`` = kuendigungsfrist_period_arithmetic_187_188,
``tkg56``, ``tkg57``, ``enwg41`` = enwg_41_5_energy_price_change_special_cancellation, ``gv`` =
grundversorgung_stromgvv_gasgvv_cancellation, ``573c`` = bgb_573c_residential_lease_notice_third_werktag,
``568`` = bgb_568_lease_termination_written_form, ``309n13`` = bgb_309_nr13_textform, ``312k``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ordnung.models import ContractTerms
from ordnung.rules import catalog
from ordnung.rules.contracts import (
    compute_contract,
    contract_origin,
    end_of_month,
    price_increase_window,
    regime_for,
    term_end,
    third_werktag,
)
from ordnung.rules.deadlines import RuleContext
from ordnung.rules.send import send_guidance

D = date.fromisoformat
TODAY = D("2026-09-25")


def ctx(today: str | date = TODAY, region: str | None = "NW", **kw: Any) -> RuleContext:
    return RuleContext(today=D(today) if isinstance(today, str) else today, region=region, **kw)


def terms(**kw: Any) -> ContractTerms:
    return ContractTerms(**kw)


# --------------------------------------------------------------------------------------- regimes


@pytest.mark.parametrize(
    ("kw", "regime"),
    [
        ({"category": "rent"}, "rent573c"),
        ({"category": "employment"}, "employment622"),
        ({"category": "energy", "is_basic_supply": True}, "stromgvv20"),
        ({"category": "gas", "is_basic_supply": True}, "stromgvv20"),
        ({"category": "energy", "concluded_date": "2023-01-01"}, "bgb309_new"),
        ({"category": "insurance", "party_kind": "health_insurer"}, "sgbv175"),
        ({"category": "insurance", "party_kind": "insurer"}, "vvg11"),
        ({"category": "mobile"}, "tkg56"),
        ({"category": "internet", "concluded_date": "2019-03-15"}, "tkg56"),
        ({"category": "gym", "concluded_date": "2022-03-01"}, "bgb309_new"),
        ({"category": "gym", "concluded_date": "2022-02-28"}, "bgb309_old"),
        ({"category": "streaming", "start_date": "2023-05-10"}, "bgb309_new"),
        ({"category": "streaming"}, "as_written"),
        ({"category": "bank", "concluded_date": "2023-01-01"}, "as_written"),
        ({"category": "gym", "concluded_date": "2023-01-01", "is_consumer": False}, "as_written"),
    ],
)
def test_regime_for(kw: dict[str, Any], regime: str) -> None:
    assert regime_for(terms(**kw)) == regime


def test_helpers() -> None:
    assert contract_origin(terms(concluded_date="2025-01-02", start_date="2025-01-15")) == D("2025-01-02")
    assert contract_origin(terms(start_date="2025-01-15")) == D("2025-01-15")
    assert contract_origin(terms()) is None
    assert term_end(D("2024-03-01"), 24) == D("2026-02-28")
    assert end_of_month(2026, 14) == D("2027-02-28")
    assert third_werktag(2026, 10, None) == D("2026-10-05")
    assert third_werktag(2026, 4, None) == D("2026-04-04")


# ------------------------------------------------------------------------------- demo persona


def test_phone_contract() -> None:
    """Demo: phone contract started 2024-11-15, 24 months, 1 month's notice → cancel by 2026-10-14."""
    result = compute_contract(
        terms(
            category="mobile",
            party_kind="telecom",
            concluded_date="2024-11-15",
            start_date="2024-11-15",
            initial_term_months=24,
            notice_value=1,
            notice_unit="months",
            notice_basis="end_of_term",
        ),
        ctx(),
    )
    assert result.regime == "tkg56"
    assert result.current_term_end == "2026-11-14"  # 309new/arith: term ends Sat 14 Nov 2026
    assert result.cancel_by == "2026-10-14"
    assert result.safe_date == "2026-10-14"
    assert result.send_by == "2026-10-08"  # 4 business days before (research: Fri 9 Oct counting Sat)
    assert result.earliest_exit == "2026-11-14"
    assert result.next_renewal == "2026-11-15"
    assert result.confidence == "high"
    assert result.summary == (
        "To leave when the term ends on Sat 14 Nov 2026, your cancellation must arrive by Wed 14 Oct 2026 — "
        "send it by Thu 8 Oct; otherwise it continues."
    )


def test_phone_contract_after_the_deadline_continues_monthly() -> None:
    """309new: same contract, cancellation received Tue 20 Oct 2026 → ends Fri 20 Nov 2026."""
    result = compute_contract(
        terms(
            category="mobile",
            concluded_date="2024-11-15",
            start_date="2024-11-15",
            initial_term_months=24,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(today="2026-10-20"),
        channel="online_button",
    )
    assert result.cancel_by is None
    assert result.earliest_exit == "2026-11-20"
    assert result.current_term_end == "2026-11-14"
    assert result.next_renewal == "2026-11-15"
    assert result.summary == (
        "After the minimum term (until Sat 14 Nov 2026) you can cancel any time with one month's notice: "
        "if your cancellation arrives by Tue 20 Oct 2026, the contract ends on Fri 20 Nov 2026."
    )


def test_gym_contract_indefinite() -> None:
    """Demo: gym concluded 2025-01-02, start 2025-01-15, 12 months → indefinite after 2026-01-14."""
    gym = terms(
        category="gym",
        party_kind="gym",
        concluded_date="2025-01-02",
        start_date="2025-01-15",
        initial_term_months=12,
        notice_value=1,
        notice_unit="months",
        notice_basis="any_time",
    )
    result = compute_contract(gym, ctx())
    assert result.regime == "bgb309_new"
    assert result.cancel_by is None and result.send_by is None and result.next_renewal is None
    assert result.earliest_exit == "2026-11-01"  # letter arrives Thu 1 Oct (4 business days)
    assert result.confidence == "high"
    button = compute_contract(gym, ctx(), channel="online_button")
    assert button.earliest_exit == "2026-10-25"
    during_term = compute_contract(gym, ctx(today="2025-11-01"))
    assert during_term.cancel_by == "2025-12-14"
    assert during_term.current_term_end == "2026-01-14"


def test_liability_insurance_year() -> None:
    """Demo: liability insurance from 2023-12-01, insurance year Dec–Nov, 3 months → 2026-08-31, then 2027-08-31."""
    insurance = terms(
        category="insurance",
        party_kind="insurer",
        concluded_date="2023-12-01",
        start_date="2023-12-01",
        initial_term_months=12,
        renewal_term_months=12,
        notice_value=3,
        notice_unit="months",
        notice_basis="end_of_term",
    )
    before = compute_contract(insurance, ctx(today="2026-08-01"))
    assert before.regime == "vvg11"
    assert before.cancel_by == "2026-08-31"
    assert before.earliest_exit == before.current_term_end == "2026-11-30"
    after = compute_contract(insurance, ctx())
    assert after.cancel_by == "2027-08-31"
    assert after.current_term_end == "2026-11-30"
    assert after.next_renewal == "2026-12-01"
    assert after.earliest_exit == "2027-11-30"
    assert after.summary.startswith(
        "The deadline for the current term (Mon 31 Aug 2026) has passed, so it renews on Tue 1 Dec 2026; to leave"
    )


def test_insurance_defaults_and_caps() -> None:
    result = compute_contract(
        terms(category="insurance", start_date="2024-01-01", notice_value=6, notice_unit="months"), ctx()
    )
    assert result.current_term_end == "2026-12-31"
    assert result.cancel_by == "2026-09-30"  # capped at three months (§ 11 Abs. 3 VVG)
    assert result.confidence == "low"  # insurance year and renewal assumed
    assert any("at most three months" in w for w in result.warnings)
    long_term = compute_contract(
        terms(
            category="insurance",
            start_date="2024-01-01",
            initial_term_months=60,
            renewal_term_months=24,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(),
    )
    assert long_term.current_term_end == "2026-12-31"  # end of the 3rd year (§ 11 Abs. 4 VVG)
    assert any("§ 11 Abs. 4 VVG" in w for w in long_term.warnings)


def test_statutory_health_insurance() -> None:
    health = terms(category="insurance", party_kind="health_insurer", start_date="2024-10-01")
    result = compute_contract(health, ctx())
    assert result.regime == "sgbv175"
    assert result.cancel_by == "2026-09-30"
    assert result.earliest_exit == "2026-11-30"
    assert result.send_by == "2026-09-25"
    locked = compute_contract(
        terms(category="insurance", party_kind="health_insurer", start_date="2026-03-01"), ctx()
    )
    assert locked.earliest_exit == "2027-02-28"  # 12-month minimum membership
    assert locked.cancel_by == "2026-12-31"
    unknown = compute_contract(terms(category="insurance", party_kind="health_insurer"), ctx())
    assert unknown.earliest_exit == "2026-11-30"
    assert unknown.confidence == "medium"


def test_basic_supply_two_weeks() -> None:
    """gv: Grundversorgung cancellation received Tue 29 Sep 2026 → ends Tue 13 Oct 2026."""
    supply = terms(category="energy", is_basic_supply=True, start_date="2025-10-01")
    result = compute_contract(supply, ctx(today="2026-09-29"), channel="online_button")
    assert result.regime == "stromgvv20"
    assert result.earliest_exit == "2026-10-13"
    gas = compute_contract(
        terms(category="gas", is_basic_supply=True), ctx(today="2026-10-02"), channel="email"
    )
    assert gas.earliest_exit == "2026-10-16"


@pytest.mark.parametrize(
    ("today", "cancel_by", "exit_day", "send_by"),
    [
        pytest.param("2026-09-25", "2026-10-05", "2026-12-31", "2026-09-29", id="573c-october-3-oct-holiday"),
        pytest.param(
            "2026-10-06", "2026-11-04", "2027-01-31", "2026-10-29", id="573c-received-6-oct-next-month"
        ),
        pytest.param("2026-10-20", "2026-11-04", "2027-01-31", "2026-10-29", id="573c-november"),
        pytest.param("2026-03-20", "2026-04-04", "2026-06-30", "2026-03-27", id="573c-april-saturday"),
    ],
)
def test_rent_notice(today: str, cancel_by: str, exit_day: str, send_by: str) -> None:
    result = compute_contract(
        terms(category="rent", party_kind="landlord", start_date="2024-10-01"), ctx(today=today)
    )
    assert result.regime == "rent573c"
    assert result.cancel_by == cancel_by
    assert result.earliest_exit == exit_day
    assert result.send_by == send_by
    assert any("§ 568 BGB" in n for n in result.notes)


def test_rent_saturday_deadline_is_kept_and_explained() -> None:
    result = compute_contract(terms(category="rent"), ctx(today="2026-03-30"))
    assert result.cancel_by == "2026-04-04"
    assert result.safe_date == "2026-04-02"
    assert any("VIII ZR 206/04" in w for w in result.warnings)


def test_rent_requires_signed_letter_and_statutory_period() -> None:
    result = compute_contract(
        terms(category="rent", notice_value=6, notice_unit="months"), ctx(), channel="email"
    )
    assert result.cancel_by == "2026-10-05"
    assert any("hand-signed letter" in w for w in result.warnings)
    assert any("§ 573c Abs. 4 BGB" in w for w in result.warnings)


def test_rent_region_unknown_regional_holiday() -> None:
    # Mon 1 Nov 2027 is Allerheiligen in NW (not nationwide): without a region it counts as a Werktag,
    # which gives the earlier deadline and a lower confidence.
    result = compute_contract(terms(category="rent"), ctx(today="2027-10-10", region=None))
    assert result.cancel_by == "2027-11-03"
    assert result.confidence == "medium"
    nrw = compute_contract(terms(category="rent"), ctx(today="2027-10-10", region="NW"))
    assert nrw.cancel_by == "2027-11-04"
    assert nrw.confidence == "high"


def test_fixed_term_employment_is_a_milestone() -> None:
    """Demo: Werkstudent contract ending 2027-03-31."""
    result = compute_contract(
        terms(category="employment", start_date="2025-04-01", end_date="2027-03-31"), ctx()
    )
    assert result.regime == "employment622"
    assert result.cancel_by is None
    assert result.earliest_exit == result.current_term_end == "2027-03-31"
    assert result.summary == "This contract ends by itself on Wed 31 Mar 2027 — no cancellation needed."
    assert "fixed_term" in result.rule_ids
    past = compute_contract(terms(category="employment", end_date="2026-03-31"), ctx())
    assert past.summary == "This contract ended on Tue 31 Mar 2026."


@pytest.mark.parametrize(
    ("kw", "cancel_by", "exit_day"),
    [
        ({}, "2026-10-03", "2026-10-31"),  # statutory four weeks to the 15th / end of month
        (
            {"notice_value": 1, "notice_unit": "months", "notice_basis": "end_of_month"},
            "2026-09-30",
            "2026-10-31",
        ),
        ({"notice_value": 2, "notice_unit": "weeks", "notice_basis": "any_time"}, None, "2026-10-15"),
    ],
)
def test_employment_notice(kw: dict[str, Any], cancel_by: str | None, exit_day: str) -> None:
    result = compute_contract(terms(category="employment", **kw), ctx())
    assert result.cancel_by == cancel_by
    assert result.earliest_exit == exit_day
    assert any("§ 623 BGB" in n for n in result.notes)


def test_employment_fifteenth_exit() -> None:
    result = compute_contract(terms(category="employment"), ctx(today="2026-10-10"))
    assert result.earliest_exit == "2026-11-15"
    assert result.cancel_by == "2026-10-18"


# ------------------------------------------------------------------------ research examples


def test_309_new_contract_hesse_holiday_deadline() -> None:
    """no193: contract ends Tue 3 Nov 2026, 1 month → Sat 3 Oct (holiday), safe Fri 2 Oct, post Mon 28 Sep."""
    result = compute_contract(
        terms(
            category="streaming",
            concluded_date="2024-11-04",
            end_date="2026-11-03",
            notice_value=1,
            notice_unit="months",
        ),
        ctx(region="HE"),
    )
    assert result.cancel_by == "2026-10-03"
    assert result.safe_date == "2026-10-02"
    assert result.send_by == "2026-09-28"


def test_309_new_month_end_contract() -> None:
    """no193/arith: contract ends Sun 28 Feb 2027, 1 month → Sun 31 Jan, safe Fri 29 Jan, post Mon 25 Jan."""
    stream = terms(
        category="streaming",
        concluded_date="2025-03-01",
        end_date="2027-02-28",
        notice_value=1,
        notice_unit="months",
    )
    result = compute_contract(stream, ctx(today="2027-01-10"))
    assert (result.cancel_by, result.safe_date, result.send_by) == ("2027-01-31", "2027-01-29", "2027-01-25")
    button = compute_contract(stream, ctx(today="2027-01-10"), channel="online_button")
    assert button.send_by == "2027-01-31"  # the button counts when pressed (§ 312k BGB)
    email = compute_contract(stream, ctx(today="2027-01-10"), channel="email")
    assert email.send_by == "2027-01-29"


def test_312k_button_on_sunday() -> None:
    """312k: initial term ends Tue 1 Dec 2026, 1 month → button until Sun 1 Nov; letter by Mon 26 Oct."""
    stream = terms(
        category="streaming",
        concluded_date="2024-12-02",
        end_date="2026-12-01",
        notice_value=1,
        notice_unit="months",
    )
    assert compute_contract(stream, ctx(), channel="online_button").send_by == "2026-11-01"
    letter = compute_contract(stream, ctx())
    assert (letter.cancel_by, letter.safe_date, letter.send_by) == ("2026-11-01", "2026-10-30", "2026-10-26")


def test_309_new_invalid_clauses_are_capped_and_flagged() -> None:
    """309new: concluded 2023-05-10, 12 months, renews by 12 unless cancelled 3 months before."""
    contract = terms(
        category="streaming",
        concluded_date="2023-05-10",
        start_date="2023-05-10",
        initial_term_months=12,
        renewal_term_months=12,
        notice_value=3,
        notice_unit="months",
    )
    result = compute_contract(contract, ctx())
    assert result.cancel_by is None  # indefinite, one month's notice any day
    assert result.earliest_exit == "2026-11-01"
    assert any("only continues indefinitely" in w for w in result.warnings)
    assert any("at most one month" in w for w in result.warnings)
    in_term = compute_contract(contract, ctx(today="2023-06-01"))
    assert in_term.cancel_by == "2024-04-09"  # one month, not the contract's three
    assert any("avoids any argument" in w for w in in_term.warnings)


def test_309_new_long_first_term_and_missing_notice() -> None:
    result = compute_contract(
        terms(category="gym", concluded_date="2025-06-01", start_date="2025-06-01", initial_term_months=36),
        ctx(),
    )
    assert result.current_term_end == "2027-05-31"  # capped at 24 months
    assert result.cancel_by == "2027-04-30"  # longest allowed notice: one month
    assert result.confidence == "low"


def test_309_new_needs_start_for_minimum_term() -> None:
    result = compute_contract(
        terms(category="gym", concluded_date="2025-06-01", initial_term_months=12), ctx(today="2026-01-10")
    )
    assert result.current_term_end == "2026-05-31"  # the conclusion date stands in for the start
    assert result.cancel_by == "2026-04-30"
    no_dates = compute_contract(terms(category="mobile", initial_term_months=24), ctx())
    assert no_dates.cancel_by is None and no_dates.earliest_exit is None
    assert no_dates.confidence == "low"
    assert no_dates.summary.startswith("We couldn't compute a cancellation date")


def test_tkg56_after_minimum_term() -> None:
    """tkg56: concluded Thu 10 Oct 2024, 24 months; today Fri 25 Sep 2026 → ends Sun 25 Oct 2026."""
    result = compute_contract(
        terms(
            category="mobile",
            concluded_date="2024-10-10",
            start_date="2024-10-10",
            initial_term_months=24,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
        channel="online_button",
    )
    assert result.current_term_end == "2026-10-09"
    assert result.cancel_by is None
    assert result.earliest_exit == "2026-10-25"
    assert "notice_no_shift" in result.rule_ids
    # tkg56 verdict: a provider may count the month only after the minimum term → Tue 10 Nov 2026.
    assert any("Tue 10 Nov 2026" in w for w in result.warnings)
    assert result.confidence == "high"


def test_open_notice_never_ends_inside_the_minimum_term() -> None:
    """tkg56 verdict: old contract with 3 months' notice before the end of the minimum term; notice
    arriving just after that deadline must not end the contract inside the minimum term."""
    result = compute_contract(
        terms(
            category="internet",
            concluded_date="2021-01-15",
            start_date="2021-01-15",
            initial_term_months=24,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(today="2022-10-20"),
        channel="online_button",
    )
    assert result.current_term_end == "2023-01-14"
    assert result.earliest_exit == "2023-02-15"  # one month after the minimum term, not 20 Nov 2022
    assert result.confidence == "medium"


@pytest.mark.parametrize(("today", "exit_day"), [("2026-10-05", "2026-11-05"), ("2026-10-03", "2026-11-05")])
def test_tkg56_old_dsl_contract(today: str, exit_day: str) -> None:
    """309old/tkg56: DSL from 2019-03-15 with yearly renewals → one month from receipt (e-mail on a
    Saturday holiday counts from Monday)."""
    result = compute_contract(
        terms(
            category="internet",
            concluded_date="2019-03-15",
            start_date="2019-03-15",
            initial_term_months=24,
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(today=today),
        channel="email",
    )
    assert result.earliest_exit == exit_day


def test_tkg56_old_contract_initial_notice_cap_is_three_months() -> None:
    result = compute_contract(
        terms(
            category="internet",
            concluded_date="2021-01-15",
            start_date="2021-01-15",
            initial_term_months=24,
            notice_value=4,
            notice_unit="months",
        ),
        ctx(today="2022-06-01"),
    )
    assert result.cancel_by == "2022-10-14"


def test_open_contract_button_on_holiday() -> None:
    """309new: open-ended phase, button pressed Sat 3 Oct 2026 → ends Tue 3 Nov 2026."""
    result = compute_contract(
        terms(
            category="streaming",
            concluded_date="2023-01-01",
            start_date="2023-01-01",
            initial_term_months=12,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(today="2026-10-03"),
        channel="online_button",
    )
    assert result.earliest_exit == "2026-11-03"


@pytest.mark.parametrize(
    ("today", "cancel_by", "exit_day", "renewal"),
    [
        pytest.param("2026-09-25", "2026-09-30", "2026-12-31", "2027-01-01", id="309old-magazine"),
        pytest.param("2026-10-01", "2027-09-30", "2027-12-31", "2027-01-01", id="309old-missed-next-year"),
    ],
)
def test_309_old_yearly_renewal(today: str, cancel_by: str, exit_day: str, renewal: str) -> None:
    result = compute_contract(
        terms(
            category="streaming",
            concluded_date="2021-01-01",
            start_date="2021-01-01",
            initial_term_months=12,
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(today=today),
    )
    assert result.regime == "bgb309_old"
    assert (result.cancel_by, result.earliest_exit, result.next_renewal) == (cancel_by, exit_day, renewal)


def test_309_old_gym_sunday_deadline() -> None:
    """309old: gym 2021-06-01, 24 months, +12, 3 months → Sun 28 Feb 2027, safe Fri 26 Feb, post Mon 22 Feb."""
    result = compute_contract(
        terms(
            category="gym",
            concluded_date="2021-06-01",
            start_date="2021-06-01",
            initial_term_months=24,
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(),
    )
    assert result.current_term_end == "2027-05-31"
    assert (result.cancel_by, result.safe_date, result.send_by) == ("2027-02-28", "2027-02-26", "2027-02-22")


def test_309_old_caps_and_bases() -> None:
    long_renewal = compute_contract(
        terms(
            category="gym",
            concluded_date="2020-09-01",
            start_date="2020-09-01",
            initial_term_months=24,
            renewal_term_months=24,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(),
    )
    assert long_renewal.current_term_end == "2027-08-31"  # yearly terms from 2022-08-31, not 24 months
    assert long_renewal.confidence == "medium"
    no_renewal = compute_contract(
        terms(
            category="gym",
            concluded_date="2020-09-01",
            start_date="2020-09-01",
            initial_term_months=24,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(),
    )
    assert no_renewal.current_term_end == "2027-08-31"
    any_time = compute_contract(
        terms(
            category="gym",
            concluded_date="2020-09-01",
            notice_value=2,
            notice_unit="weeks",
            notice_basis="any_time",
        ),
        ctx(),
    )
    assert any_time.earliest_exit == "2026-10-15"
    month_end = compute_contract(
        terms(
            category="gym",
            concluded_date="2020-09-01",
            notice_value=1,
            notice_unit="months",
            notice_basis="end_of_month",
        ),
        ctx(),
    )
    assert (month_end.cancel_by, month_end.earliest_exit) == ("2026-09-30", "2026-10-31")
    no_term = compute_contract(
        terms(category="gym", concluded_date="2020-09-01", notice_value=1, notice_unit="months"), ctx()
    )
    assert no_term.cancel_by is None and no_term.confidence == "low"


def test_as_written_contracts() -> None:
    written = terms(
        category="bank",
        start_date="2025-01-01",
        initial_term_months=12,
        renewal_term_months=6,
        notice_value=2,
        notice_unit="months",
    )
    result = compute_contract(written, ctx())
    assert result.regime == "as_written"
    assert result.current_term_end == "2026-12-31"
    assert result.cancel_by == "2026-10-31"
    assert result.confidence == "low"
    no_notice = compute_contract(
        terms(category="bank", start_date="2025-01-01", initial_term_months=12), ctx()
    )
    assert no_notice.cancel_by is None
    open_missing = compute_contract(terms(category="bank", notice_basis="any_time"), ctx())
    assert open_missing.earliest_exit is None
    any_time = compute_contract(
        terms(category="bank", notice_value=1, notice_unit="months", notice_basis="any_time"), ctx()
    )
    assert any_time.earliest_exit == "2026-11-01"
    unknown_renewal = compute_contract(
        terms(
            category="bank",
            start_date="2025-12-01",
            initial_term_months=12,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
    )
    assert unknown_renewal.cancel_by == "2026-10-31"
    assert any("how the contract continues" in w for w in unknown_renewal.warnings)
    missed_unknown = compute_contract(
        terms(
            category="bank",
            start_date="2025-10-01",
            initial_term_months=12,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
    )
    assert missed_unknown.cancel_by is None


def test_status_cancelled_and_ended() -> None:
    cancelled = compute_contract(terms(category="gym", status="cancelled", end_date="2026-10-31"), ctx())
    assert cancelled.cancel_by is None
    assert cancelled.earliest_exit == "2026-10-31"
    assert cancelled.summary == "This contract is cancelled and ends on Sat 31 Oct 2026."
    ended = compute_contract(terms(category="gym", status="ended", end_date="2026-08-31"), ctx())
    assert ended.summary == "This contract ended on Mon 31 Aug 2026."
    unknown = compute_contract(terms(category="gym", status="cancelled"), ctx())
    assert unknown.earliest_exit is None and unknown.confidence == "low"


def test_fixed_end_without_renewal_ends_by_itself() -> None:
    result = compute_contract(
        terms(category="streaming", concluded_date="2025-01-01", end_date="2026-12-31"), ctx()
    )
    assert result.cancel_by is None
    assert result.earliest_exit == "2026-12-31"


def test_late_send_by_is_today_with_warning() -> None:
    result = compute_contract(
        terms(
            category="streaming",
            concluded_date="2024-11-01",
            end_date="2026-10-31",
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
    )
    assert result.cancel_by == "2026-09-30"
    assert result.send_by == "2026-09-25"
    assert any("usual sending time has passed" in w for w in result.warnings)


def test_non_positive_numbers_are_treated_as_missing() -> None:
    result = compute_contract(
        terms(
            category="gym",
            concluded_date="2025-01-02",
            start_date="2025-01-15",
            initial_term_months=0,
            renewal_term_months=-1,
            notice_value=0,
            notice_unit="months",
        ),
        ctx(),
    )
    assert result.cancel_by is None
    assert result.earliest_exit == "2026-11-01"  # no minimum term; longest allowed notice (one month)
    assert result.confidence == "medium"


def test_foreign_contract_is_low_confidence() -> None:
    result = compute_contract(terms(category="gym", concluded_date="2025-01-01"), ctx(country="AT"))
    assert result.confidence == "low"


# ------------------------------------------------------------------------------ price increases


def test_energy_price_increase() -> None:
    """enwg41: letter received Thu 22 Oct, increase Tue 1 Dec 2026 → cancel by Mon 30 Nov 2026."""
    receipt = price_increase_window(D("2026-12-01"), "energy", D("2026-10-22"), ctx())
    assert receipt.due_date == "2026-11-30"
    assert receipt.send_by == "2026-11-24"
    assert receipt.confidence == "high"
    assert receipt.warnings == []
    assert "enwg_41_5" in receipt.rule_ids


def test_energy_price_increase_holidays_and_late_notice() -> None:
    """enwg41: gas increase Fri 1 Jan 2027 → cancel by Thu 31 Dec, post Thu 24 Dec; late notice flagged."""
    receipt = price_increase_window(D("2027-01-01"), "gas", D("2026-11-20"), ctx())
    assert (receipt.due_date, receipt.send_by) == ("2026-12-31", "2026-12-24")
    late = price_increase_window(D("2026-12-01"), "energy", D("2026-11-10"), ctx())
    assert late.due_date == "2026-11-30"
    assert any("less than a month ahead" in w for w in late.warnings)


def test_basic_supply_price_change() -> None:
    """gv (verdict): increase Fri 1 Jan 2027 → cancel by Thu 31 Dec 2026; announce by Thu 19 Nov (not 20 Nov)."""
    ok = price_increase_window(D("2027-01-01"), "energy", D("2026-11-19"), ctx(), is_basic_supply=True)
    assert ok.due_date == "2026-12-31"
    assert ok.warnings == []
    borderline = price_increase_window(
        D("2027-01-01"), "energy", D("2026-11-20"), ctx(), is_basic_supply=True
    )
    assert any("only just six weeks" in w and "Thu 19 Nov 2026" in w for w in borderline.warnings)
    late = price_increase_window(D("2027-01-15"), "energy", D("2026-12-20"), ctx(), is_basic_supply=True)
    assert late.confidence == "medium"
    assert any("six weeks" in w for w in late.warnings)


@pytest.mark.parametrize(
    ("told", "due", "safe", "timely"),
    [
        pytest.param("2026-10-15", "2027-01-15", "2027-01-15", True, id="tkg57-compliant"),
        pytest.param("2026-10-10", "2027-01-10", "2027-01-08", True, id="tkg57-sunday-window-end"),
        pytest.param("2026-11-16", "2026-11-30", "2026-11-30", False, id="tkg57-too-late"),
        pytest.param("2026-08-15", "2026-11-30", "2026-11-30", False, id="tkg57-too-early"),
    ],
)
def test_telecom_price_increase(told: str, due: str, safe: str, timely: bool) -> None:
    receipt = price_increase_window(D("2026-12-01"), "mobile", D(told), ctx())
    assert receipt.due_date == due
    assert receipt.safe_date == safe
    assert (receipt.confidence == "high") is timely


def test_telecom_price_increase_uses_letter_date_when_receipt_unknown() -> None:
    receipt = price_increase_window(D("2026-12-01"), "internet", None, ctx(document_date=D("2026-10-15")))
    assert receipt.due_date == "2027-01-15"
    assert receipt.confidence == "medium"
    unknown = price_increase_window(D("2026-12-01"), "internet", None, ctx())
    assert unknown.due_date == "2026-11-30"
    assert unknown.confidence == "low"


def test_insurance_premium_increase() -> None:
    receipt = price_increase_window(D("2027-01-01"), "insurance", D("2026-11-20"), ctx())
    assert receipt.due_date == "2026-12-20"
    assert receipt.safe_date == "2026-12-18"
    assert "vvg_40" in receipt.rule_ids
    late = price_increase_window(D("2027-01-01"), "insurance", D("2026-12-10"), ctx())
    assert any("less than a month" in w for w in late.warnings)
    unknown = price_increase_window(D("2027-01-01"), "insurance", None, ctx())
    assert unknown.due_date is None and unknown.confidence == "low"


def test_health_insurance_contribution_increase() -> None:
    receipt = price_increase_window(D("2027-01-01"), "insurance", None, ctx(), party_kind="health_insurer")
    assert receipt.due_date == "2027-01-31"
    assert "sgbv_175_4_zb" in receipt.rule_ids


def test_no_special_right_for_other_contracts() -> None:
    receipt = price_increase_window(D("2027-01-01"), "gym", D("2026-11-20"), ctx())
    assert receipt.due_date is None
    assert receipt.confidence == "low"


def test_price_window_already_closed() -> None:
    receipt = price_increase_window(D("2026-09-01"), "energy", D("2026-07-15"), ctx())
    assert receipt.due_date == "2026-08-31"
    assert receipt.send_by is None
    assert any("already passed" in w for w in receipt.warnings)


# ---------------------------------------------------------------------------------- send guidance


def test_send_guidance_rent_needs_signature() -> None:
    guidance = send_guidance(
        "cancellation", contract_category="rent", due=D("2026-10-05"), today=TODAY, region="NW"
    )
    assert guidance.form == "written_form"
    allowed = {c.channel for c in guidance.channels if c.allowed}
    assert allowed == {"registered_letter", "in_person", "letter"}
    assert guidance.must_arrive_by == "2026-10-05"
    assert guidance.send_by == "2026-09-29"  # 568: post by Tue 29 Sep
    assert [c.channel for c in guidance.channels if c.recommended] == ["registered_letter"]


def test_send_guidance_employment() -> None:
    guidance = send_guidance("cancellation", contract_category="employment", today=TODAY)
    assert guidance.form == "written_form"
    assert "§ 623 BGB" in (guidance.form_note or "")
    assert guidance.send_by is None and guidance.must_arrive_by is None


def test_send_guidance_consumer_contract() -> None:
    guidance = send_guidance("cancellation", contract_category="streaming", due=D("2026-11-01"), today=TODAY)
    assert guidance.form == "text_form"
    assert guidance.channels[0].channel == "online_button" and guidance.channels[0].recommended
    assert guidance.send_by == "2026-10-26"  # 312k: letter by Mon 26 Oct
    assert any("not a working day" in t for t in guidance.tips)


def test_send_guidance_insurance_has_no_mandatory_button() -> None:
    guidance = send_guidance("cancellation", contract_category="insurance", party_kind="insurer", today=TODAY)
    button = guidance.channels[0]
    assert button.channel == "online_button" and not button.recommended
    assert [c.channel for c in guidance.channels if c.recommended] == ["registered_letter"]


def test_send_guidance_health_insurer_switch() -> None:
    guidance = send_guidance(
        "cancellation", contract_category="insurance", party_kind="health_insurer", today=TODAY
    )
    assert guidance.channels[0].channel == "portal"
    assert "§ 175" in (guidance.form_note or "")


def test_send_guidance_tax_objection() -> None:
    guidance = send_guidance(
        "objection", party_kind="tax_office", due=D("2026-10-21"), today=TODAY, region="NW"
    )
    assert guidance.form == "text_form"
    assert guidance.channels[0].channel == "portal" and guidance.channels[0].recommended
    assert all(c.allowed for c in guidance.channels)
    assert guidance.send_by == "2026-10-15"


@pytest.mark.parametrize(
    ("party_kind", "citation"), [("immigration_office", "VwGO"), ("health_insurer", "SGG"), (None, "VwGO")]
)
def test_send_guidance_other_objections_reject_plain_email(party_kind: str | None, citation: str) -> None:
    guidance = send_guidance("objection", party_kind=party_kind, today=TODAY)
    email = next(c for c in guidance.channels if c.channel == "email")
    assert not email.allowed
    assert guidance.form == "written_form"
    assert citation in (guidance.form_note or "")


def test_send_guidance_general_reply_and_past_due() -> None:
    guidance = send_guidance("general_reply", due=D("2026-09-01"), today=TODAY)
    assert guidance.form == "any"
    assert guidance.send_by is None
    assert guidance.must_arrive_by == "2026-09-01"
    assert guidance.tips[0].startswith("The deadline (Tue 1 Sep 2026) has passed")
    soon = send_guidance("general_reply", due=D("2026-09-28"), today=TODAY)
    assert soon.send_by == "2026-09-25"


# -------------------------------------------------------------------------------------- catalog


def test_catalog_entries_are_complete() -> None:
    assert catalog.LAST_CHECKED == "2026-09-25"
    rules = catalog.list_rules()
    assert len(rules) == len(catalog.RULES)
    for rule in rules:
        assert rule.title and rule.citation and rule.summary
        assert rule.url is None or rule.url.startswith("https://")
        if rule.effective_from:
            date.fromisoformat(rule.effective_from)
    assert catalog.get_rule("bgb_193").citation == "§ 193 BGB"
    with pytest.raises(KeyError):
        catalog.get_rule("nope")


def test_rule_maps_only_use_catalog_ids() -> None:
    """Rule ids are validated when used (Trace.use, catalog.citation); the static maps are checked here."""
    from ordnung.rules import contracts, deadlines, delivery

    ids = {*contracts._REGIME_RULE.values(), *deadlines._SHIFT_RULE_BY_SCOPE.values()}
    ids |= {*delivery._RULE_BY_SCOPE_CHANNEL.values(), *(rule for _, rule, _ in deadlines._STATUTES)}
    assert ids <= set(catalog.RULES)
    trace = deadlines.Trace()
    with pytest.raises(KeyError):
        trace.use("no_such_rule")


def test_docs_mention_every_rule_and_the_check_date() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs" / "deadline-rules.md"
    text = docs.read_text(encoding="utf-8")
    assert [rule for rule in catalog.RULES if f"`{rule}`" not in text] == []
    assert "25 September 2026" in text and catalog.LAST_CHECKED == "2026-09-25"


def test_missing_conclusion_date_uses_start_date() -> None:
    result = compute_contract(
        terms(
            category="mobile",
            start_date="2024-11-15",
            initial_term_months=24,
            notice_value=1,
            notice_unit="months",
        ),
        ctx(),
    )
    assert result.cancel_by == "2026-10-14"
    assert result.confidence == "medium"
    assert any("contract date is missing" in w for w in result.warnings)


def test_renewing_contract_with_known_term_end() -> None:
    result = compute_contract(
        terms(
            category="streaming",
            concluded_date="2021-01-01",
            end_date="2026-12-31",
            renewal_term_months=12,
            notice_value=3,
            notice_unit="months",
        ),
        ctx(),
    )
    assert (result.current_term_end, result.cancel_by) == ("2026-12-31", "2026-09-30")
    assert not any(step.rule_id == "bgb_187_2" for step in result.steps)


def test_insurance_without_notice_assumes_three_months() -> None:
    result = compute_contract(
        terms(category="insurance", start_date="2024-01-01", initial_term_months=12, renewal_term_months=12),
        ctx(),
    )
    assert result.cancel_by == "2026-09-30"
    assert result.confidence == "medium"
    assert any("notice period wasn't found" in w for w in result.warnings)


def test_late_rent_notice_suggests_hand_delivery() -> None:
    """568 verdict: once posting is too late, only personal or messenger delivery can still work."""
    result = compute_contract(terms(category="rent"), ctx(today="2026-10-02"))
    assert result.cancel_by == "2026-10-05"
    assert result.send_by == "2026-10-02"
    assert any("in person (with a witness) or by messenger" in w for w in result.warnings)


def test_energy_special_contract_mentions_section_310() -> None:
    result = compute_contract(
        terms(category="energy", concluded_date="2024-01-01", notice_value=1, notice_unit="months"), ctx()
    )
    assert any("§ 310 Abs. 2 BGB" in n for n in result.notes)


def test_a_contract_notice_counted_back_over_a_partial_holiday_is_named() -> None:
    """A gym contract in Bavaria: the letter must be posted by Fri 11 Aug 2028 to arrive by Thu 17 Aug, but
    where Tue 15 Aug is a holiday (Munich) the post needs a working day more. A price-increase window on
    that day itself never moves: its safe date is a working day earlier there."""
    gym = terms(
        category="gym",
        party_kind="gym",
        concluded_date="2027-09-10",
        start_date="2027-09-18",
        initial_term_months=12,
        notice_value=1,
        notice_unit="months",
        notice_basis="end_of_term",
    )
    result = compute_contract(gym, ctx(today="2028-08-01", region="BY"))
    assert (result.cancel_by, result.send_by, result.confidence) == ("2028-08-17", "2028-08-11", "high")
    assert [w for w in result.warnings if "Mariä Himmelfahrt" in w] == [
        "Tue 15 Aug 2028 is Mariä Himmelfahrt, a public holiday only in the communities of Bayern with more "
        "Catholic than Protestant residents (as the Landesamt für Statistik lists them; Munich among them), "
        "which is not counted here. Where it holds, the send-by or safe date, counted back over it, is a "
        "working day earlier: act a working day before it to be safe."
    ]
    assert compute_contract(gym, ctx(today="2028-08-01", region="HH")).warnings == []
    window = price_increase_window(
        D("2025-08-16"), "energy", D("2025-07-01"), ctx(today="2025-07-10", region="BY")
    )
    assert (window.due_date, window.safe_date) == ("2025-08-15", "2025-08-15")
    assert any(
        "this deadline does not move off it, so the safe date is a working day earlier" in w
        for w in window.warnings
    )
