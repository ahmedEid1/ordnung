"""Build a final split's ``evals/dataset/<split>/facts.json`` from its sealed blind audit (runbook §2.4, step 6).

    python -m scripts.build_final_facts --seal $F/audit-seal.txt --map $F/audit-map.json \\
        --a1 $F/a1-*/work/audit/derived-b*.json --a1c $F/a1c/work/audit/derived-conv.json \\
        --ruling $F/a1p/work/audit/adjudication.json $F/adjudication-key.json $F/a1p-pack \\
        [--re-map $F/audit-map-re.json --a1re $F/a1re/work/audit/derived-re.json [--a1re-conv FILE]] [--check]

It writes one ``facts.json`` per final split of the manifest (the grammar of ``evals/dataset/FACTS.md``, which
``evals/verify_labels.py`` reads), and with ``--check`` exits 1 when a committed one is not what the audit gives.
Where each slot's fact comes from, its ``source``:

* ``A1``: the first blind reading (``--a1``, the sealed ``derived-<batch>.json`` files) with the set's conventions
  applied to it (``--a1c``, the sealed ``derived-conv.json``: A1's facts with their ``conventions``, and a derivation
  changed only where a convention changes it). Its letters and slots must be A1's;
* ``A1p``: the adjudicator's fact, for every slot it ruled on (``--ruling``: its ``adjudication.json``, the key that
  says which entry and slot each case is, kept outside every sandbox, and the folder that holds the case pack), with
  any verdict: the side the set held, the other side, both wrong (a new date) or ambiguous (both readings);
* ``A1re``: a fresh blind reading of a letter whose bytes changed after the audit (``--a1re``, under the opaque names
  of its own map ``--re-map``; with ``--a1re-conv``, the same reading with the conventions applied), for every slot
  of that letter.

Every reading and every ruling is bound to the bytes it read: the opaque-name map gives each opaque file's entry id
and the sha256 of the letter it was copied from, and a ruling's letter is found in a map by the sha256 of the copy in
its pack. A reading or a ruling of bytes the manifest no longer holds is left out (counted). A label slot (``i0``,
``o0``, ``term_end``, ``cancel_by``, in the manifest's order) is matched with a reader's slot the way the audit
comparison matches them: an item with the lowest unused reader's slot of the same prefix and kind, else the slot of
the same name when the reader gave it no kind; a contract slot with the reader's slot of its name. A photo shares its
letter's truth and gets no facts of its own: a ruling on a photo's slot is applied to its letter's slot (bound to the
photo's own bytes); a reader's slot that matches no label slot is left out (counted); a price change's facts are taken
when the label has one.

Refused, with nothing written (exit 2): an audit file that is not in the seal with its sha256, or not in its format;
a label slot with a date or ``"ambiguous"`` and no fact; a final letter with no reading of its bytes as they are now;
an id the manifest or the maps do not know (a map's entry, a reader's letter, a key's case or entry, a verdict's case,
a slot the label does not have); a key's case whose X and Y are not the label and the second reading; a slot ruled
twice, or ruled on a letter and on its photo with rulings that mean different things; a verdict that is not one of the
four, a ``both_wrong`` without its date, and an ``ambiguous`` verdict that names fewer than two candidates, a
candidate that is neither X's date nor Y's in its pack, no date of one of the two sides, or a fact that is not
ambiguous; and a facts file the grammar refuses. It prints ids and counts only, never a fact, a date or a reason.

A letter and its photo are two cases of the adjudication, and the pack draws which side is X for each case on its
own, so the same ruling can read ``X_right`` in one and ``Y_right`` in the other. The two rulings are compared by what
they mean (``fact_meaning``): the side each upholds (the label, the second reading, both wrong, or ambiguous), the date
or the candidates its fact derives under the grammar, the other dates it states, and the conventions it applies; not
by the verdict's letters or the fact's form. The letter's fact is the one applied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from evals import verify_labels

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "evals" / "dataset"
FACTS_NAME = "facts.json"
MAP_FORMAT = "ev8-audit-map/1"
DERIVED_FORMAT = "ev8-derived/1"
CONV_FORMAT = "ev8-derived-conv/1"
ADJUDICATION_FORMAT = "ev8-adjudication/1"
KEY_FORMAT = "ev8-adjudication-key/1"
VERDICTS = ("X_right", "Y_right", "both_wrong", "ambiguous")
#: What the key says each case's X and Y are: the label and the second reading (A1c), in the order drawn for the case.
SIDES = ("label", "a1c")
#: A contract's slots and the truth's names for them (``term_end`` -> ``expected_current_term_end``).
CONTRACT_SLOTS = verify_labels.CONTRACT_SLOTS
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_LINE = re.compile(r"^Date:\s*(.*)$", re.MULTILINE)


class BuildError(Exception):
    """The audit files do not give a facts file: the message names ids, files and slots only."""


# --------------------------------------------------------------------------------------------------
# The inputs
# --------------------------------------------------------------------------------------------------


def _load(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"{what} {path.name}: not readable as JSON ({type(exc).__name__})") from None


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BuildError(f"{path.name}: not readable ({type(exc).__name__})") from None


def _stem(name: str) -> str:
    return Path(name).stem


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BuildError(f"{where}: not an object")
    return value


def load_seal(path: Path) -> dict[str, str]:
    """The seal (``sha256sum`` lines): each sealed file's real path and sha256."""
    seal: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BuildError(f"the seal {path.name}: not readable ({type(exc).__name__})") from None
    for line in lines:
        if line.strip():
            sha, name = line.split(None, 1)
            seal[os.path.realpath(name.lstrip("*").strip())] = sha
    return seal


