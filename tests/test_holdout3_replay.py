"""holdout3 was recorded once, on the code frozen for it (2026-10-06); the code has changed since. Replayed on the
current code, its one recording must give the Ordnung path the same prediction for every letter, so README row ¹⁰
still describes what the app does. Replay only: no model call, nothing written to ``evals/results``."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import run as eval_run  # noqa: E402

RECORDING = ROOT / "evals" / "results" / "2026-10-06-claude-sonnet-5-holdout3.json"
#: Fields of a prediction that describe the run, not the answer: the calls' timings and backend, the code's fingerprint.
VOLATILE = ("calls", "fingerprint")

pytestmark = pytest.mark.slow


def _ordnung_predictions(results: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for entry in results["entries"]:
        prediction = dict(entry["conditions"]["ordnung"]["prediction"])
        for field in VOLATILE:
            prediction.pop(field, None)
        out[entry["id"]] = prediction
    return out


def test_holdout3_s_recording_gives_the_same_predictions_on_the_current_code(tmp_path: Path) -> None:
    out = tmp_path / "replayed"
    code = eval_run.run_cli(
        [
            "--split", "holdout3", "--model", "claude-sonnet-5", "--conditions", "ordnung", "--no-docs",
            "--no-resume", "--results-dir", str(out), "--quiet",
        ]
    )  # fmt: skip
    assert code == 0
    replayed = json.loads(next(out.glob("*-holdout3.json")).read_text(encoding="utf-8"))
    recorded = json.loads(RECORDING.read_text(encoding="utf-8"))
    after_metrics, before_metrics = dict(replayed["metrics"]["ordnung"]), dict(recorded["metrics"]["ordnung"])
    # the cost is a sum of floats in the order the letters finished (concurrent): equal up to rounding
    after_cost, before_cost = after_metrics.pop("cost_usd"), before_metrics.pop("cost_usd")
    assert after_cost.keys() == before_cost.keys()
    assert all(math.isclose(after_cost[key], before_cost[key], rel_tol=1e-12) for key in before_cost)
    # how long the calls took describes the run, not the answers
    after_metrics.pop("latency_ms"), before_metrics.pop("latency_ms")
    assert after_metrics == before_metrics
    before, after = _ordnung_predictions(recorded), _ordnung_predictions(replayed)
    assert after.keys() == before.keys()
    changed = sorted(entry_id for entry_id in before if after[entry_id] != before[entry_id])
    assert changed == []
