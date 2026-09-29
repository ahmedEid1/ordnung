# ADR 0008 — Two channels for Ask and claim-level citations

**Status:** accepted · **Date:** 2026-09-26 · revised after seven review rounds (their findings, and what
each round measured, are in [evals-ask](../evals-ask.md))

## Context
*Ask* is an agent: the `claude` CLI with only Ordnung's read-only MCP tools. After an answer streamed,
code checked it with a *bag of facts*: every date and amount of the answer had to appear somewhere in
this turn's tool results, and every citation had to name a record that exists and appears in them.

A reviewer showed that the bag held every date and amount of *any* tool result — a letter's page text
included. "The objection deadline was extended to 31.12.2027 [doc:doc_abc]" passed unchanged when that
date appeared only in an injected sentence of the letter, a citation only had to exist, not support its
sentence, and an id a letter's text mentioned could be cited. Nothing measured Ask at all.

## Decision
1. **Two channels in every tool result** (`assistant/channels.py`, `assistant/mcp_server.py`).
   `<ordnung_record>` holds what Ordnung's code computed, what the person entered or confirmed, and
   what the pipeline filed with verified evidence (ADR 0003): ids and links, kinds, statuses and flags,
   to-do dates and clock times, the rules engine's contract dates, letter dates, verified or
   person-given amounts and terms, totals of verified amounts, and text written by code.
   `<untrusted_document>` holds every word from a letter, keyed by record id — and amounts or terms
   read by AI from a photo or not found on the page, which the record flags (`amount_unverified`,
   `terms_unverified`). Both escape `<` and `>`. A tool keeps each result within a size budget by
   leaving out rows, and the check reads the whole result the model read.
