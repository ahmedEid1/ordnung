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

## Consequences
A reading that drops a deadline other than the objection, but keeps its sender, is caught only for a fixed date
the letter sets in strict words (below); one that moves the objection's start later by up to 7 days is not
caught, nor one on a letter whose first page names no date of its own.
Remedy notices are only recognised in German and English wording; a period the parser can't read, or one
longer than a month, leaves the to-do without a date. A notice that refers to an earlier decision whose
period has already run can still file a to-do (dated no later than the letter allows).
A general order (*Allgemeinverfügung*) deemed notified two weeks after its publication: a reading that counts
its correct date from that notification gets the notice's earlier date beside it (counted from the letter's
own date) and "Please check" — the 7-day reach can't tell that fiction from a planted later start; accepted
as rare, never later.

## Review and known limits
The check was reviewed in four adversarial rounds, six lenses each (dates, false alarms, attacks, tests,
the benchmark, what the person sees), every finding reproduced or refuted by an independent verifier and
every fix checked against all earlier rounds' probes; the owner capped the loop after round 4. A fifth pass
tightened the limits round 4 left (every earlier round's probes re-run, replay only):

- **A letter served with a Postzustellungsurkunde** (a short line of its header, or "Dieser Bescheid wird Ihnen mit
  Postzustellungsurkunde zugestellt", every notice counting from notification or service) has every to-do counted
  from its arrival cite `pzu`: the app asks "When was it delivered?" for the date on the yellow envelope, nothing
  filled in, and that date — the day of service whether the letter was handed over, put in the letterbox or
  deposited at the post office (§ 3 VwZG with §§ 180, 181 ZPO; § 41 Abs. 5 VwVfG) — starts the check and the notice
  set beside a reading's date, when it is after the letter's own and within 14 days of it. The false early "Please
  check" of round 4's R4L-1 is gone for these letters; on any other letter a notice from notification keeps the
  letter's date beside an arrival (R4L-1's guard).
- **A reminder's "Hiergegen …" or "dagegen"** on a letter that never names itself a decision counts as another
  decision's notice (from that decision's date where the letter gives it within 14 days of its own, else no
  date: round 4's V4-2 reminder is now undated, not 21 days late); "… nach Bekanntgabe des
  Bescheides" beside "Gegen diesen Bescheid ist der Widerspruch gegeben." is this letter (no longer undated or 12
  days early); a Widerspruchsbescheid's reasoning ("…, da er nicht … erhoben wurde") is no notice.
- **The start needs a date of the letter's own kinds.** A place and date counts only when the page names the place
  after a postcode or above it; a date alone on DIN 5008's date line not with an appointment's time under it; an
  appointment's block is known by a heading without its colon too ("Ihr Termin", "Einladung …"); a payments
  table or a "Stichtag" column is no reference line. A date named like the letter's own but of no own kind
  ("Abholung am Schalter, …", "Sprechtag, Dienstag, …") only lowers the start, as a weak one does: while the
  letter's own date is unread, such a planted line or an appointment's starts nothing without the reading's date
  beside it (the leftovers of rounds 3 and 4). On the recorded letters this costs no date: every place and date
  they give names a town of the page. More own-date forms are read: a date alone on the first line when the
  header gives no other, "Ort, Datum: …", a place and date beside "Ihr Zeichen:", "Leistungsabteilung   Datum …";
  "Stand: …" is a weak one.
- **A fixed date the letter sets that the reading left out** (pay by, send by, in strict words only) gets a
  "Please check" to-do of its own (`check:deadline`), dated as the letter writes it, never moved; never in a
  sentence of a remedy, a condition, the past, the sender's own act or a direct debit, an appointment, a
  discount or a validity, never a date past when the letter arrived, never when the reading has a to-do within
  3 days of it, quotes its sentence or names it as a second date, never beside a to-do the person acted on that
  covers it, and never for an almost blank reading or one that calls the letter a scam. It files none on any
  recorded reading (333: the four splits at the current and the old prompt, and the demo); with the readings'
  to-dos removed it files 15 on the benchmark letters, each coming out on the labelled date.

That fifth pass was reviewed in turn — five lenses (dates, false alarms, the envelope, attacks, tests and docs),
each finding reproduced or refuted by an independent verifier — and given one capped fix pass:

