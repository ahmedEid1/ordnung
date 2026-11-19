"""Read and write the demo folder's marker file."""

from __future__ import annotations

import json
from pathlib import Path

MARKER_NAME = ".ordnung-demo"


def read_demo_version(data_dir: Path) -> str | None:
    """The version recorded in a demo folder's marker (``None``: not a demo folder)."""
    try:
        marker = json.loads((data_dir / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(marker.get("version") or "") if isinstance(marker, dict) else None


def is_demo_dir(data_dir: Path) -> bool:
    """Whether ``data_dir`` is a demo folder (made by :func:`build_demo` or :func:`prepare_demo`)."""
    return read_demo_version(data_dir) is not None


def _write_marker(data_dir: Path, version: str) -> None:
    payload = {"kind": "ordnung-demo", "version": version}
    (data_dir / MARKER_NAME).write_text(json.dumps(payload) + "\n", encoding="utf-8")
