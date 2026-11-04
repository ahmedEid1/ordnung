"""The facts of a final split from its sealed blind audit (``scripts/build_final_facts.py``), on synthetic files.

A final split's ``facts.json`` (the grammar of ``evals/dataset/FACTS.md``) is built from the blind readers' sealed
files: the convention-free reading with the conventions applied (A1, through A1c), the adjudicator's facts for every
slot it ruled on (A1p), and a fresh blind reading of a letter whose bytes changed (A1re). Every reading is bound to
the bytes it read through the opaque-name map, so a ruling or a reading of bytes that changed since is left out. No
letter here is real: the manifest, the map and the audit files are written by the tests.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from evals import verify_labels as vl
from scripts import build_final_facts as build

SPLIT = "holdout4"
K1, K2, K1_PHOTO = "holdout4-x-K1", "holdout4-x-K2", "holdout4-x-K1-photo"
CONVENTIONS = {"conventions": [{"id": "c02", "disputed": True}, {"id": "c03", "disputed": False}]}
TERM = [
    {"op": "forward", "n": 12, "unit": "months", "shift": False},
    {"op": "back", "n": 1, "unit": "days", "shift": False},
]
CANCEL = [*TERM, {"op": "back", "n": 1, "unit": "months", "shift": False}]
SHIFTED = [{"op": "forward", "n": 2, "unit": "days", "shift": True}]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(cid: str, truth: dict[str, Any], *, photo: bool = False, sha: str | None = None) -> dict[str, Any]:
    return {
        "id": cid,
        "split": SPLIT,
        "family": "x",
        "file": f"{SPLIT}/{cid}.{'jpg' if photo else 'pdf'}",
        "sha256": sha or _sha(cid.encode()),
        "photo": photo,
        "source_id": K1 if photo else None,
        "today": "2026-12-08",
        "final_day": "2026-12-08",
        "valid_until": "2026-12-15",
        "authority_region": None,
        "truth": truth,
    }


def _truth(**parts: Any) -> dict[str, Any]:
    return {"items": [], "optional_items": [], "contract": None, "price_change": None, **parts}


def manifest() -> dict[str, Any]:
    """K1: a deadline labelled Mon 15 March 2027 under disputed convention c02, and an undated offer. K2: a payment
    on a stated day, and a contract whose end of term the adjudicator left open between two dates (its last day to
    cancel stays dated). K1's photo shares K1's truth."""
    k1 = _truth(
        items=[{"kind": "deadline", "expected_due": "2027-03-15", "conventions": ["c02"]}],
        optional_items=[{"kind": "payment", "expected_due": None}],
    )
    k2 = _truth(
        items=[{"kind": "payment", "expected_due": "2027-04-30", "conventions": []}],
        contract={
            "expected_current_term_end": "ambiguous",
            "expected_cancel_by": "2028-01-31",
            "candidates": {"expected_current_term_end": ["2028-02-29", "2028-03-31"]},
            "conventions": [],
        },
    )
    entries = [_entry(K1, k1), _entry(K2, k2), _entry(K1_PHOTO, copy.deepcopy(k1), photo=True)]
    return {"name": "synthetic", "conventions": CONVENTIONS["conventions"], "entries": entries}


def _slot(kind: str | None, status: str, **more: Any) -> dict[str, Any]:
    slot: dict[str, Any] = {"status": status, "steps": [], "citations": [], "why": "-", **more}
    if kind is not None:
        slot["kind"] = kind
    return slot


def _fact(slot: str, start: str, steps: list[dict[str, Any]], **more: Any) -> dict[str, Any]:
    return {"slot": slot, "source": "A1", "land": None, "from": start, "steps": steps, **more}


def a1_letters() -> dict[str, Any]:
    """The convention-free reading of the three files (L003 is K1's photo)."""
    k1 = {
        "slots": {"i0": _slot("deadline", "dated", date="2027-03-15"), "o0": _slot("payment", "undatable")},
        "facts": [
            _fact("i0", "2027-03-11", SHIFTED),
            {"slot": "o0", "source": "A1", "undatable": True},
        ],
    }
    k2 = {
        "slots": {
            "i0": _slot("payment", "dated", date="2027-04-30"),
            "term_end": _slot(None, "dated", date="2028-02-29"),
            "cancel_by": _slot(None, "dated", date="2028-01-31"),
        },
        "facts": [
            _fact("i0", "2027-04-30", []),
            _fact("term_end", "2027-03-01", TERM),
            _fact("cancel_by", "2027-03-01", CANCEL),
        ],
    }
    return {"L001": k1, "L002": k2, "L003": copy.deepcopy(k1)}


def a1c_letters() -> dict[str, Any]:
    """A1c applies the conventions: c02 to K1's deadline (no date changes), and on K2's end of term it reads
    Fri 31 March 2028, which is not the label's date, so that slot goes to the adjudicator."""
    letters = a1_letters()
    for letter in letters.values():
        for slot in letter["slots"].values():
            slot |= {"ids_applied": [], "changed": False}
    for name in ("L001", "L003"):
        letters[name]["slots"]["i0"]["ids_applied"] = ["c02"]
        letters[name]["facts"][0]["conventions"] = ["c02"]
    letters["L002"]["slots"]["term_end"] |= {"date": "2028-03-31", "changed": True}
    letters["L002"]["facts"][1] = _fact("term_end", "2028-03-31", [])
    return letters


class Audit:
    """The sealed audit files, the map, the adjudication and its pack, written under ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = manifest()
        self.a1 = {"format": "ev8-derived/1", "batch": "b1", "letters": a1_letters()}
        self.a1c = {"format": "ev8-derived-conv/1", "letters": a1c_letters()}
        self.opaque = {name: f"opaque copy of {name}".encode() for name in ("L001", "L002", "L003")}
        ids = {"L001": K1, "L002": K2, "L003": K1_PHOTO}
        self.map: dict[str, Any] = {"format": "ev8-audit-map/1", "items": []}
        for name, cid in ids.items():
            entry = next(e for e in self.manifest["entries"] if e["id"] == cid)
            suffix = ".jpg" if entry["photo"] else ".pdf"
            self.map["items"].append(
                {
                    "name": name + suffix,
                    "id": cid,
                    "split": SPLIT,
                    "batch": "b1",
                    "photo": entry["photo"],
                    "source_id": entry["source_id"],
                    "source_sha256": entry["sha256"],
                    "opaque_sha256": _sha(self.opaque[name]),
                }
            )
        self.key = {
            "format": "ev8-adjudication-key/1",
            "cases": {"D001": {"id": K2, "name": "L002.pdf", "slot": "term_end", "X": "label", "Y": "a1c"}},
        }
        open_end = [{"from": "2027-03-01", "steps": TERM}, {"from": "2028-03-31", "steps": []}]
        self.adjudication = {
            "format": "ev8-adjudication/1",
            "cases": {
                "D001": {
                    "verdict": "ambiguous",
                    "candidates": ["2028-02-29", "2028-03-31"],
                    "citations": ["§ 188 Abs. 2 BGB"],
                    "why": "-",
                    "fact": {"source": "A1p", "land": None, "ambiguous": open_end},
                }
            },
        }
        self.pack_dates = {"X": "2028-02-29", "Y": "2028-03-31"}
        #: Per case other than D001: the dates its X and Y give.
        self.case_dates: dict[str, dict[str, str]] = {}
        self.extra: list[str] = []

    def path(self, name: str) -> Path:
        return self.root / name

    def write(self) -> list[str]:
        """Every file on disk; the command line's arguments."""
        self.root.mkdir(parents=True, exist_ok=True)
        dataset = self.path("dataset")
        dataset.mkdir(exist_ok=True)
        (dataset / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        for name, doc in (
            ("audit-map.json", self.map),
            ("derived-b1.json", self.a1),
            ("derived-conv.json", self.a1c),
            ("adjudication.json", self.adjudication),
            ("adjudication-key.json", self.key),
        ):
            self.path(name).write_text(json.dumps(doc), encoding="utf-8")
        pack = self.path("pack") / "pack"
        (pack / "letters").mkdir(parents=True, exist_ok=True)
        rows = []
        for case, ref in sorted(self.key["cases"].items()):
            name = ref["name"]
            (pack / "letters" / name).write_bytes(self.opaque[Path(name).stem])
            rows.append({"case": case, "letter": f"letters/{name}", "slot": ref["slot"], "kind": None})
            for side, day in self.case_dates.get(case, self.pack_dates).items():
                (pack / f"{case}-{side}.md").write_text(
                    f"Case {case}, derivation {side}\nSlot: {ref['slot']}\nDate: {day}\n\nDerivation:\n-\n",
                    encoding="utf-8",
                )
        (pack / "cases.json").write_text(json.dumps(rows), encoding="utf-8")
        sealed = [self.path("derived-b1.json"), self.path("derived-conv.json"), *map(Path, self.sealed_extra)]
        self.path("audit-seal.txt").write_text(
            "".join(f"{_sha(p.read_bytes())}  {p}\n" for p in sealed), encoding="utf-8"
        )
        return [
            "--manifest", str(dataset / "manifest.json"),
            "--dataset", str(dataset),
            "--seal", str(self.path("audit-seal.txt")),
            "--map", str(self.path("audit-map.json")),
            "--a1", str(self.path("derived-b1.json")),
            "--a1c", str(self.path("derived-conv.json")),
            "--ruling", str(self.path("adjudication.json")), str(self.path("adjudication-key.json")),
            str(self.path("pack")),
            *self.extra,
        ]  # fmt: skip

    @property
    def sealed_extra(self) -> list[str]:
        return [arg for arg in self.extra if arg.endswith(".json") and "re" in Path(arg).name]

    def facts(self) -> dict[str, Any]:
        return json.loads((self.path("dataset") / SPLIT / "facts.json").read_text(encoding="utf-8"))

    def verified(self) -> dict[str, Any]:
        """``verify_labels``' check of the built facts against the synthetic manifest."""
        return vl.check_facts(
            self.path("dataset"),
            self.manifest["entries"],
            vl.convention_ids(CONVENTIONS),
            require_facts=True,
        )


@pytest.fixture()
def audit(tmp_path: Path) -> Audit:
    return Audit(tmp_path / "audit")


def test_the_facts_come_from_the_conventions_reading_and_the_adjudicators_ruling(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    """A1's facts with the conventions applied (source A1) for every slot, the adjudicator's for the slot it ruled
    on (source A1p); no photo, no ``slot`` key; and verify_labels finds every label in them."""
    assert build.main(audit.write()) == 0
    letters = audit.facts()["letters"]
    assert sorted(letters) == [K1, K2]  # a photo shares its letter's truth and has no facts of its own
    assert letters[K1]["slots"]["i0"] == {
        "source": "A1",
        "land": None,
        "from": "2027-03-11",
        "steps": SHIFTED,
        "conventions": ["c02"],
    }
    assert letters[K1]["slots"]["o0"] == {"source": "A1", "undatable": True}
    assert letters[K2]["slots"]["term_end"]["source"] == "A1p"
    assert "ambiguous" in letters[K2]["slots"]["term_end"]
    assert {slot: fact["source"] for slot, fact in letters[K2]["slots"].items()} == {
        "i0": "A1",
        "term_end": "A1p",
        "cancel_by": "A1",
    }
    report = audit.verified()
    assert report["date_problems"] == [] and report["dated_labels_checked"] == 3
    assert report["fact_sources"] == {"A1": 4, "A1p": 1}
    printed = capsys.readouterr().out
    assert "ruled ambiguous: deadline 0, offered 0, contract 1" in printed
    assert "2027" not in printed and "§" not in printed  # ids and counts only


def test_the_build_is_deterministic_and_check_finds_a_stale_file(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = audit.write()
    assert build.main(argv) == 0
    path = audit.path("dataset") / SPLIT / "facts.json"
    first = path.read_bytes()
    assert build.main(argv) == 0 and path.read_bytes() == first
    assert first.endswith(b"\n") and json.loads(first)["split"] == SPLIT
    assert build.main([*argv, "--check"]) == 0
    path.write_bytes(first.replace(b'"A1p"', b'"A1"'))
    capsys.readouterr()
    assert build.main([*argv, "--check"]) == 1
    assert "holdout4/facts.json" in capsys.readouterr().out
    path.unlink()
    assert build.main([*argv, "--check"]) == 1


def _refused(audit: Audit, capsys: pytest.CaptureFixture[str], words: str) -> None:
    assert build.main(audit.write()) == 2
    assert words in capsys.readouterr().err
    assert not (audit.path("dataset") / SPLIT / "facts.json").exists()


def test_a_dated_slot_without_a_fact_is_refused(audit: Audit, capsys: pytest.CaptureFixture[str]) -> None:
    del audit.a1c["letters"]["L001"]["facts"][0]
    _refused(audit, capsys, f"{K1} i0: no fact")


def test_a_ruled_slot_without_the_adjudicators_fact_is_refused(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    del audit.adjudication["cases"]["D001"]["fact"]
    _refused(audit, capsys, f"{K2} term_end: no fact")


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda a: a.map["items"][0].update(id="holdout4-x-K9"), "unknown entry id holdout4-x-K9"),
        (lambda a: a.a1["letters"].update(L009={"slots": {}, "facts": []}), "unknown letter L009"),
        (lambda a: a.key["cases"]["D001"].update(id="holdout4-x-K9"), "unknown entry id holdout4-x-K9"),
        (lambda a: a.adjudication["cases"].update(D002=a.adjudication["cases"]["D001"]), "unknown case D002"),
        (lambda a: a.key["cases"]["D001"].update(slot="i7"), "unknown slot i7"),
    ],
    ids=["map", "reading", "key", "verdict", "slot"],
)
def test_an_unknown_id_is_refused(
    audit: Audit, capsys: pytest.CaptureFixture[str], change: Any, words: str
) -> None:
    change(audit)
    _refused(audit, capsys, words)


def test_an_ambiguous_ruling_names_only_candidates_of_its_pack(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    audit.adjudication["cases"]["D001"]["candidates"] = ["2028-02-29", "2028-04-28"]
    _refused(audit, capsys, "D001: the candidate 2028-04-28 is in neither X nor Y")


def test_an_ambiguous_ruling_needs_two_candidates_and_an_ambiguous_fact(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    audit.adjudication["cases"]["D001"]["candidates"] = ["2028-02-29"]
    _refused(audit, capsys, "D001: an ambiguous verdict names two or more candidates")
    audit.adjudication["cases"]["D001"]["candidates"] = ["2028-02-29", "2028-03-31"]
    audit.adjudication["cases"]["D001"]["fact"] = {
        "source": "A1p",
        "land": None,
        "from": "2028-03-31",
        "steps": [],
    }
    _refused(audit, capsys, "D001: an ambiguous verdict's fact is no ambiguous fact")


def test_a_file_that_is_not_as_sealed_is_refused(audit: Audit, capsys: pytest.CaptureFixture[str]) -> None:
    argv = audit.write()
    seal = audit.path("audit-seal.txt")
    seal.write_text(seal.read_text(encoding="utf-8").replace("derived-conv.json", "elsewhere.json"))
    assert build.main(argv) == 2
    assert "derived-conv.json is not in the seal" in capsys.readouterr().err


def test_the_conventions_reading_must_keep_the_sealed_letters_and_slots(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    del audit.a1c["letters"]["L002"]["slots"]["cancel_by"]
    _refused(audit, capsys, "L002: the conventions reading has slots")


def test_a_letter_whose_bytes_changed_is_read_again(audit: Audit, capsys: pytest.CaptureFixture[str]) -> None:
    """K2's bytes change after the audit (the writer's fix). Its first reading and the ruling on the old bytes no
    longer count: without a fresh blind reading the build is refused; with one (its own map), every slot of K2 comes
    from it (source A1re), and the build is checked like any other."""
    k2 = next(e for e in audit.manifest["entries"] if e["id"] == K2)
    k2["sha256"] = _sha(b"the letter as fixed")
    _refused(audit, capsys, f"{K2}: no blind reading of its letter as it is now")
    fresh = copy.deepcopy(a1_letters()["L002"])
    fresh["slots"]["term_end"] = _slot(None, "ambiguous", candidates=["2028-02-29", "2028-03-31"])
    fresh["facts"][1] = {
        "slot": "term_end",
        "source": "A1",
        "land": None,
        "ambiguous": [{"from": "2027-03-01", "steps": TERM}, {"from": "2028-03-31", "steps": []}],
    }
    re_map = {
        "format": "ev8-audit-map/1",
        "items": [
            {
                "name": "L001.pdf",
                "id": K2,
                "split": SPLIT,
                "batch": "re",
                "photo": False,
                "source_id": None,
                "source_sha256": k2["sha256"],
                "opaque_sha256": _sha(b"opaque copy of the fixed letter"),
            }
        ],
    }
    audit.path("audit-map-re.json").write_text(json.dumps(re_map), encoding="utf-8")
    audit.path("derived-re.json").write_text(
        json.dumps({"format": "ev8-derived/1", "batch": "re", "letters": {"L001": fresh}}), encoding="utf-8"
    )
    audit.extra = [
        "--re-map",
        str(audit.path("audit-map-re.json")),
        "--a1re",
        str(audit.path("derived-re.json")),
    ]
    assert build.main(audit.write()) == 0
    letters = audit.facts()["letters"]
    assert {fact["source"] for fact in letters[K2]["slots"].values()} == {"A1re"}
    assert letters[K1]["slots"]["i0"]["source"] == "A1"
    assert "1 ruling(s) on bytes read again" in capsys.readouterr().out
    assert audit.verified()["date_problems"] == []


def test_the_command_says_what_it_reads(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        build.main(["--help"])
    assert stop.value.code == 0
    usage = capsys.readouterr().out
    for flag in (
        "--seal",
        "--map",
        "--a1",
        "--a1c",
        "--ruling",
        "--re-map",
        "--a1re",
        "--a1re-conv",
        "--check",
    ):
        assert flag in usage, flag


def test_an_ambiguous_ruling_keeps_a_date_of_each_side(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    """The candidates of an ``ambiguous`` verdict are X's date and Y's date: when one side is itself a reading with
    two dates, a ruling between that side's two dates alone drops the other side's date, which only the other-side
    or both-wrong path may do."""
    audit.pack_dates = {"X": "2028-02-29", "Y": "2028-03-31 or 2028-04-28"}
    audit.adjudication["cases"]["D001"]["candidates"] = ["2028-03-31", "2028-04-28"]
    _refused(audit, capsys, "D001: an ambiguous verdict keeps a date of each side")
    audit.adjudication["cases"]["D001"]["candidates"] = ["2028-02-29", "2028-03-31"]
    assert build.main(audit.write()) == 0


def _photo_case(audit: Audit, verdict: dict[str, Any], case: str = "D002") -> None:
    """A case on K1's photo (L003.jpg), slot i0, with the given verdict; its X and Y are K1's label and a later
    date."""
    audit.key["cases"][case] = {"id": K1_PHOTO, "name": "L003.jpg", "slot": "i0", "X": "label", "Y": "a1c"}
    audit.case_dates[case] = {"X": "2027-03-15", "Y": "2027-03-16"}
    audit.adjudication["cases"][case] = verdict


UPHELD = {
    "verdict": "X_right",
    "citations": ["§ 188 Abs. 2 BGB"],
    "why": "-",
    "fact": {"source": "A1p", "land": None, "from": "2027-03-15", "steps": [], "conventions": ["c02"]},
}


def test_a_ruling_on_a_photo_applies_to_its_letter(audit: Audit, capsys: pytest.CaptureFixture[str]) -> None:
    """A photo shares its letter's truth, and the audit comparison sends a photo's slot to the adjudicator like any
    other: its ruling is applied to the letter's slot and counted, never dropped."""
    _photo_case(audit, copy.deepcopy(UPHELD))
    assert build.main(audit.write()) == 0
    slot = audit.facts()["letters"][K1]["slots"]["i0"]
    assert slot["source"] == "A1p" and slot["from"] == "2027-03-15"
    assert "rulings applied: X_right 1, Y_right 0, both_wrong 0, ambiguous 1" in capsys.readouterr().out
    assert audit.verified()["date_problems"] == []


def test_an_ambiguous_ruling_on_a_photo_is_counted_for_its_letter(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    open_due = [{"from": "2027-03-11", "steps": SHIFTED}, {"from": "2027-03-16", "steps": []}]
    _photo_case(
        audit,
        {
            "verdict": "ambiguous",
            "candidates": ["2027-03-15", "2027-03-16"],
            "citations": ["-"],
            "why": "-",
            "fact": {"source": "A1p", "land": None, "ambiguous": open_due},
        },
    )
    assert build.main(audit.write()) == 0
    assert "ambiguous" in audit.facts()["letters"][K1]["slots"]["i0"]
    assert "ruled ambiguous: deadline 1, offered 0, contract 1" in capsys.readouterr().out


def _letter_case(audit: Audit, verdict: dict[str, Any], *, label_is_x: bool, case: str = "D003") -> None:
    """A case on K1 itself (L001.pdf), slot i0: the photo's dispute read again on the letter. The pack draws which
    side is X per case, so ``label_is_x`` says how this case's draw fell."""
    label, other = "2027-03-15", "2027-03-16"
    audit.key["cases"][case] = {
        "id": K1,
        "name": "L001.pdf",
        "slot": "i0",
        "X": "label" if label_is_x else "a1c",
        "Y": "a1c" if label_is_x else "label",
    }
    audit.case_dates[case] = {"X": label, "Y": other} if label_is_x else {"X": other, "Y": label}
    audit.adjudication["cases"][case] = verdict


def test_a_letter_and_its_photo_ruled_apart_must_agree(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same slot ruled on the letter and on its photo: the same verdict and fact are applied once; a fact that
    gives another date is refused, since the two share one truth."""
    _photo_case(audit, copy.deepcopy(UPHELD))
    _letter_case(audit, copy.deepcopy(UPHELD), label_is_x=True)
    assert build.main(audit.write()) == 0
    assert "rulings applied: X_right 1," in capsys.readouterr().out
    audit.adjudication["cases"]["D003"]["fact"]["steps"] = [
        {"op": "forward", "n": 1, "unit": "days", "shift": False}
    ]
    (audit.path("dataset") / SPLIT / "facts.json").unlink()
    _refused(audit, capsys, f"{K1} i0: ruled differently on the letter and its photo (D002, D003)")


def test_a_letter_and_its_photo_whose_sides_were_drawn_apart_agree_when_they_uphold_the_same_side(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    """The photo's case drew the label as X and the letter's case drew it as Y; both uphold the label, so the
    photo's verdict is X_right and the letter's Y_right. They mean the same, and so do two facts that differ only
    in form (another way to the same date, the Land, the event in words): the build goes on and applies the
    letter's fact, counted once under the letter's verdict."""
    _photo_case(audit, copy.deepcopy(UPHELD))
    upheld_as_y = copy.deepcopy(UPHELD) | {"verdict": "Y_right"}
    upheld_as_y["fact"] = {
        "source": "A1p",
        "land": "BY",
        "event": "the letter's date",
        "from": "2027-03-11",
        "steps": SHIFTED,
        "conventions": ["c02"],
    }
    _letter_case(audit, upheld_as_y, label_is_x=False)
    assert build.main(audit.write()) == 0
    assert audit.facts()["letters"][K1]["slots"]["i0"] == upheld_as_y["fact"]
    assert "rulings applied: X_right 0, Y_right 1, both_wrong 0, ambiguous 1" in capsys.readouterr().out
    assert audit.verified()["date_problems"] == []


@pytest.mark.parametrize(
    ("verdict", "fact"),
    [
        ("X_right", {"from": "2027-03-16"}),
        ("X_right", {}),
        ("Y_right", {"conventions": []}),
    ],
    ids=["other-side-upheld", "other-side-upheld-with-the-labels-date", "conventions-differ"],
)
def test_a_letter_and_its_photo_that_mean_different_things_are_refused(
    audit: Audit, capsys: pytest.CaptureFixture[str], verdict: str, fact: dict[str, Any]
) -> None:
    """The letter's case drew the second reading as X. ``X_right`` there upholds the second reading, the opposite of
    the photo's ``X_right`` (with the second reading's date, or even with the label's); and a ruling for the same
    side and date that applies other conventions tags the label differently. Each is refused."""
    _photo_case(audit, copy.deepcopy(UPHELD))
    ruling = copy.deepcopy(UPHELD) | {"verdict": verdict}
    ruling["fact"] = ruling["fact"] | fact
    _letter_case(audit, ruling, label_is_x=False)
    _refused(audit, capsys, f"{K1} i0: ruled differently on the letter and its photo (D002, D003)")


def test_a_facts_meaning_ignores_its_form() -> None:
    """The order of the conventions and of an ambiguous fact's readings, the Land where it changes no date, and the
    event's words are form; the date, the candidates and the conventions are meaning."""

    def meaning(fact: dict[str, Any]) -> tuple[Any, ...]:
        return build.fact_meaning(fact, "D001", "i0")

    dated = {"source": "A1p", "land": None, "from": "2027-03-15", "steps": [], "conventions": ["c02", "c03"]}
    same = dated | {"land": "NW", "event": "posted", "conventions": ["c03", "c02"]}
    assert meaning(dated) == meaning(same)
    assert meaning(dated) != meaning(dated | {"conventions": ["c02"]})
    assert meaning(dated) != meaning(dated | {"from": "2027-03-16"})
    one, two = {"from": "2027-03-15", "steps": []}, {"from": "2027-03-16", "steps": []}
    open_ = {"source": "A1p", "land": None, "ambiguous": [one, two]}
    assert meaning(open_) == meaning(open_ | {"ambiguous": [two, one]})
    assert meaning(open_) != meaning(dated | {"conventions": []})
    assert meaning({"source": "A1p", "undatable": True}) != meaning(open_)


def test_a_key_whose_sides_are_not_the_label_and_the_second_reading_is_refused(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    audit.key["cases"]["D001"]["Y"] = "label"
    _refused(audit, capsys, "D001: X and Y are not the label and the second reading")


def test_a_ruling_on_a_photo_whose_bytes_changed_is_left_out(
    audit: Audit, capsys: pytest.CaptureFixture[str]
) -> None:
    _photo_case(audit, copy.deepcopy(UPHELD))
    photo = next(e for e in audit.manifest["entries"] if e["id"] == K1_PHOTO)
    photo["sha256"] = _sha(b"the photo taken again")
    assert build.main(audit.write()) == 0
    assert audit.facts()["letters"][K1]["slots"]["i0"]["source"] == "A1"
    assert "1 ruling(s) on bytes read again" in capsys.readouterr().out


def test_the_ruled_slots_are_counted_by_the_kinds_the_final_analysis_publishes() -> None:
    from evals import analysis

    assert build.AMBIGUOUS_KINDS == analysis.AMBIGUOUS_KINDS
    assert [build._kind(slot) for slot in ("i0", "i12", "o0", "term_end", "cancel_by")] == [
        "deadline",
        "deadline",
        "offered",
        "contract",
        "contract",
    ]
