"""The power of the final run's pre-registered comparisons, by simulation (``evals/preregistration/power-0.4.0.json``).

Zero tokens: it reads results files and the dataset's manifest and calls no model. For each comparison of Ordnung
with a baseline — F1 (accuracy) and F2 (harm: late or missed) against each baseline, as the pre-registration's
analysis section names them — it gives the share of simulated final runs in which the registered rule decides it:

* ``power``: at the gap the held-out splits recorded before the freeze show (``observed``), with no run noise;
* ``power_half_gap``: at half that gap (what a smaller true difference would give);
* ``mdd``: the smallest gap, in steps of ``--step``, at which the rule decides it in at least ``--target`` of the
  runs (the minimal detectable difference), or ``None`` within ``--max-gap``;
* ``null``: with no gap at all, how often the sign-flip test rejects (about its level) and the rule decides.

What the rule decides (``detected_as``): F1 against a baseline Ordnung must be ahead of, ``clear``; F1 against a
baseline it must not trail by more than the margin (``noninferior_to``), ``non_inferior``; F2, ``fewer``.

**How a final run is simulated.**

* Its letters: the clusters (a letter with its photo) and their dated items, from the manifest's entries of the
  primary split (``--manifest``, ``--split``); while that split has no letters, the clusters of ``--runs``.
* Its rates: from ``--runs`` (the first reads of the held-out splits as recorded: ``evals.analysis``'s
  ``HELD_OUT_AS_RECORDED``), per family: Ordnung's rate, and per baseline the baseline's rate and the share of items
  on which the two differ (:func:`observed`).
* An item: Ordnung's outcome is drawn with Ordnung's rate; each baseline's, given Ordnung's, so that the difference
  of the two rates is the comparison's gap and the share of items where they differ is the observed one (at least
  the gap, and at most what the rates allow). The comparison asked about takes the scenario's gap, the others their
  observed gaps. Items are drawn independently, also within a letter.
* Its reads (the pre-registration's number): ``systematic``, each item has one outcome in every read (no run noise,
  as the held-out reads showed); or ``independent``, every read draws again.
* Its analysis, as the final run's (``evals.analysis``): per baseline the per-cluster totals over the reads, the
  two-sided cluster sign-flip test (``evals.stats.cluster_signflip``) with the registered seed and exact threshold,
  Holm within the family, the paired cluster bootstrap (``evals.stats.paired_cluster_bootstrap``), and the decision
  rule (:func:`family_decisions`: non-inferiority by the analysis' own interval). ``--draws`` and ``--resamples``
  set the sign-flip draws and bootstrap resamples of each simulated analysis, fewer than the final run's, for time;
  both are in the file.

A simulation's random numbers come from ``--seed``, the family, the comparison and the noise model, the same for
every gap, so a larger gap is the same simulated run with more differences. The run is deterministic: the same
inputs give the same file, whatever ``--workers``.

Run it from the repository root once the final letters exist, before the pre-registration is committed (it takes hours at the registered numbers; launch it
detached)::

    .venv/bin/python -m scripts.eval_power --prereg <draft final-0.4.0.json> --reps 2000 --draws 10000
        --seed 20261029 [--workers 4] [--out evals/preregistration/power-0.4.0.json | --check FILE]
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import random
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals import analysis, stats

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evals" / "results"
MANIFEST = ROOT / "evals" / "dataset" / "manifest.json"
OUT = ROOT / "evals" / "preregistration" / "power-0.4.0.json"
SCHEMA = "ordnung-prereg-power/1"
REFERENCE = "ordnung"
AGENT = "llm_rules_tool"
FAMILIES: dict[str, Callable[[analysis.Item], bool]] = {
    "F1_accuracy": lambda item: item.right,
    "F2_harm": lambda item: item.harmful,
}
NOISES = ("systematic", "independent")
TARGET = 0.8
STEP = 0.01
MAX_GAP = 0.3
REPS = 2000
DRAWS = 10_000
RESAMPLES = 2000
_EPS = 1e-12

Sums = list[tuple[int, int, int]]


@dataclass(frozen=True)
class Pair:
    """One comparison's rates: Ordnung's, the baseline's, and the share of items on which the two differ."""

    reference: float
    baseline: float
    discordance: float

    @property
    def gap(self) -> float:
        """Ordnung's rate minus the baseline's."""
        return self.reference - self.baseline


# --------------------------------------------------------------------------------------------------
# Inputs: the rates and the clusters
# --------------------------------------------------------------------------------------------------