def check_sealed(paths: Sequence[Path], seal: Mapping[str, str], seal_name: str) -> None:
    for path in paths:
        if seal.get(os.path.realpath(path)) != _sha256(path):
            raise BuildError(f"{path.name} is not in the seal with its sha256 ({seal_name})")


@dataclass(frozen=True)
class MapItem:
    """One opaque file of a map: its name (without extension), its entry, and the bytes it was copied from."""

    name: str
    entry_id: str
    photo: bool
    source_sha256: str
    opaque_sha256: str


def load_map(path: Path, entries: Mapping[str, Mapping[str, Any]]) -> dict[str, MapItem]:
    """A map's items by opaque name; an entry id the manifest's final splits do not hold is refused."""
    doc = _object(_load(path, "the map"), path.name)
    if doc.get("format") != MAP_FORMAT:
        raise BuildError(f"{path.name}: format {doc.get('format')!r}, not {MAP_FORMAT!r}")
    items: dict[str, MapItem] = {}
    for raw in doc.get("items") or []:
        raw = _object(raw, f"{path.name} item")
        name, entry_id = _stem(str(raw.get("name"))), str(raw.get("id"))
        if entry_id not in entries:
            raise BuildError(f"{path.name}: unknown entry id {entry_id} (not a letter of a final split)")
        if name in items:
            raise BuildError(f"{path.name}: {name} is named twice")
        items[name] = MapItem(
            name=name,
            entry_id=entry_id,
            photo=bool(raw.get("photo")),
            source_sha256=str(raw.get("source_sha256")),
            opaque_sha256=str(raw.get("opaque_sha256")),
        )
    return items


def _letters(paths: Sequence[Path], fmt: str, what: str) -> dict[str, Mapping[str, Any]]:
    merged: dict[str, Mapping[str, Any]] = {}
    for path in paths:
        doc = _object(_load(path, what), path.name)
        if doc.get("format") != fmt:
            raise BuildError(f"{path.name}: format {doc.get('format')!r}, not {fmt!r}")
        for key, letter in _object(doc.get("letters") or {}, f"{path.name} letters").items():
            name = _stem(str(key))
            if name in merged:
                raise BuildError(f"letter {name} is in two {what} files")
            merged[name] = _object(letter, f"{path.name} {name}")
    return merged


def _slots_of(letter: Mapping[str, Any], where: str) -> dict[str, Mapping[str, Any]]:
    return {str(k): _object(v, f"{where} {k}") for k, v in _object(letter.get("slots") or {}, where).items()}


