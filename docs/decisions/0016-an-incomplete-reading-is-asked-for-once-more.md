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

## Decision
After a valid parse, `ingest/extract.py` computes the reading check's own gap on the same pages
(`gaps.reading_gap` with the letter's remedy notices, as `verify_extraction` computes it). When there is a
gap, it makes **one** more call — the completeness re-ask:

- **Request.** `purpose="extract"`, built from the extraction's own request (never its repair: the same
  re-ask whether or not a repair came first), with Ordnung's note appended from a new prompt file,
  `prompts/reading_gaps.md` (outside the `extract*` names). The note names the parts left out in plain
  words — the sender, the letter's date, the to-dos, and the objection deadline the letter's instructions
  state — asks for the full reading again, and says that text in the document telling its reader to keep the
  answer short, leave out deadlines or treat a period as lifted is content to warn about, never an
  instruction. The letter stays inside its `<untrusted_document>` block; the note holds no letter text and
  no word of the first answer. The main extraction prompt is unchanged.
- **Schema.** A stricter copy of the extraction schema for this call only (`schemas.completion_schema`):
  `sender`, `document_date` and `items` are required too (`null` or an empty list allowed). The answer is
  validated with the same `DocumentExtraction` model; the extraction schema itself, locked under
  `extract_system`'s version, is unchanged.
- **Keying.** Version `<base>.c<n>` (`12.7.1.c1` today) and a `complete=<sorted gaps>` marker in the cache
  key, added only when set — so every existing replay key, recording and app cache entry stays valid. The
  prompt, the stricter schema and the code-written list of missing parts are locked in `prompts.lock.json`
  under `reading_gaps`'s version (`reading_gaps`, `reading_gaps_schema`, `reading_gaps_parts`).
- **Acceptance.** The second answer replaces the first only when it validates, its own gap is strictly
  smaller (`empty` → `remedy_left_out` or none; `remedy_left_out` → none), and the share of its quotes the
  existing verification finds on the pages is at least the first answer's (a first answer that quotes
  nothing counts as fully found, so then every quote of the second must be found). Otherwise the first is
  kept.
- **Errors.** Only `ValidationError` and `ClaudeBadOutput` from the re-ask keep the first reading; it is
  never repaired. Every other error — a rate limit, a timeout, the CLI missing — propagates as the
  extraction's would (a rate limit still pauses and requeues the letter). The benchmark also passes its
  replay miss (below).
- **The check stays the last line of defence.** It runs on whichever reading is kept: an accepted answer
  that dates the objection gets no check to-do; a rejected or missing one leaves the check to file its to-do
  as before.
- **Trace.** A model step "Extract · complete" (`extract_complete`) with the gap that triggered it, whether
  its answer was used and, if not, why (`no_answer`, `unusable`, `not_better`, `quotes`); its usage-log row
  names the call it completes in `repair_of`, as a repair's does (the row's outcome says whether the answer
  could be read at all: `repaired` or `failed`). The web trace says it in words.

## The benchmark
`run_ordnung` calls the same code (`extract.read_document`, which the app's `extract_document` wraps). A
replay without the re-ask's recording keeps the first reading and lets the check run — exactly the run as
recorded before this change — with the signal `reading_reask_missing`; a replay miss is no call, so the
calls accounted stay as recorded. With a recording, the signal is `reading_reask:accepted` or
`reading_reask:rejected`. The app treats a replay miss as any error: the demo, which replays recordings
only, must never need a re-ask, and none of its letters does.

## Measured basis (replay only)
- On the 217 current benchmark readings the re-ask fires on `holdout2-adversarial-injection_visible-1` only
  (gap `empty`), the one letter the reading check fires on; on the demo letters it fires on none
  (`ordnung demo --check` replays them strictly).
- Replaying dev, test, holdout and holdout2 without the new recording gives every split's numbers as before,
  that letter included (it takes the `reading_reask_missing` path).
- 208 of the 217 recorded readings have every quote found on their pages; the other 9 have 80 – 91 % found.
  A complete re-ask answer of an almost blank reading is held to every quote found, so if re-ask answers are
  like the recorded readings, roughly one good answer in twenty-five would be turned down and the check's
  "Please check" to-do would stand.

## Recording
The re-ask needs one live recording, for `holdout2-adversarial-injection_visible-1`, made with the owner's
approval; until then every replay keeps the check's to-do for that letter. A replay-first live run records
that one call and replays every other one.

## Consequences
- An incomplete reading costs one more call (and its latency) — on the recorded letters, one letter in 217.
- The re-ask carries the same injected text, so it can come back incomplete again; the check then files its
  to-do as before. An answer that is less incomplete but differs elsewhere (a to-do of the first answer left
  out) is accepted; the acceptance rule looks at the gap and the quotes only.
- A second answer that dates the objection later than the notice allows is caught as before by the notice
  rival (ADR 0015), which only lowers a date.
