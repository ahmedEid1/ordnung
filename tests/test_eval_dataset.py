"""Checks for the benchmark dataset produced by ``evals/generate.py``.

* the manifest loads and every entry's file exists with the recorded SHA-256;
* the truth uses the product's vocabularies (DocumentKind as the generator copies it, which
  ``tests/test_eval_kinds.py`` holds to the product's; item kinds, natures, remedies);
* template variants never leak across splits (A/B = dev, C/D = test, E/F = holdout, G/H = holdout2,
  I/J = holdout3; adversarial letters in test, holdout, holdout2 and holdout3 only), and no deadline-bearing
  sentence recurs in two splits;
* every dated label matches an independent re-derivation (``evals/verify_labels.py``);
* every text PDF contains its key date phrases; invisible text exists only where it is expected;
* regenerating into a temporary directory reproduces the committed dataset byte for byte; only where a
  file differs and the rendering libraries are not the versions the manifest records must two fresh runs
  agree instead;
* the generator's own date arithmetic (``evals/gen/law.py``) reproduces the worked examples of the
  verified legal research — the labels do not come from ``ordnung.rules``.

It imports nothing of ``ordnung`` (``tests/test_gen_imports.py``): it runs where the product is not installed, as
the letters' writers run it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

import pdfplumber
import pytest

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
DATASET = EVALS / "dataset"
MANIFEST = DATASET / "manifest.json"

if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

from gen import law  # noqa: E402
from gen.common import DOCUMENT_KINDS  # noqa: E402

SPLITS = ("dev", "test", "holdout", "holdout2", "holdout3")
# fresh samples of the test split's families and attack classes
HELD_OUT = ("holdout", "holdout2", "holdout3")
ITEM_KINDS = {"deadline", "payment", "appointment", "task", "expiry"}
NATURES = {"objection", "payment", "declaration", "notice", "appointment", "other"}
REMEDIES = {"einspruch", "widerspruch", "klage", "none", "unclear"}
WARNINGS = {"scam", "injection", "hidden_text", "conflicting_dates", "missing_date"}
SPEC_KEYS = {
    "type",
    "anchor",
    "amount",
    "unit",
    "delivery_scope",
    "posted_on",
    "anchor_date",
    "date",
    "time",
    "shift",
}
#: The dataset's size cap: every split's letters, the final run's included.
MAX_TOTAL_BYTES = 40 * 1024 * 1024


def fits(total_bytes: int) -> bool:
    """Whether a dataset of ``total_bytes`` is under the cap."""
    return total_bytes < MAX_TOTAL_BYTES


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return manifest["entries"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------------------------------
# manifest and files
# --------------------------------------------------------------------------------------------------


def test_manifest_loads(manifest: dict[str, Any]) -> None:
    entries = _entries(manifest)
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    split = {name: [e for e in entries if e["split"] == name] for name in SPLITS}
    assert sum(map(len, split.values())) == len(entries)
    assert 20 <= len(split["dev"]) <= 35
    assert 50 <= len(split["test"]) <= 70
    for name in HELD_OUT:
        assert 50 <= len(split[name]) <= 70, name  # a fresh sample about the size of test
    for name in ("test", *HELD_OUT):
        assert sum(1 for e in split[name] if e["family"] == "adversarial" and not e["photo"]) >= 10, name
        assert all(e["id"].startswith(f"{name}-") for e in split[name]), name
    scored = {name: sum(1 for e in split[name] for item in e["truth"]["items"] if item["expected_due"] not in (None, "ambiguous"))
              for name in ("test", *HELD_OUT)}  # fmt: skip
    for name in HELD_OUT:
        assert abs(scored[name] - scored["test"]) <= 10, scored  # dated obligations of a similar number
    photos = [e for e in entries if e["photo"]]
    assert 0.12 <= len(photos) / len(entries) <= 0.3
    for name in HELD_OUT:
        assert 0.12 <= sum(e["photo"] for e in split[name]) / len(split[name]) <= 0.25, name
    assert fits(manifest["total_bytes"])
    for name in SPLITS:
        assert manifest["counts"][name]["entries"] == len(split[name]), name
    families = {e["family"] for e in entries}
    assert len(families) == 13  # 12 template families + adversarial


def test_the_dataset_has_room_for_the_final_run_s_letters() -> None:
    """holdout4 at twice holdout3's size and the newkinds letters take the dataset to about 31.5 MB: the cap these
    checks hold it to is 40 MiB."""
    assert fits(31_500_000) and fits(40 * 1024 * 1024 - 1)
    assert not fits(40 * 1024 * 1024)


def test_files_exist_with_matching_sha(manifest: dict[str, Any]) -> None:
    listed = set()
    for entry in _entries(manifest):
        path = DATASET / entry["file"]
        assert path.is_file(), entry["file"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["file"]
        assert len(data) == entry["bytes"]
        assert entry["file"].startswith(f"{entry['split']}/")
        listed.add(path.name)
    on_disk = {p.name for p in DATASET.glob("*/*") if p.suffix in (".pdf", ".jpg")}
    assert on_disk == listed, "files on disk that the manifest does not list (or vice versa)"


def test_truth_schema(manifest: dict[str, Any]) -> None:
    for entry in _entries(manifest):
        truth = entry["truth"]
        where = entry["id"]
        assert truth["kind"] in DOCUMENT_KINDS, where
        also = truth["kind_also_accepted"]
        assert set(also) <= set(DOCUMENT_KINDS) and truth["kind"] not in also, where
        assert truth["remedy_type"] in REMEDIES, where
        assert set(truth["expected_warnings"]) <= WARNINGS, where
        assert truth["sender_name"], where
        today = date.fromisoformat(entry["today"])
        if truth["document_date"] is not None:
            assert date.fromisoformat(truth["document_date"]) <= today, where
        else:
            assert "missing_date" in truth["expected_warnings"], where
        assert entry["authority_region"] in (None, *law.LAENDER), where
        for item in [*truth["items"], *truth["optional_items"]]:
            assert item["kind"] in ITEM_KINDS and item["nature"] in NATURES, where
            assert set(item["spec"]) == SPEC_KEYS, where
            assert item["derivation"], where
            due = item["expected_due"]
            if due == "ambiguous":
                assert len(item["candidates"]) == 2 and truth["expect_low_confidence"], where
            elif due is not None:
                assert date.fromisoformat(due) >= today, where
            if item["spec"]["delivery_scope"] is not None:
                assert item["spec"]["delivery_scope"] in ("ao", "vwvfg", "sgbx"), where
        for item in truth["items"]:
            if item.get("region_sensitive"):
                assert entry["authority_region"] is not None, (
                    f"{where}: region-sensitive label without a known Land"
                )
        if truth["contract"] is not None:
            c = truth["contract"]
            assert date.fromisoformat(c["expected_cancel_by"]) < date.fromisoformat(
                c["expected_current_term_end"]
            ), where
        if "hidden_text" in truth["expected_warnings"]:
            assert entry["photo"] or entry["hidden_phrases"], where


def test_splits_do_not_share_variants(manifest: dict[str, Any]) -> None:
    variants = {
        name: {(e["family"], e["variant"]) for e in _entries(manifest) if e["split"] == name and e["family"] != "adversarial"}
        for name in SPLITS
    }  # fmt: skip
    for i, name in enumerate(SPLITS):
        for other in SPLITS[i + 1 :]:
            assert not variants[name] & variants[other], (name, other)
    assert {v for _, v in variants["dev"]} == {"A", "B"}
    assert {v for _, v in variants["test"]} == {"C", "D"}
    assert {v for _, v in variants["holdout"]} == {"E", "F"}
    assert {v for _, v in variants["holdout2"]} == {"G", "H"}
    assert {v for _, v in variants["holdout3"]} == {"I", "J"}
    assert all(e["family"] != "adversarial" for e in _entries(manifest) if e["split"] == "dev")
    families = {f for f, _ in variants["dev"]}
    for name in SPLITS:  # every template family is represented in every split, with both of its variants
        assert {(f, v) for f in families for v in {v for _, v in variants[name]}} == variants[name], name
    # the holdout letters come from new senders, and the holdout2 and holdout3 letters from senders of no other split
    senders = {
        name: {e["truth"]["sender_name"] for e in _entries(manifest) if e["split"] == name} for name in SPLITS
    }
    assert not senders["holdout"] & (senders["dev"] | senders["test"])
    assert not senders["holdout2"] & (senders["dev"] | senders["test"] | senders["holdout"])
    assert not senders["holdout3"] & (
        senders["dev"] | senders["test"] | senders["holdout"] | senders["holdout2"]
    )


def test_each_split_takes_only_its_own_template_variants() -> None:
    """``Case`` refuses a template variant of another split, and adversarial letters in dev."""
    from gen.common import SPLIT_VARIANTS, Case, truth
    from gen.pdf import Letter, Org

    letter = Letter(org=Org(name="Muster GmbH", kind="company", street="Weg 1", postcode="12345", city="Musterstadt"),
                    recipient=None, info=[], subject="Test", blocks=[])  # fmt: skip

    def case(split: str, family: str, variant: str) -> Case:
        t = truth(
            kind="invoice", sender="Muster GmbH", document_date=None, references=[], amounts=[], items=[]
        )
        return Case(id=f"{split}-{family}-{variant}1", split=split, family=family, variant=variant, letter=letter,
                    truth=t, today=date(2026, 1, 1), authority_region=None, key_phrases=[])  # fmt: skip

    assert SPLIT_VARIANTS == {
        "dev": ("A", "B"),
        "test": ("C", "D"),
        "holdout": ("E", "F"),
        "holdout2": ("G", "H"),
        "holdout3": ("I", "J"),
    }
    for split, own in SPLIT_VARIANTS.items():
        for variant in "ABCDEFGHIJ":
            if variant in own:
                case(split, "invoice_relative", variant)
            else:
                with pytest.raises(AssertionError):
                    case(split, "invoice_relative", variant)
    case("holdout", "adversarial", "scam")
    case("holdout2", "adversarial", "scam")
    case("holdout3", "adversarial", "scam")
    with pytest.raises(AssertionError):
        case("dev", "adversarial", "scam")


#: The final split; how many standard text letters with a dated scored item each of its template families holds at
#: least, when that family's letters carry a dated scored item in every earlier split (ten of the twelve: contract
#: confirmations and price increases carry none); and how many it holds at least in all.
FINAL_SPLIT = "holdout4"
DATED_TEXT_LETTERS_PER_FAMILY = 4
DATED_TEXT_LETTERS_IN_ALL = 48
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def dated_text_letter(entry: dict[str, Any]) -> bool:
    """A standard text letter (a PDF, not a photo, not adversarial) with at least one scored item that has a date."""
    return (
        not entry["photo"]
        and entry["family"] != "adversarial"
        and entry.get("media_type", "application/pdf") == "application/pdf"
        and any(_ISO_DAY.fullmatch(str(item.get("expected_due"))) for item in entry["truth"]["items"])
    )


def dated_families(entries: list[dict[str, Any]]) -> list[str]:
    """The template families whose letters carry a dated scored item in every earlier split that has letters."""
    earlier = [name for name in SPLITS if any(e["split"] == name for e in entries)]
    return sorted(
        family
        for family in {e["family"] for e in entries if e["split"] in earlier and e["family"] != "adversarial"}
        if all(
            any(e["split"] == name and e["family"] == family and dated_text_letter(e) for e in entries)
            for name in earlier
        )
    )


def families_short_of_dated_text_letters(
    entries: list[dict[str, Any]], split: str = FINAL_SPLIT
) -> dict[str, int]:
    """The families of :func:`dated_families` with fewer than :data:`DATED_TEXT_LETTERS_PER_FAMILY` dated text
    letters in ``split``, with how many each has; none while ``split`` has no letters."""
    letters = [e for e in entries if e["split"] == split]
    if not letters:
        return {}
    counts = Counter(e["family"] for e in letters if dated_text_letter(e))
    return {
        family: counts[family]
        for family in dated_families(entries)
        if counts[family] < DATED_TEXT_LETTERS_PER_FAMILY
    }


def dated_text_letters_in(entries: list[dict[str, Any]], split: str = FINAL_SPLIT) -> int | None:
    """How many dated text letters ``split`` holds in all; ``None`` while it has no letters."""
    letters = [e for e in entries if e["split"] == split]
    return sum(map(dated_text_letter, letters)) if letters else None


def test_holdout4_has_four_dated_text_letters_in_every_family_with_dated_items(
    manifest: dict[str, Any],
) -> None:
    """Each template family whose letters carry a dated scored item in every earlier split has at least four
    standard text letters with a dated scored item in holdout4, and holdout4 has at least 48 such letters in all (it
    holds while holdout4 has no letters, and binds once it has)."""
    entries = _entries(manifest)
    assert families_short_of_dated_text_letters(entries) == {}
    assert (dated_text_letters_in(entries) or DATED_TEXT_LETTERS_IN_ALL) >= DATED_TEXT_LETTERS_IN_ALL


def holdout3_twice(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The entries with holdout3's letters copied twice as the final split, in place of any it has: the composition
    the brief asks of it (twice holdout3's letters, photos and scored items), made the way holdout3 is made."""
    copies = [
        {**copy.deepcopy(e), "id": f"{e['id']}-{suffix}", "split": FINAL_SPLIT}
        for suffix in ("K", "M")
        for e in entries
        if e["split"] == "holdout3"
    ]
    return [*(e for e in entries if e["split"] != FINAL_SPLIT), *copies]


