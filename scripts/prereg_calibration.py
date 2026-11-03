"""The pre-registered analysis run once on data whose answer is known: the calibration in the pre-registration.

The held-out splits recorded before the freeze (holdout, holdout2, holdout3, as recorded:
``evals.analysis.HELD_OUT_AS_RECORDED``) are pooled into one split named holdout4 and used as its three reads,
identical, so no item can be unstable; holdout3 alone stands in for newkinds; ``pool_with`` names the three files,
as the default analysis section does (``evals.analysis.default_prereg_analysis``). The analysis is the final run's
own (``evals.analysis.final_analysis``), with no frozen-input check: these are not final reads. The file
(``evals/preregistration/calibration-0.4.0.json``, outside ``evals/results`` so nothing reads it as a result) keeps
what the registered rules decide here, and the counts they rest on: ids, counts, rates and p-values only. It is not
a result of the final run.

Run it from the repository root (zero tokens, no model)::

    .venv/bin/python -m scripts.prereg_calibration [--results-dir evals/results]
        [--out evals/preregistration/calibration-0.4.0.json | --check FILE]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals import analysis

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evals" / "results"
OUT = ROOT / "evals" / "preregistration" / "calibration-0.4.0.json"
SCHEMA = "ordnung-prereg-calibration/1"
PRIMARY = "holdout4"
SECONDARY = "newkinds"
READS = 3
ABOUT = (
    "The pre-registered analysis run on the held-out splits recorded before the freeze, pooled into one split and "
    "used as its three identical reads (holdout3 stands in for the secondary split): what the registered rules "
    "decide on data whose answer is known. Not a result of the final run."
)


def _relabelled(doc: Mapping[str, Any], split: str, repeat: int) -> dict[str, Any]:
    out = copy.deepcopy(dict(doc))
    out["meta"] = dict(out.get("meta") or {}, split=split, repeat=repeat)
    return out


def calibrate(results_dir: Path | None = None) -> dict[str, Any]:
    """The registered analysis on the pooled held-out splits, summarised (see the module's docstring)."""
    folder = results_dir or RESULTS_DIR
    names = list(analysis.HELD_OUT_AS_RECORDED)
    raws = [(folder / name).read_bytes() for name in names]
    docs = [json.loads(raw) for raw in raws]
    pooled = dict(docs[0], entries=[entry for doc in docs for entry in doc["entries"]])
    reads = [
        analysis.load_run(
            _relabelled(pooled, PRIMARY, read), name=f"pooled held-out splits as {PRIMARY} read {read}"
        )
        for read in range(1, READS + 1)
    ]
    secondary = analysis.load_run(_relabelled(docs[-1], SECONDARY, 1), name=f"{names[-1]} as {SECONDARY}")
    section = analysis.default_prereg_analysis()
    prereg = analysis.parse_prereg({"analysis": section})
    pool = [analysis.read_run(folder / name) for name in prereg.pool_with]
    final = analysis.final_analysis(prereg, [*reads, secondary], pooled_with=pool)
    inputs = [
        {
            "file": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "role": "pooled reads and newkinds" if index == len(names) - 1 else "pooled reads",
        }
        for index, (name, raw) in enumerate(zip(names, raws, strict=True))
    ]
    return summary(final, inputs, section)


def _pairs(rows: Mapping[str, Any], keep: Sequence[str]) -> dict[str, Any]:
    return {pair: {key: row.get(key) for key in keep} for pair, row in rows.items()}


def summary(
    final: Mapping[str, Any], inputs: list[dict[str, Any]], section: Mapping[str, Any]
) -> dict[str, Any]:
    """What the calibration keeps of a final analysis: counts and decisions, never a letter's id or text."""
    primary = final["primary"]
    families: dict[str, Any] = {}
    for family, rows in primary["families"].items():
        if rows is None:
            families[family] = None
        elif family == "F3_stability":
            families[family] = _pairs(rows, ("b", "c", "midp", "holm"))
        else:
            families[family] = {
                pair: {
                    "diff": row["diff"],
                    "p": row["signflip"]["p"],
                    "method": row["signflip"]["method"],
                    "nonzero": row["signflip"]["nonzero"],
                    "holm": row["holm"],
                    "bootstrap": [row["bootstrap"]["lo"], row["bootstrap"]["hi"]],
                }
                for pair, row in rows.items()
            }
    conditions = {
        condition: {
            "exact_per_read": [row["k"] for row in body["exact_per_read"]],
            "n": body["exact_per_read"][0]["n"],
            "mean_accuracy": body["mean_accuracy"],
            "harmful_per_read": [row["k"] for row in body["harmful_per_read"]],
            "unstable": body["unstable"]["k"],
        }
        for condition, body in primary["conditions"].items()
    }
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "about": ABOUT,
        "inputs": inputs,
        "analysis": dict(section),
        "primary": {
            "split": primary["split"],
            "reads": primary["reads"],
            "items": primary["items"],
            "letters": primary["letters"],
            "clusters": primary["clusters"],
            "conditions": conditions,
            "families": families,
            "sensitivity_r1": {
                name: _pairs(rows, ("b", "c", "exact_p", "midp", "bonett_price"))
                for name, rows in primary["sensitivity_r1"].items()
            },
            "decisions": primary["decisions"],
        },
    }
    if "noninferiority" in primary:
        out["primary"]["noninferiority"] = {
            pair: {"lo": row["bound"]["lo"], "hi": row["bound"]["hi"], "decision": row["decision"]}
            for pair, row in primary["noninferiority"].items()
        }
    pooled = (final.get("exploratory") or {}).get("pooled_held_out")
    if pooled is not None:
        out["exploratory_pooled_splits"] = pooled["splits"]
    return out


def render(document: Mapping[str, Any]) -> str:
    """The file's text: floats rounded as the analysis rounds them, so a render is byte for byte the same."""
    return analysis.render(document)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.prereg_calibration", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--out", type=Path, default=OUT, help=f"default: {OUT.relative_to(ROOT)}")
    where.add_argument(
        "--check", type=Path, metavar="FILE", help="exit 1 unless FILE is what the calibration gives"
    )
    args = parser.parse_args(argv)
    try:
        text = render(calibrate(args.results_dir))
    except (OSError, ValueError) as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return 2
    if args.check is not None:
        same = args.check.is_file() and args.check.read_text(encoding="utf-8") == text
        print(f"{args.check.name}: {'up to date' if same else 'differs from a fresh calibration'}")
        return 0 if same else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    decisions = json.loads(text)["primary"]["decisions"]
    print(
        f"{args.out.name}: written ({', '.join(f'{k} {v}' for k, v in decisions.items() if isinstance(v, str))})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
