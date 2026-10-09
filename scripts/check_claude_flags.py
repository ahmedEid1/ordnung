"""Check that the installed Claude Code still takes every flag Ordnung passes it, without signing in and without
spending tokens (CI's weekly run, after installing Claude Code the way the README says).

Ordnung runs ``claude -p`` with the argument list ``ClaudeCLIBackend.build_args`` writes, and refuses a Claude
Code older than ``MIN_CLAUDE_VERSION``. This script fails when

1. ``claude --version`` names no version, or one older than that;
2. Claude Code refuses an option of the argument list Ordnung writes for a call that uses every option (Ask's
   allowed tools, MCP server and budget, a reading's JSON schema, partial messages). It runs with an empty
   standard input, a fresh home folder and none of the variables that sign Claude Code in, so it has nothing
   to send and no account to send it with: it stops at the sign-in, or earlier, at an option it can't read;
3. the same list with one made-up flag (:data:`CANARY`) isn't refused, so a quiet answer to the real list
   proves nothing (checked only when the real list drew no refusal: Claude Code stops at the first option
   it can't read, so it never reaches the made-up one).

A flag that ``claude --help`` no longer lists is only a warning (a flag can be hidden and still work).

Run it from the repository root::

    .venv/bin/python -m scripts.check_claude_flags [--claude PATH]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from ordnung.assistant.ask import ALLOWED_TOOLS, MAX_BUDGET_USD
from ordnung.assistant.mcp_server import server_config
from ordnung.llm.base import LLMRequest
from ordnung.llm.claude_cli import (
    MIN_CLAUDE_VERSION,
    ClaudeCLIBackend,
    find_claude,
    parse_version,
    version_text,
)

CANARY = "--ordnung-made-up-flag"
TIMEOUT_S = 120
#: How Claude Code (commander) says it can't read its arguments.
_REFUSED_RE = re.compile(
    r"error: (?:unknown option|option '|too many arguments|missing required argument)", re.I
)
_TROUBLE_RE = re.compile(r"unknown|invalid|unrecognized|not supported", re.I)
#: The environment variables kept for Claude Code: none that sign it in.
_KEPT = ("PATH", "LANG", "LC_ALL", "TMPDIR")


def ordnung_argv(binary: str, data_dir: Path) -> list[str]:
    """The argument list Ordnung writes for a call that uses every option it passes."""
    request = LLMRequest.model_validate(
        {
            "purpose": "test",
            "prompt": "",
            "system": "Check the flags.",
            "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            "tools": [],
            "allowed_tools": ALLOWED_TOOLS,
            "mcp_config": server_config(data_dir, rules_tools=False),
            "max_budget_usd": MAX_BUDGET_USD,
        }
    )
    return ClaudeCLIBackend(binary=binary).build_args(request, partial=True)


def _flags(argv: Sequence[str]) -> list[str]:
    return sorted({arg for arg in argv[1:] if arg.startswith("-")})


def refusals(output: str, flags: Sequence[str]) -> list[str]:
    """The lines of Claude Code's output that refuse its arguments, or name one of ``flags`` with an error."""
    long_flags = [flag for flag in flags if flag.startswith("--")]
    return [
        line.strip()
        for line in output.splitlines()
        if _REFUSED_RE.search(line) or (_TROUBLE_RE.search(line) and any(flag in line for flag in long_flags))
    ]


def _run(argv: Sequence[str], home: Path) -> str:
    """Claude Code's output for ``argv``: signed out, with nothing on its standard input."""
    env = {name: os.environ[name] for name in _KEPT if name in os.environ}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), DISABLE_AUTOUPDATER="1")
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    try:
        done = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=home,
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"error: {Path(argv[0]).name} did not finish within {TIMEOUT_S} s"
    except OSError as exc:
        return f"error: could not start {argv[0]}: {exc.strerror or exc}"
    return done.stdout + done.stderr


def check(binary: str) -> tuple[list[str], list[str], str]:
    """``(problems, warnings, version)`` for the Claude Code at ``binary``."""
    problems: list[str] = []
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ordnung-claude-flags-") as work:
        home = Path(work) / "home"
        home.mkdir()
        printed = _run([binary, "--version"], home).strip()
        found = parse_version(printed)
        if printed.startswith("error: could not start"):
            return [printed.removeprefix("error: ")], warnings, printed
        if found is None or found < MIN_CLAUDE_VERSION:
            problems.append(
                f"claude --version printed {printed!r}: Ordnung needs {version_text(MIN_CLAUDE_VERSION)} or newer"
            )
        argv = ordnung_argv(binary, Path(work) / "data")
        flags = _flags(argv)
        refused = refusals(_run(argv, home), flags)
        problems += [f"Claude Code refused Ordnung's arguments: {line}" for line in refused]
        # Claude Code stops at the first option it can't read: only a list it took reaches the made-up flag
        canary = [] if refused else refusals(_run([*argv, CANARY], home), [CANARY])
        if not refused and not any(CANARY in line for line in canary):
            problems.append(
                f"Claude Code didn't refuse the made-up flag {CANARY}, so its answer proves nothing"
            )
        listed = _run([binary, "--help"], home)
        for flag in flags:
            if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", listed):
                warnings.append(f"claude --help no longer lists {flag}")
    return problems, warnings, version_text(found) if found else printed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.check_claude_flags", description=__doc__)
    parser.add_argument(
        "--claude", help="the claude to check (default: ORDNUNG_CLAUDE_BIN, else the one on PATH)"
    )
    args = parser.parse_args(argv)
    binary = find_claude(args.claude)
    if binary is None:
        print(f"error: claude not found ({args.claude or 'ORDNUNG_CLAUDE_BIN or PATH'})", file=sys.stderr)
        return 1
    problems, warnings, version = check(str(Path(binary).absolute()))  # it runs in a folder of its own
    for warning in warnings:
        print(f"warning: {warning}")
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"Claude Code {version} takes every flag Ordnung passes ({binary}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
