"""Synthetic final runs in a temporary checkout, for the presenter's final path.

Nothing here writes under the repository's own ``evals/results`` or ``evals/preregistration``: every final run lives
in a temporary folder that looks like a checkout.

* :func:`final_root` builds ``<tmp>/root``: the README copied, every committed results file linked (read only, never
  written through), and beside them the synthetic final analysis, its pre-registration and the files it names, where
  ``evals/present/final_templates.json`` puts them.
* :func:`complete` turns a hand-built final of ``tests/test_present_final.py`` (which holds only what the sentences
  read) into the real analysis's shape, numbers derived from the builder's own; :func:`complete_prereg` does the same
  for its pre-registration. ``tests/test_present_final_run.py`` holds the completion to a real
  ``evals.analysis.final_analysis`` output.
* :func:`realistic` runs the real analysis on synthetic reads written as results files, so the analysis names real
  files with their hashes.
* :func:`calibration` runs it as ``scripts/prereg_calibration.py`` does, on the earlier held-out splits read as the
  final run: real numbers of a realistic size. Its reads and its errors hold those splits' letter ids, so it is only
  ever written into a temporary folder, and nothing of it is printed.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import shutil
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from evals import analysis
from evals.present import final
from scripts import prereg_calibration

import test_present_final as builders

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "results"
MODEL = "claude-sonnet-5"
#: Where the synthetic final run's files go in the temporary checkout (the patterns of the templates' ``files``).
FINAL_NAME = "2026-12-01-claude-sonnet-5-final.json"
ASK_NAME = "2026-12-09-claude-sonnet-5-ask-heldout-final.json"
STRESS_NAME = "2026-12-08-claude-sonnet-5-stress.json"
E2E_NAME = "2026-12-11-claude-sonnet-5-e2e.json"
FILES = final.load_templates()["files"]
#: The hand-built finals with the sources each renders with: ``(name, final, sources)``.
SCENARIOS = builders.SCENARIOS
SCENARIO_IDS = [name.replace(" ", "_") for name, _, _ in SCENARIOS]
N = builders.N
PAIRS = {baseline: f"ordnung-vs-{baseline}" for baseline in final.BASELINES}
#: How many synthetic letters each of :func:`realistic_reads`' splits has.
READ_LETTERS = {"holdout4": 12, "newkinds": 6}


def _hex(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _rate(k: int, n: int) -> dict[str, Any]:
    return builders._rate(k, n) if n else {"k": 0, "n": 0, "value": None, "ci": [None, None]}


# --------------------------------------------------------------------------------------------------
# A real final analysis, on synthetic reads
# --------------------------------------------------------------------------------------------------


def synthetic_read(split: str, read: int, letters: int) -> dict[str, Any]:
    """One read as a results file: ``tests/test_present_final.py``'s synthetic read with what the presenter reads of a
    run besides (its metrics and its counts)."""
    data = builders._synthetic_run(split, read, letters)
    data["meta"] |= {"entries": letters, "photos": 0, "adversarial": 0, "scored_items": letters}
    data["metrics"] = {}
    return data


def _text(data: Any) -> str:
    return json.dumps(data, indent=1) + "\n"


def realistic_reads() -> list[tuple[str, str]]:
    """holdout4 read three times and newkinds once, as results files: ``(name, text)``."""
    names = {
        ("holdout4", 1): "2027-01-01-claude-sonnet-5-holdout4.json",
        ("holdout4", 2): "2027-01-02-claude-sonnet-5-holdout4-r2.json",
        ("holdout4", 3): "2027-01-03-claude-sonnet-5-holdout4-r3.json",
        ("newkinds", 1): "2027-01-01-claude-sonnet-5-newkinds.json",
    }
    return [
        (name, _text(synthetic_read(split, read, READ_LETTERS[split])))
        for (split, read), name in names.items()
    ]


def analyse(reads: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """The real final analysis of ``reads`` (``(name, text)``), as ``evals.analysis`` renders it."""
    section = analysis.default_prereg_analysis()
    section["pool_with"] = []
    registered = analysis.parse_prereg({"analysis": section})
    runs = [
        analysis.load_run(
            json.loads(text), name=name, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()
        )
        for name, text in reads
    ]
    record = {"file": FILES["prereg"], "sha256": "ab" * 32}
    left_open = analysis.ambiguous_slots([], ("holdout4", "newkinds"))
    document = analysis.final_analysis(registered, runs, prereg_record=record, ambiguous_slots=left_open)
    data: dict[str, Any] = json.loads(analysis.render(document))
    return data


@functools.cache
def _real_text() -> str:
    return json.dumps(analyse(realistic_reads()))


def real() -> dict[str, Any]:
    """A real final analysis on synthetic reads (a fresh copy each time)."""
    data: dict[str, Any] = json.loads(_real_text())
    return data


def realistic(
    src: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, str]]]:
    """The real final analysis of :func:`realistic_reads`, the sources it renders with and the reads themselves, to
    write beside it (:func:`final_root` with ``reads=``)."""
    reads = realistic_reads()
    named = as_written(copy.deepcopy(dict(src or builders.no_set_aside(builders.sources()))))
    return analyse(reads), named, reads


def calibration_reads() -> list[tuple[str, str]]:
    """The earlier held-out splits as the final run's reads (``scripts/prereg_calibration.py``): pooled and read as
    holdout4 three times, the last of them as newkinds once, as results files ``(name, text)``."""
    docs = [json.loads((RESULTS / name).read_bytes()) for name in analysis.HELD_OUT_AS_RECORDED]
    pooled = dict(docs[0], entries=[entry for doc in docs for entry in doc["entries"]])
    reads = [
        (name, prereg_calibration._relabelled(pooled, "holdout4", read))
        for read, name in enumerate(
            (
                "2027-01-01-claude-sonnet-5-holdout4.json",
                "2027-01-02-claude-sonnet-5-holdout4-r2.json",
                "2027-01-03-claude-sonnet-5-holdout4-r3.json",
            ),
            1,
        )
    ]
    reads.append(
        ("2027-01-01-claude-sonnet-5-newkinds.json", prereg_calibration._relabelled(docs[-1], "newkinds", 1))
    )
    return [(name, _text(data)) for name, data in reads]


def calibration(
    src: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, str]]]:
    """The calibration's final analysis, with the earlier held-out splits pooled beside it as registered: the
    analysis, the sources it renders with and the reads, to write beside it (:func:`final_root` with ``reads=``)."""
    reads = calibration_reads()
    registered = analysis.parse_prereg({"analysis": analysis.default_prereg_analysis()})
    runs = [
        analysis.load_run(
            json.loads(text), name=name, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()
        )
        for name, text in reads
    ]
    document = analysis.final_analysis(
        registered,
        runs,
        pooled_with=[analysis.read_run(RESULTS / name) for name in registered.pool_with],
        prereg_record={"file": FILES["prereg"], "sha256": "ab" * 32},
        ambiguous_slots=analysis.ambiguous_slots([], ("holdout4", "newkinds")),
        date="2027-01-04",
    )
    named = as_written(copy.deepcopy(dict(src or builders.no_set_aside(builders.sources()))))
    data: dict[str, Any] = json.loads(analysis.render(document))
    return data, named, reads


# --------------------------------------------------------------------------------------------------
# The hand-built finals, completed to the real shape
# --------------------------------------------------------------------------------------------------


def _mean(rates: Sequence[Mapping[str, Any]]) -> float:
    return sum(int(rate["k"]) for rate in rates) / max(1, sum(int(rate["n"]) for rate in rates))


def _completed_condition(summary: dict[str, Any], reads: int) -> None:
    exact, harmful = summary["exact_per_read"], summary["harmful_per_read"]
    summary.setdefault("late_per_read", [_rate(int(rate["k"]), N) for rate in harmful])
    if "mean_harmful" not in summary:
        value = _mean(harmful)
        summary["mean_harmful"] = {
            "value": value,
            "ci": [max(0.0, value - 0.02), min(1.0, value + 0.03)],
            "method": "percentile",
        }
    lowest, highest = min(int(rate["k"]) for rate in exact), max(int(rate["k"]) for rate in exact)
    unstable = int(summary["unstable"]["k"])
    summary.setdefault("pass_all", _rate(max(0, lowest - unstable // 2), N))
    summary.setdefault("pass_any", _rate(min(N, highest + unstable // 2), N))
    summary.setdefault("model_failed_per_read", [0] * reads)
    summary.setdefault("unanswered_per_read", [0] * reads)


def _completed_row(row: dict[str, Any], first: float, second: float) -> None:
    row.setdefault("first", first)
    row.setdefault("second", second)
    row["signflip"] = {"statistic": row["diff"] * N, "clusters": 104, "draws": None, "seed": None} | row[
        "signflip"
    ]
    row["bootstrap"] = {"clusters": 104, "resamples": 10000, "seed": 20261029} | row["bootstrap"]


def _deviation(number: int, kind: str, applies_to: Mapping[str, Any] | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": f"D{number:03d}",
        "kind": kind,
        "at": "2026-11-25T10:00:00Z",
        "step": "R4",
        "what": "ids and counts",
        "evidence": ["a path and its sha256"],
        "consequence": analysis.DEVIATION_CONSEQUENCES[kind],
        "issue_comment_url": f"https://github.com/owner/repo/issues/7#issuecomment-{number}",
        "created_at": "2026-11-25T10:01:00Z",
        "checkpoint_sha": _hex(f"checkpoint {number}")[:40],
    }
    if applies_to is not None:
        entry["applies_to"] = dict(applies_to)
    return entry


def _deviations(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The builders' deviations (an id, a kind and maybe what they apply to) recorded at the time, well formed."""
    return [
        _deviation(int(str(entry["id"]).removeprefix("D")), str(entry["kind"]), entry.get("applies_to"))
        | {key: value for key, value in entry.items() if key not in ("id", "kind", "applies_to")}
        for entry in entries
    ]