def _facts_of(letter: Mapping[str, Any], where: str) -> dict[str, dict[str, Any]]:
    """A letter's facts by the slot each names (``price_change`` too), without the ``slot`` key."""
    facts: dict[str, dict[str, Any]] = {}
    for raw in letter.get("facts") or []:
        fact = dict(_object(raw, f"{where} fact"))
        slot = fact.pop("slot", None)
        if not isinstance(slot, str):
            raise BuildError(f"{where}: a fact names no slot")
        if slot in facts:
            raise BuildError(f"{where}: two facts for {slot}")
        facts[slot] = fact
    return facts


@dataclass
class Reading:
    """A blind reading: its source, its map, and per opaque name the reader's slots and facts."""

    source: str
    items: dict[str, MapItem]
    slots: dict[str, dict[str, Mapping[str, Any]]] = field(default_factory=dict)
    facts: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)


def load_reading(
    source: str,
    map_path: Path,
    raw: Sequence[Path],
    conventions: Path | None,
    entries: Mapping[str, Mapping[str, Any]],
) -> Reading:
    """A reading from its map and sealed files: its facts from the conventions reading when there is one, which must
    hold exactly the sealed reading's letters and slots."""
    items = load_map(map_path, entries)
    sealed = _letters(raw, DERIVED_FORMAT, f"{source} reading")
    for name in sorted(sealed):
        if name not in items:
            raise BuildError(f"{source}: unknown letter {name} (not in {map_path.name})")
    chosen = sealed
    if conventions is not None:
        chosen = _letters([conventions], CONV_FORMAT, f"{source} conventions reading")
        if set(chosen) != set(sealed):
            odd = sorted(set(chosen) ^ set(sealed))
            raise BuildError(
                f"{source}: the conventions reading and the sealed reading differ in letters {odd}"
            )
        for name in sorted(sealed):
            mine, theirs = sorted(_slots_of(chosen[name], name)), sorted(_slots_of(sealed[name], name))
            if mine != theirs:
                raise BuildError(
                    f"{name}: the conventions reading has slots {mine}, the sealed reading {theirs}"
                )
    reading = Reading(source, items)
    for name, letter in chosen.items():
        reading.slots[name] = _slots_of(letter, name)
        reading.facts[name] = _facts_of(letter, name)
    return reading


@dataclass(frozen=True)
class Ruling:
    """One adjudicated slot: its case, entry and slot, the verdict and its fact, the bytes it ruled on, and what the
    verdict upholds (``upheld``: ``label`` or ``a1c`` for X_right and Y_right, by the key's sides of this case;
    else the verdict itself)."""

    case: str
    entry_id: str
    slot: str
    verdict: str
    fact: dict[str, Any]
    item: MapItem
    upheld: str


def _label_slots(truth: Mapping[str, Any]) -> list[tuple[str, str | None, Any]]:
    """The label's slots in the manifest's order: (slot, the item's kind or None for a contract, the label)."""
    out: list[tuple[str, str | None, Any]] = []
    for prefix, key in (("i", "items"), ("o", "optional_items")):
        for n, item in enumerate(truth.get(key) or []):
            out.append((f"{prefix}{n}", item.get("kind"), item.get("expected_due")))
    contract = truth.get("contract")
    if isinstance(contract, Mapping):
        for slot, key in CONTRACT_SLOTS.items():
            out.append((slot, None, contract.get(key)))
    return out


def _needs_fact(label: Any) -> bool:
    """A label with a date or ``"ambiguous"``: verify_labels re-derives it, so it needs its fact."""
    return isinstance(label, str) and (label == verify_labels.AMBIGUOUS or bool(_ISO_DAY.fullmatch(label)))


def _pack_dates(pack: Path, case: str) -> dict[str, set[str]]:
    """The dates X and Y each give in the case pack (``Date:`` lines; an ambiguous side gives each of its dates)."""
    dates: dict[str, set[str]] = {}
    for side in ("X", "Y"):
        path = pack / "pack" / f"{case}-{side}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise BuildError(f"{case}: no {path.name} in the pack") from None
        dates[side] = {day for line in _DATE_LINE.findall(text) for day in _ISO_DAY.findall(line)}
    return dates