def test_a_final_split_made_like_holdout3_meets_the_per_family_rule(manifest: dict[str, Any]) -> None:
    """A holdout4 made the way holdout3 is made, at twice its size, meets the rule as it stands: the families whose
    letters carry no dated item in the earlier splits are not asked for four."""
    entries = holdout3_twice(_entries(manifest))
    assert len(dated_families(entries)) == 10
    assert families_short_of_dated_text_letters(entries) == {}
    assert (dated_text_letters_in(entries) or 0) >= DATED_TEXT_LETTERS_IN_ALL


def test_the_per_family_rule_counts_dated_text_letters_only() -> None:
    """A photo, an adversarial letter and a letter whose only scored item has no single date do not count, and a
    family whose letters carried no dated item before is not asked for any."""

    def letter(
        cid: str, split: str, family: str, due: str | None = "2027-03-15", **more: Any
    ) -> dict[str, Any]:
        items = [{"expected_due": due}]
        return {
            "id": cid,
            "split": split,
            "family": family,
            "photo": False,
            "truth": {"items": items},
            **more,
        }

    earlier = [letter(f"test-{f}-C1", "test", f) for f in ("fine", "invoice", "tax")]
    earlier.append(letter("test-contract-C1", "test", "contract", due=None))
    final = [letter(f"holdout4-fine-K{n}", FINAL_SPLIT, "fine") for n in range(1, 5)]
    final += [letter(f"holdout4-tax-K{n}", FINAL_SPLIT, "tax") for n in range(1, 4)]
    final += [
        letter("holdout4-tax-K4-photo", FINAL_SPLIT, "tax", photo=True),
        letter("holdout4-tax-M1", FINAL_SPLIT, "tax", media_type="image/jpeg"),
        letter("holdout4-tax-N1", FINAL_SPLIT, "tax", due="ambiguous"),
        letter("holdout4-tax-N2", FINAL_SPLIT, "tax", due=None),
        letter("holdout4-adversarial-x", FINAL_SPLIT, "adversarial"),
    ]
    assert families_short_of_dated_text_letters(earlier) == {}
    assert dated_families(earlier) == ["fine", "invoice", "tax"]  # a family never dated before is not bound
    assert families_short_of_dated_text_letters([*earlier, *final]) == {"invoice": 0, "tax": 3}
    assert dated_text_letters_in(earlier) is None and dated_text_letters_in([*earlier, *final]) == 7
    final += [
        letter("holdout4-tax-K5", FINAL_SPLIT, "tax"),
        *(letter(f"holdout4-invoice-K{n}", FINAL_SPLIT, "invoice") for n in range(4)),
    ]
    assert families_short_of_dated_text_letters([*earlier, *final]) == {}


