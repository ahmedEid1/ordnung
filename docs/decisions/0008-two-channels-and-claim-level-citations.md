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
   the own date or amount of a record the answer cites (and the check then adds that record's
   citation, so its chip shows whose value it is). A cited record's own flagged, unverified amount
   and a value the person typed stay, in quotation marks, as unconfirmed. Every other value is left
   out: one only a letter's text holds is shown as "[date only in the letter]" / "[amount only in
   the letter]" — whatever the sentence's wording (since the fourth review round no phrase such as
   "the letter says" makes a letter's value shown) — and any other as "[date left out]" / "[amount
   left out]"; a sentence that keeps no value is removed unless all it leaves out is a letter's (a
   warning about injected text), and a left-out value is never shown. When values were left out, the
   note gives the own dates or amounts of the records concerned, each with what it is. A § must be
   in the rules catalog or a record part; any other — also one only a letter names — removes its
   whole sentence. What counts as a value fails closed: any run of digit groups joined by single
   marks that holds a day, month and year is read, and one that is no calendar date is
   *unreadable* and never supported. Overview totals support only a sentence without a citation of
   its own; a category's fixed costs belong to the contracts of that category.
3. **Only the check writes its note, and nobody reads an unchecked word.** The note (what was left
   out, quoted or cited, and why) travels in its own field of the `done` event and the stored
   thread, under its label in the answer's language; the UI shows only that field, and a model
   sentence that starts like the note is left out (the note says so). The model's words are never
   streamed: the UI and the CLI show the tool trace and "writing …" until the check is done, and
   nothing of an answer that stops, fails or cannot be checked (it fails closed, with an error).
   An answer the check did not change says "Checked against your records".
4. **Citations need a record part.** A cited id must appear in the record part of a tool result of
   the same turn and exist; an id that only a letter's text names is stripped.
5. **The prompt says so** (`ask_system` version 4 — see the fourth round below for the one line it
   no longer matches), and **a benchmark measures it**
   (`python -m evals.ask`, [docs/evals-ask.md](../evals-ask.md)): questions with gold answers from
   the sample life's truth, injected letters, attack success with and without the check, and a CI
   gate on the replay. Replays (the benchmark's and `ordnung demo --check`) answer every recorded
   tool call again with the current tools and fail when a result differs, so a change to the two
   channels cannot pass on recorded evidence.

## Consequences
- The reviewer's example is caught: the injected date is shown as "[date only in the letter]",
  however the sentence is worded, and the note gives Ordnung's own deadline. Injected text can no
  longer make a citation valid.
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
- Revised after the fourth review round (recorded in [evals-ask](../evals-ask.md)). Reviewers
  showed that the phrase list decided too much and kept growing, against ADR 0007: a letter's
  correct date in a sentence worded "The price-increase letter says …" or "Im Schreiben steht …"
  removed the only answer (and "that date" then pointed at another date), while each round added
  phrases, clause breaks and contrasts. And they found more gaps: an ISO date-time
  (`2027-12-31T23:59`) was not read although the web formats it like Ordnung's own dates; empty
  links, `12/2027`, `31_12_2027`, `31|12|2027` and look-alike letters (`2O27`) passed; "Checked by
  Ordnung's records: …" was deleted as a forged note while "✓ Checked by Ordnung: …" was kept; a
  sentence without a citation could give another cited record's date to the wrong record with no
  chip; a to-do's time (the extraction model's reading) sat in the record and backed an injected
  date; the note called unrelated record dates "Ordnung's record for what is quoted"; the UI and
  the CLI showed the unchecked draft — injected values included — while it streamed; and
  `if_not_cancelled` told Ask a fixed-term job or flat let needs no cancellation. The policy shrank
  to its closed core: the phrase list, clause breaks and contrasts are gone, and a letter's value is
  marked as the letter's everywhere; value forms fail closed (any date-shaped run of digit groups);
  the forged-note rule matches only the note's own form; an uncited sentence's borrowed value gets
  its record's citation; a to-do's time is record only as a clock time; the note's record values are
  worded neutrally; the words are never streamed; and a job or flat let's record says notice may
  still be needed (§ 15 Abs. 4 TzBfG, § 575 Abs. 1 BGB). The prompt did not change (version 4), so
  its line inviting "the letter says …" now yields "[date only in the letter]" instead of a quote;
  aligning it (and the form of address in German answers, and `do_not_pay`'s wording, which the tool
  description already hedges) is left for the next prompt version, because a prompt change means
  recording every Ask answer again. The recordings whose tool results changed were recorded again.
- Why this is a written policy in the sense of ADR 0007, although its value-form lists grew over four
  review rounds: what decides whether a value is *Ordnung's* is small and closed — it must be in the
  code-written record part of a record the answer cites; everything else is placeholdered, quoted as
  unconfirmed (a flagged amount, the person's words) or removed, whatever the wording. The form
  lists decide only what counts as a value at all, and since the fourth round they fail closed for
  digit forms: any run of digit groups joined by marks that holds a day, a month and a year is read,
  and one that is no date is never supported. What remains unread is named in the policy's limits
  (dates in words, bare years, calendar weeks, digit groups apart only by spaces other than day
  month year, other scripts). The machine-readable quotes considered earlier (`[quote:doc_…]“…”`)
  would let a correct letter value be shown as a quote again; they need a prompt change, UI support
  and a new measurement, and are the next step if the cost of the closed policy — correct letter
  values shown only as placeholders — proves too high in use.
- Accepted limits, documented in the policy: support is literal (a value in a cited record supports
  a sentence that says something else about it), claims without a date, amount or § ("there is no
  deadline"), dates in words, bare years and rates are not read, a sentence whose value was left out
  keeps its other words ("moved to [date only in the letter]" — also when it repeats a letter's claim
  as if it were true), and a correct value or § only a letter holds is never shown. The benchmark's
  `no_deadline` and `cite_other` attacks measure exactly these gaps.
- Any change to the MCP output, the Ask prompt or the ledger fingerprint invalidates recorded Ask
  answers (demo and benchmark), which must be recorded again.
