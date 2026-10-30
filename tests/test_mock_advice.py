"""The static demo's "get advice" cards say what the rules engine says: ``web/src/mocks/data/advice.ts`` is
``scripts/gen_mock_advice.py``'s output (regenerate it after changing :mod:`ordnung.rules.advice`).

The README's court-order picture shows one of these cards, so a rules change that moves one fails here, not in
the demo. The script computes on the mock demo's own day (``web/src/mocks/data/constants.ts``), never the
clock's.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "web" / "src" / "mocks" / "data" / "advice.ts"
CONSTANTS = ROOT / "web" / "src" / "mocks" / "data" / "constants.ts"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_mock_advice", ROOT / "scripts" / "gen_mock_advice.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_computes_on_the_mock_demo_s_day() -> None:
    found = re.search(r'export const TODAY = "(\d{4}-\d\d-\d\d)"', CONSTANTS.read_text(encoding="utf-8"))
    assert found, "web/src/mocks/data/constants.ts names no TODAY"
    assert _script().TODAY == date.fromisoformat(found.group(1))


def test_the_static_demo_s_advice_cards_are_what_the_rules_say(capsys: pytest.CaptureFixture[str]) -> None:
    _script().main()
    assert capsys.readouterr().out == GENERATED.read_text(encoding="utf-8"), (
        "web/src/mocks/data/advice.ts is out of date — run "
        "`.venv/bin/python scripts/gen_mock_advice.py > web/src/mocks/data/advice.ts`"
    )
