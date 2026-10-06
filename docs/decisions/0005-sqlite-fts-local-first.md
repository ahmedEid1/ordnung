# ADR 0005 — SQLite (WAL + FTS5 + trigram), no vector database

**Status:** accepted · **Date:** 2026-09-25

## Context
A personal ledger has thousands of rows, not millions. The only AI access is the Claude CLI, which
offers no embeddings endpoint, and the product must install with `pip`.

## Decision
One SQLite file (WAL, explicit `BEGIN IMMEDIATE` transactions, numbered migrations: a
`schema_migrations` table records which ran, and `PRAGMA user_version` holds the highest, so a newer
database is refused; `db/migrate.py`, SPEC § 5). Search = FTS5 (`unicode61 remove_diacritics 2`) for words + an FTS5
**trigram** index for substrings inside German compounds ("steuerbescheid" in
"Einkommensteuerbescheid"). Retrieval for *Ask* is **agentic**: the model calls Ordnung's read-only
MCP tools (`search`, `get_document`, `list_items`, `explain_date`, …) instead of relying on a vector
index.

## Consequences
Zero infrastructure, one file to back up, exact and explainable retrieval with citations that are
validated against the tool results of the same turn.
