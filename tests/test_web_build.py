"""The committed web build is the app and nothing else.

The mock world (``web/src/mocks``: an in-memory API and a sample life written by hand) is for the dev server,
Vitest, the capture script's own build and the online demo. It once shipped in the released build: about 450 kB of
test data in every install, and an address (``?mock=1``) that swapped a person's own letters for the sample life.
A build-time flag (``__ORDNUNG_MOCKS__``, web/vite.config.ts) now leaves it out; these tests read the committed
build and the sources, without Node, so they run everywhere.
"""

from __future__ import annotations

import gzip
import json
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
    mocks = "\n".join(
        path.read_text(encoding="utf-8") for path in SRC.rglob("*.ts*") if "mocks" in path.parts
    )
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
    linked = [
        path.name
        for path in files
        if path.suffix in {".js", ".css"} and "sourceMappingURL" in path.read_text(encoding="utf-8")
    ]
    assert not linked, linked


def _app_modules() -> list[Path]:
    """The web app's own modules: not the mock world, not the test helpers, not a test."""
    return [
        path
        for path in sorted(SRC.rglob("*"))
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
        and path.relative_to(SRC).parts[0] not in {"mocks", "test"}
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


# Budgets over the committed build, so its costs cannot creep back unseen (a phone on the home network fetches,
# parses and runs every byte of the first load before a page shows). Each limit is about a tenth over the build
# of 27 Nov 2026 (gzip at level 9): first load 315,906 B in 38 files, the largest later script
# 52,922 B (the Settings page), the whole build 2,509,292 B in 150 files, 134 scripts. Raise one only with the
# reason in the commit: what grew, and why it is worth it.
FIRST_LOAD_GZIP = 345_000
LATER_SCRIPT_GZIP = 58_000
BUILD_BYTES = 2_750_000
SCRIPTS = 147

#: A static import between chunks: ``import{a as b}from"./x.js"``, ``import"./x.js"``, ``export{a}from"./x.js"``.
#: A lazy ``import("./x.js")`` is not one: that chunk loads when its page or part is first used.
_STATIC = re.compile(r"""(?:\bimport|\bexport)\s*(?:[\w*{}\s,$]+?\s*from\s*)?["'](\./[^"'/]+\.js)["']""")
#: main.tsx awaits ``import("./App")`` before anything shows, so the App chunk and the files the build preloads
#: with it (their indices in the entry's ``__vite__mapDeps`` list, ``m.f``) are part of every first load too.
_APP = re.compile(
    r"""import\(\s*[`"'](\./App-[^`"'/]+\.js)[`"']\s*\)[\s\S]{0,120}?__vite__mapDeps\(\[([\d,]*)\]\)"""
)
_PRELOADS = re.compile(r"m\.f=(\[[^\]]*\])")


def _gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))


def _first_load() -> set[str]:
    """The build's files a first visit loads before any page shows (paths under the build, ``assets/x.js``):
    what index.html names, the App chunk main.tsx waits for with its preloads, and their static imports."""
    html = (DIST / "index.html").read_text(encoding="utf-8")
    queue = re.findall(r"""(?:src|href)="/?(assets/[^"]+\.(?:js|css))\"""", html)
    assert queue, "index.html names no script"
    entry = (DIST / queue[0]).read_text(encoding="utf-8")
    app = _APP.search(entry)
    preloads = _PRELOADS.search(entry)
    assert app and preloads, "the entry no longer waits for the App chunk: count the first load anew"
    listed = json.loads(preloads.group(1))
    queue += [f"assets/{app.group(1)[2:]}", *(listed[int(i)] for i in app.group(2).split(",") if i)]
    seen: set[str] = set()
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        if name.endswith(".js"):
            text = (DIST / name).read_text(encoding="utf-8")
            queue += [f"assets/{spec[2:]}" for spec in _STATIC.findall(text)]
    missing = [name for name in seen if not (DIST / name).is_file()]
    assert not missing, missing
    return seen


def test_the_first_load_stays_within_its_budget() -> None:
    first = _first_load()
    assert len(first) > 10, sorted(first)
    size = sum(_gzip_size(DIST / name) for name in first)
    assert size <= FIRST_LOAD_GZIP, f"first load {size} B gzip in {len(first)} files"


def test_no_later_script_is_over_its_budget() -> None:
    first = _first_load()
    later = {
        path.relative_to(DIST).as_posix(): _gzip_size(path)
        for path in (DIST / "assets").glob("*.js")
        if path.relative_to(DIST).as_posix() not in first
    }
    assert later, "every script is in the first load"
    name, size = max(later.items(), key=lambda item: item[1])
    assert size <= LATER_SCRIPT_GZIP, f"{name}: {size} B gzip"


def test_the_whole_build_stays_within_its_budget() -> None:
    files = _built_files()
    size = sum(path.stat().st_size for path in files)
    scripts = [path for path in files if path.suffix == ".js"]
    assert size <= BUILD_BYTES, f"{size} B in {len(files)} files"
    assert len(scripts) <= SCRIPTS, len(scripts)
