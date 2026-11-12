# Writer notes — newkinds split

Status: done — all six checks pass (2026-11-11 session) (see "Progress" at the end).

Reading day (today) 2026-11-24 (Tue); valid through 2026-12-01; letters posted / handed over 18–23.11.2026.
Days drawn with `rng_for("newkinds", case_id)` (posting day among Wed 18, Thu 19, Fri 20 Nov; the Widerruf letters among
18–21 Nov; the court orders then draw their Zustellung among the later days 19, 20, 21, 23 Nov).

Ids: `newkinds-<family>-<n>`, variant `"<n>"` (no template variants; newkinds is not in `SPLIT_VARIANTS`).
Families: mahnbescheid, vollstreckungsbescheid, kuendigung_arbeit, kuendigung_miete, mieterhoehung, betriebskosten,
widerruf. One scored item per letter for the first six kinds (24 letters); the Widerruf letters have no required item,
their withdrawal date is an optional item (c10). Photos: mahnbescheid-2, kuendigung_arbeit-2, kuendigung_miete-1,
betriebskosten-1 → 4 photos, 24 + 4 = 28 scored items counted over entries.

New conventions (CONVENTIONS_FINAL, after f01, f02 of holdout4):
- f03 (no): a private declaration handed over in person / put in the letterbox by messenger on a stated weekday morning
  reaches the addressee that day (§ 130 Abs. 1 S. 1 BGB).
- f04 (no): ZPO service: Zustellung day = the day the service note on the document states (§ 180 S. 3 ZPO); two weeks
  by § 222 Abs. 1 ZPO with §§ 187 Abs. 1, 188 Abs. 2 BGB, end moved by § 222 Abs. 2 ZPO.
- f05 (no): Mahnbescheid: label = end of the two weeks of § 692 Abs. 1 Nr. 3 ZPO; § 694 Abs. 1 ZPO gives no fixed date.
- f06 (no): § 4 S. 1 KSchG three weeks after receipt; ends generated on working days in every Land.
- f07 (yes): § 574b Abs. 2 BGB counted back from the lease end (§ 573c Abs. 1) to the month's last day where the lease
  ends on a month's last day; other reading: the same day number (28.02. → 28.12.).
- f08 (yes): § 558b Abs. 2 BGB consent period ends with the 2nd calendar month after the month of receipt, moved by
  § 193 BGB; other reading: not moved.
- f09 (yes): § 556 Abs. 3 S. 5 BGB: 12 months from receipt by §§ 187 Abs. 1, 188 Abs. 2 BGB, moved by § 193; other
  reading: end of the 12th calendar month after the month of receipt.
- f10 (no): late operating-cost statement: § 556 Abs. 3 S. 2, 3 BGB excludes the Nachforderung; the payment asked for is
  an optional item; the letters give no reason for being late.
- f11 (no): withdrawal: 14 days (§ 355 Abs. 2 BGB) from conclusion, or from receipt of the goods (§ 356 Abs. 2 Nr. 1 a),
  the information handed over on paper that day (§ 356 Abs. 3 S. 1); § 193 BGB moves the end.

## Entries (Land = where sender and recipient are; label in bold)

### mahnbescheid (kind dunning, also authority_letter; remedy widerspruch) — § 692 Abs. 1 Nr. 3, § 694 ZPO
- 1 (NW): issued Fri 20.11., served Mon 23.11. → +2 weeks **Mon 07.12.2026**.
- 2 (BY, photo): issued Wed 18.11., served Fri 20.11. → **Fri 04.12.2026**.
- 3 (NI): issued Thu 19.11., served Fri 20.11. → **Fri 04.12.2026**.
- 4 (HE): issued Thu 19.11., served Fri 20.11. → **Fri 04.12.2026**.

### vollstreckungsbescheid (kind authority_letter, also dunning; remedy einspruch) — §§ 700 Abs. 1, 339 Abs. 1 ZPO
- 1 (BW): issued Wed 18.11., served Fri 20.11. → **Fri 04.12.2026**.
- 2 (SN): issued Thu 19.11., served Mon 23.11. → **Mon 07.12.2026**.
- 3 (SH): issued Fri 20.11., served Mon 23.11. → **Mon 07.12.2026**.
- 4 (BE): issued Wed 18.11., served Mon 23.11. → **Mon 07.12.2026**.

