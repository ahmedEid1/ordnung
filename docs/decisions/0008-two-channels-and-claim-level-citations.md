# ADR 0008 — Two channels for Ask and claim-level citations

**Status:** accepted · **Date:** 2026-09-26

## Context
*Ask* is an agent: the `claude` CLI with only Ordnung's read-only MCP tools. After an answer
streams, code checked it with a *bag of facts*: every date and amount of the answer had to appear
somewhere in this turn's tool results, and every citation had to name a record that exists and
appears in those results.

A reviewer showed, by running those functions, that the bag contains every date and amount of
*any* tool result — including a letter's page text. "The objection deadline was extended to
31.12.2027 [doc:doc_abc]" passed unchanged when that date appeared only in an injected sentence of
the letter, and a citation only had to exist, not support its sentence. An id that a letter's text
mentioned could be cited too. There was also no measurement of Ask at all.

## Decision
1. **Two channels in every tool result** (`assistant/channels.py`, `assistant/mcp_server.py`).
   `<ordnung_record>` holds what Ordnung's code computed, what the person entered or confirmed, and
   what the pipeline filed with verified evidence: ids and links, kinds, statuses and flags; to-do
   due dates, times and send-by dates; the rules engine's contract dates; letter dates; amounts and
   contract terms whose evidence was found in the text layer with every digit matching (ADR 0003) or
   that the person gave; totals Ordnung adds up; text written by code (date receipts, rules, contract
   notes). `<untrusted_document>` holds everything that comes from a letter's words, keyed by record
   id: titles, summaries, names, key facts, quotes, warnings, payment details, page text — and
   amounts or terms read by AI from a photo or not found on the page, which the record flags
   (`amount_unverified`, `terms_unverified`, with a code-written note saying why). Both parts escape
   `<` and `>`, so no text can open or close a tag.
2. **Claim-level support, as a written policy** (`assistant/support.py`, ADR 0007 style). The
   answer is read as the person will see it (Markdown, escapes and invisible characters dropped).
   Each date or amount must be in the *record part* of a record its sentence cites (a letter's part
   includes its to-dos; a contract's includes its letter; a person's includes their to-dos; a
   sentence without citations takes its line's, a list item its lead line's). Today's date and
   Ordnung's overview totals need no citation. A value that only letter text holds may stay only as
   a quote — when the value's own clause names the letter ("the letter says", or a listed
   equivalent) and the sentence cites the record whose letter text holds it, or when it is a cited
   record's own flagged, unverified amount; a value the person typed stays only as their words in a
   sentence that cites nothing. Quotes are shown in quotation marks. Every other value is left out:
   replaced by a placeholder when its sentence keeps a record value, else the sentence is removed. A
   § must be in the rules catalog or a record part; one only a letter names is quoted.
3. **Only the check writes its note.** The note (what was left out or quoted, and Ordnung's own date
   or amount when a letter's value is quoted alone) travels in its own field of the `done` event
   and the stored thread; the UI shows only that field, and a model sentence that starts like the
   note is dropped. An answer that stops before the check is shown as unchecked.
4. **Citations need a record part.** A cited id must appear in the record part of a tool result of
   the same turn and exist; an id that only a letter's text names is stripped.
5. **The prompt says so** (`ask_system` version 3), and **a benchmark measures it**
   (`python -m evals.ask`, [docs/evals-ask.md](../evals-ask.md)): questions with gold answers from
   the sample life's truth, injected letters, attack success with and without the check, and a CI
   gate on the replay.

## Consequences
- The reviewer's example is removed; the same date framed as "the letter says …" is shown as a
  quoted, unconfirmed value. Injected text can no longer make a citation valid.
- The check is deterministic and linear in the answer and tool-result size; the benchmark re-runs it
  over recorded answers, so changes to it are measured without new model calls.
- Cost: correct values in sentences that cite the wrong record, or none, are left out too; the note
  makes that visible and the benchmark counts it ("removed with true values only"). A sentence
  that keeps a record value only loses the unsupported value, so a record's date is never lost
  because of another number next to it.
- Revised after the first review round (recorded in [evals-ask](../evals-ask.md)): the first check
  missed values hidden by Markdown or odd date forms, cut sentences at abbreviations, read room
  numbers and clock times as amounts, accepted a letter phrase anywhere in a sentence, let a date the
  person typed pass as Ordnung's, accepted laws that only a letter named, and let the model write
  the note itself. Its "unsupported claims in final answers" metric re-ran the check on its own
  output; the benchmark now measures that with its own parser.
- Accepted limits, documented in the policy: support is literal (a value in a cited record supports
  a sentence that says something else about it), claims without a date or amount ("there is no
  deadline") are not read, a sentence whose value was left out keeps its other words ("moved to
  [date left out]"), and a quote is recognised only by the listed phrases. The benchmark's
  `no_deadline` and `cite_other` attacks measure exactly these gaps.
- Any change to the MCP output, the Ask prompt or the ledger fingerprint invalidates recorded Ask
  answers (demo and benchmark), which must be recorded again.
