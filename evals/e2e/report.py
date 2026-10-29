"""The end-to-end results file, its console summary and its gates.

``evals/results/<date>-<model>-e2e.json`` (``-partial`` when letters were picked by id) holds ids, dates, kinds,
counts and verdicts — never a letter's words: an observation's titles, quotes and draft text stay in memory, and
the scam verdict's reasons are codes (:func:`evals.e2e.harness.reason_codes`). The file name and the rates'
wording are the benchmark's (:mod:`evals.report`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from evals import report as benchmark_report
from evals.e2e.check import LetterVerdict

SCHEMA = 1
NAME = "e2e"
#: The splits a run covers unless told otherwise: the four scored ones (pooled) and dev.
DEFAULT_SPLITS: tuple[str, ...] = ("test", "holdout", "holdout2", "holdout3", "dev")
#: The meta fields a replay at another commit or on another day may change without changing a number.
VOLATILE_META = ("date", "commit")

DEFINITIONS: dict[str, str] = {
    "obligation": "a required labelled item with one date, of a letter not labelled a scam",
    "parity": "the to-do's stored date equals the date the benchmark's Ordnung condition gives it, replayed without "
    "the sender's Land (E1)",
    "exact": "the to-do's stored date equals the labelled date",
    "reminded_in_time": "an alarm of the to-do's calendar event fires from the reading day to the labelled date (E2)",
    "lead_days": "the labelled date minus the day of the first alarm in time",
    "late_reminders": "every alarm from the reading day on fires after the labelled date (E3)",
    "not_reminded": "why an obligation got no alarm in time: reading_failed, not_stored, no_date, set_aside:<cause>, "
    "not_in_calendar, only_after_the_day, no_alarm_from_the_reading_day",
    "morning_note": "the agenda behind the desktop notification lists the to-do the day before the labelled date, or "
    "on the reading day when that is later (E4)",
    "scam": "letters labelled a scam: a scam Idea, nothing in the calendar; genuine letters: a scam Idea is a false "
    "alarm; obligations the app set aside, by cause (E5)",
    "idea_right": "a labelled deadline within its reminder window on the reading day has a deadline_soon Idea that "
    "names its to-do, with a day to act no later than the labelled date (E6)",
    "drafts": "the objection letter's PDF for a letter labelled with an Einspruch or Widerspruch: each element and "
    "all of them (E7); asking for one on a letter without a remedy is refused (E8)",
}
NOTE = (
    "Every letter read by the real app (add_file, ingest_document) on its own day, in a fresh data folder, from the "
    "benchmark's recorded readings (strict replay, no model called); the daily tick, the calendar export, the agenda "
    "behind the morning notification and, where labelled, the objection letter as a PDF. Nothing confirmed by the "
    "person: no sender's Land, no arrival day. The objection letter's optional model text has no recording, so its "
    "text is the code's alone. Checked against the manifest's labels by code that imports nothing of the app."
)


def results_path(
    run_date: str, model: str, folder: Path, *, splits: Sequence[str] = DEFAULT_SPLITS, partial: bool = False
) -> Path:
    """``<date>-<model>-e2e.json`` for the usual splits, ``…-e2e-<split>-<split>.json`` for others (a run of a
    final split never overwrites the earlier splits' run of the same day); ``-partial`` for letters picked by id."""
    name = NAME if list(splits) == list(DEFAULT_SPLITS) else "-".join([NAME, *splits])
    return folder / benchmark_report.results_filename(run_date, model, name, partial=partial)


def build_results(
    *,
    meta: Mapping[str, Any],
    verdicts: Sequence[LetterVerdict],
    summary: Mapping[str, Any],
    set_aside: Sequence[Mapping[str, Any]],
    errors: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """The results document (letters sorted by id)."""
    return {
        "schema": SCHEMA,
        "meta": dict(meta),
        "definitions": DEFINITIONS,
        "metrics": dict(summary),
        "set_aside": [dict(row) for row in set_aside],
        "errors": sorted((dict(error) for error in errors), key=lambda error: error["entry_id"]),
        "letters": [verdict.to_dict() for verdict in sorted(verdicts, key=lambda verdict: verdict.entry_id)],
    }


def _ids(values: Iterable[str]) -> str:
    return ", ".join(values)


def gate_failures(
    results: Mapping[str, Any],
    *,
    exact_parity: bool = False,
    max_late_reminders: int | None = None,
    known_set_aside: Sequence[str] | None = None,
    min_reminded: float | None = None,
) -> list[str]:
    """Why the run fails its gates (empty: it passes). A letter the harness couldn't run always fails."""
    failures = [f"{error['entry_id']}: {error['error']}" for error in results.get("errors", [])]
    metrics = results["metrics"]
    every = metrics["all"]
    if exact_parity:
        parity = every["parity"]
        if parity["n"] == 0:
            failures.append("parity: no obligation was compared with the benchmark's replay")
        elif parity["differ"]:
            failures.append(
                f"parity: {len(parity['differ'])} stored date(s) differ from the benchmark's: {_ids(parity['differ'])}"
            )
    if max_late_reminders is not None and len(every["late_reminders"]) > max_late_reminders:
        late = every["late_reminders"]
        failures.append(
            f"{len(late)} obligation(s) reminded only after the day (at most {max_late_reminders}): {_ids(late)}"
        )
    if known_set_aside is not None:
        found = sorted({row["entry_id"] for row in results.get("set_aside", [])})
        known = set(known_set_aside)
        new = [entry_id for entry_id in found if entry_id not in known]
        if new:
            failures.append(f"newly set aside (not reminded) genuine obligations: {_ids(new)}")
        ran = {row["entry_id"] for row in results["letters"]} if "letters" in results else None
        gone = sorted(entry_id for entry_id in known - set(found) if ran is None or entry_id in ran)
        if gone:
            failures.append(f"no longer set aside (take them off --known-set-aside): {_ids(gone)}")
    if min_reminded is not None:
        reminded = metrics["pooled"]["reminded_in_time"]
        value = reminded.get("value")
        if value is None or value < min_reminded:
            failures.append(
                f"reminded in time {benchmark_report.rate(reminded, ci=False, counts=True)} is below {min_reminded:.1%}"
            )
    return failures


def differences(fresh: Mapping[str, Any], published: Mapping[str, Any]) -> list[str]:
    """The top-level parts (and meta fields) where a fresh run differs from a published file, the date and the
    commit aside."""
    found = []
    for key in sorted(set(fresh) | set(published)):
        if key == "meta":
            meta_a, meta_b = fresh.get("meta", {}), published.get("meta", {})
            found += [
                f"meta.{name}"
                for name in sorted(set(meta_a) | set(meta_b))
                if name not in VOLATILE_META and meta_a.get(name) != meta_b.get(name)
            ]
        elif fresh.get(key) != published.get(key):
            found.append(key)
    return found


def _count(estimate: Mapping[str, Any]) -> str:
    return benchmark_report.rate(estimate, ci=False, counts=True)


def summary_lines(results: Mapping[str, Any]) -> list[str]:
    """One line per split and one for the pooled splits: ids and numbers only."""
    metrics = results["metrics"]
    groups = [*metrics["by_split"].items(), ("pooled", metrics["pooled"])]
    lines = []
    for name, block in groups:
        parity = block["parity"]
        scam = block["scam"]
        drafts = block["drafts"]
        not_reminded = " ".join(f"{cause}={n}" for cause, n in block["not_reminded"].items()) or "none"
        lines.append(
            f"{name:<9} letters {block['letters']:>3}  obligations {block['obligations']:>3}  "
            f"parity {parity['k']}/{parity['n']}  exact {_count(block['exact'])}  "
            f"reminded {_count(block['reminded_in_time'])}  late {len(block['late_reminders'])}  "
            f"note {_count(block['morning_note'])}  idea {_count(block['idea_right'])}  "
            f"scam idea {_count(scam['scam_idea'])}  scam in calendar {len(scam['in_the_calendar'])}  "
            f"false scam idea {_count(scam['false_scam_idea'])}  "
            f"drafts complete {_count(drafts['complete'])}  "
            f"refused w/o remedy {_count(drafts['objection_refused_without_remedy'])}  "
            f"not reminded: {not_reminded}"
        )
    return lines
