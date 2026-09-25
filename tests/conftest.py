"""Shared pytest fixtures: a throw-away data directory and a :class:`Store` opened on it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from ordnung import clock
from ordnung.config import Paths
from ordnung.db.store import Store


@pytest.fixture(autouse=True)
def _real_stamps() -> Iterator[None]:
    """A demo context dates records on its simulated day; never let that leak into the next test."""
    yield
    clock.stamp_simulated_day(False)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An empty Ordnung data directory inside pytest's tmp_path."""
    path = tmp_path / "data"
    path.mkdir()
    return path


@pytest.fixture
def paths(data_dir: Path) -> Paths:
    """The standard data-dir layout (files/, derived/, drafts/) under ``data_dir``."""
    return Paths(data_dir).ensure()


@pytest.fixture
def store(paths: Paths) -> Iterator[Store]:
    """A migrated, empty store; closed after the test."""
    opened = Store.open(paths)
    yield opened
    opened.close()
