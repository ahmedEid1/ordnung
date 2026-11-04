"""evals/law: sections of German federal statutes on time limits, service and notice periods, and each Land's rule
on when an authority's written decision counts as delivered, as plain text, for whoever writes or checks the
benchmark's labels. Each file is listed in evals/law/SOURCES.md with the statute, its sections, the address it was
taken from, the day it was retrieved and its sha256 (laender.txt: one row per Land, with the sha256 of its block), so
a changed, added or missing byte shows here."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
import unicodedata
import urllib.parse
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
    "vwgo.txt",
    "egbgb.txt",
}
#: The Länder's rules, one block per Land; listed in SOURCES.md's own table, not in the federal one.
LAENDER_FILE = "laender.txt"
LAENDER_TITLE = "Verwaltungsverfahrensrecht der Länder"
#: The sixteen Länder, in the order laender.txt holds their blocks.
LAENDER = (
    "Baden-Württemberg",
    "Bayern",
    "Berlin",
    "Brandenburg",
    "Bremen",
    "Hamburg",
    "Hessen",
    "Mecklenburg-Vorpommern",
    "Niedersachsen",
    "Nordrhein-Westfalen",
    "Rheinland-Pfalz",
    "Saarland",
    "Sachsen",
    "Sachsen-Anhalt",
    "Schleswig-Holstein",
    "Thüringen",
)
#: Each Land's official legal portal: every address a Land's row names is on its host.
PORTALS = {
    "Baden-Württemberg": "www.landesrecht-bw.de",
    "Bayern": "www.gesetze-bayern.de",
    "Berlin": "gesetze.berlin.de",
    "Brandenburg": "bravors.brandenburg.de",
    "Bremen": "www.transparenz.bremen.de",
    "Hamburg": "www.landesrecht-hamburg.de",
    "Hessen": "www.rv.hessenrecht.hessen.de",
    "Mecklenburg-Vorpommern": "www.landesrecht-mv.de",
    "Niedersachsen": "voris.wolterskluwer-online.de",
    "Nordrhein-Westfalen": "recht.nrw.de",
    "Rheinland-Pfalz": "landesrecht.rlp.de",
    "Saarland": "recht.saarland.de",
    "Sachsen": "www.revosax.sachsen.de",
    "Sachsen-Anhalt": "www.landesrecht.sachsen-anhalt.de",
    "Schleswig-Holstein": "www.gesetze-rechtsprechung.sh.juris.de",
    "Thüringen": "landesrecht.thueringen.de",
}
#: The gap: Länder whose portal could not be fetched. Their block holds only NOT_RETRIEVED_LINE, and SOURCES.md says
#: so; nothing fills it from memory or from another source.
NOT_RETRIEVED = {
    "Berlin",
    "Bremen",
    "Hamburg",
    "Hessen",
    "Mecklenburg-Vorpommern",
    "Rheinland-Pfalz",
    "Saarland",
    "Sachsen-Anhalt",
    "Schleswig-Holstein",
    "Thüringen",
}
NOT_RETRIEVED_LINE = "Not retrieved (see SOURCES.md)."
#: Sections the labels' derivations and conventions cite for a period (evals/gen, evals/generate.py): the readers who
#: write and check the final labels date them from these texts alone.
CITED = {
    "bgb.txt": ("§ 187", "§ 188", "§ 193", "§ 309", "§ 622", "§ 623"),
    "vwgo.txt": ("§ 57", "§ 58", "§ 68", "§ 70", "§ 74"),
    "tkg.txt": ("§ 56", "§ 57"),
    "vwvfg.txt": ("§ 31", "§ 41"),
    "ao.txt": ("§ 108", "§ 122", "§ 355"),
    "sgb_10.txt": ("§ 26", "§ 37"),
    "owig.txt": ("§ 46", "§ 67"),
    "zpo.txt": ("§ 222",),
}
ROW = re.compile(
    r"^\| `(?P<file>[^`]+)` \| (?P<statute>[^|]+?) \| (?P<sections>[^|]+?) \| (?P<url>[^|\s]+) "
    r"\| (?P<day>[^|\s]+) \| `(?P<sha256>[^`]+)` \|$"
)
SECTIONS = re.compile(r"^(?P<article>Art \d+[a-z]* )?§§? (?P<numbers>.+)$")
NUMBER = re.compile(r"^\d+[a-z]*$")
ANNEX = re.compile(r"^Anlage \d+[a-z]*$")
HEADING = re.compile(r"^(?:(?:Art \d+[a-z]* )?§ \d+[a-z]*|Anlage \d+[a-z]*)(?= |$)")
#: A Land's provision: "§ 41 Bekanntgabe des Verwaltungsaktes", Bavaria's "Art. 41 ...", or a number alone.
LAND_HEADING = re.compile(r"^(?:§|Art\.) \d+[a-z]*(?= |$)")
LAND_PROVISIONS = re.compile(r"^(?P<kind>§§?|Art\.) (?P<numbers>\d+[a-z]*(?:, \d+[a-z]*)*)$")
LAND_ROW = re.compile(
    r"^\| (?P<land>[^|`]+?) \| (?P<statute>[^|]+?) \| (?P<provisions>[^|]+?) \| (?P<urls>[^|]+?) "
    r"\| (?P<day>[^|\s]+) \| `(?P<sha256>[^`]+)` \|$"
)
FILE_SHA = re.compile(r"^sha256 of `laender\.txt`: `(?P<sha256>[0-9a-f]{64})`$", re.MULTILINE)


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
        elif ANNEX.match(token):
            out.append(token)
        else:
            return None
    return out


def headings(text: str, pattern: re.Pattern[str] = HEADING) -> list[str]:
    """The section ids of a text file: each heading stands alone between two blank lines. The lines of a footnote
    ("Fußnote", a blank line, then its lines up to the next blank line) are never headings, even one that starts
    with a section number."""
    lines = text.split("\n")
    found = []
    i = 1
    while i < len(lines) - 1:
        if lines[i] == "Fußnote" and lines[i - 1] == "" and lines[i + 1] == "":
            i += 2
            while i < len(lines) and lines[i] != "":
                i += 1
            continue
        match = pattern.match(lines[i])
        if lines[i - 1] == "" and lines[i + 1] == "" and match:
            found.append(match[0])
        i += 1
    return found


@dataclass(frozen=True)
class LandRow:
    land: str
    statute: str
    provisions: str
    urls: str
    day: str
    sha256: str


def land_rows(folder: Path) -> list[LandRow]:
    """SOURCES.md's table of the Länder: one row per Land."""
    text = (folder / "SOURCES.md").read_text(encoding="utf-8")
    return [LandRow(**match.groupdict()) for line in text.splitlines() if (match := LAND_ROW.match(line))]