def load_rulings(
    adjudication: Path,
    key: Path,
    pack: Path,
    maps: Sequence[Mapping[str, MapItem]],
    entries: Mapping[str, Mapping[str, Any]],
) -> list[Ruling]:
    """The rulings of one adjudication: every case of its key with its verdict, checked against the pack."""
    key_doc = _object(_load(key, "the adjudication key"), key.name)
    verdicts_doc = _object(_load(adjudication, "the adjudication"), adjudication.name)
    if key_doc.get("format") != KEY_FORMAT:
        raise BuildError(f"{key.name}: format {key_doc.get('format')!r}, not {KEY_FORMAT!r}")
    if verdicts_doc.get("format") != ADJUDICATION_FORMAT:
        raise BuildError(
            f"{adjudication.name}: format {verdicts_doc.get('format')!r}, not {ADJUDICATION_FORMAT!r}"
        )
    cases = _object(key_doc.get("cases") or {}, f"{key.name} cases")
    verdicts = _object(verdicts_doc.get("cases") or {}, f"{adjudication.name} cases")
    for case in sorted(verdicts):
        if case not in cases:
            raise BuildError(f"{adjudication.name}: unknown case {case} (not in {key.name})")
    listed = {
        str(row.get("case")): row for row in _load(pack / "pack" / "cases.json", "the pack's cases") or []
    }
    rulings = []
    for case, ref in sorted(cases.items()):
        ref = _object(ref, f"{key.name} {case}")
        entry_id, slot, name = str(ref.get("id")), str(ref.get("slot")), str(ref.get("name"))
        if entry_id not in entries:
            raise BuildError(f"{key.name} {case}: unknown entry id {entry_id}")
        if slot not in {s for s, _, _ in _label_slots(entries[entry_id]["truth"])}:
            raise BuildError(f"{key.name} {case}: unknown slot {slot} of {entry_id}")
        drawn = {"X": ref.get("X"), "Y": ref.get("Y")}
        if sorted(map(str, drawn.values())) != sorted(SIDES):
            raise BuildError(f"{key.name} {case}: X and Y are not the label and the second reading")
        row = listed.get(case)
        if row is None or row.get("slot") != slot or _stem(str(row.get("letter"))) != _stem(name):
            raise BuildError(f"{case}: the pack's cases.json does not list it with its letter and slot")
        copy_sha = _sha256(pack / "pack" / "letters" / Path(name).name)
        found = [
            item
            for items in maps
            for item in items.values()
            if item.entry_id == entry_id and item.opaque_sha256 == copy_sha
        ]
        if not found:
            raise BuildError(f"{case}: the letter in its pack is in no map as {entry_id}")
        verdict = verdicts.get(case)
        if not isinstance(verdict, Mapping):
            raise BuildError(f"{entry_id} {slot}: no verdict (case {case})")
        said = verdict.get("verdict")
        if said not in VERDICTS:
            raise BuildError(f"{case}: verdict {said!r} is not one of {', '.join(VERDICTS)}")
        fact = verdict.get("fact")
        if not isinstance(fact, Mapping):
            raise BuildError(f"{entry_id} {slot}: no fact (case {case})")
        if said == "both_wrong" and not (
            isinstance(verdict.get("date"), str) and _ISO_DAY.fullmatch(verdict["date"])
        ):
            raise BuildError(f"{case}: a both_wrong verdict gives its date")
        if said == "ambiguous":
            candidates = verdict.get("candidates")
            if (
                not isinstance(candidates, list)
                or not all(isinstance(c, str) and _ISO_DAY.fullmatch(c) for c in candidates)
                or len(set(candidates)) < 2
            ):
                raise BuildError(f"{case}: an ambiguous verdict names two or more candidates")
            sides = _pack_dates(pack, case)
            for candidate in candidates:
                if not any(candidate in dates for dates in sides.values()):
                    raise BuildError(f"{case}: the candidate {candidate} is in neither X nor Y")
            if not all(sides[side] & set(candidates) for side in sides):
                raise BuildError(f"{case}: an ambiguous verdict keeps a date of each side")
            if "ambiguous" not in fact:
                raise BuildError(f"{case}: an ambiguous verdict's fact is no ambiguous fact")
        upheld = str(drawn[said[0]]) if said in ("X_right", "Y_right") else str(said)
        rulings.append(Ruling(case, entry_id, slot, str(said), dict(fact), found[0], upheld))
    return rulings


