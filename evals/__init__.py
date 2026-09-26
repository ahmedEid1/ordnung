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
:mod:`evals.report` (results JSON, ``docs/evals.md``, chart) and :mod:`evals.run` (CLI:
``python -m evals.run``; :func:`evals.run.run_cli` for ``ordnung eval``).
"""

from __future__ import annotations

__version__ = "1"
