"""Catalog of every legal rule the engine applies, with citation, official link and effective date.

Rule ids are stable: they are stored in receipts (``ComputationReceipt.rule_ids``) and shown in the
"How dates are computed" screen. Every id used anywhere in ``ordnung.rules`` must be listed here (a
test enforces it). Wording is plain English; German terms appear in parentheses.
"""

from __future__ import annotations

from ordnung.models import RuleInfo

#: Date on which the rules and links below were last checked against the law.
LAST_CHECKED = "2026-09-25"

_GII = "https://www.gesetze-im-internet.de"
_DEJURE = "https://dejure.org/dienste/vernetzung/rechtsprechung"


def _court(court: str, day: str, docket: str) -> str:
    return f"{_DEJURE}?Gericht={court}&Datum={day}&Aktenzeichen={docket.replace(' ', '+')}"


# (id, title, citation, summary, url, effective_from)
_RULES: list[tuple[str, str, str, str, str | None, str | None]] = [
    # ------------------------------------------------------------------ periods & calendar
    (
        "bgb_187_1",
        "The day of the event is not counted",
        "§ 187 Abs. 1 BGB; § 108 Abs. 1 AO; § 31 Abs. 1 VwVfG; § 26 Abs. 1 SGB X",
        "When a period starts with an event (a letter arriving, a delivery), that day is not counted; "
        "counting starts the next day.",
        f"{_GII}/bgb/__187.html",
        None,
    ),
    (
        "bgb_187_2",
        "Periods that start at the beginning of a day",
        "§ 187 Abs. 2 BGB",
        "When a period starts at the beginning of a day (e.g. a contract term 'from 1 March'), that "
        "first day counts.",
        f"{_GII}/bgb/__187.html",
        None,
    ),
    (
        "bgb_188",
        "When a period ends",
        "§ 188 Abs. 1, 2 BGB; § 43 Abs. 1 StPO; § 64 Abs. 2 SGG",
        "A period in days ends on its last day. A period in weeks, months or years ends on the day with "
        "the same weekday name or day number as the event day (or, for periods starting at the "
        "beginning of a day, on the day before it).",
        f"{_GII}/bgb/__188.html",
        None,
    ),
    (
        "bgb_188_3",
        "Shorter months",
        "§ 188 Abs. 3 BGB",
        "If the last month has no day with that number (e.g. 31 January + 1 month), the period ends on "
        "the last day of that month. There is no end-of-month rule: 30 April + 1 month is 30 May.",
        f"{_GII}/bgb/__188.html",
        None,
    ),
    (
        "bgb_193",
        "Weekend and holiday shift (private law)",
        "§ 193 BGB",
        "If a deadline for a declaration or a payment ends on a Saturday, Sunday or public holiday at the "
        "place of performance, it moves to the next working day.",
        f"{_GII}/bgb/__193.html",
        None,
    ),
    (
        "ao_108_3",
        "Weekend and holiday shift (tax)",
        "§ 108 Abs. 3 AO",
        "A tax deadline that ends on a Saturday, Sunday or public holiday ends on the next working day.",
        f"{_GII}/ao_1977/__108.html",
        None,
    ),
    (
        "vwvfg_31_3",
        "Weekend and holiday shift (authorities)",
        "§ 31 Abs. 3 VwVfG; § 57 Abs. 2 VwGO with § 222 Abs. 2 ZPO",
        "A deadline towards an authority that ends on a Saturday, Sunday or public holiday ends on the "
        "next working day (unless the authority expressly excluded this when naming a fixed date).",
        f"{_GII}/vwvfg/__31.html",
        None,
    ),
    (
        "sgbx_26_3",
        "Weekend and holiday shift (social law)",
        "§ 26 Abs. 3 SGB X; § 64 Abs. 3 SGG",
        "A social-law deadline that ends on a Saturday, Sunday or public holiday ends on the next "
        "working day.",
        f"{_GII}/sgb_10/__26.html",
        None,
    ),
    (
        "stpo_43",
        "Week periods in fine and criminal proceedings",
        "§ 43 StPO (with § 46 Abs. 1 OWiG)",
        "A period of weeks ends on the same weekday as the delivery day; a Saturday, Sunday or holiday "
        "end moves to the next working day.",
        f"{_GII}/stpo/__43.html",
        None,
    ),
    (
        "holidays_place",
        "Which public holidays count",
        "§ 193 BGB; §§ 269, 270 Abs. 4 BGB; BAG 8 AZN 808/11; BGH VI ZA 27/11",
        "Holidays count at the place where the declaration must be received (the authority's or "
        "company's seat); for money owed to a company or person, at the payer's home (the place of "
        "performance for money debts). Ordnung uses the regional holidays only when that region is known, "
        "otherwise only nationwide holidays, which can only make a date earlier. 24 and 31 December are "
        "not public holidays.",
        "https://www.bundesarbeitsgericht.de/entscheidung/8-azn-808-11/",
        None,
    ),
    (
        "unit_business_days",
        "Counting business days",
        "§ 193 BGB (Saturday, Sunday and public holidays are not working days)",
        "Business days are Monday to Friday, excluding public holidays.",
        f"{_GII}/bgb/__193.html",
        None,
    ),
    (
        "unit_werktage",
        "Counting working days (Werktage)",
        "BGH VIII ZR 206/04",
        "Werktage are Monday to Saturday, excluding public holidays: in legal language Saturday is a "
        "Werktag.",
        _court("BGH", "27.04.2005", "VIII ZR 206/04"),
        None,
    ),
    (
        "notice_no_shift",
        "Notice periods never move to Monday",
        "BGH III ZR 172/04 (NJW 2005, 1354)",
        "§ 193 BGB does not apply to notice periods (Kündigungsfristen): a notice that must arrive by a "
        "Saturday must arrive by that Saturday, otherwise it only works for the next possible end date.",
        _court("BGH", "17.02.2005", "III ZR 172/04"),
        None,
    ),
    (
        "authority_deadline",
        "Deadlines and appointments set by an authority",
        "§ 108 Abs. 2, 3, 5 AO; § 31 Abs. 2, 3, 5 VwVfG; § 26 Abs. 2, 3, 5 SGB X",
        "A deadline an authority sets also moves off a Saturday, Sunday or holiday (under VwVfG and SGB "
        "X unless the letter expressly excludes this). Appointments (Termine) keep their date.",
        f"{_GII}/vwvfg/__31.html",
        None,
    ),
    (
        "date_as_written",
        "Dates stated in the letter",
        "The document's own wording",
        "A calendar date given in the letter is used as written. Appointments never move.",
        None,
        None,
    ),
    (
        "backward_no_shift",
        "Periods counted backwards never move later",
        "§ 193 BGB; Ordnung safety policy",
        "§ 193 BGB only extends a period that runs forward to its end. A deadline counted backwards from "
        "an event ('pay one month before the course starts') never moves to a later day; if it falls on a "
        "weekend or holiday, Ordnung also shows the working day before it as the safe date.",
        f"{_GII}/bgb/__193.html",
        None,
    ),
    (
        "safe_date",
        "Safe date",
        "Ordnung safety policy",
        "When a notice deadline falls on a weekend or holiday, Ordnung also shows the working day "
        "before it, because post and offices may not process it on the day itself.",
        None,
        None,
    ),
    (
        "postal_buffer",
        "Send-by date",
        "Ordnung safety policy; § 18 PostG (delivery targets)",
        "Deadlines are about when a letter arrives, not when it is sent. The post must deliver 95 % of "
        "letters by the 3rd and 99 % by the 4th working day after posting, so Ordnung suggests posting 4 "
        "business days before the last business day on or before the deadline (0 for online buttons, "
        "portals, fax and e-mail where allowed).",
        None,
        None,
    ),
    (
        "bgb_675s",
        "Bank transfers take up to one business day",
        "§ 675s Abs. 1 BGB",
        "A transfer must reach the payee's bank by the end of the next business day (one more for paper "
        "forms). Consumers usually pay on time if they order it by the due date (BGH VIII ZR 222/15), but "
        "tax payments count on the day of credit (§ 224 Abs. 2 AO), so Ordnung suggests ordering one "
        "bank business day early (banks don't process transfers on 24 and 31 December).",
        f"{_GII}/bgb/__675s.html",
        None,
    ),
    # ------------------------------------------------------------------ deemed delivery
    (
        "ao_122_2_1",
        "Tax letters: delivered on the 4th day after posting",
        "§ 122 Abs. 2 Nr. 1 AO; Art. 97 § 1 Abs. 15 EGAO (PostModG)",
        "A tax decision sent by post within Germany counts as delivered on the 4th day after it was "
        "posted (3rd day for letters posted before 2025). Arriving earlier changes nothing.",
        f"{_GII}/ao_1977/__122.html",
        "2025-01-01",
    ),
    (
        "ao_122_2_2",
        "Tax letters sent abroad: one month",
        "§ 122 Abs. 2 Nr. 2 AO",
        "A tax decision posted to an address abroad counts as delivered one month after posting.",
        f"{_GII}/ao_1977/__122.html",
        None,
    ),
    (
        "ao_122_2a",
        "Tax decisions sent electronically: 4th day",
        "§ 122 Abs. 2a AO",
        "A tax decision sent electronically counts as delivered on the 4th day after sending (3rd day "
        "before 2025).",
        f"{_GII}/ao_1977/__122.html",
        "2025-01-01",
    ),
    (
        "ao_122a_4",
        "Tax decisions in ELSTER: 4th day after provision",
        "§ 122a Abs. 4 AO",
        "A tax decision made available for download (Mein ELSTER) counts as delivered on the 4th day "
        "after it was made available (decisions issued from 2026). For decisions issued in 2025 the 4th day "
        "after the notification e-mail counts, before 2025 the 3rd day.",
        f"{_GII}/ao_1977/__122a.html",
        "2025-01-01",
    ),
    (
        "ao_fiction_shift",
        "Tax delivery day moves off weekends and holidays",
        "BFH IX R 68/98; § 108 Abs. 3 AO; AEAO zu § 108 Nr. 2",
        "In tax matters, if the 4th day is a Saturday, Sunday or public holiday (at the recipient's "
        "place), delivery moves to the next working day.",
        _court("BFH", "14.10.2003", "IX R 68/98"),
        None,
    ),
    (
        "vwvfg_41_2",
        "Authority letters: delivered on the 4th day, no weekend shift",
        "§ 41 Abs. 2 VwVfG (and the Länder VwVfGs); OVG NRW 19 A 4216/99",
        "A decision of a general authority (e.g. the immigration office) sent by post or electronically "
        "counts as delivered on the 4th day after sending (3rd before 2025). Under the prevailing case "
        "law that day does not move off a weekend; only the end of the objection period does.",
        f"{_GII}/vwvfg/__41.html",
        "2025-01-01",
    ),
    (
        "vwvfg_land_days",
        "Authorities of the Länder: 4 days where confirmed",
        "§ 41 Abs. 2 of the Länder VwVfGs (e.g. Art. 41 BayVwVfG; § 102b LVwVfG BW)",
        "Most Länder moved to the 4-day rule in 2025 (confirmed for BY, NW, HH, MV from 1 January, BW from "
        "7 February and SH at least from 10 June 2025; BE, BB, NI, RP, SN and ST follow the federal law). "
        "For Hessen, Bremen, Saarland and Thüringen, or when the Land is unknown, Ordnung uses the "
        "earlier 3rd day.",
        f"{_GII}/vwvfg/__41.html",
        "2025-01-01",
    ),
    (
        "vwvfg_41_2a",
        "Authority portals: day after download",
        "§ 41 Abs. 2a VwVfG",
        "A decision made available in a portal counts as delivered on the day after it was downloaded. "
        "Unless you tell Ordnung the download day, it uses the day after the decision was made available "
        "(the earliest possible download).",
        f"{_GII}/vwvfg/__41.html",
        None,
    ),
    (
        "sgbx_37_2",
        "Social-law letters: delivered on the 4th day, no weekend shift",
        "§ 37 Abs. 2 SGB X; BSG B 14 AS 12/09 R",
        "A decision of a health insurer, job centre or pension fund sent by post or electronically counts "
        "as delivered on the 4th day after sending (3rd before 2025), even on a weekend.",
        f"{_GII}/sgb_10/__37.html",
        "2025-01-01",
    ),
    (
        "sgbx_37_2a",
        "Social-law portals: 4th day after the notification",
        "§ 37 Abs. 2a SGB X",
        "A decision made available for download counts as delivered on the 4th day after the "
        "notification about it was sent.",
        f"{_GII}/sgb_10/__37.html",
        "2025-01-01",
    ),
    (
        "posting_day",
        "The posting day",
        "§ 122 Abs. 2 AO; § 41 Abs. 2 VwVfG; § 37 Abs. 2 SGB X; BFH II R 52/07",
        "Deemed delivery counts from the day the letter was handed to the post. Unless a posting date is "
        "stated, Ordnung uses the date printed on the letter: the real posting day can only be the same "
        "day or later, so the computed deadline is never too late.",
        f"{_GII}/ao_1977/__122.html",
        None,
    ),
    (
        "delivery_scope_unknown",
        "Unknown kind of sender",
        "Ordnung safety policy (earliest plausible delivery day)",
        "When Ordnung cannot tell which procedural law applies to the sender, it uses the 3rd day after "
        "posting (the 4th only where the sender's Land is known to use the 4-day rule) without the weekend "
        "shift, which gives the earliest plausible date.",
        None,
        None,
    ),
    (
        "private_sender_arrival",
        "Letters from companies count from arrival",
        "§ 130 Abs. 1 BGB",
        "Deemed delivery (the 4-day rule) applies only to letters from authorities. A letter from a "
        "company, landlord, bank or other private sender takes effect when it arrives, so a period in it "
        "runs from that day. Without the day it arrived, Ordnung counts from the letter's date, the "
        "earliest plausible start.",
        f"{_GII}/bgb/__130.html",
        None,
    ),
    (
        "private_sender_late_arrival",
        "Arriving late: the earlier, safe start",
        "§ 130 Abs. 1 BGB; Ordnung safety policy (earliest plausible date)",
        "Whether a sender is an authority is read from its letter, not known: a public body's Bescheid "
        "may come from a sender filed as a company, an insurer, a utility or an employer, or name itself "
        "in its own words. When such a letter arrived later than a letter usually counts as delivered "
        "(the 3rd or 4th day after posting), Ordnung counts from that earlier day. The later arrival "
        "counts once it can be shown — for a private sender's letter and an authority's alike — and the "
        "warning gives the date from the day it arrived.",
        f"{_GII}/bgb/__130.html",
        None,
    ),
    (
        "private_sender_no_delivery",
        "Letters from companies: no delivery days",
        "§ 187 Abs. 1 BGB",
        "Deemed delivery (the 4-day rule) applies only to letters from authorities. When a company's, "
        "landlord's or other private sender's letter counts a period from its own date or another date it "
        "names, no delivery days are added: the period runs from that date, whenever the letter arrived.",
        f"{_GII}/bgb/__187.html",
        None,
    ),
    (
        "early_receipt",
        "Arriving early changes nothing",
        "BFH X R 96/98; BSG B 14 AS 12/09 R; BVerwG 6 C 3.22",
        "If a letter arrives before its deemed delivery day, the deemed day still counts.",
        _court("BFH", "13.12.2000", "X R 96/98"),
        None,
    ),
    (
        "late_receipt",
        "Arriving late may help — if you can show it",
        "§ 122 Abs. 2 AO; § 41 Abs. 2 S. 3 VwVfG; § 37 Abs. 2 S. 3 SGB X; BFH VI R 18/22",
        "If a letter really arrived after its deemed delivery day, the actual day counts, but you may "
        "have to show it (keep the envelope). Ordnung keeps the earlier, safe date.",
        _court("BFH", "20.02.2025", "VI R 18/22"),
        None,
    ),
    (
        "pzu",
        "Formal delivery with a yellow envelope",
        "§ 3 VwZG with §§ 177–182 ZPO",
        "With a Postzustellungsurkunde (yellow envelope) the delivery date written on the envelope "
        "counts; there is no 4-day rule.",
        f"{_GII}/vwzg_2005/__3.html",
        None,
    ),
    # ------------------------------------------------------------------ remedies
    (
        "ao_355",
        "Tax objection (Einspruch): one month",
        "§ 355 Abs. 1 AO; § 357 AO",
        "An objection against a tax decision must reach the tax office within one month after delivery.",
        f"{_GII}/ao_1977/__355.html",
        None,
    ),
    (
        "vwgo_70",
        "Objection to an authority (Widerspruch): one month",
        "§ 70 Abs. 1 VwGO",
        "An objection must reach the authority within one month after delivery, in writing or for the "
        "record; a plain e-mail is not enough.",
        f"{_GII}/vwgo/__70.html",
        None,
    ),
    (
        "sgg_84",
        "Objection in social law (Widerspruch): one month",
        "§ 84 Abs. 1 SGG",
        "An objection against a health insurer's or job centre's decision must be filed within one "
        "month after delivery (three months if delivered abroad).",
        f"{_GII}/sgg/__84.html",
        None,
    ),
    (
        "klage_1_month",
        "Court action (Klage): one month",
        "§ 74 VwGO; § 47 FGO; § 87 SGG",
        "A court action must be filed within one month. Ordnung shows the date only so it is not missed, "
        "with a 'get advice' warning and lowered confidence; it never drafts court actions.",
        f"{_GII}/vwgo/__74.html",
        None,
    ),
    (
        "owig_67",
        "Objection to a fine (Einspruch gegen Bußgeldbescheid): two weeks",
        "§ 67 Abs. 1 OWiG; § 43 StPO",
        "An objection must reach the fine authority within two weeks after formal delivery (the date "
        "on the yellow envelope; for an Übergabe-Einschreiben the 4th day after posting, § 4 Abs. 2 VwZG), "
        "in writing or for the record. Without the envelope date Ordnung counts from the letter's date.",
        f"{_GII}/owig_1968/__67.html",
        None,
    ),
    (
        "stpo_410",
        "Objection to a penal order (Strafbefehl): two weeks",
        "§ 410 Abs. 1 StPO; § 43 StPO",
        "An objection must reach the court within two weeks after delivery. Get legal advice.",
        f"{_GII}/stpo/__410.html",
        None,
    ),
    (
        "owig_55",
        "Hearing form (Anhörungsbogen): no legal deadline",
        "§ 55 OWiG",
        "The reply date on a hearing form is a request, not a legal deadline. You must give your personal "
        "details; you may stay silent on the accusation.",
        f"{_GII}/owig_1968/__55.html",
        None,
    ),
    (
        "rbb_one_year",
        "Missing or wrong instructions on how to object: one year",
        "§ 356 Abs. 2 AO; § 58 Abs. 2 VwGO; § 66 Abs. 2 SGG",
        "If the instructions on how to object are missing or wrong, the objection can be filed within one "
        "year. Whether they are wrong is a legal judgement, so Ordnung only shows this as a warning.",
        f"{_GII}/ao_1977/__356.html",
        None,
    ),
    # ------------------------------------------------------------------ contracts
    (
        "bgb_309_9_new",
        "Consumer contracts from March 2022",
        "§ 309 Nr. 9 BGB; Art. 229 § 60 EGBGB",
        "For consumer contracts concluded from 1 March 2022: a first term of at most two years, notice "
        "of at most one month before its end, and after that the contract only continues indefinitely "
        "and can be cancelled at any time with at most one month's notice.",
        f"{_GII}/bgb/__309.html",
        "2022-03-01",
    ),
    (
        "bgb_309_9_old",
        "Consumer contracts before March 2022",
        "§ 309 Nr. 9 BGB (version until 28 Feb 2022)",
        "For consumer contracts concluded before 1 March 2022: a first term of at most two years, "
        "automatic renewals of at most one year and notice of at most three months.",
        f"{_GII}/bgb/__309.html",
        None,
    ),
    (
        "tkg_56",
        "Phone and internet contracts",
        "§ 56 Abs. 1, 3 TKG",
        "A first term of at most 24 months; after it the contract continues indefinitely and can be "
        "cancelled at any time with one month's notice.",
        f"{_GII}/tkg_2021/__56.html",
        "2021-12-01",
    ),
    (
        "vvg_11",
        "Insurance contracts",
        "§ 11 VVG",
        "Insurance renews for at most one year at a time; notice must be between one and three months "
        "before the end of the insurance year.",
        f"{_GII}/vvg_2008/__11.html",
        None,
    ),
    (
        "sgbv_175",
        "Statutory health insurance",
        "§ 175 Abs. 4 SGB V",
        "You are bound to your health insurer for 12 months; after that a switch takes effect at the end "
        "of the second calendar month after the month in which you give notice.",
        f"{_GII}/sgb_5/__175.html",
        None,
    ),
    (
        "stromgvv_20",
        "Basic energy supply (Grundversorgung)",
        "§ 20 Abs. 1 StromGVV; § 20 Abs. 1 GasGVV",
        "A basic supply contract can be cancelled at any time with two weeks' notice, in text form.",
        f"{_GII}/stromgvv/__20.html",
        None,
    ),
    (
        "bgb_573c",
        "Tenant's notice on a flat",
        "§ 573c Abs. 1, 4 BGB; BGH VIII ZR 206/04",
        "A tenant's notice must arrive by the 3rd working day (Werktag, Saturday counts) of a month to "
        "end the tenancy at the end of the month after next.",
        f"{_GII}/bgb/__573c.html",
        None,
    ),
    (
        "bgb_622",
        "Employee's notice",
        "§ 622 Abs. 1, 3, 6 BGB",
        "An employee can give four weeks' notice to the 15th or to the end of a calendar month (two "
        "weeks during an agreed probation period), unless the contract sets a longer period.",
        f"{_GII}/bgb/__622.html",
        None,
    ),
    (
        "fixed_term",
        "Fixed-term contracts end by themselves",
        "§ 542 Abs. 2 BGB; § 620 Abs. 1 BGB; § 15 Abs. 1 TzBfG",
        "A contract agreed for a fixed period ends on its end date without notice.",
        f"{_GII}/bgb/__620.html",
        None,
    ),
    (
        "contract_as_written",
        "Contract terms as written",
        "The contract's own terms",
        "When no special consumer rule applies, Ordnung uses the term and notice period written in the "
        "contract.",
        None,
        None,
    ),
    # ------------------------------------------------------------------ sending & form
    (
        "bgb_130",
        "Declarations count when they arrive",
        "§ 130 Abs. 1 BGB",
        "A cancellation or objection takes effect when it reaches the other side, not when you send it.",
        f"{_GII}/bgb/__130.html",
        None,
    ),
    (
        "bgb_312k",
        "Online cancellation button",
        "§ 312k BGB",
        "If you could sign up for a contract on a website, the company must offer a 'cancel contracts "
        "here' button there.",
        f"{_GII}/bgb/__312k.html",
        "2022-07-01",
    ),
    (
        "bgb_309_13",
        "Text form is enough for cancellations",
        "§ 309 Nr. 13 BGB",
        "Standard terms cannot require more than text form (e.g. e-mail) for notices in most consumer "
        "contracts.",
        f"{_GII}/bgb/__309.html",
        "2016-10-01",
    ),
    (
        "bgb_568",
        "Tenancy notice needs a signature",
        "§ 568 Abs. 1 BGB; § 126 BGB",
        "Notice on a flat must be in writing with a handwritten signature; e-mail, fax or text message "
        "is not enough.",
        f"{_GII}/bgb/__568.html",
        None,
    ),
    (
        "bgb_623",
        "Employment notice needs a signature",
        "§ 623 BGB; § 126 BGB",
        "Notice of employment must be in writing with a handwritten signature; electronic form is excluded.",
        f"{_GII}/bgb/__623.html",
        None,
    ),
    (
        "ao_357",
        "How to file a tax objection",
        "§ 357 Abs. 1 AO",
        "A tax objection can be filed in writing, electronically (ELSTER or e-mail) or in person for the "
        "record.",
        f"{_GII}/ao_1977/__357.html",
        None,
    ),
    # ------------------------------------------------------------------ price increases
    (
        "enwg_41_5",
        "Energy price increase: cancel when it takes effect",
        "§ 41 Abs. 5 EnWG; § 5 Abs. 3 StromGVV",
        "Households must be told about a price change at least one month in advance and may then cancel "
        "without notice, effective when the change takes effect.",
        f"{_GII}/enwg_2005/__41.html",
        None,
    ),
    (
        "tkg_57",
        "Phone or internet price increase: three months to cancel",
        "§ 57 Abs. 1, 2 TKG",
        "After a one-sided contract change you can cancel without notice within three months of being "
        "told; the contract ends at the earliest when the change takes effect.",
        f"{_GII}/tkg_2021/__57.html",
        "2021-12-01",
    ),
    (
        "vvg_40",
        "Insurance premium increase: one month to cancel",
        "§ 40 Abs. 1 VVG",
        "If the premium rises without more cover, you can cancel within one month of being told, "
        "effective at the earliest when the increase applies.",
        f"{_GII}/vvg_2008/__40.html",
        None,
    ),
    (
        "sgbv_175_4_zb",
        "Health insurance contribution increase",
        "§ 175 Abs. 4 S. 5, 6 SGB V",
        "If your health insurer raises its additional contribution, you can switch insurer until the end "
        "of the month for which the higher rate is first charged.",
        f"{_GII}/sgb_5/__175.html",
        None,
    ),
]

RULES: dict[str, RuleInfo] = {
    rid: RuleInfo(
        id=rid, title=title, citation=citation, summary=summary, url=url, effective_from=effective_from
    )
    for rid, title, citation, summary, url, effective_from in _RULES
}


def list_rules() -> list[RuleInfo]:
    """All rules in catalog order (for the "How dates are computed" screen and ``/api/rules``)."""
    return list(RULES.values())


def get_rule(rule_id: str) -> RuleInfo:
    """The rule with ``rule_id``; raises ``KeyError`` for unknown ids."""
    return RULES[rule_id]


def citation(rule_id: str) -> str:
    """Citation text for ``rule_id`` (e.g. ``"§ 193 BGB"``)."""
    return RULES[rule_id].citation
