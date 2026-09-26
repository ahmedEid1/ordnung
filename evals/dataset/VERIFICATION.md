# Verification of the benchmark ground truth

Checked on 2026-09-25 against `evals/dataset/manifest.json` (generator `evals/generate.py`, holidays 0.105).
Re-run at any time:

```
.venv/bin/python evals/verify_labels.py          # exit code 0 = no problems
.venv/bin/python -m pytest tests/test_eval_dataset.py -q   # includes the same check
```

## Result

| | |
|---|---|
| Letters checked (text PDFs) | 76 (24 dev, 52 test incl. 10 adversarial) + 15 phone photos (4 dev, 11 test) |
| Non-null expected dates re-derived | **82** (67 required items, 7 optional items, 8 contract term-end / cancel-by dates) |
| Further dates re-derived | 2 second candidates of conflicting-date items, 4 price-change window dates, 4 ambiguous-date candidates |
| Date mismatches with the generator's arithmetic | **0** |
| Labels changed after review | 1 contract (legally contestable, see C1), 1 ambiguous item (weekday hint, see C6) |
| Other truth corrections | 3 references, 2 amounts, 6 document kinds, 1 remedy (C2–C5, C7) |
| Split corrections | 15 deadline sentences that recurred word for word in dev and test (C8) |
| After the fixes | 0 date, 0 text, 0 cross-split, 0 photo problems |

## Method

1. **Read every letter.** Text was pulled from each PDF with pdfplumber (page 2 as well: the Bußgeld
   Zustellung date is on the envelope scan). All 15 photos were checked by eye: the whole page is in
   frame and legible. Each photo belongs to a one-page PDF and has the same truth.
2. **Wrote down the facts by hand.** For each letter I noted the posting or letter date, any posting
   day stated separately, the Zustellung date, the period wording ("einen Monat", "14 Tagen",
   "10 Werktagen (Mo–Sa)", "zwei Wochen nach Zustellung", …), which law applies (AO / Land VwVfG /
   SGB X / OWiG / private law), and the Land if the letterhead names one. These facts are in
   `FACTS` in `evals/verify_labels.py`. The generator's `derivation` text was not used.
3. **Recomputed each date with separate code.** `evals/verify_labels.py` uses only `datetime` and
   the `holidays` package. It imports nothing from `evals/gen` and nothing from `ordnung.rules`.
   Weekdays and holidays were also checked by hand for every date that depends on them (see the
   list below). Letters that name no Land must give the same date under all 16 Land calendars.
   Letters that name a Land must have `region_sensitive` and `due_if_region_ignored` agree with a
   run that uses nationwide holidays only. No label may change when municipal-only holidays are
   counted (Mariä Himmelfahrt in parts of BY, Fronleichnam in parts of SN/TH).
4. **Checked the letters against the truth.** Every sender, document date, reference, amount,
   remedy word, stated date, anchor date, posting date and appointment time in the truth must
   appear in the PDF text. Letters whose truth says `remedy_type: none` must have no
   Rechtsbehelfsbelehrung. Invisible text may appear only in the two `hidden_text` letters.
   pdfplumber's colour and size data confirm the text there is white 1 pt on white. White text on
   coloured letterhead bands is visible and does not count. Every IBAN was run through the mod-97
   check: all are valid except the one in `adversarial-scam-2`, which is meant to be invalid. The
   Zählpunkt `DE000511…` in `price_increase-C1` is not an IBAN.
5. **Checked the splits.** Variant letters are A/B in dev, C/D in test, and adversarial letters are
   test only. Beyond that, no deadline-bearing sentence may appear verbatim in both a dev letter
   and a test letter (numbers are normalised before comparing).

### Legal rules applied

- **Deemed delivery** of a posted administrative act: the 3rd day after posting for items posted up
  to 2024-12-31, the 4th day from 2025-01-01. Sources: § 122 Abs. 2 Nr. 1 AO with Art. 97 § 1 Abs. 15
  EGAO; § 41 Abs. 2 VwVfG and the Land VwVfGs verified at 4 days (BY, BW from 7 Feb 2025, NW, HH,
  SH from 10 Jun 2025); § 37 Abs. 2 SGB X. The posting date is the letter date unless the letter
  names a posting day.
