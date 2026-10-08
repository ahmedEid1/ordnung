# ADR 0001 — Use the user's own `claude` CLI as the model runtime

**Status:** accepted · **Date:** 2026-09-25

## Context
Ordnung must run entirely on the user's machine with **their Claude subscription as the only AI
access** — no hosted backend, no API key handling, no credentials in our code. The options were:
(a) the Anthropic API SDK with an API key, (b) the Claude Agent SDK, (c) shelling out to the
installed Claude Code CLI in headless mode (`claude -p`).

## Decision
Drive the **unmodified, locally installed `claude` CLI** through a small backend protocol
(`LLMBackend`) with one production implementation (`ClaudeCLIBackend`). Requests are written to the
CLI's **stdin** as a single `stream-json` user message (text + base64 image/PDF blocks); responses
are read from `stream-json` stdout; structured outputs are enforced with `--json-schema`.

## Consequences
- Works with a Pro/Max subscription *or* an API key — whatever the user's CLI is signed in with.
  Ordnung never sees or stores credentials (see Anthropic's
  [legal & compliance notes](https://code.claude.com/docs/en/legal-and-compliance): an end user may
  sign in to the unmodified Claude Code binary with their own subscription).
- Needs Claude Code 2.1.0 or newer (`MIN_CLAUDE_VERSION` in `llm/claude_cli.py`), whose flags every call
  passes. `ordnung doctor`, the app's zero-token status check and the backend before its first call all
  compare `claude --version` with it: an older CLI counts as not ready, so letters wait (*Waiting for
  Claude*) with the update command (`claude update`) instead of failing on a flag it rejects.
- Least privilege is expressed in flags: `--tools ""` for document reading, only Ordnung's read-only
  MCP tools for Ask, `--setting-sources ""`, `--strict-mcp-config`, `--no-session-persistence`, and
  never `--dangerously-skip-permissions` or `--bare` (which disables subscription login).
- The protocol keeps the choice reversible: a `ReplayBackend` (demo/CI) and a `FakeBackend` (tests)
  implement the same interface; an API-SDK backend would be ~100 lines.
- Costs: process start-up per call (~1–2 s) and dependence on CLI output formats — mitigated by a
  fake-CLI test harness and error classification from the result object, not exit codes.
