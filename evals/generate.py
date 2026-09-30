"""Generate the Ordnung benchmark documents and their ground truth (SPEC §17, §21).

    .venv/bin/python evals/generate.py                 # writes evals/dataset/{dev,test,holdout}/ + manifest.json
    .venv/bin/python evals/generate.py --out /tmp/x    # same, elsewhere (used by the determinism test)

Everything is deterministic: fixed seeds, fixed PDF metadata and creation dates, no clock reads.
Labels come from the small, commented date arithmetic in ``evals/gen/law.py`` — never from
``ordnung.rules`` — and every dated label is additionally asserted against a date worked out by hand
(``check(..., hand)`` in the family modules).

Template families have six wording/layout variants each: A and B go to ``dev`` (the only split
prompts may be tuned on), C and D to ``test`` (the published run), E and F to ``holdout``.
Adversarial letters are one-offs in ``test`` and ``holdout``; dev has none.

The test split was meant to be held out, but extraction prompts 9, 10 and 11 were each recorded on
it, so it no longer is. The ``holdout`` split is a fresh sample of the same families, written from
scratch (``gen/holdout_*.py``: new senders, recipients, wording, layout, dates and amounts) after
extraction prompt version 11 and before any holdout recording. It is recorded once, with the prompts
frozen, and never tuned on. No deadline-bearing sentence of one split recurs in another
(``evals/verify_labels.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # allow `python evals/generate.py` from the repo root
    sys.path.insert(0, str(HERE))

from gen import law  # noqa: E402
from gen.adversarial import adversarial  # noqa: E402
from gen.common import DOCUMENT_KINDS, SPLIT_VARIANTS, Case  # noqa: E402
from gen.families_admin import (  # noqa: E402
    fine_bussgeld,
    municipal_decision,
    social_decision,
    tax_assessment,
    year_boundary,
)
from gen.families_private import (  # noqa: E402
    appointment,
    business_days,
    contract_confirmation,
    dunning_fixed,
    english_letter,
    invoice_relative,
    price_increase,
)
from gen.holdout_admin import fine_bussgeld as holdout_fine_bussgeld  # noqa: E402
from gen.holdout_admin import municipal_decision as holdout_municipal_decision  # noqa: E402
from gen.holdout_admin import social_decision as holdout_social_decision  # noqa: E402
from gen.holdout_admin import tax_assessment as holdout_tax_assessment  # noqa: E402
from gen.holdout_admin import year_boundary as holdout_year_boundary  # noqa: E402
from gen.holdout_adversarial import adversarial as holdout_adversarial  # noqa: E402
from gen.holdout_private import appointment as holdout_appointment  # noqa: E402
from gen.holdout_private import business_days as holdout_business_days  # noqa: E402
from gen.holdout_private import contract_confirmation as holdout_contract_confirmation  # noqa: E402
from gen.holdout_private import dunning_fixed as holdout_dunning_fixed  # noqa: E402
from gen.holdout_private import english_letter as holdout_english_letter  # noqa: E402
from gen.holdout_private import invoice_relative as holdout_invoice_relative  # noqa: E402
from gen.holdout_private import price_increase as holdout_price_increase  # noqa: E402
from gen.pdf import render_letter  # noqa: E402
from gen.photo import phone_photo  # noqa: E402
from gen.text import seed_for  # noqa: E402

DEFAULT_OUT = HERE / "dataset"
MAX_TOTAL_BYTES = 25 * 1024 * 1024
SPLITS = tuple(SPLIT_VARIANTS)  # dev, test, holdout

FAMILIES = (
    ("tax_assessment", tax_assessment),
    ("municipal_decision", municipal_decision),
    ("social_decision", social_decision),
    ("invoice_relative", invoice_relative),
    ("dunning_fixed", dunning_fixed),
    ("appointment", appointment),
    ("fine_bussgeld", fine_bussgeld),
    ("contract_confirmation", contract_confirmation),
    ("price_increase", price_increase),
    ("english_letter", english_letter),
    ("relative_business_days", business_days),
    ("year_boundary", year_boundary),
    ("adversarial", adversarial),
)
# The holdout split's letters (variants E, F and new adversarial letters), one builder per family.
HOLDOUT_FAMILIES = (
    ("tax_assessment", holdout_tax_assessment),
    ("municipal_decision", holdout_municipal_decision),
    ("social_decision", holdout_social_decision),
    ("invoice_relative", holdout_invoice_relative),
    ("dunning_fixed", holdout_dunning_fixed),
    ("appointment", holdout_appointment),
    ("fine_bussgeld", holdout_fine_bussgeld),
    ("contract_confirmation", holdout_contract_confirmation),
    ("price_increase", holdout_price_increase),
    ("english_letter", holdout_english_letter),
    ("relative_business_days", holdout_business_days),
    ("year_boundary", holdout_year_boundary),
    ("adversarial", holdout_adversarial),
)

CONVENTIONS = [
    "Labels are computed by evals/gen/law.py (independent of ordnung.rules) and asserted against dates worked out by hand.",
    "Posting date for the deemed-delivery fiction = the letter date, unless the letter states a separate posting date (spec.posted_on).",
    "Deemed delivery: 3rd day after posting for items posted up to 2024-12-31, 4th day from 2025-01-01; AO moves a Sat/Sun/holiday "
    "fiction day to the next working day, VwVfG and SGB X do not. Remedy periods: one month (§§ 187 Abs. 1, 188 Abs. 2, 3 BGB), "
    "end moved off Sat/Sun/holidays; Bußgeld: two weeks after the Zustellung date on the envelope.",
    "authority_region is set only when the letterhead names the Land; then expected_due uses that Land's holidays. When it is null, "
    "every dated item was verified to have the same date under all 16 Land calendars (so nationwide-only == legally correct).",
    "No label depends on municipal-only holidays (Mariä Himmelfahrt in parts of BY, Fronleichnam in parts of SN/TH, Augsburg) — asserted.",
    "Private-law payment/declaration deadlines are generated region-independent (place of performance is debatable); fixed dates in "
    "dunning and English letters fall on working days; Werktage periods never end on a Saturday — so no § 193 BGB edge case is labelled.",
    "Municipal (Land VwVfG) letters come only from Länder whose 4-day fiction was verified (BY, BW, NW, HH, SH).",
    "region_sensitive=true marks items whose date differs if the Land's holidays are ignored (due_if_region_ignored).",
    "Remedy 'klage': the legal date is still the label, although Ordnung by design shows a 'get advice' card instead (SPEC §21).",
    "optional_items are neither required nor penalised (e.g. special-cancellation windows, payments after Rechtskraft, scam demands).",
    "expected_due 'ambiguous' (with candidates) and null (no confident date) expect low confidence rather than a date.",
    "Photo entries are phone-photo renderings of page 1 of a one-page PDF entry (source_id) and share its truth.",
    "today = the day the person reads the letter (posting/letter date + 2..6 days); it is not a receipt date.",
    "Template wording: the test variants (C, D) and the adversarial letters repeat no deadline-bearing sentence of the dev "
    "variants (A, B); only short statutory phrases (e.g. 'vierten Tag nach Aufgabe zur Post') recur.",
    "Holdout split: variants E, F and the holdout adversarial letters were written from scratch (new senders, recipients, "
    "wording, layout, dates and amounts) after extraction prompt version 11 and before any holdout recording; they repeat no "
    "deadline-bearing sentence of the dev or test letters. The split is recorded once with frozen prompts and never tuned on.",
    "references list identifiers only; info-block lines holding a dash, a date or a billing month are printed but not labelled.",
    "amounts = the sums the reader must pay, will receive, or that the decision sets (old/new price for price changes, fees to "
    "bring to an appointment); line items, sums insured and merely threatened penalties are not listed.",
    "remedy_type follows the letter's own Rechtsbehelfsbelehrung; kind_also_accepted names a second document kind that fits "
    "the letter equally well (score kind as correct if it is kind or in kind_also_accepted).",
    "Consumer contracts under § 309 Nr. 9 BGB / § 56 TKG are generated so that the written minimum term also fits into 24 months "
    "from conclusion — the open question whether the cap counts from conclusion or from the start of service never matters.",
]

# Letters that honestly fit two DocumentKinds (checked by hand in evals/dataset/VERIFICATION.md).
KIND_ALSO_ACCEPTED: dict[str, list[str]] = {
    "test-dunning_fixed-D1": ["dunning"],  # Hausverwaltung payment reminder (labelled rent_lease)
    "test-english_letter-C2": ["utility_bill"],  # serviced-apartment utility statement (rent_lease)
    "test-invoice_relative-D1": ["invoice"],  # Stadtwerke final bill (utility_bill)
    "test-appointment-C1": ["appointment"],  # immigration-office invitation (residence_permit)
    "test-appointment-C2": ["appointment"],  # Jobcenter Meldeaufforderung (social_insurance)
    "test-adversarial-scam-2": ["other"],  # fake Stadtwerke letter (utility_bill)
    "holdout-social_decision-E2": ["social_insurance"],  # Pflegekasse decision (health_insurance)
    "holdout-invoice_relative-F1": ["invoice"],  # annual gas bill with a balance to pay (utility_bill)
    "holdout-appointment-F1": ["appointment"],  # landlord's move-out inspection (rent_lease)
    "holdout-adversarial-scam-2": ["other"],  # fake parcel 'customs fee' demand (invoice)
}


def build_cases() -> list[Case]:
    cases: list[Case] = []
    for family, builder in (*FAMILIES, *HOLDOUT_FAMILIES):
        built = builder()
        assert built, family
        for case in built:
            assert case.family == family, (case.id, family)
        cases.extend(built)
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    assert set(KIND_ALSO_ACCEPTED) <= set(ids), set(KIND_ALSO_ACCEPTED) - set(ids)
    for case in cases:
        also = KIND_ALSO_ACCEPTED.get(case.id, [])
        assert case.truth["kind"] not in also and set(also) <= DOCUMENT_KINDS, case.id
        case.truth["kind_also_accepted"] = also
    assert {c.split for c in cases} == set(SPLITS)
    assert all(c.split != "dev" for c in cases if c.family == "adversarial")
    variants = {
        split: {(c.family, c.variant) for c in cases if c.split == split and c.family != "adversarial"}
        for split in SPLITS
    }
    families = {c.family for c in cases if c.family != "adversarial"}
    for i, split in enumerate(SPLITS):
        assert {f for f, _ in variants[split]} == families, f"{split}: a template family is missing"
        assert {v for _, v in variants[split]} == set(SPLIT_VARIANTS[split]), split
        for other in SPLITS[i + 1 :]:
            assert not variants[split] & variants[other], (
                f"a template variant appears in both {split} and {other}"
            )
    return cases


def _entry(
    case: Case, file: str, data: bytes, *, pages: int, photo: bool, source_id: str | None
) -> dict[str, Any]:
    return {
        "id": f"{case.id}-photo" if photo else case.id,
        "split": case.split,
        "family": case.family,
        "variant": case.variant,
        "file": file,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "media_type": "image/jpeg" if photo else "application/pdf",
        "photo": photo,
        "source_id": source_id,
        "pages": pages,
        "language": case.truth["language"],
        "today": case.today.isoformat(),
        "authority_region": case.authority_region,
        "recipient_region": case.recipient_region,
        "key_phrases": [] if photo else case.key_phrases,
        "hidden_phrases": [] if photo else case.hidden_phrases,
        "notes": case.notes,
        "truth": case.truth,
    }


def environment() -> dict[str, str]:
    """Library versions that determine the output bytes (PDF streams, rasterised photos)."""
    import zlib

    import fpdf
    import holidays
    import PIL
    import pypdfium2.version as pdfium_version

    return {
        "fpdf2": fpdf.__version__,
        "pypdfium2": str(pdfium_version.PYPDFIUM_INFO),
        "pdfium": str(pdfium_version.PDFIUM_INFO),
        "pillow": PIL.__version__,
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
        "holidays": holidays.__version__,
    }


def generate(out: Path) -> dict[str, Any]:
    law.cross_check_with_holidays_package(range(2024, 2028))
    cases = build_cases()
    for split in SPLITS:
        folder = out / split
        folder.mkdir(parents=True, exist_ok=True)
        for stale in [*folder.glob("*.pdf"), *folder.glob("*.jpg")]:
            stale.unlink()
    entries: list[dict[str, Any]] = []
    for case in cases:
        pdf, pages = render_letter(case.letter)
        stem = case.id.removeprefix(f"{case.split}-")
        rel = f"{case.split}/{stem}.pdf"
        (out / rel).write_bytes(pdf)
        entries.append(_entry(case, rel, pdf, pages=pages, photo=False, source_id=None))
        if case.photo:
            assert pages == 1, f"{case.id}: photos are only taken of one-page letters"
            jpg = phone_photo(pdf, seed_for("photo", case.id))
            rel_photo = f"{case.split}/{stem}-photo.jpg"
            (out / rel_photo).write_bytes(jpg)
            entries.append(_entry(case, rel_photo, jpg, pages=1, photo=True, source_id=case.id))
    entries.sort(key=lambda e: (e["split"], e["family"], e["id"]))
    total = sum(e["bytes"] for e in entries)
    assert total < MAX_TOTAL_BYTES, f"dataset too large: {total} bytes"
    counts: dict[str, dict[str, int]] = {}
    for split in SPLITS:
        per_family = Counter(e["family"] for e in entries if e["split"] == split)
        counts[split] = {
            "entries": sum(per_family.values()),
            "photos": sum(1 for e in entries if e["split"] == split and e["photo"]),
            **dict(sorted(per_family.items())),
        }
    manifest = {
        "name": "ordnung-deadline-benchmark",
        "version": 1,
        "generator": "evals/generate.py",
        "environment": environment(),
        "conventions": CONVENTIONS,
        "counts": counts,
        "total_bytes": total,
        "entries": entries,
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (out / "manifest.json").write_text(text, encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="output directory (default: evals/dataset)"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    manifest = generate(args.out)
    if not args.quiet:
        families = sorted({e["family"] for e in manifest["entries"]})
        print(f"{'family':<24}" + "".join(f" {split:>8}" for split in SPLITS) + "   (photos included)")
        for family in families:
            row = [
                sum(1 for e in manifest["entries"] if e["family"] == family and e["split"] == split)
                for split in SPLITS
            ]
            print(f"{family:<24}" + "".join(f" {n:>8}" for n in row))
        c = manifest["counts"]
        print(
            f"{'total':<24}"
            + "".join(f" {c[split]['entries']:>8}" for split in SPLITS)
            + "   photos: "
            + ", ".join(f"{split} {c[split]['photos']}" for split in SPLITS)
        )
        print(f"size: {manifest['total_bytes'] / 1e6:.1f} MB → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
