"""``evals/results/items.csv``: every item of every published run as ids, dates and outcomes, with cost and latency.

One row per (results file, condition, letter, item) of each per-letter run file of the pinned model in
``evals/results`` (a run of an earlier model is left out: its recordings are not in the repository; so are the
summaries — Ask, without the Land, the ablation, end to end, the analysis). A letter whose truth has no item gets one
row with the item's columns empty, so every letter's cost is there. ``cost_usd``, ``latency_ms`` and ``calls`` are
the letter's: the same on each of its items.

No free text: the columns are a whitelist of ids, dates, enums and numbers (:data:`COLUMNS`). An item's title, the
model's quotes and explanations never leave the results files, and a value with a space or over 64 characters stops
the export (:class:`ExportError`), so a new field can't carry a letter's words out by accident.

    python -m evals.export --write    # rewrite evals/results/items.csv
    python -m evals.export --check    # exit 1 when it is not what the results files give (make eval-reproduce)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.run import DEFAULT_MODEL, RESULTS_DIR

ITEMS_CSV = RESULTS_DIR / "items.csv"
#: The only columns: ids and labels, the item's dates and outcome, the letter's cost, latency and calls.
COLUMNS = (
    "file",
    "split",
    "repeat",
    "condition",
    "entry_id",
    "family",
    "variant",
    "modality",
    "region",
    "today",
    "item",
    "required",
    "kind",
    "expected",
    "predicted",
    "outcome",
    "direction",
    "days_off",
    "confidence",
    "flagged",
    "cause",
    "cost_usd",
    "latency_ms",
    "calls",
)
MAX_CELL = 64
_FREE_TEXT = re.compile(r"\s")


class ExportError(ValueError):
    """A value that is not an id, a date, an enum or a number (named by column and file, never quoted)."""


def run_files(results_dir: Path = RESULTS_DIR) -> list[Path]:
    """The pinned model's per-letter run files in ``results_dir``, by name."""
    found = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        meta = data.get("meta") if isinstance(data, dict) else None
        if (
            isinstance(meta, dict)
            and isinstance(data.get("entries"), list)
            and meta.get("split")
            and meta.get("model") == DEFAULT_MODEL
        ):
            found.append(path)
    return found


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def rows(name: str, results: Mapping[str, Any]) -> Iterator[dict[str, str]]:
    """The rows of one results file (``name`` is its file name)."""
    meta = results["meta"]
    for entry in results["entries"]:
        letter = {
            "file": name,
            "split": meta["split"],
            "repeat": meta.get("repeat", 1),
            "entry_id": entry["id"],
            "family": entry["family"],
            "variant": entry["variant"],
            "modality": entry["modality"],
            "region": entry["region"],
            "today": entry["today"],
        }
        for condition in meta["conditions"]:
            score = (entry["conditions"].get(condition) or {}).get("score")
            if score is None:
                continue
            cost = {
                "condition": condition,
                "cost_usd": score.get("cost_usd"),
                "latency_ms": score.get("latency_ms"),
                "calls": score.get("calls"),
            }
            items: list[dict[str, Any]] = sorted(score["items"], key=lambda item: int(item["index"]))
            for item in items or [{}]:
                values = {
                    **letter,
                    **cost,
                    "item": item.get("index"),
                    "required": item.get("required"),
                    "kind": item.get("kind"),
                    "expected": item.get("expected"),
                    "predicted": item.get("predicted"),
                    "outcome": item.get("outcome"),
                    "direction": item.get("direction"),
                    "days_off": item.get("days_off"),
                    "confidence": item.get("confidence"),
                    "flagged": item.get("flagged"),
                    "cause": item.get("cause"),
                }
                yield {column: _checked(column, _cell(values[column]), name) for column in COLUMNS}


def _checked(column: str, value: str, name: str) -> str:
    if len(value) > MAX_CELL or _FREE_TEXT.search(value):
        raise ExportError(f"{name}: the column {column} holds free text, not an id, date, enum or number")
    return value


def render(results_dir: Path = RESULTS_DIR) -> str:
    """The CSV text of every run file in ``results_dir`` (header first, ``\\n`` line ends)."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for path in run_files(results_dir):
        writer.writerows(rows(path.name, json.loads(path.read_text(encoding="utf-8"))))
    return out.getvalue()


def write(results_dir: Path = RESULTS_DIR, path: Path = ITEMS_CSV) -> Path:
    path.write_text(render(results_dir), encoding="utf-8", newline="\n")
    return path


def check(results_dir: Path = RESULTS_DIR, path: Path = ITEMS_CSV) -> list[str]:
    """What is wrong with the committed CSV (empty when it is what the results files give)."""
    if not path.is_file():
        return [f"{path.name} is missing: run python -m evals.export --write"]
    if path.read_text(encoding="utf-8") != render(results_dir):
        return [f"{path.name} is not what the results files give: run python -m evals.export --write"]
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.export", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="rewrite the CSV")
    mode.add_argument("--check", action="store_true", help="exit 1 when the CSV is not what the files give")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--out", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    out = args.out or args.results_dir / ITEMS_CSV.name
    try:
        if args.write:
            print(f"wrote {write(args.results_dir, out)}", file=sys.stderr)
            return 0
        problems = check(args.results_dir, out)
    except ExportError as exc:
        print(f"python -m evals.export: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
