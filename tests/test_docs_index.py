"""The docs' indexes and cross-references resolve.

- ``docs/decisions/README.md`` lists every ADR, with its title and status as the ADR itself gives them, and every
  file it lists exists.
- Every SPEC section the repository cites by number (``SPEC §21``, ``SPEC §9, §21``, ``SPEC.md § 8.1``), and every
  paragraph it cites by name (``SPEC § 21 "Holidays"``, ``SPEC §GiroCode``), is in ``docs/SPEC.md``; so are the
  sections SPEC cites in itself.
- Every path and name in ``docs/architecture.md``'s section *The web app* exists.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "decisions"
INDEX = DECISIONS / "README.md"
SPEC = ROOT / "docs" / "SPEC.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"

#: An ADR's file name: four digits, then the title in words.
_ADR_FILE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")


def _adrs() -> list[Path]:
    return sorted(path for path in DECISIONS.iterdir() if _ADR_FILE.match(path.name))


def _index_rows() -> dict[str, str]:
    """The index's table rows, by the file each links to."""
    assert INDEX.is_file(), "docs/decisions/README.md, the index of the decisions, is missing"
    rows: dict[str, str] = {}
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        # the row's own ADR, in its first column (a row may link others too)
        first = re.match(r"^\| \[\d{4}\]\(([^)#\s]+)\) \|", line)
        if first and _ADR_FILE.match(first[1]):
            assert first[1] not in rows, f"{first[1]} is listed twice"
            rows[first[1]] = line
    return rows


def _title_and_status(adr: Path) -> tuple[str, str]:
    """An ADR's title (its first heading, after the number) and its status word (``accepted``, …)."""
    lines = adr.read_text(encoding="utf-8").splitlines()
    heading = re.match(rf"^# ADR {adr.name[:4]} — (.+)$", lines[0])
    assert heading, f"{adr.name}: the first line is not '# ADR {adr.name[:4]} — <title>'"
    status = re.search(r"\*\*Status:\*\* (\w+)", "\n".join(lines[:4]))
    assert status, f"{adr.name}: no **Status:** line at the top"
    return heading[1], status[1]


def test_the_decisions_index_lists_every_adr() -> None:
    rows = _index_rows()
    missing = [adr.name for adr in _adrs() if adr.name not in rows]
    assert not missing, f"not in docs/decisions/README.md: {missing}"


def test_every_file_the_decisions_index_links_exists() -> None:
    assert INDEX.is_file(), "docs/decisions/README.md, the index of the decisions, is missing"
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)\s]*)?\)", INDEX.read_text(encoding="utf-8")):
        if re.match(r"^[a-z]+:", target):
            continue
        assert (DECISIONS / target).exists(), f"docs/decisions/README.md links {target}, which doesn't exist"


def test_the_decisions_index_gives_each_adr_its_own_title_and_status() -> None:
    rows = _index_rows()
    for adr in _adrs():
        title, status = _title_and_status(adr)
        row = rows[adr.name]
        assert f"[{adr.name[:4]}]({adr.name})" in row, adr.name
        assert f"| {title} |" in row, f"{adr.name}: the index doesn't give its title '{title}'"
        assert re.search(rf"\| {status}\b", row), f"{adr.name}: the index doesn't give its status '{status}'"


# --------------------------------------------------------------------------------------------------
# SPEC's sections, as the repository cites them
# --------------------------------------------------------------------------------------------------

