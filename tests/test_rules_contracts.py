"""Contracts, price-increase windows, send guidance and the rules catalog.

Research rules cited in ids: ``309new``/``309old`` = bgb_309_nr9_*, ``no193`` =
kuendigung_no_193_zugang_deadline_and_send_by, ``arith`` = kuendigungsfrist_period_arithmetic_187_188,
``tkg56``, ``tkg57``, ``enwg41`` = enwg_41_5_energy_price_change_special_cancellation, ``gv`` =
grundversorgung_stromgvv_gasgvv_cancellation, ``573c`` = bgb_573c_residential_lease_notice_third_werktag,
``568`` = bgb_568_lease_termination_written_form, ``309n13`` = bgb_309_nr13_textform, ``312k``.
"""

from __future__ import annotations

import json
import re
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
from ordnung.rules.explain import ordinal
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
    # never "ended": a job the person still works in may continue with no fixed term (§ 15 Abs. 6 TzBfG)
    assert past.summary.startswith("This job's fixed-term end date, Tue 31 Mar 2026, has passed.")
    assert "§ 15 Abs. 6 TzBfG" in past.summary
    gym = compute_contract(terms(category="gym", end_date="2026-03-31"), ctx())
    assert gym.summary == "This contract ended on Tue 31 Mar 2026."


def test_a_fixed_term_flat_let_may_still_need_notice() -> None:
    """Release blocker (ADR 0008), resolved in review round 1: a flat let's fixed term needs a written legal
    reason, or the lease counts as open-ended (§ 575 Abs. 1 S. 2 BGB) — never "ends by itself, no
    cancellation needed" — and one used on after its end may continue (§ 545 BGB): never "ended"."""
    lease = compute_contract(terms(category="rent", start_date="2025-04-01", end_date="2027-03-31"), ctx())
    assert lease.regime == "rent573c" and "fixed_term" in lease.rule_ids
    assert "no cancellation needed" not in lease.summary and "§ 575 Abs. 1 BGB" in lease.summary
    assert lease.summary.startswith("This lease's fixed term ends on Wed 31 Mar 2027.")
    past = compute_contract(terms(category="rent", end_date="2026-03-31"), ctx())
    assert "ended on" not in past.summary and "§ 545 BGB" in past.summary
    rule = catalog.get_rule("fixed_term")
    assert "end by themselves" not in rule.title and "§ 575" in rule.summary


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


# ------------------------------------------------------ terms a notice period can't say (migration 0004)

SAM_TODAY = "2026-09-28"
#: The Deutschlandticket as its letter states it: "Die Kündigung muss bis zum 10. eines Monats zum Ende
#: dieses Monats bei uns eingehen" — no notice period, the 10th of the month (scripts/samplelife).
DEUTSCHLANDTICKET = {
    "category": "transport",
    "concluded_date": "2025-12-10",
    "start_date": "2026-01-01",
    "initial_term_months": 1,
    "notice_basis": "end_of_month",
    "notice_day": 10,
}
#: The working-student job: fixed until 31 Mar 2027, and "Nach Ablauf der Probezeit kann das
#: Arbeitsverhältnis … unter Einhaltung der gesetzlichen Kündigungsfristen (§ 622 BGB) ordentlich gekündigt
#: werden" — ordinary notice before the end, with no period of its own.
WERKSTUDENT = {
    "category": "employment",
    "is_consumer": False,
    "concluded_date": "2026-03-20",
    "start_date": "2026-04-01",
    "initial_term_months": 12,
    "end_date": "2027-03-31",
    "notice_before_end": True,
}


def test_ordinal() -> None:
    assert [ordinal(day) for day in (1, 2, 3, 4, 10, 11, 12, 13, 21, 22, 23, 30, 31)] == [
        "1st", "2nd", "3rd", "4th", "10th", "11th", "12th", "13th", "21st", "22nd", "23rd", "30th", "31st",
    ]  # fmt: skip