def observed(runs: Sequence[analysis.Run], family: str) -> dict[str, Pair]:
    """Per baseline, Ordnung's rate, the baseline's and their discordance over the items of ``runs`` (one read each)."""
    test = FAMILIES[family]
    ours = {item.key: test(item) for run in runs for item in run.items[REFERENCE]}
    baselines = [c for c in runs[0].conditions if c != REFERENCE]
    pairs = {}
    for baseline in baselines:
        theirs = {item.key: test(item) for run in runs for item in run.items[baseline]}
        keys = sorted(ours.keys() & theirs.keys())
        n = len(keys)
        pairs[baseline] = Pair(
            reference=sum(ours[k] for k in keys) / n,
            baseline=sum(theirs[k] for k in keys) / n,
            discordance=sum(ours[k] != theirs[k] for k in keys) / n,
        )
    return pairs


def structure_from_runs(runs: Sequence[analysis.Run]) -> list[int]:
    """The dated items per cluster of ``runs`` (Ordnung's items), in cluster order."""
    counts: dict[str, int] = defaultdict(int)
    for run in runs:
        for item in run.items[REFERENCE]:
            counts[item.cluster] += 1
    return [counts[cluster] for cluster in sorted(counts)]


def structure_from_manifest(manifest: Mapping[str, Any], split: str) -> list[int]:
    """The dated items per cluster of the split's letters in the manifest: a photo is in its letter's cluster and its
    items count again (they are scored again)."""
    counts: dict[str, int] = defaultdict(int)
    for entry in manifest.get("entries") or []:
        if entry.get("split") != split:
            continue
        cluster = str(entry.get("source_id") or entry["id"])
        for item in (entry.get("truth") or {}).get("items") or []:
            due = item.get("expected_due")
            if isinstance(due, str) and len(due) == 10 and due[4] == "-" and due[7] == "-":
                counts[cluster] += 1
    return [counts[cluster] for cluster in sorted(counts) if counts[cluster]]


def cluster_sums(reads: Sequence[analysis.Run], baseline: str, family: str) -> Sums:
    """Per cluster, in the analysis' order: Ordnung's events, the baseline's, and the item-reads, over every read."""
    test = FAMILIES[family]
    theirs = {(run.repeat, item.key): item for run in reads for item in run.items[baseline]}
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for run in reads:
        for item in run.items[REFERENCE]:
            row = sums[item.cluster]
            row[0] += int(test(item))
            row[1] += int(test(theirs[(run.repeat, item.key)]))
            row[2] += 1
    return [(row[0], row[1], row[2]) for _, row in sorted(sums.items())]


# --------------------------------------------------------------------------------------------------
# The registered test and rule
# --------------------------------------------------------------------------------------------------


def detected_code(family: str, baseline: str, noninferior_to: Sequence[str]) -> str:
    """The decision that counts as the comparison decided."""
    if family == "F2_harm":
        return "fewer"
    return "non_inferior" if baseline in noninferior_to else "clear"


def _undecided(baseline: str) -> str:
    return "level_within_noise" if baseline == "llm_rules_text" else "no_clear_difference"


def _bootstrap(rows: Sums, settings: analysis.Settings) -> stats.PairedBootstrap:
    return stats.paired_cluster_bootstrap(
        [(float(a), float(b), float(n)) for a, b, n in rows],
        resamples=settings.resamples,
        seed=settings.seed,
        level=settings.level,
    )


def _noninferiority(baseline: str, rows: Sums, settings: analysis.Settings) -> str:
    """The analysis' non-inferiority rule: its inverted sign-flip interval where it has one, else its bootstrap one."""
    interval = getattr(analysis, "signflip_interval", None)
    decide = getattr(analysis, "noninferiority_decision", None)
    if interval is not None and decide is not None:
        bound = interval(
            [(a - b, n) for a, b, n in rows],
            level=settings.level,
            exact_max=settings.signflip_exact_max,
            draws=settings.signflip_draws,
            seed=settings.seed,
        )
        return str(decide(bound["lo"], bound["hi"], settings.noninferiority_margin, baseline))
    boot = _bootstrap(rows, settings)
    if boot.lo is not None and boot.lo > -settings.noninferiority_margin:
        return "non_inferior"
    if boot.hi is not None and boot.hi < 0:
        return "agent_higher" if baseline == AGENT else "baseline_higher"
    return "cannot_tell"


