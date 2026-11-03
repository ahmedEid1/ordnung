"""The owner's check of the held-out Ask scorer: answers of the first run, drawn blind, labelled by hand, and Cohen's κ
between the owner's labels and the scorer's (``evals/preregistration/owner-kappa-0.4.0.json``).

The check never blocks anything: the pre-registration says it is pending, and the report says "not yet checked by a
person" until it is done. Its file goes through three states, each written by this module:

1. **pending** (in the pre-registration): the sampler and its seed, no answer drawn (:func:`pending_record`);
2. **drawn** (after the first held-out run): :data:`SAMPLE_SIZE` question ids of run 1, stratified by question
   category with :func:`stratified_sample`, and the run's file and sha256 — ids only, so the owner labels each answer
   without the scorer's verdict (:func:`drawn_record`);
3. **done**: the owner's labels, κ over every (answer, aspect) pair both labelled, and κ per aspect
   (:func:`scored_record`).

The owner labels each answer on :data:`ASPECTS`, the scorer's verdicts in :func:`scorer_labels`:

* ``abstained``: the answer says the letters do not tell (``scores.abstained_final``);
* ``false_inclusion``: a list answer gives a to-do outside the asked window (``strict.list_false`` > 0; only for a
  question that asks for a list);
* ``harmful``: the answer would make the person act too late or on a wrong value, a household member's value given
  as the person's own included (``strict.harmful``).

``python -m evals.ask.owner --pending | --draw RUN1 | --score FILE --run RUN1 [--out FILE]`` writes the file (to
stdout without ``--out``). Nothing here reads or writes a question's or an answer's text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Hashable, Iterable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

SCHEMA = "ordnung-owner-kappa/1"
SEED = 20261029
SAMPLE_SIZE = 40
STRATA = "category"
ASPECTS = ("abstained", "false_inclusion", "harmful")


def cohen_kappa(pairs: Iterable[tuple[Hashable, Hashable]]) -> float | None:
    """Cohen's κ of two raters' labels, one pair per item: ``(p_o − p_e) / (1 − p_e)``. ``None`` with no pairs, or
    when chance alone agrees fully (both raters used one and the same label)."""
    rows = list(pairs)
    if not rows:
        return None
    n = len(rows)
    first: dict[Hashable, int] = {}
    second: dict[Hashable, int] = {}
    for a, b in rows:
        first[a] = first.get(a, 0) + 1
        second[b] = second.get(b, 0) + 1
    observed = Fraction(sum(1 for a, b in rows if a == b), n)
    expected = sum((Fraction(first[k], n) * Fraction(second.get(k, 0), n) for k in first), Fraction(0))
    if expected == 1:
        return None
    return float((observed - expected) / (1 - expected))


def allocate(sizes: Mapping[str, int], n: int) -> dict[str, int]:
    """How many of ``n`` draws each stratum gets: in proportion to its size, by largest remainder, at least one each
    (when ``n`` allows it) and never more than it holds. Ties go to the stratum named first."""
    total = sum(sizes.values())
    if n > total:
        raise ValueError(f"{n} draws asked for, only {total} to draw from")
    quota = {name: Fraction(n * size, total) for name, size in sizes.items()}
    floor = 1 if n >= len(sizes) else 0
    alloc = {name: min(size, max(floor, int(quota[name]))) for name, size in sizes.items()}
    order = sorted(sizes)
    while sum(alloc.values()) > n:
        over = [name for name in order if alloc[name] > max(floor, 0) and alloc[name] > 0]
        name = max(over, key=lambda s: (alloc[s] - quota[s], -order.index(s)))
        alloc[name] -= 1
    while sum(alloc.values()) < n:
        room = [name for name in order if alloc[name] < sizes[name]]
        name = max(room, key=lambda s: (quota[s] - alloc[s], -order.index(s)))
        alloc[name] += 1
    return alloc


def _rng(seed: int, *parts: str) -> random.Random:
    digest = hashlib.sha256("|".join([str(seed), *parts]).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def stratified_sample(
    rows: Sequence[Mapping[str, Any]], *, key: str, n: int, seed: int, ident: Sequence[str] = ("id",)
) -> list[Mapping[str, Any]]:
    """``n`` rows drawn without replacement, stratified by ``rows[i][key]`` (:func:`allocate`), each stratum drawn
    with its own generator seeded from ``seed`` and its name, the rows taken in their ``ident`` order: the same rows,
    seed and size always give the same sample, in stratum then id order."""
    strata: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        strata.setdefault(str(row[key]), []).append(row)
    counts = allocate({name: len(members) for name, members in strata.items()}, n)
    sample: list[Mapping[str, Any]] = []
    for name in sorted(strata):
        members = sorted(strata[name], key=lambda row: tuple(str(row[field]) for field in ident))
        chosen = _rng(seed, key, name).sample(range(len(members)), counts[name])
        sample.extend(members[i] for i in sorted(chosen))
    return sample


def sample_answers(
    results: Mapping[str, Any], n: int = SAMPLE_SIZE, seed: int = SEED, strata: str = STRATA
) -> list[dict[str, str]]:
    """``n`` question ids of an Ask results file of run 1, stratified by ``strata``; ids and categories only."""
    if int(results.get("repeat") or 1) != 1:
        raise ValueError(f"the sample is drawn from repeat 1, this file is repeat {results.get('repeat')}")
    questions = [row for row in results.get("questions") or [] if isinstance(row, Mapping)]
    chosen = stratified_sample(questions, key=strata, n=n, seed=seed)
    return [{"id": str(row["id"]), "category": str(row[strata])} for row in chosen]


def scorer_labels(row: Mapping[str, Any]) -> dict[str, bool | None]:
    """The scorer's verdict on each of :data:`ASPECTS` for one question's row (``None``: the aspect does not apply)."""
    scores = row.get("scores") or {}
    strict = row.get("strict") or {}
    listed = int(strict.get("list_gold") or 0) > 0
    return {
        "abstained": bool(scores.get("abstained_final")),
        "false_inclusion": int(strict.get("list_false") or 0) > 0 if listed else None,
        "harmful": bool(strict.get("harmful")),
    }


def _base(seed: int, n: int) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "pending",
        "about": (
            "The owner's check of the held-out Ask scorer: answers of the first run, drawn blind, labelled by hand on "
            f"{', '.join(ASPECTS)}, and Cohen's kappa between the owner's labels and the scorer's. It never blocks "
            "anything; until it is done the report says the scores are not yet checked by a person."
        ),
        "sampler": "evals.ask.owner.sample_answers",
        "seed": seed,
        "n": n,
        "strata": STRATA,
        "aspects": list(ASPECTS),
        "run": None,
        "sample": None,
        "labels": None,
        "answers": None,
        "kappa": None,
        "by_aspect": None,
    }


def pending_record(seed: int = SEED, n: int = SAMPLE_SIZE) -> dict[str, Any]:
    """The file as the pre-registration holds it: nothing drawn yet."""
    return _base(seed, n)


def drawn_record(run: Path, seed: int = SEED, n: int = SAMPLE_SIZE) -> dict[str, Any]:
    """The sample drawn from run 1's results file: ids, the run's name and sha256; still pending."""
    raw = run.read_bytes()
    record = _base(seed, n)
    record["run"] = {"file": run.name, "sha256": hashlib.sha256(raw).hexdigest()}
    record["sample"] = sample_answers(json.loads(raw), n=n, seed=seed)
    return record


def scored_record(
    record: Mapping[str, Any], results: Mapping[str, Any], labels: Mapping[str, Mapping[str, bool | None]]
) -> dict[str, Any]:
    """The drawn file with the owner's labels and κ: pooled over every (answer, aspect) pair both labelled, and per
    aspect (``n`` pairs, ``agree`` of them, ``kappa``). ``ValueError`` when a drawn answer has no labels."""
    sample = record.get("sample") or []
    ids = [str(row["id"]) for row in sample]
    missing = [ident for ident in ids if ident not in labels]
    if missing:
        raise ValueError(f"no labels for {', '.join(missing)}")
    rows = {str(row.get("id")): row for row in results.get("questions") or []}
    pairs: dict[str, list[tuple[bool, bool]]] = {aspect: [] for aspect in ASPECTS}
    for ident in ids:
        scorer = scorer_labels(rows[ident])
        for aspect in ASPECTS:
            mine, theirs = labels[ident].get(aspect), scorer[aspect]
            if mine is not None and theirs is not None:
                pairs[aspect].append((bool(mine), bool(theirs)))
    out = dict(record)
    out["status"] = "done"
    out["labels"] = {ident: {aspect: labels[ident].get(aspect) for aspect in ASPECTS} for ident in ids}
    out["answers"] = len(ids)
    out["kappa"] = cohen_kappa(pair for aspect in ASPECTS for pair in pairs[aspect])
    out["by_aspect"] = {
        aspect: {
            "n": len(pairs[aspect]),
            "agree": sum(1 for a, b in pairs[aspect] if a == b),
            "kappa": cohen_kappa(pairs[aspect]),
        }
        for aspect in ASPECTS
    }
    return out


def _write(record: Mapping[str, Any], out: Path | None) -> None:
    text = json.dumps(record, ensure_ascii=False, indent=1) + "\n"
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.ask.owner", description=__doc__.split("\n\n")[0])
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--pending", action="store_true", help="the file as the pre-registration holds it")
    what.add_argument("--draw", type=Path, metavar="RUN1", help="draw the sample from run 1's results file")
    what.add_argument("--score", type=Path, metavar="FILE", help="a drawn file with the owner's labels in it")
    parser.add_argument(
        "--run", type=Path, help="with --score: run 1's results file the sample was drawn from"
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, help="write here (default: print)")
    args = parser.parse_args(argv)
    if args.pending:
        _write(pending_record(args.seed), args.out)
        return 0
    if args.draw is not None:
        _write(drawn_record(args.draw, args.seed), args.out)
        return 0
    if args.run is None:
        parser.error("--score needs --run")
    record = json.loads(args.score.read_text(encoding="utf-8"))
    raw = args.run.read_bytes()
    if (record.get("run") or {}).get("sha256") != hashlib.sha256(raw).hexdigest():
        parser.exit(1, f"{parser.prog}: {args.run.name} is not the run the sample was drawn from\n")
    try:
        _write(scored_record(record, json.loads(raw), record.get("labels") or {}), args.out)
    except ValueError as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
