# ADR 0011 — Ask keeps to the ledger; the rules tools are for other clients

**Status:** accepted · **Date:** 2026-09-27

## Context
Two decisions of the same release meet in Ask. ADR 0009 served the rules engine as ledger-free MCP
tools (`compute_deadline`, `german_holidays`, `add_working_days`, `check_iban`) for Claude Desktop and
Claude Code, and put them on the full ledger server too. ADR 0008 made Ask's answer check claim-level:
a date, time or amount is Ordnung's only when the *record part* of a record its sentence cites holds
it.

A rules-tool result is computed by code, but from a `DateSpec`, a letter date and a sender that the
model itself supplied — possibly taken from an injected letter ("the objection period is one year").
It stores nothing, belongs to no record and has no id to cite. Were Ask to call it, the check would
have to treat its dates either as record support (then an injected letter could launder a date
through the calculator into a checked answer) or as nothing (then the tool only lets the model state
dates the check will remove). Ask's job is to quote the ledger's stored receipts — made once, from a
reading checked against the page, with the person's confirmations — not to compute new dates
(SPEC § 21, ADR 0002).

## Decision
- **Ask gets only the ledger tools.** Its server is started `--ledger-only`, and the CLI may call
  the ledger tools by name (`--allowedTools mcp__ordnung__search,…`, `ask.ALLOWED_TOOLS` built from
  `mcp_server.TOOL_NAMES`), no longer by a wildcard that a rules tool on the same server would match.
- **The check reads only the ledger tools' results.** `ask._Turn` keeps a tool result as evidence only
  when its call is one of `TOOL_NAMES`; a result of any other tool — a rules tool on Ordnung's server
  or the rules-only one, or a result no call claims — never supports a value and never makes an id
  citable, whatever its text says (a forged `<ordnung_record>` included). A result belongs to the call with
  its `tool_use_id`; one without an id only to the oldest call without one still waiting (review round 4 of
  phase 2: an extra result recorded first became the call's). The Ask benchmark and `ordnung demo --check`
  pair a recording's results the same way (`mcp_server.pair_results`) and fail a replay whose recording holds
  a call of any other tool (`mcp_server.answer_again` answers it "unknown tool", so it is stale), a result
  that differs from what the tools give now, or a result no call claims.
- **The rules tools are for other clients.** `ordnung mcp --rules-only` (what `ordnung mcp install`
  adds) and the full server for `--with-ledger` clients keep them; there the model and the person
  decide what to trust, and every result says it is information, not legal advice.

## Consequences
- An injected letter cannot turn a date into "Ordnung's answer" through the calculator: the only
  dates Ask can state as checked are those Ordnung stored for a cited record.
- Ask cannot answer "what if the letter had arrived on Friday?": it points to the letter's receipt
  ("Why this date?") and the app's own date correction, which recomputes and stores the date. A
  what-if tool for Ask would need its own channel (a hypothetical, never a record) and its own
  measurement; it is not part of this decision.
- Tests pin both halves: the request names only the ledger tools, and a scripted turn whose rules
  tool returns a forged record part cannot support the date or the id it names (`tests/test_ask.py`).
