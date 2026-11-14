"""The dropped-date check's ablation (``scripts/deadline_check_ablation.py``) and the claim it backs.

docs/deadline-rules.md § 6 says how many dates the check finds on the benchmark letters once the readings' to-dos
are removed, and that each is on a labelled due date. The page names the command that measures it, the script's
usage line runs as written from the repository's root (no ``PYTHONPATH``: ``python -m`` puts the root on the path
and ``ordnung`` is installed), and a replay of the four benchmark splits gives the page's number. The replay calls
no model and prints only ids, dates and counts.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deadline_check_ablation.py"
#: The splits the page's count covers (holdout3, recorded since, is the script's too when no split is named).
FOUR_SPLITS = ("dev", "test", "holdout", "holdout2")
COMMAND = f"python -m scripts.deadline_check_ablation --splits {' '.join(FOUR_SPLITS)}"


def _claim() -> tuple[int, str]:
    """The number of dates the page says the check finds, and the paragraph that says it."""
    rules = (ROOT / "docs" / "deadline-rules.md").read_text(encoding="utf-8")
    paragraph = next(
        " ".join(block.split())
        for block in rules.split("\n\n")
        if "with the readings' to-dos removed it finds" in " ".join(block.split())
    )
    found = re.search(r"with the readings' to-dos removed it finds (\d+) dates on the benchmark letters", paragraph)
    assert found is not None, paragraph
    return int(found[1]), paragraph


def test_the_rules_page_names_the_command_beside_its_claim() -> None:
    _, paragraph = _claim()
    assert f"`{COMMAND} --out <file>`" in paragraph


def test_the_usage_line_runs_from_the_root_as_written() -> None:
    """It said ``PYTHONPATH=src:. .venv/bin/python -m …``; neither part is needed."""
    usage = ast.get_docstring(ast.parse(SCRIPT.read_text(encoding="utf-8")))
    assert usage is not None
    assert "PYTHONPATH" not in usage
    assert ".venv/bin/python -m scripts.deadline_check_ablation --out PATH" in usage


@pytest.mark.slow
def test_a_replay_of_the_four_splits_finds_the_page_s_dates(tmp_path: Path) -> None:
    claimed, _ = _claim()
    out = tmp_path / "ablation.json"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "-m", "scripts.deadline_check_ablation", "--splits", *FOUR_SPLITS, "--out", str(out)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    total = json.loads(out.read_text(encoding="utf-8"))["total"]
    assert total["filed"] == claimed
    assert total["on_labelled_date"] == claimed and total["not_on_labelled_date"] == 0
