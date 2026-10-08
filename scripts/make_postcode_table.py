"""Build Ordnung's postcode table, ``src/ordnung/rules/data/postcodes_de.tsv``, from GeoNames' postal codes.

The table lists every German postcode GeoNames knows with the Länder of all its rows; the app asks "Is this
sender in …?" only for a postcode listed in exactly one Land (:mod:`ordnung.rules.postcodes`, ADR 0019).
The input is GeoNames' ``DE.zip`` (https://download.geonames.org/export/zip/DE.zip, CC BY 4.0), downloaded by
hand: this script never downloads, and reads ``DE.txt`` from inside the zip without extracting it (a
``DE.txt`` already unzipped works too, dated by its file). The same input gives the same bytes.

GeoNames gives each row's Land as an admin1 code in one of two series: the ISO 3166-2 letters of ordinary
postcodes (``BY``), which are Ordnung's codes, and numbers for its organisation and large-customer postcodes
(``02``, :data:`NUMERIC`). The script maps them by code, never by name; an empty code means no Land. It
stops on an unknown code, on an admin1 name of another Land than its code ("Land Berlin" is Berlin) and on
a postcode that isn't 5 digits.

``--measure-fallback`` prints the precision of the postal-area fallback ADR 0019 defers (a postcode GeoNames
doesn't list answered from the others under its first 3 or 2 digits), measured on GeoNames itself.

Run it from the repository root::

    python -I scripts/make_postcode_table.py DE.zip                       # make postcodes DE_ZIP=DE.zip
    python -I scripts/make_postcode_table.py DE.zip --check               # exit 1 if the table differs
    python -I scripts/make_postcode_table.py DE.zip --measure-fallback
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from ordnung.rules.calendar_de import REGION_NAMES, normalize_region

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "src" / "ordnung" / "rules" / "data" / "postcodes_de.tsv"
SOURCE_URL = "https://download.geonames.org/export/zip/DE.zip"
MEMBER = "DE.txt"
FIELDS = 12
NO_LAND = "-"

#: GeoNames' numeric admin1 codes for the Länder, in its order; its ISO letters are Ordnung's codes already.
NUMERIC = dict(
    zip(
        (f"{n:02d}" for n in range(1, 17)),
        "BW BY HB HH HE NI NW RP SL SH BB MV SN ST TH BE".split(),  # noqa: SIM905
        strict=True,
    )
)

HEADER = """\
# Ordnung's postcode table: the Länder GeoNames lists for each German postcode. Ordnung asks whether a
# sender is in a Land only when the postcode on their letter is listed in exactly one (rules/postcodes.py).
# Source: {url}, DE.txt of {dated}, sha256 {sha256}
# © GeoNames, https://www.geonames.org/
# CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ (LICENSE-GeoNames.txt)
# Changed by Ordnung: one row per postcode with the Länder of all its rows, GeoNames' admin1 codes mapped
# to Ordnung's two-letter Land codes, and every other column removed.
# Rows: the postcode, a tab and its Länder, comma-joined ("-": listed without a Land).
# Rebuild: download DE.zip, then python -I scripts/make_postcode_table.py DE.zip (make postcodes).
# Postcodes: {total}; in one Land: {one}; in several: {several}; in none: {none}
"""


class BuildError(ValueError):
    """A row of DE.txt the script can't map: the table is not written."""


@dataclass(frozen=True)
class Source:
    """DE.txt's text, the hash of its bytes and its date."""

    text: str
    sha256: str
    dated: date


@dataclass
class Postcodes:
    """What DE.txt says of each postcode."""

    lands: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    """Every postcode, with the Länder of all its rows (empty: none)."""
    series: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    """The admin1 series ("iso", "numeric") of the rows that give a postcode a Land."""


def read(path: Path) -> Source:
    """DE.txt from a DE.zip (dated as its zip member) or an unzipped DE.txt (dated by its file)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if MEMBER not in archive.namelist():
                raise BuildError(f"{path} has no {MEMBER}")
            raw = archive.read(MEMBER)
            dated = date(*archive.getinfo(MEMBER).date_time[:3])
    else:
        raw = path.read_bytes()
        dated = datetime.fromtimestamp(path.stat().st_mtime).date()
    return Source(raw.decode("utf-8"), hashlib.sha256(raw).hexdigest(), dated)


def _land(code: str, name: str, where: str) -> str | None:
    """The Land of an admin1 ``code`` (``None`` for an empty one), checked against its ``name``."""
    if not code:
        return None
    land = code if code in REGION_NAMES else NUMERIC.get(code)
    if land is None:
        raise BuildError(f"{where}: unknown admin1 code {code!r}")
    named = normalize_region(name.removeprefix("Land "))
    if named is not None and named != land:
        raise BuildError(f"{where}: the admin1 name {name!r} is {named}, but its code {code!r} is {land}")
    return land


def parse(text: str) -> Postcodes:
    """Every German postcode in DE.txt with the Länder of its rows; rows of other countries are skipped."""
    found = Postcodes()
    reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        where = f"{MEMBER} line {reader.line_num}"
        if len(row) != FIELDS:
            raise BuildError(f"{where}: expected {FIELDS} tab-separated fields, found {len(row)}")
        country, postcode, _place, name, code = row[:5]
        if country != "DE":
            continue
        if not re.fullmatch(r"[0-9]{5}", postcode):
            raise BuildError(f"{where}: the postcode {postcode!r} is not 5 digits")
        land = _land(code, name, where)
        lands = found.lands[postcode]  # a postcode listed without a Land is still a row
        if land is not None:
            lands.add(land)
            found.series[postcode].add("numeric" if code.isdigit() else "iso")
    return found


def render(postcodes: Postcodes, source: Source) -> str:
    """The table's text: the header, then one row per postcode, sorted."""
    sizes = Counter(min(len(lands), 2) for lands in postcodes.lands.values())
    head = HEADER.format(
        url=SOURCE_URL,
        dated=source.dated.isoformat(),
        sha256=source.sha256,
        total=len(postcodes.lands),
        one=sizes[1],
        several=sizes[2],
        none=sizes[0],
    )
    rows = (
        f"{code}\t{','.join(sorted(lands)) or NO_LAND}\n" for code, lands in sorted(postcodes.lands.items())
    )
    return head + "".join(rows)


