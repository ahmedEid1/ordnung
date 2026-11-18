"""The table-test helper: every failing row is named, and an empty table cannot pass."""

from __future__ import annotations

import pytest

from helpers_tables import check_rows


def test_a_table_whose_rows_all_hold_passes() -> None:
    seen: list[tuple[int, int]] = []

    def check(a: int, b: int) -> None:
        seen.append((a, b))
        assert a < b

    check_rows([(1, 2), (3, 4)], check)
    assert seen == [(1, 2), (3, 4)]


def test_every_failing_row_is_named_with_its_reason() -> None:
    def even(n: int) -> None:
        assert n % 2 == 0, f"{n} is odd"

    with pytest.raises(AssertionError) as failure:
        check_rows([2, 3, 4, 5], even)
    message = str(failure.value)
    assert message.startswith("2 of 4 rows failed")
    assert "row 2: 3\n    3 is odd" in message
    assert "row 4: 5\n    5 is odd" in message
    assert "row 1" not in message and "row 3" not in message


def test_a_row_that_raises_something_else_is_a_failing_row() -> None:
    with pytest.raises(AssertionError, match=r"row 2: 'x'\n    ValueError: invalid literal"):
        check_rows(["1", "x"], int)


def test_a_row_where_nothing_was_raised_though_the_check_expects_it_is_a_failing_row() -> None:
    def refuses(text: str) -> None:
        with pytest.raises(ValueError, match="invalid literal"):
            int(text)

    with pytest.raises(AssertionError) as failure:
        check_rows(["x", "1", "y", "2"], refuses)
    message = str(failure.value)
    assert message.startswith("2 of 4 rows failed")
    assert "row 2: '1'\n    DID NOT RAISE" in message
    assert "row 4: '2'\n    DID NOT RAISE" in message


def test_a_table_with_too_few_rows_fails() -> None:
    with pytest.raises(AssertionError, match="0 row"):
        check_rows([], lambda row: None)
    with pytest.raises(AssertionError, match="1 row"):
        check_rows([1], lambda row: None)
    check_rows([1], lambda row: None, at_least=1)


def test_a_row_written_as_a_pytest_param_is_named_by_its_id() -> None:
    def positive(n: int, label: str) -> None:
        assert n > 0, label

    rows = [pytest.param(1, "one", id="first"), pytest.param(-1, "minus one", id="second"), (-2, "bare")]
    with pytest.raises(AssertionError) as failure:
        check_rows(rows, positive)
    message = str(failure.value)
    assert message.startswith("2 of 3 rows failed")
    assert "row 2: second (-1, 'minus one')\n    minus one" in message
    assert "row 3: (-2, 'bare')\n    bare" in message


def test_a_row_with_marks_is_refused() -> None:
    rows = [pytest.param(1, marks=pytest.mark.xfail), pytest.param(2)]
    with pytest.raises(AssertionError, match="carries marks"):
        check_rows(rows, lambda n: None)
