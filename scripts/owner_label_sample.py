"""The owner's label check of the final splits: which dates the owner checks against an outside deadline calculator.

The sample is 20 dated slots of holdout4 and 10 of newkinds, each split stratified by family, drawn with seed
20261029 from the dataset's manifest (``evals.ask.owner.stratified_sample``). A slot is ``i<n>``: the n-th required
item of a letter whose label is one date. Photos are left out: a photo carries its letter's labels. The file lists ids and where each letter is, never a label or any condition's answer, so the owner
works the dates out without them; each verdict is published per id when the check is done, whatever it shows. It
never blocks anything: until it is done the report says the labels are not yet checked by a person.

Run it from the repository root once the final letters exist::

    .venv/bin/python -m scripts.owner_label_sample --seed 20261029 [--manifest evals/dataset/manifest.json]
        [--out evals/preregistration/owner-labels-0.4.0.json | --check FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.ask.owner import stratified_sample

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals" / "dataset" / "manifest.json"
OUT = ROOT / "evals" / "preregistration" / "owner-labels-0.4.0.json"
SCHEMA = "ordnung-owner-labels/1"
SEED = 20261029
#: How many dated slots of each final split the owner checks.
PLAN = {"holdout4": 20, "newkinds": 10}
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SampleError(ValueError):
    """The manifest cannot give the sample (no final letters yet, or too few dated slots)."""


def dated_slots(manifest: Mapping[str, Any], split: str) -> list[dict[str, str]]:
    """Every slot of the split's letters (photos left out) whose label is one date, with its family and file."""
    slots = []
    for entry in manifest.get("entries") or []:
        if entry.get("split") != split or entry.get("photo"):
            continue
        for index, item in enumerate((entry.get("truth") or {}).get("items") or []):
            if isinstance(item.get("expected_due"), str) and _DAY.match(item["expected_due"]):
                slots.append(
                    {
                        "split": split,
                        "entry_id": str(entry["id"]),
                        "slot": f"i{index}",
                        "family": str(entry["family"]),
                        "file": str(entry["file"]),
                    }
                )
    return slots


def sample(
    manifest: Mapping[str, Any], seed: int = SEED, plan: Mapping[str, int] = PLAN
) -> list[dict[str, str]]:
    """The slots the owner checks, per split in :data:`PLAN` order, stratified by family."""
    found: list[dict[str, str]] = []
    for split, n in plan.items():
        slots = dated_slots(manifest, split)
        if not slots:
            raise SampleError(
                f"the manifest has no dated {split} slot: draw the sample once the final letters exist"
            )
        try:
            chosen = stratified_sample(slots, key="family", n=n, seed=seed, ident=("entry_id", "slot"))
        except ValueError as exc:
            raise SampleError(f"{split}: {exc}") from exc
        found.extend(dict(row) for row in chosen)
    return found


def record(manifest_path: Path, seed: int = SEED) -> dict[str, Any]:
    """The file as the pre-registration holds it: the sample, pending, with the manifest's sha256."""
    raw = manifest_path.read_bytes()
    rows = sample(json.loads(raw), seed=seed)
    return {
        "schema": SCHEMA,
        "status": "pending",
        "about": (
            "The owner's check of the final splits' labels: each slot's date worked out with an outside deadline "
            "calculator and compared with the label. It never blocks anything; until it is done the report says "
            "the labels are not yet checked by a person, and each verdict is published per id when it is."
        ),
        "sampler": "scripts/owner_label_sample.py",
        "seed": seed,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "plan": dict(PLAN),
        "strata": "family",
        "items": [{**row, "verdict": None} for row in rows],
        "checked": None,
        "agree": None,
        "source": None,
    }


def render(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.owner_label_sample", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--out", type=Path, default=OUT, help=f"default: {OUT.relative_to(ROOT)}")
    where.add_argument(
        "--check", type=Path, metavar="FILE", help="exit 1 unless FILE is what the sampler draws"
    )
    args = parser.parse_args(argv)
    try:
        text = render(record(args.manifest, args.seed))
    except (SampleError, OSError) as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return 2
    if args.check is not None:
        same = args.check.is_file() and args.check.read_text(encoding="utf-8") == text
        print(f"{args.check.name}: {'the sampler draws it' if same else 'not what the sampler draws'}")
        return 0 if same else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"{args.out.name}: {sum(PLAN.values())} slots, pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
