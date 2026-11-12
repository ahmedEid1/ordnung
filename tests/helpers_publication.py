"""Whether the pre-registered final run is published in this checkout, for the tests that pin what the repository
holds before it: the publish PR adds the final run's reads, its analysis and the files made from them all at once
(evals/results), so a test that knows today's results files says what changes once the final analysis is there."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import analysis, splits  # noqa: E402

RESULTS = ROOT / "evals" / "results"
#: The final run's splits: the registry's role ``final``.
FINAL_SPLITS = tuple(split.name for split in splits.REGISTRY if split.role == "final")


def final_published(results: Path = RESULTS) -> bool:
    """Whether ``results`` holds the pre-registered final analysis (``python -m evals.analysis --prereg …``)."""
    for path in sorted(results.glob(f"*-{analysis.FINAL_KIND}.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        meta = data.get("meta") if isinstance(data, dict) else None
        if isinstance(meta, dict) and data.get("schema") == analysis.ANALYSIS_SCHEMA:
            if meta.get("kind") == analysis.FINAL_KIND:
                return True
    return False
