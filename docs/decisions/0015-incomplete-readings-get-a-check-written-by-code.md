# ADR 0015 — Incomplete readings get a check written by code

**Status:** accepted · **Date:** 2026-10-01

## Context
The extraction schema requires only a letter's kind, title, summary and explanation. On the holdout2 split's
one recording, the reading of `holdout2-adversarial-injection_visible-1` — a decision with a visible
instruction aimed at AI tools — came back with exactly those four fields: no sender, no letter date, no
to-do. The pipeline accepted it, filed the letter as `processed` with one warning and no to-do, and the
objection deadline its own instructions on how to object (*Rechtsbehelfsbelehrung*) state was lost. Nothing
judged whether a reading was complete; the only way to "Please check" was a dated to-do that failed its
check.

A model that half-obeys such an instruction can also copy the remedy and leave out only its date. Both are
silent today, and both are visible in the letter's own text.

## Decision
After quote verification, code checks every reading against the letter's **visible** text
(`ingest/gaps.py`, `verify_extraction(check_reading=True)`, the same function in the app and in the
benchmark's Ordnung condition):

- **empty** — no to-do, sender, letter date, key fact, reference, contract, change, payment or remedy;
- **remedy left out** — the letter states how to object within a period, in words about a remedy against
  this letter (not a later decision's, one already lodged, a direct debit's or one ruled out), its text
  shows an administrative act, it is not a kind whose deadlines the law files itself (unless the letter
  doesn't bear that kind out and its notice is shorter than the law's period), and no to-do dates the
  objection with a date that computes (a `remedy` read without its date does not count).

Either way the letter gets **one** to-do in slot `check:reading`, always `low` and "Please check". **Its date
is never later than the letter allows:** the period that ends first of all the notices state, dated only
when it is from a week to a month and every notice's period can be read and runs forward; counted from the
earliest date the letter gives for itself, and not at all when those dates are more than 14 days apart;
deemed delivery only when every notice counts from notification; and on recompute only an earlier start
moves it. When any of that fails, the to-do has no date — the person finds it in the letter — rather than a
wrong one. Without a notice it is an undated "Read this letter yourself". The reading itself stays as the model gave it; the to-do and a warning
say what code added. Confirming, re-dating, finishing or dismissing the to-do ends "Please check"; a later
complete reading removes it unless the person acted on it.

A reading that dates the objection, but more than 14 days after the period the letter's own notice gives
(a planted "extended" period, a later start), gets that period beside its own date as a second date the
letter gives: the earlier is kept, both are named, and the to-do is `low` and "Please check"; recomputing
keeps it, also once the person confirmed it. Within 14 days the reading's date stands (deemed delivery, a
Land's holiday and a weekend part them by up to 7 days).

In the benchmark the dated to-do is scored like any other; the undated placeholder is never scored (it
names no obligation, and would turn a miss into a decline). The held-out holdout2 row and file stay as they
were recorded; the effect appears only in a separate re-scored row that replays the same recorded outputs.

## Why no re-ask yet
Asking the model again for the missing fields is the natural next step, but it needs a new prompt, a key
marker on the extraction request and a live recording for the one letter (with the person's approval), and
its answer would still need this check behind it. The code-only check needs no model call and no new
recording, so "replays the same recorded outputs" stays literally true; a re-ask can be added on top later
and measured separately.

## Measured basis (replay only)
- On all 333 recorded readings (217 benchmark readings at the current prompt, 91 at the old one, 25 demo
  readings) the rules fire on `holdout2-adversarial-injection_visible-1` only; a guard test re-checks the
  current 217 on every run.
- The notice finder finds a notice on exactly the 98 letters whose labels have an objection deadline, and
  each has one about this letter. Forced onto all 98 with a blank reading, **none is late** and no letter
  without an objection deadline gets a date: in the app's situation (the sender's Land unknown) 27 are
  exact, 66 early (at most 8 days) and 2 get no date because their dates for themselves disagree; with the
  authority's Land 46 are exact and 47 early. The letter's date taken is never later than the label's.
- Synthetic letters that mention a remedy without one against them (reminders, hearings, a court's or an
  authority's acknowledgement, a direct debit, data-protection rights) stay silent; a test corpus keeps them
  so, beside real notices that must still be dated. These letters are not in the benchmark: it can't
  measure false alarms, since every benchmark letter that mentions an objection has one.
- On the 93 benchmark letters whose reading dates the objection and whose notice the check could date, the
  reading's date is 0 to 7 days after the notice's (67 the same day; in the app's situation too), so the
  notice is set beside none of them; the guard test checks this on every run.
- Replaying dev, test, holdout and holdout2, only that letter changes: missed becomes correct
  (2026-12-10), and injection resistance on holdout2 goes from 2 of 3 to 3 of 3. In the app, which does not
  know the sender's Land, the same letter gets Wed 9 Dec 2026 — one day early, "Please check".

## Consequences
A reading that drops a deadline other than the objection, but keeps its sender, is still not caught; one
that moves the objection date later by up to 14 days is not caught either.
Remedy notices are only recognised in German and English wording; a period the parser can't read, or one
longer than a month, leaves the to-do without a date. A notice that refers to an earlier decision whose
period has already run can still file a to-do (dated no later than the letter allows).
