"""``presentation.json``: every number a reader sees, read from the results files (never computed again).

The role of each results file is derived from the file itself (its schema, model, split and backend), so no
second list of files can drift from the folder:

* ``final`` — a run on a pre-registered final split, or the final analysis (``evals.analysis --prereg``);
* ``held-out`` — the one live recording of a held-out split (holdout, holdout2, holdout3);
* ``re-analysis`` — the held-out splits as recorded, re-analysed after their results were known (not
  pre-registered);
* ``re-scored`` — a replay of a held-out split's recordings with later code;
* ``iterated`` — the dev and test splits (tuned or iterated on) and Ask's development set;
* ``replay`` — a replay of the recordings another way (without the sender's Land, the check ablation, end to end);
* ``archive`` — a run on another model than the pinned one: listed by date in the history, never charted.

Only ``final`` and ``held-out`` recordings (``backend == "live"``) feed a headline. The headline is the final run
once it exists (phase 2, refused here until its renderer lands), else the newest re-analysis of the held-out
splits, whose inputs must be those recordings byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals import stats
from evals.present import MODEL, RESULTS_DIR, PresentError, palette

SCHEMA = "ordnung-eval-presentation/1"
ROLES = ("final", "held-out", "re-analysis", "re-scored", "iterated", "replay", "archive")
#: Files beside the results that are not results (EV4's index of them).
NOT_RESULTS = frozenset({"INDEX.json"})
HELD_OUT_SPLITS = ("holdout", "holdout2", "holdout3")
#: The pre-registered final run's splits (``evals/splits.py``).
FINAL_SPLITS = ("holdout4", "newkinds")
ITERATED_SPLITS = ("dev", "test")
SPLIT_ORDER = ("dev", "test", "holdout", "holdout2", "holdout3", "holdout4", "newkinds")
#: What each split is, for the data section and the timeline (the protocol, from evals/generate.py).
SPLIT_ROLES = {
    "dev": "prompts tuned on it",
    "test": "iterated on: recorded again after fixes",
    "holdout": "held out; code fixed after its result",
    "holdout2": "held out; code fixed after its result",
    "holdout3": "held out; written after the code freeze, audited blind",
    "holdout4": "pre-registered final run on the version that ships: not yet written",
}
#: The scorer's adversarial classes Ordnung is scored on (``evals.metrics``), in the order the report lists them.
ADVERSARIAL_CLASSES = (
    ("injection_resisted", "Visible injection resisted: deadline kept"),
    ("injection_flagged", "Visible injection shown to the person"),
    ("hidden_text_detected", "Hidden (invisible) text detected"),
    ("scam_flagged", "Scam letter flagged (a warning, or an IBAN that is not valid)"),
    ("scam_false_alarm", "Scam false alarm on an ordinary letter (lower is better)"),
    ("conflicting_dates_handled", "Conflicting dates: the earlier kept, or flagged"),
    ("missing_date_handled", "Missing date: no confident date, or flagged"),
    ("ambiguous_handled", "Ambiguous numeric date: no confident date, or flagged"),
)
#: The stored explanations of a date computed with the 3-day delivery rule of before 2025.
_THIRD_DAY = re.compile(r"third day|3rd day|3 days after|\+ ?3 days", re.IGNORECASE)
#: … and of a late date that moved a deemed delivery day off a weekend or holiday.
_SHIFTED = re.compile(r"shift|moves|next working day|Werktag")


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PresentError(f"{path.name}: not a readable results file ({exc})") from exc
    if not isinstance(data, dict):
        raise PresentError(f"{path.name}: not a results file of a kind the presenter knows")
    return data


def kind_of(name: str, data: Mapping[str, Any]) -> str:
    """What a results file holds: ``run``, ``ask``, ``analysis``, ``without-land``, ``checks-ablated`` or
    ``e2e``; raises :class:`PresentError` naming the file for anything else."""
    schema = data.get("schema")
    meta: Mapping[str, Any] = data["meta"] if isinstance(data.get("meta"), dict) else {}
    if data.get("benchmark") == "ask":
        return "ask"
    if isinstance(schema, str):
        for prefix, kind in (
            ("ordnung-eval-analysis/", "analysis"),
            ("ordnung-eval-without-land/", "without-land"),
            ("ordnung-eval-checks-ablated/", "checks-ablated"),
        ):
            if schema.startswith(prefix):
                return kind
    if "definitions" in data and "set_aside" in data and isinstance(data.get("metrics"), dict):
        return "e2e"
    if isinstance(schema, int) and "metrics" in data and "entries" in data and meta.get("split"):
        return "run"
    raise PresentError(
        f"{name}: not a results file of a kind the presenter knows; give it a role in {__name__}"
    )


def role_of(name: str, data: Mapping[str, Any]) -> str:
    """The role of one results file (see the module's docstring)."""
    kind = kind_of(name, data)
    meta: Mapping[str, Any] = data.get("meta") or {}
    model = data.get("model") if kind == "ask" else meta.get("model")
    if model != MODEL:
        return "archive"
    if kind == "ask":
        return "iterated"
    if kind == "analysis":
        analysis = meta.get("kind")
        if analysis == "final":
            return "final"
        if analysis == "heldout-reanalysis":
            return "re-analysis"
        raise PresentError(f"{name}: an analysis of a kind the presenter knows not ({analysis})")
    if kind != "run":
        return "replay"
    split, backend = meta.get("split"), meta.get("backend")
    if split in FINAL_SPLITS:
        if backend != "live":
            raise PresentError(f"{name}: a {split} file that is not a live recording")
        return "final"
    if split in HELD_OUT_SPLITS:
        return "held-out" if backend == "live" else "re-scored"
    if split in ITERATED_SPLITS:
        return "iterated"
    raise PresentError(f"{name}: a run on a split the presenter knows not ({split})")


def _files(results_dir: Path) -> list[Path]:
    return sorted(path for path in results_dir.glob("*.json") if path.name not in NOT_RESULTS)


def _classified(results_dir: Path) -> dict[str, tuple[str, str, dict[str, Any]]]:
    """``{name: (kind, role, data)}`` for every results file; each held-out split recorded once."""
    found: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path in _files(results_dir):
        data = _load(path)
        found[path.name] = (kind_of(path.name, data), role_of(path.name, data), data)
    held: dict[str, list[str]] = {}
    for name, (_, role, data) in found.items():
        if role == "held-out":
            held.setdefault(str(data["meta"]["split"]), []).append(name)
    for split, names in held.items():
        if len(names) > 1:
            raise PresentError(
                f"the {split} split is held out and recorded once, but {', '.join(names)} are live"
            )
    return found


def roles(results_dir: Path = RESULTS_DIR) -> dict[str, str]:
    """``{file name: role}`` for every results file in ``results_dir``."""
    return {name: role for name, (_, role, _) in _classified(results_dir).items()}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rate(k: float, n: float) -> dict[str, Any]:
    """``k`` of ``n`` with its Clopper-Pearson interval (``evals.stats``)."""
    k, n = int(k), int(n)
    if n == 0:
        return {"k": 0, "n": 0, "value": None, "ci": [None, None]}
    low, high = stats.clopper_pearson(k, n)
    return {"k": k, "n": n, "value": round(k / n, 10), "ci": [round(low, 10), round(high, 10)]}


def _kn(metric: Mapping[str, Any]) -> dict[str, Any]:
    keep = {key: metric[key] for key in ("k", "n", "value", "ci") if key in metric}
    keep["k"], keep["n"] = int(metric["k"]), int(metric["n"])
    return keep


def _newest(
    found: Mapping[str, tuple[str, str, dict[str, Any]]], kind: str, role: str | None = None
) -> str | None:
    names = [name for name, (k, r, _) in found.items() if k == kind and (role is None or r == role)]
    return max(names) if names else None


# --------------------------------------------------------------------------------------------------
# The headline: the held-out splits as recorded, re-analysed
# --------------------------------------------------------------------------------------------------

_CONDITION_KEYS = ("exact", "late", "early", "missed", "declined", "harmful", "letters_fully_right")


def _headline(results_dir: Path, found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    source = _newest(found, "analysis", "re-analysis")
    if source is None:
        raise PresentError("no re-analysis of the held-out splits: run python -m evals.analysis --write")
    analysis = found[source][2]
    inputs = []
    for row in analysis["meta"]["inputs"]:
        name = row["file"]
        if name not in found:
            raise PresentError(f"{source} reads {name}, which is not in {results_dir}")
        _, role, data = found[name]
        if _sha256(results_dir / name) != row["sha256"]:
            raise PresentError(
                f"{name} ({row['split']}) is not the file {source} analysed: its bytes changed"
            )
        if role != "held-out" or data["meta"].get("backend") != "live":
            raise PresentError(f"{source} reads {name}, which is not a held-out live recording ({role})")
        meta = data["meta"]
        inputs.append(
            {
                "file": name,
                "sha256": row["sha256"],
                "split": row["split"],
                "role": role,
                "date": meta["date"],
                "commit": meta.get("commit"),
                "backend": meta["backend"],
                "entries": int(meta["entries"]),
                "photos": int(meta["photos"]),
                "adversarial": int(meta["adversarial"]),
                "scored_items": int(meta["scored_items"]),
            }
        )
    conditions: dict[str, Any] = {}
    for condition in palette.CONDITIONS:
        summary = analysis["conditions"][condition]
        selective = summary["selective"]
        conditions[condition] = {
            **{key: _kn(summary[key]) for key in _CONDITION_KEYS},
            "days_late": summary["days_late"],
            "days_early": summary["days_early"],
            "spurious_dated_items": summary["spurious_dated_items"],
            "letters_with_spurious": summary["letters_with_spurious"],
            "by_confidence": summary["by_confidence"],
            "selective": {
                "tiers": selective["tiers"],
                "please_check": {
                    key: _kn(selective["please_check"][key]) for key in ("share", "precision", "recall_wrong")
                },
                "any_flag": {key: _kn(selective["any_flag"][key]) for key in ("share", "recall_wrong")},
                "unflagged": {
                    key: _kn(selective["unflagged"][key]) for key in ("coverage", "accuracy", "harmful")
                },
                "auroc": selective["auroc"],
                "aurc": selective["aurc"],
            },
            "loss": summary["loss"],
            "cost": summary["cost"],
            "latency_ms": summary["latency_ms"],
            "modality": {
                modality: _rate(
                    *_summed(found, inputs, condition, ("by_modality", modality, "due_date_accuracy"))
                )
                for modality in ("text", "photo")
            },
        }
    paired = {
        family: {
            pair: {
                key: row[key]
                for key in ("n", "b", "c", "diff", "exact_p", "midp", "holm_midp", "bonett_price", "verdict")
            }
            | {
                "signflip_p": row["signflip"]["p"],
                "bootstrap": [row["cluster_bootstrap"]["lo"], row["cluster_bootstrap"]["hi"]],
            }
            for pair, row in rows.items()
        }
        for family, rows in analysis["paired"].items()
    }
    findings = analysis["findings"]
    adversarial = [
        {"name": name, "label": label} | _rate(*_summed(found, inputs, "ordnung", ("adversarial", name)))
        for name, label in ADVERSARIAL_CLASSES
    ]
    return {
        "kind": "pooled-held-out",
        "label": "Held out, read once",
        "pre_registered": False,
        "note": analysis["meta"]["note"],
        "source": {"file": source, "sha256": _sha256(results_dir / source), "role": found[source][1]},
        "methods": analysis["meta"]["methods"],
        "settings": analysis["meta"]["settings"],
        "inputs": inputs,
        "splits": [row["split"] for row in inputs],
        "items": analysis["items"],
        "letters": analysis["letters"],
        "photos": sum(row["photos"] for row in inputs),
        "adversarial": sum(row["adversarial"] for row in inputs),
        "clusters": analysis["clusters"],
        "conditions": conditions,
        "paired": paired,
        "crossover": analysis["crossover"],
        "by_split": analysis["by_split"],
        "flags": findings["flags"]["ordnung"],
        "rules_text_claim": findings.get("rules_text_claim"),
        "rules_text_crossover": findings.get("rules_text_crossover"),
        "adversarial_classes": adversarial,
        "errors": analysis["errors"],
    }


def _summed(
    found: Mapping[str, tuple[str, str, dict[str, Any]]],
    inputs: Sequence[Mapping[str, Any]],
    condition: str,
    keys: Sequence[str],
) -> tuple[int, int]:
    """A rate's ``k`` and ``n`` summed over the headline's input files (the scorer's own counts)."""
    k = n = 0
    for row in inputs:
        metric: Any = found[row["file"]][2]["metrics"][condition]
        for key in keys:
            metric = metric.get(key) if isinstance(metric, Mapping) else None
        if isinstance(metric, Mapping) and metric.get("n"):
            k, n = k + int(metric["k"]), n + int(metric["n"])
    return k, n


# --------------------------------------------------------------------------------------------------
# Everything else on the pages
# --------------------------------------------------------------------------------------------------


def _ask(found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> dict[str, Any] | None:
    name = _newest(found, "ask", "iterated")
    if name is None:
        return None
    data = found[name][2]
    summary = data["summary"]
    return {
        "file": name,
        "date": data.get("date"),
        "set": data.get("set", "dev"),
        "questions": int(summary["questions"]),
        "answerable": int(summary["answerable"]),
        "unanswerable": int(summary["unanswerable"]),
        "attacks": int(summary["attacks"]),
        "accuracy": _kn(summary["accuracy"]),
        "abstention": _kn(summary["abstention"]),
        "citation_support": _kn(summary["citation_support"]),
        "attack_success": _kn(summary["attack_success"]),
        "attack_success_raw": _kn(summary["attack_success_raw"]),
    }


def _without_land(found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> dict[str, Any] | None:
    name = _newest(found, "without-land")
    if name is None:
        return None
    data = found[name][2]
    splits = {}
    for split in sorted(data["splits"], key=lambda s: SPLIT_ORDER.index(s) if s in SPLIT_ORDER else 99):
        numbers = data["splits"][split]
        days = sorted(-int(change["days_off"]) for change in numbers["changed"])
        splits[split] = {
            "entries": numbers["entries"],
            "with_land": _kn(numbers["with_land"]["due_date_accuracy"]),
            "without_land": _kn(numbers["without_land"]["due_date_accuracy"]),
            "without_land_late": int(numbers["without_land"]["dangerous_late_rate"]["k"]),
            "with_suggestion": _kn(numbers["with_suggestion"]["due_date_accuracy"]),
            "days_early": [days[0], days[-1]] if days else None,
            "late_changes": sum(1 for change in numbers["changed"] if change["direction"] != "early"),
        }
    return {"file": name, "date": data["meta"]["date"], "splits": splits}


def _ablation(found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> dict[str, Any] | None:
    """``scripts/eval_ablate_checks.py``'s results: Ordnung's code checks switched off one at a time."""
    name = _newest(found, "checks-ablated")
    if name is None:
        return None
    data = found[name][2]
    held = data["totals"]["held_out"]
    rows = []
    for ablation, info in data["meta"]["ablations"].items():
        counts = held["ablations"][ablation]["counts"]
        rows.append(
            {
                "name": ablation,
                "label": info["label"],
                **{key: int(counts[key]) for key in ("scored", "right", "late", "missed", "early")},
            }
        )
    return {"file": name, "splits": list(held["splits"]), "rows": rows}


def _e2e(found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> dict[str, Any] | None:
    """``python -m evals.e2e``'s results: from a letter's file to the reminder, through the real app."""
    name = _newest(found, "e2e")
    if name is None:
        return None
    data = found[name][2]
    pooled = data["metrics"]["pooled"]
    not_reminded = {str(cause): int(count) for cause, count in sorted(pooled["not_reminded"].items())}
    return {
        "file": name,
        "splits": list(data["meta"]["pooled"]),
        "letters": int(pooled["letters"]),
        "obligations": int(pooled["obligations"]),
        "parity": {"k": int(pooled["parity"]["k"]), "n": int(pooled["parity"]["n"])},
        "reminded_in_time": _kn(pooled["reminded_in_time"]),
        "late_reminders": len(pooled["late_reminders"]),
        "not_reminded": not_reminded,
        "set_aside": sum(count for cause, count in not_reminded.items() if cause.startswith("set_aside:")),
    }


def _first_test_run(found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> dict[str, Any] | None:
    """The model alone on the test split's first live run: its wrong dates, how many used the 3-day delivery rule
    of before 2025 (from the stored explanations), and how many late ones moved a delivery day off a weekend."""
    runs = sorted(
        name
        for name, (kind, role, data) in found.items()
        if kind == "run"
        and role == "iterated"
        and data["meta"].get("split") == "test"
        and data["meta"].get("backend") == "live"
        and "llm_only" in data["meta"].get("conditions", [])
    )
    if not runs:
        return None
    data = found[runs[0]][2]
    wrong = []
    for entry in data["entries"]:
        condition = entry["conditions"]["llm_only"]
        for scored in condition["score"]["items"]:
            if scored.get("required") and scored["outcome"] == "wrong":
                wrong.append((scored, condition["prediction"]["items"][scored["pred_index"]]))
    late = [predicted for scored, predicted in wrong if scored["direction"] == "late"]
    return {
        "file": runs[0],
        "date": data["meta"]["date"],
        "wrong": len(wrong),
        "n": int(data["metrics"]["llm_only"]["due_date_accuracy"]["n"]),
        "three_day": sum(
            1 for _, predicted in wrong if _THIRD_DAY.search(predicted.get("explanation") or "")
        ),
        "late": len(late),
        "late_shifted": sum(1 for predicted in late if _SHIFTED.search(predicted.get("explanation") or "")),
    }


def _composition(found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Each split's size, from the newest live run of the pinned model on it, and its role in the protocol."""
    rows: list[dict[str, Any]] = []
    for split in SPLIT_ORDER:
        names = sorted(
            name
            for name, (kind, role, data) in found.items()
            if kind == "run"
            and role != "archive"
            and data["meta"].get("split") == split
            and data["meta"].get("backend") == "live"
        )
        if not names:
            if split in SPLIT_ROLES:
                rows.append({"split": split, "role": SPLIT_ROLES[split], "recorded": None})
            continue
        held = [name for name in names if found[name][1] == "held-out"]
        name = held[0] if held else names[-1]
        meta = found[name][2]["meta"]
        ordnung = found[name][2]["metrics"].get("ordnung", {}).get("due_date_accuracy")
        rows.append(
            {
                "split": split,
                "role": SPLIT_ROLES.get(split, ""),
                "recorded": sorted(found[n][2]["meta"]["date"] for n in names)[0],
                "recordings": len(names),
                "entries": int(meta["entries"]),
                "photos": int(meta["photos"]),
                "adversarial": int(meta["adversarial"]),
                "scored_items": int(meta["scored_items"]),
                "ordnung": _kn(ordnung) if held and ordnung else None,
            }
        )
    return rows


def _file_rows(found: Mapping[str, tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """One row per results file, for the history page: what it is and Ordnung's exact dates (never an archive's)."""
    rows = []
    for name, (kind, role, data) in found.items():
        meta = data.get("meta") or {}
        row: dict[str, Any] = {
            "file": name,
            "date": name[:10],
            "kind": kind,
            "role": role,
            "split": meta.get("split") if kind == "run" else None,
            "backend": meta.get("backend") if kind == "run" else None,
            "conditions": list(meta.get("conditions", [])) if kind == "run" and role != "archive" else [],
            "ordnung": None,
        }
        if kind == "run" and role != "archive" and "ordnung" in data["metrics"]:
            row["ordnung"] = _kn(data["metrics"]["ordnung"]["due_date_accuracy"])
        rows.append(row)
    return rows


def build(results_dir: Path = RESULTS_DIR) -> dict[str, Any]:
    """The presentation model of ``results_dir``: what ``presentation.json`` holds."""
    found = _classified(results_dir)
    finals = sorted(name for name, (_, role, _) in found.items() if role == "final")
    if finals:
        raise PresentError(
            f"a final run exists ({', '.join(finals)}): it takes the headline by the pre-registered rule, which the "
            "presenter's phase 2 renders; the pooled held-out headline is never published beside it"
        )
    headline = _headline(results_dir, found)
    conditions = headline["conditions"]
    order = sorted(
        palette.CONDITIONS,
        key=lambda c: (-conditions[c]["exact"]["value"], palette.CONDITIONS.index(c)),
    )
    return {
        "schema": SCHEMA,
        "model": MODEL,
        "order": order,
        "headline": headline,
        "ask": _ask(found),
        "without_land": _without_land(found),
        "ablation": _ablation(found),
        "e2e": _e2e(found),
        "llm_only_first_run": _first_test_run(found),
        "splits": _composition(found),
        "files": _file_rows(found),
        "final": None,
    }


def dumps(document: Mapping[str, Any]) -> str:
    """``presentation.json``'s text: keys in the order they are built, one space of indent."""
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"
