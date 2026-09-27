"""Linear-time checks for ``html_to_text`` that hold on any machine.

A fixed limit in seconds fails on a slow CI runner or under the coverage tracer (which slows Python
code several times), so these checks compare the machine with itself: reading an input four times as
long may take at most ``MAX_GROWTH`` times as long. Linear work grows about 4×, quadratic work 16×.
The garbage collector is paused while a reading runs: a full collection scans every object the test
session holds, so one that happens to fall into the larger reading (and not the smaller) measures the
suite's heap, not the parser — it made this check fail or pass depending on which tests were collected.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable

from ordnung.ingest.text import html_to_text

MAX_GROWTH = 8.0
#: Below this a reading is timer noise; the larger input may then take up to MAX_GROWTH × this.
NOISE_FLOOR_SECONDS = 0.005


def read_seconds(markup: str) -> float:
    """The faster of two readings of ``markup`` (the slower one carries scheduling noise)."""
    best = float("inf")
    for _ in range(2):
        gc.collect()
        gc.disable()
        try:
            started = time.perf_counter()
            visible, _hidden = html_to_text(markup)
            best = min(best, time.perf_counter() - started)
        finally:
            gc.enable()
        assert visible
    return best


def assert_linear(build: Callable[[int], str], size: int) -> None:
    """``build(size)`` and ``build(4 * size)`` are read in time proportional to their length."""
    small = read_seconds(build(size))
    large = read_seconds(build(4 * size))
    assert large < MAX_GROWTH * max(small, NOISE_FLOOR_SECONDS), (small, large)