def test_deutschlandticket_by_the_10th_to_the_end_of_that_month() -> None:
    """Demo (Sam, Mon 28 Sep 2026, NW): September's 10th has passed, so the next deadline is Sat 10 Oct for
    Sat 31 Oct; a notice deadline never moves off the weekend (safe date Fri 9 Oct), post it by Mon 5 Oct."""
    result = compute_contract(terms(**DEUTSCHLANDTICKET), ctx(today=SAM_TODAY))
    assert result.regime == "bgb309_new"
    assert (result.cancel_by, result.safe_date, result.send_by, result.earliest_exit) == (
        "2026-10-10",
        "2026-10-09",
        "2026-10-05",
        "2026-10-31",
    )
    assert result.current_term_end is None and result.next_renewal is None  # nothing locks you in
    assert result.summary == (
        "To leave on Sat 31 Oct 2026, your notice must arrive by Sat 10 Oct 2026 (the 10th of the month, as "
        "the contract says); send it by Mon 5 Oct."
    )
    step = (
        "To end the contract on Sat 31 Oct 2026 with notice by the 10th of the month, it must arrive by Sat 10 "
        "Oct 2026"
    )
    assert step in [s.label for s in result.steps]
    assert "contract_as_written" in result.rule_ids and "bgb_188" not in result.rule_ids
    # no notice period assumed, so the card asks no "Please check"
    assert not any("notice period wasn't found" in w for w in result.warnings)
    assert result.confidence == "high"
    # a letter posted now arrives Fri 2 Oct: one month from then (Mon 2 Nov) is no sooner — no warning
    assert not any("may let a cancellation" in w for w in result.warnings)


def test_a_missed_10th_moves_to_the_next_month_and_names_the_month_from_arrival() -> None:
    """After the 10th: the 10th of next month for its end. After a fixed first term the law may let a
    cancellation end the contract one month after it arrives (§ 309 Nr. 9 BGB) — sooner here, so a hedged
    warning names it; the dates keep the contract's own rule."""
    result = compute_contract(terms(**DEUTSCHLANDTICKET), ctx(today="2026-10-11"))
    assert (result.cancel_by, result.earliest_exit) == ("2026-11-10", "2026-11-30")
    assert (
        "If the contract continued after a fixed first term, the law may let a cancellation that arrives by Thu "
        "15 Oct 2026 end it one month later, on Sun 15 Nov 2026 (§ 309 Nr. 9 BGB; Art. 229 § 60 EGBGB); the "
        "contract's date avoids any argument."
    ) in result.warnings
    assert result.confidence == "high"
    phone = {
        "category": "mobile",
        "concluded_date": "2019-01-01",
        "notice_basis": "end_of_month",
        "notice_day": 10,
    }
    button = compute_contract(terms(**phone), ctx(today="2026-10-11"), channel="online_button")
    assert (button.cancel_by, button.earliest_exit) == ("2026-11-10", "2026-11-30")
    assert any("on Wed 11 Nov 2026 (§ 56 Abs. 1, 3 TKG)" in w for w in button.warnings)


@pytest.mark.parametrize(
    ("day", "today", "cancel_by", "exit_day"),
    [
        (30, "2027-02-01", "2027-02-28", "2027-02-28"),  # a shorter month: its last day
        (31, "2026-09-28", "2026-09-30", "2026-09-30"),
        (1, "2026-09-28", "2026-10-01", "2026-10-31"),
    ],
)
def test_the_day_is_a_shorter_months_last_day(day: int, today: str, cancel_by: str, exit_day: str) -> None:
    result = compute_contract(terms(**{**DEUTSCHLANDTICKET, "notice_day": day}), ctx(today=today))
    assert (result.cancel_by, result.earliest_exit) == (cancel_by, exit_day)


def test_a_notice_period_stated_with_the_day_applies_too() -> None:
    """Review of migration 0004: prompt 9 read this letter's "bis zum 10." as 10 days' notice. Read with the
    day as well, a stated period that won over it gave "cancel any time with 10 days' notice … ends on Mon 12
    Oct" — no deadline, 19 days before the true one. Both apply now, the earlier deadline decides; another
    basis ignores the day."""
    misread = compute_contract(
        terms(**DEUTSCHLANDTICKET, notice_value=10, notice_unit="days"), ctx(today=SAM_TODAY)
    )
    assert (misread.cancel_by, misread.earliest_exit) == ("2026-10-10", "2026-10-31")
    assert misread.summary.startswith(
        "To leave on Sat 31 Oct 2026, your notice must arrive by Sat 10 Oct 2026 (10 days' notice by the 10th of "
        "the month, as the contract says)"
    )
    month = compute_contract(
        terms(**DEUTSCHLANDTICKET, notice_value=1, notice_unit="months"), ctx(today=SAM_TODAY)
    )
    assert (month.cancel_by, month.earliest_exit) == ("2026-09-30", "2026-10-31")  # the month's the earlier
    assert (
        "To end the contract on Sat 31 Oct 2026 with one month's notice by the 10th of the month, it must arrive "
        "by Wed 30 Sep 2026"
    ) in [s.label for s in month.steps]
    # capped as a period alone would be (§ 309 Nr. 9 BGB: at most one month), with the day still applying
    long = compute_contract(
        terms(**DEUTSCHLANDTICKET, notice_value=3, notice_unit="months"), ctx(today=SAM_TODAY)
    )
    assert (long.cancel_by, long.earliest_exit) == ("2026-09-30", "2026-10-31")
    assert any(w.startswith("Your contract asks for three months' notice") for w in long.warnings)
    any_time = compute_contract(
        terms(**{**DEUTSCHLANDTICKET, "notice_basis": "any_time"}), ctx(today=SAM_TODAY)
    )
    assert any_time.cancel_by is None and any(
        w.startswith("The contract's notice period wasn't found") for w in any_time.warnings
    )