# --------------------------------------------------------------------------------------------------
# The build
# --------------------------------------------------------------------------------------------------


def fact_meaning(fact: Mapping[str, Any], case: str, slot: str) -> tuple[Any, ...]:
    """What ``verify_labels`` reads from a slot's fact, whatever its form: the date it derives and the other dates
    it states, the candidates of an ambiguous fact, or that the letter cannot be dated; and the conventions it
    applies (which the label's tags must be). The order of the conventions or of the readings, the Land where it
    changes no date, the event's words and the way to a date are form."""
    try:
        parsed = verify_labels._letter_facts(case, {"slots": {slot: {**fact, "source": "A1p"}}})
    except verify_labels.FactsError:
        raise BuildError(f"{case}: its fact is not in the grammar of evals/dataset/FACTS.md") from None
    value, conventions = parsed.slots[slot], tuple(sorted(set(parsed.conventions[slot])))
    if value is None:
        return ("undatable", conventions)
    if value[0] == verify_labels.AMBIGUOUS:
        return ("ambiguous", tuple(sorted(set(value[1]))), conventions)
    fn, args, region = cast(verify_labels.Rule, value)
    stated = sorted({f(*a, region=r).isoformat() for f, a, r in parsed.conflicts.get(slot, [])})
    return ("dated", fn(*args, region=region).isoformat(), tuple(stated), conventions)


def _meaning(ruling: Ruling) -> tuple[Any, ...]:
    """A ruling as the side it upholds and its fact's meaning (the pack draws X and Y per case)."""
    return (ruling.upheld, fact_meaning(ruling.fact, ruling.case, ruling.slot))


def match(
    labels: Sequence[tuple[str, str | None, Any]], slots: Mapping[str, Mapping[str, Any]]
) -> dict[str, str | None]:
    """Each label slot's reader's slot, as the audit comparison matches them (see the module notes)."""
    used: set[str] = set()
    out: dict[str, str | None] = {}
    for name, kind, _ in labels:
        if name in CONTRACT_SLOTS:
            out[name] = name if name in slots else None
            used.add(name)
            continue
        prefix = name.rstrip("0123456789")
        same = sorted(
            (
                s
                for s in slots
                if s.startswith(prefix)
                and s[len(prefix) :].isdigit()
                and s not in used
                and slots[s].get("kind") == kind
            ),
            key=lambda s: int(s[len(prefix) :]),
        )
        pick = (
            same[0]
            if same
            else (name if name in slots and name not in used and not slots[name].get("kind") else None)
        )
        out[name] = pick
        if pick:
            used.add(pick)
    return out


@dataclass
class Report:
    """What one split's build took from where: counts only."""

    letters: int = 0
    sources: Counter[str] = field(default_factory=Counter)
    verdicts: Counter[str] = field(default_factory=Counter)
    ruled_ambiguous: Counter[str] = field(default_factory=Counter)
    stale_rulings: int = 0
    photos: int = 0
    unmatched_reader_slots: int = 0
    price_changes_without_fact: int = 0

    def lines(self, split: str) -> list[str]:
        sources = ", ".join(f"{name} {self.sources[name]}" for name in verify_labels.SOURCES)
        verdicts = ", ".join(f"{name} {self.verdicts[name]}" for name in VERDICTS)
        return [
            f"{split}: {self.letters} letters ({self.photos} photos share their letter's facts); facts by source: "
            f"{sources}",
            f"{split}: rulings applied: {verdicts}; ruled ambiguous: "
            + ", ".join(f"{kind} {self.ruled_ambiguous[kind]}" for kind in AMBIGUOUS_KINDS)
            + f"; {self.stale_rulings} ruling(s) on bytes read again",
            f"{split}: {self.unmatched_reader_slots} reader's slot(s) matched no label slot; "
            f"{self.price_changes_without_fact} price change(s) without a fact",
        ]


