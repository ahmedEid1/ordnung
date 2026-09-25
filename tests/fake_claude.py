#!/usr/bin/env python3
"""A fake ``claude`` CLI for tests: replays a captured ``stream-json`` transcript.

It stands in for ``claude -p --input-format stream-json --output-format stream-json``: it reads the
request (one stream-json user message) from stdin and prints the lines of a transcript to stdout
verbatim — a normal answer, an error result, a broken or oversized line. ``--version`` and
``auth status`` answer like the real CLI. What a call does is set by the JSON file named in
``FAKE_CLAUDE_SCENARIO``::

    {"log": "<file>", "calls": [{...}, {...}]}

Call *n* uses ``calls[n]`` (the last one repeats). Each call may have:

* ``lines`` — lines to print first; ``big_line`` — then one JSON line of about that many bytes;
* ``transcript`` — then a ``.jsonl`` file (relative to ``tests/claude_cli_outputs``), line by line;
* ``stderr`` — text for stderr; ``exit`` — the exit code (default 0);
* ``read_stdin`` — ``false`` to never read the request (a CLI that is stuck before reading);
* ``child`` — start a child process first (like the MCP server Ask starts) that sleeps;
* ``hang`` — after printing, sleep until killed (a CLI that never finishes).

Every call appends ``{"argv", "stdin", "pid", "child_pid"}`` as one JSON line to ``log``, before it
prints anything, so a test can check what was sent and which processes must be gone afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUTPUTS = Path(__file__).resolve().parent / "claude_cli_outputs"


def main(argv: list[str]) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if argv == ["--version"]:
        print("2.1.5 (Claude Code)")
        return 0
    if argv[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
        return 0
    scenario = json.loads(Path(os.environ["FAKE_CLAUDE_SCENARIO"]).read_text(encoding="utf-8"))
    log = Path(scenario["log"])
    calls = scenario["calls"]
    done = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
    call = calls[min(done, len(calls) - 1)]

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
