# Privacy & data flow

Ordnung is a **local app**. It has no server, no account, no telemetry, and it never sees your
Claude credentials. But it is not "offline AI": when Claude reads a letter, the content of that
letter is sent to Anthropic **through your own Claude account**. This page explains exactly what
goes where.

## At a glance

| Data | Where it lives | Leaves your computer? |
|---|---|---|
| Original files (PDFs, photos) | `<data dir>/files/` | Never by Ordnung itself |
| Page images, thumbnails | `<data dir>/derived/` | Only as part of a *Read* call (see below) |
| Your ledger (letters, to-dos, contracts, ideas, drafts) | `<data dir>/ordnung.db` (SQLite) | Excerpts, when you use *Ask*, *Ideas review* or *Letters* |
| Profile (name, address, region) | `ordnung.db` | Name, language and region in prompts; your address is never sent |
| Model responses | `ordnung.db` (`llm_cache`) | — (they came from Anthropic) |
| Usage log (tokens, cost, which document) | `ordnung.db` (`llm_calls`) — **no prompt or response bodies** | Never |
| Fonts, UI, rules engine | bundled in the package | Never (no CDN, no web fonts) |

`<data dir>` defaults to your platform's user data folder (e.g. `~/.local/share/ordnung`,
`~/Library/Application Support/ordnung`, `%LOCALAPPDATA%\ordnung`) and can be changed with
`--data-dir` or `ORDNUNG_HOME`. On Linux and macOS the folder is private to your account (`0700`,
files `0600`), so other accounts on a shared computer can't read your letters or your ledger.

## What is sent to Claude, per feature

Every model call goes through the `claude` CLI you installed and signed in to. Anthropic's
handling of that data (retention, training use) is governed by **your** account type and settings —
see Anthropic's [consumer terms & privacy settings](https://www.anthropic.com/legal/privacy) or, if
you use an API key, the [commercial terms](https://www.anthropic.com/legal/commercial-terms).
Check your Claude privacy settings before processing sensitive documents.

| Feature | Sent to Claude | Model (default) |
|---|---|---|
| **Read a letter** — text PDFs | the page text of that document, today's date, your country and region, your name, and the names and kinds of organisations you already have (no numbers from other letters) | Sonnet |
| **Read a letter** — photos/scans | each page image (JPEG, ≤ 1600 px) for transcription, then the transcribed text as above | Sonnet |
| **Ideas review** (weekly; can be switched off in Settings) | a compact summary of open to-dos, contracts, recent letter summaries and warnings, the organisations involved, and your language, region and whether you are on a student visa | Sonnet |
| **Secretary's note** (optional) | today's agenda (titles, dates, amounts, organisations) and your first name | Haiku |
| **Ask** | your question and the last few messages of the conversation; the assistant then reads what it needs through Ordnung's **read-only** tools (search results, document excerpts) | Sonnet |
| **Letters** | the related letter's title, date, summary and reference numbers, the contract's name and customer number, the letter's fixed wording, the recipient's name (first line only) and your instructions | Sonnet |

You can inspect every call in **Settings → Privacy & AI usage**: purpose, which documents, how many
pages and bytes were sent, tokens, API-equivalent cost, and whether it came from cache.

## Your controls

- **Keep private (no AI)** — every upload asks first: switch it on and the document is never sent to
  Claude. It is stored, searchable by its text layer, and you can add dates by hand. A letter you
  delete while it still waits to be read is never sent either.
- **Delete means delete** — deleting a letter removes it for good: the original, page images,
  everything read from it, its to-dos and Ideas, its search-index entries, its entries in the
  activity log, quotes from it in contracts you keep, and the cached model responses of every call
  that carried it (a secretary's note or review built from several letters included). The usage log
  keeps only anonymous numbers, and deleted database rows are overwritten rather than left behind.
  Contracts and letters you drafted stay, without the link to it; your *Ask* conversations stay as
  they are. *Settings → Delete everything* wipes the whole database.
- **Models** — choose which Claude model handles each purpose.
- **Nothing is sent or paid automatically** — Ordnung drafts letters and suggests actions; you send
  them yourself.

## Hardening built into every model call

- The document is passed to the CLI over **stdin** (never the command line, so it doesn't appear in
  `ps`), and **no tools** are enabled while reading documents — the model can only answer.
- `--setting-sources ""` and `--strict-mcp-config` keep your own Claude Code hooks, settings and MCP
  servers out of Ordnung's calls; `--no-session-persistence` keeps them out of your Claude history.
- Document text is treated as **untrusted**: it is wrapped in `<untrusted_document>` markers, hidden
  (invisible) text is removed before it reaches the model, and every extracted fact is checked
  against the page before it is shown as "found in the letter".
- *Ask* can only call Ordnung's **read-only** tools; there are no write tools for a
  prompt-injected document to abuse.
- *Ask*'s tool results (search snippets, summaries, quotes, page texts) reach the model inside
  `<untrusted_document>` markers too. Text an HTML e-mail certainly hides from every reader (inline
  `display:none`, `visibility:hidden`, `opacity:0`, a font of at most 1 px, zero-height clipped or
  far off-screen boxes, text in its own inline background colour, simple hiding classes) is kept from
  the model like hidden text in PDFs. When that isn't certain (media queries, Outlook-only parts,
  responsive and dark-mode copies, stylesheet colours) the text stays visible and the other defences
  apply; see [ADR 0007](decisions/0007-short-written-policies-over-growing-heuristics.md).
- Uploads are checked before anything decodes them: PDFs whose compressed streams expand too far,
  photos with too many pixels and texts over 60 pages are refused, so a hostile file can't exhaust
  your computer's memory.
- The local web server listens on `127.0.0.1` by default (another `--host` prints a warning and still
  needs the token) and requires a session token, same-origin
  requests and a custom header for any change (CSRF/DNS-rebinding protection), with a strict
  Content-Security-Policy. `ordnung serve` opens your browser through a private local page, so the
  token never appears on a command line other accounts could see.

## Demo fixtures

The repository ships recorded model outputs for the fictional sample documents so the demo runs
without tokens. The recorder refuses to record anything that is not one of those sample files, and
CI checks that fixtures only reference sample documents — your own letters can never end up in a
fixture by accident.