### kuendigung_arbeit (kind employment; remedy klage) — § 4 KSchG; end of employment § 622 BGB (not scored)
- 1 (HH): handed over Thu 19.11.; probation, § 622 Abs. 3 two weeks → ends Thu 03.12.2026; **Thu 10.12.2026**.
- 2 (RP, photo): handed over Wed 18.11.; 6 years, § 622 Abs. 2 Nr. 2 → ends 31.01.2027; **Wed 09.12.2026**.
- 3 (TH): handed over Wed 18.11.; 9 years, Nr. 3 → ends 28.02.2027; **Wed 09.12.2026**.
- 4 (BB): handed over Thu 19.11.; 1 year 7 months, § 622 Abs. 1 (4 weeks to the 15th/month end) → ends 31.12.2026;
  **Thu 10.12.2026**.

### kuendigung_miete (kind rent_lease; remedy widerspruch) — § 573c Abs. 1, § 574b Abs. 2 BGB
Receipt after the 3rd Werktag of November (Wed 04.11.) and before that of December (Thu 03.12.) → notice for December.
- 1 (NW, photo): messenger Thu 19.11.; 3 years → ends 28.02.2027 → **Thu 31.12.2026** (f07 other: 28.12.2026; f02).
- 2 (BY): messenger Thu 19.11.; 6 years (+3 months) → ends 31.05.2027 → **Wed 31.03.2027**.
- 3 (HB): messenger Fri 20.11.; 11 years (+6 months) → ends 31.08.2027 → **Wed 30.06.2027**.
- 4 (MV): messenger Wed 18.11.; 2 years → ends 28.02.2027 → **Thu 31.12.2026** (other: 28.12.2026; f02).

### mieterhoehung (kind rent_lease, also price_increase) — §§ 558, 558a, 558b BGB
Every receipt in November → consent by end of January: Sun 31.01.2027 → § 193 **Mon 01.02.2027** (f08 other:
31.01.2027); new rent owed from 01.02.2027.
- 1 (BE): messenger Thu 19.11.  - 2 (HE): Wed 18.11.  - 3 (SL): Wed 18.11.  - 4 (NI): Fri 20.11.

### betriebskosten (kind rent_lease, also utility_bill) — § 556 Abs. 3 BGB
- 1 (BW, photo): period 2024, due 31.12.2025 (late); messenger Thu 19.11. → **Fri 19.11.2027** (other 30.11.2027);
  Nachzahlung asked by Tue 15.12.2026 (optional).
- 2 (ST): period 01.07.2024–30.06.2025, due 30.06.2026 (late); messenger Wed 18.11. → **Thu 18.11.2027** (other
  30.11.2027); Nachzahlung asked by Fri 11.12.2026 (optional).
- 3 (SH): period 2024, due 31.12.2025 (late), Guthaben; messenger Fri 20.11. → Sat 20.11.2027 → **Mon 22.11.2027**
  (other 30.11.2027).
- 4 (TH): period 01.10.2024–30.09.2025, due 30.09.2026 (late); messenger Wed 18.11. → **Thu 18.11.2027** (other
  30.11.2027); Nachzahlung asked by Fri 08.01.2027 (optional).

### widerruf (kind contract) — §§ 355, 356 BGB; optional item only
- 1 (HH): heat-pump service contract signed at home Fri 20.11. → **Fri 04.12.2026**.
- 2 (NW): electricity contract signed at the door Fri 20.11. (§ 356 Abs. 2 Nr. 2) → **Fri 04.12.2026**.
- 3 (BY): online furniture order delivered by the seller's own team Wed 18.11. (§ 356 Abs. 2 Nr. 1 a) → **Wed 02.12.2026**.
- 4 (BW): cleaning-service contract at a promotion stand in a shopping centre Sat 21.11. → Sat 05.12. → **Mon 07.12.2026**.

## Progress
- [x] law.py functions (appended at the end, existing functions untouched)
- [x] newkinds.py (all 28 letters one page; delivery note under the subject for private letters, a box for courts)
- [x] final.py (FAMILIES, f03–f11, KIND_ALSO_ACCEPTED_FINAL)  - [x] common.py (SPLITS_WITHOUT_VARIANTS)
- [x] tests (composition, senders; the old tests that assumed five splits now know ALL_SPLITS)
- [x] wording compared by difflib with every other split and the statute texts; close phrases reworded
- [x] VERIFICATION.md (two sections appended at the end; the text above them unchanged)
- [x] all six checks pass: 32 entries, 4 photos, 28 scored items over entries (24 in the letters)
