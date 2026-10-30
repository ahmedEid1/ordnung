"""Ordnung's deadline benchmark (SPEC § 17).

Four conditions read the same letters with the same model, the same per-letter "today" and the same
holiday region:

* ``ordnung`` — the real pipeline logic: transcribe (photos) → extract a ``DateSpec`` → verify the
  quotes against the page text → compute every date with the deterministic rules engine;
* ``llm_only`` — the model reads the letter and computes the final due dates itself, told to apply
  current German law;
* ``llm_rules_text`` — the same, with a verified summary of the relevant rules pasted into the prompt;
* ``llm_rules_tool`` — the ``llm_only`` prompt, and the model may call Ordnung's rules engine as MCP
  tools (``ordnung mcp --rules-only``): an agent with a calculator.

Modules: :mod:`evals.records` (manifest and prediction models), :mod:`evals.conditions` (the four
conditions), :mod:`evals.metrics` (matching, error taxonomy, bootstrap CIs — pure),
:mod:`evals.report` (results JSON, a run's page and chart), :mod:`evals.run` (CLI:
``python -m evals.run``; :func:`evals.run.run_cli` for ``ordnung eval``), :mod:`evals.present` (what a reader
sees: the README block, ``docs/evals.md``, the history page, the charts and the report page),
:mod:`evals.reproduce` (``make eval-reproduce``: every published number replayed with no model call and compared
with ``evals/results/INDEX.json``) and :mod:`evals.export` (``evals/results/items.csv``: ids, dates and outcomes).

The evaluation's own modules: :mod:`evals.harness` (safe, repeated recording: ``--repeat``, ``--max-cost-usd``,
``--wait-on-limit``, the recorder lock and ``unlock``, the ledger, the request lock, the live smoke, and a recording's
day), :mod:`evals.splits` (the split registry), :mod:`evals.stats` (exact and clustered statistics),
:mod:`evals.analysis` (the held-out re-analysis and the pre-registered final analysis), :mod:`evals.e2e` (a letter's
file through the real app to its reminder), :mod:`evals.perturb` (the stress cells: targeted injections and distractor
dates) and :mod:`evals.ask` (the Ask benchmark: the development set, its household group, and the held-out set).
"""

from __future__ import annotations

__version__ = "1"