2. **Claim-level support, as a written policy** (`assistant/support.py`, ADR 0007). Its closed core:
   a date, time or amount of the answer is *Ordnung's* only when it is in the code-written record part
   of a record its sentence cites (or inherits from its line or its list's lead line) — today's date, too, is
   no exception there: a cited record must hold it, in a sentence without a citation too when the answer
   cites any record, so "the deadline passed today [item:…]" and "the period ended today" in a paragraph of
   its own are left out and the note gives the record's own date; only in an answer that cites no record does
   today stand alone, and the note then says it is today's date and gives the records' own dates, so an
   unqualified "checked" never rests on today (review round 4 of phase 2; the prompt says so since version
   6); a year that stands in no other value is
   the cited record's only when it holds a date in that year; a sentence without
   citations of its own may state a value of a record the answer cites, and the check then adds that
   record's citation (never a scam record's, never several). A cited record's flagged amount and the
   person's own words are shown in quotation marks as unconfirmed. Everything else is left out, whatever
   the wording: "[date only in the letter]" when the letter text of a cited record holds it, "[date left
   out]" otherwise; a sentence left with no value is removed unless all it left out is its letter's (a
   warning about injected text), and a § — or a law cited in words ("section 999", "Paragraf 999 AO") —
   that neither the rules nor a record vouch for removes its sentence. What counts as a value fails
   closed: any run of digit groups joined by marks that holds a day, a month and a year is read, one that
   is no calendar date is never supported, and a day, one word and a year whose word is no month the
   check knows (``31 décembre 2027`` — Ask answers in the question's language, the check knows English
   and German month names) is unreadable, never supported; so is a clock time moved by words ("halb 10
   Uhr") and a day in words before a month. A slash date that reads two ways (`03/11/2027`) is Ordnung's
   only when the record holds both readings, and an amount written with a currency only when the record's
   amount is in that currency — any currency: a sign of Unicode's category Sc, an ISO code or a currency's name
   in any offered language; cents after its currency make an amount unreadable, and so does a part of the day
   or a time zone near a clock time that the check can't place. The form lists decide only what counts as a value; what they leave unread
   is named in the policy's limits. A kept sentence that states or cites a payment the app says to decide
   on first (a rent increase's new rent, a late statement's back-payment) — through any record linked to it
   — or a record with scam signs gets the app's own warning in the note, first (ADR 0006); every tool that
   returns such a record (`list_items`, `timeline`, `explain_date`, `money_summary`, `get_document`,
   `get_party`, and `search` for a letter) carries its `scam_warning` and `payment_note`, so the notes follow
   the record whichever tool the model used.
3. **Only the check writes its note, and nobody reads an unchecked word.** The note travels in its own
   field of the `done` event and the stored thread, under its label in the answer's language, and says
   only what is true of every case it covers, in words a non-expert reads ("isn't among the dates and
   amounts Ordnung saved for the linked letter, to-do or contract").
   The answer's words are never streamed: the UI and the CLI show the tool trace — with every word of a
   value the check reads in the model's own words shown as "…"; a record's title, as the app shows it on
   every list and letter page — until the check is done, and nothing of an answer that fails or
   cannot be checked (it fails closed). An unchanged answer says "Dates and amounts checked against your
   records" (in German "Daten und Beträge mit Ihren Unterlagen abgeglichen") — it says what was checked:
   claims without a value ("there is no deadline") never are; an answer stored before this check has no
   label and is never shown as checked. The model may not write the label: a sentence starting like it is
   left out, read with look-alike letters as Latin ones and across a soft line break.
4. **Citations need a record part.** A cited id must appear in the record part of a tool result of the
   same turn and exist; an id only a letter's text names is stripped.
5. **The prompt says what the check does** (`ask_system` version 6): a value only a letter holds is not
   stated, whatever words frame it; only a cited record's flagged amount and the person's own words stay
   as quotes; today's date is checked like any other; each sentence and list item cites its own record,
   the record's legal statements keep their hedges, and a `do_not_pay` demand is not to be paid until
   checked with the sender (ADR 0006). **A
   benchmark measures it** (`python -m evals.ask`): questions with gold answers from the sample life's
   truth, injected letters, attack success with and without the check, and a CI gate on the replay.
   Replays (the benchmark's and `ordnung demo --check`) answer every recorded tool call again with the
   current tools and fail when a result differs.

## Consequences
- The reviewer's example is caught: the injected date is shown as "[date only in the letter]", and the
  note gives Ordnung's own deadline. Injected text can no longer make a citation valid.
- The check is deterministic and linear in the answer and tool-result size (a run of any character is
  read once); the benchmark re-runs it over recorded answers, so a change to it is measured without new
  model calls, and a change to the tools or the prompt fails the replay until the answers are recorded
  again.
- Cost: a correct value in a sentence that cites the wrong record, or only a letter, is left out; the
  note makes that visible and the benchmark counts it. A correct value or § only a letter holds is never
  shown. Machine-readable quotes (`[quote:doc_…]“…”`) would let a letter's value be shown as a quote;
  they need a prompt change, UI support and a new measurement, and are the next step if this cost proves
  too high in use.
- Accepted limits, documented in the policy: support is literal (a value in a cited record supports a
  sentence that says something else about it, and a left-out value is never shown *within its
  sentence* — another uncited sentence may state the same date when a cited record holds it anywhere in
  its record part); claims without a value or § ("there is no deadline"), dates in words without a named
  month, bare years, rates and times without a unit are not read; a sentence whose value was left out
  keeps its other words. The benchmark's `no_deadline` and `cite_other` attacks measure these gaps.
  Failing closed has a cost too: a correct date written with another language's month name is left
  out like a wrong one, and the note and placeholders are English or German.
- **The value reader is a list of forms, against ADR 0007 — recorded as a follow-up.** Each review round
  found forms it did not read, and each fix added forms (`support.py` grew from about 500 to about
  3,700 lines — 2,560 at final review 3). The core of the policy is closed (rule 3: a value is Ordnung's only when a cited record holds
  it); the reader is not, because "what counts as a value" has no closed definition in free text. Final
  review 3 turned the reader toward failing closed — an unknown form that looks like a date or time is
  unreadable, not unread — but the list of forms remains. Review round 1 of phase 2 found more unread
  forms in the other offered languages (marked dates such as `31-dic-2027`, month and year in those
  languages, other calendars, `31/12`, scales glued to a currency, other currencies, hour words); they
  were added the same way, and the Ask page's generated numbers are now checked in CI (`--check-docs`).
  Review round 2 of phase 2 found more again (values glued to Chinese signs, colon look-alikes, parts of
  the day, cent and scale words, months with "of", US month/day pairs, locative month names, other
  currencies' symbols); they were added the same way. Review round 3 of phase 2 found more (currency names of
  11 of the 14 answer languages, euros followed by cents as a second number, parts of the day after another
  language's hour word or in brackets, year ends, spaced month and year, doubled marks, list numbers). This
  time the fixes are closed rules rather than forms: any currency sign, code or name makes a number an amount;
  anything after a currency that can be cents makes it unreadable; every clock time is read with a part of the
  day or time zone in its clause; digit groups joined to a year by any marks are unreadable; and in a sentence
  that cites a record any year no cited record has a date in is left out. The last one costs correct answers a
  year that names a letter's period ("Income Tax Assessment 2025"): on the benchmark 7 of 173 sentences kept
  a placeholder for such a year and 2 were removed, with answer accuracy unchanged. The smaller policy ADR
  0007 asks for is the next step: the prompt requires Ordnung's own formats ("Wed 21 Oct 2026", "640.00 €", "10:30"), and
  every other digit run in a sentence that could be a date, time or amount is left out. It needs a
  prompt version, a re-recording and a new measurement of what it costs correct answers, so it is not
  part of this decision.
- **Release blocker outside Ask — resolved:** the contract page and the rules catalog's `fixed_term` rule
  said a fixed-term flat let "ends by itself" (§ 575 Abs. 1 S. 2 BGB), and the engine's summary said an
  active one past its end date "ended". Since review round 1 of phase 2 the engine and the catalog say what
  Ask's record says: notice may still be needed without a written reason, and an active flat let or job
  past its end date may still run (§ 575 Abs. 1 S. 2 and § 545 BGB, § 15 Abs. 6 TzBfG). Ask's record keeps
  its own text (the courts' reading of the end date as a waiver of notice, BGH VIII ZR 388/12) and its note
  on the rule for a flat let.
