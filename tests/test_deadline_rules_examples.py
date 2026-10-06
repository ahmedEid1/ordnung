"""Worked examples of docs/deadline-rules.md that no other test pinned (docs audit G11): the document says every
worked example is an executable test, so each row here is computed by the engine exactly as the table shows it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ordnung.models import ContractTerms, DateSpec
from ordnung.rules import RuleContext, compute_due
from ordnung.rules.contracts import compute_contract

DOCS = Path(__file__).resolve().parents[1] / "docs" / "deadline-rules.md"
D = date.fromisoformat


def _row(start: str) -> str:
    """The table row of deadline-rules.md that starts with ``start`` (so a reworded row fails here too)."""
    rows = [line for line in DOCS.read_text(encoding="utf-8").splitlines() if line.startswith(f"| {start}")]
    assert len(rows) == 1, start
    return rows[0]


def test_an_invoice_paid_from_stuttgart_skips_fronleichnam() -> None:
    """Section 2: payable within 7 days of Thu 28 May 2026, payer in Stuttgart (BW): Thu 4 Jun is Fronleichnam
    there, so the payment is due Fri 5 Jun 2026 — the payer's holidays, the company's Land unknown."""
    assert "Thu 4 Jun (Fronleichnam) → Fri 5 Jun 2026" in _row(
        "Invoice payable within 7 days of Thu 28 May 2026"
    )
    invoice = DateSpec(type="relative", anchor="document_date", amount=7, unit="days", nature="payment")
    receipt = compute_due(
        invoice, RuleContext(today=D("2026-05-28"), document_date=D("2026-05-28"), recipient_region="BW")
    )
    assert receipt.due_date == "2026-06-05"
    assert receipt.holiday_calendar == "Baden-Württemberg"


def test_a_payment_order_put_in_the_letterbox_on_a_saturday_counts_from_that_saturday() -> None:
    """Section 7: delivered Sat 19 Dec 2026 (§ 180 ZPO), two weeks end Sat 2 Jan, which moves to Mon 4 Jan 2027
    (§ 222 Abs. 2 ZPO)."""
    assert "Sat 2 Jan → Mon 4 Jan 2027" in _row("Sat 19 Dec 2026 (letterbox)")
    order = DateSpec(type="relative", anchor="receipt", amount=2, unit="weeks", nature="objection")
    receipt = compute_due(
        order,
        RuleContext(
            today=D("2026-12-19"),
            region="NW",
            document_date=D("2026-12-17"),
            received_date=D("2026-12-19"),
            received_confirmed=True,
            letter_kind="court_payment_order",
        ),
    )
    assert receipt.due_date == "2027-01-04"
    assert {"zpo_692", "zpo_180", "zpo_222"} <= set(receipt.rule_ids)


def test_an_old_gym_contract_s_first_term_is_capped_at_24_months() -> None:
    """Section 8: a gym concluded 1 Oct 2021 for 30 months, then yearly, 3 months' notice (today 1 May 2026):
    the old § 309 Nr. 9 BGB caps the first term at 24 months (30 Sep 2023), so cancel by Tue 30 Jun 2026 to
    leave on Wed 30 Sep 2026."""
    assert "cancel by Tue 30 Jun 2026 to leave Wed 30 Sep 2026" in _row(
        "Gym concluded 1 Oct 2021 for 30 months"
    )
    gym = ContractTerms(
        category="gym",
        concluded_date="2021-10-01",
        start_date="2021-10-01",
        initial_term_months=30,
        renewal_term_months=12,
        notice_value=3,
        notice_unit="months",
    )
    result = compute_contract(gym, RuleContext(today=D("2026-05-01"), region="NW"))
    assert result.regime == "bgb309_old"
    assert (result.cancel_by, result.earliest_exit) == ("2026-06-30", "2026-09-30")


def test_a_new_health_insurance_member_is_bound_for_twelve_months() -> None:
    """Section 8: a member of a statutory health insurer since 15 Jun 2026 is bound until 14 Jun 2027 (§ 175
    SGB V); two months' notice to a month's end: notice by Fri 30 Apr 2027, membership ends Wed 30 Jun 2027."""
    assert "bound until 14 Jun 2027 → notice by Fri 30 Apr 2027 → ends Wed 30 Jun 2027" in _row(
        "Statutory health insurance, member since 15 Jun 2026"
    )
    health = ContractTerms(category="insurance", party_kind="health_insurer", start_date="2026-06-15")
    result = compute_contract(health, RuleContext(today=D("2026-09-25"), region="NW"))
    assert result.regime == "sgbv175"
    assert (result.cancel_by, result.earliest_exit) == ("2027-04-30", "2027-06-30")