#: The kinds of a slot, as the final analysis counts the slots left open: a deadline the letter requires (``i0``,
#: ...), a date it offers (``o0``, ...) and a contract date (``term_end``, ``cancel_by``).
AMBIGUOUS_KINDS = ("deadline", "offered", "contract")


def _kind(slot: str) -> str:
    return "contract" if slot in CONTRACT_SLOTS else "offered" if slot.startswith("o") else "deadline"


def _is_final(entry: Mapping[str, Any]) -> bool:
    return "final_day" in entry or "valid_until" in entry


def _letter_of(entries: Mapping[str, Mapping[str, Any]], entry_id: str) -> str:
    """The letter an entry's truth belongs to: a photo's source letter, else the entry itself."""
    entry = entries.get(entry_id) or {}
    return str(entry.get("source_id") or entry_id) if entry.get("photo") else entry_id


def build(
    entries: Mapping[str, Mapping[str, Any]], readings: Sequence[Reading], rulings: Sequence[Ruling]
) -> tuple[dict[str, dict[str, Any]], dict[str, Report]]:
    """Every final split's facts document and its report."""
    docs: dict[str, dict[str, Any]] = {}
    reports: dict[str, Report] = {}
    for entry_id, entry in sorted(entries.items()):
        split = str(entry["split"])
        doc = docs.setdefault(split, {"split": split, "letters": {}})
        report = reports.setdefault(split, Report())
        if entry.get("photo"):
            report.photos += 1
            continue
        report.letters += 1
        sha = entry.get("sha256")
        now: dict[str, Ruling] = {}
        # a ruling on the letter, then one on a photo of it (which shares its truth), each on the bytes it read
        applying = sorted(
            (r for r in rulings if _letter_of(entries, r.entry_id) == entry_id),
            key=lambda r: (r.entry_id != entry_id, r.case),
        )
        for ruling in applying:
            if ruling.item.source_sha256 != entries[ruling.entry_id].get("sha256"):
                report.stale_rulings += 1
                continue
            first = now.get(ruling.slot)
            if first is None:
                now[ruling.slot] = ruling
            elif first.entry_id == ruling.entry_id:
                raise BuildError(f"{entry_id} {ruling.slot}: ruled twice ({first.case}, {ruling.case})")
            elif _meaning(first) != _meaning(ruling):
                raise BuildError(
                    f"{entry_id} {ruling.slot}: ruled differently on the letter and its photo "
                    f"({min(first.case, ruling.case)}, {max(first.case, ruling.case)})"
                )
        current = [
            (reading, item)
            for reading in readings
            for item in reading.items.values()
            if item.entry_id == entry_id and not item.photo and item.source_sha256 == sha
        ]
        if not current:
            raise BuildError(f"{entry_id}: no blind reading of its letter as it is now")
        reading, item = current[-1]  # a fresh reading (A1re) comes after the first
        truth = entry["truth"]
        labels = _label_slots(truth)
        slots = reading.slots.get(item.name, {})
        facts = reading.facts.get(item.name, {})
        matched = match(labels, slots)
        report.unmatched_reader_slots += len(set(slots) - {s for s in matched.values() if s})
        letter: dict[str, Any] = {"slots": {}}
        for slot, _, label in labels:
            ruled = now.get(slot)
            if ruled is not None:
                source, fact = "A1p", ruled.fact
                report.verdicts[ruled.verdict] += 1
                if ruled.verdict == "ambiguous":
                    report.ruled_ambiguous[_kind(slot)] += 1
            else:
                mine = matched[slot]
                found = facts.get(mine) if mine else None
                if found is None:
                    if _needs_fact(label):
                        raise BuildError(f"{entry_id} {slot}: no fact")
                    continue
                source, fact = reading.source, found
            letter["slots"][slot] = {**fact, "source": source}
            report.sources[source] += 1
        if truth.get("price_change"):
            change = facts.get("price_change")
            if change is None:
                report.price_changes_without_fact += 1
            else:
                letter["price_change"] = {**change, "source": reading.source}
                report.sources[reading.source] += 1
        doc["letters"][entry_id] = letter
    return docs, reports


