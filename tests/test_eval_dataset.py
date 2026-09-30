"""Checks for the benchmark dataset produced by ``evals/generate.py`` (SPEC §17).

* the manifest loads and every entry's file exists with the recorded SHA-256;
* the truth uses the product's vocabularies (DocumentKind, item kinds, natures, remedies);
* template variants never leak across splits (A/B = dev, C/D = test, E/F = holdout; adversarial
  letters in test and holdout only), and no deadline-bearing sentence recurs in two splits;
* every dated label matches an independent re-derivation (``evals/verify_labels.py``);
* every text PDF contains its key date phrases; invisible text exists only where it is expected;
* regenerating into a temporary directory is byte-identical (and matches the committed dataset
  when the rendering libraries are the versions recorded in the manifest);
* the generator's own date arithmetic (``evals/gen/law.py``) reproduces the worked examples of the
  verified legal research — the labels do not come from ``ordnung.rules``.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from ordnung.models import DOCUMENT_KINDS

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
DATASET = EVALS / "dataset"
MANIFEST = DATASET / "manifest.json"

if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

from gen import law  # noqa: E402

SPLITS = ("dev", "test", "holdout")
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
    assert 50 <= len(split["holdout"]) <= 70  # a fresh sample about the size of test
    for name in ("test", "holdout"):
        assert sum(1 for e in split[name] if e["family"] == "adversarial" and not e["photo"]) >= 10, name
        assert all(e["id"].startswith(f"{name}-") for e in split[name]), name
    scored = {name: sum(1 for e in split[name] for item in e["truth"]["items"] if item["expected_due"] not in (None, "ambiguous"))
              for name in ("test", "holdout")}  # fmt: skip
    assert abs(scored["holdout"] - scored["test"]) <= 10, scored  # dated obligations of a similar number
    photos = [e for e in entries if e["photo"]]
    assert 0.12 <= len(photos) / len(entries) <= 0.3
    assert 0.12 <= sum(e["photo"] for e in split["holdout"]) / len(split["holdout"]) <= 0.25
    assert manifest["total_bytes"] < 25 * 1024 * 1024
    for name in SPLITS:
        assert manifest["counts"][name]["entries"] == len(split[name]), name
    families = {e["family"] for e in entries}
    assert len(families) == 13  # 12 template families + adversarial


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
    assert all(e["family"] != "adversarial" for e in _entries(manifest) if e["split"] == "dev")
    families = {f for f, _ in variants["dev"]}
    for name in SPLITS:  # every template family is represented in every split, with both of its variants
        assert {(f, v) for f in families for v in {v for _, v in variants[name]}} == variants[name], name
    # the holdout letters come from new senders
    senders = {
        name: {e["truth"]["sender_name"] for e in _entries(manifest) if e["split"] == name} for name in SPLITS
    }
    assert not senders["holdout"] & (senders["dev"] | senders["test"])


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

    assert SPLIT_VARIANTS == {"dev": ("A", "B"), "test": ("C", "D"), "holdout": ("E", "F")}
    for split, own in SPLIT_VARIANTS.items():
        for variant in "ABCDEF":
            if variant in own:
                case(split, "invoice_relative", variant)
            else:
                with pytest.raises(AssertionError):
                    case(split, "invoice_relative", variant)
    case("holdout", "adversarial", "scam")
    with pytest.raises(AssertionError):
        case("dev", "adversarial", "scam")


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


def test_text_pdfs_contain_their_key_date_phrases(manifest: dict[str, Any]) -> None:
    for entry in _entries(manifest):
        if entry["photo"]:
            continue
        assert entry["key_phrases"], entry["id"]
        with pdfplumber.open(DATASET / entry["file"]) as pdf:
            assert len(pdf.pages) == entry["pages"]
            text = _norm(" ".join(page.extract_text() or "" for page in pdf.pages))
        for phrase in [*entry["key_phrases"], *entry["hidden_phrases"]]:
            assert _norm(phrase) in text, f"{entry['id']}: {phrase!r} not found in the PDF text"
        if entry["truth"]["document_date"] and entry["language"] == "de" and entry["family"] != "adversarial":
            d = date.fromisoformat(entry["truth"]["document_date"])
            assert f"{d.day:02d}.{d.month:02d}.{d.year}" in text, entry["id"]


def _dark_fills(page: Any) -> list[tuple[float, float, float, float]]:
    out = []
    for shape in [*page.rects, *page.curves]:
        color = shape.get("non_stroking_color")
        if shape.get("fill") and isinstance(color, tuple | list) and len(color) == 3:
            if 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2] < 0.6:
                out.append((shape["x0"], shape["top"], shape["x1"], shape["bottom"]))
    return out


def test_invisible_text_only_where_expected(manifest: dict[str, Any]) -> None:
    """SPEC §21 criteria: < 3 pt, off-page, or white text not on a dark fill counts as hidden."""
    for entry in _entries(manifest):
        if entry["photo"]:
            continue
        hidden_chars = 0
        with pdfplumber.open(DATASET / entry["file"]) as pdf:
            for page in pdf.pages:
                fills = _dark_fills(page)
                for ch in page.chars:
                    if not ch["text"].strip():
                        continue
                    color = ch.get("non_stroking_color")
                    white = isinstance(color, tuple | list) and len(color) in (1, 3) and min(color) >= 0.95
                    cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2
                    on_dark = any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in fills)
                    off_page = (
                        ch["x0"] < 0 or ch["x1"] > page.width or ch["top"] < 0 or ch["bottom"] > page.height
                    )
                    if ch["size"] < 3 or off_page or (white and not on_dark):
                        hidden_chars += 1
        expected = "hidden_text" in entry["truth"]["expected_warnings"]
        assert (hidden_chars > 0) == expected, f"{entry['id']}: {hidden_chars} invisible characters"


def test_labels_survive_the_independent_recheck() -> None:
    """``evals/verify_labels.py`` re-derives every dated label from facts read off each letter by hand, with its
    own calculator (datetime + holidays package; no code shared with evals/gen or ordnung.rules), checks that
    the letters state what the truth claims, and that no deadline sentence recurs in letters of two splits
    (dev, test, holdout). See evals/dataset/VERIFICATION.md."""
    import verify_labels

    report = verify_labels.run(DATASET)
    assert report["dated_labels_checked"] >= 152  # 92 of dev and test, 60 of holdout
    assert not report["date_problems"], report["date_problems"]
    assert not report["text_problems"], report["text_problems"]
    assert not report["shared_split_sentences"], report["shared_split_sentences"]
    assert not report["photo_problems"], report["photo_problems"]


@pytest.mark.parametrize("pair", [("dev", "test"), ("dev", "holdout"), ("test", "holdout")])
def test_the_wording_check_covers_every_pair_of_splits(pair: tuple[str, str]) -> None:
    """A deadline sentence shared by any two splits is reported (it used to compare dev with test only)."""
    import verify_labels

    shared = "Bitte antworten Sie uns binnen vierzehn Tagen nach dem Datum dieses Schreibens schriftlich."
    entries = [{"id": f"{name}-x-A1", "split": name, "photo": False} for name in SPLITS]
    texts = {
        e["id"]: shared if e["split"] in pair else "Ein Satz ohne jede Frist und ohne Termin, nur zur Info."
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


def test_generation_is_byte_identical(tmp_path: Path, manifest: dict[str, Any]) -> None:
    first = _generate(tmp_path / "a")
    assert {e["split"] for e in first["entries"]} == set(SPLITS) == set(first["counts"])
    # The labels never depend on the environment.
    assert _without_bytes(first) == _without_bytes(manifest), (
        "dataset is stale — run `.venv/bin/python evals/generate.py`"
    )
    if first["environment"] == manifest["environment"]:
        # Same rendering libraries: the committed dataset must be reproduced bit for bit.
        assert (tmp_path / "a" / "manifest.json").read_bytes() == MANIFEST.read_bytes()
        for entry in first["entries"]:
            assert (tmp_path / "a" / entry["file"]).read_bytes() == (DATASET / entry["file"]).read_bytes(), (
                entry["file"]
            )
    else:  # different library versions: still require two runs to agree bit for bit
        second = _generate(tmp_path / "b")
        assert (tmp_path / "a" / "manifest.json").read_bytes() == (
            tmp_path / "b" / "manifest.json"
        ).read_bytes()
        for entry in second["entries"]:
            assert (tmp_path / "a" / entry["file"]).read_bytes() == (
                tmp_path / "b" / entry["file"]
            ).read_bytes(), entry["file"]


# --------------------------------------------------------------------------------------------------
# the generator's arithmetic against the verified research examples (docs: legal research notes)
# --------------------------------------------------------------------------------------------------


def _remedy(posted: date, scope: str, region: str | None) -> tuple[str, str]:
    why = law.Derivation()
    notified = law.deemed_delivery(posted, scope, region, why)
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
