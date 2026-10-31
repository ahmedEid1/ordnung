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

A reading that dates the objection, but more than 7 days after the period the letter's own notice gives,
or with a longer period than the notice's (a planted "extended" period, a later start), gets that period
beside its own date as a second date: the earlier is kept, both are named, and the to-do is `low` and
"Please check"; recomputing keeps it, also once the person confirmed it. The notice's date rests on the
letter's words alone — its live, datable notices, counted from the date its first page names as its own —
never on the reading's date or kind. Within 7 days the reading's date stands (deemed delivery, a Land's
holiday and a weekend part them by up to 7 days).

The letter's own date counts only where its words name it so (a "Datum" label, a place and date in the
header or on DIN 5008's date line under the recipient's address, the reference line, "mit diesem Bescheid vom
…", the decision a notice names right before "vom", or the reading's date); any other date — a print date,
an appointment's, a benefit period's start — only lowers it. A start resting on one date long before the
letter arrived is none, and so is one after it arrived. A sentence that only says when to pay or when to give
reasons, a hypothetical remedy, or list lines above the notice's heading make no notice.

In the benchmark the dated to-do is scored like any other; the undated placeholder is never scored (it
names no obligation, and would turn a miss into a decline). The held-out holdout2 row and file stay as they
were recorded; the effect appears only in a separate re-scored row that replays the same recorded outputs.