def render(doc: Mapping[str, Any]) -> str:
    """A facts file as committed: keys sorted, one space of indent, a final newline."""
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def check_grammar(docs: Mapping[str, Mapping[str, Any]]) -> None:
    """Each facts file read back with verify_labels' own reader of the grammar."""
    with tempfile.TemporaryDirectory() as tmp:
        for split, doc in docs.items():
            path = Path(tmp) / split / FACTS_NAME
            path.parent.mkdir(parents=True)
            path.write_text(render(doc), encoding="utf-8")
            try:
                verify_labels.load_facts(path)
            except verify_labels.FactsError as exc:
                raise BuildError(f"{split}/{FACTS_NAME}: {exc}") from None


# --------------------------------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.build_final_facts", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--manifest", type=Path, default=None, help="the manifest (default: DATASET/manifest.json)"
    )
    parser.add_argument(
        "--dataset", type=Path, default=DATASET_DIR, help="where <split>/facts.json go (evals/dataset)"
    )
    parser.add_argument("--seal", type=Path, required=True, help="the audit seal (sha256sum lines)")
    parser.add_argument("--map", type=Path, required=True, help="the opaque-name map of the first reading")
    parser.add_argument(
        "--a1", type=Path, nargs="+", required=True, help="the first reading's derived-<batch>.json"
    )
    parser.add_argument(
        "--a1c", type=Path, required=True, help="the first reading with the conventions applied"
    )
    parser.add_argument(
        "--ruling",
        type=Path,
        nargs=3,
        action="append",
        default=[],
        metavar=("ADJUDICATION", "KEY", "PACK"),
        help="an adjudication: its adjudication.json, its key and the folder that holds its pack/",
    )
    parser.add_argument("--re-map", type=Path, default=None, help="the opaque-name map of the fresh reading")
    parser.add_argument(
        "--a1re", type=Path, nargs="+", default=None, help="the fresh reading of changed letters"
    )
    parser.add_argument(
        "--a1re-conv", type=Path, default=None, help="the fresh reading with the conventions applied"
    )
    parser.add_argument("--check", action="store_true", help="exit 1 when a committed facts file differs")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = args.manifest or args.dataset / "manifest.json"
    try:
        if (args.a1re is None) != (args.re_map is None) or (args.a1re_conv is not None and args.a1re is None):
            raise BuildError("--a1re and --re-map come together, and --a1re-conv only with them")
        raw = _object(_load(manifest, "the manifest"), manifest.name)
        entries = {
            str(e["id"]): e for e in raw.get("entries") or [] if isinstance(e, Mapping) and _is_final(e)
        }
        sealed = [*args.a1, args.a1c, *(args.a1re or []), *([args.a1re_conv] if args.a1re_conv else [])]
        check_sealed(sealed, load_seal(args.seal), args.seal.name)
        readings = [load_reading("A1", args.map, args.a1, args.a1c, entries)]
        if args.a1re is not None:
            readings.append(load_reading("A1re", args.re_map, args.a1re, args.a1re_conv, entries))
        maps = [reading.items for reading in readings]
        rulings = [
            ruling
            for adjudication, key, pack in args.ruling
            for ruling in load_rulings(adjudication, key, pack, maps, entries)
        ]
        docs, reports = build(entries, readings, rulings)
        check_grammar(docs)
    except BuildError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for split in sorted(reports):
        for line in reports[split].lines(split):
            print(line)
    stale = []
    for split, doc in sorted(docs.items()):
        path = args.dataset / split / FACTS_NAME
        text = render(doc)
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(f"{split}/{FACTS_NAME}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {split}/{FACTS_NAME}")
    if stale:
        print(
            f"not what the sealed audit gives: {', '.join(stale)} (run python -m scripts.build_final_facts)"
        )
        return 1
    if args.check:
        print("every facts file is what the sealed audit gives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