def land_blocks(text: str) -> list[tuple[str, str]]:
    """laender.txt as (Land, block): a block runs from a line naming a Land, after a blank line, to the line before
    the blank line that precedes the next Land's name (or to the end); each of its lines ends in a line break."""
    lines = text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")
    starts = [i for i, line in enumerate(lines) if line in LAENDER and i > 0 and lines[i - 1] == ""]
    blocks = []
    for n, start in enumerate(starts):
        end = starts[n + 1] - 1 if n + 1 < len(starts) else len(lines)
        blocks.append((lines[start], "".join(line + "\n" for line in lines[start:end])))
    return blocks


def listed_provisions(cell: str) -> list[str] | None:
    """'§§ 41, 102b' -> ['§ 41', '§ 102b']; 'Art. 41' -> ['Art. 41']; None if unreadable."""
    match = LAND_PROVISIONS.match(cell)
    if not match:
        return None
    kind = "Art." if match["kind"] == "Art." else "§"
    return [f"{kind} {number}" for number in match["numbers"].split(", ")]


def laender_problems(folder: Path) -> list[str]:
    """Everything that keeps folder/laender.txt from matching SOURCES.md's table of the Länder."""
    name = LAENDER_FILE
    path = folder / name
    if not path.is_file():
        return [f"{name}: missing"]
    data = path.read_bytes()
    text = data.decode("utf-8")
    out: list[str] = []
    found = FILE_SHA.findall((folder / "SOURCES.md").read_text(encoding="utf-8"))
    if found != [hashlib.sha256(data).hexdigest()]:
        out.append(f"{name}: sha256 is not the one in SOURCES.md")
    if text.split("\n", 1)[0] != LAENDER_TITLE:
        out.append(f"{name}: first line is not {LAENDER_TITLE!r}")
    blocks = dict(land_blocks(text))
    if [land for land, _ in land_blocks(text)] != list(LAENDER):
        out.append(f"{name}: the Länder are not the sixteen, each once, in order")
    table = {row.land: row for row in land_rows(folder)}
    if sorted(table) != sorted(LAENDER) or len(land_rows(folder)) != len(LAENDER):
        out.append(f"{name}: SOURCES.md does not list each of the sixteen Länder once")
    for land in LAENDER:
        row, block = table.get(land), blocks.get(land)
        if row is None or block is None:
            continue
        lines = block.split("\n")[:-1]
        if hashlib.sha256(block.encode("utf-8")).hexdigest() != row.sha256:
            out.append(f"{name}: {land}: sha256 is not the one in SOURCES.md")
        hosts = {urllib.parse.urlsplit(url).netloc for url in row.urls.split(", ")}
        if hosts != {PORTALS[land]} or not all(url.startswith("https://") for url in row.urls.split(", ")):
            out.append(f"{name}: {land}: source is not on {PORTALS[land]}")
        try:
            day = dt.date.fromisoformat(row.day)
        except ValueError:
            out.append(f"{name}: {land}: day {row.day!r} is not a date")
        else:
            if day > dt.date.today():
                out.append(f"{name}: {land}: day {row.day} is in the future")
        missing = lines == [land, NOT_RETRIEVED_LINE]
        if missing != (row.statute == "not retrieved"):
            out.append(f"{name}: {land}: SOURCES.md and the file disagree on whether it was retrieved")
            continue
        if missing:
            if row.provisions != "–":
                out.append(f"{name}: {land}: a Land not retrieved lists provisions")
            continue
        if len(lines) < 2 or lines[1] != row.statute:
            out.append(f"{name}: {land}: the line after the Land is not the statute named in SOURCES.md")
        wanted = listed_provisions(row.provisions)
        got = headings(block, LAND_HEADING)
        if wanted is None:
            out.append(f"{name}: {land}: provisions {row.provisions!r} can't be read")
        elif not got or got != wanted:
            out.append(f"{name}: {land}: provisions in the file are not the ones SOURCES.md lists")
    return out


