"""External golden cases (auditor A): 45 hand-derived German deadline cases run through the engine.

The cases in ``tests/golden/external_cases.json`` were written from the verified legal research
without looking at ``src/ordnung/rules``; each carries its reasoning and citations. This module only
maps them onto the public API (``compute_due``, ``compute_contract``, ``price_increase_window``) and
compares the fields the case asserts:

* date cases → ``ComputationReceipt.due_date`` (and the event day — deemed delivery/service — taken
  from the ``bgb_187_1`` "counting starts the day after …" step, when the case states it);
* contract cases → ``regime``, ``cancel_by``, ``safe_date``, ``earliest_exit`` and
  ``current_term_end``. The case's ``current_term_end`` means "the end the earliest still-reachable
  regular cancellation produces", which is the engine's ``earliest_exit`` (the engine's own
  ``current_term_end`` is the running term even when its deadline has passed). Contracts are run
  with ``channel="online_button"`` so a cancellation counts as received on ``ctx.today``;
* price-increase cases → ``due_date`` / ``safe_date`` and the "arrives by … the new terms never apply"
  step for telecom.

A result that differs from the legal answer but equals one of the case's ``safe_acceptable`` dates
(an earlier date allowed by the safety policy, SPEC § 21) passes: it is conservative, not wrong. The
event day (``bekanntgabe``/``zustellung``) of such a result is not compared, because the earlier date
comes from counting from an earlier, conservative event day (e.g. a fine counted from the letter's
date when the DateSpec cannot say it was an Übergabe-Einschreiben).

Payment cases carry the payer's Land as ``recipient_region``: money owed to a private creditor is due
at the debtor's home, so § 193 BGB uses the payer's holidays (judge's note on audit B3).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ordnung.models import ComputationReceipt, ContractTerms, DateSpec
from ordnung.rules import compute_contract, compute_due, price_increase_window
from ordnung.rules.deadlines import RuleContext

GOLDEN = Path(__file__).parent / "golden" / "external_cases.json"
CASES: list[dict[str, Any]] = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]

#: Cases where the engine and the auditor disagree after re-derivation; see the reason for who is right.
KNOWN_DISAGREEMENTS: dict[str, str] = {}

_CONTRACT_FIELDS = ("regime", "cancel_by", "safe_date", "earliest_exit")
_PRICE_SECTOR_CATEGORY = {"energy": "energy", "telecom": "internet"}


def _ctx(raw: dict[str, Any]) -> RuleContext:
    dates = ("today", "document_date", "received_date")
    kwargs = {k: (date.fromisoformat(v) if k in dates and v else v) for k, v in raw.items()}
    return RuleContext(**kwargs)


def _event_day(receipt: ComputationReceipt) -> str | None:
    return next((s.date for s in receipt.steps if s.rule_id == "bgb_187_1"), None)


def _date_case(case: dict[str, Any]) -> dict[str, Any]:
    receipt = compute_due(DateSpec(**case["input"]["spec"]), _ctx(case["input"]["ctx"]))
    got: dict[str, Any] = {"due_date": receipt.due_date}
    for key in ("bekanntgabe", "zustellung"):
        if key in case["expected"]:
            got[key] = _event_day(receipt)
    return got


def _contract_case(case: dict[str, Any]) -> dict[str, Any]:
    inp = case["input"]
    result = compute_contract(ContractTerms(**inp["terms"]), _ctx(inp["ctx"]), channel=inp["channel"])
    got = {name: getattr(result, name) for name in _CONTRACT_FIELDS}
    got["current_term_end"] = result.earliest_exit
    return {k: v for k, v in got.items() if k in case["expected"]}


def _price_case(case: dict[str, Any]) -> dict[str, Any]:
    inp = case["input"]
    pi = inp["price_increase"]
    receipt = price_increase_window(
        date.fromisoformat(pi["effective_date"]),
        _PRICE_SECTOR_CATEGORY[pi["sector"]],
        date.fromisoformat(pi["notice_received"]),
        _ctx(inp["ctx"]),
        is_basic_supply=pi.get("is_basic_supply", False),
    )
    timely = not any("may not be valid" in w or "weren't told" in w for w in receipt.warnings)
    if pi["sector"] == "telecom":
        before_change = next(
            (s.date for s in receipt.steps if s.rule_id == "tkg_57" and "never apply" in s.label), None
        )
        got = {
            "cancel_by": before_change,
            "window_end": receipt.due_date,
            "window_end_safe": receipt.safe_date,
            "notice_timely": timely,
        }
    else:
        got = {
            "cancel_by": receipt.due_date,
            "safe_date": receipt.safe_date,
            "contract_end": receipt.due_date,
            "notice_timely": timely,
        }
    return {k: v for k, v in got.items() if k in case["expected"]}


_RUNNERS = {"date": _date_case, "contract": _contract_case, "price_increase": _price_case}


def _expected(case: dict[str, Any]) -> dict[str, Any]:
    informational = ("alternative_if_late_receipt_proven", "initial_term_end")
    return {k: v for k, v in case["expected"].items() if k not in informational}


def run_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(expected, engine result) restricted to the asserted fields."""
    expected = _expected(case)
    got = _RUNNERS[case["input"]["kind"]](case)
    return expected, {k: got.get(k) for k in expected}


def test_golden_file_shape() -> None:
    assert len(CASES) == 45
    assert len({c["id"] for c in CASES}) == 45
    for case in CASES:
        assert case["reasoning"] and case["sources"], case["id"]
        assert case["input"]["kind"] in _RUNNERS, case["id"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_external_golden_case(case: dict[str, Any]) -> None:
    if case["id"] in KNOWN_DISAGREEMENTS:
        pytest.xfail(KNOWN_DISAGREEMENTS[case["id"]])
    expected, got = run_case(case)
    safe = set(case.get("safe_acceptable", []))
    conservative = got.get("due_date") in safe
    mismatches = {
        k: (got[k], v)
        for k, v in expected.items()
        if got[k] != v
        and not (k in ("due_date", "cancel_by") and got[k] in safe)
        and not (conservative and k in ("bekanntgabe", "zustellung"))
    }
    assert not mismatches, f"{case['id']}: engine vs expected {mismatches}"