def test_photos_share_truth_with_their_pdf(manifest: dict[str, Any]) -> None:
    by_id = {e["id"]: e for e in _entries(manifest)}
    for entry in _entries(manifest):
        if not entry["photo"]:
            assert entry["source_id"] is None
            continue
        source = by_id[entry["source_id"]]
        assert not source["photo"] and source["pages"] == 1
        assert entry["truth"] == source["truth"]
        assert (entry["split"], entry["family"], entry["variant"], entry["today"]) == (
            source["split"], source["family"], source["variant"], source["today"],
        )  # fmt: skip
        assert entry["file"].endswith(".jpg")
        assert (DATASET / entry["file"]).read_bytes()[:3] == b"\xff\xd8\xff"


# --------------------------------------------------------------------------------------------------
# document content
# --------------------------------------------------------------------------------------------------


def _dark_fills(page: Any) -> list[tuple[float, float, float, float]]:
    out = []
    for shape in [*page.rects, *page.curves]:
        color = shape.get("non_stroking_color")
        if shape.get("fill") and isinstance(color, tuple | list) and len(color) == 3:
            if 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2] < 0.6:
                out.append((shape["x0"], shape["top"], shape["x1"], shape["bottom"]))
    return out


def _invisible_chars(page: Any) -> int:
    """Text under 3 pt, off the page, or white and not on a dark fill: no reader sees it."""
    fills = _dark_fills(page)
    hidden = 0
    for ch in page.chars:
        if not ch["text"].strip():
            continue
        color = ch.get("non_stroking_color")
        white = isinstance(color, tuple | list) and len(color) in (1, 3) and min(color) >= 0.95
        cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2
        on_dark = any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in fills)
        off_page = ch["x0"] < 0 or ch["x1"] > page.width or ch["top"] < 0 or ch["bottom"] > page.height
        if ch["size"] < 3 or off_page or (white and not on_dark):
            hidden += 1
    return hidden


