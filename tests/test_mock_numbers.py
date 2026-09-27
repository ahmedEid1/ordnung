"""The static demo's My numbers and weekly session are what Ordnung's own code computes for its letters.

``web/src/mocks/data/numbers.ts`` is written by ``scripts/gen_mock_numbers.py``; when the mock letters,
:mod:`ordnung.numbers` or :mod:`ordnung.secretary.week` change, it has to be written again. Needs Node
and the web app's packages (skipped without them).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "web" / "src" / "mocks" / "data" / "numbers.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (ROOT / "web" / "node_modules" / "jiti").exists(),
    reason="needs node and web/node_modules (npm ci in web/)",
)


def test_mock_numbers_are_up_to_date(capsys: pytest.CaptureFixture[str]) -> None:
    spec = importlib.util.spec_from_file_location(
        "gen_mock_numbers", ROOT / "scripts" / "gen_mock_numbers.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        module.main()
    finally:
        sys.modules.pop(spec.name, None)
    out = capsys.readouterr().out
    assert out == GENERATED.read_text(encoding="utf-8"), (
        "web/src/mocks/data/numbers.ts is out of date — run "
        "`.venv/bin/python scripts/gen_mock_numbers.py > web/src/mocks/data/numbers.ts`"
    )
