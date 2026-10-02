# ADR 0016 — An incomplete reading is asked for once more

**Status:** accepted · **Date:** 2026-10-02

## Context
ADR 0015 added a check, written in code, for readings that come back incomplete: almost blank, or without
the objection deadline the letter's own instructions on how to object (*Rechtsbehelfsbelehrung*) state. It
files one low "Please check" to-do and leaves the reading as the model gave it. It deliberately asked no
model again: a re-ask needs a new prompt, a key marker and a live recording, and its answer would still need
the check behind it.

The motivating reading — `holdout2-adversarial-injection_visible-1`, a decision with a visible paragraph
addressed to AI assistants — came back with only the schema's four required fields. The check recovers the
objection deadline, but the letter keeps no sender, no letter date and no remedy, and the to-do is always
"Please check". On the same letter the three other benchmark conditions found the objection deadline in the
same text, and 8 of 9 visible injections in the benchmark were read in full: asking once more is likely to
give the full reading.

A first version accepted the second answer when its gap was smaller and its quotes were found as well. Five
reviews showed that this could leave a letter worse off than the check alone: a dated to-do dropped or moved
later, an objection date up to a week later (or any date, where the check can't date it), a gap "closed" by
reading the sender as a firm, a letter date taken from another date on the page, an invented sender, and a
timeout on the optional call failing a usable reading.

## Principle
**The re-ask never leaves the letter worse off than the first reading with the code's check behind it (the
baseline).** Every rejection path yields exactly the baseline: the first reading is kept and the check files
its to-do as it would without the re-ask.

## Decision
After a valid parse, `ingest/extract.py` computes the reading check's own gap on the same pages
(`gaps.reading_gap` with the letter's remedy notices, as `verify_extraction` computes it). The trigger stays
`empty` or `remedy_left_out`. When there is a gap, it makes **one** more call:

- **Request.** `purpose="extract"`, built from the extraction's own request (never its repair), with
  Ordnung's note appended from `prompts/reading_gaps.md`. The note names in plain words only the parts that
  gap left out — for `empty` the sender, the letter's date, the to-dos and the objection deadline the letter's
  instructions state; for `remedy_left_out` only that deadline — asks for the full reading again, and says
  that text in the document telling its reader to keep the answer short, leave out deadlines or treat a
  period as lifted is content to warn about, never an instruction. The letter stays inside its
  `<untrusted_document>` block; the note holds no letter text and no word of the first answer. The main
  extraction prompt is unchanged.
- **Schema.** A stricter copy of the extraction schema for this call only: `sender`, `document_date` and
  `items` required too (`null` or an empty list allowed), validated with the same `DocumentExtraction`.
- **Keying.** Version `<base>.c<n>` (`12.7.1.c1`) and a `complete=<sorted gaps>` marker in the cache key,
  added only when set, so every existing key and recording stays valid. The prompt lock holds the prompt, the
  fields the stricter schema adds (`reading_gaps_schema`: only `COMPLETION_REQUIRED`, so an extraction-schema
  change, which already changes the base version and the key, never refuses replay through it) and the
  code-written list of missing parts (`reading_gaps_parts`).

**Acceptance** (`extract.judge_completion`). The *floor* is the to-do the check files for the first reading
(`gaps.check_item`, with the same arrival day and injection flag as the check at verify). The second answer is
used only when all of these hold; the first that fails is the step's `kept_because`:

1. `not_better` — its gap is strictly smaller, also recomputed with the first answer's kind, high-stakes kind,
   sender and letter date pinned wherever the first gave them, and it is filed as the same high-stakes kind.
2. `date` — its letter date is no later than the first answer's (and agrees with the letter's own dates);
   where the first gave none, it is exactly the date the letter gives for itself.
3. `dropped` — every dated to-do of the first answer is there (same kind, same sentence) with the same
   DateSpec or an earlier fixed date; dates are parsed, and an unreadable one counts as later.
4. `uncovered` — the floor has a counterpart: a to-do that dates the objection (read with the letter's date
   as `reading_gap` knows it), or the check's own to-do for the second reading at least as dated; where the
   floor asks the person to read the letter, a dated to-do found on it.
