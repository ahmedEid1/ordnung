"""Versioned prompt templates. ``load(name)`` returns ``(version, template)``."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent
_VERSION_RE = re.compile(r"^<!--\s*version:\s*(\S+)\s*-->\s*\n", re.M)


@cache
def load(name: str) -> tuple[str, str]:
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    m = _VERSION_RE.match(text)
    version = m.group(1) if m else "1"
    body = text[m.end() :] if m else text
    return version, body


def render(name: str, **values: object) -> tuple[str, str]:
    """Fill ``{{placeholders}}`` (double braces so JSON examples stay literal)."""
    version, body = load(name)
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", str(value))
    missing = re.findall(r"\{\{(\w+)\}\}", body)
    if missing:
        raise KeyError(f"prompt {name!r} missing values: {sorted(set(missing))}")
    return version, body
