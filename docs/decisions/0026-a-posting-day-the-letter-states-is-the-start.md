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
**Code reads the posting day on the page** (`ingest/posting.py`, `posting_statement`, no model call), in closed
forms only. Each form names what may stand in every place, from a closed list written in the code, and a word it
does not list refuses it: unknown means no. The module's docstring names the forms that count, and each is a test:

- a field beside its label: a posting label ("Tag der Aufgabe zur Post", "Aufgabe zur Post", "Absendedatum",
  "Versanddatum", "Versandt am", "Date of posting" …) that starts its text line — or, by the page's word boxes, its
  cell in the first page's information block, right of the address window and above the salutation —, then only
  a colon, "am" or "ist der", a weekday, "den" and the date, and nothing after it;
- a field under its label, as the header's "Datum" is read: on the page right under the label by the words'
  boxes, the last thing on its row and, in the label's column, the only words there but a weekday ("Mo.,
  19.10.2026"; the address column's words to its left are another column's); or, without boxes, a label alone on
  its line over a date alone on its line (a weekday allowed);
- a whole clause that records this letter's posting: "Dieser / Der Bescheid", "Dieses / Das Schreiben", "Dieser /
  Der Brief" or "Dieser <a listed compound>" ("Dieser Widerspruchsbescheid"), then "wurde am <date> zur Post
  gegeben / der Post übergeben / versandt" or "ist am <date> … worden"; "Die Aufgabe zur Post erfolgte am
  <date>"; "Zur Post gegeben am <date>"; "This letter was posted on <date>" — after nothing but a sentence's end,
  the salutation, a line ending in a date or a listed heading ("Hinweis:").

Every other wording does not count, and the letter's date stays the start, the early side. Three review rounds
refused named wordings one by one (a growing list of "never"), and each found new ones by other routes: an
adjective in the subject, a sentence opening with its verb (a supposition: "Erfolgte die Aufgabe zur Post am …, so
gilt …"), "Bei Aufgabe zur Post am …", a label after another decision's name in its line. An open language does not
close by listing what is refused; closed forms refuse what nobody listed. Recall is given up on purpose: "Der
Bescheid vom <the letter's date> wurde am … abgesandt", "Die Aufgabe zur Post erfolgt am …" (the present, which may
be a plan), a label after other words in its line without boxes no longer count. Every false find of the reviews is
a test that the forms refuse. The app (`ingest.plan.rule_context`) and the
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
  arrival), a declaration under private law (a dismissal, a landlord's notice, a rent increase, an operating-cost
  statement, a contract's, an insurer's, an employer's, a lease's or a bank's letter: from arrival, § 130 BGB,
  whoever sends it), a court's, a fine's (a letter filed as one, whether or not its reading cites § 67 OWiG), a
  letter served with a yellow envelope (formal service) or, as its page says, with a Rückschein or an
  Empfangsbekenntnis (from the receipt it proves, § 4 Abs. 2 S. 1 and § 5 VwZG; a plain Einschreiben counts from
  its posting, § 4 Abs. 2 S. 2 VwZG, and keeps this path), a letter whose sender's procedure law is unknown, an
  e-mailed decision, or a period counted back from delivery;
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
  reading alone), so every recorded answer replays. Replayed with this code, the one tax-assessment error of each
  of the dev, test, holdout and holdout2 splits turns right (24 → 25 of 25, 55 → 56 of 56 three times), and on
  the final split seven of the eight wrong dates in each of its three reads (104 → 111 of 112; the eighth is the
  letter that gives two dates for itself). No right date turned wrong and no date became late (one read's late
  date turned right); holdout3 and newkinds are as before. The reading of a field's date under its label (a
  weekday before it, and the value read by the words' boxes beside the address column's words) was written after
  the final split's layout had been diagnosed in codes (no letter's text read); every number it changes on
  holdout, holdout2 and the final split is re-scored, not held-out, as is every number obtained on a split
  already seen.
- The rule it replaces stays in force where no page was read (the rules tools, a to-do added by hand).