def problems(folder: Path) -> list[str]:
    """Everything that keeps folder/*.txt from matching folder/SOURCES.md (an empty list when they match)."""
    table = rows(folder)
    out: list[str] = []
    listed = [row.file for row in table] + [LAENDER_FILE] * len(
        FILE_SHA.findall((folder / "SOURCES.md").read_text("utf-8"))
    )
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
    return out + laender_problems(folder)


def test_every_text_matches_its_row_in_sources_md() -> None:
    assert {row.file for row in rows(LAW)} == FILES
    assert problems(LAW) == []


def test_every_land_has_a_block_or_is_listed_as_not_retrieved() -> None:
    """laender.txt holds one block per Land, in order: the Land's rule as its portal gives it, or the one line that
    says it was not retrieved; SOURCES.md has a row for each, naming its official portal and the block's sha256."""
    blocks = land_blocks((LAW / LAENDER_FILE).read_text(encoding="utf-8"))
    assert [land for land, _ in blocks] == list(LAENDER)
    assert sorted(row.land for row in land_rows(LAW)) == sorted(LAENDER)
    assert laender_problems(LAW) == []


def test_the_laender_not_retrieved_are_the_known_gap() -> None:
    """The gap, listed: the Länder whose portal could not be fetched. A Land filled in later leaves this list."""
    blocks = land_blocks((LAW / LAENDER_FILE).read_text(encoding="utf-8"))
    missing = {land for land, block in blocks if block == f"{land}\n{NOT_RETRIEVED_LINE}\n"}
    assert missing == NOT_RETRIEVED
    assert {row.land for row in land_rows(LAW) if row.statute == "not retrieved"} == NOT_RETRIEVED


def test_each_retrieved_land_states_when_its_authorities_letters_count_as_delivered() -> None:
    """A retrieved block holds either the Land's own text of the federal § 41 (a provision titled 'Bekanntgabe des
    Verwaltungsakt(e)s' with a paragraph (2)) or a provision that applies the federal Verwaltungsverfahrensgesetz."""
    for land, block in land_blocks((LAW / LAENDER_FILE).read_text(encoding="utf-8")):
        if land in NOT_RETRIEVED:
            continue
        own = re.search(
            r"^(?:§|Art\.) \d+[a-z]* Bekanntgabe des Verwaltungsakte?s\n\n(?:.*\n)*?\(2\) ", block, re.M
        )
        applies = re.search(r"Verwaltungsverfahrensgesetz(?:es)?\b", block.split("\n\n", 1)[1])
        assert own or applies, land


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


def _land_row(folder: Path, land: str) -> str:
    text = (folder / "SOURCES.md").read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if line.startswith(f"| {land} |"))


def _resync_file_sha(folder: Path, old: bytes, new: bytes) -> None:
    sources = folder / "SOURCES.md"
    text = sources.read_text(encoding="utf-8")
    sources.write_text(
        text.replace(hashlib.sha256(old).hexdigest(), hashlib.sha256(new).hexdigest()), encoding="utf-8"
    )