def test_a_first_term_is_left_by_the_day_of_its_last_month() -> None:
    """A first term still running: the day of the month it ends in (or of the month before, when the term ends
    first); once that has passed, the next month end whose day is ahead — never inside the first term."""
    gym = {
        "category": "gym",
        "concluded_date": "2026-01-15",
        "start_date": "2026-02-01",
        "initial_term_months": 12,
    }
    day = {"notice_basis": "end_of_month", "notice_day": 10}
    running = compute_contract(terms(**gym, **day), ctx(today=SAM_TODAY))
    assert (running.cancel_by, running.earliest_exit, running.current_term_end, running.next_renewal) == (
        "2027-01-10",
        "2027-01-31",
        "2027-01-31",
        "2027-02-01",
    )
    assert running.summary.endswith("otherwise it continues.")
    missed = compute_contract(terms(**gym, **day), ctx(today="2027-01-20"))
    assert "The deadline to leave when the first term ends was Sun 10 Jan 2027" in [
        s.label for s in missed.steps
    ]
    assert (missed.cancel_by, missed.earliest_exit) == ("2027-02-10", "2027-02-28")
    mid_month = compute_contract(terms(**{**gym, "start_date": "2026-02-06"}, **day), ctx(today=SAM_TODAY))
    assert (mid_month.cancel_by, mid_month.earliest_exit) == ("2027-01-10", "2027-02-05")


def test_an_end_date_with_the_day_needs_notice() -> None:
    """Review of migration 0004: a minimum term's end read as the end date, with the day as the only notice
    term, was "ends by itself — no cancellation needed" while the contract runs on. The day needs notice, as a
    notice period does."""
    gym = {
        "category": "gym",
        "concluded_date": "2026-01-15",
        "start_date": "2026-02-01",
        "end_date": "2027-01-31",
    }
    result = compute_contract(terms(**gym, notice_basis="end_of_month", notice_day=10), ctx(today=SAM_TODAY))
    assert (result.cancel_by, result.earliest_exit, result.next_renewal) == (
        "2027-01-10",
        "2027-01-31",
        "2027-02-01",
    )
    assert "fixed_term" not in result.rule_ids and "no cancellation needed" not in result.summary
    # the day is read only with a month-end basis: another one leaves the end date deciding
    other = compute_contract(terms(**gym, notice_basis="any_time", notice_day=10), ctx(today=SAM_TODAY))
    assert other.summary == "This contract ends by itself on Sun 31 Jan 2027 — no cancellation needed."


def test_the_day_waits_for_a_first_term_that_still_runs() -> None:
    """Review of migration 0004: under the contract's own terms (here a business contract), "by the 10th of a
    month, to its end" gave an exit inside a 24-month first term. The first term is left by the day of its last
    month; once that has passed, the month ends after it."""
    business = {
        "category": "internet",
        "is_consumer": False,
        "start_date": "2026-01-01",
        "initial_term_months": 24,
        "renewal_term_months": 12,
        "notice_basis": "end_of_month",
        "notice_day": 10,
    }
    running = compute_contract(terms(**business), ctx(today=SAM_TODAY))
    assert running.regime == "as_written"
    assert (running.cancel_by, running.earliest_exit, running.next_renewal) == (
        "2027-12-10",
        "2027-12-31",
        "2028-01-01",
    )
    missed = compute_contract(terms(**business), ctx(today="2027-12-15"))
    assert "The deadline to leave when the first term ends was Fri 10 Dec 2027" in [
        s.label for s in missed.steps
    ]
    assert (missed.cancel_by, missed.earliest_exit) == ("2028-01-10", "2028-01-31")


