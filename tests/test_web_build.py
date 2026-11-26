"""The committed web build is the app and nothing else.

The mock world (``web/src/mocks``: an in-memory API and a sample life written by hand) is for the dev server,
Vitest, the capture script's own build and the online demo. It once shipped in the released build: about 450 kB of
test data in every install, and an address (``?mock=1``) that swapped a person's own letters for the sample life.
A build-time flag (``__ORDNUNG_MOCKS__``, web/vite.config.ts) now leaves it out; these tests read the committed
build and the sources, without Node, so they run everywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "src" / "ordnung" / "web" / "dist"
SRC = ROOT / "web" / "src"

#: What only the mock world puts in a build: the window property its API is installed under, the tab's session key
#: that kept mock mode on, the banner it showed, and the id of its court payment order (web/src/mocks/data).
MOCK_MARKERS = ("__ordnungMock", "ordnung.mock", "Browser-only sample data", "doc_mahnbescheid")
TEXT_SUFFIXES = {".js", ".css", ".html", ".json", ".txt", ".svg", ".webmanifest"}

#: An import of a module: ``import … from "x"``, ``import "x"``, ``export … from "x"`` and ``import("x")``.
_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)["']([^"']+)["']""")
_GATE = "if (__ORDNUNG_MOCKS__) {"


def _built_files() -> list[Path]:
    return [path for path in DIST.rglob("*") if path.is_file()]


def test_the_build_has_no_mock_world() -> None:
    """No chunk of the mock world (its entry, ``install.ts``, made a chunk of that name) and none of its markers in
    any file of the build. The marker list is checked against the sources, so a renamed marker cannot make the
    test pass by finding nothing."""
    files = _built_files()
    assert any(path.name == "index.html" for path in files), "no committed build"
    assert not [path.name for path in files if re.fullmatch(r"install-[\w-]+\.js", path.name)]
    mocks = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.ts*") if "mocks" in path.parts)
    shell = (SRC / "components" / "shell" / "MockBanner.tsx").read_text(encoding="utf-8")
    mode = (SRC / "lib" / "mode.ts").read_text(encoding="utf-8")
    for marker in MOCK_MARKERS:
        assert marker in mocks + shell + mode, f"{marker!r} is no longer a marker of the mock world"
    found = {
        f"{path.relative_to(DIST)}: {marker}"
        for path in files
        if path.suffix in TEXT_SUFFIXES
        for marker in MOCK_MARKERS
        if marker in path.read_text(encoding="utf-8", errors="replace")
    }
    assert not found, sorted(found)


def test_the_build_has_no_source_maps() -> None:
    """A source map would carry every source file, the mock world's too, into the install."""
    files = _built_files()
    assert not [path.name for path in files if path.suffix == ".map"]
    linked = [path.name for path in files if path.suffix in {".js", ".css"} and "sourceMappingURL" in path.read_text(encoding="utf-8")]
    assert not linked, linked


def _app_modules() -> list[Path]:
    """The web app's own modules: not the mock world, not the test helpers, not a test."""
    return [
        path
        for path in sorted(SRC.rglob("*"))
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
        and not path.relative_to(SRC).parts[0] in {"mocks", "test"}
    ]


def _test_only(module: Path, spec: str) -> bool:
    """Whether ``spec`` imported from ``module`` names a module of the mock world or of the test helpers."""
    if spec.startswith("@/"):
        first = spec[2:].split("/")[0]
    elif spec.startswith("."):
        target = (module.parent / spec).resolve()
        try:
            first = target.relative_to(SRC.resolve()).parts[0]
        except ValueError:
            return False
    else:
        return False
    return first in {"mocks", "test"}


def _gated(text: str, offset: int) -> bool:
    """Whether ``offset`` lies inside an ``if (__ORDNUNG_MOCKS__) { … }`` block of ``text``."""
    for match in re.finditer(re.escape(_GATE), text):
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        if match.end() <= offset < i:
            return True
    return False


def test_only_main_loads_the_mock_world_and_only_behind_the_flag() -> None:
    """The build leaves out what no module of the app reaches: so no module of the app may name the mock world or the
    test helpers, except ``main.tsx``'s one dynamic import, inside ``if (__ORDNUNG_MOCKS__)``, which the build folds
    away when the flag is off."""
    modules = _app_modules()
    assert len(modules) > 100, len(modules)
    found: list[str] = []
    gated: list[str] = []
    for module in modules:
        text = module.read_text(encoding="utf-8")
        for match in _IMPORT.finditer(text):
            if not _test_only(module, match.group(1)):
                continue
            where = f"{module.relative_to(SRC)}: {match.group(1)}"
            dynamic = re.match(r"import\s*\(", match.group(0)) is not None
            if module == SRC / "main.tsx" and dynamic and _gated(text, match.start()):
                gated.append(where)
            else:
                found.append(where)
    assert not found, found
    assert gated == ["main.tsx: @/mocks/install"], gated