#: The folders whose files cite SPEC.
_CITING = ("src", "tests", "scripts", "web", "evals", "docs")
#: Never searched: generated or third-party files, the benchmark's letters, its recordings and results.
_NOT_SEARCHED = (
    "src/ordnung/web/dist",
    "evals/dataset",
    "evals/recorded",
    "evals/results",
    "web/node_modules",
    "web/dist",
    "web/test-results",
    "web/playwright-report",
)
_TEXT = frozenset(".py .ts .tsx .mjs .js .md .json .yml .yaml .toml .sh .css .html".split())
#: A section number: ``21``, ``12b``, ``8.1``, ``14.10``.
_NUMBER = r"\d+[a-z]?(?:\.\d+)?"
#: ``SPEC``, ``SPEC.md`` or ``docs/SPEC.md``, a few separators (comment marks and line breaks too), the first
#: ``§ N`` and more joined to it (``SPEC §9, §21``, ``SPEC §6/§21``); or a paragraph by name (``SPEC §GiroCode``).
_SPEC_CITATION = re.compile(
    r"SPEC(?:\.md)?[\s#/*'\"(`:,\-–—]{0,12}§\s?(?:(?P<numbers>"
    + _NUMBER
    + r"(?:\s*(?:,|/|and|&|;|or)\s*(?:SPEC\s*)?§\s?"
    + _NUMBER
    + r")*)(?:\s+[\"“](?P<paragraph>[^\"”\n]{2,40})[\"”])?|(?P<named>[A-Z][A-Za-z]+))"
)
#: SPEC's own ``§ N``, not a law's (``§ 193 BGB``, ``§ 556 Abs. 3 BGB``) nor another document's
#: (``deadline-rules.md`` § 5).
_SPEC_SELF = re.compile(r"(?<![§\w\"])§\s?(" + _NUMBER + r")(?!\d)")
_LAW_AFTER = re.compile(
    r"^(?:\(\d+\))*(?:\s*(?:Abs\.|Nr\.|S\.|Satz|Hs\.|ff\.|lit\.|Alt\.)\s*[\dIVX]+[a-z]?)*\s*[A-Z][A-Za-z]*[A-Z]"
)
_OTHER_DOC_BEFORE = re.compile(r"(?:deadline-rules|evals|privacy|architecture)\.md`?\s*$|deadline-rules\s*$")


def _citing_files() -> Iterator[Path]:
    for top in _CITING:
        for folder, subfolders, files in os.walk(ROOT / top):
            here = Path(folder)
            relative = here.relative_to(ROOT).as_posix()
            subfolders[:] = [
                name
                for name in subfolders
                if f"{relative}/{name}" not in _NOT_SEARCHED and name not in {"__pycache__", "node_modules"}
            ]
            for name in files:
                if Path(name).suffix in _TEXT:
                    yield here / name


@cache
def _spec_sections() -> dict[str, str]:
    """SPEC's numbered sections (``## 12b. …``, ``### 8.1 …``) and each one's text, by number."""
    text = SPEC.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    heading = re.compile(r"^(#{2,3}) (\d+[a-z]?(?:\.\d+)?)\.? ", re.M)
    found = list(heading.finditer(text))
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        sections[match[2]] = text[match.end() : end]
    return sections


def _resolves(number: str) -> bool:
    """A section number is SPEC's: a heading, or a numbered item of its section (§14's pages: ``§14.10``)."""
    sections = _spec_sections()
    if number in sections:
        return True
    top, _, item = number.partition(".")
    return bool(item) and top in sections and re.search(rf"^{item}\. ", sections[top], re.M) is not None


def _paragraph(number: str | None, name: str) -> bool:
    """A paragraph SPEC leads in bold (``**Holidays.**``, ``**GiroCode (EPC-QR).**``), in that section if given."""
    text = _spec_sections()[number] if number else SPEC.read_text(encoding="utf-8")
    return f"**{name}" in text


def spec_citations() -> list[tuple[str, int, str]]:
    """Every SPEC section or paragraph the repository cites: ``(file, line, what)``."""
    found: list[tuple[str, int, str]] = []
    for path in _citing_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        name = path.relative_to(ROOT).as_posix()
        for match in _SPEC_CITATION.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if match["named"]:
                found.append((name, line, f"§{match['named']}"))
                continue
            numbers = re.findall(_NUMBER, re.sub(r"SPEC", "", match["numbers"]))
            found.extend((name, line, f"§{number}") for number in numbers)
            if match["paragraph"]:
                found.append((name, line, f'§{numbers[-1]} "{match["paragraph"]}"'))
        if name == "docs/SPEC.md":
            for match in _SPEC_SELF.finditer(text):
                after = text[match.end() : match.end() + 16]
                before = text[max(0, match.start() - 24) : match.start()]
                top = int(re.match(r"\d+", match[1])[0])  # type: ignore[index]
                if _LAW_AFTER.match(after) or _OTHER_DOC_BEFORE.search(before) or top > 21:
                    continue
                found.append((name, text.count("\n", 0, match.start()) + 1, f"§{match[1]}"))
    return found