@pytest.mark.parametrize(
    "kw",
    [
        {"category": "gym", "concluded_date": "2021-06-01", "start_date": "2021-06-01"},  # bgb309_old
        {"category": "streaming"},  # as_written
    ],
)
def test_renewing_contracts_read_the_day_too(kw: dict[str, Any]) -> None:
    result = compute_contract(terms(**kw, notice_basis="end_of_month", notice_day=15), ctx(today=SAM_TODAY))
    assert (result.cancel_by, result.earliest_exit) == ("2026-10-15", "2026-10-31")
    assert result.summary.startswith(
        "To leave on Sat 31 Oct 2026, your notice must arrive by Thu 15 Oct 2026"
    )
    # with a notice period too, both apply (the old consumer rule caps it at three months)
    short = compute_contract(
        terms(**kw, notice_basis="end_of_month", notice_day=15, notice_value=2, notice_unit="weeks"),
        ctx(today=SAM_TODAY),
    )
    assert (short.cancel_by, short.earliest_exit) == ("2026-10-15", "2026-10-31")
    long = compute_contract(
        terms(**kw, notice_basis="end_of_month", notice_day=15, notice_value=4, notice_unit="months"),
        ctx(today=SAM_TODAY),
    )
    capped = any(w.startswith("Your contract asks for four months' notice") for w in long.warnings)
    if result.regime == "bgb309_old":
        assert (long.cancel_by, long.earliest_exit, capped) == ("2026-09-30", "2026-12-31", True)
    else:
        assert (long.cancel_by, long.earliest_exit, capped) == ("2026-09-30", "2027-01-31", False)


def test_insurance_ignores_the_day() -> None:
    insurance = {
        "category": "insurance",
        "party_kind": "insurer",
        "start_date": "2023-12-01",
        "notice_value": 3,
    }
    insurance |= {"notice_unit": "months", "notice_basis": "end_of_month"}
    assert compute_contract(terms(**insurance, notice_day=10), ctx()) == compute_contract(
        terms(**insurance), ctx()
    )


def test_an_implausible_day_is_missing() -> None:
    zero = compute_contract(terms(**{**DEUTSCHLANDTICKET, "notice_day": 0}), ctx(today=SAM_TODAY))
    assert zero.cancel_by is None and zero.confidence == "medium"  # the longest the law allows, any day
    assert any(w.startswith("The contract's notice period wasn't found") for w in zero.warnings)
    late = compute_contract(terms(**{**DEUTSCHLANDTICKET, "notice_day": 45}), ctx(today=SAM_TODAY))
    assert (
        "The contract's day of the month for notice (45) can't be right, so we ignored it — please check it."
        in late.warnings
    )
    assert late.confidence == "low"


def test_werkstudent_job_can_be_left_by_notice_before_its_end() -> None:
    """Demo (Sam, Mon 28 Sep 2026, NW): four weeks to the 15th or the end of a month (§ 622 Abs. 1 BGB) —
    Sat 31 Oct, so the notice must arrive by Sat 3 Oct (German Unity Day; kept, safe date Fri 2 Oct), post it
    today; without notice the job ends by itself on Wed 31 Mar 2027."""
    result = compute_contract(terms(**WERKSTUDENT), ctx(today=SAM_TODAY))
    assert result.regime == "employment622"
    assert (result.cancel_by, result.safe_date, result.send_by, result.earliest_exit) == (
        "2026-10-03",
        "2026-10-02",
        "2026-09-28",
        "2026-10-31",
    )
    assert result.current_term_end == "2027-03-31" and result.next_renewal is None  # no decision locks you in
    assert "fixed_term" in result.rule_ids and "bgb_622" in result.rule_ids
    assert result.confidence == "medium"  # the statutory four weeks were assumed
    assert result.summary == (
        "To leave on Sat 31 Oct 2026, your notice must arrive by Sat 3 Oct 2026; send it by Mon 28 Sep. If you "
        "don't give notice, it ends by itself on Wed 31 Mar 2027."
    )
    written = compute_contract(
        terms(**WERKSTUDENT, notice_value=4, notice_unit="weeks", notice_basis="end_of_month"),
        ctx(today=SAM_TODAY),
    )
    assert (written.cancel_by, written.earliest_exit, written.current_term_end) == (
        "2026-10-03",
        "2026-10-31",
        "2027-03-31",
    )
    assert written.confidence == "high"
    assert not any("probation" in w for w in written.warnings)