- **Only the AO moves the deemed-delivery day** off a Saturday, Sunday or holiday (§ 108 Abs. 3 AO,
  BFH IX R 68/98), using holidays at the tax office's seat. Under VwVfG and SGB X that day does not
  move (OVG NRW 19 A 4216/99, BSG B 14 AS 12/09 R).
- **One-month remedy periods** run under §§ 187 Abs. 1, 188 Abs. 2, 3 BGB. When the month has no
  matching day, the period ends on its last day (30.01. → 28.02.; 31.01. → 28.02.). The **end** moves
  to the next working day in every regime: § 108 Abs. 3 AO, § 31 Abs. 3 VwVfG, § 64 Abs. 3 SGG,
  § 57 Abs. 2 VwGO with § 222 Abs. 2 ZPO. The holidays are those of the Land where the authority or
  court sits.
- **Bußgeld Einspruch:** two weeks after the "zugestellt am" date on the envelope (§ 67 OWiG, § 43
  StPO). The same weekday two weeks later, then moved off Saturdays, Sundays and holidays.
- **Private-law periods:** §§ 187 Abs. 1, 188 Abs. 1 BGB, with § 193 BGB applied to the end.
  Werktage are Mon–Sat and Arbeitstage Mon–Fri, holidays excluded in both. 24 and 31 December are
  working days.
- **Contract terms** "from X for n months" end on the day before X in the last month (§ 187 Abs. 2,
  § 188 Abs. 2 Alt. 2 BGB). The notice deadline is the latest day D with D + notice ≤ term end. It
  is never moved (BGH III ZR 172/04).
- **Appointments** are never moved. The Saturday appointment in `appointment-D1` stays on Saturday.

Holidays that the labels depend on, checked by hand:

- Easter 2025 was 20.04. and Easter 2026 is 05.04. (Karfreitag 03.04.2026, Ostermontag 06.04.2026).
- 1 May, Christi Himmelfahrt 14.05.2026, Pfingstmontag 25.05.2026.
- Fronleichnam 19.06.2025 and 04.06.2026: a holiday in NW, BY and HE, not in HH.
- Heilige Drei Könige 06.01. in BY.
- Reformationstag 31.10. in NI, SN and HH.
- Buß- und Bettag 19.11.2025 in SN.
- Tag der Deutschen Einheit, Christmas and New Year.

## Findings and corrections

No expected date was arithmetically wrong. Eight labels depend on the named Land's holidays, and
all eight are correct:

- tax A1 (NW, Fronleichnam)
- tax C1 (NI, Reformationstag)
- tax D1 (BY, Heilige Drei Könige)
- municipal A1 (NW, Fronleichnam 2025)
- municipal B1 (BY, Heilige Drei Könige)
- social B1 (SN, Buß- und Bettag)
- fine C1 (NI, Reformationstag)
- fine D1 (BY, Fronleichnam)

So are the planned traps:

- the AO fiction day moving off 01.05., Karfreitag, Reformationstag, Pfingstmontag, 06.01. and 26.12.;
- the VwVfG / SGB X fiction day falling on a Saturday or holiday and staying put;
- Fronleichnam not being a holiday in Hamburg;
- a Bußgeld Zustellung on a Saturday;
- the old 3-day rule in December 2024;
- month ends in February.

Everything below was corrected in the generator (`evals/gen/*`), the dataset was regenerated, and
the check was run again until it reported nothing.

