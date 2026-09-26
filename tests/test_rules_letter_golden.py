"""Worked examples for the high-stakes letters (``tests/golden/letter_cases.json``), each with sources.

The cases come from the statutes and from court, ministry, Arbeitsagentur, tenants' association and
Verbraucherzentrale pages (cited per case). ``date`` cases run through the public ``compute_due``
(so routing by legal basis and by the letter's kind is part of what is tested), ``statement`` cases
through :func:`ordnung.rules.tenancy.statement_check` (``statement_text`` cases read the billing period
from the statement's text first, :func:`ordnung.rules.advice.billing_period`), ``withdrawal_long`` cases through
:func:`ordnung.rules.consumer.long_withdrawal_end`. Where sources disagree, the case records the
later date as ``alternative`` and the engine must give the earlier one (SPEC § 21).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ordnung.models import DateSpec
from ordnung.rules.advice import billing_period
from ordnung.rules.consumer import long_withdrawal_end
from ordnung.rules.deadlines import RuleContext, compute_due
from ordnung.rules.tenancy import statement_check

GOLDEN = Path(__file__).parent / "golden" / "letter_cases.json"
CASES: list[dict[str, Any]] = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
_DATES = ("today", "document_date", "received_date", "end_date")


def _ctx(raw: dict[str, Any]) -> RuleContext:
    return RuleContext(**{k: (date.fromisoformat(v) if k in _DATES and v else v) for k, v in raw.items()})


def _run(case: dict[str, Any]) -> dict[str, Any]:
    inp = case["input"]
    if inp["kind"] == "date":
        receipt = compute_due(DateSpec(**inp["spec"]), _ctx(inp["ctx"]))
        return receipt.model_dump()
    if inp["kind"] == "statement":
        check = statement_check(
            date.fromisoformat(inp["period_end"]),
            date.fromisoformat(inp["arrived"]),
            confirmed=inp["confirmed"],
            region=inp["region"],
        )
        return {
            "deadline": check.deadline.isoformat(),
            "late": check.late,
            "objections_by": check.objections_by.isoformat(),
        }
    if inp["kind"] == "statement_text":
        arrived = date.fromisoformat(inp["arrived"])
        period = billing_period(inp["text"], before=arrived)
        assert period is not None, case["id"]
        check = statement_check(period.end, arrived, confirmed=inp["confirmed"], region=inp["region"])
        return {
            "period_end": period.end.isoformat(),
            "exact": period.exact,
            "deadline": check.deadline.isoformat(),
            "late": check.late,
        }
    end, _ = long_withdrawal_end(date.fromisoformat(inp["start"]))
    return {"end": end.isoformat()}


def test_golden_file_shape() -> None:
    assert len(CASES) >= 20
    assert len({case["id"] for case in CASES}) == len(CASES)
    for case in CASES:
        assert case["reasoning"] and case["sources"], case["id"]
        assert all("https://" in source for source in case["sources"]), case["id"]
        assert case["input"]["kind"] in ("date", "statement", "statement_text", "withdrawal_long"), case["id"]
        if case["unsure"]:
            assert case.get("unsure_note"), case["id"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_letter_golden_case(case: dict[str, Any]) -> None:
    got = _run(case)
    mismatches = {
        key: (got.get(key), value) for key, value in case["expected"].items() if got.get(key) != value
    }
    assert not mismatches, f"{case['id']}: engine vs expected {mismatches}"
    alternative = case.get("alternative")
    if alternative is not None:
        assert (got.get("due_date") or got.get("end")) < alternative  # the earlier reading is kept


def test_every_new_rule_has_a_golden_case() -> None:
    cited = {case["id"].split("-")[0] for case in CASES}
    assert {"zpo692", "zpo339", "kschg4", "sgb3", "bgb558b", "bgb574b", "bgb556", "bgb355", "bgb356"} <= cited