## Why no re-ask yet
Asking the model again for the missing fields is the natural next step, but it needs a new prompt, a key
marker on the extraction request and a live recording for the one letter (with the person's approval), and
its answer would still need this check behind it. The code-only check needs no model call and no new
recording, so "replays the same recorded outputs" stays literally true; a re-ask can be added on top later
and measured separately.

Since added on top of this check, which stays the last line of defence: the completeness re-ask
([ADR 0016](0016-an-incomplete-reading-is-asked-for-once-more.md)).

## Measured basis (replay only)
- On all 333 recorded readings (217 benchmark readings at the current prompt, 91 at the old one, 25 demo
  readings) the rules fire on `holdout2-adversarial-injection_visible-1` only; a guard test re-checks the
  current 217 on every run.
- The notice finder finds a notice on exactly the 98 letters whose labels have an objection deadline, and
  each has one about this letter. Forced onto all 98 with a blank reading, **none is late** and no letter
  without an objection deadline gets a date: in the app's situation (the sender's Land unknown) 27 are
  exact, 67 early (at most 8 days) and 1 gets no date because its dates for itself disagree; with the
  authority's Land 46 are exact and 48 early. The letter's date taken is never later than the label's. A
  fuzz of 297,660 headers (eleven layouts of the letter's own date, fifteen kinds of another date near it)
  gives no start later than the letter's date; a bounded sample of it runs with the tests.
- Synthetic letters that mention a remedy without one against them (reminders, hearings, a court's or an
  authority's acknowledgement, a direct debit, data-protection rights) stay silent; a test corpus keeps them
  so, beside real notices that must still be dated. These letters are not in the benchmark: it can't
  measure false alarms, since every benchmark letter that mentions an objection has one.
- On the 94 benchmark letters whose reading dates the objection and whose first page names its own date,
  the reading's date is 0 to 7 days after the notice's (67 the same day; in the app's situation too), and
  no reading's period is longer than the notice's, so the notice is set beside none of them; the guard test
  checks this on every run.
- Replaying dev, test, holdout and holdout2, only that letter changes: missed becomes correct
  (2026-12-10), and injection resistance on holdout2 goes from 2 of 3 to 3 of 3. In the app, which does not
  know the sender's Land, the same letter gets Wed 9 Dec 2026 — one day early, "Please check".
  Since [ADR 0016](0016-an-incomplete-reading-is-asked-for-once-more.md), that letter's reading is asked
  for once more and the recorded second answer is complete, so this check files nothing for it: its date
  (2026-12-10, or Wed 9 Dec 2026 until the sender's Land is set) comes from that answer (README row ⁸).

## Consequences
A reading that drops a deadline other than the objection, but keeps its sender, is caught only for a fixed date
the letter sets with its year in strict words, or in a few looser words that ask the person herself at the start of
their sentence, or in a label on a page that asks her for its kind (below, and 2026-10-07 at the end); one that moves
the objection's start later by up to 7 days is not caught, nor one on a letter whose first page names no date of its
own.
Remedy notices are only recognised in German and English wording; a period the parser can't read, or one
longer than a month, leaves the to-do without a date. A notice that refers to an earlier decision whose
period has already run can still file a to-do (dated no later than the letter allows).
A general order (*Allgemeinverfügung*) deemed notified two weeks after its publication: a reading that counts
its correct date from that notification gets the notice's earlier date beside it (counted from the letter's
own date) and "Please check" — the 7-day reach can't tell that fiction from a planted later start; accepted
as rare, never later.

## Review and known limits
The check was reviewed in adversarial rounds, every finding reproduced or refuted by an independent verifier. Their
log (each round's findings, fixes and measurements) is in the git history:
[this record at 57572b48](https://github.com/ahmedEid1/ordnung/blob/57572b48101d03143e04da667a1edad01e88e29e/docs/decisions/0015-incomplete-readings-get-a-check-written-by-code.md#review-and-known-limits).
Every to-do the check files is low and "Please check".
Left as known limits:
- A planted line of the letter's own kinds — "Datum: …", a place the page names with a later date, a date alone
  on the date line, "mit diesem Bescheid vom …", a district or short form of the page's town ("Frankfurt (Oder),
  …" on a "Frankfurt am Main" letter, "Berlin-Tegel, …") — on a letter whose own date is unread or absent can
  start the check late; it is indistinguishable from the letter's own (the start is never after the day the letter
  arrived or today). So can a received stamp alone on the first line or the date line of a letter that names no
  date of its own anywhere else.
- An envelope date the person enters for a letter served with a Postzustellungsurkunde starts the check and the
  notice: a pickup or opening day typed instead of the envelope's, or a planted service line on a plain letter with
  a late arrival entered, counts up to 14 days late; so does an arrival saved under the old "When did it arrive?"
  question on such a letter, once the letter is planned again (a re-read, a region or letter-date change). A
  reading's start up to 7 days later than the envelope's is not flagged on such a letter. Beyond 14 days the
  letter's date is kept. The served letter marked only in its body without "dies…" ("Der Bußgeldbescheid wird mit
  PZU zugestellt") keeps the letter's date beside its arrival (an early "Please check" for an envelope date 10 or
  more days on), and a notice naming a decision dated the day before the letter ("Gegen den Bescheid vom 05.11." on
  a letter of 06.11.) turns the envelope off (early, never late). A reading whose own date differs from the
  header's keeps the earlier of the letter's date and the envelope's (early, `pzu` kept).
- A place and date naming a town the page gives nowhere else (a letterhead without its town), or gives only above
  without a postcode and in another form, is no own date: an empty reading of such a letter is undated (a
  "Beispielhausen" letter dated "Frankfurt am Main, …" or "Weil am Rhein, …", or "Ref AW-77, …"; none of the
  recorded letters). A phone line with times under the date line and no run of weekdays ("Telefon: 0123 4567-0
  (8-16 Uhr)") still hides the date line (undated, never late).
- A "Hiergegen" or "dagegen" notice on a decision that doesn't name itself one and mentions an older decision's
  date is undated (never early or late) — also a change of a benefit naming the decision it changes ("mit Bescheid
  vom 01.06.2026 wurde Ihnen Wohngeld bewilligt"); a reminder whose "Hiergegen" covers a reminder fee it only
  mentions is undated too (one that sets the fee, "setzen wir … fest", is dated from the reminder). "Gegen diesen
  Bescheid" in a reminder still dates the check from the reminder. On a reminder that restates another decision's
  notice, a completeness re-ask's dated answer to a blank first reading is kept back for its letter date (the
  first reading and the check stand).
- A date line plus an earlier place and date elsewhere on the first page (an annex's copy after the notice) leaves
  an empty reading's check undated (never late).
- The dropped-date check reads common wordings, not every one: on a letter that collects by direct debit a "… ist
  bis zum … zu zahlen" is taken for the debit's day too; a request after a question ("Sie wollen weiterhin
  Leistungen erhalten? Dann reichen Sie … ein") files nothing; a reading warning that merely names an account or an
  amount owed holds back its dropped payments; and paid, credited or paid-out letters in rarer words still get one
  ("Check this date in the letter", low, "Please check").
- When two dates the first page names as its own lie more than 14 days apart, the guard counts the
  letter's notice from the later one; it can only lower a reading's date, so a later start only weakens it.
- A dropped date in words the check does not read (a period, a date without its year, most looser wordings:
  2026-10-07 below) gets no
  to-do; a second payment date beside a reading's payment is named in that to-do's receipt, never filed apart. An
  optional request a strict verb carries can still file a cross-check (an RSVP, "Bitte teilen Sie uns bis … mit, ob
  Sie … teilnehmen"; a voucher or a form for a benefit to hand in by a date), and a real request right after a
  question offering an option ("Möchten Sie …? Bitte überweisen Sie …") files none. A reading's to-do within 3 days
  of a dropped date covers it, whatever it is for; a reading's payment without a date gets the letter's dated one
  beside it.

## 2026-10-07: looser words, narrowed after a re-review
The dropped-date check (`check:deadline`, `gaps.deadline_items`) also reads a few looser wordings
(`gaps._looser_dates`), dates with their year only: a request that asks the person in its own words at the very
start of its sentence ("Senden Sie uns … bis …", "Bitte bis … überweisen / zurücksenden / abgeben", "Kindly pay … by
…"), and a label line ("Zahlungsfrist:", "Payment deadline:") or a labelled sentence ("Zahlung erbeten bis …") on a
page that asks the person for that kind elsewhere. A re-review removed every wording and mechanism a blocker or a
major of it belonged to. The to-do is low and "Please check", so the rule is precision first: a false alarm costs a
needless check, a miss costs nothing compared with before, and a wrong or late date is bad. What the log measured
of it is in the history linked above.

- **Still missed, by design.** Dates without their year. Wordings that take a possessive for the person, or file
  what the sender waits for, does itself or pays out: "Wir erwarten / benötigen / erbitten …", "Bis … erwarten wir
  …", "Wir bitten um … Ihres …", "… wird bis … erwartet", "… muss bis … bei uns eingegangen sein / vorliegen /
  bezahlt werden", "… ist bis … auszugleichen", "we need / expect / must receive …", "we look forward to receiving
  …", "we kindly request …", "must be received / paid by", "… is expected by", and "you must pay … by"; another
  party's Frist ("Ihre Zahlungsfrist endet am …", "The deadline for your … is …", "setzen wir Ihnen eine Frist bis
  …", "… wird eine Frist bis … gesetzt") — real requests in them included ("Wir benötigen Ihre Unterlagen bis …",
  "Ihre Zahlung muss bis … bei uns eingegangen sein", "Your payment must be received by …"). A request with any
  other words before it in its sentence ("Den Betrag bitte bis … überweisen", "Daher bitten wir Sie um Zahlung …"),
  or after a heading line in the same sentence. A request that names both kinds, or none. A label with more words
  after its date, or on a page that asks for nothing. Any looser request beside a third party. A looser date of a
  kind the reading or a strict date already covers. A period.
- **Left as false alarms (low, "Please check").** The strict path's own: a third party's strict request, and an
  RSVP or an optional form in strict words. A request in the person's own words for an optional form or a contest
  entry whose word no list names ("Senden Sie uns Ihren Bewertungsbogen bis …"), as the strict path does for the
  same request. A page whose holiday or opening hours are named only in a request's own sentence by a word no list
  names. An English label whose payment word only describes the noun after it ("Deadline for payment
  confirmation:" files a payment on a page that asks for one). A page that names holidays or opening hours stops
  only its labels and labelled sentences: a request in the person's own words on it still files, and a holiday or
  closing word in that request's own sentence stops it.