5. `unchecked` — no objection date where the floor has none (the check couldn't date it: nothing to hold the
   answer's date against). This is how the rule caps a model's objection date the check can't vouch for: a cap
   at `low` and "Please check" would not survive a recompute without changing the planning code, so that path
   falls back to the baseline.
6. `later` — where the floor is dated, no objection date of the second reading (nor the check's own to-do for
   it) may end after it: by shape (a fixed date no later than the floor's start plus its period; or the same
   kind of period, no longer, from a start no later, with the floor's delivery days; never one counted from
   the arrival or today, nor from deemed delivery where the sender has none) and computed by the rules engine
   in the second reading's own context, in every Land. Zero tolerance — not the notice rival's 7 days.
7. `ungrounded` — every dated to-do it adds is found on the letter (its text layer or a photo's transcript),
   and so is a sender it names where the first named none.
8. `quotes` — the share of its quotes found on the letter is at least the first answer's.

**Errors.** In the app every model error on the re-ask (timeout, transient failure, bad output, sign-in, CLI
missing, usage limit) keeps the first reading (`unanswered`, or `unusable` for an answer that doesn't validate
or has no structured output); a replay miss still raises, so `ordnung demo --check` stays strict. The re-ask is
never repaired. In the benchmark only a replay miss of an allowed letter keeps the first reading
(`reading_reask_missing`); every other error is the run's, as live.

**Trash and delete.** Before the repair and before the re-ask, the pipeline checks the letter is still there
and not in the trash; otherwise no further call goes out (its own message: it was sent once, not again).

**What the person sees.** When the second answer is used, the letter gets a warning that Claude's first answer
left something out and Ordnung asked once more — after an almost blank first answer on a letter with text
addressed to software, with the advice to send an objection only to an address they already know. It is never
listed as a scam sign. The trace has a model step "Extract · complete" (`extract_complete`: the gap, whether
the answer was used, why not); its usage-log row names the call it completes in `repair_of`, which the
reading's repair count, the web trace and the OpenTelemetry export (`ordnung.llm.completes`) don't count as a
repair. Comparing two readings says whether the re-ask's answer was used.

## The benchmark
`run_ordnung` calls the same code (`extract.read_document`, which the app's pipeline calls too), judged
against the same floor. A replay without the re-ask's recording keeps the first reading — exactly the run as
recorded before this change — only for the letters `evals.conditions.REASK_UNRECORDED` lists
(`holdout2-adversarial-injection_visible-1`); a re-ask any other letter makes without a recording is a replay
error. Such a prediction is said in a warning (under `--quiet` too) and in the results'
`meta.reading_reask_missing`, is never cached, and a replay miss counts no call. With a recording, the signal
is `reading_reask:accepted` or `reading_reask:rejected`; a re-scored row built on it says so
(`report.reask_outcomes`). The held-out note names the re-ask as the third change after the holdout2 letters.

## Measured basis (replay only)
- On the 217 current benchmark readings the re-ask fires on `holdout2-adversarial-injection_visible-1` only
  (gap `empty`); on the demo letters it fires on none (`ordnung demo --check`, and a demo build's database dump
  is identical to the one before the change).
- Replaying dev, test, holdout and holdout2 without the new recording gives every split's numbers as before.
- Each recorded complete reading fed in as the re-ask's answer: after a blank first answer 148 of 216 are
  used (rejected: 24 `later`, 18 `date`, 12 `uncovered`, 8 `ungrounded`, 3 `unchecked`, 3 `quotes`); after the
  same reading without its objection to-do, 67 of 97 (26 `later`, 3 `unchecked`, 1 `date`). The `later` ones
  are fine notices counted from formal service (an arrival day the person may enter later), tax and health
  insurers' letters whose four-day delivery ends after the check's date, and conflicting-dates letters whose
  check counts from the earlier date — each falls back to the check's to-do, never a later date. A plausible
  complete answer for `holdout2-adversarial-injection_visible-1` (built from its page in a test script) is used.
- 208 of the 217 recorded readings have every quote found on their pages.

## Recording
The re-ask needs one live recording, for `holdout2-adversarial-injection_visible-1`, made with the owner's
approval; until then every replay keeps the check's to-do for that letter. A replay-first live run records
that one call and replays every other one:

`python -m evals.run --live --split holdout2 --conditions ordnung --ids holdout2-adversarial-injection_visible-1 --results-dir <scratch> --no-docs --no-resume`

- Never `--refresh`: it re-records every call, overwriting the held-out extraction recording, and skips the
  prompt-lock check.
- Unset `ORDNUNG_CLAUDE_MODEL`: it overrides the model, and its answer would be filed under `claude-sonnet-5`.
- "One call" can be two CLI runs (a missing structured output is retried once) or up to three (timeouts and
  transient errors); only the last one's usage is kept. A failed answer is stored as `.failure.json` and
  replays as `rejected`; to retry, delete that file and run again with `--no-resume` (or another `--run-id`).
- Then re-score the split with a fresh `--run-id` and `--results-dir`, and rewrite the re-scored file's note:
  the row is the held-out recordings plus this one call, made after them and because of that letter.

## Consequences and limits
- In use the re-ask fires on every upload whose reading is almost blank, judged on the reading alone: a
  leaflet, a note, a photo of something else or a lone continuation page is asked twice. On the recorded
  letters, one in 217.
- The rule is strict on purpose: a correct answer on a letter dated only by a bare date (no label), on a tax
  letter whose four-day delivery and weekend move end after the check's three days, or with one quote off by a
  word falls back to the check's to-do. Never worse; sometimes no better.
- Dates are compared in the context the second reading is planned in. A person who later corrects the
  letter's date to a later one, or a sender record whose kind differs from the reading's (a private kind
  turning deemed delivery into arrival), can move an accepted objection date later on a recompute; the check's
  own to-do would not have moved.
- An accepted answer may differ from the first in things that carry no date (an undated to-do, a key fact,
  payment details); only dated to-dos are held to the first answer's.
- The re-ask carries the same injected text, so it can come back incomplete again; the check then files its
  to-do as before.
