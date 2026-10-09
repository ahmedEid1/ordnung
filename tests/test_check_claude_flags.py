"""scripts/check_claude_flags.py: CI's weekly run installs the real Claude Code and checks, without signing in
and without spending tokens, that it still takes every flag Ordnung passes. Here a fake ``claude`` that reads
its options as Claude Code does stands in for it."""

from __future__ import annotations

import inspect
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from ordnung.llm.claude_cli import ClaudeCLIBackend

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_claude_flags import CANARY, main, ordnung_argv  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake claude is a script with a shebang")

#: A fake ``claude``: ``--version`` and ``--help`` answer like Claude Code; otherwise an option it doesn't know
#: is refused as commander refuses it, and a call with known options fails for want of a sign-in. Each call
#: appends its arguments, environment and standard input to the log.
FAKE = """#!{python}
import json, os, sys
KNOWN = {known!r}
HIDDEN = {hidden!r}
args = sys.argv[1:]
with open({log!r}, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": args, "env": dict(os.environ), "stdin": sys.stdin.read()}}) + "\\n")
if args == ["--version"]:
    print({version!r})
    sys.exit(0)
if args == ["--help"]:
    print("Usage: claude [options] [command] [prompt]\\n\\nOptions:")
    for flag in KNOWN:
        if flag not in HIDDEN:
            print(f"  {{flag}} <value>   what it does")
    sys.exit(0)
for arg in args:
    if arg.startswith("-") and arg not in KNOWN and {strict!r}:
        print(f"Error: unknown option '{{arg}}'", file=sys.stderr)
        sys.exit(1)
print('{{"type":"result","is_error":true,"result":"Not logged in · Please run /login"}}')
sys.exit(1)
"""

#: Every flag Ordnung passes (as ``ClaudeCLIBackend.build_args`` writes them).
FLAGS = sorted(set(re.findall(r'"(--?[A-Za-z][\w-]*)"', inspect.getsource(ClaudeCLIBackend.build_args))))


def _fake(
    tmp_path: Path,
    *,
    known: list[str] = FLAGS,
    hidden: tuple[str, ...] = (),
    version: str = "2.1.5 (Claude Code)",
    strict: bool = True,
) -> tuple[Path, Path]:
    log = tmp_path / "calls.jsonl"
    path = tmp_path / "claude"
    script = FAKE.format(
        python=sys.executable, known=known, hidden=hidden, version=version, strict=strict, log=str(log)
    )
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path, log


def _calls(log: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_the_checked_call_passes_every_flag_ordnung_passes(tmp_path: Path) -> None:
    """The argument list is the backend's own, for a call that uses every option: a new flag in
    ``build_args`` is checked too."""
    assert {"-p", "--json-schema", "--mcp-config", "--max-budget-usd", "--include-partial-messages"} <= set(
        FLAGS
    )
    claude, _ = _fake(tmp_path)
    argv = ordnung_argv(str(claude), tmp_path / "data")
    assert argv[0] == str(claude)
    assert sorted({arg for arg in argv[1:] if arg.startswith("-")}) == FLAGS


def test_a_claude_that_takes_every_flag_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude, log = _fake(tmp_path)
    assert main(["--claude", str(claude)]) == 0
    out = capsys.readouterr().out
    assert "Claude Code 2.1.5 takes every flag Ordnung passes" in out
    called = [call["argv"] for call in _calls(log)]
    assert ["--version"] in called and ["--help"] in called
    assert any(CANARY in args for args in called)  # the made-up flag was refused, so the real ones were read


def test_a_flag_claude_no_longer_takes_fails_the_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claude, _ = _fake(tmp_path, known=[flag for flag in FLAGS if flag != "--max-budget-usd"])
    assert main(["--claude", str(claude)]) == 1
    printed = capsys.readouterr()
    assert "Error: unknown option '--max-budget-usd'" in printed.out + printed.err


def test_a_claude_that_never_refuses_an_option_fails_the_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Were unknown options taken in silence, a quiet answer would prove nothing."""
    claude, _ = _fake(tmp_path, strict=False)
    assert main(["--claude", str(claude)]) == 1
    assert f"didn't refuse the made-up flag {CANARY}" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["2.0.99 (Claude Code)", "Claude Code"])
def test_a_claude_older_than_ordnung_needs_or_without_a_version_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], version: str
) -> None:
    claude, _ = _fake(tmp_path, version=version)
    assert main(["--claude", str(claude)]) == 1
    assert "2.1.0" in capsys.readouterr().err


def test_a_flag_missing_from_help_is_only_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claude, _ = _fake(tmp_path, hidden=("--strict-mcp-config",))
    assert main(["--claude", str(claude)]) == 0
    assert "warning: claude --help no longer lists --strict-mcp-config" in capsys.readouterr().out


def test_claude_runs_signed_out_with_nothing_to_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No credentials reach it (a fresh home folder, none of the variables that sign Claude Code in) and its
    standard input is empty, so no prompt can reach a model."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-key")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "not-a-token")
    claude, log = _fake(tmp_path)
    assert main(["--claude", str(claude)]) == 0
    for call in _calls(log):
        env = call["env"]
        assert isinstance(env, dict)
        assert not {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"} & set(env)
        assert env["HOME"] != os.environ.get("HOME")
        assert call["stdin"] == ""


def test_no_claude_fails_the_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--claude", str(tmp_path / "missing" / "claude")]) == 1
    assert "not found" in capsys.readouterr().err
