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
   `<` and `>`, so no text can open or close a tag. A tool keeps each result within a size budget
   by leaving out rows (and says how many), and the check reads the whole result the model read.
2. **Claim-level support, as a written policy** (`assistant/support.py`, ADR 0007 style). The
   answer is read as the person will see it (Markdown, escapes and invisible characters dropped).
   Each date or amount must be in the *record part* of a record its sentence cites (a letter's part
   includes its to-dos; a contract's includes its letter; a person's includes their to-dos; a
   sentence without citations takes its line's, a list item its lead line's). Today's date and
   Ordnung's overview totals need no citation, and a sentence without citations of its own may state
   the own date or amount of any record the answer cites. A value that only letter text holds may
   stay only as a quote — when a phrase naming the letter ("the letter says", or a listed
   equivalent) stands before it in its own clause, not negated, and the sentence cites the record
   whose letter text holds it (citing nothing: a letter read in the turn), or when it is a cited
   record's own flagged, unverified amount; a value the person typed stays only as their words.
   Quotes are shown in quotation marks, and the note gives Ordnung's own date or amount of the
   records a quote belongs to. Every other value is left out: replaced by a placeholder when its
   sentence keeps a value, else the sentence is removed; a left-out value is never shown. A § must
   be in the rules catalog or a record part; one only a letter names is quoted when its clause names
   the letter as its source (like a letter's date), and any other § removes its whole sentence.
   Overview totals support only a sentence without a citation of its own; a category's fixed costs belong to
   the contracts of that category.
3. **Only the check writes its note.** The note (what was left out or quoted, and Ordnung's own date
   or amount when a letter's value is quoted alone) travels in its own field of the `done` event
   and the stored thread; the UI shows only that field, and a model sentence that starts like the
   note is dropped. An answer that stops before the check is shown as unchecked, and one the check
   cannot read ends with an error, never as a checked answer (it fails closed); the CLI prints the
   streamed text dim under "Draft — not yet checked".
4. **Citations need a record part.** A cited id must appear in the record part of a tool result of
   the same turn and exist; an id that only a letter's text names is stripped.
5. **The prompt says so** (`ask_system` version 4), and **a benchmark measures it**
   (`python -m evals.ask`, [docs/evals-ask.md](../evals-ask.md)): questions with gold answers from
   the sample life's truth, injected letters, attack success with and without the check, and a CI
   gate on the replay. Replays (the benchmark's and `ordnung demo --check`) answer every recorded
   tool call again with the current tools and fail when a result differs, so a change to the two
   channels cannot pass on recorded evidence.

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
- Revised after the second review round (recorded in [evals-ask](../evals-ask.md)): the check
  skipped one of two overlapping edits (a date and an amount sharing a currency), so a value the
  note called left out stayed readable — it now never drops an edit and removes a sentence rather
  than show a left-out value; it deleted the model's warnings about injected text (they repeat the
  value to flag it) — "the letter's text contains a line claiming …" now names the letter as the
  source and keeps the warning with the value quoted; a letter phrase framed values before it,
  negated phrases, and values after ", and" or "while"; a date the person typed was lost in a
  sentence that cites a record, and an uncited "yes, that's right: … 31.12.2027" kept it with no
  record value next to it — it is now quoted whatever the sentence cites, and the note gives
  Ordnung's own value; an unknown § removed a record's date; straight quotes were doubled; spaced,
  Roman-month and default-ignorable forms and currency words were not read; one long sentence took
  quadratic time; the note was English under German answers; and the CLI backend cut every tool
  result at 20,000 characters for the check (not for the model), so a longer result lost its whole
  record part. The tools now keep results within a budget by rows, `money_summary` lists undated
  payments and demands not to pay, and the prompt went to version 4, so all Ask answers were
  recorded again.
- Revised after the third review round (recorded in [evals-ask](../evals-ask.md)): the
  `money_summary` totals supported any sentence whatever it cited (a category total is often one
  contract's cost, so "you owe the library 640.00 € [item:…]" passed); a month without a day, one
  decimal amounts, `31-Dec-2027`, a date split by a soft line break and money written as "from
  18.36 to 21.50" were not read; a § that only a letter names was kept, quoted, in a sentence that
  cited the letter without naming it as the source — an injected legal basis for "your deadline no
  longer applies"; catalog citations with subsection lists (`§ 622 Abs. 1, 3, 6 BGB`) lost their
  law, so a correct "§ 56 TKG" was removed; rates were read as money and phone numbers as dates; a
  malformed number in a letter (`12,34..56`) made the check raise, which cut the answer stream;
  link syntax took quadratic time; a cancellation letter's end date sat in the record part;
  `if_not_cancelled` said a fixed-term employment contract continues indefinitely; replays could not
  notice a change to the tools' output. All are fixed; the stale recordings were recorded again with
  the same prompt (version 4).
- Why this is still a short written policy in the sense of ADR 0007, although its phrase and form
  lists grew in three review rounds: the part that decides whether a value is *Ordnung's* is small
  and closed — it must be in the code-written record part of a record the answer cites. The phrase
  list only chooses between two safe outcomes for a value a letter holds (a quote, with Ordnung's
  own value in the note, or left out). The form lists are different: they decide what counts as a
  value at all, and a form they do not read is not checked — the value passes unmarked. The first
  version of this ADR said a gap could never let a letter's value through as Ordnung's statement;
  that was true only for the phrase list, and the forms reviewers found unread are now read, with
  the remaining ones named in the policy's limits. Two smaller policies were considered: always leaving out letter-only values (loses
  correct answers the record does not hold, such as a refund read from a photo, and the warnings
  about injected text), and machine-readable quotes from the model (`[quote:doc_…]“…”`, rendered as
  quotes) — which would replace the phrase list by a contract with the model and needs a prompt
  change, UI support and a new measurement. The latter is the next step if review keeps finding
  wordings. **That condition is met:** the third review round again found list gaps (value forms,
  law lists, rates, phone numbers). The lists were extended once more, and where a gap was not a
  safe outcome — an unvouched § kept in its sentence — the fallback became removing the sentence.
  The next change to Ask's prompt replaces rule 4a's phrase list by machine-readable quotes
  (`[quote:doc_…]“…”`, rendered as quotes; anything unmarked is Ordnung's claim and must be in the
  record), measured by this benchmark; until then a gap in the value forms can let a letter's value
  through unmarked, which the benchmark's attacks keep probing.
- Accepted limits, documented in the policy: support is literal (a value in a cited record supports
  a sentence that says something else about it), claims without a date, amount or § ("there is no
  deadline"), dates in words, bare years and rates are not read, a sentence whose value was left out keeps its other words ("moved to
  [date left out]"), and a quote is recognised only by the listed phrases. The benchmark's
  `no_deadline` and `cite_other` attacks measure exactly these gaps.
- Any change to the MCP output, the Ask prompt or the ledger fingerprint invalidates recorded Ask
  answers (demo and benchmark), which must be recorded again.
