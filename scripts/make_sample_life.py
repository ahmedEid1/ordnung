#!/usr/bin/env python3
"""Generate the fictional "sample life" of the demo persona Sam Rivera.

Writes realistic German (and some English) letters, bills, contracts and phone photos plus a
``manifest.json`` with ground truth to ``src/ordnung/demo/samples``. The output is deterministic:
running the script twice produces byte-identical files.

Usage::

    python scripts/make_sample_life.py                 # regenerate the demo samples
    python scripts/make_sample_life.py --out /tmp/s    # write elsewhere
    python scripts/make_sample_life.py --check         # fail if the committed samples are stale
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from samplelife.build import main

if __name__ == "__main__":
    sys.exit(main())