FLOOR = (
    "Before the fixed term's end we used at least four weeks' notice to the 15th or the end of a month (§ 622 "
    "Abs. 1 BGB): a shorter notice, or notice to any day, is usually the probation period's (§ 622 Abs. 3 BGB), "
    "and after it a contract can rarely agree less (§ 622 Abs. 4, 5 BGB)."
)


def test_a_job_left_before_its_end_gets_at_least_the_statutory_notice() -> None:
    """Review of migration 0004: the working-student contract's probation clause ("mit einer Frist von zwei
    Wochen") is where a model picks up 2 weeks or any day. Planned as read, the job "ends on Fri 16 Oct" with no
    deadline; after probation § 622 Abs. 1 BGB applies (a contract can't shorten it, § 622 Abs. 5 BGB): arrive by
    Sat 3 Oct for Sat 31 Oct."""
    probation = compute_contract(
        terms(**WERKSTUDENT, notice_value=2, notice_unit="weeks", notice_basis="any_time"),
        ctx(today=SAM_TODAY),
    )
    assert (probation.cancel_by, probation.earliest_exit, probation.current_term_end) == (
        "2026-10-03",
        "2026-10-31",
        "2027-03-31",
    )
    assert FLOOR in probation.warnings
    assert probation.summary.endswith("If you don't give notice, it ends by itself on Wed 31 Mar 2027.")
    # any day with the statutory four weeks assumed: still to the 15th or the end of a month
    statutory = compute_contract(terms(**WERKSTUDENT, notice_basis="any_time"), ctx(today="2026-10-05"))
    assert (statutory.cancel_by, statutory.earliest_exit) == ("2026-10-18", "2026-11-15")
    # a longer period stands, to the 15th or the end of a month
    longer = compute_contract(
        terms(**WERKSTUDENT, notice_value=3, notice_unit="months", notice_basis="any_time"),
        ctx(today=SAM_TODAY),
    )
    assert (longer.cancel_by, longer.earliest_exit) == ("2026-09-30", "2026-12-31")
    # an open-ended job keeps its terms as read
    open_ended = {**WERKSTUDENT, "end_date": None, "notice_value": 2, "notice_unit": "weeks"}
    as_read = compute_contract(terms(**open_ended, notice_basis="any_time"), ctx(today=SAM_TODAY))
    assert (as_read.cancel_by, as_read.earliest_exit) == (None, "2026-10-16")


def test_a_job_notice_cant_end_sooner_than_its_end_date() -> None:
    """Near its end, or after it: the fixed term decides (and the clause is not read for a flat let)."""
    near = compute_contract(terms(**WERKSTUDENT), ctx(today="2027-03-10"))
    assert (near.cancel_by, near.earliest_exit, near.current_term_end) == (None, "2027-03-31", "2027-03-31")
    assert near.summary == "This contract ends by itself on Wed 31 Mar 2027 — no cancellation needed."
    # the fixed term alone explains it: no notice's must-arrive-by date, no assumed notice period
    unflagged = compute_contract(
        terms(**{**WERKSTUDENT, "notice_before_end": False}), ctx(today="2027-03-10")
    )
    assert [s.label for s in near.steps] == [
        *[s.label for s in unflagged.steps[:-1]],
        "Fixed term: notice can't end it sooner, so it ends on Wed 31 Mar 2027",
    ]
    assert near.model_copy(update={"steps": unflagged.steps}) == unflagged
    assert "bgb_188" not in near.rule_ids and near.confidence == "high"
    past = compute_contract(terms(**{**WERKSTUDENT, "end_date": "2026-03-31"}), ctx(today=SAM_TODAY))
    without = compute_contract(
        terms(**{**WERKSTUDENT, "end_date": "2026-03-31", "notice_before_end": False}), ctx(today=SAM_TODAY)
    )
    assert past == without and past.summary.startswith(
        "This job's fixed-term end date, Tue 31 Mar 2026, has passed."
    )
    lease = {"category": "rent", "start_date": "2025-04-01", "end_date": "2027-03-31"}
    assert compute_contract(terms(**lease, notice_before_end=True), ctx()) == compute_contract(
        terms(**lease), ctx()
    )


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


