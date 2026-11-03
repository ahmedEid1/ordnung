"""evals/law: sections of German federal statutes on time limits, service and notice periods, as plain text, for
whoever writes or checks the benchmark's labels. Each file is listed in evals/law/SOURCES.md with the statute, its
sections, the address it was taken from, the day it was retrieved and its sha256, so a changed, added or missing
byte shows here."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAW = ROOT / "evals" / "law"
SITE = "https://www.gesetze-im-internet.de/"
#: The statutes the folder holds, one file each.
FILES = {
    "bgb.txt",
    "ao.txt",
    "egao.txt",
    "vwvfg.txt",
    "sgb_10.txt",
    "sgg.txt",
    "owig.txt",
    "stpo.txt",
    "zpo.txt",
    "kschg.txt",
    "tkg.txt",
    "enwg.txt",
}
ROW = re.compile(
    r"^\| `(?P<file>[^`]+)` \| (?P<statute>[^|]+?) \| (?P<sections>[^|]+?) \| (?P<url>[^|\s]+) "
    r"\| (?P<day>[^|\s]+) \| `(?P<sha256>[^`]+)` \|$"
)
SECTIONS = re.compile(r"^(?P<article>Art \d+ )?§§? (?P<numbers>.+)$")
NUMBER = re.compile(r"^\d+[a-z]*$")
HEADING = re.compile(r"^(?:Art \d+ )?§ \d+[a-z]*(?= |$)")


@dataclass(frozen=True)
class Row:
    file: str
    statute: str
    sections: str
    url: str
    day: str
    sha256: str


def rows(folder: Path) -> list[Row]:
    """The table of SOURCES.md: one row per text file."""
    text = (folder / "SOURCES.md").read_text(encoding="utf-8")
    return [Row(**match.groupdict()) for line in text.splitlines() if (match := ROW.match(line))]


def listed_sections(cell: str) -> list[str] | None:
    """'§§ 186–188, 309' -> ['§ 186', '§ 187', '§ 188', '§ 309']; 'Art 97 § 1' -> ['Art 97 § 1']; None if unreadable."""
    match = SECTIONS.match(cell)
    if not match:
        return None
    prefix = match["article"] or ""
    out: list[str] = []
    for token in match["numbers"].split(", "):
        first, dash, last = token.partition("–")
        if dash and first.isdigit() and last.isdigit() and int(first) < int(last):
            out += [f"{prefix}§ {n}" for n in range(int(first), int(last) + 1)]
        elif not dash and NUMBER.match(token):
            out.append(f"{prefix}§ {token}")
        else:
            return None
    return out


def headings(text: str) -> list[str]:
    """The section ids of a text file: each heading stands alone between two blank lines."""
    lines = text.split("\n")
    found = []
    for before, line, after in zip(lines, lines[1:], lines[2:]):
        match = HEADING.match(line)
        if before == "" and after == "" and match:
            found.append(match[0])
    return found


def problems(folder: Path) -> list[str]:
    """Everything that keeps folder/*.txt from matching folder/SOURCES.md (an empty list when they match)."""
    table = rows(folder)
    out: list[str] = []
    listed = [row.file for row in table]
    on_disk = sorted(path.name for path in folder.iterdir() if path.name != "SOURCES.md")
    out += [f"{name}: listed twice" for name in sorted({n for n in listed if listed.count(n) > 1})]
    out += [f"{name}: not listed in SOURCES.md" for name in on_disk if name not in listed]
    out += [f"{name}: listed in SOURCES.md but missing" for name in sorted(set(listed) - set(on_disk))]
    for row in table:
        path = folder / row.file
        if not path.is_file():
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row.sha256:
            out.append(f"{row.file}: sha256 is not the one in SOURCES.md")
        if not row.url.startswith(SITE):
            out.append(f"{row.file}: source is not on {SITE}")
        try:
            day = dt.date.fromisoformat(row.day)
        except ValueError:
            out.append(f"{row.file}: retrieval day {row.day!r} is not a date")
        else:
            if day > dt.date.today():
                out.append(f"{row.file}: retrieval day {row.day} is in the future")
        text = data.decode("utf-8")
        if text.split("\n", 1)[0] != row.statute:
            out.append(f"{row.file}: first line is not the statute named in SOURCES.md")
        wanted = listed_sections(row.sections)
        if wanted is None:
            out.append(f"{row.file}: sections {row.sections!r} can't be read")
        elif headings(text) != wanted:
            out.append(f"{row.file}: sections in the file are not the ones SOURCES.md lists")
    return out


def test_every_text_matches_its_row_in_sources_md() -> None:
    assert {row.file for row in rows(LAW)} == FILES
    assert problems(LAW) == []


def _flip_a_byte(folder: Path) -> None:
    path = folder / "bgb.txt"
    data = bytearray(path.read_bytes())
    data[-2] = ord("x") if data[-2] != ord("x") else ord("y")
    path.write_bytes(bytes(data))


def _drop_a_section(folder: Path) -> None:
    """KSchG without its last section, with SOURCES.md's sha256 updated to match: only the section list catches it."""
    path = folder / "kschg.txt"
    old = path.read_bytes()
    new = old.split(b"\n\n\xc2\xa7 7", 1)[0] + b"\n"
    path.write_bytes(new)
    sources = folder / "SOURCES.md"
    text = sources.read_text(encoding="utf-8")
    sources.write_text(
        text.replace(hashlib.sha256(old).hexdigest(), hashlib.sha256(new).hexdigest()), encoding="utf-8"
    )


def _edit_sources(old: str, new: str):
    def edit(folder: Path) -> None:
        sources = folder / "SOURCES.md"
        text = sources.read_text(encoding="utf-8")
        assert old in text
        sources.write_text(text.replace(old, new, 1), encoding="utf-8")

    return edit


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_flip_a_byte, "bgb.txt: sha256 is not the one in SOURCES.md"),
        (
            lambda folder: (folder / "extra.txt").write_text("§ 1\n", encoding="utf-8"),
            "not listed in SOURCES.md",
        ),
        (lambda folder: (folder / "kschg.txt").unlink(), "kschg.txt: listed in SOURCES.md but missing"),
        (_drop_a_section, "kschg.txt: sections in the file are not the ones SOURCES.md lists"),
        (
            _edit_sources("https://www.gesetze-im-internet.de/stpo/", "https://example.org/stpo/"),
            "stpo.txt: source",
        ),
        (_edit_sources("| Kündigungsschutzgesetz (KSchG) |", "| KSchG |"), "kschg.txt: first line is not"),
        (_edit_sources("|---|\n", "|---|\n| `sgg.txt` | x | § 1 | x | x | `x` |\n"), "sgg.txt: listed twice"),
        (_edit_sources("| `tkg.txt` |", "| `tkg.txt` |"), None),
    ],
    ids=[
        "changed-byte",
        "unlisted-file",
        "missing-file",
        "dropped-section",
        "other-site",
        "other-statute",
        "listed-twice",
        "unchanged",
    ],
)
def test_a_change_to_the_folder_is_caught(tmp_path: Path, mutate, expected: str | None) -> None:
    folder = tmp_path / "law"
    shutil.copytree(LAW, folder)
    mutate(folder)
    found = problems(folder)
    if expected is None:
        assert found == []
    else:
        assert any(expected in problem for problem in found), found


def test_a_retrieval_day_must_be_a_past_date(tmp_path: Path) -> None:
    folder = tmp_path / "law"
    shutil.copytree(LAW, folder)
    sources = folder / "SOURCES.md"
    text = sources.read_text(encoding="utf-8")
    (row,) = [r for r in rows(folder) if r.file == "zpo.txt"]
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    line = next(line for line in text.splitlines() if line.startswith("| `zpo.txt` |"))
    sources.write_text(
        text.replace(line, line.replace(f"| {row.day} |", f"| {tomorrow} |")), encoding="utf-8"
    )
    assert "zpo.txt: retrieval day " + tomorrow + " is in the future" in problems(folder)
    sources.write_text(text.replace(line, line.replace(f"| {row.day} |", "| 2026-13-01 |")), encoding="utf-8")
    assert "zpo.txt: retrieval day '2026-13-01' is not a date" in problems(folder)


def test_the_section_lists_read_ranges_letters_and_articles() -> None:
    assert listed_sections("§§ 186–188, 309, 558a") == ["§ 186", "§ 187", "§ 188", "§ 309", "§ 558a"]
    assert listed_sections("§ 43") == ["§ 43"]
    assert listed_sections("Art 97 § 1") == ["Art 97 § 1"]
    assert listed_sections("§§ 558–558b") is None  # a range with letters is ambiguous: list them one by one
    assert listed_sections("BGB 187") is None


@pytest.mark.parametrize("name", sorted(FILES))
def test_each_text_is_plain_utf8_lines_that_hash_the_same_everywhere(name: str) -> None:
    """UTF-8 in NFC, LF line ends, no tab, no trailing space, no empty runs, one final newline: the bytes, and so
    the sha256, are the same on every system (.gitattributes checks every file out byte for byte)."""
    data = (LAW / name).read_bytes()
    text = data.decode("utf-8")
    assert unicodedata.normalize("NFC", text) == text
    assert "\r" not in text and "\t" not in text and " " not in text
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "\n\n\n" not in text
    lines = text.split("\n")[:-1]
    assert all(line == line.rstrip() for line in lines)
    assert all(ch.isprintable() for line in lines for ch in line)


def test_the_folder_names_no_software_and_no_file_of_this_repository() -> None:
    """The texts and SOURCES.md are statute text and its provenance only: they name no program and point at no
    file of this repository, so the folder can be handed to a reader on its own."""
    for path in sorted(LAW.iterdir()):
        text = re.sub(r"öffentliche[nrs]?\s+Ordnung", "", path.read_text(encoding="utf-8"))  # statute German
        assert not re.search(r"(?<![^\W\d_])ordnung(?![^\W\d_])", text, re.IGNORECASE), path.name
        assert not re.search(r"\b(?:src|evals|docs|tests|scripts)/|\.py\b", text), path.name
