"""The Ask benchmark: can you trust what Ask says? (ADR 0008, ``docs/evals-ask.md``).

~50 questions about Sam Rivera's sample life — the demo's — asked through the app's real Ask agent
(MCP tools, prompt, answer check), with gold answers computed from the sample life's hand-written
truth, plus a set of letters with injected text. Replayed from recordings by default, so the numbers
recompute exactly and at no cost; ``--live`` records with the ``claude`` CLI.

Modules: :mod:`evals.ask.questions` (questions and gold from the truth), :mod:`evals.ask.attacks`
(the injected letters and what counts as a successful attack), :mod:`evals.ask.ledger` (the demo
ledger and its injected copies), :mod:`evals.ask.parse` (an independent reader of dates and amounts),
:mod:`evals.ask.score` (per-question scores), :mod:`evals.ask.metrics` (bootstrap summaries),
:mod:`evals.ask.run` (asking, replay and recording), :mod:`evals.ask.report` (results file and page)
and ``python -m evals.ask`` (the command line and the CI gate).
"""
