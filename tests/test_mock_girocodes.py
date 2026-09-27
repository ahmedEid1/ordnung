"""The static demo's GiroCodes are what the gate decides today: ``web/src/mocks/data/girocodes.ts``
is ``scripts/gen_mock_girocodes.py``'s output (regenerate it after changing the gate or builder)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_static_demo_shows_exactly_what_the_gate_decides() -> None:
    spec = importlib.util.spec_from_file_location(
        "gen_mock_girocodes", ROOT / "scripts" / "gen_mock_girocodes.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = (ROOT / "web" / "src" / "mocks" / "data" / "girocodes.ts").read_text(encoding="utf-8")
    assert current == module.render(), (
        "run: .venv/bin/python scripts/gen_mock_girocodes.py > web/src/mocks/data/girocodes.ts"
    )
