#!/usr/bin/env python3
"""A fake ``claude`` CLI for tests: replays a captured ``stream-json`` transcript.

It stands in for ``claude -p --input-format stream-json --output-format stream-json``: it reads the
request (one stream-json user message) from stdin and prints the lines of a transcript to stdout
verbatim — a normal answer, an error result, a broken or oversized line. ``--version`` (the one in
``FAKE_CLAUDE_VERSION``, else 2.1.5) and ``auth status`` answer like the real CLI. What a call does is
set by the JSON file named in ``FAKE_CLAUDE_SCENARIO``::

    {"log": "<file>", "calls": [{...}, {...}]}

Call *n* uses ``calls[n]`` (the last one repeats). Each call may have:

* ``lines`` — lines to print first; ``big_line`` — then one JSON line of about that many bytes;
* ``transcript`` — then a ``.jsonl`` file (relative to ``tests/claude_cli_outputs``), line by line;
* ``stderr`` — text for stderr; ``exit`` — the exit code (default 0);
* ``read_stdin`` — ``false`` to never read the request (a CLI that is stuck before reading);
* ``exit_before_reading`` — write ``stderr`` and exit with ``exit`` at once, the request unread and
  nothing printed (a broken install: ``env: node: No such file or directory``, exit 127);
* ``child`` — start a child process first (like the MCP server Ask starts) that sleeps;
* ``hang`` — after printing, sleep until killed (a CLI that never finishes).

Every call appends ``{"argv", "stdin", "pid", "child_pid"}`` as one JSON line to ``log``, before it
prints anything, so a test can check what was sent and which processes must be gone afterwards.

``--version`` and ``auth status`` read no scenario. With ``FAKE_CLAUDE_STATUS_LOG`` (a file) they first
append ``{"argv", "pid", "stdin_null"}`` to it (``stdin_null``: their input is the null device); with
``FAKE_CLAUDE_STATUS_HANG`` set they then sleep until killed (a CLI stuck before it answers).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUTPUTS = Path(__file__).resolve().parent / "claude_cli_outputs"


def status(argv: list[str]) -> None:
    """What ``--version`` and ``auth status`` do before they answer (see the module notes)."""
    log = os.environ.get("FAKE_CLAUDE_STATUS_LOG")
    if log:
        null = os.path.samestat(os.fstat(0), os.stat(os.devnull))
        record = {"argv": argv, "pid": os.getpid(), "stdin_null": null}
        with Path(log).open("a", encoding="utf-8") as out:
            out.write(json.dumps(record) + "\n")
    if os.environ.get("FAKE_CLAUDE_STATUS_HANG"):
        time.sleep(120)


def main(argv: list[str]) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if argv == ["--version"] or argv[:2] == ["auth", "status"]:
        status(argv)
    if argv == ["--version"]:
        print(os.environ.get("FAKE_CLAUDE_VERSION", "2.1.5 (Claude Code)"))
        return 0
    if argv[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
        return 0
    scenario = json.loads(Path(os.environ["FAKE_CLAUDE_SCENARIO"]).read_text(encoding="utf-8"))
    log = Path(scenario["log"])
    calls = scenario["calls"]
    done = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
    call = calls[min(done, len(calls) - 1)]

    if call.get("exit_before_reading"):
        record = {"argv": argv, "stdin": "", "pid": os.getpid(), "child_pid": None}
        with log.open("a", encoding="utf-8") as out:
            out.write(json.dumps(record) + "\n")
        sys.stderr.write(call.get("stderr", ""))
        sys.stderr.flush()
        return int(call.get("exit", 0))

    child = None
    if call.get("child"):  # its own pipes, like an MCP server: only its process group ties it to us
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    stdin = sys.stdin.read() if call.get("read_stdin", True) else ""
    record = {"argv": argv, "stdin": stdin, "pid": os.getpid(), "child_pid": child.pid if child else None}
    with log.open("a", encoding="utf-8") as out:
        out.write(json.dumps(record) + "\n")

    for line in call.get("lines", []):
        sys.stdout.write(line + "\n")
    if call.get("big_line"):
        sys.stdout.write('{"type": "assistant", "padding": "' + "x" * call["big_line"] + '"}\n')
    if call.get("transcript"):
        sys.stdout.write((OUTPUTS / call["transcript"]).read_text(encoding="utf-8"))
    sys.stdout.flush()
    if call.get("stderr"):
        sys.stderr.write(call["stderr"])
        sys.stderr.flush()
    if call.get("hang") or not call.get("read_stdin", True):
        time.sleep(120)
    return int(call.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
