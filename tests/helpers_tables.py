"""Table tests: one behaviour, held for many rows.

Thirty wordings that must all be read as a deadline are one behaviour with thirty rows, not thirty tests.
``check_rows`` runs the same check on every row and fails once, naming every row that failed, so a table
test says as much as one test per row while the suite stays one test per behaviour.

Use it when the rows are examples of one rule. When the rows are different rules a reader wants to see fail
apart, they are different tests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import pytest

__all__ = ["check_rows", "check_rows_async"]

_Param = type(pytest.param())  # what ``pytest.param(...)`` makes: values, marks and an id


def check_rows(rows: Iterable[Any], check: Callable[..., object], *, at_least: int = 2) -> None:
    """Run ``check`` on every row; fail once, with every failing row and what it failed on.

    A row that is a tuple is passed as the check's arguments, any other row as its only argument. A row
    written as ``pytest.param(..., id="name")`` is passed by its values and named by its id. The check
    passes by returning and fails by raising, as a test does (a ``pytest.raises`` that saw nothing raised and
    ``pytest.fail`` count as that row failing, like an assertion). A table with fewer than ``at_least`` rows
    fails: a table emptied by a wrong filter or a bad merge must not pass by checking nothing.
    """
    __tracebackhide__ = True
    table = _Table(at_least)
    for row in rows:
        args = table.next_row(row)
        try:
            check(*args)
        except _ROW_FAILED as exc:
            table.failed_on(exc)
    table.conclude()


async def check_rows_async(
    rows: Iterable[Any], check: Callable[..., Awaitable[object]], *, at_least: int = 2
) -> None:
    """``check_rows`` for a check that has to be awaited: the rows are awaited one after the other."""
    __tracebackhide__ = True
    table = _Table(at_least)
    for row in rows:
        args = table.next_row(row)
        try:
            await check(*args)
        except _ROW_FAILED as exc:
            table.failed_on(exc)
    table.conclude()


#: What a check raises when its row does not hold. ``pytest.fail`` and a ``pytest.raises`` that saw nothing
#: raised fail with pytest's own exception, which is not an ``Exception``.
_ROW_FAILED = (Exception, pytest.fail.Exception)


class _Table:
    """The bookkeeping both helpers share: which row is running, which rows failed and on what."""

    def __init__(self, at_least: int) -> None:
        self.at_least = at_least
        self.count = 0
        self.name = ""
        self.failed: list[str] = []

    def next_row(self, row: Any) -> tuple[Any, ...]:
        """Count the row, remember its name for a failure, and return the check's arguments."""
        self.count += 1
        self.name = repr(row)
        if isinstance(row, _Param):
            if row.marks:
                raise AssertionError(f"row {self.count} carries marks, which a table cannot honour: {row!r}")
            self.name = f"{row.id} {row.values!r}" if row.id else repr(row.values)
            row = row.values
        return row if isinstance(row, tuple) else (row,)

    def failed_on(self, exc: BaseException) -> None:
        reason = str(exc).strip() or type(exc).__name__
        if not isinstance(exc, AssertionError | pytest.fail.Exception):
            reason = f"{type(exc).__name__}: {reason}"
        self.failed.append(f"row {self.count}: {self.name}\n    " + reason.replace("\n", "\n    "))

    def conclude(self) -> None:
        __tracebackhide__ = True
        if self.count < self.at_least:
            raise AssertionError(f"the table has {self.count} row(s), expected at least {self.at_least}")
        if self.failed:
            raise AssertionError(f"{len(self.failed)} of {self.count} rows failed\n" + "\n".join(self.failed))