def _flip_a_land_byte(folder: Path) -> None:
    """One letter of Bavaria's block changed, with the whole file's sha256 updated: only the block's sha256 catches
    it."""
    path = folder / "laender.txt"
    old = path.read_bytes()
    text = old.decode("utf-8")
    (block,) = [b for land, b in land_blocks(text) if land == "Bayern"]
    changed = block.replace("vierten", "dritten", 1) if "vierten" in block else block.replace("e", "a", 1)
    new = text.replace(block, changed, 1).encode("utf-8")
    path.write_bytes(new)
    _resync_file_sha(folder, old, new)


def _drop_a_land(folder: Path) -> None:
    path = folder / "laender.txt"
    old = path.read_bytes()
    text = old.decode("utf-8")
    (block,) = [b for land, b in land_blocks(text) if land == "Bremen"]
    new = text.replace("\n" + block, "", 1).encode("utf-8")
    path.write_bytes(new)
    _resync_file_sha(folder, old, new)


def _move_a_land_source(folder: Path) -> None:
    sources = folder / "SOURCES.md"
    line = _land_row(folder, "Bayern")
    moved = line.replace("https://www.gesetze-bayern.de/", "https://example.org/")
    sources.write_text(sources.read_text(encoding="utf-8").replace(line, moved), encoding="utf-8")


def _claim_a_land_not_retrieved(folder: Path) -> None:
    sources = folder / "SOURCES.md"
    row = next(r for r in land_rows(folder) if r.land == "Bayern")
    line = _land_row(folder, "Bayern")
    claimed = line.replace(f"| {row.statute} | {row.provisions} |", "| not retrieved | – |")
    sources.write_text(sources.read_text(encoding="utf-8").replace(line, claimed), encoding="utf-8")


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
        (_flip_a_land_byte, "laender.txt: Bayern: sha256 is not the one in SOURCES.md"),
        (_drop_a_land, "laender.txt: the Länder are not the sixteen, each once, in order"),
        (_move_a_land_source, "laender.txt: Bayern: source is not on www.gesetze-bayern.de"),
        (_claim_a_land_not_retrieved, "laender.txt: Bayern: SOURCES.md and the file disagree"),
        (lambda folder: (folder / "laender.txt").unlink(), "laender.txt: missing"),
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
        "land-changed-byte",
        "land-dropped",
        "land-other-site",
        "land-not-retrieved",
        "laender-missing",
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
    assert listed_sections("Art 246a §§ 1–3, Anlage 1") == [
        "Art 246a § 1",
        "Art 246a § 2",
        "Art 246a § 3",
        "Anlage 1",
    ]
    assert listed_provisions("§§ 41, 102b") == ["§ 41", "§ 102b"] and listed_provisions("Art. 41") == [
        "Art. 41"
    ]
    assert listed_provisions("§ 1") == ["§ 1"] and listed_provisions("41") is None
    assert listed_sections("§§ 558–558b") is None  # a range with letters is ambiguous: list them one by one
    assert listed_sections("BGB 187") is None


def test_a_footnote_that_starts_with_a_section_number_is_no_heading() -> None:
    """A portal's footnote such as "§ 41 zuletzt geändert durch ..." stands alone between blank lines, like a
    heading; it belongs to the section before it."""
    text = (
        "T\n\n§ 41 Bekanntgabe\n\n(1) a\n\nFußnote\n\n§ 41 zuletzt geändert durch b.\n\n§ 97 Übergang\n\nc\n"
    )
    assert headings(text, LAND_HEADING) == ["§ 41", "§ 97"]
    assert headings("T\n\n§ 1 A\n\nFußnote\n\nx\ny\n\n§ 2\n\nz\n") == ["§ 1", "§ 2"]


@pytest.mark.parametrize("name", sorted(FILES | {LAENDER_FILE}))
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


def test_every_section_the_labels_cite_for_a_period_is_here() -> None:
    """The VwGO's Widerspruch and Klage periods, the TKG's price-change cancellation and the BGB's employment notice
    periods are cited by the labels' derivations; a reader who dates them from these texts alone needs them."""
    missing = [
        f"{name} {section}"
        for name, sections in CITED.items()
        for section in sections
        if not (LAW / name).is_file() or section not in headings((LAW / name).read_text(encoding="utf-8"))
    ]
    assert missing == []


def test_the_withdrawal_period_s_information_duty_and_its_model_are_here() -> None:
    """BGB § 356 (3) starts the withdrawal period only once the consumer is informed as EGBGB Art. 246a § 1 (2)
    requires; Anlage 1 is the model notice that meets it. A reader who dates a withdrawal period needs both."""
    bgb = (LAW / "bgb.txt").read_text(encoding="utf-8")
    assert "Artikels 246a § 1 Absatz 2" in bgb
    held = headings((LAW / "egbgb.txt").read_text(encoding="utf-8"))
    assert {"Art 246a § 1", "Anlage 1"} <= set(held)
