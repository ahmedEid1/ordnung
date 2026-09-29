# ADR 0010 — High-stakes letters: kinds assigned by code from the reading

**Status:** accepted · **Date:** 2026-09-26 · **Updated:** 2026-09-29 (extraction prompt version 9)

## Context
Some letters are rare but catastrophic when missed — a court payment order (*Mahnbescheid*), an
enforcement order, a dismissal, a landlord's notice, a rent increase request — and most of them never
state their most important deadline. Their dates follow their own rules (`rules/letters.py`), so the
rules engine must know the kind of letter. The model reads (ADR 0002), but the extraction prompt has no
field for these kinds, and changing the prompt invalidates every recorded answer (demo fixtures and
benchmark recordings, ADR 0004). So code has to decide the kind from the model's ordinary reading, which
means reading some German wording in code — the kind of clause parsing ADR 0007 warns about.

## Decision
1. **Kinds assigned by code.** `HighStakesKind` (`court_payment_order`, `enforcement_order`, `dismissal`,
   `landlord_notice`, `rent_increase`, `operating_costs`) is not part of the model's `kind` vocabulary
   (since prompt version 9 the model names one in a field of its own, point 5). Code files
   a letter under one of them from the reading (`rules/routing.py`), one short written policy per kind in
   the module docstring; the person can change the kind on the letter's page, and a kind the person
   chose is kept when the letter is read again. An operating-cost statement is only recognised on read
   (its dates don't depend on its kind), never from a reminder about an old statement, and never against a
   kind the person chose for the letter.
2. **Court orders: three signals, no list of exceptions.** The sender is a court (its name names a kind of
   court, or abbreviates one before a place from a sender read as an authority or of no particular kind —
   a company whose name starts like "LG" or "AG" is none, nor a recipient typed in without its kind unless
   it gives the court's full name — though such a recipient may be one, so a letter people send to a court
   gets the court's channels, with e-mail allowed only "if it isn't a court"), the letter asks the person to answer it as the
   respondent (a *Widerspruch*/*Einspruch* remedy or an objection date), and it names the order (the
   title first, else the remedy). Later court letters about an order give the person no remedy, so they drop out without
   a list of "later letter" wordings, which kept growing and vetoing genuine orders.
3. **Structured parts before wording.** What a termination ends is decided by the contract it names,
   then the letter's kind, then the sender's kind (an employer ending a company flat's lease is a
   landlord's notice). Wording is read only where the reading has no structured field: whether a rent
   increase asks for consent, whether a notice is *fristlos* or gives notice *hilfsweise*, and a
   statement's billing period.
4. **Errors go to the safe side.** Where the wording parser is unsure, it keeps the to-do and offers the
   letter: a *fristlos* wording that is negated, reserved or far from its end counts as an ordinary notice
   (the objection to-do is kept), "außerordentlich" alone only as *probably* one (§ 573d BGB: the to-do
   and letter are kept), a notice with no end read counts back from the earliest permissible end, and
   any *hilfsweise* in the notice's own words counts as a notice in
   the alternative, even one that only reserves it (an objection is offered that may not be needed — and
   kept though the objection is excluded against it too when the grounds for the notice without notice
   period existed, BGH VIII ZR 323/18, which the card says); a statutory period ("mit gesetzlicher Frist",
   "with statutory notice") said of the notice itself makes it a special termination with the objection —
   never one that is denied ("without statutory notice") or belongs to the notice given in the alternative
   (after *hilfsweise*), which would turn a *fristlos* notice into an ordinary one. The late-statement check
   only calls a statement late when it certainly is, and never counts from a later letter's date: a date
   the letter gives a statement without its year may be the statement a later letter is about (a reply
   repeats the billing period too) or an enclosure's, so it never lets the statement be called late when
   it would make it on time; the card says both readings. Another year's statement's date never counts,
   and a named billing year gives way only to a range that says which months it covers — never to the
   tenant's own time in the flat or a cost item's service period (they would end it earlier: the harmful
   direction). A notice whose end is too early for its period (or a notice in the alternative with no end
   of its own) keeps an objection to-do, `low`, from the earliest end the law allows (§ 573c Abs. 1 BGB):
   such a notice usually ends the tenancy then.
5. **The prompt change was deferred, not dropped — and is done.** Extraction prompt version 9 lets the
   model name the letter kind itself (a `high_stakes_kind` field with these kinds); the rules check the
   model's answer where they read no kind of their own, and still decide where they do (see the update
   below).

## Consequences
- The recorded answers, the demo and the benchmark stay valid; every high-stakes kind is testable
  without a model call. Readings recorded before prompt version 9 name no kind of their own and are filed
  exactly as before.
- Accepted misses, documented in `routing.py`: a court named only in English and a court order whose
  reading has no remedy and no objection date (both filed under the kind the model names since prompt
  version 9; without one, under the model's ordinary kind — the person can change it); a club "SG …" or
  "VG Wort" read as an authority (or `other`) counts as a court (the safe side: earlier dates, never
  `high`); a later court letter whose reading gives the person an objection date anyway (filed as the
  order: the safe side for a two-week *Notfrist*); "Hilfsweise behalten wir uns eine ordentliche
  Kündigung vor" read as a notice in the alternative; a reply to objections about an old statement that
  names the statement in its title without dating it; an enclosure a statement dates with the statement's
  own year ("Heizkostenabrechnung 2024 der Techem vom …"), which is taken for the statement's date; a
  statement that dates its enclosure without the year is not called late with certainty, only "too late
  if this letter is the statement itself".
- When a review round finds a new counter-example in one of the wording rules, the fix follows ADR
  0007: prefer moving the error to the safe side (keep the to-do, show the caveat) over more clause
  parsing. The prompt field is in place (`high_stakes_kind`, version 9): a letter the rules read no kind
  from gets the model's, so a new counter-example there is fixed by a veto from the structured parts of
  the reading, never by another wording list.

## Update (extraction prompt version 9)
**Date:** 2026-09-29

Extraction prompt version 9 adds `high_stakes_kind` to the reading: the model names a court payment order,
an enforcement order, a dismissal, a landlord's notice, a rent increase request or an operating-cost
statement itself, else null (point 5). `routing.classify_letter` weighs it against the kind code reads, in
one short written policy (ADR 0007):

- **The model names none** — every reading recorded before version 9: code's kind, exactly as before. The
  demo, the recorded benchmark answers and every earlier test give the same kinds.
- **Code reads a kind:** code's, whether the model names the same one or another. Code's kind is the
  structured decision the review rounds checked; a disagreement is not worth a rule of its own.
- **Only the model names one:** the model's, unless the rest of the reading rules it out with the checks
  code already has, and no new wording lists — a court order whose sender is clearly no court (read as a
  company, a landlord, a bank … under a name that names no court, or a bailiff or a court cashier) or that
  is a European order for payment; a dismissal or a landlord's notice whose contract is of another category
  (a gym, a job ticket; a tenancy for a dismissal, a job for a landlord's notice), the contract deciding
  first as in point 3; a rent increase of a kind that needs no consent (graduated or index rent, a
  prepayment adjustment, a modernisation, "Zustimmung nicht erforderlich").
- **An operating-cost statement** is still recognised on read only (point 1): the model's `operating_costs`
  makes a reading one, with the vetoes of code's own recognition (a reminder, a utility or a public body),
  and never against a kind the person chose.
- **The kind the person chose** on the letter's page wins over both, also when the letter is read again.

Errors stay on the safe side (point 4): a veto only takes the model's kind away when the reading says the
letter is something else, and filing a letter under a kind that brings the law's deadlines is the safe
side of missing one.

When the model names the kind, it now covers these misses: a court named only in English; a court order
whose reading has no remedy and no objection date; a termination the reading doesn't record (no
termination by the other side); a rent increase request whose reading doesn't quote its consent wording
in German; a statement whose reading doesn't use the words code knows ("utility cost settlement"). Still
missed: all of these when the model names no kind either; and a labour court named only in English — its
order is filed from the model's kind, but code can't tell it is a labour court, so the law's to-do gives
the civil courts' two weeks rather than one week (when the reading has the letter's own one-week date, that
earlier date is the one filed).
