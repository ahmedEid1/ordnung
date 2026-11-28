# ADR 0026 — A posting day the letter states is the start

**Status:** accepted · **Date:** 2026-11-27

## Context
An authority's letter counts as delivered on the 4th day "nach der Aufgabe zur Post" (§ 122 Abs. 2 Nr. 1 AO,
§ 41 Abs. 2 S. 1 VwVfG, § 37 Abs. 2 S. 1 SGB X): the law counts from the day the letter was handed to the post,
not from its printed date. Many authorities print that day on the letter, a day or a few after its date ("Tag
der Aufgabe zur Post: …"). Since its first version the engine set such a day aside on purpose and counted from
the letter's date: posting can only be the same day or later, so the letter's date was the safe stand-in, and
"never replace the anchor with a later date for the primary result" kept a posting day the model alone had read
from making a date late. The receipt said only that the deadline "may be a few days later", at confidence
`high`.

The final run of the pre-registered evaluation showed what that costs ([evals.md](../evals.md)): Ordnung dated
92.9 % of the final split's deadlines exactly right, the agent given Ordnung's engine as a tool 98.8 %, and
"Please check" caught 0 of Ordnung's 8 wrong dates. 21 of Ordnung's 24 wrong answers were this one rule: seven
deadlines whose letter prints a later posting day, each counted from the letter's date, 1 to 6 days early. The
same rule made Ordnung's one tax-assessment error on the dev, test, holdout and holdout2 splits. The early date
is the safe side, but it is not the law's date, and nothing told the person so.

The project's principle settles where the line is ([ADR 0002](0002-llm-reads-code-computes.md),
[ADR 0003](0003-grounding-levels.md)): the model reads, code checks the reading against the page. A posting day
the model names is a reading; one that code finds on the letter's own page is the authority's record.

## Decision
**Code reads the posting day on the page** (`ingest/posting.py`, `posting_statement`, no model call): a field in
the header or the footer ("Tag der Aufgabe zur Post: …", "Absendedatum", "Datum des Versands", "Versandt am:"
where a cell starts, "Date of posting"), its date beside the label or under it — under it as the header's "Datum"
is read: on the page right under the label by the words' boxes, or, without boxes, label and date each alone on
their line, never another column's date or a table's row —, or a sentence in the statutes' words ("am … zur Post
gegeben", "Aufgabe zur Post am …") with no subject or about this letter, or that *this* letter was sent on a day
("Dieser Bescheid wurde am … versandt"). Never another decision's or the person's letter, another document named
by its own noun or sent to someone else ("Die Zahlungsaufforderung …", "Eine Mitteilung an den Arbeitgeber …"),
a line that dates another letter, an enclosure or a copy, a card, an ID or documents sent, a payment's or a
deadline's date, the day a letter counts as delivered, a future, planned ("voraussichtlich", "geplant"),
requested or negated posting, an e-mail or a portal, goods sent, or a date that reads two ways — in a field as in
a sentence (the module's docstring lists each, and a test holds each). The app (`ingest.plan.rule_context`) and the
benchmark's Ordnung condition call the same function, so the benchmark measures what ships. It reaches the
engine as `RuleContext.posting`, never through the model's `anchor_date`.

**The engine starts an authority's deemed delivery there** (`rules.deadlines._stated_posting`), also when it is
later than the letter's date, under guards in code:

- after the letter's date (an earlier posting day the reading names is used as before; one on the letter's date
  changes nothing);
- not after the day the letter is read: it can't have been posted after it arrived;
- at most 7 days after the letter's date (`POSTING_REACH`). An authority posts a decision on the day it is dated
  or in the next working days; a week covers a weekend with the longest run of holidays (24 December to
  1 January). Beyond it a misprint or another letter's date is likelier, and the further a start moves, the more
  a wrong one costs: the letter's date stays the start and a note names the later deadline. (The two-dates
  check accepts 14 days for a letter's own date, but it only ever keeps the earlier date.);
- only for an authority's deemed delivery by post, counted forward: never a company's period (it runs from
  arrival), a court's, a fine's (a letter filed as one, whether or not its reading cites § 67 OWiG) or a letter
  served with a yellow envelope (formal service), a letter whose sender's procedure law is unknown, an e-mailed
  decision, or a period counted back from delivery;
- two different posting days on the page: the earlier counts, both are named, `low` and "Please check"
  (`conflicting_dates`);
- found only in a photo's transcription: the date is at most `medium`, as every fact read from a photo (counted
  once with a quote read from the same transcript).

The receipt names the posting day and its words on the page (rule `posting_day_stated`), says what the letter's
own date would have given, and gives that earlier date as the **safe date** — that count's own safe date where it
has one (a notice, which never moves, may end on a weekend: the working day before it): acting by it is on time
even if the printed posting day were wrong. The send-by date follows the due date, as everywhere.

**A later posting day only the reading names** — the pages were read and state none — changes nothing in the
date, as before. It is no longer silent: the receipt names the later deadline it would give, and the
confidence is one level lower (`medium`), since the later date may be the right one. That holds whether the
reading gives it as the period's start (`anchor_date`) or only among its key facts (a fact labelled as a posting
day, read in code: `read_posting_day`, `RuleContext.posting_read`). A posting day the page states beyond a guard
is named the same way — except one after the day the letter is read: it can't be the posting day, so the note
says so and names no deadline.

**The rules tools do not change**, in behaviour or in a word of their instructions: a tool caller has no page,
so `RuleContext.posting` stays unset and a later posting day stays the note it was.

## Consequences
- A date can now be later than before: by the days between the letter's date and the posting day it prints,
  and more where the end then crosses a weekend or holidays (up to 7 days at the year's turn). Protecting
  against a wrong posting day: only code's reading of the page starts it, in words that say this letter was
  posted then; the guards above; the safe date on the receipt; "Please check" when the page contradicts itself.
- An earlier date is never moved: a posting day before the letter's date, a confirmed arrival, the two-dates
  check and the letter's own notice still keep the earlier date.
- Nothing sent to the model changed (no prompt, schema or re-ask wording; the completeness re-ask decides on the
  reading alone), so every recorded answer replays. Replayed with this code, the dev split's and the test
  split's one tax-assessment error turn right and no other date moves. On the holdout, holdout2 and final
  splits the check finds no posting day on the letters whose label counts from one, so their dates are as
  before; why is not known (the letters may not be read to write a cue). Every number obtained on a split
  already seen is re-scored, not held-out.
- The rule it replaces stays in force where no page was read (the rules tools, a to-do added by hand).
