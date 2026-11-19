"""The benchmark's document kinds are the product's (``ordnung.models.DOCUMENT_KINDS``, SPEC §17).

The generator keeps its own copy of the vocabulary (``evals/gen/common.py``), because it must not import the product,
and ``tests/test_eval_dataset.py`` checks the labels against that copy, so it runs where the product is not installed.
This module holds the copy to the product's list; with ``test_truth_schema`` there, every label's kind is one the
product knows.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.gen import common  # noqa: E402

from ordnung.models import DOCUMENT_KINDS  # noqa: E402


def test_the_generator_s_kinds_are_the_product_s() -> None:
    assert common.DOCUMENT_KINDS == set(DOCUMENT_KINDS)
