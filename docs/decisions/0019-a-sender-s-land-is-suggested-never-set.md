# ADR 0019 — A sender's Land is suggested, never set

**Status:** accepted · **Date:** 2026-10-08

## Context
A sender's Land decides which regional public holidays move the dates of their letters and, for a Land
authority, whether its letter counts as delivered after 3 or 4 days. Only the person sets it, in the
sender's details (*Which state is this sender in?*); until then the engine counts nationwide holidays and
3 days, so a date comes out early, never late (SPEC § 21). The benchmark shows what that costs: replayed
without the sender's Land, Ordnung scores 84–91 % on the published splits instead of 98–100 %
([evals.md](../evals.md#without-the-senders-land)). Most people never open a sender's details, so the
select alone is rarely answered.

Almost every German letter prints its sender's postcode, and almost every postcode lies in one Land. But
the two kinds of error are not alike: an unknown Land makes a date early, while a wrong Land the person
confirmed can make it late (the wrong Land's holiday moves the date out). So a suggestion has to be
precise more than it has to reach far, and it has to stay a question.

## Principle
The postcode suggests, the person decides ([ADR 0006](0006-read-only-agent-and-humble-automation.md)).
Nothing Ordnung reads sets a sender's Land.

## Decision

**The data.** GeoNames' postal codes for Germany (CC BY 4.0), reduced to one row per postcode with the
Länder GeoNames lists for it: `src/ordnung/rules/data/postcodes_de.tsv`, 10,813 postcodes, 10,780 of them
in one Land, 32 in several and 1 in none. `scripts/make_postcode_table.py` builds it from a downloaded
`DE.zip` (the lookup never downloads anything; `--check` says whether the table matches the download). The
credit, the licence and the changes are in its header and in `LICENSE-GeoNames.txt`, which the wheel
carries; the README credits GeoNames too.

**The lookup** (`ordnung.rules.postcodes`, the policy in its docstring, ADR 0007). It is exact: a postcode
GeoNames lists in exactly one Land, with no prefix, range or fuzzy inference. There is no suggestion for an
address that names another country (or has a foreign postal prefix, or a foreign e-mail or web domain),
an address without a 5-digit postcode (a Postfach number is never one), a postcode GeoNames doesn't list,
lists in several Länder or lists without one, postcodes in different Länder, or a postcode that is not in
the letter's visible text. The own-state check removes one more question: when the postcode is the
person's own, or is in their town under the same first two digits, and the table puts it in another Land
than the one the person chose for themselves, the table and the person disagree, and nothing is asked.
Before onboarding the person's Land is unknown and never vetoes.

**The source.** The sender's live incoming letters, newest first (at most 12), never one with signs of a
scam; when they suggest different Länder there is no question. The sender's stored address (the first
letter's, never refreshed) is never a source.

**Where it is asked.** In the sender's details, whenever there is a suggestion and no Land. On a letter's
page, as a card after the arrival question, when one of that letter's open dates may change once the Land
is confirmed. Among Today's Ideas (`sender_land`, one per sender) when one of the sender's open dates may.
A date "may change" when its receipt says a regional holiday was not counted, when it was counted backwards
over one, or when it was counted with the 3-day delivery rule and the suggested Land uses 4 days
(`waits_for_sender_land`; "may", as the holiday need not be one in that Land). Never as a toast, a desktop
notification, a modal, a preselected select, in *Ask* or on the command line. The question names its
evidence: *Is X in Bavaria?* with the postcode on their letter.

**The answers.** *Yes* sends the same `PATCH /api/parties/{id}` as the select, which recomputes every letter
of that sender, with Undo. *Other state…* opens the select. *Don't know* dismisses the sender's Idea through
`PATCH /api/suggestions/{id}`, with that Idea's Undo: the dates stay the earlier ones, the card and the Idea
go away, and the details keep asking. Nothing new is stored (the suggestion is computed on read), there is
no new route and no migration, and *Ask* does not see it.

## Measured
`scripts/eval_without_land.py` replays the benchmark's recorded readings a third time, giving the rules
engine the Land `suggest_land_why` suggests from the reading's sender address and the letter's visible
text, as if the person said Yes to every suggestion
(`evals/results/2026-10-08-claude-sonnet-5-without-land.json`, no model called). Every split scores what it
scores with the letterhead's Land: 55, 55, 55 and 56 of 56 on test, holdout, holdout2 and holdout3, 24 of 25
on dev, none late, and no required date differs from the letterhead replay. On the 77 of the benchmark's
280 letters whose letterhead names a Land, the postcode suggested that Land for 76, another Land for none,
and none for 1 (a postcode GeoNames doesn't list); of the other 203, it suggested a Land for 178; 16 have a
postcode GeoNames doesn't list, 7 an address abroad and 2 no postcode. No letter lost its suggestion to the
visible-text rule.

What this does not show: the number is a ceiling (Yes to every suggestion); each benchmark letter is its own
sender and the benchmark has no address for the person, so the checks on the sender's other letters and the
own-state check are not exercised; and the letters are synthetic, with mostly real postcodes and made-up
towns. 0 wrong of 76 puts the rate of wrong suggestions at no more than 3.9 % with 95 % confidence
(one-sided; 4.7 % two-sided), not at zero.

On the demo, whose postcodes are mostly in Berlin's range while its person's Land is North Rhine-Westphalia,
the own-state check keeps 10 senders quiet whose postcode, or town and first two digits, are the person's
own; two senders are asked, in their details only (none of their dates waits for a Land). Without the
check, 12 would be asked. In real use the check fires only when the table and the person disagree, and it
only ever removes a question.

## Rejected or deferred
- **Setting the Land by itself, with an Undo.** Silent, and a date counted backwards with a wrong Land can
  come out late.
- **Asking Claude for the Land.** A model call per sender, open to injection, and not grounded in data.
- **A town cross-check** (the town after the postcode must be a GeoNames place of it). It would keep only 12
  of the 75 right suggestions on the benchmark, whose towns are made up, so the feature could not be
  measured; and the table would need place names.
- **A postal-area fallback** for postcodes GeoNames doesn't list (many P.O. box and large-customer
  postcodes). Measured on GeoNames itself, the first three digits are right for 99.72 % of all postcodes
  left out one at a time, but for 98.94 % (1,969 right, 21 wrong) of the organisation and large-customer
  postcodes it is meant for; the first two digits, each 3-digit block left out, for 98.59 % (4,531 right,
  65 wrong). On the benchmark it gains one letter and no date. Deferred until real use shows the need;
  `python -I scripts/make_postcode_table.py DE.zip --measure-fallback` reproduces the numbers.
- **A range table** (245 runs between listed neighbours, 3.7 KB). It answers postcodes GeoNames doesn't
  list, which is inference, and loses "listed in several" and "listed without a Land".
- **Asking about every new sender.** It nags about senders none of whose dates depends on the Land.
- **A new route.** The existing PATCHes already sync, have an Undo and are allowed from a paired phone.
- **A stored column.** It needs a migration, and a computer still on 0.2.0 would refuse the newer database
  in hand-off sync.

## Consequences and known limits
- The suggestion can be wrong, and the question shows the postcode so the person can check: a central mail
  centre or a service address in another Land; a digit misread on a photo; the recipient's address read as
  the sender's; a foreign address that names no country, uses a German-looking 5-digit code and a `.com`
  domain; GeoNames' own errors (its data comes "as is") and its ageing (rebuild with the script).
- No question for many P.O. box and large-customer postcodes, which GeoNames doesn't list.
- A computer still on 0.2.0 that receives a `sender_land` Idea by hand-off sync shows it but never takes it
  away; it opens the sender's details, which is harmless. Update both computers.
- The question's title (the sender's name and the Land) is part of what *Weekly Ideas* sends, like every
  Idea's ([privacy.md](../privacy.md)).
