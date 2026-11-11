"""The final run in ``presentation.json`` (its ``final``): found, held to its files, and copied, never computed again.

Once a file of the pre-registered final run is among the results (:func:`evals.present.model.role_of` gives it the
role ``final``), the final run takes the headline by the pre-registered rule. :func:`section` then finds the final
analysis, the pre-registration and the results files it names where the registered templates put them
(:func:`evals.present.final.published`, which reads a checkout's ``evals/results`` and never its folders, so a
checkpoint waiting in ``evals/results/pending/`` stays unread), and refuses, naming the file, anything that does not fit
them:

* a final read without the final analysis, or a final run in a results folder that is not a checkout's;
* a final analysis run under another pre-registration than the one committed (its sha256), or a pre-registration
  without the registered commits and days or the data's hashes that the provenance shows;
* an input whose bytes changed since the analysis read it, an input of the wrong role, and a final split's read the
  analysis does not read;
* a held-out Ask run without the Ask set's file of runs, or one that file does not list with its bytes;
* a deviation the analysis applied that the deviations file does not hold, or a deviations file other than the one the
  analysis read;
* any other file of the final run that the analysis and its named files do not account for;
* a sentence the registered rules refuse (:class:`evals.present.final.FinalSentenceError`).

What it returns is everything the renderers need, copied from those files: the coded sentences of both blocks, the
README layout as registered, the numbers by condition and read, the comparisons, the error rows (ids and codes only),
the deviations (never their ``what``), the provenance and the view templates (:mod:`evals.present.views`). The pooled
re-analysis of the earlier held-out splits stays in ``headline``, shown as recorded and not pre-registered.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.present import PresentError, final, palette, views

Found = Mapping[str, tuple[str, str, dict[str, Any]]]
#: The posted record of the presenter's tree (``scripts/prereg_hashes.py --phase2``), when it is committed.
PHASE2 = "evals/preregistration/phase2-0.4.0.json"
#: What the pre-registration registers that the provenance shows.
REGISTERED = ("freeze_sha", "freeze_pr", "commit_a", "planned_day", "valid_until")
DATA_HASHES = ("manifest_sha256", "tree_sha256")
SETTINGS = ("level", "alpha", "noninferiority_margin", "seed", "resamples", "signflip_draws")
#: The input roles of the final analysis that are the final run's own reads (the rest, ``pooled``, are the earlier
#: held-out splits' live recordings).
FINAL_INPUTS = ("primary", "secondary", "left_out")
INPUT_FIELDS = ("file", "sha256", "split", "repeat", "date", "commit", "backend", "role")
RATE_FIELDS = ("k", "n", "value", "ci")
MEAN_FIELDS = ("value", "ci", "method")
#: An error row's fields the page may show: ids, codes and numbers, never a letter's words.
ERROR_FIELDS = (
    "condition",
    "split",
    "entry_id",
    "item",
    "family",
    "modality",
    "outcome",
    "direction",
    "days_off",
    "confidence",
    "flagged",
    "tier",
    "cause",
    "read",
)
SENSITIVITIES = ("s_conv", "label_corrected", "first_attempt", "same_day_f3", "same_cli_f3")
_SENSITIVITY_FIELDS = (
    "same_as_primary",
    "items_changed",
    "tagged_items",
    "items",
    "versions",
    "deviations",
    "not_run",
)
STRESS_ENDPOINTS = ("injection_targeted", "distractor_taken", "harmful_unflagged")
_HASH = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _at(doc: Any, path: str, where: str) -> Any:
    """The value at ``path`` (dotted keys), or a :class:`PresentError` naming the path and where it is missing."""
    value = doc
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise PresentError(f"{where}: no {path}")
        value = value[part]
    return value


def _list(doc: Any, path: str, where: str) -> list[Any]:
    value = _at(doc, path, where)
    if not isinstance(value, list):
        raise PresentError(f"{where}: {path} is not a list")
    return value


def _root(results_dir: Path) -> Path:
    if results_dir.name != "results" or results_dir.parent.name != "evals":
        raise PresentError(
            f"a final run is presented from a checkout's evals/results, with its pre-registration beside it; "
            f"{results_dir} is not one"
        )
    return results_dir.parent.parent


def _named(found: Found, pattern: str, kind: str, split: str | None = None) -> str | None:
    """The results file of ``kind`` that the templates' ``pattern`` names (for the end-to-end run, the one that holds
    the final split)."""
    names = [
        name
        for name, (k, _, data) in found.items()
        if k == kind
        and fnmatch.fnmatch(name, Path(pattern).name)
        and (split is None or split in ((data.get("meta") or {}).get("splits") or ()))
    ]
    return names[0] if len(names) == 1 else None


def section(results_dir: Path, found: Found) -> dict[str, Any] | None:
    """``presentation.json``'s ``final``: ``None`` while no file of the final run is in ``results_dir``; else the
    final run, checked against its files (see the module's docstring), or a :class:`PresentError` naming what does
    not fit."""
    finals = sorted(name for name, (_, role, _) in found.items() if role == "final")
    if not finals:
        return None
    root = _root(results_dir)
    files: dict[str, str] = final.load_templates()["files"]
    published = final.published(root)
    if published is None:
        raise PresentError(
            f"final reads without the final analysis ({', '.join(finals)}): run python -m evals.analysis --prereg "
            f"{files['prereg']} with the reads, then --write; a final read is never shown under the pooled headline"
        )
    final_doc, prereg, named = published
    sources = [
        name
        for name, (kind, role, _) in found.items()
        if kind == "analysis" and role == "final" and fnmatch.fnmatch(name, Path(files["final"]).name)
    ]
    if len(sources) != 1:
        raise PresentError(
            f"the final analysis is not one results file of the pinned model in {files['final']}: "
            f"{', '.join(sources) or 'none'}"
        )
    source = sources[0]
    digest = _sha256(root / files["prereg"])
    if _at(final_doc, "meta.prereg.sha256", source) != digest:
        raise PresentError(
            f"{source} was analysed under another pre-registration than {files['prereg']} as committed: the "
            f"sha256 it names is not the file's ({digest[:12]})"
        )
    registered = {key: _at(prereg, f"registered.{key}", files["prereg"]) for key in REGISTERED}
    data_hashes = {key: _at(prereg, f"data.{key}", files["prereg"]) for key in DATA_HASHES}
    blind = _at(prereg, "blind_writing", files["prereg"])
    if not isinstance(blind, Mapping):
        raise PresentError(f"{files['prereg']}: blind_writing is not an object")
    inputs = _list(final_doc, "meta.inputs", source)
    read = _inputs(results_dir, found, source, inputs)
    ask_runs, ask_file = _ask_runs(results_dir, found, files, named)
    stress_file = _named(found, files["stress"], "stress")
    accounted = {source, *read, *ask_runs, *(name for name in (ask_file, stress_file) if name)}
    unaccounted = [name for name in finals if name not in accounted]
    if unaccounted:
        raise PresentError(
            f"{', '.join(unaccounted)}: a file of the final run that the final analysis {source} and the files it "
            "names do not account for"
        )
    _deviations_problems(root, files, source, final_doc, named.get("deviations"))
    page = final.coded(final_doc, prereg, block="page", sources=named)
    readme = final.coded(final_doc, prereg, block="readme", sources=named)
    loaded = views.load()
    problems = views.check(loaded)
    if problems:
        raise PresentError(f"{views.VIEWS_PATH.name}: {'; '.join(problems)}")
    primary = _at(final_doc, "primary", source)
    meta = _at(final_doc, "meta", source)
    split = str(_at(primary, "split", source))
    templates = prereg["sentences"]
    return {
        "source": {"file": source, "sha256": _sha256(results_dir / source)},
        "prereg": {
            "file": files["prereg"],
            "sha256": digest,
            "registered": registered,
            "data": data_hashes,
            "blind_writing": _hashes(blind),
        },
        "phase2": _phase2(root),
        "files": _files(root, found, files, named, split),
        "inputs": [{key: row.get(key) for key in INPUT_FIELDS} for row in inputs],
        "date": _at(meta, "date", source),
        "model": _at(meta, "model", source),
        "settings": {key: _at(meta, f"settings.{key}", source) for key in SETTINGS},
        "methods": dict(_at(meta, "methods", source)),
        "split": split,
        "reads": _at(primary, "reads", source),
        "reads_registered": _at(primary, "reads_registered", source),
        "reads_used": list(_list(primary, "reads_used", source)),
        "reads_missing": [
            {
                "read": _at(row, "read", source),
                "kinds": list(_list(row, "kinds", source)),
                "deviations": list(_list(row, "deviations", source)),
            }
            for row in _list(primary, "reads_missing", source)
        ],
        "items": _at(primary, "items", source),
        "letters": _at(primary, "letters", source),
        "clusters": _at(primary, "clusters", source),
        "not_run": dict(_at(primary, "not_run", source)),
        "conditions": {c: _condition(primary, c, source) for c in final.CONDITIONS},
        "families": _families(primary, source),
        "noninferiority": {
            pair: _noninferiority(block, f"{source} noninferiority {pair}")
            for pair, block in _at(primary, "noninferiority", source).items()
        },
        "decisions": dict(_at(primary, "decisions", source)),
        "decision_roles": dict(_at(primary, "decision_roles", source)),
        "confirmatory": dict(_at(primary, "confirmatory", source)),
        "sensitivities": _sensitivities(_at(final_doc, "sensitivities", source), source),
        "newkinds": _newkinds(_at(final_doc, "secondary.newkinds", source), source),
        "errors": [
            {key: _at(row, key, f"{source} errors") for key in ERROR_FIELDS}
            for row in _list(primary, "errors", source)
        ],
        "deviations": [_deviation(entry, files["deviations"]) for entry in named.get("deviations") or []],
        "owner": {"labels": _status(named.get("owner_labels")), "kappa": _status(named.get("owner_kappa"))},
        "ask": _ask(named.get("ask"), ask_file or files["ask"]),
        "stress": _stress(named.get("stress"), stress_file or files["stress"]),
        "e2e": _e2e(named.get("e2e"), _named(found, files["e2e"], "e2e", split) or files["e2e"]),
        "power": _power(named.get("power"), files["power"]),
        "sentences": {
            "page": [sentence._asdict() for sentence in page],
            "readme": [sentence._asdict() for sentence in readme],
        },
        "layout": {
            "readme_block": list(templates["readme_block"]),
            "readme_layout": templates["readme_layout"],
        },
        "views": loaded,
    }


def order(section: Mapping[str, Any]) -> list[str]:
    """The pages' one row order with a final run: its mean accuracy over the reads, highest first, ties in the
    conditions' fixed order."""

    def mean(condition: str) -> float:
        value = section["conditions"][condition]["mean_accuracy"]["value"]
        return float(value) if isinstance(value, (int, float)) else float("-inf")

    return sorted(palette.CONDITIONS, key=lambda c: (-mean(c), palette.CONDITIONS.index(c)))


# --------------------------------------------------------------------------------------------------
# What is checked
# --------------------------------------------------------------------------------------------------


def _inputs(results_dir: Path, found: Found, source: str, inputs: Sequence[Any]) -> set[str]:
    """The files the final analysis reads, each the bytes it read and of its role; every live read of a final split
    among them."""
    read: set[str] = set()
    for row in inputs:
        name = str(_at(row, "file", f"{source} meta.inputs"))
        if name not in found:
            raise PresentError(f"{source} reads {name}, which is not in evals/results")
        if _sha256(results_dir / name) != _at(row, "sha256", f"{source} meta.inputs"):
            raise PresentError(f"{name} is not the file {source} analysed: its bytes changed")
        kind, role, _ = found[name]
        wanted = "final" if row.get("role") in FINAL_INPUTS else "held-out"
        if kind != "run" or role != wanted:
            raise PresentError(f"{source} reads {name} as {row.get('role')}, but it is a {role} {kind} file")
        read.add(name)
    unread = sorted(name for name, (kind, role, _) in found.items() if kind == "run" and role == "final")
    unread = [name for name in unread if name not in read]
    if unread:
        raise PresentError(
            f"{', '.join(unread)}: a final split's read that the final analysis {source} does not read"
        )
    return read


def _ask_runs(
    results_dir: Path, found: Found, files: Mapping[str, str], named: Mapping[str, Any]
) -> tuple[list[str], str | None]:
    """The held-out Ask set's runs, each listed with its bytes in the set's file of runs, and that file's name."""
    runs = sorted(name for name, (kind, role, _) in found.items() if kind == "ask" and role == "final")
    ask_file = _named(found, files["ask"], "ask-final")
    if named.get("ask") is not None and ask_file is None:
        raise PresentError(f"the Ask file of runs is not one ask-final results file named as {files['ask']}")
    if not runs:
        return runs, ask_file
    if named.get("ask") is None or ask_file is None:
        raise PresentError(
            f"{', '.join(runs)}: held-out Ask runs without the Ask file of runs: run python -m evals.ask.heldout "
            "--final with them, then --write"
        )
    listed = {
        str(_at(row, "file", ask_file)): _at(row, "sha256", ask_file)
        for row in _list(named["ask"], "meta.inputs", ask_file)
    }
    for name in runs:
        if listed.get(name) != _sha256(results_dir / name):
            raise PresentError(
                f"{name}: a held-out Ask run that the Ask file of runs {ask_file} does not list as is"
            )
    return runs, ask_file


def _deviations_problems(
    root: Path, files: Mapping[str, str], source: str, final_doc: Mapping[str, Any], raw: Any
) -> None:
    """The deviations the final analysis applied are the deviations file's, and the file is the one it read."""
    ids = (
        {str(entry.get("id")) for entry in raw if isinstance(entry, Mapping)}
        if isinstance(raw, list)
        else set()
    )
    applied = (final_doc.get("meta") or {}).get("deviations")
    if applied is not None:
        unknown = sorted({str(_at(entry, "id", f"{source} meta.deviations")) for entry in applied} - ids)
        if unknown:
            raise PresentError(
                f"{source} applies the deviations {', '.join(unknown)}, which {files['deviations']} does not hold"
            )
    frozen = ((final_doc.get("meta") or {}).get("frozen_check") or {}).get("deviations_file")
    if isinstance(frozen, Mapping) and frozen.get("sha256") is not None:
        path = root / files["deviations"]
        if not path.is_file() or _sha256(path) != frozen["sha256"]:
            raise PresentError(
                f"{files['deviations']} is not the deviations file {source} read: its sha256 differs; run the final "
                "analysis again on the file as it is"
            )


# --------------------------------------------------------------------------------------------------
# What is copied
# --------------------------------------------------------------------------------------------------


def _rate(value: Any, where: str) -> dict[str, Any]:
    return {key: _at(value, key, where) for key in RATE_FIELDS}


def _counted(value: Any, where: str) -> dict[str, Any]:
    """A count of the Ask set's file (whose counts are written as numbers with a fraction): ``k`` of ``n``."""
    return {"k": int(_at(value, "k", where)), "n": int(_at(value, "n", where))}


def _condition(primary: Any, condition: str, source: str) -> dict[str, Any]:
    where = f"{source} conditions {condition}"
    summary = _at(primary, f"conditions.{condition}", source)
    return {
        **{
            key: [_rate(rate, where) for rate in _list(summary, key, where)]
            for key in ("exact_per_read", "harmful_per_read", "late_per_read")
        },
        **{
            key: {k: _at(summary, f"{key}.{k}", where) for k in MEAN_FIELDS}
            for key in ("mean_accuracy", "mean_harmful")
        },
        **{key: _rate(_at(summary, key, where), where) for key in ("pass_all", "pass_any", "unstable")},
        **{key: list(_list(summary, key, where)) for key in ("model_failed_per_read", "unanswered_per_read")},
    }


def _pair(row: Any, where: str) -> dict[str, Any]:
    """An F1 or F2 comparison: the difference (Ordnung minus the baseline), its bootstrap interval, the sign-flip p
    and its Holm adjustment."""
    return {
        "n": _at(row, "n", where),
        "diff": _at(row, "diff", where),
        "lo": _at(row, "bootstrap.lo", where),
        "hi": _at(row, "bootstrap.hi", where),
        "holm": _at(row, "holm", where),
        "p": _at(row, "signflip.p", where),
        "method": _at(row, "bootstrap.method", where),
        "p_method": _at(row, "signflip.method", where),
    }


def _stability(rows: Any, where: str) -> dict[str, Any] | None:
    if rows is None:
        return None
    keys = ("n", "b", "c", "diff", "midp", "exact_p", "bonett_price", "holm")
    return {pair: {key: _at(row, key, f"{where} {pair}") for key in keys} for pair, row in rows.items()}


def _families(block: Any, where: str) -> dict[str, Any]:
    families = _at(block, "families", where)
    return {
        **{
            family: {
                pair: _pair(row, f"{where} {family} {pair}")
                for pair, row in _at(families, family, where).items()
            }
            for family in ("F1_accuracy", "F2_harm")
        },
        "F3_stability": _stability(_at(families, "F3_stability", where), where),
    }


def _noninferiority(block: Any, where: str) -> dict[str, Any]:
    return {
        "margin": _at(block, "margin", where),
        "lo": _at(block, "bound.lo", where),
        "hi": _at(block, "bound.hi", where),
        "estimate": _at(block, "bound.estimate", where),
        "errors": {key: _at(block, f"errors.{key}", where) for key in ("ours", "theirs", "ratio")},
        "decision": _at(block, "decision", where),
    }


def _sensitivity(block: Mapping[str, Any], where: str) -> dict[str, Any]:
    """A sensitivity analysis, labelled beside the primary (never replacing it): what changed and, when anything did,
    its numbers and codes."""
    shown: dict[str, Any] = {key: block[key] for key in _SENSITIVITY_FIELDS if key in block}
    if "conditions" in block:
        shown["conditions"] = {
            condition: {key: _at(summary, key, where) for key in ("mean_accuracy", "harmful_item_reads")}
            for condition, summary in block["conditions"].items()
        }
    for family in ("F1_accuracy", "F2_harm"):
        if family in block:
            shown[family] = {pair: _pair(row, f"{where} {pair}") for pair, row in block[family].items()}
    if "F3_stability" in block:
        shown["F3_stability"] = _stability(block["F3_stability"], where)
    if "decisions" in block:
        shown["decisions"] = dict(block["decisions"])
    return shown


def _sensitivities(blocks: Any, source: str) -> dict[str, Any]:
    return {
        name: _sensitivity(blocks[name], f"{source} sensitivities {name}")
        for name in SENSITIVITIES
        if isinstance(blocks, Mapping) and isinstance(blocks.get(name), Mapping)
    }


def _newkinds(block: Any, source: str) -> dict[str, Any]:
    where = f"{source} secondary.newkinds"
    if isinstance(block, Mapping) and "not_recorded" in block:
        missing = block["not_recorded"]
        return {
            "not_recorded": {
                "read": _at(missing, "read", where),
                "kinds": list(_list(missing, "kinds", where)),
                "deviations": list(_list(missing, "deviations", where)),
            }
        }
    return {
        "items": _at(block, "items", where),
        "letters": _at(block, "letters", where),
        "clusters": _at(block, "clusters", where),
        "conditions": {
            c: {key: _rate(_at(block, f"conditions.{c}.{key}", where), where) for key in ("exact", "harmful")}
            for c in final.CONDITIONS
        },
    }


def _deviation(entry: Any, where: str) -> dict[str, Any]:
    """One entry of the deviations file as the page lists it: what it is, what it applies to and its registered
    consequence, where and when it was recorded; never its ``what``."""
    applies = entry.get("applies_to") if isinstance(entry.get("applies_to"), Mapping) else {}
    evidence = entry.get("evidence") if isinstance(entry.get("evidence"), list) else []
    kind = str(_at(entry, "kind", where))
    return {
        "id": str(_at(entry, "id", where)),
        "kind": kind,
        "step": entry.get("step"),
        "at": entry.get("at"),
        "split": applies.get("split"),
        "repeat": applies.get("repeat"),
        "entries": len(applies["entries"]) if isinstance(applies.get("entries"), list) else None,
        "items": len(applies["items"]) if isinstance(applies.get("items"), list) else None,
        # a code_hash_changed deviation names the changed path, alone or before a note
        "paths": [str(item).split(" ", 1)[0] for item in evidence] if kind == "code_hash_changed" else [],
        "consequence": entry.get("consequence"),
        "created_at": entry.get("created_at"),
        "issue_comment_url": entry.get("issue_comment_url"),
        "checkpoint_sha": entry.get("checkpoint_sha"),
    }


def _status(doc: Any) -> str:
    return "pending" if doc is None else str(doc.get("status"))


def _ask(doc: Any, name: str) -> dict[str, Any] | None:
    """The held-out Ask set: its runs and the numbers its sentences read (no id list)."""
    if doc is None:
        return None
    return {
        "runs": int(_at(doc, "consistency.runs", name)),
        "registered_runs": int(_at(doc, "meta.registered_reads", name)),
        "strict": {
            **_counted(_at(doc, "r1.strict_accuracy", name), name),
            "value": _at(doc, "r1.strict_accuracy.value", name),
            "ci": _at(doc, "r1.strict_accuracy.ci", name),
        },
        "harmful": _counted(_at(doc, "r1.harmful", name), name),
        "harmful_any": _counted(_at(doc, "consistency.harmful_any", name), name),
        "attack_success_worst": _counted(_at(doc, "consistency.attack_success_worst", name), name),
    }


def _stress(doc: Any, name: str) -> dict[str, Any] | None:
    """The stress test's pre-registered endpoints (never its letters)."""
    endpoints = doc.get("endpoints") if isinstance(doc, Mapping) else None
    if endpoints is None:
        return None
    return {
        endpoint: {
            **{
                key: _at(endpoints, f"{endpoint}.{key}", name)
                for key in ("n", "ordnung", "llm_rules_tool", "b", "c", "p")
            },
            "holm": _at(endpoints, f"holm.{endpoint}", name),
        }
        for endpoint in STRESS_ENDPOINTS
    }


def _e2e(doc: Any, name: str) -> dict[str, Any] | None:
    """The end-to-end replay of the final letters: its obligations, reminders and the scam letters' demands."""
    if doc is None:
        return None
    scam = _at(doc, "metrics.all.scam", name)
    return {
        "file": name,
        "obligations": _at(doc, "metrics.all.obligations", name),
        "reminded_in_time": _rate(_at(doc, "metrics.all.reminded_in_time", name), name),
        "set_aside": _at(scam, "set_aside_obligations", name),
        "scam_letters": _at(scam, "scam_letters", name),
        "in_the_calendar": [
            {"entry_id": str(_at(row, "entry_id", name)), "events": int(_at(row, "events", name))}
            for row in _list(scam, "in_the_calendar", name)
        ],
    }


def _power(doc: Any, where: str) -> dict[str, Any] | None:
    if doc is None:
        return None
    return {
        family: {
            pair: _at(row, "power", where) for pair, row in _at(doc, f"comparisons.{family}", where).items()
        }
        for family in ("F1_accuracy", "F2_harm")
    }


def _hashes(value: Any, path: str = "") -> dict[str, str]:
    """Every sha256 under the pre-registration's ``blind_writing``, by its dotted path."""
    found: dict[str, str] = {}
    if isinstance(value, Mapping):
        for key, inner in value.items():
            found |= _hashes(inner, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            found |= _hashes(inner, f"{path}.{index}")
    elif isinstance(value, str) and _HASH.fullmatch(value):
        found[path] = value
    return found


def _phase2(root: Path) -> dict[str, Any] | None:
    path = root / PHASE2
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PresentError(f"{PHASE2}: not a readable JSON file ({exc})") from exc
    return {"head": _at(data, "head", PHASE2), "tree_sha256": _at(data, "tree_sha256", PHASE2)}


def _files(
    root: Path, found: Found, files: Mapping[str, str], named: Mapping[str, Any], split: str
) -> dict[str, dict[str, str] | None]:
    """Each file the sentences name, by its path from the root and its sha256 (``None`` when it is not there)."""
    places = {
        "ask": _named(found, files["ask"], "ask-final"),
        "stress": _named(found, files["stress"], "stress"),
        "e2e": _named(found, files["e2e"], "e2e", split),
    }
    shown: dict[str, dict[str, str] | None] = {}
    for name in final.NAMED:
        if named.get(name) is None:
            shown[name] = None
            continue
        result = places.get(name)
        relative = f"evals/results/{result}" if result else files[name]
        path = root / relative
        if not path.is_file():
            raise PresentError(f"the {name} file the sentences read is not one file at {files[name]}")
        shown[name] = {"file": relative, "sha256": _sha256(path)}
    return shown
