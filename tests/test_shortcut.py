"""``ordnung shortcut``: the launcher per operating system and ``serve --from-shortcut``, which it runs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ordnung import autostart, cli, shortcut
from ordnung.cli import app

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def invoke(*args: str) -> Any:
    return runner.invoke(app, list(args))


def plain(output: str) -> str:
    """Help text without terminal styling (Typer forces Rich styling on CI, e.g. GITHUB_ACTIONS)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", output)


# --------------------------------------------------------------------------------------------------
# what each system calls the launcher
# --------------------------------------------------------------------------------------------------


def test_each_system_has_its_launcher_and_the_menu_it_goes_into() -> None:
    assert shortcut.KINDS == {
        "linux": "app menu entry",
        "macos": "app in your Applications folder",
        "windows": "Start menu shortcut",
    }
    assert shortcut.WHERE == {
        "linux": "your app menu",
        "macos": "your Applications folder",
        "windows": "your Start menu",
    }
    assert set(shortcut.KINDS) == set(autostart.KINDS)
    state = shortcut.State(system="windows", path=Path("Ordnung.lnk"), added=False)
    assert state.kind == "Start menu shortcut" and state.ours and not state.current


def test_without_a_window_the_launcher_starts_nothing_and_says_so_with_exit_code_3() -> None:
    """The Mac bundle opens Terminal on that code; the CLI uses 1, 128+n and 130 for everything else."""
    assert shortcut.NO_WINDOW_EXIT == 3


# --------------------------------------------------------------------------------------------------
# serve --from-shortcut
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_serve(folder: Path, **kwargs: Any) -> None:
        calls.append({"folder": folder, **kwargs})

    monkeypatch.setattr(cli, "_serve", fake_serve)
    return calls


def test_serve_takes_the_launcher_s_flag_without_listing_it(
    served: list[dict[str, Any]], tmp_path: Path
) -> None:
    result = invoke("serve", "--data-dir", str(tmp_path), "--from-shortcut")
    assert result.exit_code == 0, result.output
    assert served[-1]["from_shortcut"] is True and served[-1]["folder"] == tmp_path
    assert invoke("serve", "--data-dir", str(tmp_path)).exit_code == 0
    assert served[-1]["from_shortcut"] is False
    help_text = plain(invoke("serve", "--help").output)
    assert "--no-browser" in help_text and "--from-shortcut" not in help_text
