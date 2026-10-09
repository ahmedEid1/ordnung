"""scripts/check_rules_age.py: CI's weekly run fails, with a warning, once the rules were last checked against the
law more than 90 days ago, and names the pending changes to re-check."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from ordnung.rules.catalog import LAST_CHECKED, PENDING_CHANGES, PendingChange

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_rules_age import MAX_AGE_DAYS, main, stale_warning  # noqa: E402

CHECKED = date.fromisoformat(LAST_CHECKED)


def test_the_rules_are_stale_only_after_ninety_days(capsys: pytest.CaptureFixture[str]) -> None:
    assert MAX_AGE_DAYS == 90
    assert main(["--today", (CHECKED + timedelta(days=90)).isoformat()]) == 0
    assert f"last checked on {LAST_CHECKED}, 90 days ago" in capsys.readouterr().out
    assert main(["--today", (CHECKED + timedelta(days=91)).isoformat()]) == 1
    printed = capsys.readouterr()
    assert printed.out.startswith("::warning title=Rules not re-checked::The rules were last checked")
    assert f"on {LAST_CHECKED}, 91 days ago (more than 90)" in printed.out
    for change in PENDING_CHANGES:  # each one named, with the rules it touches
        assert change.change in printed.err and ", ".join(change.rule_ids) in printed.err


def test_the_warning_says_what_to_update_for_each_pending_change() -> None:
    change = PendingChange(
        change="A new rule on notice periods",
        status="In committee",
        rule_ids=("bgb_573c", "bgb_574b"),
        update="the notice cards",
        source="https://example.org",
    )
    warning = stale_warning(date(2026, 1, 1), date(2026, 6, 1), [change])
    assert warning == (
        "The rules were last checked against the law on 2026-01-01, 151 days ago (more than 90): re-check them "
        "and docs/deadline-rules.md, then update LAST_CHECKED in src/ordnung/rules/catalog.py.\n"
        "Pending changes to re-check:\n"
        "- A new rule on notice periods. Status as of 2026-01-01: In committee. Rules: bgb_573c, bgb_574b. "
        "When it passes, update the notice cards."
    )
    assert stale_warning(date(2026, 1, 1), date(2026, 6, 1), []) == warning.split("\n", 1)[0]
    assert stale_warning(date(2026, 1, 1), date(2026, 3, 31), [change]) is None
