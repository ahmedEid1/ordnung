# ADR 0009 — The rules engine as MCP tools, rules-only by default

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
- `ordnung mcp --rules-only` serves only these tools and opens no data folder. It is what
  `ordnung mcp install` adds; the full ledger server (which also carries the tools) needs an explicit
  `--with-ledger`, and the install command shows what it exposes before it prints or writes the
  entry. In Claude Code the ledger goes only into the person's local scope (`claude mcp add --scope
  local`), never into a project's `.mcp.json`, which is usually committed and shared. Options that
  would be dropped (put before `install`, or a data folder without `--with-ledger`, wherever it is
  given) are refused. The two entries have different names, so installing the rules tools says
  plainly when the ledger server is still in the file, and `--remove-ledger` takes it out.
- A model, not a person, now passes the facts, so the tools check what they are given: an arrival
  day (or a delivery day the letter states) after today is refused, an implausible one lowers
  confidence, and a result is always for the server's today — a caller's `today` far from it only
  adds that day's view (the benchmark's server ignores it), so a stale date never makes a live
  deadline look missed.
- The tools add no law of their own: whether a sender has deemed delivery at all (a company's letter
  counts from its arrival, but for a kind a public body may be filed as, or a period whose own words
  name an administrative act, never later than an authority's letter would count as delivered; an
  unknown sender's keeps the earliest plausible deemed delivery; and an *Einspruch*, *Widerspruch* or
  *Klage* makes a letter an authority's only with a notice naming an administrative route — a
  period's words alone never do), and which
  holidays of only part of a Land a date is counted back over, are the engine's rules, under its
  coverage gate, so a tool and the app give the same date and the same warnings for
  the same facts. What the tools add is about the caller, not the law: checks on the arrival day,
  a stated posting or delivery day without the letter's date, a letter dated after today and a stale
  `today` (a model passes these facts, not the person), and their warnings in the tools' own voice.
  Next to the ledger (`--with-ledger`), a letter in the ledger keeps its stored date.
- Ask's own server leaves the rules tools out (`--ledger-only`). Ask quotes the ledger's stored
  receipts and never computes a new date (SPEC § 21); with a calculator in reach, any date it
  echoed would also pass Ask's fact check.
- `ordnung mcp install` prints first and writes only with `--write`, under a written merge policy:
  only Ordnung's entry changes, the file is backed up, a file that is not a UTF-8 JSON object is
  refused untouched, an app's settings folder is never created.
- The benchmark measures the alternative this invites — an agent with Ordnung's engine as a tool
  instead of the fixed pipeline — as a fourth condition, on the same letters.

## Consequences
The engine reaches people where they already are, without their data. The fourth condition answers
"why a fixed pipeline instead of an agent with a calculator?" with data ([evals](../evals.md)): with
the tool the same model matched the pipeline's accuracy within noise (all 56 dates of the test split
right in its third recording there, each made after a review revised the tool interface — the last
one checked on the dev split first; the first scored 98.2 %, as does the fixed pipeline, the second
100 %; no dangerous-late date), so the pipeline's case rests on what an agent's answer lacks — a
quote checked against the page, a stored receipt per date, the same date for the same letter every
time, and no reliance on the model choosing when to call the tool, what to pass it and whether to
accept its safe date (it dated the printed dates of 9 of 53 letters without asking, and on the one
letter between it and the pipeline asked again without the letter's date to get a later one; an
earlier recording passed the day of the recording as "today" in 11 of 50 calls and then told people
live deadlines had passed, and the first once overrode the tool with a wrong date). Tool results and the tools' descriptions
are part of the benchmark recording, so an engine or description change does not re-score that
condition; it has to be recorded again (on the dev split first), and until then the CI gate, which
checks Ordnung, leaves it — and only it — out with a warning.