class PdfRead(NamedTuple):
    pages: int
    text: str  # every page's text, whitespace folded
    invisible_chars: int


@pytest.fixture(scope="module")
def pdf_reads(manifest: dict[str, Any]) -> dict[str, PdfRead]:
    """Every text PDF of the dataset, opened once for the tests below that read them."""
    reads = {}
    for entry in _entries(manifest):
        if entry["photo"]:
            continue
        with pdfplumber.open(DATASET / entry["file"]) as pdf:
            text = _norm(" ".join(page.extract_text() or "" for page in pdf.pages))
            invisible = sum(_invisible_chars(page) for page in pdf.pages)
            reads[entry["id"]] = PdfRead(pages=len(pdf.pages), text=text, invisible_chars=invisible)
    return reads


def test_text_pdfs_contain_their_key_date_phrases(
    manifest: dict[str, Any], pdf_reads: dict[str, PdfRead]
) -> None:
    for entry in _entries(manifest):
        if entry["photo"]:
            continue
        assert entry["key_phrases"], entry["id"]
        read = pdf_reads[entry["id"]]
        assert read.pages == entry["pages"]
        text = read.text
        for phrase in [*entry["key_phrases"], *entry["hidden_phrases"]]:
            assert _norm(phrase) in text, f"{entry['id']}: {phrase!r} not found in the PDF text"
        if entry["truth"]["document_date"] and entry["language"] == "de" and entry["family"] != "adversarial":
            d = date.fromisoformat(entry["truth"]["document_date"])
            assert f"{d.day:02d}.{d.month:02d}.{d.year}" in text, entry["id"]


