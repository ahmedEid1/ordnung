"""What the server loads when it starts: a library first used later is imported where it is used.

The PDF writer (fpdf, which brings fontTools) writes a letter, a Nachweis or photos combined into one PDF —
never at start — and loading it there was about a tenth of the command's start. httpx talks to a calendar
server only when calendar sync (off by default) runs, and asks a server that already runs for this data folder
whether it answers. A fresh interpreter imports the command and the web server and looks for a running server
in an empty data folder, as ``ordnung serve`` does before it listens, and must find none of them loaded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

#: Libraries the server's start must not load: each is imported in the function that first needs it.
LOADED_LATER = ("fpdf", "fontTools", "httpx")


def test_the_server_starts_without_the_libraries_it_loads_later(tmp_path: Path) -> None:
    code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "import ordnung.cli, ordnung.api.app\n"
        # the first thing "ordnung serve" does: is a server already running for this data folder? (none is)
        f"assert ordnung.cli.reachable_server(Path({str(tmp_path)!r})) is None\n"
        f"print(json.dumps(sorted(m for m in {LOADED_LATER!r} if m in sys.modules)))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True
    )
    assert json.loads(done.stdout.strip().splitlines()[-1]) == []
