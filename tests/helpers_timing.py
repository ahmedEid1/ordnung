"""Linear-time checks that hold on any machine (``html_to_text``, and any reader of a string).

A fixed limit in seconds fails on a slow CI runner or under the coverage tracer (which slows Python
code several times), so these checks compare the machine with itself: reading an input four times as
long may take at most ``MAX_GROWTH`` times as long. Linear work grows about 4×, quadratic work 16×; the
limit sits between them with room for a busy machine (a run beside three browsers measured 8.2× for linear
work, whose readings grow 4.5× on an idle one).
A reading is timed in CPU time of the thread that reads (``time.thread_time``), not on the wall clock:
on a loaded machine the scheduler pauses the process for whole time slices, and a pause that falls into
one reading and not the other measured the machine's load, not the reader (wall-clock ratios of linear
work reached 10.8× at a load of 7 on 4 cores, CPU-time ratios 4.4×).
The garbage collector is paused while a reading runs: a full collection scans every object the test
session holds, so one that happens to fall into the larger reading (and not the smaller) measures the
suite's heap, not the parser — it made this check fail or pass depending on which tests were collected.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable

from ordnung.ingest.text import html_to_text

MAX_GROWTH = 10.0
#: Below this a reading is timer noise; the larger input may then take up to MAX_GROWTH × this.
NOISE_FLOOR_SECONDS = 0.005


def _read_html(markup: str) -> None:
    visible, _hidden = html_to_text(markup)
    assert visible


def read_seconds(markup: str, read: Callable[[str], object] = _read_html) -> float:
    """The faster of two readings of ``markup`` in CPU seconds of this thread (the slower one carries
    noise), with the garbage collector paused: a full collection scans every object earlier tests left
    alive, so in a long test run it made a large input look slower than its own work."""
    best = float("inf")
    gc.collect()
    paused = gc.isenabled()
    gc.disable()
    try:
        for _ in range(2):
            started = time.thread_time()
            read(markup)
            best = min(best, time.thread_time() - started)
    finally:
        if paused:
            gc.enable()
    return best


def assert_linear(build: Callable[[int], str], size: int, read: Callable[[str], object] = _read_html) -> None:
    """``build(size)`` and ``build(4 * size)`` are read (by ``read``, ``html_to_text`` by default) in
    time proportional to their length."""
    small = read_seconds(build(size), read)
    large = read_seconds(build(4 * size), read)
    assert large < MAX_GROWTH * max(small, NOISE_FLOOR_SECONDS), (small, large)
