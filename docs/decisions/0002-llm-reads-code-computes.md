# ADR 0002 — The LLM reads, deterministic code computes dates

**Status:** accepted · **Date:** 2026-09-25

## Context
German deadlines hide traps: since 2025 a posted tax assessment counts as delivered on the **4th**
day after posting (it used to be the 3rd), that day moves to Monday if it is a weekend for tax law
but *not* for general administrative law, month periods end on the same-numbered day, notice periods
never move to the next working day, and regional holidays depend on the authority's seat. In early
tests the model's free-text explanation still quoted the old 3-day rule.

## Decision
The extraction model never outputs a computed relative deadline. It returns a **`DateSpec`** —
*what the document says* (`relative`, anchor `deemed_delivery`, 1 month, nature `objection`,
original wording) — and a pure, unit-tested **rules engine** (`ordnung.rules`) computes the date,
producing a *receipt*: a plain-language sentence, the steps, the rule ids and statute citations,
the holiday calendar used, and a confidence level with reasons.

## Consequences
- Dates are reproducible, testable (worked legal examples + Hypothesis properties) and explainable
  ("Why this date?").
- The eval can separate **reading errors** (wrong DateSpec) from **computing errors** (wrong date
  from a correct reading) — see [evals](../evals.md).
- The engine follows an *earliest plausible date* safety policy when inputs are uncertain.
- New rules require code (and tests), not prompt tweaks — intentional.