def test_a_current_account_can_be_closed_any_time() -> None:
    """Walkthrough of phase 2: "Selbstverständlich können auch Sie Ihr Girokonto jederzeit kostenfrei
    kündigen" (read as notice any time, no period) got "We couldn't compute a cancellation date". A consumer's
    current account can be closed any time without notice unless one was agreed, and an agreed one counts
    for at most a month (§ 675h Abs. 1 BGB)."""
    account = compute_contract(terms(category="bank", notice_basis="any_time"), ctx())
    assert account.regime == "bgb675h"
    assert account.earliest_exit == "2026-10-01"  # the day a letter posted today arrives
    assert account.cancel_by is None and account.next_renewal is None
    assert account.confidence == "high" and account.warnings == []
    assert "bgb_675h" in account.rule_ids
    assert account.summary.startswith("You can cancel any time, without notice (§ 675h Abs. 1 BGB)")
    assert any("§ 675h" in note for note in account.notes)
    agreed = compute_contract(
        terms(category="bank", notice_value=2, notice_unit="weeks", notice_basis="any_time"), ctx()
    )
    assert agreed.regime == "bgb675h" and agreed.earliest_exit == "2026-10-15"
    capped = compute_contract(
        terms(category="bank", notice_value=3, notice_unit="months", notice_basis="any_time"), ctx()
    )
    assert capped.earliest_exit == "2026-11-01"  # three months agreed, one month is the most (void beyond)
    assert any("at most one month" in w for w in capped.warnings)
    # other bank contracts (a savings plan, a loan) follow their own terms
    fixed = compute_contract(terms(category="bank", notice_basis="end_of_term"), ctx())
    assert fixed.regime == "as_written"


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
    # a business's bank contract that can be ended any time follows its terms (a consumer's is § 675h BGB)
    open_missing = compute_contract(terms(category="bank", notice_basis="any_time", is_consumer=False), ctx())
    assert open_missing.earliest_exit is None
    any_time = compute_contract(
        terms(
            category="bank", notice_value=1, notice_unit="months", notice_basis="any_time", is_consumer=False
        ),
        ctx(),
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
    # a special contract: the basic-supply regulation (StromGVV) is not cited (walkthrough of phase 2)
    assert "stromgvv_5_3" not in receipt.rule_ids
    assert all("StromGVV" not in step.citation for step in receipt.steps if step.citation)


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
    assert {"enwg_41_5", "stromgvv_5_3"} <= set(ok.rule_ids)
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


def test_every_rule_is_listed_under_a_topic_in_one_run() -> None:
    """The settings screen groups the rules by topic: every rule has one and each topic is one block."""
    assert set(catalog.TOPIC_STARTS) <= set(catalog.RULES)
    topics = [rule.topic for rule in catalog.list_rules()]
    assert None not in topics
    runs = [topic for i, topic in enumerate(topics) if i == 0 or topic != topics[i - 1]]
    assert runs == list(catalog.TOPIC_STARTS.values())
    assert catalog.get_rule("tkg_57").topic == "Price increases"


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


def test_the_static_demo_shows_the_catalogs_texts_for_the_engines_rule_ids() -> None:
    """Reviewer repro: the static demo's rules list (``web/src/mocks/data/system.ts``) carries entries by
    the engine's ids; their title, citation and summary are the catalog's, word for word — the demo
    once cited § 188 Abs. 1, 2 BGB for the month-end clause of Abs. 3."""
    mocks = Path(__file__).resolve().parents[1] / "web" / "src" / "mocks" / "data" / "system.ts"
    shown = {
        found.group(1): found.group(0)
        for found in re.finditer(
            r'\{ id: "([a-z0-9_]+)", title: .*\},$', mocks.read_text(encoding="utf-8"), re.M
        )
    }
    engine_ids = sorted(set(shown) & set(catalog.RULES))
    assert {"bgb_187_1", "bgb_188", "bgb_193", "private_sender_arrival"} <= set(engine_ids)
    for rule_id in engine_ids:
        rule = catalog.get_rule(rule_id)
        for field in (rule.title, rule.citation, rule.summary):
            assert json.dumps(field, ensure_ascii=False) in shown[rule_id], (rule_id, field)


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