def _decide(family: str, baseline: str, rows: Sums, holm: float, prereg: analysis.Prereg) -> str:
    settings = prereg.settings
    if family == "F1_accuracy" and baseline in prereg.noninferior_to:
        return _noninferiority(baseline, rows, settings)
    if family == "F1_accuracy":
        higher, lower, otherwise = "clear", "baseline_ahead", _undecided(baseline)
    else:
        higher, lower, otherwise = "more", "fewer", "no_clear_difference"
    if holm >= settings.alpha:
        return otherwise
    boot = _bootstrap(rows, settings)
    if boot.lo is not None and boot.lo > 0:
        return higher
    if boot.hi is not None and boot.hi < 0:
        return lower
    return otherwise


def _pvalue(rows: Sums, settings: analysis.Settings) -> float:
    return stats.cluster_signflip(
        [a - b for a, b, _ in rows],
        exact_max=settings.signflip_exact_max,
        draws=settings.signflip_draws,
        seed=settings.seed,
    ).p


def family_decisions(
    sums: Mapping[str, Sums], family: str, prereg: analysis.Prereg
) -> dict[str, dict[str, Any]]:
    """One family as the analysis tests it: per baseline the sign-flip p, Holm's p and the decision."""
    baselines = [b for b in prereg.baselines if b in sums]
    pvalues = [_pvalue(sums[b], prereg.settings) for b in baselines]
    holm = stats.holm(pvalues)
    return {
        b: {"p": p, "holm": h, "decision": _decide(family, b, sums[b], h, prereg)}
        for b, p, h in zip(baselines, pvalues, holm, strict=True)
    }


# --------------------------------------------------------------------------------------------------
# The simulation
# --------------------------------------------------------------------------------------------------


def _conditional(reference: float, gap: float, discordance: float) -> tuple[float, float] | None:
    """P(the baseline's event | Ordnung's event) and P(… | no Ordnung event) for this gap and discordance; ``None``
    when no pair of rates gives that gap."""
    a = reference
    if not -_EPS <= a - gap <= 1 + _EPS:
        return None
    most = min(2 * a - gap, 2 * (1 - a) + gap)
    d = min(max(discordance, abs(gap)), most)
    if d < abs(gap) - _EPS:
        return None
    ahead, behind = (d + gap) / 2, (d - gap) / 2  # Ordnung's event alone, the baseline's alone
    given_event = 1 - ahead / a if a > 0 else 0.0
    given_none = behind / (1 - a) if a < 1 else 0.0
    return min(max(given_event, 0.0), 1.0), min(max(given_none, 0.0), 1.0)


