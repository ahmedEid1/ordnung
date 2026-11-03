"""The benchmark's document kinds are the product's (``ordnung.models.DOCUMENT_KINDS``, SPEC §17).

The generator keeps its own copy of the vocabulary (``evals/gen/common.py``), because it must not import the product,
and ``tests/test_eval_dataset.py`` checks the labels against that copy, so it runs where the product is not installed.
This module holds both to the product's list: the copy is the product's, and every label's kind is one the product
knows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.gen import common  # noqa: E402

from ordnung.models import DOCUMENT_KINDS  # noqa: E402

MANIFEST = ROOT / "evals" / "dataset" / "manifest.json"


def test_the_generator_s_kinds_are_the_product_s() -> None:
    assert common.DOCUMENT_KINDS == set(DOCUMENT_KINDS)


def test_every_label_s_kind_is_one_the_product_knows() -> None:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["entries"]
    assert entries
    for entry in entries:
        truth = entry["truth"]
        assert truth["kind"] in DOCUMENT_KINDS, entry["id"]
        assert set(truth["kind_also_accepted"]) <= set(DOCUMENT_KINDS), entry["id"]