def test_invisible_text_only_where_expected(manifest: dict[str, Any], pdf_reads: dict[str, PdfRead]) -> None:
    """Text under 3 pt, off the page, or white and not on a dark fill: no reader sees it."""
    for entry in _entries(manifest):
        if entry["photo"]:
            continue
        hidden_chars = pdf_reads[entry["id"]].invisible_chars
        expected = "hidden_text" in entry["truth"]["expected_warnings"]
        assert (hidden_chars > 0) == expected, f"{entry['id']}: {hidden_chars} invisible characters"


def test_labels_survive_the_independent_recheck() -> None:
    """``evals/verify_labels.py`` re-derives every dated label from facts read off each letter, with its own
    calculator (datetime + holidays package; no code shared with evals/gen or ordnung.rules), checks that the
    letters state what the truth claims, and that no deadline sentence recurs in letters of two splits. The facts
    of dev, test, holdout, holdout2 and holdout3 were read off each letter by hand. A final split's (holdout4,
    newkinds) are not a person's: they come from the blind audit, an auditor's reading of each letter sealed before
    any comparison with the labels (and, where it disagreed with a label, the adjudication's), each fact with its
    source. See evals/dataset/VERIFICATION.md."""
    import verify_labels

    report = verify_labels.run(DATASET)
    # 92 of dev and test, 60 of holdout, 60 of holdout2, 60 of holdout3
    assert report["dated_labels_checked"] >= 272
    assert not report["date_problems"], report["date_problems"]
    assert not report["text_problems"], report["text_problems"]
    assert not report["shared_split_sentences"], report["shared_split_sentences"]
    assert not report["photo_problems"], report["photo_problems"]
    assert not report["land_window_problems"], report["land_window_problems"]


@pytest.mark.parametrize(
    ("region", "posted", "scope", "flagged"),
    [
        ("HH", "2025-03-03", "vwvfg", True),  # before the HmbVwVfG change took effect (14.05.2025)
        ("HH", "2025-05-14", "vwvfg", False),
        ("BW", "2025-02-06", "vwvfg", True),
        ("BW", "2025-02-07", "vwvfg", False),
        ("SH", "2025-06-09", "vwvfg", True),
        ("SH", "2024-12-20", "vwvfg", False),  # the old 3-day rule, certain in every Land
        ("SH", "2025-03-03", "sgbx", False),  # not a Land VwVfG label
        ("NW", "2025-01-02", "vwvfg", False),  # NW, BY and MV: 4 days from 1 Jan 2025
    ],
)
def test_land_vwvfg_labels_avoid_the_uncertain_start_windows(
    region: str, posted: str, scope: str, flagged: bool
) -> None:
    """``remedy`` counts 4 days from 2025-01-01 in every Land; the guard catches a letter posted where that is not sure."""
    import verify_labels

    item = {"expected_due": "2025-12-31", "spec": {"delivery_scope": scope, "posted_on": posted}}
    entry = {"id": "x", "photo": False, "authority_region": region,
             "truth": {"document_date": None, "items": [item], "optional_items": [], "contract": None}}  # fmt: skip
    assert bool(verify_labels.check_land_windows([entry])) == flagged


