"""A reading that came back incomplete, and the one to-do code files for it (SPEC § 8 stage 5).

The extraction schema requires only a letter's kind, title, summary and explanation, so a valid answer can
leave out everything a person acts on — a prompt injection's aim, or a model that half-obeys one. After
quote verification, code checks every reading against the letter's own **visible** text (``Page.text``, a
photo's transcript; never ``Page.hidden``), with two rules (:func:`reading_gap`; the first wins):

* ``empty`` — nothing a person could act on or file came back: no to-do, no sender, no letter date, no key
  fact, no reference, no contract, change or payment details, and no remedy;
* ``remedy_left_out`` — the letter explains how to object within a period (:func:`remedy_notices`) in words
  that speak of a remedy against *this* letter (:attr:`RemedyNotice.live`), its text shows an administrative
  act, and no to-do of the reading dates the objection (whatever its ``remedy`` field says). Never for a
  kind of letter whose deadline the law files itself (:data:`LAW_DATED_KINDS`) when the letter bears that
  kind out.

Either way the letter gets **one** to-do in slot :data:`CHECK_SLOT` (:func:`check_item`), always ``low`` and
"Please check" (:data:`~ordnung.ingest.verify.READING_INCOMPLETE`). Its date is never later than the letter
allows when the letter's own date is read (ADR 0015 lists the planted layouts that can defeat this):

* **the period** is the one of every period the notices state (and the sentence after each, when that one
  goes on about it) that ends first, counted from the letter's date; it is dated only when that is at least a
  week and at most a month (every domestic remedy period is: § 70/§ 74 VwGO, § 355 AO, § 47 FGO, § 84/§ 87
  SGG, § 67 OWiG, § 410 StPO, § 692 ZPO), and when no notice holds a period that can't be read or dated
  (Werktage, years) or that counts back from an event ("zwei Wochen vor …") — otherwise the to-do is filed
  without a date, to be found in the letter;
* **the start** is the earliest date the letter gives for itself (:func:`letter_date`): dates its words name
  as its own (a "Datum" label, a place and date in its header, the date line under the recipient's address,
  the reference line, "mit diesem Bescheid vom …", the decision its notice names right before "vom", the
  reading's date) set it — none when those are more than two weeks apart, none from one date alone long
  before the letter arrived, none after it arrived; other dates (another "…datum", a print date, a date
  alone, a continuation page's, a period's start the notice names) only lower it, never set it; an
  appointment's date never counts. Deemed delivery is added only when every notice
  counts from notification, by post (or the day after a portal download), never on formal service.
  Recomputed later, an earlier letter date or arrival still moves it earlier (:func:`start_variants`), never
  later;
* without a notice — or for an almost blank reading of a letter whose notices are all ruled out — it is an
  undated "Read this letter yourself".

A reading that does date the objection, but later than the period the letter's own notice gives (a planted
"extended" period, a start moved later), gets that period beside its own date (:func:`notice_rival`, counted
from the date the first page names as its own): the earlier is kept and the to-do is "Please check"
(:func:`~ordnung.ingest.plan.compute_item`).

Nothing here calls a model; the reading itself (its sender, date and remedy) stays as the model gave it.
"""

from __future__ import annotations

from ordnung.ingest.gaps.dropped_dates import _OPTION_ASKED as _OPTION_ASKED
from ordnung.ingest.gaps.dropped_dates import _W_QUESTION as _W_QUESTION
from ordnung.ingest.gaps.dropped_dates import DEADLINE_REACH as DEADLINE_REACH
from ordnung.ingest.gaps.dropped_dates import DEADLINE_TITLE as DEADLINE_TITLE
from ordnung.ingest.gaps.dropped_dates import _label_kind as _label_kind
from ordnung.ingest.gaps.dropped_dates import _noun_kind as _noun_kind
from ordnung.ingest.gaps.dropped_dates import _nouns_kind as _nouns_kind
from ordnung.ingest.gaps.dropped_dates import _offers_option as _offers_option
from ordnung.ingest.gaps.dropped_dates import deadline_items as deadline_items
from ordnung.ingest.gaps.dropped_dates import deadline_slots as deadline_slots
from ordnung.ingest.gaps.dropped_dates import deadline_warning as deadline_warning
from ordnung.ingest.gaps.reading import CHECK_SLOT as CHECK_SLOT
from ordnung.ingest.gaps.reading import DEADLINE_ACTION as DEADLINE_ACTION
from ordnung.ingest.gaps.reading import DEADLINE_CONSEQUENCE as DEADLINE_CONSEQUENCE
from ordnung.ingest.gaps.reading import DEADLINE_SLOT as DEADLINE_SLOT
from ordnung.ingest.gaps.reading import GAP_WARNING as GAP_WARNING
from ordnung.ingest.gaps.reading import KLAGE_ACTION as KLAGE_ACTION
from ordnung.ingest.gaps.reading import KLAGE_CONSEQUENCE as KLAGE_CONSEQUENCE
from ordnung.ingest.gaps.reading import KNOWN_ADDRESS as KNOWN_ADDRESS
from ordnung.ingest.gaps.reading import LAW_DATED_KINDS as LAW_DATED_KINDS
from ordnung.ingest.gaps.reading import LETTER_DATE_SPAN as LETTER_DATE_SPAN
from ordnung.ingest.gaps.reading import NOTICE_REACH as NOTICE_REACH
from ordnung.ingest.gaps.reading import PLACEHOLDER_ACTION as PLACEHOLDER_ACTION
from ordnung.ingest.gaps.reading import QUOTE_CAP as QUOTE_CAP
from ordnung.ingest.gaps.reading import Check as Check
from ordnung.ingest.gaps.reading import CheckKind as CheckKind
from ordnung.ingest.gaps.reading import Gap as Gap
from ordnung.ingest.gaps.reading import RemedyNotice as RemedyNotice
from ordnung.ingest.gaps.reading import _own_start as _own_start
from ordnung.ingest.gaps.reading import check_item as check_item
from ordnung.ingest.gaps.reading import check_reasons as check_reasons
from ordnung.ingest.gaps.reading import dates_the_objection as dates_the_objection
from ordnung.ingest.gaps.reading import envelope_start as envelope_start
from ordnung.ingest.gaps.reading import formally_served as formally_served
from ordnung.ingest.gaps.reading import gap_warning as gap_warning
from ordnung.ingest.gaps.reading import is_check_slot as is_check_slot
from ordnung.ingest.gaps.reading import letter_date as letter_date
from ordnung.ingest.gaps.reading import needs_check as needs_check
from ordnung.ingest.gaps.reading import notice_rival as notice_rival
from ordnung.ingest.gaps.reading import reading_gap as reading_gap
from ordnung.ingest.gaps.reading import remedy_notices as remedy_notices
from ordnung.ingest.gaps.reading import square_gap_warnings as square_gap_warnings
from ordnung.ingest.gaps.reading import start_variants as start_variants

__all__ = [
    "CHECK_SLOT",
    "DEADLINE_SLOT",
    "LAW_DATED_KINDS",
    "NOTICE_REACH",
    "Check",
    "CheckKind",
    "Gap",
    "RemedyNotice",
    "check_item",
    "check_reasons",
    "dates_the_objection",
    "deadline_items",
    "deadline_slots",
    "deadline_warning",
    "envelope_start",
    "formally_served",
    "gap_warning",
    "is_check_slot",
    "letter_date",
    "notice_rival",
    "reading_gap",
    "remedy_notices",
    "start_variants",
]