**C1 — `dev-contract_confirmation-B1`: label was legally contestable. Changed.**
The letter said "24 Monate ab Freischaltung". The contract was concluded on 12.06.2025 and
activated on 16.06.2025. That gives an end of 15.06.2027, which is 4 days beyond 24 months from
conclusion. Whether the 24-month cap in § 56 Abs. 1 TKG / § 309 Nr. 9 BGB counts from conclusion or
from activation is open (the BGH left it undecided). The project's own contract research says to
check the cap from the conclusion date and to flag this case. The minimum term is now **12 Monate
ab Freischaltung**, so both readings agree. The labels are now 2026-06-15 (term end) and 2026-05-15
(cancel-by); they were 2027-06-15 and 2027-05-15. `_contract_truth` now asserts that every
§ 309 / § 56 term fits within 24 months from conclusion.

**C2 — references that are not identifiers. Removed from the truth; the letters still print them.**
- `social_decision-C1`: "Ihr Zeichen: –"
- `social_decision-D2`: "Ihr Schreiben vom: 08.09.2025"
- `dunning_fixed-C2`: "Rechnung: Februar 2026"

A model that correctly leaves out a placeholder dash, a date or a billing month would have been
penalised. The fix is `common.identifier_references`.

**C3 — amounts missing under the dataset's own definition. Added.**
- `appointment-A1`: the passport fee "70,00 €" that the reader must bring
- `appointment-D1`: "Gebühr ca. 37,60 €"

The definition of `amounts` is now in the manifest `conventions`: sums the reader must pay, will
receive, or that the decision sets. It excludes line items, sums insured and penalties that are
only threatened, such as the Zwangsgeld in municipal A1 and the Ersatzvornahme costs in D2.

**C4 — document kinds with two honest answers. Added `kind_also_accepted`.**

| Letter | `kind` | Also accepted |
|---|---|---|
| `dunning_fixed-D1` (Hausverwaltung payment reminder) | rent_lease | dunning |
| `english_letter-C2` (serviced-apartment utility statement) | rent_lease | utility_bill |
| `invoice_relative-D1` (Stadtwerke final bill) | utility_bill | invoice |
| `appointment-C1` (immigration-office invitation) | residence_permit | appointment |
| `appointment-C2` (Jobcenter Meldeaufforderung) | social_insurance | appointment |
| `adversarial-scam-2` (fake Stadtwerke letter) | utility_bill | other |

The scorer should count `kind` or any entry in `kind_also_accepted` as correct.

**C5 — `adversarial-missing_date-2`: remedy contradicted the dataset's own NRW letters. Changed to Klage.**
The same NRW Ordnungsamt that says "Ein Widerspruchsverfahren findet nicht statt" in municipal A1
and D2 offered a Widerspruch here. That contradicts § 110 JustG NRW. The remedy is now Klage and
the label `remedy_type: klage`. The expected date stays null, because the letter carries no date.

**C6 — ambiguous numeric dates must really be ambiguous.**
`english_letter-D2` gave "03/05/2026" with the salutation "Dear Mr O'Connor:". The US colon hinted
at month/day. The day/month reading, 3 May 2026, is also a Sunday. Both hints point the same way, so
the item was not honestly ambiguous. The date is now **03/06/2026** (Fri 6 March or Wed 3 June; both
are working days after "today"), and the salutation ends with a comma. `english_letter-B1`
(07/08/2026: Wed 8 July or Fri 7 August, letter date 05/05/2026) was already sound. For both
letters, the derivation text now says "no reliable locale hint (a German sender writing English)"
instead of "no hint". The checker now requires both readings of an ambiguous date to be plausible
working days.

**C7 — `adversarial-missing_date-1/-2` and `conflicting_dates-1/-2` checked, no change.**
Neither missing-date letter has a date anywhere, so neither can be dated. In missing_date-1 the
work date 12.08.2026 is not the anchor. In both conflicting-date letters the label is the earlier
candidate, as SPEC §21 requires ("earliest plausible"):
- conflicting_dates-1: 13.05. in the text against 20.05. in the summary box;
- conflicting_dates-2: the header date 12.03. gives Thu 16.04. and "Bescheid vom 16.03." gives Mon 20.04.

