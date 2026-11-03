# Decisions

Each record says why Ordnung is built one way and not another: the problem, the decision and what it costs. A
later change is dated in the record it changes, or made by a new record that amends it. A new record takes the
next number and a row here; `tests/test_docs_index.py` checks that every record is listed with its own title and
status.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-claude-cli-as-the-model-runtime.md) | Use the user's own `claude` CLI as the model runtime | accepted · 2026-09-25 |
| [0002](0002-llm-reads-code-computes.md) | The LLM reads, deterministic code computes dates | accepted · 2026-09-25 |
| [0003](0003-grounding-levels.md) | Four grounding levels instead of "verified" | accepted · 2026-09-25 |
| [0004](0004-replay-fixtures-and-deterministic-ids.md) | Replay fixtures and content-derived IDs for a zero-token demo and CI | accepted · 2026-09-25 |
| [0005](0005-sqlite-fts-local-first.md) | SQLite (WAL + FTS5 + trigram), no vector database | accepted · 2026-09-25 |
| [0006](0006-read-only-agent-and-humble-automation.md) | A read-only agent and "humble automation" | accepted · 2026-09-25, superseded in part by [0014](0014-proof-files-are-deleted-for-good.md) |
| [0007](0007-short-written-policies-over-growing-heuristics.md) | Short written policies instead of growing heuristics | accepted · 2026-09-26, updated 2026-10-07 |
| [0008](0008-two-channels-and-claim-level-citations.md) | Two channels for Ask and claim-level citations | accepted · 2026-09-26 |
| [0009](0009-rules-engine-as-mcp-tools.md) | The rules engine as MCP tools, rules-only by default | accepted · 2026-09-26 |
| [0010](0010-high-stakes-kinds-assigned-by-code.md) | High-stakes letters: kinds assigned by code from the reading | accepted · 2026-09-26, updated 2026-09-29 |
| [0011](0011-ask-keeps-to-the-ledger.md) | Ask keeps to the ledger; the rules tools are for other clients | accepted · 2026-09-27 |
| [0012](0012-girocode-only-for-grounded-transfers.md) | A GiroCode only for grounded transfers, decided by a written policy | accepted · 2026-09-27 |
| [0013](0013-backups-and-reminders-outside-the-browser.md) | Backups and reminders that work while Ordnung is closed | accepted · 2026-09-27, updated 2026-10-08, 2026-10-09 and 2026-10-10 |
| [0014](0014-proof-files-are-deleted-for-good.md) | Proof files are deleted for good, after a confirmation that names them | accepted · 2026-09-27 |
| [0015](0015-incomplete-readings-get-a-check-written-by-code.md) | Incomplete readings get a check written by code | accepted · 2026-10-01, updated 2026-10-07 |
| [0016](0016-an-incomplete-reading-is-asked-for-once-more.md) | An incomplete reading is asked for once more | accepted · 2026-10-02 |
| [0017](0017-phone-access-over-the-home-network.md) | Phone access over the home network | accepted · 2026-10-07 |
| [0018](0018-hand-off-sync-through-a-folder-you-already-sync.md) | Hand-off sync through a folder you already sync | accepted · 2026-10-07 |
| [0019](0019-a-sender-s-land-is-suggested-never-set.md) | A sender's Land is suggested, never set | accepted · 2026-10-08 |
| [0020](0020-a-scanner-s-text-is-for-finding-not-reading.md) | A scanner's text is for finding, not reading | accepted · 2026-10-09 |
| [0021](0021-a-move-is-said-never-guessed.md) | A move is said, never guessed | accepted · 2026-10-09 |
| [0022](0022-compressed-answers-and-a-lighter-letter-list.md) | Compressed answers and a lighter letter list | accepted · 2026-10-11 |
| [0023](0023-letters-for-your-household-are-suggested-never-filed.md) | Letters for your household are suggested, never filed | accepted · 2026-10-27, amended by [0025](0025-ask-and-the-ideas-say-whose-it-is.md) |
| [0024](0024-words-ordnung-reads-in-a-picture-are-for-finding-not-reading.md) | Words Ordnung reads in a picture are for finding, not reading | accepted · 2026-10-28, amended in 0.4.0 |
| [0025](0025-ask-and-the-ideas-say-whose-it-is.md) | Ask and the Ideas say whose it is | accepted · 2026-10-29, amends [0023](0023-letters-for-your-household-are-suggested-never-filed.md) |