def build(path: Path) -> str:
    """The table built from ``path`` (a DE.zip or a DE.txt)."""
    source = read(path)
    return render(parse(source.text), source)


# ------------------------------------------------------------------------------------ the deferred fallback


def _outcome(left: Iterable[str], truth: str) -> str:
    """ "right" or "wrong" when the other postcodes leave one Land, "none" otherwise."""
    lands = set(left)
    if len(lands) != 1:
        return "none"
    return "right" if lands == {truth} else "wrong"


def _tally(name: str, counts: Counter[str]) -> str:
    answered = counts["right"] + counts["wrong"]
    share = f"{100 * counts['right'] / answered:.2f} % right" if answered else "no answer"
    return f"  {name}: {counts['right']} right, {counts['wrong']} wrong, {counts['none']} none: {share}"


def _leave_one_out(postcodes: Postcodes, *, numeric_only: bool) -> Counter[str]:
    """Hide each postcode of one Land and answer it from the other postcodes under its first 3 digits."""
    areas: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for code, lands in postcodes.lands.items():
        areas[code[:3]].update(lands)
    counts: Counter[str] = Counter()
    for code, lands in postcodes.lands.items():
        if len(lands) != 1 or (numeric_only and postcodes.series.get(code) != {"numeric"}):
            continue
        (truth,) = lands
        rest = areas[code[:3]] - Counter({truth: 1})
        counts[_outcome(rest, truth)] += 1
    return counts


def _leave_one_block_out(postcodes: Postcodes) -> tuple[Counter[str], Counter[str]]:
    """Hide each 3-digit block and answer its postcodes of one Land from the rest of its first 2 digits:
    the counts per postcode and per block answered ("right", "partly wrong", "wholly wrong")."""
    blocks: defaultdict[str, Counter[str]] = defaultdict(Counter)
    single: defaultdict[str, list[str]] = defaultdict(list)
    for code, lands in postcodes.lands.items():
        blocks[code[:3]].update(lands)
        if len(lands) == 1:
            single[code[:3]].extend(lands)
    areas: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for block, lands in blocks.items():
        areas[block[:2]].update(lands)
    counts: Counter[str] = Counter()
    answered: Counter[str] = Counter()
    for block, truths in single.items():
        rest = areas[block[:2]] - blocks[block]
        outcomes = Counter(_outcome(rest, truth) for truth in truths)
        counts.update(outcomes)
        if outcomes["right"] or outcomes["wrong"]:
            kind = "partly wrong" if outcomes["right"] else "wholly wrong"
            answered["right" if not outcomes["wrong"] else kind] += 1
    return counts, answered


def measure_fallback(path: Path) -> list[str]:
    """The deferred postal-area fallback's precision on GeoNames itself (ADR 0019), as printed lines."""
    postcodes = parse(read(path).text)
    counts, blocks = _leave_one_block_out(postcodes)
    return [
        "The postal-area fallback Ordnung does not use (ADR 0019), measured on GeoNames itself:",
        _tally("first 3 digits, each postcode left out", _leave_one_out(postcodes, numeric_only=False)),
        _tally(
            "first 3 digits, each organisation or large-customer postcode left out",
            _leave_one_out(postcodes, numeric_only=True),
        ),
        _tally("first 2 digits, each 3-digit block left out", counts)
        + f"; of the {blocks.total()} blocks answered, {blocks['right']} right, {blocks['partly wrong']} "
        f"partly wrong, {blocks['wholly wrong']} wholly wrong",
    ]


# ------------------------------------------------------------------------------------ the command


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="GeoNames' DE.zip (or its DE.txt)")
    parser.add_argument("--out", type=Path, default=TABLE, help="the table to write (default: %(default)s)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="write nothing; exit 1 if the table differs")
    mode.add_argument(
        "--measure-fallback", action="store_true", help="print the deferred fallback's precision"
    )
    args = parser.parse_args(argv)
    try:
        if args.measure_fallback:
            print("\n".join(measure_fallback(args.source)))
            return 0
        table = build(args.source).encode("utf-8")
    except (BuildError, OSError) as error:
        print(f"make_postcode_table: {error}", file=sys.stderr)
        return 2
    if args.check:
        if not args.out.is_file() or args.out.read_bytes() != table:
            print(f"{args.out} differs from what {args.source} builds: run without --check", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.write_bytes(table)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
