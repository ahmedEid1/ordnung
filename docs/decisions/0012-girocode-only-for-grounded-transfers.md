# ADR 0012 — A GiroCode only for grounded transfers, decided by a written policy

**Status:** accepted · **Date:** 2026-09-27

## Context
Paying a bill from a letter means typing a 22-character IBAN and a reference (a Kassenzeichen, an
invoice number) into a banking app. Typos misallocate payments, and a misallocated payment comes back
as a reminder with a fee. German banking apps scan the EPC QR code ("GiroCode", EPC069-12) and pre-fill
the transfer, so Ordnung can produce one for every payment it knows.

But a scanned value is not read the way a typed one is. A code built from a misread photo, from a
reference that belongs to another payment of the same letter, or from an attacker's letter that
imitates a known sender pre-fills exactly the wrong transfer — and looks authoritative doing it. The
existing scam checks only *warn*; a code would *help* pay.

## Decision
1. **The payload is the standard, nothing more lenient** (`ordnung/girocode.py`, pure): version 002,
   UTF-8, the BIC left empty only for accounts in the EEA, amounts as the standard writes them, an
   ISO 11649 RF reference structured only with valid check digits, free text on one line, at most 331
   bytes. Text that doesn't fit is refused, never shortened. Tests reproduce the standard's worked
   examples byte for byte, and a decoder reads the rendered QR back to the payload.
2. **Whether a payment gets a code is a written policy decided by code** (ADR 0007;
   `secretary/girocode_gate.py`): a transfer the person makes, still to pay, on a letter without scam
   signs (and with an IBAN no letter with scam signs asked for), not taken over by a reminder or by the
   bill attached to its e-mail, not one of several payments of the letter, complete and within the
   standard — and every value grounded
   (ADR 0003): the amount in a verified sentence, the IBAN in the text layer or known for the sender
   from another letter without scam signs, the whole reference in the text layer. Every refusal says
   why in plain words; the copy-by-hand fields stay.
3. **Photos need the person, and the person's check is bound to the values.** A value read by AI
   from a photo waits for "These match the letter". The confirmation records the exact payee, IBAN,
   reference and amount and holds only while they stay the same. It never overrides a scam sign, and
   it never teaches the sender's IBANs: a scam letter matches its own paper. Nothing else the person
   does to a to-do vouches for its amount: its `grounding="user"` comes from moving its date or
   "Correct" on a Please-check card, so it is about the date.
4. **Stored as an activity entry, not a schema change.** `PaymentDetails` is part of the model's
   extraction schema; a new field would change the prompt schema and invalidate every recorded answer
   (demo and benchmark). The confirmation is a `payment.checked` activity entry, which deleting the
   letter removes.
5. **Ordnung still never pays** (ADR 0006): the code only pre-fills; the bank app shows the details and
   asks for the TAN, and its verification of payee checks the name against the IBAN.

## Consequences
- The demo's utility statement and payment reminder get codes; the parking fine read from a photo asks
  for the paper first; the lease's monthly rent (next to its deposit, one reference) and the scam
  letter get none, with the reason shown.
- Reviewing the demo found a case the app's wording missed: the gym contract's sentence says
  "per SEPA-Lastschrift eingezogen" while its to-do reads like a transfer. The gate reads the quoted
  sentence too, so no code invites paying a direct debit twice; the app-wide wording is unchanged.
- The same check misread other letters, found in review: a returned debit ("Rücklastschrift … bitte
  überweisen Sie") read as a debit, while "eingezogen", "Bankeinzug" and "buchen … ab" didn't. The
  wording is one written list in `ordnung/payments.py` (mirrored by the web app for the to-do's
  words), with the returned debit and a transfer asked for as exceptions.
- The final review found that widening the list reached the whole app: a to-do whose own words said
  its debit failed ("konnte nicht eingezogen werden", "could not be debited") became "collected", lost
  its reminders and got "nothing to transfer"; a first rent "sobald Sie eingezogen sind" did too; and
  "Sofern Sie nicht am Lastschriftverfahren teilnehmen, überweisen Sie …" — stock wording on German
  bills — read as a debit because the negation of the debit's clause waved off the transfer. The
  failed debit is now an exception for the to-do's words as well; "einziehen" counts only in a clause
  that names the account or the money, and never among the to-do's words (nor do a mandate's
  reference and the creditor's ID, which a letter asking for a transfer after the mandate ended
  prints too); a negation waves off only a transfer in its own clause.
- The review of wave 2 found the failed-debit exception too wide the other way: any "returned" (a
  router to be returned) and stock warnings on direct-debit bills ("bei einer Rücklastschrift berechnen
  wir 3,00 € Gebühr", "a returned debit costs €3") made a debit a transfer — the to-do got "transfer by",
  reminders and a place in the Pay total, and with the same words in its sentence a code. Now a failure
  counts only as a fact about a debit (a debit named beside "returned" or "zurückgegeben"), never in a
  clause that is a condition or a price ("bei", "falls", "sollte", "if", "kostet", "costs" …), and in a
  letter's sentence a failure cancels only the debit of its own clause: a debit named in another clause
  still blocks the code. The same review found that an e-mail repeating its attached bill's payment got
  a code of its own (point 4 now covers it: pay once, from the bill).
- A utility statement asks for its back-payment and sets the new monthly advance (§ 560 Abs. 4 BGB):
  a recurring payment doesn't compete with a one-off one for its letter's reference, but gets a code
  only when its letter asks for no other transfer.
- Accepted limits (in the policy's docstring): a first letter from an unknown sender is checked only
  for look-alike names; a letter asking for several one-off payments gets no code even when its
  reference fits all of them, nor does a lease's rent next to its deposit; an account outside the EEA
  gets none because Ordnung reads no BICs; a letter wrongly flagged as a scam keeps its IBAN from
  codes until it is deleted for good — and, the other way round, a letter with scam signs that is
  deleted for good (the app's Delete) no longer blocks its IBAN on other letters, because Ordnung
  keeps nothing of a letter deleted for good (privacy.md, "Delete means delete"); a later letter asking
  for that account is then judged on its own, like a first letter from a new sender. Debit wording is
  matched, not understood. A payment without a reference gets a code without one, and the Pay panel
  says to add the letter's reference, if it names one, in the banking app.
- The static demo's codes are generated by the same code and point to the sample life's fictional
  accounts, so scanning a demo code never pre-fills a transfer to a real account.
