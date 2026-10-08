"""scripts/make_postcode_table.py: GeoNames' DE.zip in, Ordnung's postcode table out (ADR 0019), and the
committed table it wrote. The script's tests run on a tiny DE.txt written here: the real one is a download."""

from __future__ import annotations

import hashlib
import os
import random
import re
import sys
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.postcodes import TABLE_PATH

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.make_postcode_table import BuildError, build, main  # noqa: E402

DATED = (2026, 10, 8, 4, 17, 12)


def row(postcode: str, place: str, name: str, code: str, country: str = "DE") -> str:
    """One line of GeoNames' postal code file: 12 tab-separated fields."""
    return "\t".join([country, postcode, place, name, code, "", "", "", "", "48.1", "11.5", "4"]) + "\n"


#: Both admin1 series (ISO letters and GeoNames' numbers), "Land Berlin", a postcode without a Land, one in
#: two Länder, a postcode listed twice, a row of another country — and, made up for the fallback's
#: measure, a 3-digit area and a 2-digit area whose Länder disagree.
ROWS = [
    row("80331", "München", "Bayern", "BY"),
    row("80333", "München", "Bayern", "BY"),
    row("80333", "Bayerische Landesbank", "Bavaria", "02"),
    row("80335", "Allianz SE", "Bavaria", "02"),
    row("80995", "München", "Bayern", "BY"),
    row("10115", "Berlin", "Berlin", "BE"),
    row("10117", "Deutsche Bank", "Land Berlin", "16"),
    row("10315", "Neustadt", "Brandenburg", "BB"),
    row("21039", "Börnsen", "Schleswig-Holstein", "SH"),
    row("21039", "Hamburg", "Hamburg", "HH"),
    row("21031", "Hamburg", "Hamburg", "HH"),
    row("87491", "Jungholz", "", ""),
    row("6691", "Jungholz", "Tirol", "07", country="AT"),
    row("66111", "Saarbrücken", "Saarland", "SL"),
    row("66113", "Saarbrücken", "Saarland", "SL"),
    row("66119", "Neudorf", "Rheinland-Pfalz", "RP"),
    row("66280", "Neudorf", "Rheinland-Pfalz", "RP"),
]

ROWS_OUT = """\
10115\tBE
10117\tBE
10315\tBB
21031\tHH
21039\tHH,SH
66111\tSL
66113\tSL
66119\tRP
66280\tRP
80331\tBY
80333\tBY
80335\tBY
80995\tBY
87491\t-
"""


