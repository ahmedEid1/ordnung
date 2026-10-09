"""Warn once the rules were last checked against the law more than 90 days ago (CI's weekly run).

``LAST_CHECKED`` in ``src/ordnung/rules/catalog.py`` is the day the rules and their links were last checked
against the law, and ``PENDING_CHANGES`` lists the changes on their way. A rule that went stale would give
confident wrong dates, so CI's weekly run fails, with a warning, once that day is more than
:data:`MAX_AGE_DAYS` days ago, and lists the pending changes to re-check. Re-check the rules (and
docs/deadline-rules.md), then update ``LAST_CHECKED``. Pull requests don't run it.

Run it from the repository root::

    .venv/bin/python -m scripts.check_rules_age [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from ordnung.rules.catalog import LAST_CHECKED, PENDING_CHANGES, PendingChange

MAX_AGE_DAYS = 90


def stale_warning(last_checked: date, today: date, pending: Sequence[PendingChange]) -> str | None:
    """What to re-check when ``last_checked`` is more than :data:`MAX_AGE_DAYS` days before ``today``;
    ``None`` while it isn't."""
    age = (today - last_checked).days
    if age <= MAX_AGE_DAYS:
        return None
    lines = [
        f"The rules were last checked against the law on {last_checked.isoformat()}, {age} days ago (more than "
        f"{MAX_AGE_DAYS}): re-check them and docs/deadline-rules.md, then update LAST_CHECKED in "
        "src/ordnung/rules/catalog.py."
    ]
    if pending:
        lines.append("Pending changes to re-check:")
        lines += [
            f"- {change.change}. Status as of {last_checked.isoformat()}: {change.status}. Rules: "
            f"{', '.join(change.rule_ids)}. When it passes, update {change.update}."
            for change in pending
        ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.check_rules_age", description=__doc__)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(), help="the day to check on")
    args = parser.parse_args(argv)
    last_checked = date.fromisoformat(LAST_CHECKED)
    warning = stale_warning(last_checked, args.today, PENDING_CHANGES)
    if warning is None:
        print(f"The rules were last checked on {LAST_CHECKED}, {(args.today - last_checked).days} days ago.")
        return 0
    print(f"::warning title=Rules not re-checked::{warning.splitlines()[0]}")  # a GitHub annotation
    print(warning, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
