# ADR 0008 — The rules engine as MCP tools, rules-only by default

**Status:** accepted · **Date:** 2026-09-26

## Context
The rules engine was only reachable inside the app, while many people already ask Claude Desktop or
Claude Code about their letters — where the model does the date arithmetic itself, and gets German
law wrong (the benchmark's *LLM only*: 82 % of due dates right, 7 % dangerously late). Ordnung
already had an MCP server, but it serves the person's ledger: added to another client, everything
Claude reads through it also reaches every other MCP server loaded there, through the model.

## Decision
- The engine is served as **ledger-free tools** (`ordnung/assistant/rules_tools.py`):
  `compute_deadline` takes what a letter *says* — the extractor's `DateSpec`, validated strictly —
  plus the letter's date, sender and region, never a question; `german_holidays`,
  `add_working_days` and `check_iban` expose the calendar and the IBAN check. Results carry the
  engine's receipt, hints for missing facts and "information, not legal advice"; they echo no letter
  text. ADR 0002 holds across the process boundary: the model reads, code computes.
- `ordnung mcp --rules-only` serves only these tools and opens no data folder. It is what the docs
  and `ordnung mcp install` lead with; the full ledger server (which also carries the tools) needs
  the data folder named and prints what it exposes.
- `ordnung mcp install` prints first and writes only with `--write`, under a written merge policy:
  only Ordnung's entry changes, the file is backed up, a file that is not a JSON object is refused
  untouched, an app's settings folder is never created.
- The benchmark measures the alternative this invites — an agent with Ordnung's engine as a tool
  instead of the fixed pipeline — as a fourth condition, on the same letters.

## Consequences
The engine reaches people where they already are, without their data. The fourth condition answers
"why a fixed pipeline instead of an agent with a calculator?" with data ([evals](../evals.md)): with
the tool the same model reached the pipeline's accuracy (98.2 % on the test split, no dangerous-late
date), so the pipeline's case rests on what an agent's answer lacks — a quote checked against the
page, a stored receipt per date, the same date for the same letter every time, and no reliance on
the model choosing to call the tool (it skipped it for 16 dates it judged simple, and overrode it
once). Tool results are part of the benchmark recording, so an engine change does not re-score that
condition; it has to be recorded again.
