"""docs/README.md, the doc map: it lists every document by its reader, and PyPI's *Documentation* link opens it.

- Every page in ``docs/``, the decisions' index, the benchmark code's README and the root's CONTRIBUTING.md,
  SECURITY.md and CHANGELOG.md is linked from the map, so a page added to ``docs/`` fails here until the map
  names it.
- ``pyproject.toml``'s ``[project.urls] Documentation`` is the map on GitHub, and the map exists.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MAP = DOCS / "README.md"
REPOSITORY = "https://github.com/ahmedEid1/ordnung"

#: A Markdown link's target, without its ``#anchor`` (``[text](target#anchor)``).
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)\s]*)?\)")


def _linked() -> set[Path]:
    """The files the map links, each resolved from ``docs/``."""
    assert MAP.is_file(), "docs/README.md, the doc map, is missing"
    targets = _LINK.findall(MAP.read_text(encoding="utf-8"))
    return {(DOCS / target).resolve() for target in targets if not re.match(r"^[a-z][a-z+.-]*:", target)}


def test_the_doc_map_lists_every_doc() -> None:
    pages = [page for page in sorted(DOCS.glob("*.md")) if page != MAP]
    assert len(pages) >= 8, pages  # the search still finds them (SPEC, architecture, … releasing)
    wanted = [
        *pages,
        DOCS / "decisions" / "README.md",
        ROOT / "evals" / "README.md",
        *(ROOT / name for name in ("CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md")),
    ]
    linked = _linked()
    missing = [page.relative_to(ROOT).as_posix() for page in wanted if page.resolve() not in linked]
    assert not missing, f"not in docs/README.md: {missing}"


def test_pypi_s_documentation_link_opens_the_doc_map() -> None:
    urls = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["urls"]
    assert urls["Documentation"] == f"{REPOSITORY}/blob/main/docs/README.md"
    assert MAP.is_file()