def _seed(seed: int, *parts: str) -> int:
    digest = hashlib.sha256("|".join([str(seed), *parts]).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _draw(
    structure: Sequence[int],
    reference: float,
    conditional: Mapping[str, tuple[float, float]],
    reads: int,
    noise: str,
    rng: random.Random,
) -> dict[str, Sums]:
    copies, scale = (1, reads) if noise == "systematic" else (reads, 1)
    sums: dict[str, Sums] = {b: [] for b in conditional}
    for size in structure:
        ours = 0
        theirs = dict.fromkeys(conditional, 0)
        for _ in range(size * copies):
            event = rng.random() < reference
            ours += event
            for b, (given_event, given_none) in conditional.items():
                theirs[b] += rng.random() < (given_event if event else given_none)
        for b in conditional:
            sums[b].append((ours * scale, theirs[b] * scale, size * reads))
    return sums


def power(
    *,
    structure: Sequence[int],
    pairs: Mapping[str, Pair],
    family: str,
    baseline: str,
    gap: float,
    prereg: analysis.Prereg,
    reads: int,
    noise: str,
    reps: int,
    draws: int,
    resamples: int,
    seed: int,
) -> dict[str, float] | None:
    """Over ``reps`` simulated final runs with ``baseline`` at ``gap``: how often its sign-flip test rejects at the
    registered level (``rejects``) and how often the rule decides it (``detected``); ``None`` for an impossible gap."""
    reference = pairs[baseline].reference
    conditional: dict[str, tuple[float, float]] = {}
    for b, pair in pairs.items():
        found = _conditional(reference, gap if b == baseline else pair.gap, pair.discordance)
        if found is None:
            if b == baseline:
                return None
            raise ValueError(f"{family} {b}: the observed rates do not fit Ordnung's rate {reference}")
        conditional[b] = found
    simulated = dataclasses.replace(
        prereg, settings=dataclasses.replace(prereg.settings, signflip_draws=draws, resamples=resamples)
    )
    settings = simulated.settings
    baselines = [b for b in simulated.baselines if b in conditional]
    target = detected_code(family, baseline, simulated.noninferior_to)
    rng = random.Random(_seed(seed, family, baseline, noise))
    rejects = detected = 0
    for _ in range(reps):
        sums = _draw(structure, reference, {b: conditional[b] for b in baselines}, reads, noise, rng)
        pvalues = [_pvalue(sums[b], settings) for b in baselines]
        holm = stats.holm(pvalues)
        index = baselines.index(baseline)
        rejects += pvalues[index] < settings.alpha
        detected += _decide(family, baseline, sums[baseline], holm[index], simulated) == target
    return {"rejects": rejects / reps, "detected": detected / reps}


def _grid(family: str, baseline: str, prereg: analysis.Prereg, step: float, max_gap: float) -> list[float]:
    """The gaps the minimal detectable difference is looked for at, smallest first, in the direction that counts."""
    count = round(max_gap / step)
    if family == "F2_harm":
        return [-round(step * i, 10) for i in range(1, count + 1)]
    if baseline in prereg.noninferior_to:
        start = -round(prereg.settings.noninferiority_margin / step)
        return [round(step * i, 10) for i in range(start + 1, count + 1)]
    return [round(step * i, 10) for i in range(1, count + 1)]


@dataclass(frozen=True)
class _Task:
    structure: tuple[int, ...]
    pairs: Mapping[str, Pair]
    family: str
    baseline: str
    prereg: analysis.Prereg
    reads: int
    noise: str
    reps: int
    draws: int
    resamples: int
    seed: int
    target: float
    step: float
    max_gap: float


def _sequence(task: _Task) -> dict[str, Any]:
    """One comparison under one noise model: no gap, the observed gap, half of it, and the minimal detectable gap."""

    def at(gap: float) -> dict[str, float] | None:
        return power(
            structure=task.structure,
            pairs=task.pairs,
            family=task.family,
            baseline=task.baseline,
            gap=gap,
            prereg=task.prereg,
            reads=task.reads,
            noise=task.noise,
            reps=task.reps,
            draws=task.draws,
            resamples=task.resamples,
            seed=task.seed,
        )

    gap = task.pairs[task.baseline].gap
    observed_power, half = at(gap), at(gap / 2)
    grid = _grid(task.family, task.baseline, task.prereg, task.step, task.max_gap)
    seen: dict[int, float] = {}

    def detected(index: int) -> float:
        if index not in seen:
            found = at(grid[index])
            seen[index] = -1.0 if found is None else found["detected"]
        return seen[index]

    mdd = None
    feasible = [
        i for i, g in enumerate(grid) if _conditional(task.pairs[task.baseline].reference, g, 0.0) is not None
    ]
    if feasible:
        lo, hi = feasible[0], feasible[-1]
        if detected(hi) >= task.target:
            while lo < hi:
                mid = (lo + hi) // 2
                if detected(mid) >= task.target:
                    hi = mid
                else:
                    lo = mid + 1
            mdd = {"gap": grid[lo], "power": detected(lo)}
    return {
        "null": at(0.0),
        "observed": None if observed_power is None else observed_power["detected"],
        "half_gap": None if half is None else half["detected"],
        "mdd": mdd,
    }


def run(
    prereg_data: Mapping[str, Any],
    runs: Sequence[analysis.Run],
    *,
    structure: Sequence[int],
    structure_source: str,
    reps: int = REPS,
    draws: int = DRAWS,
    resamples: int = RESAMPLES,
    seed: int = stats.SEED,
    target: float = TARGET,
    step: float = STEP,
    max_gap: float = MAX_GAP,
    noises: Sequence[str] = NOISES,
    workers: int = 1,
    inputs: Sequence[Mapping[str, str]] = (),
    prereg_record: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The power file (see the module's docstring)."""
    prereg = analysis.parse_prereg(prereg_data)
    observed_pairs = {family: observed(runs, family) for family in FAMILIES}
    tasks = [
        _Task(
            tuple(structure),
            observed_pairs[family],
            family,
            baseline,
            prereg,
            prereg.primary_reads,
            noise,
            reps,
            draws,
            resamples,
            seed,
            target,
            step,
            max_gap,
        )
        for family in FAMILIES
        for baseline in prereg.baselines
        for noise in noises
    ]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_sequence, tasks))
    else:
        results = [_sequence(task) for task in tasks]
    found = {(t.family, t.baseline, t.noise): result for t, result in zip(tasks, results, strict=True)}
    comparisons: dict[str, Any] = {}
    for family, pairs in observed_pairs.items():
        comparisons[family] = {}
        for baseline in prereg.baselines:
            pair = pairs[baseline]
            first = found[(family, baseline, noises[0])]
            comparisons[family][f"{REFERENCE}-vs-{baseline}"] = {
                "detected_as": detected_code(family, baseline, prereg.noninferior_to),
                "observed": {
                    "reference": pair.reference,
                    "baseline": pair.baseline,
                    "gap": pair.gap,
                    "discordance": pair.discordance,
                },
                "power": first["observed"],
                "power_half_gap": first["half_gap"],
                "mdd": first["mdd"],
                "noise": {noise: found[(family, baseline, noise)] for noise in noises},
            }
    settings = prereg.settings
    return {
        "schema": SCHEMA,
        "about": (
            "The power of the final run's pre-registered comparisons by simulation: how often the registered test "
            "and rule decide each comparison at the gap the held-out splits show (power), at half of it, and the "
            f"smallest gap they decide in {target:.0%} of simulated runs (mdd). power, power_half_gap and mdd are "
            f"for the first noise model ({noises[0]}); 'noise' gives every model's."
        ),
        "prereg": dict(prereg_record or {}),
        "inputs": [dict(row) for row in inputs],
        "structure": {"source": structure_source, "clusters": len(structure), "items": sum(structure)},
        "settings": {
            "reps": reps,
            "draws": draws,
            "resamples": resamples,
            "seed": seed,
            "target": target,
            "step": step,
            "max_gap": max_gap,
            "noise": list(noises),
            "reads": prereg.primary_reads,
            "alpha": settings.alpha,
            "level": settings.level,
            "analysis_seed": settings.seed,
            "signflip_exact_max": settings.signflip_exact_max,
            "noninferiority_margin": settings.noninferiority_margin,
        },
        "model": {
            "items": (
                "Ordnung's outcome drawn with its observed rate; each baseline's given Ordnung's, so that the "
                "difference of the rates is the gap and the share of items where they differ is the observed one "
                "(at least the gap); items independent, also within a letter"
            ),
            "systematic": "each item has one outcome in every read",
            "independent": "every read draws each item again",
        },
        "comparisons": comparisons,
    }


def render(document: Mapping[str, Any]) -> str:
    """The file's text: floats rounded as the analysis rounds them, so a render is byte for byte the same."""
    return analysis.render(document)


def _file(path: Path) -> dict[str, str]:
    try:
        name = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        name = path.name
    return {"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.eval_power", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--prereg", type=Path, required=True, help="the (draft) pre-registration: its analysis section"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="the clusters of the primary split")
    parser.add_argument(
        "--runs", type=Path, nargs="+", help="results files the rates come from (default: held out)"
    )
    parser.add_argument("--reps", type=int, default=REPS, help="simulated final runs per gap")
    parser.add_argument("--draws", type=int, default=DRAWS, help="sign-flip draws per simulated analysis")
    parser.add_argument(
        "--resamples", type=int, default=RESAMPLES, help="bootstrap resamples per simulated analysis"
    )
    parser.add_argument("--seed", type=int, default=stats.SEED)
    parser.add_argument("--target", type=float, default=TARGET)
    parser.add_argument("--step", type=float, default=STEP)
    parser.add_argument("--max-gap", type=float, default=MAX_GAP)
    parser.add_argument("--noise", nargs="+", choices=NOISES, default=list(NOISES))
    parser.add_argument("--workers", type=int, default=1, help="processes (the file does not depend on it)")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--out", type=Path, default=OUT, help=f"default: {OUT.relative_to(ROOT)}")
    where.add_argument("--check", type=Path, metavar="FILE", help="exit 1 unless FILE is what this run gives")
    args = parser.parse_args(argv)
    prereg_data = json.loads(args.prereg.read_text(encoding="utf-8"))
    paths = args.runs or [RESULTS_DIR / name for name in analysis.HELD_OUT_AS_RECORDED]
    runs = [analysis.read_run(path) for path in paths]
    split = analysis.parse_prereg(prereg_data).primary_split
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest.is_file() else {}
    structure = structure_from_manifest(manifest, split)
    source = f"the manifest's {split} letters"
    if not structure:
        structure, source = structure_from_runs(runs), f"the runs' clusters (no {split} letters yet)"
    document = run(
        prereg_data,
        runs,
        structure=structure,
        structure_source=source,
        reps=args.reps,
        draws=args.draws,
        resamples=args.resamples,
        seed=args.seed,
        target=args.target,
        step=args.step,
        max_gap=args.max_gap,
        noises=args.noise,
        workers=args.workers,
        inputs=[_file(path) for path in paths],
        prereg_record=_file(args.prereg),
    )
    text = render(document)
    if args.check is not None:
        same = args.check.is_file() and args.check.read_text(encoding="utf-8") == text
        print(f"{args.check.name}: {'up to date' if same else 'differs from this run'}")
        return 0 if same else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"{args.out.name}: written ({len(document['comparisons'])} families)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
