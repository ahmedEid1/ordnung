# ADR 0004 — Replay fixtures and content-derived IDs for a zero-token demo and CI

**Status:** accepted · **Date:** 2026-09-25

## Context
Recruiters and CI can't (and shouldn't) call a model. The demo must still exercise the real
pipeline, and recorded answers (e.g. an Idea that references a contract, an Ask answer that cites a
document) must stay valid when the demo database is rebuilt.

## Decision
- Every model call has a stable key: `purpose : prompt_version : model : sha256(canonical stable
  inputs)` — never wall-clock time or ingestion order. The same key addresses the local response
  cache and the replay fixture file.
- IDs are **content-derived** (`doc_` from the file hash, `itm_` from document + slot, `pty_` from
  the normalised name, …), so references in recorded outputs resolve after every rebuild.
- `ReplayBackend` is strict in CI (`ordnung demo --check` fails on any miss); the interactive demo
  turns a miss into a friendly "the demo uses recorded answers" message.
- The recorder refuses documents that are not in the sample manifest.

## Consequences
The whole product — including Ask streams and letter drafting — runs offline in the demo and in
Playwright e2e tests, with identical ledgers (apart from timestamps).