@pytest.mark.parametrize("pair", [(a, b) for i, a in enumerate(SPLITS) for b in SPLITS[i + 1 :]])
def test_the_wording_check_covers_every_pair_of_splits(pair: tuple[str, str]) -> None:
    """A deadline sentence shared by any two splits is reported (it used to compare dev with test only)."""
    import verify_labels

    shared = "Bitte antworten Sie uns binnen vierzehn Tagen nach dem Datum dieses Schreibens schriftlich."
    entries = [{"id": f"{name}-x-A1", "split": name, "photo": False} for name in SPLITS]
    texts = {  # each other split has a sentence of its own (named by a letter: digits are normalised away)
        e["id"]: shared
        if e["split"] in pair
        else f"Ein Satz ohne jede Frist und ohne Termin, nur zur Info ({'VWXYZ'[SPLITS.index(e['split'])]})."
        for e in entries
    }
    assert verify_labels.shared_deadline_sentences(entries, texts) == [f"{'+'.join(sorted(pair))}: {shared}"]


# --------------------------------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------------------------------


def _generate(out: Path) -> dict[str, Any]:
    subprocess.run(
        [sys.executable, str(EVALS / "generate.py"), "--out", str(out), "--quiet"],
        check=True,
        cwd=ROOT,
        timeout=600,
    )
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def _without_bytes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [{k: v for k, v in e.items() if k not in ("sha256", "bytes")} for e in manifest["entries"]]


def _differing(manifest: dict[str, Any], here: Path, there: Path) -> list[str]:
    """The files ``manifest`` lists whose bytes in ``here`` and in ``there`` differ (or that one of them lacks)."""

    def read(path: Path) -> bytes | None:
        return path.read_bytes() if path.is_file() else None

    return [e["file"] for e in manifest["entries"] if read(here / e["file"]) != read(there / e["file"])]


def _check_generation(
    generate: Callable[[Path], dict[str, Any]], out: Path, committed: dict[str, Any], dataset: Path
) -> int:
    """Generate the dataset once into ``out`` and compare it with the committed one (``dataset``, whose manifest
    is ``committed``): every file byte for byte, and the manifest apart from the rendering libraries it records.
    Only when a file differs and those libraries differ too (a newer Pillow may draw the same letter in other
    bytes) is it generated a second time, and the two runs must agree bit for bit. Returns how many runs it made."""
    first = generate(out / "a")
    differ = _differing(first, out / "a", dataset)
    if not differ:
        assert {k: v for k, v in first.items() if k != "environment"} == {
            k: v for k, v in committed.items() if k != "environment"
        }, "the committed manifest is not what the generator writes"
        if first["environment"] == committed["environment"]:
            assert (out / "a" / "manifest.json").read_bytes() == (dataset / "manifest.json").read_bytes()
        return 1
    assert first["environment"] != committed["environment"], (
        f"{len(differ)} files differ from the committed dataset under the libraries it was made with: {differ[:5]}"
    )
    second = generate(out / "b")
    again = _differing(second, out / "a", out / "b")
    assert not again, f"two runs differ: {again[:5]}"
    assert (out / "a" / "manifest.json").read_bytes() == (out / "b" / "manifest.json").read_bytes()
    return 2