def geonames_zip(path: Path, lines: list[str] = ROWS) -> Path:
    """A DE.zip as GeoNames publishes it: DE.txt (dated) next to a readme."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo("readme.txt", date_time=DATED), "GeoNames postal codes\n")
        archive.writestr(zipfile.ZipInfo("DE.txt", date_time=DATED), "".join(lines).encode("utf-8"))
    return path


def header(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("#")]


def body(text: str) -> str:
    return "".join(line for line in text.splitlines(keepends=True) if not line.startswith("#"))


# ------------------------------------------------------------------------------------ the build


def test_each_postcode_gets_the_länder_of_all_its_rows_mapped_by_code(tmp_path: Path) -> None:
    table = build(geonames_zip(tmp_path / "DE.zip"))
    assert body(table) == ROWS_OUT
    assert table.endswith("\n") and "\r" not in table


def test_the_header_names_the_source_its_hash_the_licence_the_changes_and_the_counts(tmp_path: Path) -> None:
    raw = "".join(ROWS).encode("utf-8")
    lines = header(build(geonames_zip(tmp_path / "DE.zip")))
    text = "\n".join(lines)
    assert "https://download.geonames.org/export/zip/DE.zip" in text
    assert f"DE.txt of 2026-10-08, sha256 {hashlib.sha256(raw).hexdigest()}" in text
    assert "# © GeoNames, https://www.geonames.org/" in lines
    assert "# CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ (LICENSE-GeoNames.txt)" in lines
    assert "Changed by Ordnung: one row per postcode with the Länder of all its rows" in text
    assert "python -I scripts/make_postcode_table.py" in text
    assert lines[-1] == "# Postcodes: 14; in one Land: 12; in several: 1; in none: 1"


def test_the_same_input_gives_the_same_bytes_whatever_the_order_of_its_rows(tmp_path: Path) -> None:
    first = build(geonames_zip(tmp_path / "a.zip"))
    assert build(geonames_zip(tmp_path / "b.zip")) == first
    shuffled = ROWS.copy()
    random.Random(7).shuffle(shuffled)
    assert body(build(geonames_zip(tmp_path / "c.zip", shuffled))) == body(first)


def test_an_unzipped_de_txt_with_its_date_gives_the_same_table_as_the_zip(tmp_path: Path) -> None:
    text = tmp_path / "DE.txt"
    text.write_text("".join(ROWS), encoding="utf-8", newline="")
    stamp = datetime(*DATED).timestamp()  # unzip sets the member's date (local time) as the file's
    os.utime(text, (stamp, stamp))
    assert build(text) == build(geonames_zip(tmp_path / "DE.zip"))


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        pytest.param(
            row("80331", "München", "Bayern", "17"), "unknown admin1 code '17'", id="unknown-number"
        ),
        pytest.param(
            row("80331", "München", "Bayern", "XX"), "unknown admin1 code 'XX'", id="unknown-letters"
        ),
        pytest.param(
            row("60311", "Frankfurt am Main", "Bayern", "05"),
            "'Bayern' is BY, but its code '05' is HE",
            id="name",
        ),
        pytest.param(
            row("14467", "Potsdam", "Land Berlin", "11"),
            "'Land Berlin' is BE, but its code '11' is BB",
            id="land",
        ),
        pytest.param(
            row("8033", "München", "Bayern", "BY"), "postcode '8033' is not 5 digits", id="4-digits"
        ),
        pytest.param("DE\t80331\tMünchen\n", "expected 12 tab-separated fields", id="short-row"),
    ],
)
def test_a_row_it_cannot_map_stops_the_build(tmp_path: Path, bad: str, message: str) -> None:
    with pytest.raises(BuildError, match=re.escape(message)) as raised:
        build(geonames_zip(tmp_path / "DE.zip", [*ROWS, bad]))
    assert "DE.txt line 18" in str(raised.value)


# ------------------------------------------------------------------------------------ the command


def test_it_writes_the_table_and_check_finds_a_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, out = geonames_zip(tmp_path / "DE.zip"), tmp_path / "postcodes_de.tsv"
    assert main([str(source), "--out", str(out)]) == 0
    assert out.read_bytes() == build(source).encode("utf-8")
    assert main([str(source), "--out", str(out), "--check"]) == 0
    out.write_bytes(out.read_bytes().replace(b"80331\tBY", b"80331\tBW"))
    assert main([str(source), "--out", str(out), "--check"]) == 1
    assert "differs" in capsys.readouterr().err
    assert out.read_bytes().count(b"80331\tBW") == 1  # --check never writes
    out.unlink()
    assert main([str(source), "--out", str(out), "--check"]) == 1


def test_a_build_error_exits_2_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source, out = (
        geonames_zip(tmp_path / "DE.zip", [*ROWS, row("80331", "X", "Bayern", "17")]),
        tmp_path / "t.tsv",
    )
    assert main([str(source), "--out", str(out)]) == 2
    assert "unknown admin1 code '17'" in capsys.readouterr().err
    assert not out.exists()


def test_a_missing_input_or_a_zip_without_de_txt_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "DE.zip"), "--check"]) == 2
    assert "DE.zip" in capsys.readouterr().err
    other = tmp_path / "AT.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("AT.txt", row("6691", "Jungholz", "Tirol", "07", country="AT"))
    assert main([str(other), "--check"]) == 2
    assert "AT.zip has no DE.txt" in capsys.readouterr().err


def test_measure_fallback_prints_the_deferred_fallback_s_three_precisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Worked by hand on :data:`ROWS`: 3 digits leave 66119 (RP) among two SL, 2 digits put 10115 and 10117
    (BE) next to 10315 (BB), and 66111 and 66113 (SL) next to 66280 (RP)."""
    out = tmp_path / "postcodes_de.tsv"
    assert main([str(geonames_zip(tmp_path / "DE.zip")), "--out", str(out), "--measure-fallback"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1:] == [
        "  first 3 digits, each postcode left out: 5 right, 1 wrong, 6 none: 83.33 % right",
        "  first 3 digits, each organisation or large-customer postcode left out: 2 right, 0 wrong, 0 none: "
        "100.00 % right",
        "  first 2 digits, each 3-digit block left out: 5 right, 5 wrong, 2 none: 50.00 % right; of the 5 "
        "blocks answered, 2 right, 1 partly wrong, 2 wholly wrong",
    ]
    assert not out.exists()


def test_measure_fallback_without_an_answer_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = geonames_zip(tmp_path / "DE.zip", [row("80331", "München", "Bayern", "BY")])
    assert main([str(source), "--measure-fallback"]) == 0
    assert "0 right, 0 wrong, 1 none: no answer" in capsys.readouterr().out


# ------------------------------------------------------------------------------------ the committed table


def test_the_committed_table_is_well_formed() -> None:
    raw = TABLE_PATH.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    lines = raw.decode("utf-8").splitlines()
    head = [line for line in lines if line.startswith("#")]
    assert lines[: len(head)] == head  # the header comes first
    rows = lines[len(head) :]
    codes = [line.split("\t")[0] for line in rows]
    assert codes == sorted(set(codes))
    for line in rows:
        assert re.fullmatch(r"[0-9]{5}\t(-|[A-Z]{2}(,[A-Z]{2})*)", line), line
        lands = line.split("\t")[1]
        if lands != "-":
            assert lands.split(",") == sorted(set(lands.split(","))) and set(lands.split(",")) <= set(
                REGION_NAMES
            )
    several = sum("," in line for line in rows)
    none = sum(line.endswith("\t-") for line in rows)
    one = len(rows) - several - none
    assert head[-1] == f"# Postcodes: {len(rows)}; in one Land: {one}; in several: {several}; in none: {none}"
    text = "\n".join(head)
    assert re.search(
        r"https://download\.geonames\.org/export/zip/DE\.zip, DE\.txt of \d{4}-\d\d-\d\d, sha256 [0-9a-f]{64}",
        text,
    )
    assert "# © GeoNames, https://www.geonames.org/" in head
    assert "# CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ (LICENSE-GeoNames.txt)" in head
    assert "Changed by Ordnung:" in text


def test_the_geonames_licence_ships_with_the_wheel() -> None:
    licence = TABLE_PATH.with_name("LICENSE-GeoNames.txt")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert licence.relative_to(ROOT).as_posix() in pyproject["project"]["license-files"]
    text = licence.read_text(encoding="utf-8")
    for needed in (
        "© GeoNames, https://www.geonames.org/",
        "https://creativecommons.org/licenses/by/4.0/",
        "Changed by Ordnung:",
        "without warranty",
    ):
        assert needed in text