def _add_deviation(src: dict[str, Any], kind: str, applies_to: Mapping[str, Any]) -> str:
    entry = _deviation(len(src["deviations"]) + 1, kind, applies_to)
    src["deviations"].append(entry)
    return str(entry["id"])


def _errors(primary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Error rows consistent with the builder's rates: each read's late dates (its harmful ones), then its other wrong
    dates, early; ids are synthetic."""
    rows: list[dict[str, Any]] = []
    reads = int(primary["reads"])
    for read in range(1, reads + 1):
        for condition in final.CONDITIONS:
            summary = primary["conditions"][condition]
            right = int(summary["exact_per_read"][read - 1]["k"])
            harmful = int(summary["harmful_per_read"][read - 1]["k"])
            for index in range(max(0, N - right)):
                late = index < harmful
                rows.append(
                    {
                        "condition": condition,
                        "split": primary["split"],
                        "entry_id": f"holdout4-syn-{index:03d}",
                        "item": 0,
                        "family": "f",
                        "modality": "photo" if index % 5 == 4 else "text",
                        "outcome": "wrong",
                        "direction": "late" if late else "early",
                        "days_off": 2 if late else -1,
                        "confidence": "high" if index % 2 else "medium",
                        "flagged": index % 3 == 0,
                        "tier": "please_check" if index % 3 == 0 else "none",
                        "cause": None,
                        "read": read,
                    }
                )
    return rows


def complete(doc: Mapping[str, Any], src: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``doc`` (a hand-built final) in the real analysis's shape, and ``src`` (its sources) as the files the final
    run's tools write; the numbers added are derived from the builder's own. A read not made (``two_reads``,
    ``one_read``) is named by a ``budget_cut`` deviation recorded at the time, and new kinds not recorded by a
    ``window_closed`` one."""
    doc, src = copy.deepcopy(dict(doc)), as_written(copy.deepcopy(dict(src)))
    template = real()
    meta = doc["meta"]
    meta.setdefault("date", "2026-12-01")
    meta.setdefault("label", "pre-registered")
    meta.setdefault("inputs", [])
    meta.setdefault("analysis", template["meta"]["analysis"])
    meta.setdefault("methods", template["meta"]["methods"])
    meta["settings"] = template["meta"]["settings"] | meta["settings"]
    primary = doc["primary"]
    reads = int(primary["reads"])
    for summary in primary["conditions"].values():
        _completed_condition(summary, reads)
    means = {
        family: {c: primary["conditions"][c][key]["value"] for c in final.CONDITIONS}
        for family, key in (("F1_accuracy", "mean_accuracy"), ("F2_harm", "mean_harmful"))
    }
    for family in ("F1_accuracy", "F2_harm"):
        for baseline, pair in PAIRS.items():
            _completed_row(
                primary["families"][family][pair], means[family]["ordnung"], means[family][baseline]
            )
    stability = primary["families"].get("F3_stability")
    for row in (stability or {}).values():
        row.setdefault("bonett_price", [row["diff"] - 0.05, row["diff"] + 0.05])
    for pair, block in primary["noninferiority"].items():
        block.setdefault("bootstrap", copy.deepcopy(primary["families"]["F1_accuracy"][pair]["bootstrap"]))
        block["bound"] = {"clusters": 104, "draws": None, "method": "exact", "seed": None} | block["bound"]
    primary.setdefault("reads_registered", 3)
    primary.setdefault("reads_used", list(range(1, reads + 1)))
    if "reads_missing" not in primary:
        primary["reads_missing"] = [
            {
                "read": read,
                "kinds": ["budget_cut"],
                "deviations": [_add_deviation(src, "budget_cut", {"split": "holdout4", "repeat": read})],
            }
            for read in range(reads + 1, 4)
        ]
    primary.setdefault(
        "not_run",
        {} if stability is not None else {"F3_stability": "fewer reads than min_reads (2)"},
    )
    primary.setdefault("decision_roles", analysis._decision_roles(primary["decisions"]))
    primary.setdefault(
        "confirmatory",
        {
            "decision": "beats_llm_only",
            "family": "F1_accuracy",
            "pair": PAIRS["llm_only"],
            "code": primary["decisions"]["beats_llm_only"],
        },
    )
    primary.setdefault("errors", _errors(primary))
    primary.setdefault("unanswered", [])
    newkinds = doc["secondary"]["newkinds"]
    if "not_recorded" in newkinds and set(newkinds["not_recorded"]) == {"reason"}:
        kind = str(newkinds["not_recorded"]["reason"])
        newkinds["not_recorded"] = {
            "read": 1,
            "kinds": [kind],
            "deviations": [_add_deviation(src, kind, {"split": "newkinds", "repeat": 1})],
        }
    elif "not_recorded" not in newkinds:
        newkinds.setdefault("unanswered", [])
        for summary in newkinds["conditions"].values():
            summary["exact"].setdefault("published_ci", list(summary["exact"]["ci"]))
    sensitivities = doc["sensitivities"]
    s_conv = sensitivities["s_conv"]
    if not s_conv.get("same_as_primary") and "conditions" in s_conv:
        _changed_sensitivity(s_conv, primary)
    for name in ("label_corrected", "first_attempt"):
        sensitivities.setdefault(name, {"deviations": [], "items_changed": 0, "same_as_primary": True})
    sensitivities.setdefault("same_day_f3", {"items": 0, "F3_stability": None})
    sensitivities.setdefault("same_cli_f3", {"versions": [], "same_as_primary": True})
    return doc, src


def _changed_sensitivity(block: dict[str, Any], primary: Mapping[str, Any]) -> None:
    """A sensitivity analysis whose items changed, in the real shape: per condition the dates right per read, the
    mean and the harmful item-reads; F1, F2, non-inferiority and the codes (the primary's rows, labelled beside)."""
    reads = int(primary["reads"])
    for condition, summary in block["conditions"].items():
        mean = float(summary["mean_accuracy"])
        summary.setdefault("exact_per_read", [round(mean * N)] * reads)
        summary.setdefault(
            "harmful_item_reads",
            sum(int(rate["k"]) for rate in primary["conditions"][condition]["harmful_per_read"]),
        )
    for family in ("F1_accuracy", "F2_harm"):
        block.setdefault(family, copy.deepcopy(primary["families"][family]))
    block.setdefault("noninferiority", copy.deepcopy(primary["noninferiority"]))
    block.setdefault(
        "decisions",
        {
            key: primary["decisions"][key]
            for key in (
                "beats_llm_only",
                "vs_llm_rules_text",
                "vs_llm_rules_tool",
                "f2_vs_llm_only",
                "f2_vs_llm_rules_text",
            )
        },
    )


def as_written(src: dict[str, Any]) -> dict[str, Any]:
    """The named results as the final run's tools write them: the Ask file of runs with its schema and meta, the
    stress file with its meta, the end-to-end file with its definitions, set-aside list and meta, the deviations well
    formed. Nothing the sentences read changes."""
    if src.get("ask") is not None and "schema" not in src["ask"]:
        runs = int(src["ask"]["consistency"]["runs"])
        src["ask"] = {
            "schema": "ordnung-eval-ask-final/1",
            "meta": {
                "kind": "ask-heldout-final",
                "date": "2026-12-09",
                "model": MODEL,
                "set": "heldout",
                "reads": runs,
                "registered_reads": final.ASK_REGISTERED_RUNS,
                "inputs": [],
            },
            **src["ask"],
        }
    if src.get("stress") is not None and "meta" not in src["stress"]:
        src["stress"] = {**src["stress"], "meta": {"date": "2026-12-08", "model": MODEL}}
    e2e = src.get("e2e")
    if e2e is not None and "definitions" not in e2e:
        src["e2e"] = {
            "schema": 1,
            "meta": {**e2e["meta"], "date": "2026-12-11", "model": MODEL, "backend": "replay"},
            "definitions": {},
            "metrics": e2e["metrics"],
            "set_aside": [],
        }
    src["deviations"] = (
        _deviations(src.get("deviations") or []) if src.get("deviations") is not None else None
    )
    return src


def complete_prereg(prereg: Mapping[str, Any]) -> dict[str, Any]:
    """The hand-built pre-registration with what the provenance reads: the registered commits and days, the data's
    hashes and the blind writing's (fake hashes, never the real ones)."""
    data = copy.deepcopy(dict(prereg))
    data.setdefault(
        "registered",
        {
            "freeze_sha": _hex("freeze")[:40],
            "freeze_pr": 51,
            "commit_a": _hex("letters")[:40],
            "planned_day": "2026-11-24",
            "valid_until": "2026-12-08",
        },
    )
    data["data"] = {"manifest_sha256": _hex("manifest"), "tree_sha256": _hex("tree")} | data["data"]
    data.setdefault(
        "blind_writing",
        {
            "holdout4": {"sandbox_files_sha256": _hex("sandbox"), "writer_log_sha256": _hex("writer log")},
            "audit": {"map_sha256": _hex("map"), "tallies": [_hex("tally 1"), _hex("tally 2")]},
            "statement": "written and audited by a model that is not the benchmarked one",
        },
    )
    return data


def scenario(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The hand-built final ``name`` of :data:`SCENARIOS` (spaces or underscores), completed, with its sources."""
    for label, make_final, make_sources in SCENARIOS:
        if label.replace(" ", "_") == name.replace(" ", "_"):
            return complete(make_final(), make_sources())
    raise KeyError(name)


# --------------------------------------------------------------------------------------------------
# A checkout with a final run
# --------------------------------------------------------------------------------------------------


def _write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else _text(data), encoding="utf-8")
    return path


def final_root(
    tmp_path: Path,
    final_doc: Mapping[str, Any] | None,
    *,
    sources: Mapping[str, Any] | None = None,
    prereg: Mapping[str, Any] | None = None,
    reads: Iterable[tuple[str, str]] = (),
    extra: Iterable[tuple[str, Any]] = (),
) -> Path:
    """``<tmp_path>/root``, a checkout as far as the presenter reads one: the README, a link to every committed
    results file, and the final analysis (``meta.prereg`` set to the written pre-registration), the pre-registration,
    the named files, the reads (``(name, text)`` in ``evals/results``) and ``extra`` files (``(path from the root,
    data)``) written beside them. A named file that is ``None`` is not written."""
    root = tmp_path / "root"
    results = root / "evals" / "results"
    results.mkdir(parents=True)
    shutil.copyfile(ROOT / "README.md", root / "README.md")
    for path in sorted(RESULTS.glob("*.json")):
        (results / path.name).symlink_to(path)
    if prereg is not None:
        written = _write(root / FILES["prereg"], prereg)
        digest = hashlib.sha256(written.read_bytes()).hexdigest()
    else:
        digest = "0" * 64
    if final_doc is not None:
        doc = copy.deepcopy(dict(final_doc))
        doc["meta"]["prereg"] = {"file": FILES["prereg"], "sha256": digest}
        _write(results / FINAL_NAME, doc)
    named = dict(sources or {})
    places = {"ask": f"evals/results/{ASK_NAME}", "stress": f"evals/results/{STRESS_NAME}"}
    places["e2e"] = f"evals/results/{E2E_NAME}"
    for name in ("power", "owner_labels", "owner_kappa", "deviations"):
        places[name] = FILES[name]
    for name, relative in places.items():
        if named.get(name) is not None:
            _write(root / relative, named[name])
    for name, text in reads:
        _write(results / name, text)
    for relative, data in extra:
        _write(root / relative, data)
    return root


def scenario_root(tmp_path: Path, name: str) -> Path:
    """:func:`final_root` of the hand-built scenario ``name``, completed."""
    doc, src = scenario(name)
    return final_root(tmp_path, doc, sources=src, prereg=complete_prereg(builders.prereg()))


def realistic_root(tmp_path: Path) -> Path:
    """:func:`final_root` of :func:`realistic`: the final analysis names the reads written beside it."""
    doc, src, reads = realistic()
    return final_root(tmp_path, doc, sources=src, prereg=complete_prereg(builders.prereg()), reads=reads)


def calibration_root(tmp_path: Path) -> Path:
    """:func:`final_root` of :func:`calibration`: its reads beside it, the earlier held-out splits linked."""
    doc, src, reads = calibration()
    return final_root(tmp_path, doc, sources=src, prereg=complete_prereg(builders.prereg()), reads=reads)


def published(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """What the presenter finds in ``root``: the final analysis, the pre-registration and the named files."""
    found = final.published(root)
    assert found is not None
    return found
