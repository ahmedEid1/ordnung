"""What the server loads when it starts: a library first used later is imported where it is used.

The PDF writer (fpdf, which brings fontTools) writes a letter, a Nachweis or photos combined into one PDF —
never at start — and loading it there was about a tenth of the command's start. A fresh interpreter imports
the command and the web server, as ``ordnung serve`` does, and must find neither loaded.
"""

from __future__ import annotations

import json
import subprocess
import sys

#: Libraries the server's start must not load: each is imported in the function that first needs it.
LOADED_LATER = ("fpdf", "fontTools")


def test_the_server_starts_without_the_pdf_writer() -> None:
    code = (
        "import json, sys\n"
        "import ordnung.cli, ordnung.api.app\n"
        f"print(json.dumps(sorted(m for m in {LOADED_LATER!r} if m in sys.modules)))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True
    )
    assert json.loads(done.stdout.strip().splitlines()[-1]) == []