def _stand_in(
    runs: list[dict[str, bytes]], environment: dict[str, str]
) -> tuple[Callable[[Path], dict[str, Any]], list[Path]]:
    """A stand-in for ``evals/generate.py``: its n-th run writes ``runs[n]`` (file -> bytes) and their manifest."""
    made: list[Path] = []

    def generate(out: Path) -> dict[str, Any]:
        files = runs[len(made)]
        made.append(out)
        entries = []
        for name, data in files.items():
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(data)
            entries.append({"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        manifest = {"environment": environment, "entries": entries}
        (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    return generate, made


LETTERS = {"dev/dev-a.pdf": b"%PDF one", "test/test-b.jpg": b"\xff\xd8\xff two"}
OLD_LIBRARIES = {"pillow": "12.3.0"}
NEW_LIBRARIES = {"pillow": "13.0.0"}


def _committed(tmp_path: Path, environment: dict[str, str]) -> tuple[Path, dict[str, Any]]:
    generate, _ = _stand_in([LETTERS], environment)
    return tmp_path / "committed", generate(tmp_path / "committed")


def test_a_generation_equal_to_the_committed_files_is_made_once(tmp_path: Path) -> None:
    """With newer rendering libraries than the manifest records, the files are still compared with the committed
    ones first, and when they are equal, nothing is generated a second time."""
    dataset, committed = _committed(tmp_path, OLD_LIBRARIES)
    generate, made = _stand_in([LETTERS, LETTERS], NEW_LIBRARIES)
    assert _check_generation(generate, tmp_path / "out", committed, dataset) == 1
    assert len(made) == 1


def test_a_file_that_differs_under_the_recorded_libraries_fails(tmp_path: Path) -> None:
    dataset, committed = _committed(tmp_path, OLD_LIBRARIES)
    generate, made = _stand_in([{**LETTERS, "dev/dev-a.pdf": b"%PDF other"}], OLD_LIBRARIES)
    with pytest.raises(AssertionError, match=r"dev/dev-a\.pdf"):
        _check_generation(generate, tmp_path / "out", committed, dataset)
    assert len(made) == 1


def test_a_manifest_that_differs_beyond_its_libraries_fails(tmp_path: Path) -> None:
    dataset, committed = _committed(tmp_path, OLD_LIBRARIES)
    generate, _ = _stand_in([LETTERS], NEW_LIBRARIES)
    with pytest.raises(AssertionError, match="manifest"):
        _check_generation(generate, tmp_path / "out", {**committed, "version": 2}, dataset)


def test_under_other_libraries_a_changed_file_needs_two_runs_that_agree(tmp_path: Path) -> None:
    """A newer library may draw the same letter in other bytes: then two runs must agree bit for bit."""
    dataset, committed = _committed(tmp_path, OLD_LIBRARIES)
    redrawn = {**LETTERS, "test/test-b.jpg": b"\xff\xd8\xff redrawn"}
    generate, made = _stand_in([redrawn, redrawn], NEW_LIBRARIES)
    assert _check_generation(generate, tmp_path / "out", committed, dataset) == 2
    assert len(made) == 2
    generate, _ = _stand_in([redrawn, {**redrawn, "test/test-b.jpg": b"\xff\xd8\xff again"}], NEW_LIBRARIES)
    with pytest.raises(AssertionError, match=r"test/test-b\.jpg"):
        _check_generation(generate, tmp_path / "again", committed, dataset)


#: The earlier splits' manifest as it stood before the Länder table reworded conventions c03 and c07, with those two
#: texts left out: the sha256 of its canonical JSON (name, version, generator, the c-conventions, the five splits'
#: counts and entries, file hashes included). Nothing else of it may change with a convention's wording; a deliberate
#: change to an earlier split's letters or labels updates this pin and says why in VERIFICATION.md.
EARLIER_SPLITS_MASKED_SHA256 = "d4e8de39a48ede5b4078939f7bee125dba1a1298ef31a2455bd7d25c8ea93bf1"
#: The conventions whose wording the Länder table changed (their ids and disputed flags stay).
REWORDED_FOR_THE_LAENDER = ("c03", "c07")


def _earlier_splits_masked(manifest: dict[str, Any]) -> str:
    conventions = [
        {**c, "text": None} if c["id"] in REWORDED_FOR_THE_LAENDER else c
        for c in manifest["conventions"]
        if re.fullmatch(r"c\d+", c["id"])
    ]
    doc = {
        "name": manifest["name"],
        "version": manifest["version"],
        "generator": manifest["generator"],
        "conventions": conventions,
        "counts": {split: n for split, n in manifest["counts"].items() if split in SPLITS},
        "entries": sorted((e for e in manifest["entries"] if e["split"] in SPLITS), key=lambda e: e["id"]),
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def test_the_earlier_splits_changed_only_in_two_conventions_words(manifest: dict[str, Any]) -> None:
    """Every letter, label and derivation of dev … holdout3 is as it was before the Länder table; of the manifest
    only the texts of c03 and c07 changed, and they still carry their ids and disputed flags."""
    assert _earlier_splits_masked(manifest) == EARLIER_SPLITS_MASKED_SHA256
    flags = {c["id"]: c["disputed"] for c in manifest["conventions"]}
    assert (flags["c03"], flags["c07"]) == (True, True)


def test_c03_and_c07_say_what_the_land_table_counts(manifest: dict[str, Any]) -> None:
    """The two conventions about a Land authority's letter name the table of ``evals/gen/law.py`` in plain words: the
    Land with the 3rd day, the Länder whose 4th day starts later and on which day, the Länder where an older
    procedure keeps the 3rd, and the Länder no such letter may come from."""
    texts = {c["id"]: c["text"] for c in manifest["conventions"]}
    c03, c07 = texts["c03"], texts["c07"]
    assert "evals/law/laender.txt" in c03 and "evals/law/laender.txt" in c07
    assert all(law.LAND_NAMES[land] in c03 for land in law.LAND_VWVFG_THIRD_DAY)
    for land, start in law.LAND_VWVFG_FOURTH_DAY_FROM.items():
        if start != date(2025, 1, 1):
            assert law.LAND_NAMES[land] in c03 and start.isoformat() in c03, land
    assert all(law.LAND_NAMES[land] in c03 for land in law.LAND_VWVFG_OLD_PROCEDURES)
    assert all(law.LAND_NAMES[land] in c07 for land in law.LAND_VWVFG_UNVERIFIED)
    assert "evals/gen/law.py" in c07


def test_generation_is_byte_identical(tmp_path: Path, manifest: dict[str, Any]) -> None:
    def generate(out: Path) -> dict[str, Any]:
        made = _generate(out)
        assert {e["split"] for e in made["entries"]} == set(SPLITS) == set(made["counts"])
        # The labels never depend on the environment.
        assert _without_bytes(made) == _without_bytes(manifest), (
            "dataset is stale — run `.venv/bin/python evals/generate.py`"
        )
        return made

    _check_generation(generate, tmp_path, manifest, DATASET)


# --------------------------------------------------------------------------------------------------
# the generator's arithmetic against the verified research examples (docs: legal research notes)
# --------------------------------------------------------------------------------------------------


def _remedy(posted: date, scope: str, region: str | None) -> tuple[str, str]:
    """A posted decision's one-month remedy period; a Land authority's (``vwvfg``) sits in ``region``."""
    why = law.Derivation()
    notified = law.deemed_delivery(posted, scope, region, why, land=region)
    end = law.period_end(notified, 1, "months", region, why, shift=True, shift_citation="test")
    return notified.isoformat(), end.isoformat()


@pytest.mark.parametrize(
    ("posted", "scope", "region", "notified", "end"),
    [
        (date(2026, 9, 29), "ao", "NW", "2026-10-05", "2026-11-05"),  # Sat 3.10. holiday → Mon 5.10.
        (date(2026, 9, 24), "ao", None, "2026-09-28", "2026-10-28"),
        (date(2026, 12, 22), "ao", "BE", "2026-12-28", "2027-01-28"),
        (date(2026, 2, 27), "ao", "HE", "2026-03-03", "2026-04-07"),  # end on Karfreitag → Tue after Easter
        (date(2026, 10, 28), "ao", "SN", "2026-11-02", "2026-12-02"),
        (date(2024, 12, 30), "ao", "NW", "2025-01-02", "2025-02-03"),  # old 3-day rule
        (date(2025, 1, 2), "ao", "NW", "2025-01-06", "2025-02-06"),
        (date(2025, 1, 2), "ao", "BY", "2025-01-07", "2025-02-07"),  # Heilige Drei Könige in BY
        (date(2025, 12, 31), "ao", None, "2026-01-05", "2026-02-05"),
        (date(2025, 10, 27), "ao", "NI", "2025-11-03", "2025-12-03"),  # Reformationstag in NI
        (date(2025, 10, 27), "ao", "BY", "2025-10-31", "2025-12-01"),
        (date(2026, 9, 29), "sgbx", None, "2026-10-03", "2026-11-03"),  # no fiction shift outside tax law
        (date(2026, 11, 27), "sgbx", "BE", "2026-12-01", "2027-01-04"),
        (date(2026, 12, 23), "sgbx", None, "2026-12-27", "2027-01-27"),
        (date(2026, 11, 25), "sgbx", None, "2026-11-29", "2026-12-29"),
        (date(2026, 10, 27), "vwvfg", "NI", "2026-10-31", "2026-11-30"),
        (date(2026, 9, 29), "vwvfg", "NW", "2026-10-03", "2026-11-03"),
    ],
)
def test_law_reproduces_research_examples(
    posted: date, scope: str, region: str | None, notified: str, end: str
) -> None:
    assert _remedy(posted, scope, region) == (notified, end)


@pytest.mark.parametrize(
    ("served", "region", "end"),
    [
        (date(2026, 9, 17), "BY", "2026-10-01"),
        (date(2026, 9, 19), "NW", "2026-10-05"),
        (date(2026, 12, 11), "BE", "2026-12-28"),
    ],
)
def test_law_two_week_fine_examples(served: date, region: str, end: str) -> None:
    why = law.Derivation()
    assert (
        law.period_end(served, 2, "weeks", region, why, shift=True, shift_citation="test").isoformat() == end
    )


def test_law_contract_examples() -> None:
    assert law.term_end(date(2024, 11, 15), 24) == date(2026, 11, 14)
    assert law.latest_notice_receipt(date(2026, 11, 14), 1, "months") == date(2026, 10, 14)
    assert law.latest_notice_receipt(date(2026, 12, 31), 3, "months") == date(2026, 9, 30)
    assert law.latest_notice_receipt(date(2027, 2, 28), 1, "months") == date(2027, 1, 31)
    assert law.latest_notice_receipt(date(2027, 5, 31), 3, "months") == date(2027, 2, 28)


def test_law_holiday_tables_match_the_holidays_package() -> None:
    law.cross_check_with_holidays_package(range(2024, 2028))
    assert law.easter_sunday(2025) == date(2025, 4, 20)
    assert law.easter_sunday(2026) == date(2026, 4, 5)
    assert law.easter_sunday(2027) == date(2027, 3, 28)