- **Town forms.** The town after a postcode is read within its line and column (no "Berlin" run into the
  recipient's name below it), and a place and date may give it shortened, with its river or district, or with its
  umlauts spelled out ("Frankfurt a. M." for "Frankfurt am Main", "Halle (Saale)", "Berlin-Mitte", "Muenchen") —
  never with another word after it ("Frankfurt Hauptwache"). "Stand: …" is a weak date of the letter's only in its
  header or on its date line; in the body ("Forderungsaufstellung, Stand: …") it is none.
- **Stamps.** A date alone on the first line, or alone on the date line, is lowered to a date the letter names as
  its own at its foot ("Beispielhausen, den 06.11.2026" over the signature, on the first page or a later one) and
  leaves no start when that one is more than 14 days earlier: a received stamp ("20.11.2026" over "EINGANG") never
  starts the check late when the letter is dated at its foot.
- **What hides the date line.** Opening hours that say so or run Mo–Fr, a line naming its own date and time
  ("Meldeaufforderung zum … um 9:00 Uhr"), an info block's rule for visits ("Termine nach Vereinbarung", "Vorsprache
  nur mit Termin") and a department's name ("Terminvergabe") no longer make the letter's own date an appointment's.
- **Notices.** A reported remedy is dropped only on a decision on a remedy, and never in a condition ("…, wenn nicht
  innerhalb von zwei Wochen … Einspruch eingelegt worden ist"). With "Hiergegen", the hearing before the decision
  ("Mit Schreiben vom … haben wir Sie angehört") is no other decision; a reminder ("Zahlungserinnerung", "die noch
  offen ist") whose "Hiergegen" restates a decision it doesn't date is undated — 21 days late before, on main too;
  a letter that decides itself now ("Ihren Antrag … lehnen wir ab", "setzen wir eine Mahngebühr … fest") is no such
  reminder, whatever open amount it mentions.
- **The envelope.** A notice naming an earlier decision turns the envelope off unless it names this letter too or a
  decision on a remedy (a Widerspruchsbescheid stays served, § 74 VwGO); copies, representatives' service,
  negations and reference numbers ("PZU-2026-…") mark no letter served. A conflicted reading's settled receipt keeps
  `pzu`, so the app keeps asking for the envelope date (it asked "When did it arrive?" with Today before: 7 days
  late); a reading of a served letter gets no deemed delivery days; an envelope date more than 14 days on is said
  to be kept back; the question says "not the day you picked it up or opened it".
- **Dropped dates.** `check:deadline` to-dos are slotted by date and kind and carried over by date (a paid one
  moves onto the new reading's payment of its day; another date never takes over its status), worded as a
  cross-check ("Check this date in the letter"), never a "Pay" Idea, at most three. They are never filed for an
  option the person may take, a period's end, an instalment of a recurring to-do of the reading (its very day), a
  direct debit's, a box on a letter that says it is paid or credited or that pays money out (label dates only, and
  not when the sentence denies it: "bisher nicht erhalten"), the full price beside a reading's discount, or a
  payment a reading's warning doubts.

A fuzz of 297,660 headers (eleven layouts of the letter's own date, fifteen kinds of another date near it) gives
no start of the check later than the letter's date and leaves fewer undated than before (56,334 of the 270,600
outside one layout, from 64,534); that one, "Frankfurt am Main, …" on a "Beispielhausen" letter, is now undated in
23,370 of 27,060 (from 6,560; below). An extended one of 858,704 — the new own-date forms, own dates left unread,
appointment blocks and planted lines among the distractors — gives none either, but for a planted date of the
letter's own kinds on a letter that gives no date of its own (below); a date alone under a sentence naming
another ("Mit diesem Bescheid vom … setzen wir … fest.") is weak now, not dropped, so that sentence planted above
it no longer moves the start later. The notice set beside a reading's date still starts at the later of two
own dates more than 14 days apart; it can only lower a reading's date. Every to-do the check files is low and
"Please check". Left as known limits:
- A planted line of the letter's own kinds — "Datum: …", a place the page names with a later date, a date alone
  on the date line, "mit diesem Bescheid vom …", a district or short form of the page's town ("Frankfurt (Oder),
  …" on a "Frankfurt am Main" letter, "Berlin-Tegel, …") — on a letter whose own date is unread or absent can
  start the check late; it is indistinguishable from the letter's own (the start is never after the day the letter
  arrived or today). So can a received stamp alone on the first line or the date line of a letter that names no
  date of its own anywhere else (as before this round).
- An envelope date the person enters for a letter served with a Postzustellungsurkunde starts the check and the
  notice: a pickup or opening day typed instead of the envelope's, or a planted service line on a plain letter with
  a late arrival entered, counts up to 14 days late; so does an arrival saved under the old "When did it arrive?"
  question on such a letter, once the letter is planned again (a re-read, a region or letter-date change). A
  reading's start up to 7 days later than the envelope's is no longer flagged on such a letter. Beyond 14 days the
  letter's date is kept. The served letter marked only in its body without "dies…" ("Der Bußgeldbescheid wird mit
  PZU zugestellt") keeps R4L-1's guard (an early "Please check" for an envelope date 10 or more days on), and a
  notice naming a decision dated the day before the letter ("Gegen den Bescheid vom 05.11." on a letter of 06.11.)
  turns the envelope off (early, never late). A reading whose own date differs from the header's keeps the earlier
  of the letter's date and the envelope's (early, `pzu` kept).
- A place and date naming a town the page gives nowhere else (a letterhead without its town), or gives only above
  without a postcode and in another form, is no own date: an empty reading of such a letter is undated. Of the
  earlier rounds' probes this undates lines like a "Beispielhausen" letter dated "Frankfurt am Main, …" or "Weil am
  Rhein, …", and "Ref AW-77, …"; none of the recorded letters. A phone line with times under the date line and no
  run of weekdays ("Telefon: 0123 4567-0 (8-16 Uhr)") still hides the date line (undated, never late).
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
- A dropped date in looser words ("Die Zahlung wird bis … erwartet", a date without its year, a period) gets no
  to-do; a second payment date beside a reading's payment is named in that to-do's receipt, never filed apart. An
  optional request a strict verb carries can still file a cross-check (an RSVP, "Bitte teilen Sie uns bis … mit, ob
  Sie … teilnehmen"; a voucher or a form for a benefit to hand in by a date), and a real request right after a
  question offering an option ("Möchten Sie …? Bitte überweisen Sie …") files none. A reading's to-do within 3 days
  of a dropped date covers it, whatever it is for; a reading's payment without a date gets the letter's dated one
  beside it.
