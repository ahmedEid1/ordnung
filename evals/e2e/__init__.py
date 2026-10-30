"""End to end: from a benchmark letter's file to what reaches the person (zero tokens).

The reading benchmark (:mod:`evals.run`) stops at the computed due date, in a harness that is not the app
(``evals/conditions.py``: "without the app, the database or the global clock"). This package runs every
benchmark letter through **the real app** with the benchmark's own recorded readings, and checks what the person
gets: the stored to-do, the calendar file's alarms, the morning note, the Ideas and the objection letter as a
PDF.

**Harness** (:mod:`evals.e2e.harness`). For each manifest entry: a fresh data folder whose profile is the
benchmark persona (its language, the person's own Land, no Land for the sender: nothing confirmed, as on day one)
and whose model settings name the pinned model, so the app's requests key the benchmark's recordings
(``evals/recorded/<model>``, strict replay: a reading without its recording fails the run by name); then
``add_file`` and ``ingest_document`` on the letter's own day; the daily tick (the Ideas); the calendar export
(``build_ics``) and the agenda behind the morning notification (``build_agenda``) on the days that matter; and,
for a letter whose labelled remedy is an Einspruch or Widerspruch, ``compose("objection")`` rendered to the PDF the
person sends (for a letter without a remedy, the same request, which must be refused). The objection letter's
optional model text has no recording, so its text is the code's alone. The person's name is empty while a letter
is read (as in the recordings) and set before drafting.

**Checker** (:mod:`evals.e2e.check`). It imports nothing of the app — no rules engine, no draft checks, no Ask
check (a test enforces it) — and reads only the manifest's labels and what the harness observed: the to-dos'
dates, the calendar file's alarms, the agenda's lines, the Ideas' references and the PDF's text. A labelled
obligation is matched to the app's to-do by the benchmark's own matching (:func:`evals.metrics.match_items`).

**Metrics** (:mod:`evals.e2e.metrics`). On the dated obligations of genuine letters (not labelled a scam):

* **E1 parity** — the stored to-do's date equals the date the benchmark's Ordnung condition gives for the same
  obligation when replayed without the sender's Land (``scripts/eval_without_land.py``): the app and the benchmark
  are the same product (a CI gate: ``--exact-parity``).
* **E2 reminded in time** (primary) — a calendar alarm of its to-do fires on a day from the reading day to the
  labelled date; with the lead (days before the date of the first such alarm).
* **E3 reminded only after the day** — every alarm from the reading day on comes after the labelled date (target
  0; a gate: ``--max-late-reminders``).
* **E4 on the morning note** — the agenda behind the desktop notification lists the to-do (overdue, today or in
  the next 7 days) the day before the labelled date, or on the reading day when that is later.
* **E5 scam handling** — letters labelled a scam: a scam Idea, and nothing in the calendar; genuine letters: a
  scam Idea is a false alarm; and every genuine obligation the app set aside, with the cause (the app's scam
  verdict's reasons as codes, never their words).
* **E6 Idea right** — a labelled deadline within its reminder window on the reading day has a ``deadline_soon``
  Idea that names its to-do, with a day to act no later than the labelled date.
* **E7 objection letter complete** — every element of the PDF the person sends (:data:`evals.e2e.check.
  DRAFT_ELEMENTS`), each with a mutation test (take it away and the check fails); and the app's own checks.
* **E8 objection refused** — on a letter without a remedy, asking for an objection is refused.

Rates carry the benchmark's interval (:func:`evals.metrics.bootstrap_ratio`: a 95 % bootstrap over letters, a
photo resampled with the PDF it was rendered from; Wilson at 0 or 1). Results: ``evals/results/<date>-<model>-
e2e.json`` — ids, dates, kinds, counts and verdicts, never a letter's text. Run it from the repository root::

    .venv/bin/python -m evals.e2e [--splits test holdout holdout2 holdout3 dev] [--exact-parity] ...
"""

from __future__ import annotations
