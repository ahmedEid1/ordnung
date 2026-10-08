# ADR 0007 — Short written policies instead of growing heuristics

**Status:** accepted · **Date:** 2026-09-26 · **Updated:** 2026-10-07 (a later feature that changes an
earlier policy changes its text; hand-off sync's kept copies and the backup policy)

## Context
Ordnung was reviewed in rounds by independent agents, each prompted to break something and to prove
it with a failing test. Most findings were fixed once and stayed fixed. Three areas did not
converge: every fix produced new, more exotic counter-examples.

- **Hidden text in HTML e-mails.** To decide which text a mail client shows, the code grew an HTML
  tree builder, a CSS cascade with specificity, media-query evaluation and simulated phone and
  desktop screens: about 2,800 lines at its peak. Each round found another gap (a dark-mode block
  read as hidden, an Outlook-only copy, a quadratic regex).
- **The health-insurance special right** (§ 175 Abs. 4 SGB V). Code decided from German sentences
  whether the *Zusatzbeitrag* was raised, with lists of rise and stay words and clause splitting.
  Verb-final sentences, negations and other insurers named in the same sentence kept breaking it.
- **Recurring obligations.** Dates moved as days passed, and "unpaid occurrence" markers tried to
  remember which month had not been paid. Re-reading a letter, manual dates and paying ahead kept
  producing contradictions.

## Decision
Each area gets a short policy, written in the code's docstring, that decides every case, and tests
that pin the policy. Cases the policy does not decide are documented limitations, not bugs.

1. **HTML e-mails** (`ingest/text.py`, `html_to_text`). Text counts as hidden only when simple rules
   make it certain: inline hiding styles (display, visibility, opacity, a font of at most 1 px,
   zero-height clipped boxes, far off-screen boxes, text in its own inline background colour) and
   simple top-level or screen-only hiding classes that no other rule may show. Hidden text before the
   first visible text is the preview text the inbox list shows, so it is visible. When in doubt, text
   is visible. Hidden text never reaches the model; visible text is still wrapped as untrusted, read by
   a model without tools, checked for injection phrases, and every date it yields is computed and
   checked against the page (ADR 0002, 0003, 0006).
2. **Special right to cancel a health insurance.** Reading is the model's job (ADR 0002): the
   extraction states a price change with its old and new unit price. The Idea is raised only when both
   are percentages and the new one is higher. A contribution that rises with income opens no right.
   A missed Idea is acceptable; a wrong legal claim is not, and a genuine raise letter states the
   right itself, which Ordnung files as that letter's to-do.
3. **Recurring obligations** (`recurrence.py`). Ordnung cannot see payments, so a recurring item is
   a schedule: it always shows its next occurrence and is never overdue because a month passed.
   Marking it paid moves it to the next occurrence; each occurrence is dated by the rules engine;
   re-reading a letter never moves a date backwards. Missed payments surface through reminder letters,
   and a reminder never hides a bill's recurring items.

## Consequences
- The e-mail code went from about 2,800 lines at its peak to about 400, linear in input size, and
  the review rounds on all three areas ended with only exotic cases, which are listed as limitations
  in the docstrings.
- Accepted trade-offs: an attacker can keep text visible, and so sent to the model, by styling it in
  ways the policy does not read; it then meets the other defences. A missed Zusatzbeitrag Idea
  when the model reports the rates in words. A missed month of a recurring payment shows up only
  when a reminder arrives.
- The pattern generalises: when adversarial review keeps finding new cases in a heuristic, the fix is
  a smaller policy and a clear statement of what it does not do, not a bigger heuristic.

## Later policies, and when one changes another
Later features that touch the rest of the person's world got their policy the same way: backups,
reminders and calendar sync (ADR 0013), phone access (ADR 0017), hand-off sync between computers (ADR
0018), each in its module's docstring. A policy is only worth its text if the text stays true, so a feature
that changes what an earlier policy promises changes that policy's text in the same change — and says so
where the reader of the old text will look.

The first case: the backup policy (`ordnung/backup/__init__.py`) said that a backup file is never written
inside the data folder it backs up. Hand-off sync's *kept copies* are backup files written into
`<data>/sync/kept/` before a computer's data is replaced. The rule that refuses the data folder belongs to
`ordnung backup --to` and the browser's download (`destination`), which make backups meant to survive the
computer; a kept copy only undoes a replacement on this computer. So the backup policy now says both: a
backup you make is never stored inside the data folder, and a kept copy is, and is lost with this
computer's disk and with *Delete everything* (ADR 0018).
