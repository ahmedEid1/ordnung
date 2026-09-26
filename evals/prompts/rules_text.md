<!-- version: 1 -->
VERIFIED GERMAN DEADLINE RULES (law as in force on 25 September 2026). Apply them exactly.

1. When a posted letter from a German authority counts as delivered (Bekanntgabefiktion)
- Posted on or after 1 January 2025: on the 4th day after posting. Posted on or before
  31 December 2024: on the 3rd day (PostModG). Count calendar days.
- The posting day is the date printed on the letter, unless the letter states a separate posting
  date ("zur Post gegeben am …", "Tag der Aufgabe zur Post"); then that stated day counts.
- Tax offices (Finanzamt; § 122 Abs. 2 Nr. 1 AO; also Kindergeld decisions of the Familienkasse):
  if the 4th day is a Saturday, Sunday or public holiday, the delivery day moves to the next working
  day (§ 108 Abs. 3 AO, BFH IX R 68/98). Example: posted Tue 15 Sep 2026 → Sat 19 Sep → delivered
  Mon 21 Sep 2026 → one-month objection period ends Wed 21 Oct 2026.
- All other authorities: the delivery day does NOT move, even if it is a Saturday, Sunday or
  holiday. This covers general authorities such as cities, district offices, immigration offices
  and universities (§ 41 Abs. 2 VwVfG and the Länder laws; the 4-day rule is confirmed for BY, NW,
  HH and MV from 1 Jan 2025, BW from 7 Feb 2025, SH at least from 10 Jun 2025, and BE, BB, NI, RP,
  SN and ST apply the federal law) and social-law bodies such as statutory health insurers
  (Krankenkassen), job centres, pension funds and the Familienkasse for Kinderzuschlag
  (§ 37 Abs. 2 SGB X; BSG B 14 AS 12/09 R). Example: posted Tue 15 Sep 2026 by a city →
  delivered Sat 19 Sep 2026 (not moved).
- Formal delivery (yellow envelope, Postzustellungsurkunde): the date written on the envelope is
  the delivery day; no days are added.

2. Counting a period (§§ 187, 188 BGB; the same arithmetic applies under § 108 Abs. 1 AO,
   § 31 Abs. 1 VwVfG, § 26 Abs. 1 SGB X, § 64 SGG and § 43 StPO)
- The day of the event that starts the period (delivery, the invoice date, the formal delivery)
  is not counted.
- Days: the period ends after that number of days. Weeks: on the same weekday n weeks later.
  Months: on the day with the same number n months later; if that month has no such day, on its
  last day (31 March + 1 month → 30 April). There is no end-of-month rule (30 April + 1 month →
  30 May).
- "Werktage" are Monday to Saturday; "Arbeitstage", "Geschäftstage" and business days are Monday to
  Friday — public holidays excluded in both. 24 and 31 December are working days.

3. When the last day of a period is a Saturday, Sunday or public holiday
- For objections (Einspruch, Widerspruch), court actions (Klage), payments and declarations or
  responses, the period ends on the next working day instead (§ 193 BGB, § 108 Abs. 3 AO,
  § 31 Abs. 3 VwVfG, § 26 Abs. 3 SGB X, § 64 Abs. 3 SGG, § 57 Abs. 2 VwGO with § 222 Abs. 2 ZPO,
  § 43 Abs. 2 StPO). Only the END of the period moves — never its start, and (outside tax law)
  never the deemed delivery day.
- Notice periods for cancelling a contract never move (BGH III ZR 172/04). Appointments never move.
  A calendar date printed in the letter is used as written.
- Public holidays: the nationwide ones always count (1 Jan, Good Friday, Easter Monday, 1 May,
  Ascension Day, Whit Monday, 3 Oct, 25 and 26 Dec). Regional ones count for the place where the
  obligation must be fulfilled: for objections and declarations, and for payments to an authority,
  the Land where the office sits (the Land named in the letterhead, otherwise the person's Land);
  for payments to a company or a person, the payer's own Land (§§ 269, 270 Abs. 4 BGB).
  Examples: 6 Jan (BW, BY, ST); Corpus Christi (BW, BY, HE, NW, RP, SL); 31 Oct
  Reformation Day (BB, HB, HH, MV, NI, SN, ST, SH, TH); 1 Nov All Saints' Day (BW, BY, NW, RP, SL);
  Repentance Day, Buß- und Bettag (SN); 8 Mar (BE, MV).

4. Typical statutory periods
- Tax objection (Einspruch): one month after the (deemed) delivery (§ 355 Abs. 1 AO).
- Objection to a decision of another authority or a social-law body (Widerspruch): one month after
  delivery (§ 70 VwGO, § 84 SGG). Court action (Klage): one month after delivery (§ 74 VwGO,
  § 87 SGG).
- Objection to a fine notice (Einspruch gegen einen Bußgeldbescheid): two weeks after formal
  delivery — the date on the yellow envelope (§ 67 OWiG, § 43 StPO).
- Private deadlines (invoices, landlords, employers, insurers, banks): as the letter states,
  counted from the stated start (e.g. the invoice date) under §§ 187, 188, 193 BGB.

5. Contracts
- A term that runs "from day X for n months" ends on the day before the same day number n months
  later (§ 187 Abs. 2, § 188 Abs. 2 BGB): from 1 Mar 2024 for 24 months → ends 28 Feb 2026.
- The last day to cancel for the end of a term is the latest day D such that D plus the notice
  period ends on or before the term end, counted backwards (term ends 30 Jun 2027 with three months'
  notice → 31 Mar 2027). It is never moved off weekends or holidays.
- Consumer contracts concluded from 1 Mar 2022: after the first term (at most 24 months) they run
  indefinitely and can be cancelled at any time with at most one month's notice (§ 309 Nr. 9 BGB;
  phone and internet: § 56 TKG). Insurance renews yearly; notice as written, at most three months
  before the end of the insurance year (§ 11 VVG).

6. Safety
- When something is uncertain, choose the earliest plausible date and say why in `warnings`.
- If the start of a period is unknown (e.g. "within 14 days of receipt" on a letter that carries
  no date), no reliable date exists: set `due_date` to null and explain.
