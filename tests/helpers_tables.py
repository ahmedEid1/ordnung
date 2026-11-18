"""Table tests: one behaviour, held for many rows.

Thirty wordings that must all be read as a deadline are one behaviour with thirty rows, not thirty tests.
``check_rows`` runs the same check on every row and fails once, naming every row that failed, so a table
test says as much as one test per row while the suite stays one test per behaviour.

Use it when the rows are examples of one rule. When the rows are different rules a reader wants to see fail
apart, they are different tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pytest

__all__ = ["check_rows"]

_Param = type(pytest.param())  # what ``pytest.param(...)`` makes: values, marks and an id


def check_rows(rows: Iterable[Any], check: Callable[..., object], *, at_least: int = 2) -> None:
    """Run ``check`` on every row; fail once, with every failing row and what it failed on.

    A row that is a tuple is passed as the check's arguments, any other row as its only argument. A row
    written as ``pytest.param(..., id="name")`` is passed by its values and named by its id. The check
    passes by returning and fails by raising, as a test does. A table with fewer than ``at_least`` rows
    fails: a table emptied by a wrong filter or a bad merge must not pass by checking nothing.
    """
    __tracebackhide__ = True
    count = 0
    failed: list[str] = []
    for row in rows:
        count += 1
        name = repr(row)
        if isinstance(row, _Param):
            if row.marks:
                raise AssertionError(f"row {count} carries marks, which a table cannot honour: {row!r}")
            name = f"{row.id} {row.values!r}" if row.id else repr(row.values)
            row = row.values
        args = row if isinstance(row, tuple) else (row,)
        try:
            check(*args)
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            if not isinstance(exc, AssertionError):
                reason = f"{type(exc).__name__}: {reason}"
            failed.append(f"row {count}: {name}\n    " + reason.replace("\n", "\n    "))
    if count < at_least:
        raise AssertionError(f"the table has {count} row(s), expected at least {at_least}")
    if failed:
        raise AssertionError(f"{len(failed)} of {count} rows failed\n" + "\n".join(failed))