def test_every_spec_section_the_repository_cites_is_in_spec() -> None:
    """Code, tests and docs point into SPEC by section number, so a section keeps its number: one SPEC no longer
    has, or a paragraph name no section leads with, fails here with where it is cited."""
    cited = spec_citations()
    assert len(cited) > 250  # the search still finds them (about 280 in 0.4.0)
    broken = []
    for name, line, what in cited:
        named = re.fullmatch(
            r"§(?:(?P<number>" + _NUMBER + r') "(?P<paragraph>[^"]+)"|(?P<named>[A-Z]\w+))', what
        )
        if named and named["paragraph"]:
            ok = _resolves(named["number"]) and _paragraph(named["number"], named["paragraph"])
        elif named and named["named"]:
            ok = _paragraph(None, named["named"])
        else:
            ok = _resolves(what.removeprefix("§"))
        if not ok:
            broken.append(f"{name}:{line} {what}")
    assert not broken, "SPEC has no such section or paragraph:\n" + "\n".join(broken)


# --------------------------------------------------------------------------------------------------
# docs/architecture.md, The web app
# --------------------------------------------------------------------------------------------------


def _web_section() -> str:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "\n## The web app\n" in text, "docs/architecture.md has no section 'The web app'"
    return text.split("\n## The web app\n", 1)[1].split("\n## ", 1)[0]


@cache
def _web_sources() -> str:
    """Every source and config file of the web app, and the Makefile, as one text: where a name must be."""
    texts = [(ROOT / "Makefile").read_text(encoding="utf-8")]
    for folder in ("src", "e2e", "scripts"):
        for path in sorted((ROOT / "web" / folder).rglob("*")):
            if path.suffix in {".ts", ".tsx", ".mjs", ".css"} and path.is_file():
                texts.append(path.read_text(encoding="utf-8"))
    texts.extend(path.read_text(encoding="utf-8") for path in sorted((ROOT / "web").glob("*.[jt]s*")))
    texts.append((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    return "\n".join(texts)


def _exists(path: str) -> bool:
    """A path from the repository's root; a ``*`` matches as in a shell."""
    if "*" not in path:
        return (ROOT / path.rstrip("/")).exists()
    folder, _, pattern = path.rpartition("/")
    return any(fnmatch.fnmatch(entry.name, pattern) for entry in (ROOT / folder).iterdir())


def test_every_path_and_name_the_web_app_section_gives_exists() -> None:
    """*The web app*: a path is the repository's (from its root), ``make X`` a Makefile target, ``ordnung X`` a
    command, ``/dev/ui`` a route of the router, ``/api/…`` an API path, and any other name (``qk``,
    ``VITE_STATIC_DEMO=1``) is in the web app's sources."""
    from typer.testing import CliRunner

    from ordnung.cli import app

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    router = (ROOT / "web" / "src" / "app" / "router.tsx").read_text(encoding="utf-8")
    openapi = (ROOT / "web" / "openapi.json").read_text(encoding="utf-8")
    names = re.findall(r"`([^`\n]+)`", _web_section())
    assert len(names) > 20, names
    for name in names:
        if name.startswith("make "):
            assert re.search(rf"^{re.escape(name.removeprefix('make '))}:", makefile, re.M), name
        elif name.startswith("ordnung "):
            command = name.split()[1]
            result = CliRunner().invoke(app, [command, "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
            assert result.exit_code == 0, name
        elif name.startswith("/api/"):
            assert f'"{name.rstrip("*").rstrip("/")}' in openapi, name
        elif name.startswith("/"):
            assert f'path: "{name.lstrip("/")}"' in router, name
        elif "/" in name or re.search(r"\.(py|ts|tsx|mjs|json|md)$", name):
            assert _exists(name), name
        else:
            word = re.split(r"[=?(]", name.lstrip("?"))[0] or name
            assert word in _web_sources(), name