The injection and scam labels are also right:
- The visible and hidden instructions do not change any real deadline.
- Scam payments are optional items with a `scam` warning.
- Hidden text appears only in the two `hidden_text` letters.

**C8 — wording shared between dev and test. Rewritten.**
The dev variants (A, B) and the test variants (C, D) were meant to use different wording, but 15
deadline-bearing sentences appeared word for word in both splits. Prompts tuned on dev would
already have seen the test deadline sentences. The shared sentences were:

- the Bußgeld Rechtsbehelfsbelehrung and the payment sentence (A↔C and B↔D, in all six fines);
- the municipal Widerspruch and Klage Belehrung (B↔D1 and A↔D2);
- the SGB X Belehrung (social A↔C and B↔D; municipal C also reused social A's wording);
- four adversarial letters (conflicting_dates-2, hidden_text-1, injection_visible-2, missing_date-2)
  that reused the dev variant-A Widerspruch Belehrung;
- the tax variant-A Belehrung in `adversarial-injection_visible-1`.

Weaker shared phrases also showed up:

- dunning "Bitte überweisen Sie den Betrag bis zum …" (A↔C1);
- English "within 30 days of the date of this letter" (A1↔C2);
- invoice "Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum" (A1↔adversarial);
- year-boundary D reusing the opening of social A.

The C and D variants and the adversarial letters now have their own wording. Only short statutory
phrases still appear in both splits, such as "vierten Tag nach Aufgabe zur Post". This is now tested
(`shared_dev_test_sentences` must be empty). None of these edits changed a date. The key phrases
were updated to the new wording.

## Judgement calls kept on purpose (documented, not changed)

- **A stated posting day is the anchor** (tax B1: Bescheid 26.03., posted 30.03.; tax D1: Bescheid
  31.12.2025, posted 02.01.2026). The labels 07.05.2026 and 09.02.2026 are the legal dates,
  because § 122 Abs. 2 AO counts from "Aufgabe zur Post". `docs/deadline-rules.md` says Ordnung
  keeps the earlier letter date and shows the later date as a note. By design, Ordnung will
  therefore answer 30.04.2026 and 05.02.2026. The scorer should record this as an *early (safe)*
  deviation, not as a hit and not as a late error.
- **VwVfG / SGB X deemed-delivery day never moves.** This is the prevailing case law, but the
  literature disputes it for VwVfG. It matters for:
  - municipal B1 (fiction day Sat 06.12.2025)
  - municipal C1 (Sat 03.10.2026)
  - municipal D2 (Sat 27.12.2025)
  - social A1 (Karfreitag)
  - social C2 (Pfingstmontag)
  - adversarial injection_visible-2 (Sunday)

  In every one of these cases the label is the earlier, safe reading.
- **`remedy_type` follows the letter's own Rechtsbehelfsbelehrung.** Whether a Bavarian authority
  should have offered Widerspruch (Art. 12 AGVwGO) was not judged.
- **Klage labels** (municipal A1, D2) carry the legal date, although Ordnung shows a "get advice"
  card for Klage (SPEC §21).
- **Price-increase items are optional.** "Cancel before the change" is the effective date minus
  one day. The § 57 TKG window from the letter date is a lower bound ("at the earliest"), because
  the date of receipt is unknown.
- **Holiday data source.** The generator (`evals/gen/law.py`) and this checker both depend on the
  statutory Land holiday calendar. The generator cross-checks its own tables against the holidays
  package; this checker uses the package directly. The two share the data source but no code. The
  holidays that matter were checked by hand (list above).

## Not date-scored (deliberately excluded)

- 2 ambiguous items (English B1, D2), whose expected value is "ambiguous" with 2 candidates.
- 2 missing-date items (adversarial missing_date-1, -2), whose expected value is null.
- 7 optional undated items: six "zahlbar zwei Wochen nach Rechtskraft" payments on Bußgeld letters,
  and one "drei Wochen nach Bestandskraft" task in hidden_text-1. Their dates depend on whether an
  objection is filed.
