#!/usr/bin/env python3
"""A fake ``tesseract`` for tests (ADR 0024): it answers ``--version``, ``--list-langs`` and a reading
(``stdin stdout -l deu+eng``) like Tesseract 5.3.4, or breaks the way an installed one can.

Run it as ``(sys.executable, "tests/fake_tesseract.py", …)``, through ``ordnung.ingest.ocr.Tesseract.launcher``:
no shell wrapper, so it runs on Windows too. ``FAKE_TESSERACT_MODE`` says what it does (default ``ok``):

* ``ok`` — Tesseract 5.3.4 with ``deu``, ``eng`` and ``osd``; a reading finds no words;
* ``echo`` — the same, and a reading prints :data:`ECHO_TEXT`;
* ``old`` — Tesseract 4.0.0 (too old);
* ``no-deu`` — no German language data (``eng`` and ``osd``);
* ``no-langs`` — neither German nor English (``osd`` only);
* ``silent`` — ``--version`` never answers (it sleeps until it is killed);
* ``hang`` — a reading never ends (it sleeps until it is killed);
* ``fail`` — a reading prints text on stdout and exits 1;
* ``report`` — like ``echo``; ``FAKE_TESSERACT_REPORT`` must name the report file;
* ``slow`` — like ``echo``, but it waits :data:`SLOW_S` seconds before it takes its stdin, as a real Tesseract
  loads its language data first (a picture larger than the pipe holds then waits for it).

A reading always takes its whole stdin first. When ``FAKE_TESSERACT_REPORT`` names a file, every reading writes
one JSON object there before it prints, fails or hangs: ``argv``, whether stdin began with a PNG signature
(``png``), its ``pid``, its ``priority`` (the niceness on Linux and macOS, ``GetPriorityClass`` on Windows, read
after stdin was taken) and the ``OMP_THREAD_LIMIT``, ``TMPDIR``, ``TMP`` and ``TEMP`` it was given (``null``:
not set). A mode it doesn't know exits 2.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

MODE_ENV = "FAKE_TESSERACT_MODE"
REPORT_ENV = "FAKE_TESSERACT_REPORT"
#: What ``echo`` and ``report`` read in any picture: fictional, with umlauts (UTF-8 on stdout).
ECHO_TEXT = "Ihr Kellerabteil 7 · Gebäude Süd"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

VERSIONS = {"old": "4.0.0"}
LANGUAGES = {"no-deu": ("eng", "osd"), "no-langs": ("osd",)}
MODES = ("ok", "echo", "old", "no-deu", "no-langs", "silent", "hang", "fail", "report", "slow")
#: The real 5.3.4's answer after its first line (on stdout).
VERSION_TAIL = (
    " leptonica-1.82.0\n"
    "  libgif 5.2.1 : libjpeg 8d (libjpeg-turbo 2.1.5) : libpng 1.6.43 : libtiff 4.5.1 : zlib 1.3\n"
    " Found AVX2\n"
)
TESSDATA = "/usr/share/tesseract-ocr/5/tessdata/"
FOREVER_S = 120
#: How long ``slow`` waits before it takes its stdin.
SLOW_S = 0.5


def _priority() -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Typed, or the pseudo-handle -1 reaches GetPriorityClass cut to 32 bits and the call answers 0 (failed)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
        kernel32.GetPriorityClass.restype = wintypes.DWORD
        priority = int(kernel32.GetPriorityClass(kernel32.GetCurrentProcess()))
        if priority == 0:
            raise OSError(ctypes.get_last_error(), "GetPriorityClass failed")
        return priority
    return os.getpriority(os.PRIO_PROCESS, 0)


def _report(argv: list[str], picture: bytes) -> None:
    target = os.environ.get(REPORT_ENV)
    if not target:
        return
    seen = {
        "argv": argv,
        "png": picture.startswith(PNG_SIGNATURE),
        "pid": os.getpid(),
        "priority": _priority(),
        **{name: os.environ.get(name) for name in ("OMP_THREAD_LIMIT", "TMPDIR", "TMP", "TEMP")},
    }
    Path(target).write_text(json.dumps(seen), encoding="utf-8")


def _read(mode: str, argv: list[str]) -> int:
    if mode == "slow":
        time.sleep(SLOW_S)
    picture = sys.stdin.buffer.read() if argv[:1] == ["stdin"] else b""
    _report(argv, picture)
    if mode == "report" and not os.environ.get(REPORT_ENV):
        sys.stderr.write(f"{REPORT_ENV} names no file\n")
        return 2
    if mode == "hang":
        time.sleep(FOREVER_S)
    if mode == "fail":
        sys.stdout.write("Error in pixReadMem: what the page said\n")
        sys.stdout.flush()
        return 1
    if mode in ("echo", "report", "slow"):
        sys.stdout.buffer.write(f"{ECHO_TEXT}\n".encode())
        sys.stdout.flush()
    return 0


def main(argv: list[str]) -> int:
    mode = os.environ.get(MODE_ENV, "ok")
    if mode not in MODES:
        sys.stderr.write(f"{MODE_ENV}={mode!r} is not one of {', '.join(MODES)}\n")
        return 2
    if argv == ["--version"]:
        if mode == "silent":
            time.sleep(FOREVER_S)
        sys.stdout.write(f"tesseract {VERSIONS.get(mode, '5.3.4')}\n{VERSION_TAIL}")
        return 0
    if argv == ["--list-langs"]:
        names = LANGUAGES.get(mode, ("deu", "eng", "osd"))
        sys.stdout.write(f'List of available languages in "{TESSDATA}" ({len(names)}):\n')
        sys.stdout.write("".join(f"{name}\n" for name in names))
        return 0
    if argv[:2] == ["stdin", "stdout"]:
        return _read(mode, argv)
    sys.stderr.write("Usage:\n  tesseract --help | --help-extra | --version\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
